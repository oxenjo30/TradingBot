# Classic Chart Patterns Strategy — Design Spec

## Goal

Add a `ClassicPatterns` strategy to TradeBot that detects 21 classic technical analysis patterns across three categories (candlestick, reversal, continuation) and trades when a pattern aligns with the current trend (EMA200 filter). Position size scales with pattern confidence. Works on both stocks (Alpaca/daily) and crypto (Binance/hourly). Fully compliant with TradeBot's light/dark UI themes — no hardcoded colors anywhere.

---

## Architecture

**Two new files, zero engine changes:**

```
server/strategies/chart_patterns.py         — Strategy class (~120 lines)
server/strategies/patterns/__init__.py      — empty package marker
server/strategies/patterns/detectors.py    — 21 detection functions + PatternHit dataclass (~400 lines)
```

**One registration change:**
`server/strategies/__init__.py` — add import + REGISTRY entry (identical pattern to EMAConfluence).

**Separation of concerns:**
- `detectors.py` has one job: given a list of OHLCV bars, return `list[PatternHit]`
- `chart_patterns.py` has one job: apply trend filter, score hits, emit Signals
- Neither file touches the engine, risk layer, or UI

---

## Data Type

```python
@dataclass
class PatternHit:
    name: str                           # e.g. "hammer", "double_bottom"
    direction: Literal["bull", "bear"]  # signal direction
    confidence: float                   # 0.4, 0.7, or 1.0
    category: str                       # "candlestick", "reversal", "continuation"
```

`detect_all(bars, enabled_categories)` calls all enabled detectors and returns `list[PatternHit]`. Each detector is a standalone function that takes `bars: list[dict]` and returns `PatternHit | None`.

`enabled_categories` is `list[str]` — e.g. `["candlestick", "reversal"]`. The strategy builds it from the three bool params:
```python
enabled_categories = [c for c, on in [
    ("candlestick", self.params.get("enable_candlestick", True)),
    ("reversal",    self.params.get("enable_reversal", True)),
    ("continuation",self.params.get("enable_continuation", True)),
] if on]
```

---

## Pattern Catalogue (21 patterns)

### Candlestick (last 1–3 bars)

| Pattern | Direction | Confidence | Detection Rule |
|---------|-----------|------------|----------------|
| Bullish Engulfing | bull | 0.7 | bar[-1] bullish body fully wraps bar[-2] bearish body |
| Bearish Engulfing | bear | 0.7 | bar[-1] bearish body fully wraps bar[-2] bullish body |
| Hammer | bull | 0.7 | lower wick >= 2x body, upper wick <= 0.3x body, in downtrend (price < 10-bar SMA) |
| Shooting Star | bear | 0.7 | upper wick >= 2x body, lower wick <= 0.3x body, in uptrend (price > 10-bar SMA) |
| Morning Star | bull | 0.7 | 3-bar: large bearish -> small body (gap or inside) -> large bullish closing above bar[-3] midpoint |
| Evening Star | bear | 0.7 | 3-bar: large bullish -> small body -> large bearish closing below bar[-3] midpoint |
| Doji | bull/bear | 0.4 | abs(close - open) <= 0.05 * (high - low); direction from trend (bull if price < 10-bar SMA, bear if above) |

### Reversal (last 20–60 bars)

| Pattern | Direction | Confidence | Detection Rule |
|---------|-----------|------------|----------------|
| Double Bottom | bull | 1.0 | two troughs within 2% of each other, 5+ bars apart, price breaks above neckline (peak between troughs) |
| Double Top | bear | 1.0 | two peaks within 2% of each other, 5+ bars apart, price breaks below neckline |
| Triple Bottom | bull | 1.0 | three troughs within 2% of each other, each 5+ bars apart; confirmed by price breaking above the highest peak between the troughs (neckline) |
| Triple Top | bear | 1.0 | three peaks within 2% of each other, each 5+ bars apart; confirmed by price breaking below the lowest trough between the peaks (neckline) |
| Head & Shoulders | bear | 1.0 | left shoulder < head > right shoulder (shoulders within 3% of each other), neckline break below |
| Inverse Head & Shoulders | bull | 1.0 | left shoulder > head < right shoulder (shoulders within 3%), neckline break above |
| V-Bottom | bull | 0.4 | decline >= 8% over 5 bars followed by recovery >= 8% over next 5 bars |

