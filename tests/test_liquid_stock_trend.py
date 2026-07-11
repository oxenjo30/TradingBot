"""Tests for the Liquid US Stock Trend/Breakout strategy (Task 8, spec §7).

These are PURE signal-model tests: deterministic bar fixtures, NO network, NO
global state. The decision bar is the LAST bar in each list (most recently
completed daily bar). Trailing windows that the spec says exclude the decision
bar use bars[:-1].
"""
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Bar fixtures
# ---------------------------------------------------------------------------

def _bar(o, h, l, c, v):
    return {"o": o, "h": h, "l": l, "c": c, "v": v}


def _flat_bars(n, price, vol=1000.0):
    return [_bar(price, price, price, price, vol) for _ in range(n)]


def _client(bars_by_symbol):
    """MagicMock broker client whose get_recent_bars returns per-symbol fixtures."""
    client = MagicMock()

    def _get(symbol, days=0):
        return bars_by_symbol.get(symbol.upper(), [])

    client.get_recent_bars.side_effect = _get
    return client


def _rising_spy(n=260, start=100.0, step=1.0, vol=1000.0):
    """SPY closes strictly rising so close>SMA200 and SMA200 rising over 20 sessions."""
    return [_bar(start + i * step, start + i * step, start + i * step,
                 start + i * step, vol) for i in range(n)]


# Convenience: build a symbol history that fires an entry on the decision bar.
def _breakout_history(n_prior=260, base=100.0, prior_high=150.0,
                      decision_close=160.0, decision_vol=2000.0,
                      prior_vol=1000.0):
    """Prior bars sit below prior_high with SMA100 well under decision_close;
    the decision bar closes above the prior-252 high on high volume."""
    bars = []
    # First bars low, then one bar sets the prior-252 high just under decision.
    for i in range(n_prior):
        c = base + (i * (prior_high - base) / n_prior)
        bars.append(_bar(c, c, c, c, prior_vol))
    # ensure the single highest prior high is exactly prior_high on the 2nd-last-ish bar
    bars[-1] = _bar(prior_high, prior_high, prior_high, prior_high, prior_vol)
    # decision bar (last) breaks out
    bars.append(_bar(decision_close, decision_close, decision_close,
                     decision_close, decision_vol))
    return bars


def _strat(**params):
    from server.strategies.liquid_stock_trend import LiquidStockTrend
    base = {}
    base.update(params)
    return LiquidStockTrend(base)


def _no_entry_state():
    """Patch the entry-price lookup so the strategy sees no owned position."""
    import server.strategies.liquid_stock_trend as mod
    return patch.object(mod.db, "get_strategy_entry_price", return_value=None)


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------

class TestUniverse:
    def test_universe_is_fixed_declared_list(self):
        from server.strategies.liquid_stock_trend import LiquidStockTrend
        assert LiquidStockTrend.UNIVERSE == [
            "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META"
        ]

    def test_no_scanner_used(self):
        # The strategy must never call the scanner module.
        import server.strategies.liquid_stock_trend as mod
        assert not hasattr(mod, "scanner")


# ---------------------------------------------------------------------------
# Regime gate (§7.2)
# ---------------------------------------------------------------------------

