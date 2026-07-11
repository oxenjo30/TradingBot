"""Tests for the Dual-Momentum ETF Rotation strategy.

PURE signal-model tests: deterministic bar fixtures, NO network, NO global state.
The decision bar is the LAST bar in each list. These lock the load-bearing rules:
absolute-momentum cash-out, relative-momentum ranking, top-K, monthly rebalance,
and exit-on-drop-out.
"""
from unittest.mock import MagicMock

from server.strategies.dual_momentum import DualMomentum


def _bar(c, t=None, v=1000.0):
    b = {"o": c, "h": c, "l": c, "c": c, "v": v}
    if t is not None:
        b["t"] = t
    return b


def _series(closes, dates=None):
    """Build a bar list from a close sequence; optional ISO dates (YYYY-MM-DD)."""
    out = []
    for i, c in enumerate(closes):
        t = f"{dates[i]}T00:00:00+00:00" if dates else None
        out.append(_bar(c, t=t))
    return out


def _client(bars_by_symbol):
    client = MagicMock()

    def _get(symbol, days=0):
        return bars_by_symbol.get(symbol.upper(), [])

    client.get_recent_bars.side_effect = _get
    return client


def _rising(n, start=100.0, step=1.0):
    """Strictly rising closes → above any SMA and positive lookback return."""
    return [start + i * step for i in range(n)]


def _falling(n, start=300.0, step=1.0):
    """Strictly falling closes → below SMA (fails absolute momentum)."""
    return [max(1.0, start - i * step) for i in range(n)]


# All fixtures long enough for lookback=126 + abs_sma=200.
N = 300


def test_all_below_trend_goes_to_cash():
    """When every symbol is below its SMA (broad downtrend), NOTHING is bought.

    This is the crash-protection property: no entries, book stays in cash."""
    bars = {sym: _series(_falling(N)) for sym in DualMomentum.UNIVERSE}
    strat = DualMomentum({"notional": 1000})
    signals = strat.evaluate(positions={}, client=_client(bars), account_id=1)
    buys = [s for s in signals if s.side == "buy"]
    assert buys == []


def test_holds_top_k_by_relative_momentum():
    """Among symbols above trend, exactly top_k highest-momentum names are bought."""
    # Give each symbol a different slope → different lookback return, all rising.
    slopes = {"SPY": 2.0, "QQQ": 1.8, "IWM": 1.5, "DIA": 1.0,
              "GLD": 0.5, "TLT": 0.3, "EEM": 0.2}
    bars = {sym: _series(_rising(N, step=slopes[sym])) for sym in DualMomentum.UNIVERSE}
    strat = DualMomentum({"top_k": 2, "notional": 1000})
    signals = strat.evaluate(positions={}, client=_client(bars), account_id=1)
    bought = sorted(s.symbol for s in signals if s.side == "buy")
    # Steepest two slopes are SPY and QQQ.
    assert bought == ["QQQ", "SPY"]


def test_top_k_respected():
    """top_k=1 buys exactly one; top_k=3 buys three."""
    slopes = {"SPY": 2.0, "QQQ": 1.8, "IWM": 1.5, "DIA": 1.0,
              "GLD": 0.5, "TLT": 0.3, "EEM": 0.2}
    bars = {sym: _series(_rising(N, step=slopes[sym])) for sym in DualMomentum.UNIVERSE}
    for k, expected in ((1, 1), (3, 3)):
        strat = DualMomentum({"top_k": k, "notional": 1000})
        sig = strat.evaluate(positions={}, client=_client(bars), account_id=1)
        assert len([s for s in sig if s.side == "buy"]) == expected


def test_exits_symbol_that_fell_out_of_top_k():
    """A held symbol no longer in the target set is SOLD."""
    slopes = {"SPY": 2.0, "QQQ": 1.8, "IWM": 1.5, "DIA": 1.0,
              "GLD": 0.5, "TLT": 0.3, "EEM": 0.2}
    bars = {sym: _series(_rising(N, step=slopes[sym])) for sym in DualMomentum.UNIVERSE}
    strat = DualMomentum({"top_k": 2, "notional": 1000})
    # We hold DIA (rank 4) — it should be sold; targets are SPY, QQQ.
    signals = strat.evaluate(positions={"DIA": 5.0}, client=_client(bars), account_id=1)
    sells = [s for s in signals if s.side == "sell"]
    assert any(s.symbol == "DIA" for s in sells)
    # And it does not re-buy DIA.
    assert not any(s.symbol == "DIA" and s.side == "buy" for s in signals)


def test_no_rebuy_of_already_held_target():
    """A held symbol that is STILL in the target set is not bought again."""
    slopes = {"SPY": 2.0, "QQQ": 1.8, "IWM": 1.5, "DIA": 1.0,
              "GLD": 0.5, "TLT": 0.3, "EEM": 0.2}
    bars = {sym: _series(_rising(N, step=slopes[sym])) for sym in DualMomentum.UNIVERSE}
    strat = DualMomentum({"top_k": 2, "notional": 1000})
    signals = strat.evaluate(positions={"SPY": 3.0}, client=_client(bars), account_id=1)
    assert not any(s.symbol == "SPY" and s.side == "buy" for s in signals)
    # SPY is still a target, so it is not sold either.
    assert not any(s.symbol == "SPY" and s.side == "sell" for s in signals)


def test_rebalance_only_on_first_session_of_month():
    """With dated bars, no action mid-month; action on the month boundary."""
    slopes = {"SPY": 2.0, "QQQ": 1.8, "IWM": 1.5, "DIA": 1.0,
              "GLD": 0.5, "TLT": 0.3, "EEM": 0.2}

    def dated(step, last_two):
        closes = _rising(N, step=step)
        dates = [f"2020-{1 + (i // 21) % 12:02d}-{1 + i % 21:02d}" for i in range(N)]
        # Force the final two bar dates to control the month-boundary check.
        dates[-2], dates[-1] = last_two
        return _series(closes, dates)

    # Mid-month: last two bars in the SAME month → NO rebalance.
    mid = {sym: dated(slopes[sym], ("2021-03-14", "2021-03-15"))
           for sym in DualMomentum.UNIVERSE}
    strat = DualMomentum({"top_k": 2, "notional": 1000})
    assert strat.evaluate(positions={}, client=_client(mid), account_id=1) == []

    # Month boundary: last bar is the first session of a NEW month → rebalance.
    boundary = {sym: dated(slopes[sym], ("2021-02-26", "2021-03-01"))
                for sym in DualMomentum.UNIVERSE}
    strat2 = DualMomentum({"top_k": 2, "notional": 1000})
    sig = strat2.evaluate(positions={}, client=_client(boundary), account_id=1)
    assert len([s for s in sig if s.side == "buy"]) == 2


def test_registered_and_validated():
    """dual_momentum is registered and (post-validation) allowed to trade.

    It PASSED walk-forward validation on 2026-07-11, so auto_trade is True and it is
    visible in the UI. Safety now lives at the per-account assignment level, not the
    class flag: it only runs where an operator has explicitly enabled it."""
    from server.strategies import REGISTRY
    assert "dual_momentum" in REGISTRY
    cls = REGISTRY["dual_momentum"]
    assert cls.auto_trade is True
    assert cls.hidden is False


def test_insufficient_history_no_signals():
    """Too-short history yields no signals, no crash."""
    bars = {sym: _series(_rising(50)) for sym in DualMomentum.UNIVERSE}  # < abs_sma
    strat = DualMomentum({"notional": 1000})
    assert strat.evaluate(positions={}, client=_client(bars), account_id=1) == []
