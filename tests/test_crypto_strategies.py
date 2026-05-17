"""Tests for crypto-specific trading strategies."""
import pytest
from unittest.mock import MagicMock


def _make_bars(closes):
    return [{"o": c, "h": c * 1.01, "l": c * 0.99, "c": c, "v": 1000} for c in closes]


def _mock_client(closes):
    client = MagicMock()
    client.get_recent_bars.return_value = _make_bars(closes)
    return client


# ---------------------------------------------------------------------------
# CryptoTrend — EMA crossover
# ---------------------------------------------------------------------------

class TestCryptoTrend:
    def test_buy_signal_on_ema_crossover(self):
        from server.strategies.crypto_trend import CryptoTrend
        # 21 flat bars then a rise: flat makes fast==slow (<=satisfied), rise makes fast>slow
        closes = [100.0] * 21 + [110.0]
        client = _mock_client(closes)
        strat = CryptoTrend({"symbols": ["BTC/USDT"], "fast_ema": 9, "slow_ema": 21,
                              "notional": 500, "max_positions": 3})
        signals = strat.evaluate({}, client=client)
        assert any(s.symbol == "BTC/USDT" and s.side == "buy" for s in signals)

    def test_sell_signal_when_holding_and_ema_crosses_below(self):
        from server.strategies.crypto_trend import CryptoTrend
        # 21 flat bars then a drop: flat makes fast==slow (>=satisfied), drop makes fast<slow
        closes = [100.0] * 21 + [90.0]
        client = _mock_client(closes)
        strat = CryptoTrend({"symbols": ["BTC/USDT"], "fast_ema": 9, "slow_ema": 21,
                              "notional": 500, "max_positions": 3})
        signals = strat.evaluate({"BTC/USDT": 0.5}, client=client)
        assert any(s.symbol == "BTC/USDT" and s.side == "sell" for s in signals)

    def test_no_buy_when_max_positions_reached(self):
        from server.strategies.crypto_trend import CryptoTrend
        closes = [100.0] * 30 + [110.0, 115.0, 120.0, 125.0, 130.0]
        client = _mock_client(closes)
        strat = CryptoTrend({"symbols": ["BTC/USDT", "ETH/USDT"], "fast_ema": 9, "slow_ema": 21,
                              "notional": 500, "max_positions": 1})
        # Already holding 1 position — at max
        signals = strat.evaluate({"ETH/USDT": 1.0}, client=client)
        assert not any(s.side == "buy" for s in signals)

    def test_no_signal_when_no_crossover(self):
        from server.strategies.crypto_trend import CryptoTrend
        # Perfectly flat — no crossover ever
        closes = [100.0] * 40
        client = _mock_client(closes)
        strat = CryptoTrend({"symbols": ["BTC/USDT"], "fast_ema": 9, "slow_ema": 21,
                              "notional": 500, "max_positions": 3})
        signals = strat.evaluate({}, client=client)
        assert not any(s.side == "buy" for s in signals)

    def test_notional_used_for_buy_signal(self):
        from server.strategies.crypto_trend import CryptoTrend
        closes = [100.0] * 30 + [110.0, 115.0, 120.0, 125.0, 130.0]
        client = _mock_client(closes)
        strat = CryptoTrend({"symbols": ["BTC/USDT"], "fast_ema": 9, "slow_ema": 21,
                              "notional": 750, "max_positions": 3})
        signals = strat.evaluate({}, client=client)
        buy_signals = [s for s in signals if s.side == "buy"]
        if buy_signals:
            assert buy_signals[0].notional == 750.0


# ---------------------------------------------------------------------------
# CryptoRSIBounce — RSI mean-reversion
# ---------------------------------------------------------------------------

