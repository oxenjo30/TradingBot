# Crypto-Specific Trading Strategies Design

**Date:** 2026-05-13
**Status:** Approved

---

## Goal

Add four crypto-native trading strategies for Binance accounts in TradeBot. These are separate from existing stock strategies, designed for 24/7 crypto markets with USDT pairs (BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT, XRP/USDT, ADA/USDT).

---

## Architecture

Four new files in `server/strategies/`:
- `crypto_trend.py` — EMA crossover trend-following
- `crypto_rsi_bounce.py` — RSI mean-reversion bounce
- `crypto_volatility_breakout.py` — Bollinger Band breakout
- `crypto_grid.py` — Grid trading (Binance-style buy-low/sell-high ladder)

All inherit `Strategy` from `base.py`. No new plumbing: `_get_bars(client, symbol, days)` already routes to Binance data when a Binance client is passed. `_signal(symbol, side, reason)` handles notional sizing.

Registered in `server/strategies/__init__.py` with `crypto_` prefix names. Appear in Bots UI alongside stock strategies — prefix makes crypto strategies visually distinct.

---

## Default Symbols

```python
["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"]
```

User can override via the strategy params UI (symbols field, comma-separated).

---

## Position Sizing

Notional (USD) per trade. Default $500. Configurable per strategy in the UI.

---

## Strategy Specifications

### 1. `crypto_trend` — EMA Crossover Trend

**Logic:**
- Compute fast EMA (default period=9) and slow EMA (default period=21) from daily close prices
- **Buy signal:** fast EMA crosses above slow EMA and not already holding the symbol
- **Sell signal:** fast EMA crosses below slow EMA while holding the symbol
- Checks both current and previous bar to detect the crossover (not just current state)

**Default params:**
```python
{
    "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"],
    "fast_ema": 9,
    "slow_ema": 21,
    "notional": 500,
    "max_positions": 3,
}
```

**UI schema fields:** symbols (symbols type), fast_ema (number, 2-50), slow_ema (number, 5-200), notional (number, 10-100000), max_positions (number, 1-20)

---

### 2. `crypto_rsi_bounce` — RSI Mean-Reversion Bounce

**Logic:**
- Compute RSI (default period=14) from daily closes
- **Buy signal:** RSI was below `rsi_oversold` (35) on the previous bar and is now above it — confirms the bounce, avoids catching falling knives
- **Sell signal:** RSI rises above `rsi_overbought` (65) while holding
- Crypto RSI ranges are tighter than stocks (35/65 vs 30/70) to account for faster mean-reversion

**Default params:**
```python
{
    "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"],
    "rsi_period": 14,
    "rsi_oversold": 35,
    "rsi_overbought": 65,
    "notional": 500,
    "max_positions": 3,
}
```

**UI schema fields:** symbols, rsi_period (number, 2-50), rsi_oversold (number, 10-49), rsi_overbought (number, 51-90), notional, max_positions

---

### 3. `crypto_volatility_breakout` — Bollinger Band Breakout

**Logic:**
- Compute Bollinger Bands: middle = SMA(period), upper = SMA + std_mult * stddev, lower = SMA - std_mult * stddev
- **Buy signal:** current close > upper band and not already holding
- **Sell signal:** current close < middle band (SMA) while holding — exits early to lock in gains
- Default std multiplier 2.0 handles crypto's wider natural volatility

**Default params:**
```python
{
    "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"],
    "bb_period": 20,
    "bb_std": 2.0,
    "notional": 500,
    "max_positions": 3,
}
```

**UI schema fields:** symbols, bb_period (number, 5-100), bb_std (number, 0.5-4.0, step 0.1), notional, max_positions

---

### 4. `crypto_grid` — Grid Trading (Binance-style)

**Logic:**
Simulates Binance's grid trading strategy using price history to determine grid levels:
- User defines a price range (`grid_lower`, `grid_upper`) and number of grid lines (`grid_levels`, default 5)
- Grid lines are evenly spaced between lower and upper bounds
- **Buy signal:** current price is at or below the lowest unoccupied grid level below current price and max_positions not reached
- **Sell signal:** current price is at or above the highest occupied grid level above entry price
- Each grid level is treated as a separate "slot" — the strategy tracks which levels are filled via positions dict
- Since TradeBot can only hold one position per symbol, grid trading is simplified: one symbol = one active grid slot at a time. The strategy buys when price enters a buy zone and sells when it hits the next grid level up.

**Simplified grid logic (one position per symbol):**
- Divide range into N equal bands
- **Buy:** price is in the lower half of the current band and not holding
- **Sell:** price has risen to the upper half of the current band or above while holding

**Default params:**
```python
{
    "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    "grid_lower": 0.0,    # 0 = auto-detect from recent low
    "grid_upper": 0.0,    # 0 = auto-detect from recent high
    "grid_levels": 5,
    "lookback_days": 30,  # used for auto range detection
    "notional": 500,
    "max_positions": 3,
}
```

**Auto-range:** When `grid_lower=0` and `grid_upper=0`, the strategy uses the lowest low and highest high over `lookback_days` as the grid bounds. This mimics Binance's "AI range" feature.

**UI schema fields:** symbols, grid_lower (number, 0+), grid_upper (number, 0+), grid_levels (number, 2-20), lookback_days (number, 7-90), notional, max_positions

---

## Registration

In `server/strategies/__init__.py`, import and add to REGISTRY:
```python
from .crypto_trend import CryptoTrend
from .crypto_rsi_bounce import CryptoRSIBounce
from .crypto_volatility_breakout import CryptoVolatilityBreakout
from .crypto_grid import CryptoGrid

REGISTRY = {
    ...existing entries...,
    "crypto_trend": CryptoTrend,
    "crypto_rsi_bounce": CryptoRSIBounce,
    "crypto_volatility_breakout": CryptoVolatilityBreakout,
    "crypto_grid": CryptoGrid,
}
```

---

## What Does NOT Change

- `base.py` — no changes needed
- `engine.py` — no changes needed (already passes client, already 24/7 for Binance)
- Existing stock strategies — untouched
- Database schema — no changes needed
- UI — no changes needed (Bots page auto-discovers registered strategies)

---

## Testing

Each strategy tested with:
1. Unit test: `evaluate()` returns buy signals when conditions met, sell signals when holding and exit triggered, no signal when max_positions reached
2. Uses a mock client returning synthetic bar data — no live API calls in tests
3. All tested via `pytest tests/` — must pass alongside existing 41 tests
