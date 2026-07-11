"""Liquid US Stock Trend / Breakout strategy (Task 8, spec §7).

A PURE, completed-bar signal model. It performs NO network calls itself (bars are
supplied by the account's broker client through the base-class helper) and holds
NO global state. Each evaluation reads only:

  - the completed daily bars for each universe symbol (decision bar = last bar), and
  - this strategy's OWN entry price for the account, via the Task 2 ledger
    (`db.get_strategy_entry_price`), which only ever returns strategy-owned lots.

The entry ATR, peak close, and trailing stop are derived deterministically from
the bar history each tick; the confirmed entry price / ATR / peak / stop live with
the owned lot (Task 1/2 ledger) — this model never invents a new table.

RESEARCH CANDIDATE: `auto_trade = False`, so it is registered (exists in REGISTRY)
but is NOT auto-assigned or enabled. It is enabled only after Task 9 research and
the Task 12 paper cutover.

Spec thresholds implemented (do not change without re-reading §7):
  - prior 252-session high (EXCLUDING the decision bar), close strictly above
  - close above SMA100
  - decision-bar volume >= 1.2x avg volume of prior 20 sessions (excluding decision bar)
  - regime: SPY close > SMA200 AND SMA200 > its value 20 sessions earlier
  - two consecutive SPY closes below SMA200 -> regime exit
  - initial stop = entry - 2.5*ATR20(at entry); trailing = peak close - 3.0*ATR20; never lowers
  - max 5 positions; rank surplus qualifiers by % distance above prior-252 high, then symbol
"""
from typing import ClassVar

from .base import Strategy, Signal
from .. import db

RULE_VERSION = "liquid_stock_trend/v1"

# Spec §7 thresholds (named constants — every one is load-bearing).
BREAKOUT_LOOKBACK = 252     # prior sessions for the breakout high (excl. decision bar)
SMA_TREND = 100             # close must exceed SMA100
VOL_LOOKBACK = 20           # prior sessions for the average-volume baseline
VOL_MULT = 1.2             # decision-bar volume must be >= 1.2x that average
REGIME_SMA = 200            # SPY regime SMA
REGIME_SLOPE_LOOKBACK = 20  # SMA200 must exceed its value this many sessions earlier
ATR_PERIOD = 20             # ATR lookback for stops
INITIAL_STOP_ATR = 2.5      # initial stop = entry - 2.5 * ATR20
TRAIL_STOP_ATR = 3.0        # trailing stop = peak close - 3.0 * ATR20


def _sma(values: list[float], period: int, offset: int = 0):
    """Simple moving average of the `period` values ending `offset` bars before
    the last element. offset=0 → the most recent window. Returns None if short."""
    end = len(values) - offset
    start = end - period
    if start < 0 or end <= 0:
        return None
    window = values[start:end]
    if len(window) < period:
        return None
    return sum(window) / period


def _atr(bars: list[dict], period: int):
    """Wilder-style ATR over the most recent `period` completed true ranges.

    True range uses the previous bar's close, so `period+1` bars are needed."""
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


def _trailing_stop(peak_close: float, atr: float, mult: float = TRAIL_STOP_ATR) -> float:
    """Trailing stop level = highest completed close since entry - mult*ATR20."""
    return peak_close - mult * atr


def _initial_stop(entry: float, atr: float, mult: float = INITIAL_STOP_ATR) -> float:
    """Initial stop = confirmed entry - mult*ATR20 (at entry)."""
    return entry - mult * atr


