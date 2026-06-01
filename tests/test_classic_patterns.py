"""Tests for Classic Chart Patterns strategy."""
import pytest
from unittest.mock import MagicMock


def _make_bars(closes, highs=None, lows=None, opens=None):
    bars = []
    for i, c in enumerate(closes):
        h = highs[i] if highs else c * 1.01
        l = lows[i] if lows else c * 0.99
        o = opens[i] if opens else c
        bars.append({"o": o, "h": h, "l": l, "c": c, "v": 1000})
    return bars


def _mock_client(closes, highs=None, lows=None, opens=None):
    client = MagicMock()
    client.get_recent_bars.return_value = _make_bars(closes, highs, lows, opens)
    return client


# ---------------------------------------------------------------------------
# PatternHit dataclass
# ---------------------------------------------------------------------------

class TestPatternHit:
    def test_fields_accessible(self):
        from server.strategies.patterns.detectors import PatternHit
        hit = PatternHit(name="hammer", direction="bull", confidence=0.7, category="candlestick")
        assert hit.name == "hammer"
        assert hit.direction == "bull"
        assert hit.confidence == 0.7
        assert hit.category == "candlestick"

    def test_detect_all_returns_list(self):
        from server.strategies.patterns.detectors import detect_all
        bars = _make_bars([100.0] * 30)
        result = detect_all(bars, ["candlestick"])
        assert isinstance(result, list)

    def test_detect_all_empty_categories_returns_empty(self):
        from server.strategies.patterns.detectors import detect_all
        bars = _make_bars([100.0] * 30)
        result = detect_all(bars, [])
        assert result == []

    def test_detect_all_each_item_is_pattern_hit(self):
        from server.strategies.patterns import detectors as det_mod
        from server.strategies.patterns.detectors import detect_all, PatternHit
        from unittest.mock import patch
        fake_hit = PatternHit(name="test", direction="bull", confidence=0.7, category="candlestick")
        bars = _make_bars([100.0] * 30)
        with patch.object(det_mod, "detect_bullish_engulfing", return_value=fake_hit):
            results = detect_all(bars, ["candlestick"])
        assert len(results) >= 1
        for item in results:
            assert isinstance(item, PatternHit)


# ---------------------------------------------------------------------------
# Candlestick detectors
# ---------------------------------------------------------------------------

