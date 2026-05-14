# Classic Chart Patterns Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `ClassicPatterns` strategy that detects 21 classic chart patterns across candlestick, reversal, and continuation categories and trades when a pattern aligns with the EMA200 trend.

**Architecture:** Two new files — `server/strategies/patterns/detectors.py` holds the `PatternHit` dataclass and all 21 standalone detector functions; `server/strategies/chart_patterns.py` holds the `ClassicPatterns` strategy class that calls `detect_all()`, applies the EMA200 trend filter, scores hits, and emits Signals. One registration change in `server/strategies/__init__.py` adds the strategy to the REGISTRY.

**Tech Stack:** Python 3.11, dataclasses, pytest — no new dependencies.

---

## File Map

| File | Action |
|------|--------|
| `server/strategies/patterns/__init__.py` | Create (empty package marker) |
| `server/strategies/patterns/detectors.py` | Create — `PatternHit` dataclass + `detect_all()` + 21 detectors |
| `server/strategies/chart_patterns.py` | Create — `ClassicPatterns` strategy |
| `server/strategies/__init__.py` | Modify — add import + REGISTRY entry |
| `tests/test_classic_patterns.py` | Create — full test suite |

---

## Background — Patterns You Are Implementing

Read this section carefully. All detector functions return `PatternHit | None`. The `PatternHit` dataclass:

```python
@dataclass
class PatternHit:
    name: str
    direction: Literal["bull", "bear"]
    confidence: float   # 0.4, 0.7, or 1.0
    category: str       # "candlestick", "reversal", "continuation"
```

Bars are `list[dict]` where each bar has keys `"o"`, `"h"`, `"l"`, `"c"`, `"v"`. Most recent bar is `bars[-1]`.

### Candlestick detectors (all return confidence 0.7 except doji=0.4)

| Function | Rule |
|----------|------|
| `detect_bullish_engulfing(bars)` | `bars[-1]` bullish body fully wraps `bars[-2]` bearish body: `open[-2] > close[-2]` (bear candle) and `open[-1] < close[-2]` and `close[-1] > open[-2]` |
| `detect_bearish_engulfing(bars)` | `bars[-1]` bearish body fully wraps `bars[-2]` bullish body: `open[-2] < close[-2]` (bull candle) and `open[-1] > close[-2]` and `close[-1] < open[-2]` |
| `detect_hammer(bars)` | Last bar: body = abs(close - open); lower_wick = min(open,close) - low; upper_wick = high - max(open,close). Requires: lower_wick >= 2*body, upper_wick <= 0.3*body, body > 0, price < 10-bar SMA of closes |
| `detect_shooting_star(bars)` | Same geometry but inverted: upper_wick >= 2*body, lower_wick <= 0.3*body, body > 0, price > 10-bar SMA of closes |
| `detect_morning_star(bars)` | 3-bar pattern: bar[-3] large bearish (body >= 0.6*(high-low)); bar[-2] small body (body <= 0.3*(high-low)); bar[-1] bullish with close above midpoint of bar[-3] (midpoint = (open[-3]+close[-3])/2) |
| `detect_evening_star(bars)` | 3-bar pattern: bar[-3] large bullish (body >= 0.6*(high-low)); bar[-2] small body (body <= 0.3*(high-low)); bar[-1] bearish with close below midpoint of bar[-3] |
| `detect_doji(bars)` | Last bar: abs(close - open) <= 0.05 * (high - low) AND (high - low) > 0. Direction: bull if price < 10-bar SMA, else bear. Confidence 0.4 |

### Reversal detectors (all return confidence 1.0 except v_bottom=0.4)

| Function | Rule |
|----------|------|
| `detect_double_bottom(bars)` | Use last 60 bars. Find two local troughs (local min in window of ±3 bars) at least 5 bars apart, within 2% of each other: `abs(t1 - t2) / max(t1, t2) <= 0.02`. Neckline = highest close between the two trough indices. Confirmed if `bars[-1]["c"] > neckline` |
| `detect_double_top(bars)` | Same structure but two peaks (local max), within 2% of each other. Neckline = lowest close between the two peak indices. Confirmed if `bars[-1]["c"] < neckline` |
| `detect_triple_bottom(bars)` | Use last 60 bars. Three local troughs all within 2% of the lowest trough, each pair at least 5 bars apart. Neckline = highest close among all bars between first and last trough index. Confirmed if `bars[-1]["c"] > neckline` |
| `detect_triple_top(bars)` | Three local peaks all within 2% of the highest peak, each pair at least 5 bars apart. Neckline = lowest close between first and last peak index. Confirmed if `bars[-1]["c"] < neckline` |
| `detect_head_and_shoulders(bars)` | Use last 60 bars. Find left_shoulder (local max), head (higher local max after left_shoulder), right_shoulder (local max after head, within 3% of left_shoulder height). Neckline = average of the two troughs between the three peaks. Confirmed if `bars[-1]["c"] < neckline` |
| `detect_inverse_head_and_shoulders(bars)` | Mirror: left_shoulder (local min), head (lower local min), right_shoulder (local min within 3% of left_shoulder). Neckline = average of two peaks between troughs. Confirmed if `bars[-1]["c"] > neckline` |
| `detect_v_bottom(bars)` | Use last 15 bars. Left leg: decline >= 8% from bars[-15]["c"] to minimum close in bars[-10:-5]. Right leg: recovery >= 8% from that minimum to bars[-1]["c"]. Confidence 0.4 |

### Continuation detectors (all return confidence 0.7 except pennant=0.4)