class LiquidStockTrend(Strategy):
    name = "liquid_stock_trend"
    label = "Liquid US Stock Trend"
    brokers: ClassVar[list[str]] = ["stock"]
    # Research candidate — NOT auto-assigned/enabled until research + cutover.
    auto_trade: ClassVar[bool] = False
    hidden: ClassVar[bool] = True
    description = (
        "Long-only daily trend/breakout on a fixed liquid US universe "
        "(SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META). Enters on a 252-session "
        "breakout confirmed by SMA100 and volume, only while SPY's 200-day trend is "
        "rising. Exits on ATR trailing stop or SPY regime failure. Research candidate: "
        "disabled by default until walk-forward validation passes."
    )

    UNIVERSE: ClassVar[list[str]] = [
        "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META",
    ]

    default_params = {
        "max_positions": 5,
        "notional": 1000,
    }
    params_schema = [
        {"key": "max_positions", "label": "Max Open Positions", "type": "number",
         "min": 1, "max": 5, "ai_tunable": False,
         "hint": "Maximum concurrent stock positions (spec cap is 5)."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number",
         "min": 10, "max": 100000, "ai_tunable": False,
         "hint": "Fallback per-trade notional. Live sizing is governed by the "
                 "portfolio risk controller; this is used only when no risk budget "
                 "is supplied."},
    ]

    # ── regime ──────────────────────────────────────────────────────────────
    def _spy_regime(self, client) -> tuple[bool, bool]:
        """Return (entries_allowed, regime_exit).

        entries_allowed: SPY close > SMA200 AND SMA200 rising over 20 sessions.
        regime_exit: SPY closed below SMA200 for the last TWO completed sessions."""
        try:
            bars = self._get_bars(client, "SPY", days=REGIME_SMA + REGIME_SLOPE_LOOKBACK + 40)
        except Exception:
            return False, False
        closes = [b["c"] for b in bars]
        sma_now = _sma(closes, REGIME_SMA)
        sma_prev20 = _sma(closes, REGIME_SMA, offset=REGIME_SLOPE_LOOKBACK)
        if sma_now is None or sma_prev20 is None or len(closes) < 2:
            return False, False

        entries_allowed = closes[-1] > sma_now and sma_now > sma_prev20

        # Two consecutive completed closes below SMA200 → regime exit next session.
        sma_last = _sma(closes, REGIME_SMA, offset=0)
        sma_second_last = _sma(closes, REGIME_SMA, offset=1)
        regime_exit = False
        if sma_last is not None and sma_second_last is not None:
            regime_exit = (closes[-1] < sma_last) and (closes[-2] < sma_second_last)
        return entries_allowed, regime_exit

    def evaluate(self, positions, client=None, account_id=None):
        out: list[Signal] = []
        max_pos = int(self.params.get("max_positions", 5))
        notional = float(self.params.get("notional", 1000))

        entries_allowed, regime_exit = self._spy_regime(client)

        # Fetch bars once per universe symbol.
        bars_by_symbol: dict[str, list[dict]] = {}
        for sym in self.UNIVERSE:
            try:
                bars_by_symbol[sym] = self._get_bars(
                    client, sym, days=BREAKOUT_LOOKBACK + ATR_PERIOD + 60
                )
            except Exception:
                bars_by_symbol[sym] = []

        # ── EXITS (owned positions only) ────────────────────────────────────
        # `positions` already contains ONLY this strategy's owned lots on this
        # account (engine passes db.get_strategy_positions). Never account-level.
        for sym in self.UNIVERSE:
            held = positions.get(sym, 0.0)
            if held <= 0:
                continue
            bars = bars_by_symbol.get(sym, [])
            if len(bars) < ATR_PERIOD + 2:
                # Still honour regime failure even without enough bars for ATR.
                if regime_exit:
                    out.append(Signal(symbol=sym, side="sell", qty=held,
                        reason=f"{RULE_VERSION}: regime failure (SPY 2 closes < SMA200) — exit next open"))
                continue

            if regime_exit:
                out.append(Signal(symbol=sym, side="sell", qty=held,
                    reason=f"{RULE_VERSION}: regime failure (SPY 2 closes < SMA200) — exit next open"))
                continue

            close = bars[-1]["c"]
            atr = _atr(bars, ATR_PERIOD)
            entry = self._owned_entry(account_id, sym)
            stop = self._stop_level(bars, entry, atr)
            if stop is not None and close < stop:
                out.append(Signal(symbol=sym, side="sell", qty=held,
                    reason=f"{RULE_VERSION}: stop breach close {close:.2f} < stop {stop:.2f} — exit next open"))

        # ── ENTRIES ─────────────────────────────────────────────────────────
        if not entries_allowed:
            return out

        held_count = sum(1 for v in positions.values() if v > 0)
        if held_count >= max_pos:
            return out

        qualifiers: list[tuple[float, str]] = []
        for sym in self.UNIVERSE:
            if positions.get(sym, 0.0) > 0:
                continue  # no pyramiding: already owned
            # Also skip if the ledger reports an owned entry (pending/owned lot).
            if self._owned_entry(account_id, sym) is not None:
                continue
            bars = bars_by_symbol.get(sym, [])
            surplus = self._entry_surplus(bars)
            if surplus is not None:
                qualifiers.append((surplus, sym))

        # Rank by % distance above prior-252 high (desc), then symbol (asc).
        qualifiers.sort(key=lambda t: (-t[0], t[1]))

        slots = max_pos - held_count
        for surplus, sym in qualifiers[:slots]:
            bars = bars_by_symbol[sym]
            close = bars[-1]["c"]
            reason = (f"{RULE_VERSION}: breakout close {close:.2f} > prior-{BREAKOUT_LOOKBACK} high "
                      f"(+{surplus * 100:.2f}%), > SMA{SMA_TREND}, vol >= {VOL_MULT}x avg")
            out.append(Signal(symbol=sym, side="buy", notional=notional, reason=reason))

        return out

    # ── helpers ─────────────────────────────────────────────────────────────
    def _owned_entry(self, account_id, symbol):
        """This strategy's own entry price for the account (Task 2 ledger), or None."""
        if account_id is None:
            return None
        try:
            ep = db.get_strategy_entry_price(self.name, account_id, symbol)
        except Exception:
            return None
        return float(ep) if ep is not None else None

    def _stop_level(self, bars, entry, atr):
        """Effective stop = max(initial stop, trailing stop), never below initial.

        The trailing stop uses the highest completed close since entry. Without a
        precise entry index we conservatively use the highest completed close over
        the available window (the peak can only be >= the true post-entry peak,
        which keeps the stop from moving DOWN — the spec's monotonic requirement)."""
        if atr is None or atr <= 0:
            return None
        closes = [b["c"] for b in bars]
        peak_close = max(closes)
        trail = _trailing_stop(peak_close, atr, TRAIL_STOP_ATR)
        if entry is not None:
            initial = _initial_stop(entry, atr, INITIAL_STOP_ATR)
            return max(initial, trail)
        return trail

    def _entry_surplus(self, bars):
        """Return % distance of the decision close above the prior-252 high when the
        symbol qualifies for entry, else None. Excludes the decision bar from the
        trailing high and the volume average."""
        if len(bars) < max(BREAKOUT_LOOKBACK, SMA_TREND, VOL_LOOKBACK) + 1:
            return None
        decision = bars[-1]
        prior = bars[:-1]  # EXCLUDES the decision bar (§7.3)

        close = decision["c"]

        # 1) close > highest high of prior 252 sessions (excluding decision bar).
        prior_252 = prior[-BREAKOUT_LOOKBACK:]
        if len(prior_252) < BREAKOUT_LOOKBACK:
            return None
        prior_high = max(b["h"] for b in prior_252)
        if not (close > prior_high) or prior_high <= 0:
            return None

        # 2) close > SMA100 (over the most recent 100 completed closes incl. decision).
        closes = [b["c"] for b in bars]
        sma100 = _sma(closes, SMA_TREND)
        if sma100 is None or not (close > sma100):
            return None

        # 3) decision volume >= 1.2x avg volume of prior 20 sessions (excl. decision).
        prior_20 = prior[-VOL_LOOKBACK:]
        if len(prior_20) < VOL_LOOKBACK:
            return None
        avg_vol = sum(b["v"] for b in prior_20) / VOL_LOOKBACK
        if avg_vol <= 0 or not (decision["v"] >= VOL_MULT * avg_vol):
            return None

        return (close - prior_high) / prior_high
