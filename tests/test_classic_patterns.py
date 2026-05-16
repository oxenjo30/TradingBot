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
        highs  = [100.0] * 7 + [110.0, 113.0, 112.5]
        lows   = [100.0] * 7 + [100.0, 110.0, 102.5]
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