| Function | Rule |
|----------|------|
| `detect_bull_flag(bars)` | Use last 25 bars. Upleg: bars[-25] to bars[-15] — close at bars[-15] >= bars[-25]["c"] * 1.05. Channel: bars[-14] to bars[-1] — linear regression slope of closes is negative AND max retracement from upleg high <= 40% of upleg size |
| `detect_bear_flag(bars)` | Downleg: bars[-25] to bars[-15] — close at bars[-15] <= bars[-25]["c"] * 0.95. Channel: bars[-14] to bars[-1] — slope of closes is positive AND max retracement <= 40% of downleg size |
| `detect_ascending_triangle(bars)` | Use last 40 bars. Flat resistance: top 3 highs within 1.5% of max high. Rising lows: find at least 3 local lows and fit linear regression — slope > 0. Require at least 2 touches of resistance and 2 touches of rising support |
| `detect_descending_triangle(bars)` | Flat support: bottom 3 lows within 1.5% of min low. Falling highs: at least 3 local highs, slope < 0. At least 2 touches each side |
| `detect_symmetrical_triangle(bars)` | Use last 40 bars. Highs: linear regression slope < 0. Lows: linear regression slope > 0. At least 2 local highs and 2 local lows. Direction from EMA200 trend (bull if last close > EMA200 of last 40 closes, bear otherwise) |
| `detect_pennant(bars)` | Use last 10 bars. Strong move in bars[-10:-5]: abs change >= 5%. Then bars[-5:] form tight triangle: max(highs[-5:]) - min(lows[-5:]) <= 0.05 * bars[-6]["c"]. Direction from sign of the preceding move (up = bull, down = bear). Confidence 0.4 |
| `detect_rising_wedge(bars)` | Use last 20 bars. Fit linear regression to highs and lows separately. Both slopes > 0 (both rising). Slope of highs > slope of lows. At least 3 local highs and 3 local lows |
| `detect_falling_wedge(bars)` | Both slopes < 0 (both falling). Slope of lows < slope of highs (lows falling faster). At least 3 local highs and 3 local lows |

---

## Task 1: Package scaffold + PatternHit dataclass

**Files:**
- Create: `server/strategies/patterns/__init__.py`
- Create: `server/strategies/patterns/detectors.py` (dataclass + `detect_all` only)
- Test: `tests/test_classic_patterns.py` (PatternHit tests only)

- [ ] **Step 1: Write the failing tests for PatternHit**

Create `tests/test_classic_patterns.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```
pytest tests/test_classic_patterns.py::TestPatternHit -v
```

Expected: `ModuleNotFoundError: No module named 'server.strategies.patterns'`

- [ ] **Step 3: Create the package marker and detectors scaffold**

Create `server/strategies/patterns/__init__.py` — empty file:

```python
```

Create `server/strategies/patterns/detectors.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


@dataclass
class PatternHit:
    name: str
    direction: Literal["bull", "bear"]
    confidence: float
    category: str


def detect_all(bars: list[dict], enabled_categories: list[str]) -> list[PatternHit]:
    """Call all detectors in enabled categories and return non-None hits."""
    if not enabled_categories or len(bars) < 5:
        return []

    _CANDLESTICK = [
        detect_bullish_engulfing,
        detect_bearish_engulfing,
        detect_hammer,
        detect_shooting_star,
        detect_morning_star,
        detect_evening_star,
        detect_doji,
    ]
    _REVERSAL = [
        detect_double_bottom,
        detect_double_top,
        detect_triple_bottom,
        detect_triple_top,
        detect_head_and_shoulders,
        detect_inverse_head_and_shoulders,
        detect_v_bottom,
    ]
    _CONTINUATION = [
        detect_bull_flag,
        detect_bear_flag,
        detect_ascending_triangle,
        detect_descending_triangle,
        detect_symmetrical_triangle,
        detect_pennant,
        detect_rising_wedge,
        detect_falling_wedge,
    ]

    category_map = {
        "candlestick": _CANDLESTICK,
        "reversal": _REVERSAL,
        "continuation": _CONTINUATION,
    }

    hits: list[PatternHit] = []
    for cat in enabled_categories:
        for fn in category_map.get(cat, []):
            try:
                result = fn(bars)
                if result is not None:
                    hits.append(result)
            except Exception:
                pass
    return hits


# ---------------------------------------------------------------------------
# Candlestick detectors — stubs (will be filled in Task 2)
# ---------------------------------------------------------------------------

def detect_bullish_engulfing(bars: list[dict]) -> PatternHit | None:
    return None

def detect_bearish_engulfing(bars: list[dict]) -> PatternHit | None:
    return None

def detect_hammer(bars: list[dict]) -> PatternHit | None:
    return None

def detect_shooting_star(bars: list[dict]) -> PatternHit | None:
    return None

def detect_morning_star(bars: list[dict]) -> PatternHit | None:
    return None

def detect_evening_star(bars: list[dict]) -> PatternHit | None:
    return None

def detect_doji(bars: list[dict]) -> PatternHit | None:
    return None


# ---------------------------------------------------------------------------
# Reversal detectors — stubs (will be filled in Task 3)
# ---------------------------------------------------------------------------

def detect_double_bottom(bars: list[dict]) -> PatternHit | None:
    return None

def detect_double_top(bars: list[dict]) -> PatternHit | None:
    return None

def detect_triple_bottom(bars: list[dict]) -> PatternHit | None:
    return None

def detect_triple_top(bars: list[dict]) -> PatternHit | None:
    return None

def detect_head_and_shoulders(bars: list[dict]) -> PatternHit | None:
    return None

def detect_inverse_head_and_shoulders(bars: list[dict]) -> PatternHit | None:
    return None

def detect_v_bottom(bars: list[dict]) -> PatternHit | None:
    return None


# ---------------------------------------------------------------------------
# Continuation detectors — stubs (will be filled in Task 4)
# ---------------------------------------------------------------------------

