"""Strategy engine: periodically evaluates enabled strategies and submits orders."""
import logging
import threading
import uuid
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import ai_explainer, ai_tuner, alpaca_client, crypto, db, notifications, risk, strategies
from .broker_factory import get_account_client

log = logging.getLogger("engine")
log.setLevel(logging.INFO)

_scheduler: AsyncIOScheduler | None = None
_tuner_timer: threading.Timer | None = None
_last_run: dict = {"ts": None, "ran": [], "signals": [], "error": None, "risk": None}



def _run_take_profit_pass(acct_client, acct_id: int, take_profit_pct: float,
                          local_positions: dict) -> None:
    """Sell any position whose unrealized gain >= take_profit_pct. Skips kill switch and risk checks."""
    if take_profit_pct <= 0:
        return
    try:
        live_positions = acct_client.get_positions()
    except Exception as e:
        log.warning("take-profit: get_positions failed for acct %d: %s", acct_id, e)
        return

    for p in live_positions:
        if p.get("side", "long") != "long":
            continue
        plpc = p.get("unrealized_plpc", 0.0)
        if plpc < take_profit_pct:
            continue
        symbol = p["symbol"]
        qty = p.get("qty", 0.0)
        if qty <= 0:
            continue
        reason = f"take-profit: {plpc:.2f}% >= {take_profit_pct:.2f}%"
        log.info("take-profit triggered %s acct %d (%.2f%% gain)", symbol, acct_id, plpc)
        try:
            import uuid
            client_oid = f"tp-{uuid.uuid4().hex[:12]}"
            order = acct_client.submit_market_order(
                symbol, "sell", qty=qty, client_order_id=client_oid
            )
            db.log_signal("take_profit", symbol, "sell", qty, reason,
                          order["id"], order["status"], account_id=acct_id)
            notifications.notify_trade(
                "take_profit", symbol, "sell", qty, None, reason, order["id"]
            )
            local_positions.pop(symbol, None)
        except Exception as e:
            log.exception("take-profit order failed for %s acct %d", symbol, acct_id)
            db.log_signal("take_profit", symbol, "sell", qty,
                          f"{reason} | submit error: {e}", None, "error", account_id=acct_id)