class TestCandlestickDetectors:
    def test_bullish_engulfing_detected(self):
        from server.strategies.patterns.detectors import detect_bullish_engulfing
        # bar[-2]: bearish (open 105, close 100); bar[-1]: bullish wrapping it (open 99, close 107)
        bars = _make_bars(
            closes=[100.0] * 8 + [100.0, 107.0],
            opens= [100.0] * 8 + [105.0, 99.0],
        )
        result = detect_bullish_engulfing(bars)
        assert result is not None
        assert result.direction == "bull"
        assert result.confidence == 0.7

    def test_bullish_engulfing_not_detected_when_not_wrapping(self):
        from server.strategies.patterns.detectors import detect_bullish_engulfing
        # bar[-1] is bullish but doesn't wrap bar[-2]
        bars = _make_bars(
            closes=[100.0] * 8 + [100.0, 102.0],
            opens= [100.0] * 8 + [105.0, 101.0],
        )
        result = detect_bullish_engulfing(bars)
        assert result is None

    def test_bearish_engulfing_detected(self):
        from server.strategies.patterns.detectors import detect_bearish_engulfing
        # bar[-2]: bullish (open 100, close 105); bar[-1]: bearish wrapping it (open 106, close 99)
        bars = _make_bars(
            closes=[100.0] * 8 + [105.0, 99.0],
            opens= [100.0] * 8 + [100.0, 106.0],
        )
        result = detect_bearish_engulfing(bars)
        assert result is not None
        assert result.direction == "bear"
        assert result.confidence == 0.7

    def test_hammer_detected(self):
        from server.strategies.patterns.detectors import detect_hammer
        # Downtrend: 10 bars declining from 110 to 100 (price < SMA10 = ~105)
        # Last bar: open=100, close=101 (body=1), low=96 (lower_wick=4 >= 2*1), high=101.2 (upper_wick=0.2 <= 0.3*1)
        closes = [110.0 - i for i in range(9)] + [101.0]
        opens  = [110.0 - i for i in range(9)] + [100.0]
        highs  = [c * 1.005 for c in closes[:-1]] + [101.2]
        lows   = [c * 0.995 for c in closes[:-1]] + [96.0]
        bars = _make_bars(closes, highs=highs, lows=lows, opens=opens)
        result = detect_hammer(bars)
        assert result is not None
        assert result.direction == "bull"
        assert result.confidence == 0.7

    def test_hammer_not_in_uptrend(self):
        from server.strategies.patterns.detectors import detect_hammer
        # Uptrend: 10 bars rising 100->109 (price > SMA10 ~104.5), hammer geometry on last bar
        closes = [100.0 + i for i in range(9)] + [109.0]
        opens  = [100.0 + i for i in range(9)] + [108.0]
        highs  = [c * 1.005 for c in closes[:-1]] + [109.2]
        lows   = [c * 0.995 for c in closes[:-1]] + [104.0]
        bars = _make_bars(closes, highs=highs, lows=lows, opens=opens)
        result = detect_hammer(bars)
        assert result is None

    def test_shooting_star_detected(self):
        from server.strategies.patterns.detectors import detect_shooting_star
        # Uptrend: 10 bars rising. Last bar: open=109, close=108 (body=1), high=113 (upper_wick=4), low=107.7 (lower_wick=0.3)
        closes = [100.0 + i for i in range(9)] + [108.0]
        opens  = [100.0 + i for i in range(9)] + [109.0]
        highs  = [c * 1.005 for c in closes[:-1]] + [113.0]
        lows   = [c * 0.995 for c in closes[:-1]] + [107.7]
        bars = _make_bars(closes, highs=highs, lows=lows, opens=opens)
        result = detect_shooting_star(bars)
        assert result is not None
        assert result.direction == "bear"
        assert result.confidence == 0.7

    def test_morning_star_detected(self):
        from server.strategies.patterns.detectors import detect_morning_star
        # bar[-3]: big bearish (open=110, close=100, range=10, body=10 >= 0.6*10)
        # bar[-2]: small body (open=99, close=100, range=5, body=1 <= 0.3*5)
        # bar[-1]: bullish, close=107 > midpoint of bar[-3] = (110+100)/2=105
        closes = [110.0] * 7 + [100.0, 100.0, 107.0]
        opens  = [110.0] * 7 + [110.0, 99.0,  101.0]
        highs  = [110.0] * 7 + [110.0, 101.0, 107.5]
        lows   = [110.0] * 7 + [100.0, 97.0,  100.5]
        bars = _make_bars(closes, highs=highs, lows=lows, opens=opens)
        result = detect_morning_star(bars)
        assert result is not None
        assert result.direction == "bull"

    def test_evening_star_detected(self):
        from server.strategies.patterns.detectors import detect_evening_star
        # bar[-3]: big bullish (open=100, close=110, range=10, body=10)
        # bar[-2]: small body  (open=111, close=112, range=5, body=1)
        # bar[-1]: bearish, close=103 < midpoint of bar[-3] = (100+110)/2=105
        closes = [100.0] * 7 + [110.0, 112.0, 103.0]
        opens  = [100.0] * 7 + [100.0, 111.0, 112.0]
        highs  = [100.0] * 7 + [110.0, 114.0, 112.5]  # bar[-2] range=5 (114-109), body=1
        lows   = [100.0] * 7 + [100.0, 109.0, 102.5]
        bars = _make_bars(closes, highs=highs, lows=lows, opens=opens)
        result = detect_evening_star(bars)
        assert result is not None
        assert result.direction == "bear"

    def test_doji_detected_bull_in_downtrend(self):
        from server.strategies.patterns.detectors import detect_doji
        # Downtrend: SMA10 ~ 105, last close=99 (price < SMA) -> bull doji
        closes = [110.0 - i for i in range(9)] + [99.0]
        opens  = list(closes[:-1]) + [99.1]   # tiny body
        highs  = [c * 1.01 for c in closes[:-1]] + [103.0]
        lows   = [c * 0.99 for c in closes[:-1]] + [95.0]
        bars = _make_bars(closes, highs=highs, lows=lows, opens=opens)
        result = detect_doji(bars)
        assert result is not None
        assert result.direction == "bull"
        assert result.confidence == 0.4

    def test_doji_not_detected_when_body_too_large(self):
        from server.strategies.patterns.detectors import detect_doji
        # Last bar: open=100, close=103 (body=3), high=104, low=99 (range=5). 3 > 0.05*5=0.25 -> not doji
        closes = [100.0] * 9 + [103.0]
        opens  = list(closes[:-1]) + [100.0]
        highs  = [c * 1.01 for c in closes[:-1]] + [104.0]
        lows   = [c * 0.99 for c in closes[:-1]] + [99.0]
        bars = _make_bars(closes, highs=highs, lows=lows, opens=opens)
        result = detect_doji(bars)
        assert result is None

    def test_detect_all_candlestick_category_only(self):
        from server.strategies.patterns.detectors import detect_all
        bars = _make_bars([100.0] * 30)
        result = detect_all(bars, ["candlestick"])
        for hit in result:
            assert hit.category == "candlestick"

    def test_detector_exception_does_not_crash_detect_all(self):
        from server.strategies.patterns import detectors as det_mod
        from server.strategies.patterns.detectors import detect_all
        from unittest.mock import patch
        bars = _make_bars([100.0] * 30)
        with patch.object(det_mod, "detect_bullish_engulfing", side_effect=Exception("boom")):
            result = detect_all(bars, ["candlestick"])
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Reversal detectors
# ---------------------------------------------------------------------------

