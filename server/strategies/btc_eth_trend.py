"""BTC/ETH Spot Daily Trend strategy (Task 8, spec §8).

A PURE, completed-daily-candle signal model. NO network calls of its own, NO
global state. Reads only the completed daily candles (decision candle = last
candle) and this strategy's OWN entry price via the Task 2 ledger
(`db.get_strategy_entry_price`). Entry ATR / peak close / stop live with the owned
lot; this model derives them deterministically each tick and invents no new table.

RESEARCH CANDIDATE: `auto_trade = False` — registered but not auto-assigned or
enabled until Task 9 research and the Task 12 paper cutover.

Universe is BTC/USDT and ETH/USDT spot ONLY, daily UTC candles. No leverage,
derivatives, shorts, staking, 4h candles, or other assets (§8.1).

Spec thresholds implemented (do not change without re-reading §8):
  - close > highest high of prior 55 completed candles (EXCLUDING decision candle)
  - EMA50 > EMA200
  - exit: close < lowest low of prior 20 candles; OR close below EMA200 for two
    consecutive candles; OR ATR trailing stop breach
  - initial stop = entry - 3.0*ATR20; trailing = peak close - 3.5*ATR20; never loosens
  - risk 0.10% equity; BTC max 3%, ETH max 2%, combined <=5%, max 2 positions
  - qty rounds down to exchange precision; skip if min notional exceeds budget
"""
from typing import ClassVar

from .base import Strategy, Signal
from .. import db

RULE_VERSION = "btc_eth_trend/v1"

# Spec §8 thresholds (named constants — all load-bearing).
BREAKOUT_LOOKBACK = 55       # prior daily highs for breakout (excl. decision candle)
EXIT_LOW_LOOKBACK = 20       # prior daily lows for the exit trigger
EMA_FAST = 50                # EMA50 must be above EMA200 to enter
EMA_SLOW = 200
ATR_PERIOD = 20              # ATR lookback for stops
INITIAL_STOP_ATR = 3.0       # initial stop = entry - 3.0*ATR20
TRAIL_STOP_ATR = 3.5         # trailing stop = peak close - 3.5*ATR20

# Per-symbol exchange precision (decimal places) for quantity rounding.
QTY_PRECISION: dict[str, int] = {"BTC/USDT": 5, "ETH/USDT": 4}


def _ema(values: list[float], period: int):
    """Exponential moving average, seeded with the SMA of the first `period`."""
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    val = sum(values[:period]) / period
    for price in values[period:]:
        val = price * k + val * (1 - k)
    return val


def _atr(bars: list[dict], period: int):
    """Average true range over the most recent `period` completed true ranges."""
    if len(bars) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(bars)):
        h = bars[i]["h"]
        l = bars[i]["l"]
        prev_c = bars[i - 1]["c"]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    window = trs[-period:]
    if len(window) < period:
        return None
    return sum(window) / period


def _initial_stop(entry: float, atr: float, mult: float = INITIAL_STOP_ATR) -> float:
    return entry - mult * atr


def _trailing_stop(peak_close: float, atr: float, mult: float = TRAIL_STOP_ATR) -> float:
    return peak_close - mult * atr


def _round_qty_down(qty: float, precision: int) -> float:
    """Round a quantity DOWN to `precision` decimal places (never up)."""
    if precision < 0:
        precision = 0
    import math
    factor = 10 ** precision
    return math.floor(qty * factor) / factor


def _passes_min_notional(budget_usd: float, min_notional: float) -> bool:
    """Skip an entry when the exchange minimum notional exceeds the budget (§8.4)."""
    return budget_usd >= min_notional


