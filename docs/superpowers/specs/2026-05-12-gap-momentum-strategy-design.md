# Gap & Catalyst Momentum Strategy — Design Spec

**Date:** 2026-05-12  
**Goal:** Add a new intraday-oriented strategy that targets 5–10% single-day gains by detecting gap-up openings confirmed by unusual volume, then exiting at a configurable profit target.

---

## Context

All existing TradeBot strategies use daily bars from `alpaca_client.get_recent_bars()` and run on the engine tick (every 60 s). This strategy follows the same contract — no intraday or real-time data required. It infers "gap" from today's open vs yesterday's close and "unusual volume" from today's bar volume vs the 20-day average.

---

## Strategy Logic

### Entry — all four conditions must be true

| Condition | Parameter | Default |
|-----------|-----------|---------|
| Today's open ≥ X% above yesterday's close | `gap_min_pct` | 3.0% |
| Today's open ≤ Y% above yesterday's close | `gap_max_pct` | 8.0% |
| Today's volume ≥ Z× 20-day average | `volume_multiplier` | 1.5 |
| RSI(14) < overbought threshold | `rsi_entry_max` | 75 |

`gap_max_pct` prevents chasing stocks already up 12–15% where the easy money is gone. Volume confirmation filters news-less drifts. RSI guard avoids stocks already exhausted at open.

### Exit — first condition hit wins

| Condition | Parameter | Default |
|-----------|-----------|---------|
| Position P&L ≥ profit target | `profit_target_pct` | 5.0% |
| RSI(14) > exhaustion level | `rsi_exit` | 80 |

Exit P&L is estimated as `(current_price - avg_entry) / avg_entry`. `avg_entry` is approximated as the open price of today's bar (the bar on which entry fired).

### Position sizing & limits

- `notional` (USD) per trade — same as all other strategies
- `max_positions` cap — same guard as Momentum Breakout

---

## Symbol Universe

Uses the existing scanner (`scanner.get_scanner_universe`) combining top actives + top gainers, plus an optional fixed symbol list. Gap stocks naturally surface in the top-gainers feed, making this pairing highly effective.

Parameters: `use_scanner` (default `True`), `scanner_top_actives` (25), `scanner_top_gainers` (20), `scanner_min_price` (5.0), `scanner_max_price` (500.0), `symbols` (optional fixed list).

---

## File Layout

| File | Change |
|------|--------|
| `server/strategies/gap_momentum.py` | New file — full strategy implementation |
| `server/strategies/__init__.py` | Register `GapMomentum` in `REGISTRY` |

No other files need changes. The engine, DB, and UI all pick up new strategies automatically via `REGISTRY`.

---

## UI Parameters (params_schema)

| Key | Label | Type | Range | Hint |
|-----|-------|------|-------|------|
| `gap_min_pct` | Min Gap % | number | 1–20 | Today's open must be at least this % above yesterday's close to qualify. |
| `gap_max_pct` | Max Gap % | number | 1–50 | Ignores stocks that have already gapped beyond this % — avoids chasing. |
| `profit_target_pct` | Profit Target % | number | 1–50 | Sell when position is up this % from entry. |
| `volume_multiplier` | Volume Confirmation | number | 1.0–10.0 | Today's volume must be this many times the 20-day average. |
| `rsi_entry_max` | RSI Entry Max | number | 50–99 | Skip buy if RSI already above this — stock may be exhausted. |
| `rsi_exit` | RSI Exit (Exhaustion) | number | 60–99 | Sell when RSI rises above this while holding. |
| `notional` | Amount per Trade (USD) | number | 10–100000 | Dollar amount per buy signal. |
| `max_positions` | Max Open Positions | number | 1–50 | Cap on simultaneous open positions. |
| `use_scanner` | Auto-discover Stocks | bool | — | Use market scanner to find gapping stocks automatically. |
| `symbols` | Symbols to Trade | symbols | — | Optional fixed list of tickers to always include. |

---

## Error Handling

- Bars fetch failure → `continue` to next symbol (same as all existing strategies)
- Fewer than 2 bars returned → skip (can't compute gap without yesterday's close)
- `avg_entry` approximation: use `bars[-1]["o"]` (today's open). If open is 0 or missing, skip exit P&L check and rely solely on RSI exit.

---

## Testing

Manual verification via backtesting page: run against a date range containing known gap-up events (e.g. earnings weeks). Confirm:
1. Signals only fire on days where open/prev-close gap ≥ `gap_min_pct`
2. No buy signals fire when position count = `max_positions`
3. Sell signals fire when simulated P&L crosses `profit_target_pct`