class TestReversalDetectors:
    def test_double_bottom_detected(self):
        from server.strategies.patterns.detectors import detect_double_bottom
        # Two troughs at ~90, neckline ~100, current price 101 (above neckline)
        closes = [100.0] * 10 + [95.0, 92.0, 90.0, 92.0, 95.0] + \
                 [100.0] * 10 + [95.0, 92.0, 90.5, 92.0, 95.0] + \
                 [100.0] * 10 + [101.0]
        bars = _make_bars(closes)
        result = detect_double_bottom(bars)
        assert result is not None
        assert result.direction == "bull"
        assert result.confidence == 1.0

    def test_double_top_detected(self):
        from server.strategies.patterns.detectors import detect_double_top
        # Two peaks at ~110, neckline ~100, current price 99 (below neckline)
        closes = [100.0] * 10 + [105.0, 108.0, 110.0, 108.0, 105.0] + \
                 [100.0] * 10 + [105.0, 108.0, 110.5, 108.0, 105.0] + \
                 [100.0] * 10 + [99.0]
        bars = _make_bars(closes)
        result = detect_double_top(bars)
        assert result is not None
        assert result.direction == "bear"
        assert result.confidence == 1.0

    def test_triple_bottom_detected(self):
        from server.strategies.patterns.detectors import detect_triple_bottom
        # Three troughs near 90, neckline ~100, price breaks above
        closes = ([100.0] * 5 + [95.0, 90.0, 95.0] +
                  [100.0] * 5 + [95.0, 90.5, 95.0] +
                  [100.0] * 5 + [95.0, 90.2, 95.0] +
                  [100.0] * 5 + [101.0])
        bars = _make_bars(closes)
        result = detect_triple_bottom(bars)
        assert result is not None
        assert result.direction == "bull"
        assert result.confidence == 1.0

    def test_triple_top_detected(self):
        from server.strategies.patterns.detectors import detect_triple_top
        # Three peaks near 110, neckline ~100, price breaks below
        closes = ([100.0] * 5 + [105.0, 110.0, 105.0] +
                  [100.0] * 5 + [105.0, 110.5, 105.0] +
                  [100.0] * 5 + [105.0, 110.2, 105.0] +
                  [100.0] * 5 + [99.0])
        bars = _make_bars(closes)
        result = detect_triple_top(bars)
        assert result is not None
        assert result.direction == "bear"
        assert result.confidence == 1.0

    def test_head_and_shoulders_detected(self):
        from server.strategies.patterns.detectors import detect_head_and_shoulders
        # LS=108, trough1=100, Head=115, trough2=100, RS=108.5, neckline~100, current=99
        closes = ([100.0] * 3 +
                  [104.0, 108.0, 104.0] +   # left shoulder
                  [100.0] * 3 +              # trough 1
                  [108.0, 112.0, 115.0, 112.0, 108.0] +  # head
                  [100.0] * 3 +              # trough 2
                  [104.0, 108.5, 104.0] +    # right shoulder
                  [100.0] * 3 + [99.0])
        bars = _make_bars(closes)
        result = detect_head_and_shoulders(bars)
        assert result is not None
        assert result.direction == "bear"
        assert result.confidence == 1.0

    def test_inverse_head_and_shoulders_detected(self):
        from server.strategies.patterns.detectors import detect_inverse_head_and_shoulders
        # LS=92, peak1=100, Head=85, peak2=100, RS=91.5, neckline~100, current=101
        closes = ([100.0] * 3 +
                  [96.0, 92.0, 96.0] +       # left shoulder
                  [100.0] * 3 +              # peak 1
                  [92.0, 88.0, 85.0, 88.0, 92.0] +  # head
                  [100.0] * 3 +              # peak 2
                  [96.0, 91.5, 96.0] +       # right shoulder
                  [100.0] * 3 + [101.0])
        bars = _make_bars(closes)
        result = detect_inverse_head_and_shoulders(bars)
        assert result is not None
        assert result.direction == "bull"
        assert result.confidence == 1.0

    def test_v_bottom_detected(self):
        from server.strategies.patterns.detectors import detect_v_bottom
        # 15 bars: bars[-15] close=100, bars[-10:-5] min around 90 (decline>=8%),
        # bars[-1] close=99 (recovery>=8% from 90)
        closes = ([100.0] +          # bars[-15]
                  [97.0, 94.0, 92.0, 91.0] +  # bars[-14:-10]
                  [90.0, 90.5, 91.0, 92.0, 93.0] +  # bars[-10:-5] min=90
                  [94.0, 95.0, 96.0, 97.5, 99.0])    # bars[-5:] recovery
        bars = _make_bars(closes)
        result = detect_v_bottom(bars)
        assert result is not None
        assert result.direction == "bull"
        assert result.confidence == 0.4

    def test_v_bottom_not_detected_when_decline_too_small(self):
        from server.strategies.patterns.detectors import detect_v_bottom
        # Only 3% decline - below 8% threshold
        closes = ([100.0] +
                  [99.0, 98.5, 98.0, 97.5] +
                  [97.0, 97.5, 98.0, 98.5, 99.0] +
                  [99.5, 100.0, 100.5, 101.0, 102.0])
        bars = _make_bars(closes)
        result = detect_v_bottom(bars)
        assert result is None

    def test_double_bottom_requires_neckline_break(self):
        from server.strategies.patterns.detectors import detect_double_bottom
        # Two troughs at ~90, neckline ~100, but current price is only 98 (below neckline)
        closes = ([100.0] * 10 + [95.0, 92.0, 90.0, 92.0, 95.0] +
                  [100.0] * 10 + [95.0, 92.0, 90.5, 92.0, 95.0] +
                  [100.0] * 5 + [98.0])
        bars = _make_bars(closes)
        result = detect_double_bottom(bars)
        assert result is None


