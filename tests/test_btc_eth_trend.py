"""Tests for the BTC/ETH Spot Daily Trend strategy (Task 8, spec §8).

PURE signal-model tests: deterministic daily-candle fixtures, NO network, NO
global state. The decision candle is the LAST candle in each list. Windows the
spec says exclude the decision candle use bars[:-1].
"""
import pytest
from unittest.mock import MagicMock, patch


def _bar(o, h, l, c, v=1000.0):
    return {"o": o, "h": h, "l": l, "c": c, "v": v}


def _client(bars_by_symbol):
    client = MagicMock()

    def _get(symbol, days=0):
        return bars_by_symbol.get(symbol, [])

    client.get_recent_bars.side_effect = _get
    return client


def _strat(**params):
    from server.strategies.btc_eth_trend import BtcEthTrend
    return BtcEthTrend(dict(params))


def _no_entry_state():
    import server.strategies.btc_eth_trend as mod
    return patch.object(mod.db, "get_strategy_entry_price", return_value=None)


def _uptrend_history(n=260, start=100.0, step=1.0):
    """Strictly rising closes so EMA50 > EMA200 and the last close is a new high."""
    return [_bar(start + i * step, start + i * step, start + i * step,
                 start + i * step) for i in range(n)]


def _breakout_history(n_prior=260, prior_high=150.0, decision_close=160.0):
    """Rising prior candles (so EMA50>EMA200) whose max prior-55 high < decision."""
    bars = []
    for i in range(n_prior):
        c = 50.0 + (i * (prior_high - 50.0) / n_prior)
        bars.append(_bar(c, c, c, c))
    bars[-1] = _bar(prior_high, prior_high, prior_high, prior_high)
    bars.append(_bar(decision_close, decision_close, decision_close, decision_close))
    return bars


# ---------------------------------------------------------------------------
# Universe (§8.1)
# ---------------------------------------------------------------------------

class TestUniverse:
    def test_universe_is_btc_eth_only(self):
        from server.strategies.btc_eth_trend import BtcEthTrend
        assert BtcEthTrend.UNIVERSE == ["BTC/USDT", "ETH/USDT"]

    def test_other_symbols_ignored(self):
        # Even if a caller holds SOL/USDT, the strategy never emits signals for it.
        bars = {
            "BTC/USDT": _breakout_history(),
            "ETH/USDT": _breakout_history(),
            "SOL/USDT": _breakout_history(),
        }
        client = _client(bars)
        strat = _strat()
        with _no_entry_state():
            sigs = strat.evaluate({"SOL/USDT": 10.0}, client=client, account_id=1)
        assert not any(s.symbol == "SOL/USDT" for s in sigs)

    def test_daily_only_no_4h(self):
        # Timeframe param must not offer/claim 4h in v1.
        from server.strategies.btc_eth_trend import BtcEthTrend
        tf = BtcEthTrend.default_params.get("timeframe", "day")
        assert tf == "day"


# ---------------------------------------------------------------------------
# Entry (§8.2)
# ---------------------------------------------------------------------------

class TestEntry:
    def test_prior_55_high_excludes_decision_candle(self):
        # Control: decision close == prior-55 high → not strictly above → no entry.
        equal_hist = _breakout_history(prior_high=150.0, decision_close=150.0)
        client = _client({"BTC/USDT": equal_hist})
        strat = _strat()
        with _no_entry_state():
            sigs = strat.evaluate({}, client=client, account_id=1)
        assert not any(s.symbol == "BTC/USDT" and s.side == "buy" for s in sigs)

        # Positive: strictly above prior-55 high → entry.
        above_hist = _breakout_history(prior_high=150.0, decision_close=151.0)
        client2 = _client({"BTC/USDT": above_hist})
        strat2 = _strat()
        with _no_entry_state():
            sigs2 = strat2.evaluate({}, client=client2, account_id=1)
        assert any(s.symbol == "BTC/USDT" and s.side == "buy" for s in sigs2)

    def test_no_entry_when_ema50_below_ema200(self):
        # Downtrend then a single spike above prior-55 high: EMA50 < EMA200 blocks.
        bars = [_bar(c, c, c, c) for c in [300.0 - i for i in range(260)]]
        # final candle spikes above the prior-55 high but trend is down.
        prior55_high = max(b["h"] for b in bars[-56:-1])
        bars[-1] = _bar(prior55_high + 5, prior55_high + 5, prior55_high + 5,
                        prior55_high + 5)
        client = _client({"BTC/USDT": bars})
        strat = _strat()
        with _no_entry_state():
            sigs = strat.evaluate({}, client=client, account_id=1)
        assert not any(s.side == "buy" for s in sigs)

    def test_no_pyramiding_when_owned(self):
        client = _client({"BTC/USDT": _breakout_history()})
        strat = _strat()
        with patch("server.strategies.btc_eth_trend.db.get_strategy_entry_price",
                   return_value=155.0):
            sigs = strat.evaluate({"BTC/USDT": 0.5}, client=client, account_id=1)
        assert not any(s.symbol == "BTC/USDT" and s.side == "buy" for s in sigs)