### Continuation (last 15–40 bars)

| Pattern | Direction | Confidence | Detection Rule |
|---------|-----------|------------|----------------|
| Bull Flag | bull | 0.7 | upleg >= 5% in <= 10 bars, then shallow downward channel <= 40% retracement over 5–15 bars |
| Bear Flag | bear | 0.7 | downleg >= 5% in <= 10 bars, then shallow upward channel <= 40% retracement over 5–15 bars |
| Ascending Triangle | bull | 0.7 | flat resistance (highs within 1.5%) + rising lows, at least 2 touches each side |
| Descending Triangle | bear | 0.7 | flat support (lows within 1.5%) + falling highs, at least 2 touches each side |
| Symmetrical Triangle | bull/bear | 0.7 | converging highs and lows, at least 2 touches each side; direction from trend |
| Pennant | bull/bear | 0.4 | strong move >= 5% then tight symmetrical triangle within 5 bars; direction from preceding move |
| Rising Wedge | bear | 0.7 | last 10–20 bars: rising highs + rising lows (at least 3 touches each), slope of highs > slope of lows; both trendlines rising |
| Falling Wedge | bull | 0.7 | last 10–20 bars: falling highs + falling lows (at least 3 touches each), slope of lows < slope of highs (lows falling faster); both trendlines falling |

**Confidence levels:**
- `1.0` — high-reliability patterns (H&S, double/triple tops/bottoms) — full notional
- `0.7` — moderate patterns (flags, triangles, most candlesticks except doji) — 70% notional
- `0.4` — lower-confidence patterns (doji, pennant, V-bottom) — 40% notional

---

## Signal Logic

### Trend Filter

Compute EMA200 from available bars (same `_ema()` formula as EMAConfluence):
- Bull hits only considered when `price > EMA200`
- Bear exit hits only considered when `price < EMA200`
- Insufficient bars for EMA200 (< 200 bars) → skip symbol silently

### Buy Signal

1. Call `detect_all(bars, enabled_categories)`
2. Filter to bull-direction hits that pass the trend filter
3. If one or more hits: take the **highest-confidence hit**
4. If `confidence >= min_confidence` param: emit buy signal
5. `size = notional * confidence` if `scaled_sizing=True`, else full `notional`
6. Reason: `"Chart: {name} (conf {confidence:.0%}) | price {price:.2f} > EMA200 {ema200:.2f} | notional ${size:.0f}"`

### Sell/Exit Signal (when holding)

The trend filter (`price > EMA200`) guards **new entries only**. Exits apply regardless of EMA200.

Fire when any of:
- Any bear-direction hit detected (no EMA200 check — if holding a long, a bear pattern is always a valid exit signal)
- `price < ema_exit_value` (EMA48 or EMA200 depending on `ema_exit` param)

Reason (pattern): `"Chart exit: {name} -- {direction} pattern detected"`
Reason (EMA): `"Chart exit: price {price:.2f} < EMA{ema_exit} {val:.2f} -- trend invalidated"`

---

