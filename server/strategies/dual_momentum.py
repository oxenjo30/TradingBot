"""Dual-Momentum ETF Rotation strategy.

A low-turnover, monthly-rebalanced rotation across a diversified ETF universe.
It combines TWO momentum filters (hence "dual"):

  1. Absolute (time-series) momentum — a symbol is eligible ONLY when its close is
     above its own long-term SMA (default 200). This is the safety valve: when
     everything is below trend (a broad crash), NOTHING qualifies and the book goes
     to cash rather than buying a falling market.
  2. Relative (cross-sectional) momentum — among the eligible symbols, hold the
     top-K ranked by total return over the lookback window (default 126 sessions).

Design intent (grounded in the live P&L evidence): the strategy that bled the most
was a high-turnover pattern matcher (classic_patterns, -$1,954, 41% win rate). This
strategy is the opposite — it acts only at a monthly rebalance, so cost drag is
minimal, and it holds only proven-trending instruments. It is the most-validated
style in the literature (Antonacci dual momentum; time-series + cross-sectional).

PURE completed-bar signal model: NO network calls of its own (bars come from the
account's broker client via the base helper), NO global state. Positions passed in
are ONLY this strategy's owned lots on the account (Task 2 ledger).

RESEARCH CANDIDATE: `auto_trade = False`, `hidden = True` — registered but NOT
auto-assigned or enabled. Enabled only after walk-forward validation PASSES and an
explicit paper cutover.
"""
from typing import ClassVar

from .base import Strategy, Signal

RULE_VERSION = "dual_momentum/v1"

# Defaults (every one is load-bearing; the research grid tunes lookback/abs_sma/top_k).
LOOKBACK = 126        # sessions for the relative-momentum total return (~6 months)
ABS_SMA = 200         # absolute-momentum trend filter: close must exceed this SMA
TOP_K = 2             # number of top-ranked eligible symbols to hold
REBALANCE_DOM = 1     # act only on the first completed session of a new month


def _sma(closes: list[float], period: int):
    """SMA of the last `period` closes, or None if too short."""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _total_return(closes: list[float], lookback: int):
    """Total return over the last `lookback` sessions: close[-1]/close[-1-lookback]-1.

    Returns None if there is not enough history or the base price is non-positive."""
    if len(closes) < lookback + 1:
        return None
    base = closes[-1 - lookback]
    if base <= 0:
        return None
    return closes[-1] / base - 1.0


class DualMomentum(Strategy):
    name = "dual_momentum"
    label = "Dual-Momentum ETF Rotation"
    brokers: ClassVar[list[str]] = ["stock"]
    # Research candidate — NOT auto-assigned/enabled until validation + cutover.
    auto_trade: ClassVar[bool] = False
    hidden: ClassVar[bool] = True
    description = (
        "Low-turnover monthly rotation across a diversified ETF universe "
        "(SPY, QQQ, IWM, DIA, GLD, TLT, EEM). Holds the top-K symbols ranked by "
        "6-month return, but only those still above their 200-day trend; goes to "
        "cash when nothing qualifies (sits out broad crashes). Research candidate: "
        "disabled by default until walk-forward validation passes."
    )

    UNIVERSE: ClassVar[list[str]] = [
        "SPY", "QQQ", "IWM", "DIA", "GLD", "TLT", "EEM",
    ]

    default_params = {
        "lookback": LOOKBACK,
        "abs_sma": ABS_SMA,
        "top_k": TOP_K,
        "notional": 1000,
    }
    params_schema = [
        {"key": "lookback", "label": "Momentum Lookback (sessions)", "type": "number",
         "min": 20, "max": 252, "ai_tunable": True,
         "hint": "Sessions used for the relative-momentum total return (~126 = 6mo)."},
        {"key": "abs_sma", "label": "Trend Filter SMA", "type": "number",
         "min": 50, "max": 250, "ai_tunable": True,
         "hint": "A symbol is eligible only when its close exceeds this SMA."},
        {"key": "top_k", "label": "Positions to Hold", "type": "number",
         "min": 1, "max": 4, "ai_tunable": True,
         "hint": "Number of top-ranked eligible symbols to hold."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number",
         "min": 10, "max": 100000, "ai_tunable": False,
         "hint": "Fallback per-trade notional; live sizing is governed by the "
                 "portfolio risk controller."},
    ]

    def _is_rebalance_day(self, client) -> bool:
        """True only on the first completed session of a new calendar month.

        Uses SPY's bar dates as the market calendar. If a bar lacks a parseable
        timestamp (pure fixture with no 't'), we treat EVERY tick as a rebalance so
        deterministic tests still exercise the rotation logic."""
        try:
            bars = self._get_bars(client, "SPY", days=5)
        except Exception:
            return True
        dated = [b for b in bars if b.get("t")]
        if len(dated) < 2:
            return True                 # undated fixture → always evaluate
        last = dated[-1]["t"][:10]
        prev = dated[-2]["t"][:10]
        # First session of a new month: month component differs from the prior bar.
        return last[5:7] != prev[5:7]

    def evaluate(self, positions, client=None, account_id=None):
        lookback = int(self.params.get("lookback", LOOKBACK))
        abs_sma = int(self.params.get("abs_sma", ABS_SMA))
        top_k = int(self.params.get("top_k", TOP_K))
        notional = float(self.params.get("notional", 1000))

        # Only act at the monthly rebalance — this is what keeps turnover (and cost
        # drag) low. Between rebalances, hold.
        if not self._is_rebalance_day(client):
            return []

        need = max(lookback + 1, abs_sma)
        closes_by_symbol: dict[str, list[float]] = {}
        for sym in self.UNIVERSE:
            try:
                bars = self._get_bars(client, sym, days=need + 40)
            except Exception:
                bars = []
            closes_by_symbol[sym] = [b["c"] for b in bars]

        # Eligible = passes ABSOLUTE momentum (close > own SMA) AND has a lookback return.
        ranked: list[tuple[float, str]] = []
        for sym in self.UNIVERSE:
            closes = closes_by_symbol.get(sym, [])
            sma = _sma(closes, abs_sma)
            if sma is None or closes[-1] <= sma:
                continue
            ret = _total_return(closes, lookback)
            if ret is None:
                continue
            ranked.append((ret, sym))

        # Relative momentum: highest total return first, tie-break by symbol.
        ranked.sort(key=lambda t: (-t[0], t[1]))
        target = {sym for _r, sym in ranked[:top_k]}

        out: list[Signal] = []

        # EXITS: sell any owned symbol NOT in the new target set (fell out of top-K
        # or lost its uptrend). `positions` holds only this strategy's owned lots.
        for sym, qty in positions.items():
            if qty > 0 and sym not in target:
                out.append(Signal(symbol=sym, side="sell", qty=qty,
                    reason=f"{RULE_VERSION}: exit — no longer top-{top_k} above SMA{abs_sma}"))

        # ENTRIES: buy target symbols not already held.
        for ret, sym in ranked[:top_k]:
            if positions.get(sym, 0.0) > 0:
                continue
            out.append(Signal(symbol=sym, side="buy", notional=notional,
                reason=f"{RULE_VERSION}: top-{top_k} momentum "
                       f"(+{ret * 100:.1f}% / {lookback}d) above SMA{abs_sma}"))

        return out
