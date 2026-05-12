# Strategy Health — Live vs Backtest Drift Monitor
**Date:** 2026-05-12
**Status:** Approved

---

## Overview

A "Strategy Health" section added to the Performance page that compares each strategy's live win rate and average return-per-trade against a user-designated backtest benchmark run. When divergence exceeds defined thresholds the strategy is flagged as drifting, giving traders early warning before losses accumulate.

This feature is uniquely differentiated in the retail trading bot market — no SaaS or open-source competitor surfaces this comparison clearly.

---

## Confirmed Design Decisions

| Topic | Decision |
|---|---|
| Where health is shown | New card on existing `performance.html`, below Strategy Statistics |
| Benchmark designation | Star button on each row of the Backtest History table (also on `backtesting.html`) |
| Live metric source | SQL aggregate over `strategy_perf` table (already populated by engine) |
| Benchmark metric source | `backtest_runs` table — `win_rate_pct` and `total_return_pct / total_trades` |
| Drift thresholds | Green ≤15%, Yellow 15–30%, Red >30% divergence on worst of win rate or avg return |
| Minimum live trades | 10 trades required before health is evaluated (below threshold → "No Data") |
| No benchmark set | Row shows "No Benchmark" pill with greyed metrics |
| Expand/collapse | Clicking a row expands a detail panel with benchmark name, period, backtest stats, "View Backtest" link |
| Backtesting page change | Run history table gains a "Set Benchmark" / "Benchmark ★" button per row |
| Mockup | `server/static/mockup-strategy-health.html` — implementation must match exactly |

---

## Architecture

### Data Model Changes

**`backtest_runs` table** — one new column added via migration:

```sql
ALTER TABLE backtest_runs ADD COLUMN is_benchmark INTEGER NOT NULL DEFAULT 0;
```

One run per strategy may be the benchmark at a time. Enforced at the DB helper level (clear existing benchmark for the strategy before setting the new one), not via SQL constraint — consistent with existing TradeBot patterns.

**`strategy_perf` table** — no changes needed. Win rate and avg return are computed on-the-fly via SQL aggregation.

---

### New DB Helpers (`server/db.py`)

**`set_benchmark(run_id: int) -> bool`**
- Looks up the strategy name for `run_id`
- Clears `is_benchmark = 0` for all runs with that strategy
- Sets `is_benchmark = 1` for `run_id`
- Returns `True` if successful, `False` if run not found

**`get_benchmark(strategy: str) -> dict | None`**
- Returns the benchmark run for the given strategy: `{id, name, win_rate_pct, avg_return_pct, total_trades, start_date, end_date}`
- `avg_return_pct` = `total_return_pct / total_trades` (computed in Python, not SQL)
- Returns `None` if no benchmark is set

**`get_live_health_stats(strategy: str) -> dict`**
- SQL aggregate over `strategy_perf` for the given strategy:
  - `total_trades`: `COUNT(*)`
  - `winning_trades`: `COUNT(*) WHERE pnl > 0`
  - `live_win_rate`: `winning_trades / total_trades` (0.0 if no trades)
  - `live_avg_return_pct`: `AVG(pnl_pct)` (0.0 if no trades)
- Returns dict with those four keys

**`list_backtest_runs_with_benchmark() -> list[dict]`**
- Extends existing `list_backtest_runs()` to include `is_benchmark` column
- Used by backtesting page to show star state per row

---

### New API Endpoints (`server/main.py`)

**`GET /api/strategy-health`**

Returns health stats for all registered strategies. Calls `get_strategies()`, then for each strategy calls `get_benchmark()` and `get_live_health_stats()` and computes `drift_status`.

Response shape (array):
```json
[
  {
    "strategy": "RSI Mean Reversion",
    "live_trades": 42,
    "live_win_rate": 0.42,
    "live_avg_return_pct": 0.7,
    "benchmark_run_id": 3,
    "benchmark_run_name": "RSI MR Apr-2025",
    "benchmark_start_date": "2025-01-01",
    "benchmark_end_date": "2025-04-30",
    "benchmark_total_trades": 183,
    "benchmark_win_rate": 0.62,
    "benchmark_avg_return_pct": 1.8,
    "drift_status": "red"
  }
]
```

`drift_status` values: `"green"` | `"yellow"` | `"red"` | `"no_benchmark"` | `"no_data"`

Drift computation logic:
```python
def compute_drift_status(live_wr, live_ar, bench_wr, bench_ar, live_trades):
    if live_trades < 10:
        return "no_data"
    wr_div = abs(live_wr - bench_wr) / max(bench_wr, 0.001)
    ar_div = abs(live_ar - bench_ar) / max(abs(bench_ar), 0.001)
    worst = max(wr_div, ar_div)
    if worst <= 0.15:   return "green"
    if worst <= 0.30:   return "yellow"
    return "red"
```