def detect_bull_flag(bars: list[dict]) -> PatternHit | None:
    return None

def detect_bear_flag(bars: list[dict]) -> PatternHit | None:
    return None

def detect_ascending_triangle(bars: list[dict]) -> PatternHit | None:
    return None

def detect_descending_triangle(bars: list[dict]) -> PatternHit | None:
    return None

def detect_symmetrical_triangle(bars: list[dict]) -> PatternHit | None:
    return None

def detect_pennant(bars: list[dict]) -> PatternHit | None:
    return None

def detect_rising_wedge(bars: list[dict]) -> PatternHit | None:
    return None

def detect_falling_wedge(bars: list[dict]) -> PatternHit | None:
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

```
pytest tests/test_classic_patterns.py::TestPatternHit -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```
git add server/strategies/patterns/__init__.py server/strategies/patterns/detectors.py tests/test_classic_patterns.py
git commit -m "feat: add PatternHit dataclass, detect_all scaffold, and package marker"
```

---

## Task 2: Candlestick detectors (7 patterns)

**Files:**
- Modify: `server/strategies/patterns/detectors.py` — implement 7 candlestick functions
- Modify: `tests/test_classic_patterns.py` — add `TestCandlestickDetectors` class

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_classic_patterns.py`:

```python
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
        # Uptrend: 10 bars rising 100→109 (price > SMA10 ~104.5), hammer geometry on last bar
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
        # Downtrend: SMA10 ~ 105, last close=99 (price < SMA) → bull doji
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
        # Last bar: open=100, close=103 (body=3), high=104, low=99 (range=5). 3 > 0.05*5=0.25 → not doji
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```
pytest tests/test_classic_patterns.py::TestCandlestickDetectors -v
```

Expected: All 12 tests fail — detectors return `None`.

- [ ] **Step 3: Implement the 7 candlestick detectors**

Replace the stub functions in `server/strategies/patterns/detectors.py`:

```python
def detect_bullish_engulfing(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 2:
        return None
    prev, curr = bars[-2], bars[-1]
    prev_bear = prev["o"] > prev["c"]
    curr_bull = curr["c"] > curr["o"]
    if not prev_bear or not curr_bull:
        return None
    if curr["o"] < prev["c"] and curr["c"] > prev["o"]:
        return PatternHit("bullish_engulfing", "bull", 0.7, "candlestick")
    return None


def detect_bearish_engulfing(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 2:
        return None
    prev, curr = bars[-2], bars[-1]
    prev_bull = prev["c"] > prev["o"]
    curr_bear = curr["o"] > curr["c"]
    if not prev_bull or not curr_bear:
        return None
    if curr["o"] > prev["c"] and curr["c"] < prev["o"]:
        return PatternHit("bearish_engulfing", "bear", 0.7, "candlestick")
    return None


def _sma(values: list[float]) -> float:
    return sum(values) / len(values)


def detect_hammer(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 10:
        return None
    b = bars[-1]
    body = abs(b["c"] - b["o"])
    if body == 0:
        return None
    lower_wick = min(b["o"], b["c"]) - b["l"]
    upper_wick = b["h"] - max(b["o"], b["c"])
    if lower_wick < 2 * body or upper_wick > 0.3 * body:
        return None
    sma10 = _sma([x["c"] for x in bars[-10:]])
    if b["c"] >= sma10:
        return None
    return PatternHit("hammer", "bull", 0.7, "candlestick")


def detect_shooting_star(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 10:
        return None
    b = bars[-1]
    body = abs(b["c"] - b["o"])
    if body == 0:
        return None
    upper_wick = b["h"] - max(b["o"], b["c"])
    lower_wick = min(b["o"], b["c"]) - b["l"]
    if upper_wick < 2 * body or lower_wick > 0.3 * body:
        return None
    sma10 = _sma([x["c"] for x in bars[-10:]])
    if b["c"] <= sma10:
        return None
    return PatternHit("shooting_star", "bear", 0.7, "candlestick")


def detect_morning_star(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 3:
        return None
    b3, b2, b1 = bars[-3], bars[-2], bars[-1]
    range3 = b3["h"] - b3["l"]
    if range3 == 0:
        return None
    body3 = abs(b3["c"] - b3["o"])
    range2 = b2["h"] - b2["l"]
    body2 = abs(b2["c"] - b2["o"])
    if body3 < 0.6 * range3:
        return None
    if b3["o"] <= b3["c"]:  # bar[-3] must be bearish
        return None
    if range2 > 0 and body2 > 0.3 * range2:
        return None
    midpoint3 = (b3["o"] + b3["c"]) / 2
    if b1["c"] > b1["o"] and b1["c"] > midpoint3:
        return PatternHit("morning_star", "bull", 0.7, "candlestick")
    return None


def detect_evening_star(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 3:
        return None
    b3, b2, b1 = bars[-3], bars[-2], bars[-1]
    range3 = b3["h"] - b3["l"]
    if range3 == 0:
        return None
    body3 = abs(b3["c"] - b3["o"])
    range2 = b2["h"] - b2["l"]
    body2 = abs(b2["c"] - b2["o"])
    if body3 < 0.6 * range3:
        return None
    if b3["c"] <= b3["o"]:  # bar[-3] must be bullish
        return None
    if range2 > 0 and body2 > 0.3 * range2:
        return None
    midpoint3 = (b3["o"] + b3["c"]) / 2
    if b1["o"] > b1["c"] and b1["c"] < midpoint3:
        return PatternHit("evening_star", "bear", 0.7, "candlestick")
    return None


def detect_doji(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 10:
        return None
    b = bars[-1]
    rng = b["h"] - b["l"]
    if rng == 0:
        return None
    body = abs(b["c"] - b["o"])
    if body > 0.05 * rng:
        return None
    sma10 = _sma([x["c"] for x in bars[-10:]])
    direction: Literal["bull", "bear"] = "bull" if b["c"] < sma10 else "bear"
    return PatternHit("doji", direction, 0.4, "candlestick")
```

- [ ] **Step 4: Run the tests to verify they pass**

```
pytest tests/test_classic_patterns.py::TestCandlestickDetectors -v
```

Expected: All 12 tests pass.

- [ ] **Step 5: Commit**

```
git add server/strategies/patterns/detectors.py tests/test_classic_patterns.py
git commit -m "feat: implement 7 candlestick pattern detectors"
```

---

## Task 3: Reversal detectors (7 patterns)

**Files:**
- Modify: `server/strategies/patterns/detectors.py` — implement 7 reversal functions
- Modify: `tests/test_classic_patterns.py` — add `TestReversalDetectors` class

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_classic_patterns.py`:

```python
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
        # Only 3% decline — below 8% threshold
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```
pytest tests/test_classic_patterns.py::TestReversalDetectors -v
```

Expected: All 9 tests fail.

- [ ] **Step 3: Implement a shared local-extrema helper and the 7 reversal detectors**

Add the helper and implement the reversal detectors in `server/strategies/patterns/detectors.py`. Add the helper right after the `_sma` function:

```python
def _local_minima(values: list[float], window: int = 3) -> list[int]:
    """Return indices that are local minima within ±window bars."""
    result = []
    for i in range(window, len(values) - window):
        if all(values[i] <= values[i + j] for j in range(-window, window + 1) if j != 0):
            result.append(i)
    return result


def _local_maxima(values: list[float], window: int = 3) -> list[int]:
    """Return indices that are local maxima within ±window bars."""
    result = []
    for i in range(window, len(values) - window):
        if all(values[i] >= values[i + j] for j in range(-window, window + 1) if j != 0):
            result.append(i)
    return result


def _linreg_slope(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    num = sum((xs[i] - x_mean) * (values[i] - y_mean) for i in range(n))
    den = sum((xs[i] - x_mean) ** 2 for i in range(n))
    return num / den if den != 0 else 0.0
```

Now replace the reversal stub functions:

```python
def detect_double_bottom(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 20:
        return None
    window = bars[-60:] if len(bars) >= 60 else bars
    closes = [b["c"] for b in window]
    troughs = _local_minima(closes, window=3)
    for i in range(len(troughs) - 1):
        t1, t2 = troughs[i], troughs[i + 1]
        if t2 - t1 < 5:
            continue
        v1, v2 = closes[t1], closes[t2]
        if abs(v1 - v2) / max(v1, v2) > 0.02:
            continue
        neckline = max(closes[t1:t2 + 1])
        if closes[-1] > neckline:
            return PatternHit("double_bottom", "bull", 1.0, "reversal")
    return None


def detect_double_top(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 20:
        return None
    window = bars[-60:] if len(bars) >= 60 else bars
    closes = [b["c"] for b in window]
    peaks = _local_maxima(closes, window=3)
    for i in range(len(peaks) - 1):
        p1, p2 = peaks[i], peaks[i + 1]
        if p2 - p1 < 5:
            continue
        v1, v2 = closes[p1], closes[p2]
        if abs(v1 - v2) / max(v1, v2) > 0.02:
            continue
        neckline = min(closes[p1:p2 + 1])
        if closes[-1] < neckline:
            return PatternHit("double_top", "bear", 1.0, "reversal")
    return None


def detect_triple_bottom(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 25:
        return None
    window = bars[-60:] if len(bars) >= 60 else bars
    closes = [b["c"] for b in window]
    troughs = _local_minima(closes, window=3)
    if len(troughs) < 3:
        return None
    base = min(closes[t] for t in troughs)
    for i in range(len(troughs) - 2):
        t1, t2, t3 = troughs[i], troughs[i + 1], troughs[i + 2]
        if t2 - t1 < 5 or t3 - t2 < 5:
            continue
        v1, v2, v3 = closes[t1], closes[t2], closes[t3]
        if any(abs(v - base) / base > 0.02 for v in (v1, v2, v3)):
            continue
        neckline = max(closes[t1:t3 + 1])
        if closes[-1] > neckline:
            return PatternHit("triple_bottom", "bull", 1.0, "reversal")
    return None


def detect_triple_top(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 25:
        return None
    window = bars[-60:] if len(bars) >= 60 else bars
    closes = [b["c"] for b in window]
    peaks = _local_maxima(closes, window=3)
    if len(peaks) < 3:
        return None
    apex = max(closes[p] for p in peaks)
    for i in range(len(peaks) - 2):
        p1, p2, p3 = peaks[i], peaks[i + 1], peaks[i + 2]
        if p2 - p1 < 5 or p3 - p2 < 5:
            continue
        v1, v2, v3 = closes[p1], closes[p2], closes[p3]
        if any(abs(v - apex) / apex > 0.02 for v in (v1, v2, v3)):
            continue
        neckline = min(closes[p1:p3 + 1])
        if closes[-1] < neckline:
            return PatternHit("triple_top", "bear", 1.0, "reversal")
    return None


def detect_head_and_shoulders(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 20:
        return None
    window = bars[-60:] if len(bars) >= 60 else bars
    closes = [b["c"] for b in window]
    peaks = _local_maxima(closes, window=3)
    if len(peaks) < 3:
        return None
    for i in range(len(peaks) - 2):
        ls_i, head_i, rs_i = peaks[i], peaks[i + 1], peaks[i + 2]
        ls, head, rs = closes[ls_i], closes[head_i], closes[rs_i]
        if head <= ls or head <= rs:
            continue
        if abs(ls - rs) / max(ls, rs) > 0.03:
            continue
        troughs_between = _local_minima(closes[ls_i:rs_i + 1], window=2)
        if len(troughs_between) < 2:
            continue
        t1 = closes[ls_i + troughs_between[0]]
        t2 = closes[ls_i + troughs_between[-1]]
        neckline = (t1 + t2) / 2
        if closes[-1] < neckline:
            return PatternHit("head_and_shoulders", "bear", 1.0, "reversal")
    return None


def detect_inverse_head_and_shoulders(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 20:
        return None
    window = bars[-60:] if len(bars) >= 60 else bars
    closes = [b["c"] for b in window]
    troughs = _local_minima(closes, window=3)
    if len(troughs) < 3:
        return None
    for i in range(len(troughs) - 2):
        ls_i, head_i, rs_i = troughs[i], troughs[i + 1], troughs[i + 2]
        ls, head, rs = closes[ls_i], closes[head_i], closes[rs_i]
        if head >= ls or head >= rs:
            continue
        if abs(ls - rs) / max(ls, rs) > 0.03:
            continue
        peaks_between = _local_maxima(closes[ls_i:rs_i + 1], window=2)
        if len(peaks_between) < 2:
            continue
        p1 = closes[ls_i + peaks_between[0]]
        p2 = closes[ls_i + peaks_between[-1]]
        neckline = (p1 + p2) / 2
        if closes[-1] > neckline:
            return PatternHit("inverse_head_and_shoulders", "bull", 1.0, "reversal")
    return None


def detect_v_bottom(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 15:
        return None
    segment = bars[-15:]
    start_close = segment[0]["c"]
    mid_closes = [b["c"] for b in segment[5:10]]
    end_close = segment[-1]["c"]
    trough = min(mid_closes)
    if trough == 0:
        return None
    decline = (start_close - trough) / start_close
    recovery = (end_close - trough) / trough
    if decline >= 0.08 and recovery >= 0.08:
        return PatternHit("v_bottom", "bull", 0.4, "reversal")
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

```
pytest tests/test_classic_patterns.py::TestReversalDetectors -v
```

Expected: All 9 tests pass.

- [ ] **Step 5: Commit**

```
git add server/strategies/patterns/detectors.py tests/test_classic_patterns.py
git commit -m "feat: implement 7 reversal pattern detectors with neckline confirmation"
```

---

## Task 4: Continuation detectors (8 patterns)

**Files:**
- Modify: `server/strategies/patterns/detectors.py` — implement 8 continuation functions
- Modify: `tests/test_classic_patterns.py` — add `TestContinuationDetectors` class

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_classic_patterns.py`:

```python
# ---------------------------------------------------------------------------
# Continuation detectors
# ---------------------------------------------------------------------------

class TestContinuationDetectors:
    def test_bull_flag_detected(self):
        from server.strategies.patterns.detectors import detect_bull_flag
        # Upleg bars[-25:-15]: from 100 to 108 (>=5% gain)
        # Channel bars[-14:]: slight pullback from 108 to 105 (retracement < 40% of 8-pt move)
        upleg  = [100.0 + i * 0.8 for i in range(11)]   # 100 → 108
        channel = [108.0 - i * 0.21 for i in range(14)]  # 108 → 105.1 (retracement ~2.9/8=36%)
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
        downleg = [100.0 - i * 0.8 for i in range(11)]   # 100 → 92
        channel = [92.0 + i * 0.21 for i in range(14)]   # 92 → 94.9
        closes = downleg + channel
        bars = _make_bars(closes)
        result = detect_bear_flag(bars)
        assert result is not None
        assert result.direction == "bear"
        assert result.confidence == 0.7

    def test_ascending_triangle_detected(self):
        from server.strategies.patterns.detectors import detect_ascending_triangle
        # Flat resistance near 110, rising lows: 95, 97, 99, 101
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
        # Flat support near 90, falling highs: 115, 113, 111, 109
        lows   = [90.0, 91.0, 90.2, 91.5, 90.1, 91.0, 90.3, 91.2, 90.0, 90.5] * 4
        highs  = [115.0, 114.0, 113.0, 112.0, 111.0, 110.0, 109.0, 108.0, 107.0, 106.0] * 4
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
        bars = _make_bars(closes, highs=highs, lows=lows)
        result = detect_descending_triangle(bars)
        assert result is not None
        assert result.direction == "bear"
        assert result.confidence == 0.7

    def test_symmetrical_triangle_bull_in_uptrend(self):
        from server.strategies.patterns.detectors import detect_symmetrical_triangle
        # Converging: highs falling from 115→105, lows rising from 85→95
        # Last close above EMA200 of the window → bull
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
        move = [100.0 + i * 1.1 for i in range(6)]  # 100 → 105.5 (5.5%)
        tight = [105.5, 105.6, 105.4, 105.5, 105.3]  # tight range
        closes = pre + move + tight
        # highs/lows for tight section: max spread = 0.3 on a base of 105.5 (0.28% << 5%)
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
        # Upleg 100→108 (+8), then channel retraces more than 40% (>3.2 pts) → not a flag
        upleg   = [100.0 + i * 0.8 for i in range(11)]   # 100 → 108
        channel = [108.0 - i * 0.35 for i in range(14)]  # 108 → 103.1 (retracement ~4.9/8=61%)
        closes = upleg + channel
        bars = _make_bars(closes)
        result = detect_bull_flag(bars)
        assert result is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```
pytest tests/test_classic_patterns.py::TestContinuationDetectors -v
```

Expected: All 9 tests fail.

- [ ] **Step 3: Implement the 8 continuation detectors**

Replace the continuation stub functions in `server/strategies/patterns/detectors.py`:

```python
def detect_bull_flag(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 25:
        return None
    upleg_start = bars[-25]["c"]
    upleg_end   = bars[-15]["c"]
    if upleg_end < upleg_start * 1.05:
        return None
    upleg_size = upleg_end - upleg_start
    channel = [b["c"] for b in bars[-14:]]
    slope = _linreg_slope(channel)
    if slope >= 0:
        return None
    retracement = upleg_end - min(channel)
    if retracement > 0.4 * upleg_size:
        return None
    return PatternHit("bull_flag", "bull", 0.7, "continuation")


def detect_bear_flag(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 25:
        return None
    downleg_start = bars[-25]["c"]
    downleg_end   = bars[-15]["c"]
    if downleg_end > downleg_start * 0.95:
        return None
    downleg_size = downleg_start - downleg_end
    channel = [b["c"] for b in bars[-14:]]
    slope = _linreg_slope(channel)
    if slope <= 0:
        return None
    retracement = max(channel) - downleg_end
    if retracement > 0.4 * downleg_size:
        return None
    return PatternHit("bear_flag", "bear", 0.7, "continuation")


def detect_ascending_triangle(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 20:
        return None
    window = bars[-40:] if len(bars) >= 40 else bars
    highs = [b["h"] for b in window]
    lows  = [b["l"] for b in window]
    max_high = max(highs)
    top3_highs = sorted([h for h in highs if abs(h - max_high) / max_high <= 0.015], reverse=True)
    if len(top3_highs) < 2:
        return None
    lows_indices = _local_minima(lows, window=2)
    if len(lows_indices) < 2:
        return None
    lows_at_minima = [lows[i] for i in lows_indices]
    if _linreg_slope(lows_at_minima) <= 0:
        return None
    return PatternHit("ascending_triangle", "bull", 0.7, "continuation")


def detect_descending_triangle(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 20:
        return None
    window = bars[-40:] if len(bars) >= 40 else bars
    highs = [b["h"] for b in window]
    lows  = [b["l"] for b in window]
    min_low = min(lows)
    bottom3_lows = [l for l in lows if abs(l - min_low) / max(min_low, 0.01) <= 0.015]
    if len(bottom3_lows) < 2:
        return None
    highs_indices = _local_maxima(highs, window=2)
    if len(highs_indices) < 2:
        return None
    highs_at_maxima = [highs[i] for i in highs_indices]
    if _linreg_slope(highs_at_maxima) >= 0:
        return None
    return PatternHit("descending_triangle", "bear", 0.7, "continuation")


def detect_symmetrical_triangle(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 20:
        return None
    window = bars[-40:] if len(bars) >= 40 else bars
    highs = [b["h"] for b in window]
    lows  = [b["l"] for b in window]
    highs_at = _local_maxima(highs, window=2)
    lows_at  = _local_minima(lows, window=2)
    if len(highs_at) < 2 or len(lows_at) < 2:
        return None
    if _linreg_slope([highs[i] for i in highs_at]) >= 0:
        return None
    if _linreg_slope([lows[i] for i in lows_at]) <= 0:
        return None
    closes = [b["c"] for b in window]
    from server.strategies.chart_patterns import _ema as _cp_ema  # noqa: avoid circular at module level
    ema200 = _cp_ema(closes, 200) if len(closes) >= 200 else None
    price = closes[-1]
    direction: Literal["bull", "bear"] = "bull" if (ema200 is None or price > ema200) else "bear"
    return PatternHit("symmetrical_triangle", direction, 0.7, "continuation")


def detect_pennant(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 10:
        return None
    pre_close  = bars[-11]["c"] if len(bars) > 10 else bars[-10]["c"]
    move_close = bars[-6]["c"]
    move_pct = (move_close - pre_close) / pre_close if pre_close != 0 else 0
    if abs(move_pct) < 0.05:
        return None
    tight_highs = [b["h"] for b in bars[-5:]]
    tight_lows  = [b["l"] for b in bars[-5:]]
    range_size = max(tight_highs) - min(tight_lows)
    base = bars[-6]["c"]
    if base == 0 or range_size > 0.05 * base:
        return None
    direction: Literal["bull", "bear"] = "bull" if move_pct > 0 else "bear"
    return PatternHit("pennant", direction, 0.4, "continuation")


def detect_rising_wedge(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 10:
        return None
    window = bars[-20:] if len(bars) >= 20 else bars
    highs = [b["h"] for b in window]
    lows  = [b["l"] for b in window]
    highs_at = _local_maxima(highs, window=2)
    lows_at  = _local_minima(lows, window=2)
    if len(highs_at) < 3 or len(lows_at) < 3:
        return None
    slope_h = _linreg_slope([highs[i] for i in highs_at])
    slope_l = _linreg_slope([lows[i] for i in lows_at])
    if slope_h <= 0 or slope_l <= 0:
        return None
    if slope_h <= slope_l:
        return None
    return PatternHit("rising_wedge", "bear", 0.7, "continuation")


def detect_falling_wedge(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 10:
        return None
    window = bars[-20:] if len(bars) >= 20 else bars
    highs = [b["h"] for b in window]
    lows  = [b["l"] for b in window]
    highs_at = _local_maxima(highs, window=2)
    lows_at  = _local_minima(lows, window=2)
    if len(highs_at) < 3 or len(lows_at) < 3:
        return None
    slope_h = _linreg_slope([highs[i] for i in highs_at])
    slope_l = _linreg_slope([lows[i] for i in lows_at])
    if slope_h >= 0 or slope_l >= 0:
        return None
    if slope_l >= slope_h:
        return None
    return PatternHit("falling_wedge", "bull", 0.7, "continuation")
```

**Important note on the `detect_symmetrical_triangle` import:** The function imports `_ema` from `chart_patterns` (which doesn't exist yet). For this task, replace that EMA call with an inline EMA so the module doesn't need a circular import. Use this version instead:

```python
def detect_symmetrical_triangle(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 20:
        return None
    window = bars[-40:] if len(bars) >= 40 else bars
    highs = [b["h"] for b in window]
    lows  = [b["l"] for b in window]
    highs_at = _local_maxima(highs, window=2)
    lows_at  = _local_minima(lows, window=2)
    if len(highs_at) < 2 or len(lows_at) < 2:
        return None
    if _linreg_slope([highs[i] for i in highs_at]) >= 0:
        return None
    if _linreg_slope([lows[i] for i in lows_at]) <= 0:
        return None
    closes = [b["c"] for b in window]
    # inline EMA200 for trend direction (avoid cross-module import)
    k = 2 / 201
    if len(closes) >= 200:
        ema = sum(closes[:200]) / 200
        for c in closes[200:]:
            ema = c * k + ema * (1 - k)
        direction: Literal["bull", "bear"] = "bull" if closes[-1] > ema else "bear"
    else:
        direction = "bull"  # insufficient history, default bull
    return PatternHit("symmetrical_triangle", direction, 0.7, "continuation")
```

- [ ] **Step 4: Run the tests to verify they pass**

```
pytest tests/test_classic_patterns.py::TestContinuationDetectors -v
```

Expected: All 9 tests pass.

- [ ] **Step 5: Run all detector tests**

```
pytest tests/test_classic_patterns.py -v
```

Expected: All tests pass (PatternHit + Candlestick + Reversal + Continuation).

- [ ] **Step 6: Commit**

```
git add server/strategies/patterns/detectors.py tests/test_classic_patterns.py
git commit -m "feat: implement 8 continuation pattern detectors"
```

---

## Task 5: ClassicPatterns strategy class

**Files:**
- Create: `server/strategies/chart_patterns.py`
- Modify: `tests/test_classic_patterns.py` — add `TestClassicPatternsStrategy` class

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_classic_patterns.py`:

```python
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
        assert "EMA48" in sells[0].reason or "trend invalidated" in sells[0].reason

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
        assert "alpaca" in ClassicPatterns.brokers
        assert "binance" in ClassicPatterns.brokers

    def test_registered_in_registry(self):
        from server.strategies import REGISTRY
        assert "classic_patterns" in REGISTRY
```

- [ ] **Step 2: Run the tests to verify they fail**

```
pytest tests/test_classic_patterns.py::TestClassicPatternsStrategy -v
```

Expected: `ModuleNotFoundError` or `ImportError` for `server.strategies.chart_patterns`.

- [ ] **Step 3: Create `server/strategies/chart_patterns.py`**

```python
from .base import Strategy, Signal
from .patterns.detectors import detect_all


def _ema(closes: list, period: int):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    val = sum(closes[:period]) / period
    for price in closes[period:]:
        val = price * k + val * (1 - k)
    return val


class ClassicPatterns(Strategy):
    name = "classic_patterns"
    label = "Classic Chart Patterns"
    description = (
        "Detects 21 classic patterns across candlestick, reversal, and continuation categories. "
        "Only trades patterns that align with the EMA200 trend. Position size scales with "
        "pattern confidence. Works on stocks (daily) and crypto (hourly)."
    )
    brokers = ["alpaca", "binance"]
    default_params = {
        "symbols": [],
        "use_scanner": True,
        "timeframe": "day",
        "enable_candlestick": True,
        "enable_reversal": True,
        "enable_continuation": True,
        "min_confidence": 0.7,
        "scaled_sizing": True,
        "notional": 500,
        "ema_exit": "48",
        "max_positions": 5,
    }
    params_schema = [
        {"key": "symbols", "label": "Symbols to Trade", "type": "symbols",
         "hint": "Comma-separated tickers to always include. Leave empty to use the scanner (stocks only)."},
        {"key": "use_scanner", "label": "Auto-discover Stocks", "type": "bool",
         "hint": "Add top active and gaining stocks each tick. Ignored for Binance accounts."},
        {"key": "timeframe", "label": "Timeframe", "type": "select",
         "options": ["day", "hour"],
         "hint": "Use 'day' for stocks (Alpaca) and 'hour' for crypto (Binance)."},
        {"key": "enable_candlestick", "label": "Candlestick Patterns", "type": "bool",
         "hint": "Enable 7 short-term candlestick patterns: engulfing, hammer, shooting star, morning/evening star, doji."},
        {"key": "enable_reversal", "label": "Reversal Patterns", "type": "bool",
         "hint": "Enable 7 reversal patterns: double/triple tops and bottoms, head-and-shoulders, V-bottom."},
        {"key": "enable_continuation", "label": "Continuation Patterns", "type": "bool",
         "hint": "Enable 8 continuation patterns: flags, triangles, pennant, rising/falling wedge."},
        {"key": "min_confidence", "label": "Min Pattern Confidence", "type": "select",
         "options": ["0.4", "0.7", "1.0"],
         "hint": "Minimum confidence to trade. 0.4 includes all patterns; 0.7 excludes doji/pennant/V-bottom; 1.0 only trades high-reliability reversal patterns."},
        {"key": "scaled_sizing", "label": "Scale Size by Confidence", "type": "bool",
         "hint": "When on: confidence 1.0 = 100% notional, 0.7 = 70%, 0.4 = 40%. When off, always uses the full amount."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number", "min": 10, "max": 100000,
         "hint": "Max USD per trade at confidence 1.0."},
        {"key": "ema_exit", "label": "EMA Exit Period", "type": "select",
         "options": ["48", "200"],
         "hint": "EMA period used as trend exit fallback. Price dropping below this EMA exits the position."},
        {"key": "max_positions", "label": "Max Open Positions", "type": "number", "min": 1, "max": 50,
         "hint": "Maximum simultaneous open positions."},
    ]

    def _get_symbols(self) -> list:
        fixed = [s.upper().strip() for s in (self.params.get("symbols") or []) if s]
        if self.params.get("use_scanner", True):
            try:
                from .. import scanner
                scanned = scanner.get_scanner_universe(
                    min_price=5.0, max_price=500.0, top_actives=25, top_gainers=15
                )
                seen = set(fixed)
                for s in scanned:
                    if s not in seen:
                        fixed.append(s)
                        seen.add(s)
            except Exception:
                pass
        return fixed

    def evaluate(self, positions, client=None):
        out: list[Signal] = []
        min_conf    = float(self.params.get("min_confidence", 0.7))
        scaled      = bool(self.params.get("scaled_sizing", True))
        notional    = float(self.params.get("notional", 500))
        ema_exit    = int(self.params.get("ema_exit", "48"))
        max_pos     = int(self.params.get("max_positions", 5))
        timeframe   = self.params.get("timeframe", "day")

        enabled_categories = [
            cat for cat, key in [
                ("candlestick",   "enable_candlestick"),
                ("reversal",      "enable_reversal"),
                ("continuation",  "enable_continuation"),
            ]
            if self.params.get(key, True)
        ]

        open_positions = sum(1 for v in positions.values() if v > 0)
        days = 10 if timeframe == "hour" else 500

        for sym in self._get_symbols():
            try:
                bars = self._get_bars(client, sym, days=days)
            except Exception:
                continue

            closes = [b["c"] for b in bars]
            e200 = _ema(closes, 200)
            if e200 is None:
                continue

            price = closes[-1]
            e_exit_val = _ema(closes, ema_exit)

            held = positions.get(sym, 0.0)

            if held > 0:
                hits = detect_all(bars, enabled_categories)
                bear_hits = [h for h in hits if h.direction == "bear"]
                if bear_hits:
                    top = max(bear_hits, key=lambda h: h.confidence)
                    reason = f"Chart exit: {top.name} -- bear pattern detected"
                    out.append(Signal(symbol=sym, side="sell", qty=held, reason=reason))
                elif e_exit_val is not None and price < e_exit_val:
                    reason = f"Chart exit: price {price:.2f} < EMA{ema_exit} {e_exit_val:.2f} -- trend invalidated"
                    out.append(Signal(symbol=sym, side="sell", qty=held, reason=reason))
                continue

            if open_positions >= max_pos:
                continue

            if price <= e200:
                continue

            hits = detect_all(bars, enabled_categories)
            bull_hits = [h for h in hits if h.direction == "bull" and h.confidence >= min_conf]
            if not bull_hits:
                continue

            top = max(bull_hits, key=lambda h: h.confidence)
            size = notional * top.confidence if scaled else notional
            reason = (
                f"Chart: {top.name} (conf {top.confidence:.0%}) | "
                f"price {price:.2f} > EMA200 {e200:.2f} | notional ${size:.0f}"
            )
            out.append(Signal(symbol=sym, side="buy", notional=size, reason=reason))
            open_positions += 1

        return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```
pytest tests/test_classic_patterns.py::TestClassicPatternsStrategy -v
```

Expected: All 12 tests pass.

- [ ] **Step 5: Commit**

```
git add server/strategies/chart_patterns.py tests/test_classic_patterns.py
git commit -m "feat: implement ClassicPatterns strategy with EMA200 trend filter and confidence sizing"
```

---

## Task 6: Register strategy and run full suite

**Files:**
- Modify: `server/strategies/__init__.py` — add import and REGISTRY entry

- [ ] **Step 1: Add the import and registration**

Open `server/strategies/__init__.py`. After the `EMAConfluence` import line, add:

```python
from .chart_patterns import ClassicPatterns
```

And in the `REGISTRY` tuple, add `ClassicPatterns` after `EMAConfluence`:

```python
REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (
        ManualStrategy,
        SMACrossover,
        RSIMeanReversion,
        MomentumBreakout,
        BollingerBandMeanReversion,
        Breakout52Week,
        MACDVolume,
        GoldenCross,
        CryptoTrend,
        CryptoRSIBounce,
        CryptoVolatilityBreakout,
        CryptoGrid,
        EMAConfluence,
        ClassicPatterns,
    )
}
```

- [ ] **Step 2: Run the registration test**

```
pytest tests/test_classic_patterns.py::TestClassicPatternsStrategy::test_registered_in_registry -v
```

Expected: PASS.

- [ ] **Step 3: Run the full test suite**

```
pytest tests/ -v
```

Expected: All tests pass (no regressions).

- [ ] **Step 4: Commit**

```
git add server/strategies/__init__.py
git commit -m "feat: register ClassicPatterns strategy in REGISTRY"
```

---

## Self-Review Checklist

Run this before declaring done:

- [ ] `detect_all` catches exceptions per-detector (Task 1 scaffold)
- [ ] All 21 patterns implemented with correct confidence values from spec
- [ ] Triple Bottom/Top have neckline confirmation (not just proximity)
- [ ] Bear exits fire regardless of EMA200 (exit logic in Task 5)
- [ ] EMA200 trend filter guards new entries only
- [ ] `min_confidence` cast via `float()`, `ema_exit` cast via `int()`
- [ ] `_ema()` defined locally in `chart_patterns.py` (not imported from `ema_confluence.py`)
- [ ] Reason strings are ASCII-only, match spec format
- [ ] No hardcoded hex colors anywhere
- [ ] All tests pass: `pytest tests/ -v`