# ---------------------------------------------------------------------------
# Exit (§8.3)
# ---------------------------------------------------------------------------

class TestExit:
    def test_exit_on_close_below_prior_20_low(self):
        # Held BTC; decision close drops below the lowest low of prior 20 candles.
        bars = [_bar(100.0, 101.0, 99.0, 100.0) for _ in range(60)]
        bars.append(_bar(90.0, 91.0, 89.0, 90.0))  # decision below prior-20 low (99)
        client = _client({"BTC/USDT": bars})
        strat = _strat()
        with patch("server.strategies.btc_eth_trend.db.get_strategy_entry_price",
                   return_value=100.0):
            sigs = strat.evaluate({"BTC/USDT": 0.5}, client=client, account_id=1)
        sells = [s for s in sigs if s.side == "sell" and s.symbol == "BTC/USDT"]
        assert sells
        assert "low" in sells[0].reason.lower() or "20" in sells[0].reason

    def test_exit_on_two_closes_below_ema200(self):
        # Rising history (EMA200 high) then last TWO closes below EMA200.
        bars = _uptrend_history(260)
        # Compute EMA200 near the end and force last two closes just below it.
        from server.strategies.btc_eth_trend import _ema
        closes = [b["c"] for b in bars]
        ema200 = _ema(closes[:-2], 200)
        assert ema200 is not None
        low = ema200 - 5.0
        bars[-2] = _bar(low, low, low - 1, low)
        bars[-1] = _bar(low, low, low - 1, low)
        client = _client({"BTC/USDT": bars})
        strat = _strat()
        with patch("server.strategies.btc_eth_trend.db.get_strategy_entry_price",
                   return_value=low + 50.0):
            sigs = strat.evaluate({"BTC/USDT": 0.5}, client=client, account_id=1)
        sells = [s for s in sigs if s.side == "sell" and s.symbol == "BTC/USDT"]
        assert sells
        assert "ema200" in sells[0].reason.lower() or "ema" in sells[0].reason.lower()

    def test_no_exit_on_single_close_below_ema200(self):
        bars = _uptrend_history(260)
        from server.strategies.btc_eth_trend import _ema
        closes = [b["c"] for b in bars]
        ema200 = _ema(closes[:-1], 200)
        low = ema200 - 5.0
        # Only the LAST close below EMA200 (one candle).
        bars[-1] = _bar(low, low, low - 1, low)
        client = _client({"BTC/USDT": bars})
        strat = _strat()
        with patch("server.strategies.btc_eth_trend.db.get_strategy_entry_price",
                   return_value=low + 50.0):
            sigs = strat.evaluate({"BTC/USDT": 0.5}, client=client, account_id=1)
        assert not any(s.side == "sell" and "ema" in s.reason.lower() for s in sigs)

    def test_exit_on_atr_trailing_stop_breach(self):
        # Isolate the ATR trailing-stop condition: the decision close must breach
        # peak_close - 3.5*ATR while staying ABOVE the prior-20 low (so the 20-low
        # rule does NOT fire) and ABOVE EMA200 (so the two-close rule does NOT fire).
        #
        # Rising history to 240 (EMA200 stays well below price and the prior-20 low
        # is high), tiny ATR (~1), peak close 240. A pullback to 233 is:
        #   below trailing stop 240 - 3.5*1 = 236.5  → breach
        #   above prior-20 low (~221)                → 20-low rule quiet
        #   above EMA200 (well under 200)            → two-close rule quiet
        bars = [_bar(100.0 + i, 100.5 + i, 99.5 + i, 100.0 + i) for i in range(141)]
        # last built close is 100+140 = 240 (peak); decision pulls back to 233.
        bars.append(_bar(233.0, 233.5, 232.5, 233.0))
        client = _client({"BTC/USDT": bars})
        strat = _strat()
        with patch("server.strategies.btc_eth_trend.db.get_strategy_entry_price",
                   return_value=180.0):
            sigs = strat.evaluate({"BTC/USDT": 0.5}, client=client, account_id=1)
        sells = [s for s in sigs if s.side == "sell" and s.symbol == "BTC/USDT"]
        assert sells
        assert "stop" in sells[0].reason.lower()


