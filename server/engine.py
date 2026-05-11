"""Strategy engine: periodically evaluates enabled strategies and submits orders."""
import logging
import uuid
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import alpaca_client, crypto, db, notifications, risk, strategies
from .alpaca_client import AccountClient

log = logging.getLogger("engine")
log.setLevel(logging.INFO)

_scheduler: AsyncIOScheduler | None = None
_last_run: dict = {"ts": None, "ran": [], "signals": [], "error": None, "risk": None}



def run_tick():
    """Run all enabled strategies across all assigned broker accounts."""
    global _last_run
    from datetime import datetime, timezone
    _last_run = {"ts": datetime.now(timezone.utc).isoformat(),
                 "ran": [], "signals": [], "error": None, "risk": None}

    try:
        clock = alpaca_client.get_clock()
    except Exception as e:
        _last_run["error"] = f"clock: {e}"
        log.exception("clock fetch failed")
        return

    active_mode = db.get_risk_settings().get("trading_mode", "paper")

    if not clock["is_open"]:
        _last_run["error"] = "market closed"
        log.info("market closed; skipping strategy tick")
        return

    if risk.is_killed():
        _last_run["error"] = "kill switch active"
        log.warning("kill switch active; skipping tick")
        return

    # Per-account cache: one entry per account_id per tick.
    # Stored as mutable dict so dtc and positions can be updated after each order.
    # Structure: {"client": AccountClient, "account": dict, "dtc": int, "positions": dict[str, float]}
    client_cache: dict[int, dict] = {}

    for s in db.get_strategies():
        if not s["enabled"]:
            continue
        if s["name"] not in strategies.REGISTRY:
            continue
        cls = strategies.REGISTRY[s["name"]]
        if not cls.auto_trade:
            continue

        accounts = db.get_strategy_accounts(s["name"])
        if not accounts:
            continue

        for acct in accounts:
            if acct["account_type"] != active_mode:
                continue
            acct_id = acct["id"]

            if acct_id not in client_cache:
                try:
                    acct_client = AccountClient(
                        api_key=crypto.decrypt(acct["api_key"]),
                        api_secret=crypto.decrypt(acct["api_secret"]),
                        paper=(acct["account_type"] == "paper"),
                    )
                    acct_summary = acct_client.get_account_summary()
                    acct_dtc = acct_client.get_day_trade_count()
                    acct_positions = {
                        p["symbol"]: (p["qty"] if p["side"] == "long" else -p["qty"])
                        for p in acct_client.get_positions()
                    }
                except Exception as e:
                    log.warning("acct %d init failed: %s", acct_id, e)
                    continue
                client_cache[acct_id] = {
                    "client": acct_client,
                    "account": acct_summary,
                    "dtc": acct_dtc,
                    "positions": acct_positions,
                }

            acct_data = client_cache[acct_id]
            acct_client = acct_data["client"]
            account = acct_data["account"]
            day_trade_count = acct_data["dtc"]
            positions = acct_data["positions"]

            try:
                strat = strategies.build(s["name"], s["params"])
                signals = strat.evaluate(positions)
            except Exception as e:
                log.exception("strategy %s acct %d failed", s["name"], acct_id)
                db.log_signal(s["name"], "-", "-", 0, f"error: {e}", None, "error")
                _last_run["ran"].append({"strategy": s["name"], "error": str(e)})
                continue

            _last_run["ran"].append({"strategy": s["name"], "signals": len(signals)})

            for sig in signals:
                # ── risk check ──────────────────────────────────────────────
                try:
                    risk.check_all(
                        sig.symbol, sig.side, account, acct_data["dtc"],
                        open_positions_count=len(acct_data["positions"]),
                        current_symbol_qty=abs(acct_data["positions"].get(sig.symbol, 0.0)),
                    )
                except risk.RiskViolation as rv:
                    reason = f"RISK BLOCK: {rv}"
                    log.warning("%s %s blocked — %s", sig.side, sig.symbol, rv)
                    db.log_signal(s["name"], sig.symbol, sig.side, sig.qty,
                                  reason, None, "blocked")
                    _last_run["signals"].append({
                        "strategy": s["name"], "symbol": sig.symbol,
                        "side": sig.side, "qty": sig.qty,
                        "reason": reason, "order_id": None, "blocked": True,
                    })
                    notifications.notify_risk_block(sig.symbol, sig.side, str(rv))
                    continue

                # ── position sizing ─────────────────────────────────────────
                if sig.notional:
                    final_qty = None
                else:
                    try:
                        quote = alpaca_client.get_latest_quote(sig.symbol)
                        price = (quote["bid"] + quote["ask"]) / 2
                    except Exception:
                        price = None
                    final_qty = risk.calc_qty(
                        sig.symbol, sig.side, sig.qty, account, price
                    )

                # ── zero-qty guard ──────────────────────────────────────────
                if not sig.notional and (final_qty is None or final_qty <= 0):
                    db.log_signal(s["name"], sig.symbol, sig.side, final_qty,
                                  "blocked: zero or negative qty after sizing", None, "blocked")
                    continue

                # ── submit ──────────────────────────────────────────────────
                client_oid = f"{s['name']}-{uuid.uuid4().hex[:12]}"
                try:
                    order = acct_client.submit_market_order(
                        sig.symbol, sig.side,
                        qty=final_qty if not sig.notional else None,
                        notional=sig.notional,
                        client_order_id=client_oid,
                    )
                    display_qty = final_qty if not sig.notional else sig.notional
                    db.log_signal(s["name"], sig.symbol, sig.side, display_qty,
                                  sig.reason, order["id"], order["status"])
                    notifications.notify_trade(
                        s["name"], sig.symbol, sig.side,
                        final_qty, sig.notional, sig.reason, order["id"]
                    )
                    db.reset_consecutive_losses()
                    _last_run["signals"].append({
                        "strategy": s["name"], "symbol": sig.symbol, "side": sig.side,
                        "qty": final_qty, "reason": sig.reason, "order_id": order["id"],
                    })
                    if sig.side == "sell":
                        acct_data["dtc"] += 1
                    delta = (final_qty or 0) if sig.side == "buy" else -(final_qty or 0)
                    acct_data["positions"][sig.symbol] = (
                        acct_data["positions"].get(sig.symbol, 0.0) + delta
                    )
                except Exception as e:
                    log.exception("order submit failed for %s %s %s",
                                  sig.symbol, sig.side, final_qty)
                    db.increment_consecutive_losses()
                    db.log_signal(s["name"], sig.symbol, sig.side, final_qty,
                                  f"{sig.reason} | submit error: {e}", None, "error")


def last_run() -> dict:
    return _last_run


def start(interval_seconds: int = 60):
    global _scheduler
    if _scheduler:
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(run_tick, IntervalTrigger(seconds=interval_seconds),
                       id="tick", max_instances=1, coalesce=True)
    _scheduler.start()
    log.info("engine started, tick every %ss", interval_seconds)


def shutdown():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