## Parameters Schema

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `symbols` | symbols | `[]` | — | — | Tickers to watch. Leave empty to use scanner (stocks). |
| `use_scanner` | bool | `true` | — | — | Auto-add top actives/gainers. Stocks only; ignored for crypto. |
| `timeframe` | select | `"day"` | — | — | `day` for stocks (Alpaca), `hour` for crypto (Binance). |
| `enable_candlestick` | bool | `true` | — | — | Enable 7 candlestick patterns (hammer, engulfing, doji, etc.). |
| `enable_reversal` | bool | `true` | — | — | Enable 7 reversal patterns (H&S, double top/bottom, etc.). |
| `enable_continuation` | bool | `true` | — | — | Enable 7 continuation patterns (flags, triangles, wedges, etc.). |
| `min_confidence` | select | `0.7` | — | — | Minimum pattern confidence to trade. Options: 0.4, 0.7, 1.0. |
| `scaled_sizing` | bool | `true` | — | — | Scale position size by confidence (1.0=100%, 0.7=70%, 0.4=40%). |
| `notional` | number | `500` | `10` | `100000` | Max USD per trade at confidence 1.0. |
| `ema_exit` | select | `"48"` | — | — | EMA period for exit fallback. Options: 48, 200. |
| `max_positions` | number | `5` | `1` | `50` | Max simultaneous open positions. |

**Parameter casts:** `min_confidence` is stored as a string by the param editor (`"0.7"`) — cast with `float(self.params.get("min_confidence", 0.7))`. `ema_exit` is stored as `"48"` or `"200"` — cast with `int(self.params.get("ema_exit", "48"))`. `_ema()` should be defined locally in `chart_patterns.py` (copy from `ema_confluence.py`) — do not import it cross-module.

---

## Broker Behaviour

| Broker | Timeframe | Scanner | Bar depth |
|--------|-----------|---------|-----------|
| Alpaca (stocks) | `day` | top actives/gainers | `days=500` (EMA200 warmup) |
| Binance (crypto) | `hour` | uses `symbols` list | `days=10` (~240 hourly bars) |

---

## Strategy Metadata

```python
name        = "classic_patterns"
label       = "Classic Chart Patterns"
description = (
    "Detects 21 classic patterns across candlestick, reversal, and continuation categories. "
    "Only trades patterns that align with the EMA200 trend. Position size scales with "
    "pattern confidence. Works on stocks (daily) and crypto (hourly)."
)
brokers     = ["alpaca", "binance"]
```

---

## Reason Strings (ASCII only, no Unicode)

Buy:
```
Chart: double_bottom (conf 100%) | price 185.20 > EMA200 162.00 | notional $500
```

Sell (pattern):
```
Chart exit: evening_star -- bear pattern detected
```

Sell (EMA fallback):
```
Chart exit: price 174.50 < EMA48 175.20 -- trend invalidated
```

---

## UI Theme Compliance

- No hardcoded hex colors in `params_schema` hints or anywhere in strategy files
- All UI rendering uses existing CSS variables: `var(--text)`, `var(--muted)`, `var(--card)`, `var(--bg)`, `var(--border)`, `var(--blue)`, `var(--green)`, `var(--red)`
- The param editor in `app.js` renders all strategies uniformly — no UI changes needed

---

## Error Handling

- Insufficient bars for any pattern → return `None` (skip silently)
- Insufficient bars for EMA200 → skip symbol entirely
- Bar fetch exception → `continue` to next symbol
- Any individual detector exception → catch, skip that pattern (don't crash the whole evaluate)

---

## File Map

| File | Action |
|------|--------|
| `server/strategies/patterns/__init__.py` | Create (empty) |
| `server/strategies/patterns/detectors.py` | Create |
| `server/strategies/chart_patterns.py` | Create |
| `server/strategies/__init__.py` | Modify — add import + REGISTRY entry |
| `tests/test_classic_patterns.py` | Create |

---

## What This Does NOT Change

- Engine tick loop
- Risk checks (all existing guards still apply)
- Take-profit pass (engine handles it)
- Any HTML, CSS, or JS files
- Any other strategy

---

## Self-Review

- No placeholders or TBDs
- EMA200 warmup: `days=500` for daily, `days=10` for hourly (same as EMAConfluence)
- All reason strings ASCII-safe
- No hardcoded colors
- `PatternHit` dataclass is the single shared interface between detectors and strategy
- Confidence levels are explicit constants: 1.0, 0.7, 0.4
- Trend filter applied before sizing to avoid trading against macro direction
- Detector exceptions caught per-pattern so one bad detector can't crash evaluate()
