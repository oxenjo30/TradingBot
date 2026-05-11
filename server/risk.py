"""
Risk manager — checked before every order submission.

Guards:
  1. Kill switch            — manual halt, blocks all auto-orders
  2. Symbol blacklist       — never trade specific tickers
  3. Trading hours          — only allow orders within ET window
  4. Daily loss limit       — halts (auto kill switch) if day P&L % exceeds threshold
  5. Weekly loss limit      — halts if week P&L % exceeds threshold
  6. PDT guard              — blocks if day-trade count would exceed limit (< $25k accounts)
  7. Max open positions     — cap simultaneous open positions (buy side only)
  8. Max symbol exposure    — cap single-ticker portfolio % (buy side only)
  9. Max orders per day     — cap total filled orders per calendar day
 10. Consecutive loss limit — circuit-breaker after N consecutive order failures
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from . import db

log = logging.getLogger("risk")

PDT_EQUITY_THRESHOLD = 25_000.0


@dataclass
class RiskViolation(Exception):
    reason: str

    def __str__(self):
        return self.reason


def get_settings() -> dict:
    return db.get_risk_settings()


# ── Kill switch ────────────────────────────────────────────────────────────────

def is_killed() -> bool:
    return db.get_risk_settings()["kill_switch"]


def set_kill_switch(on: bool):
    db.set_risk_setting("kill_switch", "true" if on else "false")
    log.warning("kill switch %s", "ACTIVATED" if on else "deactivated")


# ── Weekly P&L helper ─────────────────────────────────────────────────────────

def _get_weekly_pl_pct(account: dict) -> float:
    """
    Returns week-to-date P&L % vs equity at Monday open.
    Snapshots the baseline on first call of each week.
    """
    equity = account.get("equity", 0.0)
    if equity <= 0:
        return 0.0

    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    monday_str = monday.isoformat()

    stored_date = db.get_app_config("week_start_date", "")
    stored_eq_s = db.get_app_config("week_start_equity", "0")
    try:
        stored_eq = float(stored_eq_s)
    except ValueError:
        stored_eq = 0.0

    if stored_date != monday_str or stored_eq <= 0:
        db.set_app_config("week_start_date", monday_str)
        db.set_app_config("week_start_equity", str(equity))
        return 0.0

    return (equity - stored_eq) / stored_eq * 100.0


# ── Pre-order checks ──────────────────────────────────────────────────────────

def check_all(symbol: str, side: str, account: dict, day_trade_count: int,
              open_positions_count: int = 0, current_symbol_qty: float = 0.0):
    """
    Raises RiskViolation if any guard fails.
    Call before every auto-order submission.

    account              — dict from alpaca_client.get_account_summary()
    day_trade_count      — int from Alpaca account.daytrade_count
    open_positions_count — number of currently open positions
    current_symbol_qty   — current absolute position qty in this symbol
    """
    settings = get_settings()

    # 1. Kill switch
    if settings["kill_switch"]:
        raise RiskViolation("kill switch is active — all auto-trading halted")

    # 2. Symbol blacklist
    blacklist = db.get_symbol_blacklist()
    if symbol.upper() in blacklist:
        raise RiskViolation(f"{symbol} is on the no-trade blacklist")

    # 3. Trading hours guard (ET)
    start_str = settings.get("trading_hours_start", "")
    end_str   = settings.get("trading_hours_end", "")
    if start_str and end_str:
        try:
            from zoneinfo import ZoneInfo
            et_now = datetime.now(ZoneInfo("America/New_York")).time()
            sh, sm = map(int, start_str.split(":"))
            eh, em = map(int, end_str.split(":"))
            if not (time(sh, sm) <= et_now <= time(eh, em)):
                raise RiskViolation(
                    f"outside allowed trading hours ({start_str}–{end_str} ET)"
                )
        except RiskViolation:
            raise
        except Exception:
            pass  # malformed time setting — skip check

    # 4. Daily loss limit
    day_pl_pct = account.get("day_pl_pct", 0.0)
    max_loss = -abs(settings["max_daily_loss_pct"])
    if day_pl_pct <= max_loss:
        set_kill_switch(True)
        raise RiskViolation(
            f"daily loss limit hit: {day_pl_pct:.2f}% ≤ {max_loss:.2f}% "
            f"— kill switch auto-engaged"
        )

    # 5. Weekly loss limit
    weekly_limit = settings.get("weekly_loss_limit_pct", 0.0)
    if weekly_limit > 0:
        week_pl_pct = _get_weekly_pl_pct(account)
        if week_pl_pct <= -abs(weekly_limit):
            set_kill_switch(True)
            raise RiskViolation(
                f"weekly loss limit hit: {week_pl_pct:.2f}% ≤ -{weekly_limit:.2f}% "
                f"— kill switch auto-engaged"
            )

    # 6. PDT guard (buy side only, accounts < $25k)
    if side == "buy":
        equity = account.get("equity", 0.0)
        if equity < PDT_EQUITY_THRESHOLD:
            max_dt = settings["max_day_trades"]
            if day_trade_count >= max_dt:
                raise RiskViolation(
                    f"PDT limit: {day_trade_count}/{max_dt} day trades used "
                    f"(equity ${equity:,.0f} < ${PDT_EQUITY_THRESHOLD:,.0f} threshold)"
                )

    # 7. Max open positions (buy side only)
    max_pos = settings.get("max_open_positions", 0)
    if side == "buy" and max_pos > 0 and open_positions_count >= max_pos:
        raise RiskViolation(
            f"max open positions reached: {open_positions_count}/{max_pos}"
        )

    # 8. Max symbol exposure (buy side only)
    max_sym_exp = settings.get("max_symbol_exposure_pct", 0.0)
    if side == "buy" and max_sym_exp > 0 and current_symbol_qty > 0:
        portfolio_value = account.get("portfolio_value", 0.0)
        if portfolio_value > 0:
            sym_exposure_pct = (current_symbol_qty / portfolio_value) * 100.0
            if sym_exposure_pct >= max_sym_exp:
                raise RiskViolation(
                    f"{symbol} exposure {sym_exposure_pct:.1f}% exceeds max {max_sym_exp:.1f}%"
                )

    # 9. Max orders per day
    max_ord = settings.get("max_orders_per_day", 0)
    if max_ord > 0:
        today_count = db.count_signals_today()
        if today_count >= max_ord:
            raise RiskViolation(
                f"max orders per day reached: {today_count}/{max_ord}"
            )

    # 10. Consecutive loss limit
    consec_limit = settings.get("consecutive_loss_limit", 0)
    if consec_limit > 0:
        consec = db.get_consecutive_losses()
        if consec >= consec_limit:
            raise RiskViolation(
                f"consecutive failure limit reached: {consec}/{consec_limit} — "
                f"manual reset required"
            )


# ── Position sizing ───────────────────────────────────────────────────────────

def calc_qty(symbol: str, side: str, fixed_qty: float,
             account: dict, current_price: float | None) -> float:
    """
    Returns the qty to trade after applying position sizing rules.
    Falls back to fixed_qty if price is unavailable or mode is 'fixed'.
    """
    settings = get_settings()
    mode = settings["position_size_mode"]

    if mode == "fixed" or current_price is None or current_price <= 0:
        return fixed_qty

    portfolio_value = account.get("portfolio_value", 0.0)
    if portfolio_value <= 0:
        return fixed_qty

    if mode == "pct_portfolio":
        dollar_target = portfolio_value * settings["position_size_pct"] / 100.0
        qty = max(1.0, round(dollar_target / current_price, 4))

        max_dollars = portfolio_value * settings["max_position_pct"] / 100.0
        max_qty = max(1.0, round(max_dollars / current_price, 4))
        qty = min(qty, max_qty)

        log.info(
            "%s size: pct_portfolio %.1f%% of $%.0f → %.4f shares @ $%.2f",
            symbol, settings["position_size_pct"], portfolio_value, qty, current_price,
        )
        return qty

    return fixed_qty


# ── Status summary ────────────────────────────────────────────────────────────

def status_summary(account: dict, day_trade_count: int) -> dict:
    settings = get_settings()
    equity      = account.get("equity", 0.0)
    day_pl_pct  = account.get("day_pl_pct", 0.0)
    pdt_applies = equity < PDT_EQUITY_THRESHOLD

    # Weekly P&L
    week_pl_pct   = _get_weekly_pl_pct(account)
    weekly_limit  = settings.get("weekly_loss_limit_pct", 0.0)
    weekly_loss_ok = weekly_limit <= 0 or week_pl_pct > -abs(weekly_limit)

    # Orders today
    orders_today      = db.count_signals_today()
    max_orders        = settings.get("max_orders_per_day", 0)
    orders_today_ok   = max_orders <= 0 or orders_today < max_orders

    # Consecutive losses
    consec_losses      = db.get_consecutive_losses()
    consec_limit       = settings.get("consecutive_loss_limit", 0)
    consec_ok          = consec_limit <= 0 or consec_losses < consec_limit

    warnings = []
    if settings["kill_switch"]:
        warnings.append("Kill switch is ACTIVE — no auto-trading")
    if pdt_applies and day_trade_count >= settings["max_day_trades"] - 1:
        remaining = max(0, settings["max_day_trades"] - day_trade_count)
        warnings.append(f"PDT: {remaining} day trade(s) remaining today")
    if day_pl_pct < -abs(settings["max_daily_loss_pct"]) * 0.75:
        warnings.append(f"Approaching daily loss limit ({day_pl_pct:.2f}%)")
    if weekly_limit > 0 and week_pl_pct < -abs(weekly_limit) * 0.75:
        warnings.append(f"Approaching weekly loss limit ({week_pl_pct:.2f}%)")
    if not consec_ok:
        warnings.append(f"Consecutive failure limit reached ({consec_losses}/{consec_limit}) — reset required")
    if not orders_today_ok:
        warnings.append(f"Daily order cap reached ({orders_today}/{max_orders})")

    return {
        # Existing fields
        "kill_switch":         settings["kill_switch"],
        "day_pl_pct":          day_pl_pct,
        "max_daily_loss_pct":  settings["max_daily_loss_pct"],
        "daily_loss_ok":       day_pl_pct > -abs(settings["max_daily_loss_pct"]),
        "pdt_applies":         pdt_applies,
        "day_trade_count":     day_trade_count,
        "max_day_trades":      settings["max_day_trades"],
        "pdt_ok":              not pdt_applies or day_trade_count < settings["max_day_trades"],
        "position_size_mode":  settings["position_size_mode"],
        "position_size_pct":   settings["position_size_pct"],
        "max_position_pct":    settings["max_position_pct"],
        "warnings":            warnings,
        "settings":            settings,
        # New fields
        "week_pl_pct":         week_pl_pct,
        "weekly_loss_ok":      weekly_loss_ok,
        "orders_today":        orders_today,
        "orders_today_ok":     orders_today_ok,
        "consecutive_losses":  consec_losses,
        "consecutive_ok":      consec_ok,
        "blacklist":           db.get_symbol_blacklist(),
    }
