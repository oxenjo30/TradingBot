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
# Candlestick detectors
# ---------------------------------------------------------------------------

def _sma(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


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
    body2 = abs(b2["c"] - b2["o"])
    range2 = b2["h"] - b2["l"]
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
    body2 = abs(b2["c"] - b2["o"])
    range2 = b2["h"] - b2["l"]
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
    direction = "bull" if b["c"] < sma10 else "bear"
    return PatternHit("doji", direction, 0.4, "candlestick")


# ---------------------------------------------------------------------------
# Reversal detectors — stubs
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
# Continuation detectors — stubs
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
