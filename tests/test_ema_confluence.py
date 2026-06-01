"""Tests for the 4-EMA Confluence strategy."""
import pytest
from unittest.mock import MagicMock


def _make_bars(closes):
    return [{"o": c, "h": c * 1.01, "l": c * 0.99, "c": c, "v": 1000} for c in closes]


def _mock_client(closes):
    client = MagicMock()
    client.get_recent_bars.return_value = _make_bars(closes)
    return client


# ---------------------------------------------------------------------------
# _ema() helper
# ---------------------------------------------------------------------------

class TestEmaHelper:
    def test_returns_none_when_insufficient_data(self):
        from server.strategies.ema_confluence import _ema
        assert _ema([100.0, 101.0], 5) is None

    def test_returns_sma_for_exactly_period_length(self):
        from server.strategies.ema_confluence import _ema
        result = _ema([100.0, 100.0, 100.0, 100.0], 4)
        assert result == pytest.approx(100.0)

    def test_ema_rises_toward_rising_price(self):
        from server.strategies.ema_confluence import _ema
        closes = [100.0] * 8 + [200.0]
        result = _ema(closes, 8)
        assert 100.0 < result < 200.0

    def test_ema_falls_toward_falling_price(self):
        from server.strategies.ema_confluence import _ema
        closes = [100.0] * 8 + [50.0]
        result = _ema(closes, 8)
        assert 50.0 < result < 100.0

    def test_returns_float(self):
        from server.strategies.ema_confluence import _ema
        result = _ema([100.0] * 10, 5)
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# EMAConfluence — buy signals
# ---------------------------------------------------------------------------

class TestEMAConfluenceBuy:
    def _bull_closes(self, n=220):
        return [100.0 + i * 0.5 for i in range(n)]

    def test_buy_signal_full_bull_score(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = self._bull_closes(220)
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 4,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        assert any(s.symbol == "AAPL" and s.side == "buy" for s in signals)

    def test_no_buy_when_min_confluence_not_met(self):
        from server.strategies.ema_confluence import EMAConfluence
        # Flat for 210 bars then a small rise — EMA200 (slow) stays above price,
        # so bear_score > 0 (mixed signal) and buy is blocked.
        # 210 flat bars at 100, then final bar at 99.5 (price drops slightly).
        # All EMAs converge to ~100, price < all EMAs → bear confluence, not bull.
        closes = [100.0] * 210 + [99.0]
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 4,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        assert not any(s.side == "buy" for s in signals)

    def test_no_buy_when_max_positions_reached(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = self._bull_closes(220)
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL", "MSFT"],
            "use_scanner": False,
            "min_confluence": 4,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 1,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({"MSFT": 1.0}, client=client)
        assert not any(s.side == "buy" for s in signals)

    def test_buy_notional_used(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = self._bull_closes(220)
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 4,
            "scaled_sizing": False,
            "notional": 750,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        buys = [s for s in signals if s.side == "buy"]
        assert buys, "expected a buy signal but got none"
        assert buys[0].notional == 750.0

    def test_scaled_sizing_score4_uses_full_notional(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = self._bull_closes(220)
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 4,
            "scaled_sizing": True,
            "notional": 1000,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        buys = [s for s in signals if s.side == "buy"]
        assert buys, "expected a buy signal but got none"
        assert buys[0].notional == pytest.approx(1000.0)

    def test_no_buy_when_mixed_signals(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = [200.0 - i * 0.3 for i in range(220)]
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 2,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        assert not any(s.side == "buy" for s in signals)

    def test_no_buy_when_bear_score_nonzero_despite_meeting_bull_count(self):
        """bear_score == 0 guard: price above 2 EMAs but below the other 2 must not buy."""
        import server.strategies.ema_confluence as mod
        from unittest.mock import patch
        from server.strategies.ema_confluence import EMAConfluence
        # Patch _ema to return controlled values: price=120 > EMA8=115 > EMA13=110 (bull 2)
        # but price=120 < EMA48=130 < EMA200=150 (bear 2). bull_score=2, bear_score=2 -> blocked.
        ema_values = {8: 115.0, 13: 110.0, 48: 130.0, 200: 150.0}
        def fake_ema(closes, period):
            return ema_values.get(period, 100.0)
        closes = [120.0] * 210
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 2,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        with patch.object(mod, "_ema", side_effect=fake_ema):
            signals = strat.evaluate({}, client=client)
        assert not any(s.side == "buy" for s in signals)

    def test_no_buy_when_already_holding(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = self._bull_closes(220)
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 4,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({"AAPL": 2.5}, client=client)
        assert not any(s.side == "buy" for s in signals)


# ---------------------------------------------------------------------------
# EMAConfluence — sell signals
# ---------------------------------------------------------------------------

class TestEMAConfluenceSell:
    def test_sell_on_bear_confluence(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = [200.0 - i * 0.5 for i in range(220)]
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 3,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({"AAPL": 10.0}, client=client)
        assert any(s.symbol == "AAPL" and s.side == "sell" for s in signals)

    def test_sell_qty_equals_held(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = [200.0 - i * 0.5 for i in range(220)]
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 3,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({"AAPL": 7.5}, client=client)
        sells = [s for s in signals if s.side == "sell"]
        assert sells, "expected a sell signal but got none"
        assert sells[0].qty == pytest.approx(7.5)

    def test_no_sell_when_not_holding(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = [200.0 - i * 0.5 for i in range(220)]
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 3,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        assert not any(s.side == "sell" for s in signals)


# ---------------------------------------------------------------------------
# EMAConfluence — edge cases
# ---------------------------------------------------------------------------

class TestEMAConfluenceEdgeCases:
    def test_skip_symbol_when_insufficient_bars(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = [100.0 + i for i in range(50)]
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 3,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        assert signals == []

    def test_bar_fetch_exception_skips_symbol(self):
        from server.strategies.ema_confluence import EMAConfluence
        client = MagicMock()
        client.get_recent_bars.side_effect = Exception("network error")
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 3,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        assert signals == []


# ---------------------------------------------------------------------------
# EMAConfluence — metadata
# ---------------------------------------------------------------------------

class TestEMAConfluenceMetadata:
    def test_strategy_name(self):
        from server.strategies.ema_confluence import EMAConfluence
        assert EMAConfluence.name == "ema_confluence"

    def test_strategy_brokers(self):
        from server.strategies.ema_confluence import EMAConfluence
        assert "stock" in EMAConfluence.brokers
        assert "crypto" in EMAConfluence.brokers

    def test_describe_has_required_keys(self):
        from server.strategies.ema_confluence import EMAConfluence
        d = EMAConfluence.describe()
        for key in ("name", "label", "description", "default_params", "params_schema", "brokers"):
            assert key in d

    def test_registered_in_registry(self):
        from server.strategies import REGISTRY
        assert "ema_confluence" in REGISTRY
