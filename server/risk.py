"""
Risk manager — checked before every order submission.

Guards:
  1. Kill switch       — manual halt, blocks all auto-orders
  2. Daily loss limit  — halts if day P&L % exceeds threshold
  3. PDT guard         — blocks if day-trade count would exceed limit (accounts < $25k)
  4. Position sizing   — calculates qty from % of portfolio instead of fixed shares
"""
import logging
from dataclasses import dataclass

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


# ── Pre-order checks ──────────────────────────────────────────────────────────

def check_all(symbol: str, side: str, account: dict, day_trade_count: int):
    """
    Raises RiskViolation if any guard fails.
    Call this before every auto-order submission.

    account: dict from alpaca_client.get_account_summary()
    day_trade_count: int from Alpaca account.daytrade_count
    """
    settings = get_settings()

    # 1. Kill switch
    if settings["kill_switch"]:
        raise RiskViolation("kill switch is active — all auto-trading halted")

    # 2. Daily loss limit
    day_pl_pct = account.get("day_pl_pct", 0.0)
    max_loss = -abs(settings["max_daily_loss_pct"])
    if day_pl_pct <= max_loss:
        set_kill_switch(True)  # auto-engage kill switch
        raise RiskViolation(
            f"daily loss limit hit: {day_pl_pct:.2f}% ≤ {max_loss:.2f}% "
            f"— kill switch auto-engaged"
        )

    # 3. PDT guard (only applies to buys on accounts under $25k)
    if side == "buy":
        equity = account.get("equity", 0.0)
        if equity < PDT_EQUITY_THRESHOLD:
            max_dt = settings["max_day_trades"]
            if day_trade_count >= max_dt:
                raise RiskViolation(
                    f"PDT limit: {day_trade_count}/{max_dt} day trades used "
                    f"(equity ${equity:,.0f} < ${PDT_EQUITY_THRESHOLD:,.0f} threshold)"
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
        # buy up to position_size_pct % of portfolio value
        dollar_target = portfolio_value * settings["position_size_pct"] / 100.0
        qty = max(1.0, round(dollar_target / current_price, 4))

        # cap at max_position_pct
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
    equity = account.get("equity", 0.0)
    day_pl_pct = account.get("day_pl_pct", 0.0)
    pdt_applies = equity < PDT_EQUITY_THRESHOLD

    warnings = []
    if settings["kill_switch"]:
        warnings.append("Kill switch is ACTIVE — no auto-trading")
    if pdt_applies and day_trade_count >= settings["max_day_trades"] - 1:
        remaining = max(0, settings["max_day_trades"] - day_trade_count)
        warnings.append(f"PDT: {remaining} day trade(s) remaining today")
    if day_pl_pct < -abs(settings["max_daily_loss_pct"]) * 0.75:
        warnings.append(f"Approaching daily loss limit ({day_pl_pct:.2f}%)")

    return {
        "kill_switch": settings["kill_switch"],
        "day_pl_pct": day_pl_pct,
        "max_daily_loss_pct": settings["max_daily_loss_pct"],
        "daily_loss_ok": day_pl_pct > -abs(settings["max_daily_loss_pct"]),
        "pdt_applies": pdt_applies,
        "day_trade_count": day_trade_count,
        "max_day_trades": settings["max_day_trades"],
        "pdt_ok": not pdt_applies or day_trade_count < settings["max_day_trades"],
        "position_size_mode": settings["position_size_mode"],
        "position_size_pct": settings["position_size_pct"],
        "max_position_pct": settings["max_position_pct"],
        "warnings": warnings,
        "settings": settings,
    }