# ---------------------------------------------------------------------------
# ATR stop helpers (§8.3)
# ---------------------------------------------------------------------------

class TestStopHelpers:
    def test_initial_stop_is_3_0_atr(self):
        from server.strategies.btc_eth_trend import _initial_stop
        assert _initial_stop(entry=100.0, atr=2.0) == pytest.approx(100.0 - 3.0 * 2.0)

    def test_trailing_stop_is_3_5_atr_and_monotonic(self):
        from server.strategies.btc_eth_trend import _trailing_stop
        s_high = _trailing_stop(peak_close=120.0, atr=2.0)
        assert s_high == pytest.approx(120.0 - 3.5 * 2.0)
        # Higher peak → higher (never looser) stop.
        assert s_high > _trailing_stop(peak_close=110.0, atr=2.0)


# ---------------------------------------------------------------------------
# Sizing / precision / allocation caps (§8.4)
# ---------------------------------------------------------------------------

class TestSizingAndCaps:
    def test_default_caps(self):
        from server.strategies.btc_eth_trend import BtcEthTrend
        p = BtcEthTrend.default_params
        assert p["btc_max_alloc_pct"] == 3.0
        assert p["eth_max_alloc_pct"] == 2.0
        assert p["combined_max_alloc_pct"] == 5.0
        assert p["max_positions"] == 2
        assert p["risk_pct"] == pytest.approx(0.10)

    def test_precision_rounding_down(self):
        # Notional / price rounded DOWN to exchange precision.
        from server.strategies.btc_eth_trend import _round_qty_down
        # BTC precision 5 dp: 0.123456789 → 0.12345
        assert _round_qty_down(0.123456789, 5) == pytest.approx(0.12345)
        # never rounds up
        assert _round_qty_down(0.999999, 2) == pytest.approx(0.99)

    def test_skip_when_min_notional_exceeds_budget(self):
        # If min notional > allocation budget, skip the entry.
        from server.strategies.btc_eth_trend import _passes_min_notional
        # budget 10 USD, min notional 15 USD → fails
        assert _passes_min_notional(budget_usd=10.0, min_notional=15.0) is False
        assert _passes_min_notional(budget_usd=20.0, min_notional=15.0) is True

    def test_max_two_positions(self):
        # Two qualifiers but already holding 2 → no new buys.
        bars = {"BTC/USDT": _breakout_history(), "ETH/USDT": _breakout_history()}
        client = _client(bars)
        strat = _strat(max_positions=2)
        with patch("server.strategies.btc_eth_trend.db.get_strategy_entry_price",
                   return_value=155.0):
            sigs = strat.evaluate({"BTC/USDT": 0.5, "ETH/USDT": 1.0},
                                  client=client, account_id=1)
        assert not any(s.side == "buy" for s in sigs)


# ---------------------------------------------------------------------------
# Metadata / registration
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_name(self):
        from server.strategies.btc_eth_trend import BtcEthTrend
        assert BtcEthTrend.name == "btc_eth_trend"

    def test_brokers_crypto_only(self):
        from server.strategies.btc_eth_trend import BtcEthTrend
        assert BtcEthTrend.brokers == ["crypto"]

    def test_registered_in_registry(self):
        from server.strategies import REGISTRY
        assert "btc_eth_trend" in REGISTRY

    def test_not_auto_trade_by_default(self):
        from server.strategies.btc_eth_trend import BtcEthTrend
        assert BtcEthTrend.auto_trade is False

    def test_describe_has_required_keys(self):
        from server.strategies.btc_eth_trend import BtcEthTrend
        d = BtcEthTrend.describe()
        for key in ("name", "label", "description", "default_params",
                    "params_schema", "brokers"):
            assert key in d