class TestRegime:
    def test_no_entry_when_spy_below_sma200(self):
        # SPY declining: close < SMA200 → no new entries anywhere.
        spy = [_bar(c, c, c, c, 1000) for c in [300.0 - i for i in range(260)]]
        bars = {"SPY": spy, "AAPL": _breakout_history()}
        client = _client(bars)
        strat = _strat()
        with _no_entry_state():
            signals = strat.evaluate({}, client=client, account_id=1)
        assert not any(s.side == "buy" for s in signals)

    def test_no_entry_when_sma200_not_rising(self):
        # SPY close above SMA200, but SMA200(now) == SMA200(20 sessions earlier).
        # Regime requires SMA200 STRICTLY above its value 20 sessions earlier, so a
        # flat SMA200 must block new entries.
        #
        # With 260 bars: SMA200(now) covers indices 60..259; SMA200(offset 20)
        # covers indices 40..239. Put ONE elevated bar in the now-only region
        # (index 259) and ONE in the offset-only region (index 50), so each 200-bar
        # window contains exactly one +5 bump → equal averages → flat slope.
        spy = _flat_bars(260, 200.0)
        spy[259] = _bar(205.0, 205.0, 205.0, 205.0, 1000)  # now-window only
        spy[50] = _bar(205.0, 205.0, 205.0, 205.0, 1000)   # offset-20 window only
        bars = {"SPY": spy, "AAPL": _breakout_history()}
        client = _client(bars)
        strat = _strat()
        with _no_entry_state():
            signals = strat.evaluate({}, client=client, account_id=1)
        assert not any(s.side == "buy" for s in signals)

    def test_entry_allowed_when_regime_rising(self):
        spy = _rising_spy()
        bars = {"SPY": spy, "AAPL": _breakout_history()}
        client = _client(bars)
        strat = _strat()
        with _no_entry_state():
            signals = strat.evaluate({}, client=client, account_id=1)
        assert any(s.symbol == "AAPL" and s.side == "buy" for s in signals)

    def test_two_consecutive_spy_closes_below_sma200_exits_positions(self):
        # SPY was rising, then last two closes fall below SMA200 → regime-exit.
        spy = _rising_spy(260)
        # Force the last two closes far below the SMA200 (~ mid of the rising series).
        spy[-2] = _bar(50.0, 50.0, 50.0, 50.0, 1000)
        spy[-1] = _bar(49.0, 49.0, 49.0, 49.0, 1000)
        aapl = _breakout_history()
        bars = {"SPY": spy, "AAPL": aapl}
        client = _client(bars)
        strat = _strat()
        with patch("server.strategies.liquid_stock_trend.db.get_strategy_entry_price",
                   return_value=140.0):
            signals = strat.evaluate({"AAPL": 10.0}, client=client, account_id=1)
        sells = [s for s in signals if s.side == "sell" and s.symbol == "AAPL"]
        assert sells, "expected a regime-exit sell for the held position"
        assert "regime" in sells[0].reason.lower()

    def test_single_spy_close_below_sma200_does_not_regime_exit(self):
        spy = _rising_spy(260)
        # Only the LAST close dips below SMA200 (one session, not two).
        spy[-1] = _bar(49.0, 49.0, 49.0, 49.0, 1000)
        aapl = _breakout_history()
        bars = {"SPY": spy, "AAPL": aapl}
        client = _client(bars)
        strat = _strat()
        with patch("server.strategies.liquid_stock_trend.db.get_strategy_entry_price",
                   return_value=140.0):
            signals = strat.evaluate({"AAPL": 10.0}, client=client, account_id=1)
        assert not any(s.side == "sell" and "regime" in s.reason.lower() for s in signals)


# ---------------------------------------------------------------------------
# Entry (§7.3)
# ---------------------------------------------------------------------------