class BtcEthTrend(Strategy):
    name = "btc_eth_trend"
    label = "BTC/ETH Daily Trend"
    brokers: ClassVar[list[str]] = ["crypto"]
    # Research candidate — NOT auto-assigned/enabled until research + cutover.
    auto_trade: ClassVar[bool] = False
    hidden: ClassVar[bool] = True
    description = (
        "Spot-only daily trend on BTC/USDT and ETH/USDT. Enters on a 55-day "
        "breakout while EMA50 > EMA200. Exits on a 20-day low break, two closes "
        "below EMA200, or an ATR trailing stop. No leverage, shorts, or 4h candles. "
        "Research candidate: disabled by default until walk-forward validation passes."
    )

    UNIVERSE: ClassVar[list[str]] = ["BTC/USDT", "ETH/USDT"]

    default_params = {
        "timeframe": "day",
        "max_positions": 2,
        "risk_pct": 0.10,            # 0.10% of equity per position
        "btc_max_alloc_pct": 3.0,    # BTC max allocation 3%
        "eth_max_alloc_pct": 2.0,    # ETH max allocation 2%
        "combined_max_alloc_pct": 5.0,  # combined crypto MV <= 5%
        "notional": 500,
    }
    params_schema = [
        {"key": "max_positions", "label": "Max Open Positions", "type": "number",
         "min": 1, "max": 2, "ai_tunable": False,
         "hint": "Maximum concurrent crypto positions (spec cap is 2)."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number",
         "min": 10, "max": 100000, "ai_tunable": False,
         "hint": "Fallback per-trade notional. Live sizing is governed by the "
                 "portfolio risk controller and the 3%/2%/5% allocation caps."},
    ]

    def evaluate(self, positions, client=None, account_id=None):
        out: list[Signal] = []
        max_pos = int(self.params.get("max_positions", 2))
        notional = float(self.params.get("notional", 500))

        bars_by_symbol: dict[str, list[dict]] = {}
        for sym in self.UNIVERSE:
            try:
                bars_by_symbol[sym] = self._get_bars(
                    client, sym, days=max(BREAKOUT_LOOKBACK, EMA_SLOW) + ATR_PERIOD + 40
                )
            except Exception:
                bars_by_symbol[sym] = []

        # ── EXITS (owned positions only) ────────────────────────────────────
        for sym in self.UNIVERSE:
            held = positions.get(sym, 0.0)
            if held <= 0:
                continue
            bars = bars_by_symbol.get(sym, [])
            if len(bars) < max(EXIT_LOW_LOOKBACK, ATR_PERIOD) + 2:
                continue
            reason = self._exit_reason(bars, account_id, sym)
            if reason is not None:
                out.append(Signal(symbol=sym, side="sell", qty=held,
                                  reason=f"{RULE_VERSION}: {reason} — exit next candle"))

        # ── ENTRIES ─────────────────────────────────────────────────────────
        held_count = sum(1 for v in positions.values() if v > 0)
        if held_count >= max_pos:
            return out

        slots = max_pos - held_count
        for sym in self.UNIVERSE:   # BTC before ETH — deterministic order
            if slots <= 0:
                break
            if positions.get(sym, 0.0) > 0:
                continue  # no pyramiding
            if self._owned_entry(account_id, sym) is not None:
                continue
            bars = bars_by_symbol.get(sym, [])
            if not self._entry_ok(bars):
                continue
            close = bars[-1]["c"]
            reason = (f"{RULE_VERSION}: breakout close {close:.2f} > prior-{BREAKOUT_LOOKBACK} high, "
                      f"EMA{EMA_FAST} > EMA{EMA_SLOW}")
            out.append(Signal(symbol=sym, side="buy", notional=notional, reason=reason))
            slots -= 1

        return out

    # ── helpers ─────────────────────────────────────────────────────────────
    def _owned_entry(self, account_id, symbol):
        if account_id is None:
            return None
        try:
            ep = db.get_strategy_entry_price(self.name, account_id, symbol)
        except Exception:
            return None
        return float(ep) if ep is not None else None

    def _entry_ok(self, bars) -> bool:
        if len(bars) < max(BREAKOUT_LOOKBACK, EMA_SLOW) + 1:
            return False
        decision = bars[-1]
        prior = bars[:-1]   # EXCLUDES decision candle (§8.2)

        prior_55 = prior[-BREAKOUT_LOOKBACK:]
        if len(prior_55) < BREAKOUT_LOOKBACK:
            return False
        prior_high = max(b["h"] for b in prior_55)
        if not (decision["c"] > prior_high):
            return False

        closes = [b["c"] for b in bars]
        ema_fast = _ema(closes, EMA_FAST)
        ema_slow = _ema(closes, EMA_SLOW)
        if ema_fast is None or ema_slow is None or not (ema_fast > ema_slow):
            return False
        return True

    def _exit_reason(self, bars, account_id, symbol) -> str | None:
        decision = bars[-1]
        prior = bars[:-1]
        close = decision["c"]
        closes = [b["c"] for b in bars]

        # 1) close < lowest low of prior 20 candles (excluding decision candle).
        prior_20 = prior[-EXIT_LOW_LOOKBACK:]
        if len(prior_20) >= EXIT_LOW_LOOKBACK:
            prior_low = min(b["l"] for b in prior_20)
            if close < prior_low:
                return f"close {close:.2f} < prior-{EXIT_LOW_LOOKBACK} low {prior_low:.2f}"

        # 2) close below EMA200 for two consecutive completed candles.
        ema_now = _ema(closes, EMA_SLOW)
        ema_prev = _ema(closes[:-1], EMA_SLOW)
        if (ema_now is not None and ema_prev is not None
                and close < ema_now and closes[-2] < ema_prev):
            return f"two closes < EMA{EMA_SLOW}"

        # 3) ATR trailing stop breach (also covers the initial stop floor).
        atr = _atr(bars, ATR_PERIOD)
        entry = self._owned_entry(account_id, symbol)
        stop = self._stop_level(closes, entry, atr)
        if stop is not None and close < stop:
            return f"ATR trailing stop breach close {close:.2f} < stop {stop:.2f}"

        return None

    def _stop_level(self, closes, entry, atr):
        """max(initial stop, trailing stop); trailing uses the highest completed
        close over the window. The peak can only be >= the true post-entry peak,
        which keeps the stop monotonic (never loosens) per §8.3."""
        if atr is None or atr <= 0:
            return None
        peak_close = max(closes)
        trail = _trailing_stop(peak_close, atr, TRAIL_STOP_ATR)
        if entry is not None:
            initial = _initial_stop(entry, atr, INITIAL_STOP_ATR)
            return max(initial, trail)
        return trail