def run_tick():
    """Run all enabled strategies across all assigned broker accounts."""
    global _last_run
    from datetime import datetime, timezone
    _last_run = {"ts": datetime.now(timezone.utc).isoformat(),
                 "ran": [], "signals": [], "error": None, "risk": None}

    active_mode = db.get_risk_settings().get("trading_mode", "paper")

    # Fetch US market clock once — used to gate stock brokers only.
    # Crypto brokers (Binance) trade 24/7 and bypass this gate.
    _us_market_open: bool | None = None
    def is_us_market_open() -> bool:
        nonlocal _us_market_open
        if _us_market_open is None:
            try:
                _us_market_open = alpaca_client.get_clock()["is_open"]
            except Exception:
                _us_market_open = False
        return _us_market_open

    CRYPTO_BROKERS = {"binance"}

    if risk.is_killed():
        _last_run["error"] = "kill switch active"
        log.warning("kill switch active; skipping tick")
        return

    # Per-account cache: one entry per account_id per tick.
    # Stored as mutable dict so dtc and positions can be updated after each order.
    # Structure: {"client": AccountClient, "account": dict, "dtc": int, "positions": dict[str, float]}
    client_cache: dict[int, dict] = {}

    from datetime import datetime, timezone
    now_et = datetime.now(timezone.utc).astimezone(
        __import__("zoneinfo", fromlist=["ZoneInfo"]).ZoneInfo("America/New_York")
    )
    now_time = now_et.strftime("%H:%M")

    for s in db.get_strategies():
        if not s["enabled"]:
            continue
        if s["name"] not in strategies.REGISTRY:
            continue
        cls = strategies.REGISTRY[s["name"]]
        if not cls.auto_trade:
            continue
        # Per-strategy time window check (ET)
        if s.get("active_start") and s.get("active_end"):
            if not (s["active_start"] <= now_time <= s["active_end"]):
                log.debug("strategy %s skipped — outside window %s–%s (now %s ET)",
                          s["name"], s["active_start"], s["active_end"], now_time)
                _last_run["ran"].append({"strategy": s["name"], "skipped": "window"})
                continue

        accounts = db.get_strategy_accounts(s["name"])
        if not accounts:
            _last_run["ran"].append({"strategy": s["name"], "skipped": "no_accounts"})
            continue

        # Track whether any account actually ran for this strategy this tick.
        _strategy_ran = False
        _skip_reasons = set()
        _init_failed = False

        for acct in accounts:
            if acct["account_type"] != active_mode:
                _skip_reasons.add("mode_mismatch")
                continue
            acct_id = acct["id"]
            broker  = (acct.get("broker") or "alpaca").lower()

            # Stock brokers only trade during US market hours.
            # Crypto brokers (Binance) run 24/7 — skip the clock gate.
            if broker not in CRYPTO_BROKERS and not is_us_market_open():
                log.info("market closed; skipping acct %d (%s)", acct_id, broker)
                _skip_reasons.add("market_closed")
                continue

            if acct_id not in client_cache:
                try:
                    acct_client = get_account_client(
                        broker=acct.get("broker", "alpaca"),
                        api_key=crypto.decrypt(acct["api_key"]),
                        api_secret=crypto.decrypt(acct["api_secret"]),
                        paper=(acct["account_type"] == "paper"),
                        account_id=acct_id,
                    )
                    acct_summary = acct_client.get_account_summary()
                    acct_dtc = acct_client.get_day_trade_count()
                    raw_positions = acct_client.get_positions()
                    # For Binance, positions use bare tickers (e.g. "ETH") but crypto
                    # strategies use slash pairs (e.g. "ETH/USDT"). Normalise to match.
                    # Also filter out dust (< $1 market value) so strategies don't
                    # treat tiny leftover fractions as real holdings.
                    def _pos_key(sym: str) -> str:
                        if broker in CRYPTO_BROKERS and "/" not in sym:
                            return sym + "/USDT"
                        return sym
                    _dust_threshold = 1.0 if broker in CRYPTO_BROKERS else 0.0
                    acct_positions = {
                        _pos_key(p["symbol"]): (p["qty"] if p["side"] == "long" else -p["qty"])
                        for p in raw_positions
                        if p.get("market_value", 0) >= _dust_threshold
                    }
                    acct_market_values = {
                        _pos_key(p["symbol"]): p["market_value"]
                        for p in raw_positions
                        if p.get("market_value", 0) >= _dust_threshold
                    }
                except Exception as e:
                    log.warning("acct %d init failed: %s", acct_id, e)
                    _init_failed = True
                    _skip_reasons.add("init_error")
                    continue
                client_cache[acct_id] = {
                    "client": acct_client,
                    "account": acct_summary,
                    "dtc": acct_dtc,
                    "positions": acct_positions,
                    "market_values": acct_market_values,
                }

            acct_data = client_cache[acct_id]
            acct_client = acct_data["client"]
            account = acct_data["account"]
            day_trade_count = acct_data["dtc"]
            positions = acct_data["positions"]

            try:
                strat = strategies.build(s["name"], s["params"])
                signals = strat.evaluate(positions, client=acct_client)
            except Exception as e:
                log.exception("strategy %s acct %d failed", s["name"], acct_id)
                db.log_signal(s["name"], "-", "-", 0, f"error: {e}", None, "error")
                _last_run["ran"].append({"strategy": s["name"], "error": str(e)})
                _strategy_ran = True
                continue

            _last_run["ran"].append({"strategy": s["name"], "signals": len(signals)})
            _strategy_ran = True

            for sig in signals:
                # ── risk check ──────────────────────────────────────────────
                try:
                    risk.check_all(
                        sig.symbol, sig.side, account, acct_data["dtc"],
                        open_positions_count=len(acct_data["positions"]),
                        current_symbol_value=acct_data["market_values"].get(sig.symbol, 0.0),
                        account_id=acct_id,
                        broker=broker,
                    )
                except risk.RiskViolation as rv:
                    reason = f"RISK BLOCK: {rv}"
                    log.warning("%s %s blocked — %s", sig.side, sig.symbol, rv)
                    db.log_signal(s["name"], sig.symbol, sig.side, sig.qty,
                                  reason, None, "blocked", blocked=True, account_id=acct_id)
                    _last_run["signals"].append({
                        "strategy": s["name"], "symbol": sig.symbol,
                        "side": sig.side, "qty": sig.qty,
                        "reason": reason, "order_id": None, "blocked": True,
                    })
                    notifications.notify_risk_block(sig.symbol, sig.side, str(rv))
                    continue

                # ── position sizing ─────────────────────────────────────────
                price = None
                if sig.notional:
                    final_qty = None
                else:
                    try:
                        quote = acct_client.get_latest_quote(sig.symbol)
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
                    # Capture filled qty/price from order response for crypto P&L tracking
                    ord_filled_qty   = float(order.get("qty") or 0) or None
                    ord_filled_price = float(order.get("filled_avg_price") or price or 0) or None
                    sig_id = db.log_signal(s["name"], sig.symbol, sig.side, display_qty,
                                           sig.reason, order["id"], order["status"],
                                           account_id=acct_id,
                                           filled_qty=ord_filled_qty,
                                           filled_price=ord_filled_price)
                    try:
                        ai_explainer.enqueue({
                            "id": sig_id,
                            "ts": db.now_iso(),
                            "strategy": s["name"],
                            "symbol": sig.symbol,
                            "side": sig.side,
                            "reason": sig.reason,
                        })
                    except Exception:
                        pass
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
                    delta_qty = (final_qty or 0) if sig.side == "buy" else -(final_qty or 0)
                    acct_data["positions"][sig.symbol] = (
                        acct_data["positions"].get(sig.symbol, 0.0) + delta_qty
                    )
                    value_delta = sig.notional if sig.notional else (final_qty or 0) * (price or 0)
                    if sig.side == "sell":
                        value_delta = -value_delta
                    acct_data["market_values"][sig.symbol] = (
                        acct_data["market_values"].get(sig.symbol, 0.0) + value_delta
                    )
                except Exception as e:
                    log.exception("order submit failed for %s %s %s",
                                  sig.symbol, sig.side, final_qty)
                    db.increment_consecutive_losses()
                    db.log_signal(s["name"], sig.symbol, sig.side, final_qty,
                                  f"{sig.reason} | submit error: {e}", None, "error",
                                  account_id=acct_id)

        # If no account ran, record why so the UI shows the right badge.
        if not _strategy_ran:
            if "init_error" in _skip_reasons:
                skip_reason = "init_error"
            elif "market_closed" in _skip_reasons:
                skip_reason = "market_closed"
            elif "mode_mismatch" in _skip_reasons:
                skip_reason = "mode_mismatch"
            else:
                skip_reason = "market_closed"
            _last_run["ran"].append({"strategy": s["name"], "skipped": skip_reason})

    # ── Take-profit pass ────────────────────────────────────────────────────
    tp_pct = db.get_risk_settings().get("take_profit_pct", 0.0)
    for acct_id, acct_data in client_cache.items():
        _run_take_profit_pass(
            acct_data["client"], acct_id, tp_pct, acct_data["positions"]
        )

    # Check price alerts using quotes fetched during this tick
    try:
        symbols = list({
            sig.symbol
            for s in db.get_strategies() if s["enabled"]
            for acct in db.get_strategy_accounts(s["name"])
            for sig in []  # placeholder — use known active symbols from cache
        })
        quote_prices = {}
        for acct_data in client_cache.values():
            acct_client_q = acct_data["client"]
            for sym in list(acct_data.get("positions", {}).keys()):
                if sym not in quote_prices:
                    try:
                        q = acct_client_q.get_latest_quote(sym)
                        mid = (q["bid"] + q["ask"]) / 2 if q["bid"] and q["ask"] else q["bid"] or q["ask"]
                        if mid:
                            quote_prices[sym] = mid
                    except Exception:
                        pass
        if quote_prices:
            check_price_alerts(quote_prices)
    except Exception as e:
        log.warning("price alert check failed: %s", e)


