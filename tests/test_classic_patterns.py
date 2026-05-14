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
        from server.strategies.patterns.detectors import detect_all, PatternHit
        bars = _make_bars([100.0] * 30)
        results = detect_all(bars, ["candlestick", "reversal", "continuation"])
        for item in results:
            assert isinstance(item, PatternHit)