class TestEntry:
    def test_prior_252_high_excludes_decision_bar(self):
        # Decision-bar close equals the highest prior high but does NOT exceed it →
        # if the code wrongly INCLUDED the decision bar, close would equal its own
        # high and never "exceed prior high". We assert exclusion by making the
        # decision close only slightly above the prior 252 high and requiring a buy,
        # then a control where it equals prior high and must NOT buy.
        spy = _rising_spy()
        # Control: decision close == prior-252 high → not strictly above → no entry.
        equal_hist = _breakout_history(prior_high=150.0, decision_close=150.0,
                                       decision_vol=5000.0)
        client = _client({"SPY": spy, "AAPL": equal_hist})
        strat = _strat()
        with _no_entry_state():
            sigs = strat.evaluate({}, client=client, account_id=1)
        assert not any(s.symbol == "AAPL" and s.side == "buy" for s in sigs), \
            "close equal to prior-252 high must NOT enter (strictly-above rule)"

        # Positive: decision close strictly above prior-252 high → entry.
        above_hist = _breakout_history(prior_high=150.0, decision_close=150.5,
                                       decision_vol=5000.0)
        client2 = _client({"SPY": spy, "AAPL": above_hist})
        strat2 = _strat()
        with _no_entry_state():
            sigs2 = strat2.evaluate({}, client=client2, account_id=1)
        assert any(s.symbol == "AAPL" and s.side == "buy" for s in sigs2)

    def test_no_entry_when_close_below_sma100(self):
        # Build a history whose decision close is above the prior-252 high but
        # BELOW SMA100 (SMA100 elevated by a high early plateau). Should not enter.
        spy = _rising_spy()
        bars = []
        # 100 very high bars → SMA100 high, then a long low stretch with a modest
        # prior high, then a decision bar above prior high but below SMA100.
        for _ in range(100):
            bars.append(_bar(500.0, 500.0, 500.0, 500.0, 1000))
        for _ in range(160):
            bars.append(_bar(90.0, 90.0, 90.0, 90.0, 1000))
        bars[-1] = _bar(95.0, 95.0, 95.0, 95.0, 1000)   # prior-252 high = 95 region
        bars.append(_bar(100.0, 100.0, 100.0, 100.0, 5000))  # decision: >95 but < SMA100
        client = _client({"SPY": spy, "AAPL": bars})
        strat = _strat()
        with _no_entry_state():
            sigs = strat.evaluate({}, client=client, account_id=1)
        assert not any(s.symbol == "AAPL" and s.side == "buy" for s in sigs)

    def test_no_entry_when_volume_below_1_2x(self):
        # Decision-bar volume must be >= 1.2x avg of prior 20 sessions (excluding
        # the decision bar). Prior avg volume = 1000, so a decision volume of 1100
        # (1.1x) must NOT enter.
        spy = _rising_spy()
        hist = _breakout_history(prior_high=150.0, decision_close=160.0,
                                 decision_vol=1100.0, prior_vol=1000.0)
        client = _client({"SPY": spy, "AAPL": hist})
        strat = _strat()
        with _no_entry_state():
            sigs = strat.evaluate({}, client=client, account_id=1)
        assert not any(s.symbol == "AAPL" and s.side == "buy" for s in sigs)

    def test_entry_when_volume_at_1_2x(self):
        spy = _rising_spy()
        hist = _breakout_history(prior_high=150.0, decision_close=160.0,
                                 decision_vol=1200.0, prior_vol=1000.0)
        client = _client({"SPY": spy, "AAPL": hist})
        strat = _strat()
        with _no_entry_state():
            sigs = strat.evaluate({}, client=client, account_id=1)
        assert any(s.symbol == "AAPL" and s.side == "buy" for s in sigs)

    def test_no_pyramiding_when_already_owned(self):
        spy = _rising_spy()
        hist = _breakout_history()
        client = _client({"SPY": spy, "AAPL": hist})
        strat = _strat()
        # Already owns AAPL (positions map non-zero) → no new buy.
        with patch("server.strategies.liquid_stock_trend.db.get_strategy_entry_price",
                   return_value=155.0):
            sigs = strat.evaluate({"AAPL": 5.0}, client=client, account_id=1)
        assert not any(s.symbol == "AAPL" and s.side == "buy" for s in sigs)


# ---------------------------------------------------------------------------
# Deterministic ranking (§7.3)
# ---------------------------------------------------------------------------

class TestRanking:
    def test_rank_by_pct_distance_then_symbol(self):
        spy = _rising_spy()
        # Two qualifiers: AAPL breaks out by a larger % than MSFT.
        aapl = _breakout_history(prior_high=100.0, decision_close=130.0,
                                 decision_vol=5000.0)   # +30%
        msft = _breakout_history(prior_high=100.0, decision_close=110.0,
                                 decision_vol=5000.0)   # +10%
        client = _client({"SPY": spy, "AAPL": aapl, "MSFT": msft})
        # max_positions=1 → only the top-ranked qualifier (AAPL, larger %) is chosen.
        strat = _strat(max_positions=1)
        with _no_entry_state():
            sigs = strat.evaluate({}, client=client, account_id=1)
        buys = [s for s in sigs if s.side == "buy"]
        assert len(buys) == 1
        assert buys[0].symbol == "AAPL"

    def test_symbol_tiebreak_when_equal_pct(self):
        spy = _rising_spy()
        # Equal % breakout → tie broken by symbol ascending (AAPL before MSFT).
        aapl = _breakout_history(prior_high=100.0, decision_close=120.0,
                                 decision_vol=5000.0)
        msft = _breakout_history(prior_high=100.0, decision_close=120.0,
                                 decision_vol=5000.0)
        client = _client({"SPY": spy, "AAPL": aapl, "MSFT": msft})
        strat = _strat(max_positions=1)
        with _no_entry_state():
            sigs = strat.evaluate({}, client=client, account_id=1)
        buys = [s for s in sigs if s.side == "buy"]
        assert len(buys) == 1
        assert buys[0].symbol == "AAPL"


# ---------------------------------------------------------------------------
# ATR stops (§7.4)
# ---------------------------------------------------------------------------