**`POST /api/backtest-runs/{run_id}/set-benchmark`**

Calls `db.set_benchmark(run_id)`. Returns `{"ok": true}` or 404 if run not found. Auth-gated via `_require_auth`.

**`GET /api/backtest-runs/{run_id}/benchmark-status`**

Returns `{"is_benchmark": true/false}` for the given run. Used by backtesting page on load to restore star state.

> Note: `list_backtest_runs` response already returns all fields needed — the existing `GET /api/backtest/runs` endpoint is extended to include `is_benchmark` in the response (no breaking change, additive field only).

---

## UI Changes

### `server/static/performance.html`

Add a new card **after** the "Strategy Statistics / Top Symbols" row and **before** the "Daily Signal Activity" chart. The card:

- Has a blue→purple gradient accent bar at the top (matching modal style)
- Header: icon + "Strategy Health" title + subtitle + summary count badges ("N on track · N drifting")
- Table columns: *(expand toggle)* | Strategy | Win Rate | Avg Return / Trade | Live Trades | Health
- Each metric cell shows two rows: live value (colored by drift) + benchmark value in muted text with a delta chip
- Health pill: **On Track** (green), **Watching** (yellow), **Drifting** (red), **No Benchmark** (grey), **Need More Data** (grey, <10 trades)
- Clicking a row toggles an expand panel showing: benchmark run name, period, backtest win rate, backtest avg return, backtest total trades, account name, "View Backtest" button
- Footer hint linking to Backtesting page to set a benchmark
- Exact visual: matches `mockup-strategy-health.html`

### `server/static/app.js`

New function `initPerformance()` additions (or new `initStrategyHealth()` called from `initPerformance()`):

- `GET /api/strategy-health` on page load
- Renders health table rows with correct pills, delta chips, metric pairs
- Wires row click → expand/collapse detail panel
- Handles all states: no_benchmark, no_data, green, yellow, red

### `server/static/backtesting.html`

Backtest History table gains a **Benchmark** column. Each row shows:
- If `is_benchmark === true`: filled star button styled as `bench-star-btn is-bench` with label "Benchmark"
- If `is_benchmark === false`: outline star button with label "Set Benchmark"

Clicking "Set Benchmark": `POST /api/backtest-runs/{id}/set-benchmark` → on success, update all rows for same strategy (clear other benchmarks for that strategy in the UI), set this row to filled star.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `server/db.py` | **Modify** | Add `is_benchmark` migration + 3 new helpers |
| `server/main.py` | **Modify** | Add 3 new endpoints; extend `list_backtest_runs` response |
| `server/static/performance.html` | **Modify** | Add Strategy Health card |
| `server/static/backtesting.html` | **Modify** | Add Benchmark column to run history table |
| `server/static/app.js` | **Modify** | Wire health card + benchmark toggle |
| `tests/test_strategy_health.py` | **Create** | Unit tests for DB helpers + API endpoints |
| `server/static/mockup-strategy-health.html` | **Reference** | Visual specification — do not modify |

---

## Tests (`tests/test_strategy_health.py`)

- `test_set_benchmark_sets_flag` — verifies `is_benchmark=1` after call, other runs for same strategy cleared
- `test_set_benchmark_unknown_run_returns_false` — returns False for non-existent run_id
- `test_get_benchmark_returns_none_when_none_set` — no benchmark set → returns None
- `test_get_live_health_stats_empty` — no rows in strategy_perf → returns zeros
- `test_get_live_health_stats_counts_correctly` — insert known rows, verify win rate and avg return
- `test_strategy_health_endpoint_returns_all_strategies` — GET /api/strategy-health returns one entry per strategy
- `test_set_benchmark_endpoint_returns_ok` — POST /api/backtest-runs/{id}/set-benchmark → 200 + `{"ok": true}`
- `test_set_benchmark_endpoint_404` — POST with unknown id → 404

---

## Drift Threshold Rationale

| Status | Condition | Meaning |
|---|---|---|
| On Track (green) | Worst divergence ≤ 15% | Normal market variance — strategy behaving as expected |
| Watching (yellow) | 15–30% divergence | Noticeable underperformance — monitor closely |
| Drifting (red) | >30% divergence | Strategy may no longer reflect backtest conditions — consider pausing or re-optimising |

Thresholds use relative divergence (not absolute) so a strategy with a 60% backtest win rate and 50% live win rate is flagged the same as one with 30% vs 25%.
