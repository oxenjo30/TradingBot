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
# Candlestick detectors — stubs
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