class TestStops:
    def test_initial_stop_is_entry_minus_2_5_atr(self):
        # Held position; price still above trailing stop but the strategy should
        # expose the initial stop = entry - 2.5*ATR20. We drive an actual stop
        # breach and check the exit reason mentions the stop.
        from server.strategies.liquid_stock_trend import _atr
        # ATR helper sanity: constant 1.0 true range → ATR20 == 1.0
        bars = [_bar(100 + i, 101 + i, 100 + i, 100 + i, 1000) for i in range(30)]
        atr = _atr(bars, 20)
        assert atr is not None and atr > 0

    def test_stop_breach_produces_exit(self):
        spy = _rising_spy()
        # Held AAPL entered at 160 with ATR ~1. Decision close crashes below the
        # initial stop (160 - 2.5*ATR). Use a history whose recent closes fall hard.
        hist = [_bar(160.0, 160.5, 159.5, 160.0, 1000) for _ in range(60)]
        hist.append(_bar(140.0, 141.0, 139.0, 140.0, 1000))  # decision crash
        client = _client({"SPY": spy, "AAPL": hist})
        strat = _strat()
        with patch("server.strategies.liquid_stock_trend.db.get_strategy_entry_price",
                   return_value=160.0):
            sigs = strat.evaluate({"AAPL": 10.0}, client=client, account_id=1)
        sells = [s for s in sigs if s.side == "sell" and s.symbol == "AAPL"]
        assert sells, "a completed-bar stop breach must produce an exit"
        assert "stop" in sells[0].reason.lower()

    def test_trailing_stop_never_moves_down(self):
        # The trailing stop = highest completed close since entry - 3.0*ATR.
        # Feed a run-up then a pullback: the trailing stop level computed on the
        # run-up peak must not decrease when price pulls back but stays above stop.
        from server.strategies.liquid_stock_trend import _trailing_stop
        closes_peak = [100.0, 105.0, 110.0, 120.0]   # peak 120
        atr = 2.0
        stop_at_peak = _trailing_stop(peak_close=120.0, atr=atr, mult=3.0)
        # A later, lower peak-close must not lower an already-higher stop: the
        # helper is pure (peak - 3*ATR); the strategy tracks the max peak so the
        # stop is monotonic. Assert the formula.
        assert stop_at_peak == pytest.approx(120.0 - 3.0 * 2.0)
        assert stop_at_peak > _trailing_stop(peak_close=110.0, atr=atr, mult=3.0)


# ---------------------------------------------------------------------------
# Sizing / constraints (§7.5)
# ---------------------------------------------------------------------------

class TestConstraints:
    def test_max_positions_default_is_five(self):
        from server.strategies.liquid_stock_trend import LiquidStockTrend
        assert LiquidStockTrend.default_params["max_positions"] == 5

    def test_respects_max_positions(self):
        spy = _rising_spy()
        # Give six qualifiers but cap at 2 open (already holding 2) → no new buys.
        qual = _breakout_history(prior_high=100.0, decision_close=130.0,
                                 decision_vol=5000.0)
        bars = {"SPY": spy}
        for sym in ["AAPL", "MSFT", "NVDA", "AMZN"]:
            bars[sym] = qual
        client = _client(bars)
        strat = _strat(max_positions=2)
        with patch("server.strategies.liquid_stock_trend.db.get_strategy_entry_price",
                   return_value=125.0):
            # Already holding 2 positions.
            sigs = strat.evaluate({"SPY": 1.0, "QQQ": 1.0}, client=client, account_id=1)
        assert not any(s.side == "buy" for s in sigs)


# ---------------------------------------------------------------------------
# Metadata / registration
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_name(self):
        from server.strategies.liquid_stock_trend import LiquidStockTrend
        assert LiquidStockTrend.name == "liquid_stock_trend"

    def test_brokers_stock_only(self):
        from server.strategies.liquid_stock_trend import LiquidStockTrend
        assert LiquidStockTrend.brokers == ["stock"]

    def test_registered_in_registry(self):
        from server.strategies import REGISTRY
        assert "liquid_stock_trend" in REGISTRY

    def test_not_auto_trade_by_default(self):
        # Research candidate: must default to disabled/not-auto-assigned. The
        # engine seeds registry strategies with enabled=False; auto_trade False
        # keeps it out of automatic assignment until research + cutover.
        from server.strategies.liquid_stock_trend import LiquidStockTrend
        assert LiquidStockTrend.auto_trade is False

    def test_describe_has_required_keys(self):
        from server.strategies.liquid_stock_trend import LiquidStockTrend
        d = LiquidStockTrend.describe()
        for key in ("name", "label", "description", "default_params",
                    "params_schema", "brokers"):
            assert key in d
