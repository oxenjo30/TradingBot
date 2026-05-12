# AI Trade Explanation & Continuous Learning Design

## Goal

Add an AI layer to TradeBot that (1) generates a plain-English explanation for every trade signal as it fires, and (2) analyzes past trade outcomes weekly and automatically tunes strategy parameters to improve performance over time — notifying the user of every change made.

## Architecture

Two new server modules added to `server/`:

### `server/ai_explainer.py`
- Exposes `enqueue(signal_data: dict)` — called by the engine immediately after `db.log_signal()`
- A single daemon thread runs a blocking queue loop, builds a prompt from signal context, calls Ollama via `POST http://localhost:11434/api/generate`, and writes the result back to `signals.ai_explanation`
- If Ollama is unreachable: silently skips — no crash, no engine slowdown
- On server startup: calls `db.get_unexplained_signals(limit=50)` and re-enqueues any signals that were never explained (e.g. Ollama was offline)
- Ollama model defaults to `llama3`, configurable via `OLLAMA_MODEL` in app_config

### `server/ai_tuner.py`
- Exposes `run_tuning()` — callable by the weekly scheduler and by the "Run Now" API endpoint
- Iterates every enabled strategy with ≥ 10 trades in the last 90 days
- For each: queries `strategy_perf`, builds a prompt, parses Ollama's JSON response, validates bounds, applies params via `db.upsert_strategy()`, logs to `ai_tuning_log`
- Sends one consolidated email/Telegram notification after all strategies are processed
- If Ollama unreachable: logs warning, sends no notification, makes no changes

### Engine changes
- One line added after `db.log_signal(...)`: `ai_explainer.enqueue(signal_data)`
- Weekly timer added using `threading.Timer` — fires every Sunday at 11 PM ET, calls `ai_tuner.run_tuning()`

---

## Data Layer

### Migration: `signals.ai_explanation`
```sql
ALTER TABLE signals ADD COLUMN ai_explanation TEXT DEFAULT NULL;
```
`NULL` = not yet explained. Non-null string = Ollama has processed it.

### New table: `ai_tuning_log`
```sql
CREATE TABLE IF NOT EXISTS ai_tuning_log (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at       TEXT NOT NULL,
  strategy         TEXT NOT NULL,
  old_params       TEXT NOT NULL,   -- JSON
  new_params       TEXT NOT NULL,   -- JSON
  rationale        TEXT NOT NULL,   -- Ollama's explanation
  win_rate_before  REAL,
  win_rate_after   REAL DEFAULT NULL  -- filled in on the next tuning run
);
```

### New DB helper functions in `db.py`
- `set_signal_explanation(signal_id: int, text: str)` — writes explanation back to signals row
- `get_unexplained_signals(limit: int = 50) -> list[dict]` — signals where ai_explanation IS NULL, oldest first
- `log_tuning_run(strategy, old_params, new_params, rationale, win_rate_before) -> int`
- `get_tuning_history(strategy: str) -> list[dict]`
- `list_tuning_log() -> list[dict]` — all runs, newest first
- `revert_tuning_run(run_id: int) -> bool` — restores old_params for the strategy

---

## AI Explainer — Prompt & Behaviour

**Prompt template:**
```
You are a trading assistant explaining a trade signal to its owner.
Be concise (2-3 sentences). Use plain English, no jargon.

Strategy: {strategy_label}
Symbol: {symbol}
Side: {side}
Signal reason: {reason}
Time: {ts} ET

Past performance of this strategy (last 90 days):
- Win rate: {win_rate}%, Avg P&L: ${avg_pnl}, Total trades: {total_trades}

Explain why this trade was taken and what the strategy is looking for.
```

**Example output:**
> "RSI Mean Reversion bought AAPL because its RSI fell to 27.4, well below the oversold threshold of 30, signaling the stock may be due for a bounce. The strategy also confirmed the overall trend is up since price sits above the 14-day moving average. This setup has produced a 63% win rate over the last 90 days."

---

## AI Tuner — Prompt & Behaviour

**Prompt template:**
```
You are a trading strategy optimizer. Suggest parameter adjustments
as valid JSON only — no explanation outside the JSON block.

Strategy: {strategy_label}
Current params: {current_params_json}
Param bounds: {bounds_summary}

Performance last 90 days:
- Total trades: {total_trades}, Win rate: {win_rate}%, Avg P&L: ${avg_pnl}

Suggest new params that may improve win rate.
Reply with ONLY: {"params": {...}, "rationale": "..."}
```

**Safety guards:**
- Only adjusts params within each param's `min`/`max` from `params_schema` — out-of-range values are rejected and the strategy is skipped
- Skips strategies with fewer than 10 trades in the 90-day window
- Never disables a strategy — only tunes numeric params
- If Ollama response is malformed JSON: logs a warning, skips that strategy, no change made
- `win_rate_after` is filled in on the subsequent tuning run, allowing the tuner to track whether its own changes helped

**Schedule:** Every Sunday at 11 PM ET via `threading.Timer` chained recursively in `engine.py`.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/signals/{id}/explanation` | Returns `{explanation, ready: bool}` for polling |
| `GET` | `/api/ai/tuning-log` | Returns full tuning history, newest first |
| `POST` | `/api/ai/tune-now` | Triggers immediate tuning run (async, returns job id) |
| `GET` | `/api/ai/status` | Ollama reachability + current model name |
| `PATCH` | `/api/ai/settings` | Saves model/URL/enabled toggles to app_config |
| `POST` | `/api/ai/tuning-log/{id}/revert` | Restores old_params from a specific tuning run |

---

## UI Changes

### Logs & Signals page
- Each row gets a small info icon button (ℹ)
- Clicking expands an inline explanation panel below the row
- If `ai_explanation` is stored: renders immediately
- If `NULL`: shows amber "Generating…" pill, polls `GET /api/signals/{id}/explanation` every 2s until `ready: true`

### New page: `/static/ai-tuning.html`
- Linked from sidebar under System section (between Risk and Logs)
- Shows `ai_tuning_log` as a table: Date, Strategy, Win Rate Before, Changes Made, Rationale
- Each row has a **Revert** button — calls `POST /api/ai/tuning-log/{id}/revert`, re-fetches table
- Empty state: "No tuning runs yet. The AI will analyze your strategies every Sunday at 11 PM."

### Settings page — new "AI Assistant" section
- Ollama URL input (default `http://localhost:11434`)
- Ollama model input (default `llama3`)
- Toggle: Enable trade explanations
- Toggle: Enable weekly parameter tuning
- "Run Tuning Now" button — calls `POST /api/ai/tune-now`, shows spinner + success message
- Ollama connection status dot (green = reachable, red = offline) — tested on page load via `GET /api/ai/status`

---

## Error Handling

- Ollama offline: all AI features degrade gracefully — engine continues normally, explanations stay NULL, tuner skips silently
- Malformed JSON from tuner: strategy skipped, warning logged to server log
- Out-of-bounds params from tuner: rejected, strategy skipped
- Explanation queue overflow (> 500 items): oldest items dropped, warning logged
- Revert on a strategy that no longer exists: returns 404, no change

---

## Tech Stack

- **Ollama** local inference — `http://localhost:11434/api/generate`
- Default model: `llama3` (configurable)
- Python `queue.Queue` for async explanation processing
- `threading.Timer` for weekly schedule
- SQLite migrations via existing `init_db()` pattern
