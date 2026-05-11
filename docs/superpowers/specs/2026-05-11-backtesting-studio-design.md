# Backtesting Studio — Design Spec
**Date:** 2026-05-11
**Status:** Approved

---

## Overview

A full backtesting feature for TradeBot that lets users run any registered strategy against historical OHLCV data from Alpaca, review simulation results, and save/compare runs over time.

**Tech stack:** FastAPI + SQLite3 backend, Alpaca historical bars API, vanilla JS + Tailwind CDN + ApexCharts, no build step.

---

## Confirmed Design Decisions

| Topic | Decision |
|---|---|
| Symbol mode | Single symbol (default) and multi-symbol (comma-separated) |
| Save & compare | All runs auto-saved to DB; user can label, load, and delete |
| Simulation fills | Next-day open price ± configurable slippage % |
| Commission | Configurable % deducted per trade from portfolio equity |
| Position sizing | Always % of current portfolio equity (not strategy's fixed notional) |
| Engine approach | Hybrid: context-manager patches `alpaca_client.get_recent_bars()` for existing strategies; `BarsProvider` protocol added to `base.py` for new strategies |
| Page layout | Option B — Stacked (config bar at top, results fill page below) |

---

## Architecture

### New Files

**`server/backtest.py`**
- `BacktestEngine` class — core simulation logic
- `run(strategy_name, symbols, start_date, end_date, initial_capital, position_size_pct, commission_pct, slippage_pct)` → returns result dict

**`server/strategies/base.py`** (modified)
- Adds `BarsProvider` protocol — a simple `Protocol` with `get_bars(symbol, limit) -> list` method
- Existing strategies are unaffected (no breaking change)

### Modified Files

| File | Change |
|---|---|
| `server/db.py` | New `backtest_runs` table + 5 CRUD functions |
| `server/main.py` | 5 new REST endpoints |
| `server/static/backtesting.html` | Full rewrite (stacked layout) |
| `server/static/app.js` | `initBacktesting()` + PAGE_INIT entry |

---

## Data Model

### `backtest_runs` Table

```sql
CREATE TABLE backtest_runs (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at        TEXT NOT NULL,
  name              TEXT,                  -- optional user label
  strategy          TEXT NOT NULL,
  symbols           TEXT NOT NULL,         -- JSON array e.g. ["AAPL","MSFT"]
  start_date        TEXT NOT NULL,
  end_date          TEXT NOT NULL,
  initial_capital   REAL NOT NULL,
  position_size_pct REAL NOT NULL,
  commission_pct    REAL NOT NULL,
  slippage_pct      REAL NOT NULL,
  total_return_pct  REAL,
  max_drawdown_pct  REAL,
  win_rate_pct      REAL,
  sharpe_ratio      REAL,
  total_trades      INTEGER,
  equity_curve      TEXT,                  -- JSON [{date, equity}, ...]
  trades            TEXT                   -- JSON [{date, symbol, side, qty, price, pnl}, ...]
);
```

### DB Functions (added to `db.py`)

- `save_backtest_run(params, results)` → `int` (new run id)
- `list_backtest_runs()` → list of summary dicts (no equity_curve/trades)
- `get_backtest_run(id)` → full run dict including equity_curve + trades
- `delete_backtest_run(id)` → None
- `rename_backtest_run(id, name)` → None

---

## API Endpoints

```
POST   /api/backtest              Run engine, auto-save result, return full result
GET    /api/backtest/runs         List saved runs (summary only — no curves/trades)
GET    /api/backtest/runs/{id}    Full run detail (equity curve + trades included)
PATCH  /api/backtest/runs/{id}    Update run name — body: {"name": "..."}
DELETE /api/backtest/runs/{id}    Delete a saved run
```

**`POST /api/backtest` request body:**
```json
{
  "strategy":          "momentum",
  "symbols":           ["AAPL"],
  "start_date":        "2024-01-01",
  "end_date":          "2024-12-31",
  "initial_capital":   10000.0,
  "position_size_pct": 2.0,
  "commission_pct":    0.1,
  "slippage_pct":      0.05
}
```

**`POST /api/backtest` response:**
```json
{
  "id":               42,
  "total_return_pct": 24.3,
  "max_drawdown_pct": -8.1,
  "win_rate_pct":     61.0,
  "sharpe_ratio":     1.42,
  "total_trades":     47,
  "equity_curve":     [{"date": "2024-01-02", "equity": 10000.0}, ...],
  "trades":           [{"date": "2024-01-05", "symbol": "AAPL", "side": "buy", "qty": 12, "price": 185.20, "pnl": 320.0}, ...]
}
```

Runs synchronously. For typical date ranges (1–3 years, 1–5 symbols) this completes in under 2 seconds. Frontend shows a spinner while waiting.

---

## Engine Logic (`BacktestEngine.run`)

1. **Fetch full history** — call `alpaca_client.get_recent_bars(symbol, limit=N)` for each symbol, where N = trading days in the date range + 200 (buffer for strategy lookback windows). Store as `{symbol: [bars]}` sorted ascending by date.

2. **Build trading calendar** — union of all bar dates across symbols, filtered to `[start_date, end_date]`.

3. **Context-manager patch** — `get_recent_bars` is monkeypatched inside a `with` block. On each tick, the patch returns only bars with `date <= current_simulation_date`, so the strategy never sees future data.

4. **Tick loop** — for each simulation date:
   - Call `strategy.generate_signals()` for each symbol
   - On BUY signal: calculate `notional = portfolio_equity × position_size_pct / 100`, compute shares; skip if symbol already held
   - On SELL signal: close existing position if held; silently skip if no position open for that symbol
   - Fill at **next bar's open**: BUY fills at `open × (1 + slippage_pct/100)`, SELL at `open × (1 - slippage_pct/100)`
   - Commission deducted: `notional × commission_pct / 100` from cash
   - Mark-to-market portfolio equity updated each bar

5. **Summary stats computed at end:**
   - `total_return_pct` = `(final_equity − initial_capital) / initial_capital × 100`
   - `max_drawdown_pct` = largest peak-to-trough equity drop
   - `win_rate_pct` = profitable closed trades / total closed trades × 100
   - `sharpe_ratio` = annualised mean daily return / std dev of daily returns × √252

6. **Result persisted** — `db.save_backtest_run()` called before returning to caller.

### `BarsProvider` Protocol (`base.py`)

```python
from typing import Protocol

class BarsProvider(Protocol):
    def get_bars(self, symbol: str, limit: int) -> list[dict]: ...
```

Existing strategies continue calling `alpaca_client.get_recent_bars()` directly. New strategies can accept an injected `BarsProvider` for cleaner unit testing.

---

## Frontend

### `backtesting.html` — Stacked Layout

**Page header** (sticky, matches all other pages):
- Title: "Backtesting Studio"
- Subtitle: "Test strategies against historical OHLCV data"

**Config card** (always visible):
- Row 1: Strategy `<select>` | Symbol `<input>` (comma-sep for multi) | Start date | End date
- Row 2: Initial capital | Position size % | Commission % (default 0.1) | Slippage % (default 0.05)
- Run button — right-aligned, blue `.btn-primary`, shows spinner + "Running…" during fetch

**Results section** (hidden until first run):
- 5 stat pills: Total Return (green if positive, red if negative) | Max Drawdown (red) | Win Rate | Sharpe Ratio | Total Trades
- ApexCharts area chart — equity curve, blue gradient fill matching app style
- Name row: optional text input for run name + "Save Name" button → `PATCH /api/backtest/runs/{id}` (run is already auto-saved on completion)
- Trades table (`.dtable`): Date | Symbol | Side (BUY/SELL badge) | Shares | Fill Price | P&L

**History section** (always visible below results):
- Card titled "Saved Runs"
- Each row: name or timestamp | strategy | symbols | return % | drawdown | win rate | **Load** button | **Delete** button
- Load replaces results section with that run's data (no new backtest run)

### `app.js` additions

```
PAGE_INIT entry:  backtesting: initBacktesting

Functions:
  initBacktesting()     — populate strategy dropdown, wire all handlers, load history
  runBacktest()         — POST /api/backtest, show spinner, call renderResults()
  renderResults(data)   — draw stat pills + ApexCharts equity curve + trades table
  renderHistory(runs)   — render saved runs list with Load/Delete handlers
  loadRun(id)           — GET /api/backtest/runs/{id}, call renderResults()
  deleteRun(id)         — DELETE /api/backtest/runs/{id}, refresh history
  renameRun(id, name)   — PATCH  /api/backtest/runs/{id}, update history row label
```

**Strategy dropdown** — populated from a hardcoded list matching the strategies registered in `server/strategies/`:
`SMA Cross`, `Golden Cross`, `RSI Mean Reversion`, `MACD + Volume`, `Bollinger Bands`, `Momentum`, `52-Week Breakout`, `Manual`

---

## Error Handling

- If Alpaca returns no bars for a symbol/date range: return 400 with `{"detail": "No historical data found for AAPL in the given date range"}`
- If strategy key is unknown: return 400 with `{"detail": "Unknown strategy: xyz"}`
- If `end_date <= start_date`: return 422 from Pydantic validation
- Frontend displays API `detail` messages in a red banner below the config card

---

## Out of Scope

- Real-time progress streaming (WebSocket tick-by-tick updates)
- Walk-forward / Monte Carlo analysis
- Multi-strategy comparison within a single run
- Exporting results to CSV