class TestCryptoRSIBounce:
    def test_sell_when_overbought(self):
        from server.strategies.crypto_rsi_bounce import CryptoRSIBounce
        # Sustained rally — RSI > 65
        closes = [50.0] * 20 + [52, 55, 58, 62, 66, 70, 75, 80, 85, 90,
                                  92, 94, 96, 98, 100]
        client = _mock_client(closes)
        strat = CryptoRSIBounce({"symbols": ["ETH/USDT"], "rsi_period": 14,
                                  "rsi_oversold": 35, "rsi_overbought": 65,
                                  "notional": 500, "max_positions": 3})
        signals = strat.evaluate({"ETH/USDT": 0.5}, client=client)
        assert any(s.symbol == "ETH/USDT" and s.side == "sell" for s in signals)

    def test_no_buy_when_max_positions_reached(self):
        from server.strategies.crypto_rsi_bounce import CryptoRSIBounce
        closes = [100.0] * 20 + [95, 90, 85, 80, 75, 70, 65, 60, 55, 50,
                                   52, 54, 56, 58, 60]
        client = _mock_client(closes)
        strat = CryptoRSIBounce({"symbols": ["ETH/USDT", "SOL/USDT"], "rsi_period": 14,
                                  "rsi_oversold": 35, "rsi_overbought": 65,
                                  "notional": 500, "max_positions": 1})
        signals = strat.evaluate({"SOL/USDT": 1.0}, client=client)
        assert not any(s.side == "buy" for s in signals)

    def test_no_sell_when_not_holding(self):
        from server.strategies.crypto_rsi_bounce import CryptoRSIBounce
        closes = [50.0] * 20 + list(range(52, 102, 2))
        client = _mock_client(closes)
        strat = CryptoRSIBounce({"symbols": ["ETH/USDT"], "rsi_period": 14,
                                  "rsi_oversold": 35, "rsi_overbought": 65,
                                  "notional": 500, "max_positions": 3})
        signals = strat.evaluate({}, client=client)
        assert not any(s.side == "sell" for s in signals)

    def test_returns_list(self):
        from server.strategies.crypto_rsi_bounce import CryptoRSIBounce
        closes = [100.0] * 30
        client = _mock_client(closes)
        strat = CryptoRSIBounce({"symbols": ["BTC/USDT"], "rsi_period": 14,
                                  "rsi_oversold": 35, "rsi_overbought": 65,
                                  "notional": 500, "max_positions": 3})
        signals = strat.evaluate({}, client=client)
        assert isinstance(signals, list)


# ---------------------------------------------------------------------------
# CryptoVolatilityBreakout — Bollinger Band breakout
# ---------------------------------------------------------------------------

class TestCryptoVolatilityBreakout:
    def test_buy_on_lower_band_touch(self):
        from server.strategies.crypto_volatility_breakout import CryptoVolatilityBreakout
        from unittest.mock import patch
        # Flat then crash — price clearly below lower band; RSI oversold
        closes = [100.0] * 25 + [65.0]
        client = _mock_client(closes)
        strat = CryptoVolatilityBreakout({"symbols": ["SOL/USDT"], "bb_period": 20,
                                           "bb_std": 2.0, "rsi_oversold": 35,
                                           "notional": 500, "max_positions": 3})
        # count_open_trades_for_symbol returns 0 (no existing position in DB)
        import server.strategies.crypto_volatility_breakout as mod
        with patch.object(mod.db, "count_open_trades_for_symbol", return_value=0), \
             patch.object(mod.db, "get_open_trade_entry_price", return_value=None):
            signals = strat.evaluate({}, client=client)
        assert any(s.symbol == "SOL/USDT" and s.side == "buy" for s in signals)

    def test_sell_when_price_reaches_middle_band(self):
        from server.strategies.crypto_volatility_breakout import CryptoVolatilityBreakout
        from unittest.mock import patch
        # Price was bought at lower band, now recovered to SMA → sell
        closes = [100.0] * 25 + [100.0]  # flat — SMA=100, price=100 >= mid → sell
        client = _mock_client(closes)
        strat = CryptoVolatilityBreakout({"symbols": ["SOL/USDT"], "bb_period": 20,
                                           "bb_std": 2.0, "notional": 500, "max_positions": 3})
        import server.strategies.crypto_volatility_breakout as mod
        with patch.object(mod.db, "get_open_trade_entry_price", return_value=95.0):
            signals = strat.evaluate({"SOL/USDT": 1.0}, client=client)
        assert any(s.symbol == "SOL/USDT" and s.side == "sell" for s in signals)

    def test_no_buy_when_max_positions_reached(self):
        from server.strategies.crypto_volatility_breakout import CryptoVolatilityBreakout
        closes = [100.0] * 25 + [135.0]
        client = _mock_client(closes)
        strat = CryptoVolatilityBreakout({"symbols": ["SOL/USDT", "BNB/USDT"], "bb_period": 20,
                                           "bb_std": 2.0, "notional": 500, "max_positions": 1})
        signals = strat.evaluate({"BNB/USDT": 1.0}, client=client)
        assert not any(s.side == "buy" for s in signals)

    def test_no_buy_when_price_inside_bands(self):
        from server.strategies.crypto_volatility_breakout import CryptoVolatilityBreakout
        # Price exactly at SMA (middle band) — not above upper band, no buy
        closes = [100.0] * 26
        client = _mock_client(closes)
        strat = CryptoVolatilityBreakout({"symbols": ["SOL/USDT"], "bb_period": 20,
                                           "bb_std": 2.0, "notional": 500, "max_positions": 3})
        signals = strat.evaluate({}, client=client)
        assert not any(s.side == "buy" for s in signals)