def check_price_alerts(prices: dict) -> None:
    """Check open price alerts against current prices and fire notifications on trigger."""
    alerts = db.list_price_alerts(include_triggered=False)
    for alert in alerts:
        symbol = alert["symbol"]
        price  = prices.get(symbol)
        if price is None:
            continue
        target = float(alert["target_price"])
        fired  = False
        if alert["direction"] == "above" and price >= target:
            fired = True
        elif alert["direction"] == "below" and price <= target:
            fired = True
        if fired:
            db.trigger_price_alert(alert["id"])
            notifications.notify_price_alert(symbol, alert["direction"], target, price)


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
    ai_explainer.start()       # start the explanation daemon
    _schedule_weekly_tuner()   # schedule weekly tuning
    log.info("engine started, tick every %ss", interval_seconds)


def shutdown():
    global _scheduler, _tuner_timer
    if _tuner_timer:
        _tuner_timer.cancel()
        _tuner_timer = None
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def _schedule_weekly_tuner():
    """Fire ai_tuner.run_tuning() every Sunday at 11 PM ET, then reschedule."""
    global _tuner_timer
    import zoneinfo
    from datetime import datetime, timedelta, timezone
    now_et = datetime.now(timezone.utc).astimezone(zoneinfo.ZoneInfo("America/New_York"))
    # Find next Sunday 23:00 ET
    days_until_sunday = (6 - now_et.weekday()) % 7  # Monday=0, Sunday=6
    if days_until_sunday == 0 and now_et.hour >= 23:
        days_until_sunday = 7  # already past 11pm Sunday — wait for next week
    next_run = now_et.replace(hour=23, minute=0, second=0, microsecond=0) + timedelta(days=days_until_sunday)
    delay_s = (next_run - now_et).total_seconds()
    log.info("Weekly tuner scheduled in %.0f seconds (next Sunday 11pm ET)", delay_s)

    def _fire():
        try:
            result = ai_tuner.run_tuning()
            log.info("Weekly tuner complete: %s", result)
        except Exception:
            log.exception("Weekly tuner failed")
        _schedule_weekly_tuner()  # reschedule for next week

    _tuner_timer = threading.Timer(delay_s, _fire)
    _tuner_timer.daemon = True
    _tuner_timer.start()