# ---------------------------------------------------------------------------
# Continuation detectors
# ---------------------------------------------------------------------------

class TestContinuationDetectors:
    def test_bull_flag_detected(self):
        from server.strategies.patterns.detectors import detect_bull_flag
        # Upleg bars[-25:-15]: from 100 to 108 (>=5% gain)
        # Channel bars[-14:]: slight pullback from 108 to 105 (retracement < 40% of 8-pt move)
        upleg   = [100.0 + i * 0.8 for i in range(11)]   # 100 -> 108
        channel = [108.0 - i * 0.21 for i in range(14)]  # 108 -> 105.1 (retracement ~2.9/8=36%)
        closes = upleg + channel
        bars = _make_bars(closes)
        result = detect_bull_flag(bars)
        assert result is not None
        assert result.direction == "bull"
        assert result.confidence == 0.7

    def test_bear_flag_detected(self):
        from server.strategies.patterns.detectors import detect_bear_flag
        # Downleg bars[-25:-15]: from 100 to 92 (>=5% drop)
        # Channel bars[-14:]: slight bounce from 92 to 95 (retracement ~3/8=37.5% < 40%)
        downleg = [100.0 - i * 0.8 for i in range(11)]   # 100 -> 92
        channel = [92.0 + i * 0.21 for i in range(14)]   # 92 -> 94.9
        closes = downleg + channel
        bars = _make_bars(closes)
        result = detect_bear_flag(bars)
        assert result is not None
        assert result.direction == "bear"
        assert result.confidence == 0.7

    def test_ascending_triangle_detected(self):
        from server.strategies.patterns.detectors import detect_ascending_triangle
        # Flat resistance near 110, rising lows
        highs  = [110.0, 108.0, 110.2, 107.0, 110.1, 106.0, 110.3, 105.0, 110.0, 104.0] * 4
        lows   = [95.0,  96.0,  97.0,  98.0,  99.0,  100.0, 101.0, 102.0, 103.0, 104.0] * 4
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
        bars = _make_bars(closes, highs=highs, lows=lows)
        result = detect_ascending_triangle(bars)
        assert result is not None
        assert result.direction == "bull"
        assert result.confidence == 0.7

    def test_descending_triangle_detected(self):
        from server.strategies.patterns.detectors import detect_descending_triangle
        # Flat support near 90, falling highs
        lows   = [90.0, 91.0, 90.2, 91.5, 90.1, 91.0, 90.3, 91.2, 90.0, 90.5] * 4
        highs  = [115.0, 114.0, 113.0, 112.0, 111.0, 110.0, 109.0, 108.0, 107.0, 106.0] * 4
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
        bars = _make_bars(closes, highs=highs, lows=lows)
        result = detect_descending_triangle(bars)
        assert result is not None
        assert result.direction == "bear"
        assert result.confidence == 0.7

    def test_symmetrical_triangle_detected(self):
        from server.strategies.patterns.detectors import detect_symmetrical_triangle
        # Converging: highs falling from 115->105, lows rising from 85->95
        highs  = [115.0 - i * 0.25 for i in range(40)]
        lows   = [85.0  + i * 0.25 for i in range(40)]
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
        bars = _make_bars(closes, highs=highs, lows=lows)
        result = detect_symmetrical_triangle(bars)
        assert result is not None
        assert result.confidence == 0.7

    def test_pennant_detected(self):
        from server.strategies.patterns.detectors import detect_pennant
        # bars[-10:-5]: strong move up >=5%; bars[-5:]: tight consolidation
        pre = [100.0] * 25
        move = [100.0 + i * 1.1 for i in range(6)]  # 100 -> 105.5 (5.5%)
        tight = [105.5, 105.6, 105.4, 105.5, 105.3]  # tight range
        closes = pre + move + tight
        highs = [c * 1.01 for c in closes[:-5]] + [105.7, 105.8, 105.6, 105.7, 105.5]
        lows  = [c * 0.99 for c in closes[:-5]] + [105.3, 105.4, 105.2, 105.3, 105.1]
        bars = _make_bars(closes, highs=highs, lows=lows)
        result = detect_pennant(bars)
        assert result is not None
        assert result.direction == "bull"
        assert result.confidence == 0.4

    def test_rising_wedge_detected(self):
        from server.strategies.patterns.detectors import detect_rising_wedge
        # Both highs and lows rise, but highs rise faster
        highs = [100.0 + i * 1.2 for i in range(20)]   # slope 1.2
        lows  = [95.0  + i * 0.6 for i in range(20)]   # slope 0.6 (lows rise slower)
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
        bars = _make_bars(closes, highs=highs, lows=lows)
        result = detect_rising_wedge(bars)
        assert result is not None
        assert result.direction == "bear"
        assert result.confidence == 0.7

    def test_falling_wedge_detected(self):
        from server.strategies.patterns.detectors import detect_falling_wedge
        # Both highs and lows fall, but lows fall faster
        highs = [120.0 - i * 0.6 for i in range(20)]   # slope -0.6
        lows  = [115.0 - i * 1.2 for i in range(20)]   # slope -1.2 (lows fall faster)
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
        bars = _make_bars(closes, highs=highs, lows=lows)
        result = detect_falling_wedge(bars)
        assert result is not None
        assert result.direction == "bull"
        assert result.confidence == 0.7

    def test_bull_flag_not_detected_when_retracement_too_deep(self):
        from server.strategies.patterns.detectors import detect_bull_flag
        # Upleg 100->108 (+8), then channel retraces more than 40% (>3.2 pts)
        upleg   = [100.0 + i * 0.8 for i in range(11)]   # 100 -> 108
        channel = [108.0 - i * 0.35 for i in range(14)]  # 108 -> 103.1 (retracement ~4.9/8=61%)
        closes = upleg + channel
        bars = _make_bars(closes)
        result = detect_bull_flag(bars)
        assert result is None