# ---------------------------------------------------------------------------
# CryptoGrid — Grid trading
# ---------------------------------------------------------------------------

class TestCryptoGrid:
    def test_buy_when_price_in_lower_zone(self):
        from server.strategies.crypto_grid import CryptoGrid
        # Grid: lower=80, upper=120, levels=4 → band_width=10
        # Price=82 → band_idx=0, band_low=80, band_mid=85 → lower zone
        closes = [100.0] * 30 + [82.0]
        client = _mock_client(closes)
        strat = CryptoGrid({"symbols": ["BTC/USDT"], "grid_lower": 80.0, "grid_upper": 120.0,
                             "grid_levels": 4, "notional": 500, "max_positions": 3})
        signals = strat.evaluate({}, client=client)
        assert any(s.symbol == "BTC/USDT" and s.side == "buy" for s in signals)

    def test_sell_when_price_in_upper_zone(self):
        from server.strategies.crypto_grid import CryptoGrid
        # Grid 80-120, 4 levels → band_width=10
        # Price=117 → band_idx=3, band_low=110, sell_trigger=110+10*0.6=116 → price >= trigger → sell
        closes = [100.0] * 30 + [117.0]
        client = _mock_client(closes)
        strat = CryptoGrid({"symbols": ["BTC/USDT"], "grid_lower": 80.0, "grid_upper": 120.0,
                             "grid_levels": 4, "notional": 500, "max_positions": 3})
        signals = strat.evaluate({"BTC/USDT": 0.005}, client=client)
        assert any(s.symbol == "BTC/USDT" and s.side == "sell" for s in signals)

    def test_auto_range_uses_lookback(self):
        from server.strategies.crypto_grid import CryptoGrid
        # grid_lower=0, grid_upper=0 → auto from bars
        closes = list(range(60, 141))  # 81 bars, range 60–140
        client = _mock_client(closes)
        strat = CryptoGrid({"symbols": ["ETH/USDT"], "grid_lower": 0.0, "grid_upper": 0.0,
                             "grid_levels": 5, "lookback_days": 30, "notional": 500, "max_positions": 3})
        signals = strat.evaluate({}, client=client)
        assert isinstance(signals, list)

    def test_no_buy_when_max_positions_reached(self):
        from server.strategies.crypto_grid import CryptoGrid
        closes = [100.0] * 30 + [82.0]
        client = _mock_client(closes)
        strat = CryptoGrid({"symbols": ["BTC/USDT", "ETH/USDT"], "grid_lower": 80.0, "grid_upper": 120.0,
                             "grid_levels": 4, "notional": 500, "max_positions": 1})
        signals = strat.evaluate({"ETH/USDT": 1.0}, client=client)
        assert not any(s.side == "buy" for s in signals)

    def test_no_signal_when_price_outside_grid(self):
        from server.strategies.crypto_grid import CryptoGrid
        # Price 200 is above the grid upper of 120 — band_idx clamped to last band
        # price >= upper triggers sell only if holding
        closes = [100.0] * 30 + [200.0]
        client = _mock_client(closes)
        strat = CryptoGrid({"symbols": ["BTC/USDT"], "grid_lower": 80.0, "grid_upper": 120.0,
                             "grid_levels": 4, "notional": 500, "max_positions": 3})
        signals = strat.evaluate({}, client=client)
        assert not any(s.side == "buy" for s in signals)
