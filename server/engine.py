"""Strategy engine: periodically evaluates enabled strategies and submits orders."""
import logging
import uuid
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import alpaca_client, db, notifications, risk, strategies

log = logging.getLogger("engine")
log.setLevel(logging.INFO)

_scheduler: AsyncIOScheduler | None = None
_last_run: dict = {"ts": None, "ran": [], "signals": [], "error": None, "risk": None}


def _current_positions() -> dict[str, float]:
    out: dict[str, float] = {}
    for p in alpaca_client.get_positions():
        qty = p["qty"] if p["side"] == "long" else -p["qty"]
        out[p["symbol"]] = qty
    return out


def _get_day_trade_count(account_raw) -> int:
    """Pull daytrade_count directly from Alpaca account object."""
    try:
        from alpaca.trading.client import TradingClient
        tc = alpaca_client.trading()
        a = tc.get_account()
        return int(a.daytrade_count or 0)
    except Exception:
        return 0


def run_tick():
    """Run all enabled strategies once. Submits orders for any signals."""
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

    if not clock["is_open"]:
        _last_run["error"] = "market closed"
        log.info("market closed; skipping strategy tick")
        return

    # fetch account + risk status once per tick
    try:
        account = alpaca_client.get_account_summary()
        day_trade_count = _get_day_trade_count(account)
        risk_status = risk.status_summary(account, day_trade_count)
        _last_run["risk"] = risk_status
    except Exception as e:
        _last_run["error"] = f"account: {e}"
        log.exception("account fetch failed")
        return

    # hard stop if kill switch is on
    if risk_status["kill_switch"]:
        _last_run["error"] = "kill switch active"
        log.warning("kill switch active; skipping tick")
        return

    try:
        positions = _current_positions()
    except Exception as e:
        _last_run["error"] = f"positions: {e}"
        log.exception("positions fetch failed")
        return

    for s in db.get_strategies():
        if not s["enabled"]:
            continue
        if s["name"] not in strategies.REGISTRY:
            continue
        cls = strategies.REGISTRY[s["name"]]
        if not cls.auto_trade:
            continue
        try:
            strat = strategies.build(s["name"], s["params"])
            signals = strat.evaluate(positions)
        except Exception as e:
            log.exception("strategy %s failed", s["name"])
            db.log_signal(s["name"], "-", "-", 0, f"error: {e}", None, "error")
            _last_run["ran"].append({"strategy": s["name"], "error": str(e)})
            continue

        _last_run["ran"].append({"strategy": s["name"], "signals": len(signals)})

        for sig in signals:
            # ── risk check ────────────────────────────────────────────────────
            try:
                risk.check_all(sig.symbol, sig.side, account, day_trade_count)
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

            # ── position sizing ───────────────────────────────────────────────
            # if signal already carries a notional (USD), skip qty sizing
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

            # ── submit ────────────────────────────────────────────────────────
            client_oid = f"{s['name']}-{uuid.uuid4().hex[:12]}"
            try:
                order = alpaca_client.submit_market_order(
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
                _last_run["signals"].append({
                    "strategy": s["name"], "symbol": sig.symbol, "side": sig.side,
                    "qty": final_qty, "reason": sig.reason, "order_id": order["id"],
                })
                # increment day trade count if this is a closing buy/sell
                if sig.side == "sell":
                    day_trade_count += 1
                # update local positions view
                delta = final_qty if sig.side == "buy" else -final_qty
                positions[sig.symbol] = positions.get(sig.symbol, 0.0) + delta
            except Exception as e:
                log.exception("order submit failed for %s %s %s",
                              sig.symbol, sig.side, final_qty)
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
