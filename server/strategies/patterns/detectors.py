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


def _local_minima(values: list[float], window: int = 3) -> list[int]:
    result = []
    for i in range(window, len(values) - window):
        if all(values[i] <= values[i + j] for j in range(-window, window + 1) if j != 0):
            result.append(i)
    return result


def _local_maxima(values: list[float], window: int = 3) -> list[int]:
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
# Reversal detectors
# ---------------------------------------------------------------------------

def detect_double_bottom(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 20:
        return None
    window = bars[-60:] if len(bars) >= 60 else bars
    closes = [b["c"] for b in window]
    troughs = _local_minima(closes, window=3)
    for i in range(len(troughs)):
        for j in range(i + 1, len(troughs)):
            t1, t2 = troughs[i], troughs[j]
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
    for i in range(len(peaks)):
        for j in range(i + 1, len(peaks)):
            p1, p2 = peaks[i], peaks[j]
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
    for i in range(len(troughs) - 2):
        t1, t2, t3 = troughs[i], troughs[i + 1], troughs[i + 2]
        if t2 - t1 < 5 or t3 - t2 < 5:
            continue
        v1, v2, v3 = closes[t1], closes[t2], closes[t3]
        base = min(v1, v2, v3)
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
    for i in range(len(peaks) - 2):
        p1, p2, p3 = peaks[i], peaks[i + 1], peaks[i + 2]
        if p2 - p1 < 5 or p3 - p2 < 5:
            continue
        v1, v2, v3 = closes[p1], closes[p2], closes[p3]
        apex = max(v1, v2, v3)
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
    if trough == 0 or start_close == 0:
        return None
    decline = (start_close - trough) / start_close
    recovery = (end_close - trough) / trough
    if decline >= 0.08 and recovery >= 0.08:
        return PatternHit("v_bottom", "bull", 0.4, "reversal")
    return None


# ---------------------------------------------------------------------------
# Continuation detectors
# ---------------------------------------------------------------------------

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
    slope_h = _linreg_slope(highs)
    slope_l = _linreg_slope(lows)
    # Rising lows (slope_l > 0) and flat/converging highs (|slope_h| < slope_l)
    if slope_l <= 0:
        return None
    if abs(slope_h) >= slope_l:
        return None
    return PatternHit("ascending_triangle", "bull", 0.7, "continuation")


def detect_descending_triangle(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 20:
        return None
    window = bars[-40:] if len(bars) >= 40 else bars
    highs = [b["h"] for b in window]
    lows  = [b["l"] for b in window]
    slope_h = _linreg_slope(highs)
    slope_l = _linreg_slope(lows)
    # Falling highs (slope_h < 0) and flat/converging lows (|slope_l| < |slope_h|)
    if slope_h >= 0:
        return None
    if abs(slope_l) >= abs(slope_h):
        return None
    return PatternHit("descending_triangle", "bear", 0.7, "continuation")


def detect_symmetrical_triangle(bars: list[dict]) -> PatternHit | None:
    if len(bars) < 20:
        return None
    window = bars[-40:] if len(bars) >= 40 else bars
    highs = [b["h"] for b in window]
    lows  = [b["l"] for b in window]
    slope_h = _linreg_slope(highs)
    slope_l = _linreg_slope(lows)
    # Converging: highs falling (slope_h < 0) and lows rising (slope_l > 0)
    if slope_h >= 0 or slope_l <= 0:
        return None
    closes = [b["c"] for b in window]
    # inline EMA200 for trend direction; default bull when insufficient history
    if len(closes) >= 200:
        k = 2 / 201
        ema = sum(closes[:200]) / 200
        for c in closes[200:]:
            ema = c * k + ema * (1 - k)
        direction: Literal["bull", "bear"] = "bull" if closes[-1] > ema else "bear"
    else:
        direction = "bull"
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
    slope_h = _linreg_slope(highs)
    slope_l = _linreg_slope(lows)
    # Both rising, highs rising faster (converging upward)
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
    slope_h = _linreg_slope(highs)
    slope_l = _linreg_slope(lows)
    # Both falling, lows falling faster (converging downward)
    if slope_h >= 0 or slope_l >= 0:
        return None
    if slope_l >= slope_h:
        return None
    return PatternHit("falling_wedge", "bull", 0.7, "continuation")
