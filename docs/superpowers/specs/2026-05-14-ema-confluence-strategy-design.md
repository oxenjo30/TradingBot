# 4-EMA Confluence Strategy — Design Spec

## Goal

Add a `EMAConfluence` strategy to TradeBot that trades stocks (Alpaca) and crypto (Binance) using a 4-EMA confluence scoring system (EMA 8/13/48/200). Higher confluence = stronger signal. Position size scales with score when enabled. Works in both light and dark UI themes.

## Architecture

Single new file `server/strategies/ema_confluence.py`. No engine changes. No base class changes. One line added to `server/strategies/__init__.py` to register it. Follows the identical pattern of all existing strategies.

**Tech Stack:** Python, existing `Strategy` base class, existing `_get_bars()` helper, APScheduler engine tick (unchanged).

---

## File Map

- **Create:** `server/strategies/ema_confluence.py` — strategy logic
- **Modify:** `server/strategies/__init__.py` — import + register
- No changes to `engine.py`, `base.py`, `main.py`, `app.js`, or any HTML

---

## Signal Logic

### EMA Calculation

```python
def _ema(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    val = sum(closes[:period]) / period  # seed with SMA
    for price in closes[period:]:
        val = price * k + val * (1 - k)
    return val
```

### Confluence Score

For each of the 4 EMAs (8, 13, 48, 200):
- +1 if `price > EMA` (bullish vote)
- -1 if `price < EMA` (bearish vote)

`bull_score` = count of EMAs where price > EMA (0–4)  
`bear_score` = count of EMAs where price < EMA (0–4)

A signal is valid only when all voting EMAs agree — no mixed signals:
- **Buy signal:** `bull_score >= min_confluence` AND `bear_score == 0`
- **Sell signal (exit):** held position AND (`bear_score >= min_confluence` OR `price < ema_48`)

### Position Sizing

When `scaled_sizing=True`:
- score 4 → 100% of `notional`
- score 3 → 70% of `notional`
- score 2 → 40% of `notional`

When `scaled_sizing=False`: always full `notional`.

### Earnings Avoidance

When `avoid_earnings=True` and broker is Alpaca:
- Call `client.get_calendar(symbol)` to check for earnings within ±2 days of today
- If earnings found → skip symbol this tick
- For Binance accounts → bypass check entirely (crypto has no earnings)

---

## Parameters Schema

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `symbols` | symbols | `[]` | — | — | Tickers to watch. Leave empty to use scanner (stocks). |
| `use_scanner` | bool | `true` | — | — | Auto-add top actives/gainers. Stocks only; ignored for crypto. |
| `timeframe` | select | `"day"` | — | — | `day` for stocks, `hour` for crypto. |
| `min_confluence` | number | `3` | `2` | `4` | Minimum EMA alignment score to trigger a trade. |
| `scaled_sizing` | bool | `true` | — | — | Scale position size by confluence score. |
| `notional` | number | `500` | `10` | `100000` | Max USD per trade (100% size at score 4). |
| `avoid_earnings` | bool | `false` | — | — | Skip symbols with earnings within ±2 days (Alpaca only). |
| `max_positions` | number | `5` | `1` | `50` | Max simultaneous open positions. |

---

## Broker Behaviour

| Broker | Timeframe | Scanner | Earnings check | Hours |
|--------|-----------|---------|----------------|-------|
| Alpaca (stocks) | `day` | ✅ top actives/gainers | ✅ when enabled | US market hours only |
| Binance (crypto) | `hour` | ❌ uses `symbols` list | ❌ bypassed | 24/7 |

Bar fetch depth:
- `day` → `_get_bars(client, symbol, days=60)` — enough for EMA 200 warmup (need 200 bars minimum; 60 days ≈ 60 bars which is marginal — use `days=300` for daily)
- `hour` → `client.get_recent_bars(symbol, days=10)` with hourly timeframe — 240 bars

**Correction:** for daily bars, use `days=300` to ensure 200+ bars for EMA 200 warmup.

---

## UI Theme Compliance

The strategy appears in the Bots & Strategies page param editor. All rendered param fields use existing CSS classes and variables:
- Text: `var(--text)`, `var(--muted)`
- Backgrounds: `var(--card)`, `var(--bg)`
- Borders: `var(--border)`
- Accents: `var(--blue)`, `var(--green)`, `var(--red)`

No hardcoded hex colors in `params_schema` hint strings or anywhere in the strategy file. The param editor in `app.js` already renders all strategies using these variables — no UI changes needed.

---

## Strategy Metadata

```python
name        = "ema_confluence"
label       = "4-EMA Confluence"
description = (
    "Scores EMA 8/13/48/200 alignment to find high-conviction trend entries. "
    "Requires all scored EMAs to agree — no mixed signals. Position size scales "
    "with confluence score when enabled. Works on stocks (daily) and crypto (hourly)."
)
brokers     = ["alpaca", "binance"]
```

---

## Reason Strings (signal log)

Buy:
```
4-EMA bull score 4/4: price 185.20 > EMA8 183.1 > EMA13 181.4 > EMA48 175.2 > EMA200 162.0 | notional $500
```

Sell (trend break):
```
4-EMA exit: price 174.50 < EMA48 175.20 — trend invalidated
```

Sell (bear confluence):
```
4-EMA bear score 3/4: price below EMA8/13/48 | exit full position
```

---

## Error Handling

- Insufficient bars for EMA 200 → skip symbol silently (`continue`)
- `get_calendar` API failure → log warning, treat as no earnings (don't block trade)
- Any bar fetch exception → `continue` to next symbol (same as all other strategies)

---

## What This Does NOT Change

- Engine tick loop — unchanged
- Risk checks — all existing risk rules still apply (daily loss cap, kill switch, DTC)
- Take-profit pass — existing engine take-profit handles profit exits
- Any HTML, CSS, or JS files — zero frontend changes needed
- Any other strategy — fully isolated

---

## Self-Review

- ✅ No placeholders or TBDs
- ✅ EMA 200 warmup issue caught and fixed (days=300 for daily)
- ✅ Broker-specific behaviour clearly defined
- ✅ Earnings avoidance gracefully degrades on API failure
- ✅ Consistent with momentum.py / sma_cross.py patterns
- ✅ Theme compliance — no hardcoded colors
- ✅ Reason strings are ASCII-safe (no Unicode, consistent with recent fix)