# ---------------------------------------------------------------------------
# ClassicPatterns strategy
# ---------------------------------------------------------------------------

class TestClassicPatternsStrategy:
    def _uptrend_closes(self, n=250):
        """Rising price series: all 4 EMAs below price, EMA200 well below."""
        return [100.0 + i * 0.3 for i in range(n)]

    def _downtrend_closes(self, n=250):
        """Falling price series: all EMAs above price."""
        return [200.0 - i * 0.3 for i in range(n)]

    def test_buy_signal_emitted_for_bull_pattern_in_uptrend(self):
        """A confirmed bull hit in uptrend (price > EMA200) should produce a buy."""
        import server.strategies.chart_patterns as mod
        from server.strategies.chart_patterns import ClassicPatterns
        from server.strategies.patterns.detectors import PatternHit
        from unittest.mock import patch
        closes = self._uptrend_closes(250)
        client = _mock_client(closes)
        strat = ClassicPatterns({
            "symbols": ["AAPL"], "use_scanner": False,
            "enable_candlestick": True, "enable_reversal": False, "enable_continuation": False,
            "min_confidence": 0.7, "scaled_sizing": False, "notional": 500,
            "ema_exit": "48", "max_positions": 5,
        })
        fake_hit = PatternHit("hammer", "bull", 0.7, "candlestick")
        with patch("server.strategies.chart_patterns.detect_all", return_value=[fake_hit]):
            signals = strat.evaluate({}, client=client)
        buys = [s for s in signals if s.side == "buy"]
        assert buys, "expected a buy signal but got none"
        assert buys[0].symbol == "AAPL"

    def test_no_buy_when_price_below_ema200(self):
        """Bull pattern but price < EMA200 → trend filter blocks buy."""
        from server.strategies.chart_patterns import ClassicPatterns
        from server.strategies.patterns.detectors import PatternHit
        from unittest.mock import patch
        closes = self._downtrend_closes(250)
        client = _mock_client(closes)
        strat = ClassicPatterns({
            "symbols": ["AAPL"], "use_scanner": False,
            "enable_candlestick": True, "enable_reversal": False, "enable_continuation": False,
            "min_confidence": 0.7, "scaled_sizing": False, "notional": 500,
            "ema_exit": "48", "max_positions": 5,
        })
        fake_hit = PatternHit("hammer", "bull", 0.7, "candlestick")
        with patch("server.strategies.chart_patterns.detect_all", return_value=[fake_hit]):
            signals = strat.evaluate({}, client=client)
        assert not any(s.side == "buy" for s in signals)

    def test_no_buy_below_min_confidence(self):
        """Bull hit confidence 0.4 with min_confidence=0.7 should not buy."""
        from server.strategies.chart_patterns import ClassicPatterns
        from server.strategies.patterns.detectors import PatternHit
        from unittest.mock import patch
        closes = self._uptrend_closes(250)
        client = _mock_client(closes)
        strat = ClassicPatterns({
            "symbols": ["AAPL"], "use_scanner": False,
            "enable_candlestick": True, "enable_reversal": False, "enable_continuation": False,
            "min_confidence": 0.7, "scaled_sizing": False, "notional": 500,
            "ema_exit": "48", "max_positions": 5,
        })
        fake_hit = PatternHit("doji", "bull", 0.4, "candlestick")
        with patch("server.strategies.chart_patterns.detect_all", return_value=[fake_hit]):
            signals = strat.evaluate({}, client=client)
        assert not any(s.side == "buy" for s in signals)

    def test_scaled_sizing_uses_confidence(self):
        """scaled_sizing=True with confidence 0.7 → notional * 0.7."""
        from server.strategies.chart_patterns import ClassicPatterns
        from server.strategies.patterns.detectors import PatternHit
        from unittest.mock import patch
        closes = self._uptrend_closes(250)
        client = _mock_client(closes)
        strat = ClassicPatterns({
            "symbols": ["AAPL"], "use_scanner": False,
            "enable_candlestick": True, "enable_reversal": False, "enable_continuation": False,
            "min_confidence": 0.7, "scaled_sizing": True, "notional": 1000,
            "ema_exit": "48", "max_positions": 5,
        })
        fake_hit = PatternHit("hammer", "bull", 0.7, "candlestick")
        with patch("server.strategies.chart_patterns.detect_all", return_value=[fake_hit]):
            signals = strat.evaluate({}, client=client)
        buys = [s for s in signals if s.side == "buy"]
        assert buys, "expected a buy signal"
        assert buys[0].notional == pytest.approx(700.0)

    def test_highest_confidence_hit_wins(self):
        """When multiple bull hits pass filter, the highest-confidence one drives sizing."""
        from server.strategies.chart_patterns import ClassicPatterns
        from server.strategies.patterns.detectors import PatternHit
        from unittest.mock import patch
        closes = self._uptrend_closes(250)
        client = _mock_client(closes)
        strat = ClassicPatterns({
            "symbols": ["AAPL"], "use_scanner": False,
            "enable_candlestick": True, "enable_reversal": True, "enable_continuation": False,
            "min_confidence": 0.7, "scaled_sizing": True, "notional": 1000,
            "ema_exit": "48", "max_positions": 5,
        })
        hits = [
            PatternHit("hammer", "bull", 0.7, "candlestick"),
            PatternHit("double_bottom", "bull", 1.0, "reversal"),
        ]
        with patch("server.strategies.chart_patterns.detect_all", return_value=hits):
            signals = strat.evaluate({}, client=client)
        buys = [s for s in signals if s.side == "buy"]
        assert buys, "expected a buy signal"
        assert buys[0].notional == pytest.approx(1000.0)  # 1.0 confidence → full notional

    def test_sell_on_bear_pattern_when_holding(self):
        """Bear pattern hit while holding → sell (no EMA200 check on exits)."""
        from server.strategies.chart_patterns import ClassicPatterns
        from server.strategies.patterns.detectors import PatternHit
        from unittest.mock import patch
        closes = self._uptrend_closes(250)
        client = _mock_client(closes)
        strat = ClassicPatterns({
            "symbols": ["AAPL"], "use_scanner": False,
            "enable_candlestick": True, "enable_reversal": False, "enable_continuation": False,
            "min_confidence": 0.7, "scaled_sizing": False, "notional": 500,
            "ema_exit": "48", "max_positions": 5,
        })
        fake_hit = PatternHit("bearish_engulfing", "bear", 0.7, "candlestick")
        with patch("server.strategies.chart_patterns.detect_all", return_value=[fake_hit]):
            signals = strat.evaluate({"AAPL": 10.0}, client=client)
        sells = [s for s in signals if s.side == "sell"]
        assert sells, "expected a sell signal"
        assert sells[0].qty == pytest.approx(10.0)

    def test_sell_on_ema_exit_when_holding(self):
        """Price below EMA48 while holding → sell with EMA reason string."""
        from server.strategies.chart_patterns import ClassicPatterns
        from unittest.mock import patch
        closes = self._downtrend_closes(250)
        client = _mock_client(closes)
        strat = ClassicPatterns({
            "symbols": ["AAPL"], "use_scanner": False,
            "enable_candlestick": True, "enable_reversal": False, "enable_continuation": False,
            "min_confidence": 0.7, "scaled_sizing": False, "notional": 500,
            "ema_exit": "48", "max_positions": 5,
        })
        with patch("server.strategies.chart_patterns.detect_all", return_value=[]):
            signals = strat.evaluate({"AAPL": 5.0}, client=client)
        sells = [s for s in signals if s.side == "sell"]
        assert sells, "expected a sell on EMA48 cross"
        assert "EMA48" in sells[0].reason and "trend invalidated" in sells[0].reason

    def test_no_buy_when_max_positions_reached(self):
        from server.strategies.chart_patterns import ClassicPatterns
        from server.strategies.patterns.detectors import PatternHit
        from unittest.mock import patch
        closes = self._uptrend_closes(250)
        client = _mock_client(closes)
        strat = ClassicPatterns({
            "symbols": ["AAPL", "MSFT"], "use_scanner": False,
            "enable_candlestick": True, "enable_reversal": False, "enable_continuation": False,
            "min_confidence": 0.7, "scaled_sizing": False, "notional": 500,
            "ema_exit": "48", "max_positions": 1,
        })
        fake_hit = PatternHit("hammer", "bull", 0.7, "candlestick")
        with patch("server.strategies.chart_patterns.detect_all", return_value=[fake_hit]):
            signals = strat.evaluate({"MSFT": 1.0}, client=client)
        assert not any(s.side == "buy" for s in signals)

    def test_skip_symbol_when_insufficient_bars(self):
        from server.strategies.chart_patterns import ClassicPatterns
        closes = [100.0 + i for i in range(50)]  # only 50 bars — not enough for EMA200
        client = _mock_client(closes)
        strat = ClassicPatterns({
            "symbols": ["AAPL"], "use_scanner": False,
            "enable_candlestick": True, "enable_reversal": True, "enable_continuation": True,
            "min_confidence": 0.7, "scaled_sizing": False, "notional": 500,
            "ema_exit": "48", "max_positions": 5,
        })
        signals = strat.evaluate({}, client=client)
        assert signals == []

    def test_buy_reason_string_format(self):
        """Buy reason must contain pattern name, conf %, price, EMA200, and notional."""
        from server.strategies.chart_patterns import ClassicPatterns
        from server.strategies.patterns.detectors import PatternHit
        from unittest.mock import patch
        closes = self._uptrend_closes(250)
        client = _mock_client(closes)
        strat = ClassicPatterns({
            "symbols": ["AAPL"], "use_scanner": False,
            "enable_candlestick": True, "enable_reversal": False, "enable_continuation": False,
            "min_confidence": 0.7, "scaled_sizing": False, "notional": 500,
            "ema_exit": "48", "max_positions": 5,
        })
        fake_hit = PatternHit("hammer", "bull", 0.7, "candlestick")
        with patch("server.strategies.chart_patterns.detect_all", return_value=[fake_hit]):
            signals = strat.evaluate({}, client=client)
        buys = [s for s in signals if s.side == "buy"]
        assert buys
        reason = buys[0].reason
        assert "hammer" in reason
        assert "70%" in reason
        assert "EMA200" in reason
        assert "notional" in reason.lower() or "$" in reason

    def test_strategy_metadata(self):
        from server.strategies.chart_patterns import ClassicPatterns
        assert ClassicPatterns.name == "classic_patterns"
        assert "stock" in ClassicPatterns.brokers
        assert "crypto" in ClassicPatterns.brokers

    def test_registered_in_registry(self):
        from server.strategies import REGISTRY
        assert "classic_patterns" in REGISTRY
