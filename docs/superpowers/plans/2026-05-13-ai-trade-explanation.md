# AI Trade Explanation & Continuous Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add local-AI-powered plain-English explanations for every trade signal and a weekly adaptive parameter tuner that automatically adjusts strategy params based on recent performance.

**Architecture:** Two new Python modules (`server/ai_explainer.py` and `server/ai_tuner.py`) integrate with the existing FastAPI server. The explainer runs as a daemon thread with a `queue.Queue`; the tuner fires weekly via `threading.Timer`. Both call Ollama at `http://localhost:11434/api/generate` and degrade gracefully when Ollama is offline.

**Tech Stack:** Python `queue.Queue`, `threading.Timer`, `urllib.request` (stdlib — no new deps), SQLite migrations via existing `init_db()` pattern, Ollama local inference, existing `notifications` module for tuner alerts.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `server/ai_explainer.py` | **Create** | Async queue daemon — builds prompts, calls Ollama, writes `ai_explanation` back to signals |
| `server/ai_tuner.py` | **Create** | Weekly tuner — queries perf, calls Ollama, validates & applies param changes, sends notification |
| `server/db.py` | **Modify** | Add 6 new helper functions + 2 DB migrations (`signals.ai_explanation`, `ai_tuning_log`) |
| `server/engine.py` | **Modify** | Call `ai_explainer.enqueue()` after `db.log_signal()`; add weekly `threading.Timer` for tuner |
| `server/main.py` | **Modify** | Add 6 new API endpoints for AI features |
| `server/static/ai-tuning.html` | **Create** | New page: tuning log table with Revert buttons |
| `server/static/index.html` | **Modify** | Add "AI Tuning" nav link in System section |
| `server/static/logs.html` | **Modify** | Add ℹ column header; widen colspan from 7 to 8 |
| `server/static/settings.html` | **Modify** | Add "AI Assistant" settings card before the save button |
| `server/static/app.js` | **Modify** | `initLogs()` explain button + polling; `initSettings()` AI section load/save; `initAiTuning()` new page function |

---

## Task 1: DB migrations and helper functions

**Files:**
- Modify: `server/db.py`

- [ ] **Step 1: Add `ai_explanation` column migration to `init_db()`**

In `server/db.py`, at the end of `init_db()` (after the `is_benchmark` migration block, around line 255), add:

```python
    # Migration: add ai_explanation to signals if missing
    with get_conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(signals)")]
        if "ai_explanation" not in cols:
            c.execute("ALTER TABLE signals ADD COLUMN ai_explanation TEXT DEFAULT NULL")
    # Migration: create ai_tuning_log table if missing
    with get_conn() as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "ai_tuning_log" not in tables:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS ai_tuning_log (
                  id               INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at       TEXT NOT NULL,
                  strategy         TEXT NOT NULL,
                  old_params       TEXT NOT NULL,
                  new_params       TEXT NOT NULL,
                  rationale        TEXT NOT NULL,
                  win_rate_before  REAL,
                  win_rate_after   REAL DEFAULT NULL
                );
            """)
```

- [ ] **Step 2: Add 6 new DB helper functions**

Append to the end of `server/db.py`:

```python
# ── AI helpers ─────────────────────────────────────────────────────────────────

def set_signal_explanation(signal_id: int, text: str) -> None:
    with get_conn() as c:
        c.execute("UPDATE signals SET ai_explanation=? WHERE id=?", (text, signal_id))


def get_unexplained_signals(limit: int = 50) -> list[dict]:
    with get_conn() as c:
        rows = c.execute(
            """SELECT id, ts, strategy, symbol, side, reason
               FROM signals
               WHERE ai_explanation IS NULL
                 AND status NOT IN ('blocked', 'error')
                 AND symbol NOT IN ('-', '')
               ORDER BY id ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_signal_explanation(signal_id: int) -> str | None:
    with get_conn() as c:
        row = c.execute(
            "SELECT ai_explanation FROM signals WHERE id=?", (signal_id,)
        ).fetchone()
    return row["ai_explanation"] if row else None


def log_tuning_run(
    strategy: str,
    old_params: dict,
    new_params: dict,
    rationale: str,
    win_rate_before: float | None,
) -> int:
    with get_conn() as c:
        cur = c.execute(
            """INSERT INTO ai_tuning_log
               (created_at, strategy, old_params, new_params, rationale, win_rate_before)
               VALUES (?,?,?,?,?,?)""",
            (now_iso(), strategy, json.dumps(old_params), json.dumps(new_params),
             rationale, win_rate_before),
        )
        return cur.lastrowid


def list_tuning_log() -> list[dict]:
    with get_conn() as c:
        rows = c.execute(
            "SELECT * FROM ai_tuning_log ORDER BY id DESC"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["old_params"] = json.loads(d["old_params"])
        d["new_params"] = json.loads(d["new_params"])
        result.append(d)
    return result


def get_tuning_run(run_id: int) -> dict | None:
    with get_conn() as c:
        row = c.execute(
            "SELECT * FROM ai_tuning_log WHERE id=?", (run_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["old_params"] = json.loads(d["old_params"])
    d["new_params"] = json.loads(d["new_params"])
    return d


def revert_tuning_run(run_id: int) -> bool:
    run = get_tuning_run(run_id)
    if not run:
        return False
    strat = get_strategy(run["strategy"])
    if not strat:
        return False
    upsert_strategy(run["strategy"], enabled=strat["enabled"], params=run["old_params"])
    return True


def get_strategy_perf_90d(strategy: str) -> dict:
    """Win rate, avg P&L, and trade count for a strategy over the last 90 days."""
    with get_conn() as c:
        row = c.execute(
            """SELECT
                COUNT(*)                                      AS total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)    AS wins,
                COALESCE(AVG(pnl), 0.0)                      AS avg_pnl
               FROM strategy_perf
               WHERE strategy=?
                 AND date >= DATE('now', '-90 days')""",
            (strategy,),
        ).fetchone()
    total = row["total_trades"] or 0
    wins  = row["wins"] or 0
    return {
        "total_trades": total,
        "win_rate":     round(wins / total * 100, 1) if total else 0.0,
        "avg_pnl":      round(row["avg_pnl"], 2),
    }
```

- [ ] **Step 3: Verify the migrations run cleanly**

Start the server and check the log for errors:
```
cd c:\TradeBot
python -m uvicorn server.main:app --port 8000
```
Expected: no `OperationalError` in the log. Stop with Ctrl+C.

- [ ] **Step 4: Commit**

```bash
git add server/db.py
git commit -m "feat: db migrations and helpers for AI explanations and tuning log"
```

---

## Task 2: `server/ai_explainer.py` — async explanation queue

**Files:**
- Create: `server/ai_explainer.py`

- [ ] **Step 1: Create the file**

```python
"""Async trade signal explainer — calls Ollama in a background thread."""
import json
import logging
import queue
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import db
from .config import get_app_config_cached  # defined in Task 2 Step 1 note below

log = logging.getLogger("ai_explainer")

_Q: queue.Queue = queue.Queue(maxsize=500)
_started = False
_lock = threading.Lock()


def _ollama_url() -> str:
    return db.get_app_config("ai_ollama_url", "http://localhost:11434")


def _ollama_model() -> str:
    return db.get_app_config("ai_ollama_model", "llama3")


def _explanations_enabled() -> bool:
    return db.get_app_config("ai_explanations_enabled", "true") == "true"


def _call_ollama(prompt: str) -> str | None:
    payload = json.dumps({
        "model": _ollama_model(),
        "prompt": prompt,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{_ollama_url()}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip()
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


def _build_prompt(sig: dict) -> str:
    perf = db.get_strategy_perf_90d(sig["strategy"])
    strat_label = sig["strategy"].replace("_", " ").title()
    ts_fmt = sig.get("ts", "")[:16].replace("T", " ")
    return (
        "You are a trading assistant explaining a trade signal to its owner.\n"
        "Be concise (2-3 sentences). Use plain English, no jargon.\n\n"
        f"Strategy: {strat_label}\n"
        f"Symbol: {sig['symbol']}\n"
        f"Side: {sig['side']}\n"
        f"Signal reason: {sig.get('reason', '')}\n"
        f"Time: {ts_fmt} ET\n\n"
        "Past performance of this strategy (last 90 days):\n"
        f"- Win rate: {perf['win_rate']}%, "
        f"Avg P&L: ${perf['avg_pnl']}, "
        f"Total trades: {perf['total_trades']}\n\n"
        "Explain why this trade was taken and what the strategy is looking for."
    )


def _worker():
    while True:
        item = _Q.get()
        if item is None:
            break
        signal_id, sig = item
        if not _explanations_enabled():
            _Q.task_done()
            continue
        try:
            prompt = _build_prompt(sig)
            explanation = _call_ollama(prompt)
            if explanation:
                db.set_signal_explanation(signal_id, explanation)
            else:
                log.debug("Ollama unreachable or empty response for signal %d", signal_id)
        except Exception:
            log.exception("Explainer worker error for signal %d", signal_id)
        finally:
            _Q.task_done()


def start():
    """Start the background explanation worker. Called once on server startup."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=_worker, daemon=True, name="ai-explainer")
    t.start()
    # Re-enqueue any signals that were never explained (e.g. Ollama was offline)
    try:
        backlog = db.get_unexplained_signals(limit=50)
        for sig in backlog:
            enqueue(sig)
        if backlog:
            log.info("Re-enqueued %d unexplained signals", len(backlog))
    except Exception:
        log.exception("Failed to load backlog of unexplained signals")


def enqueue(sig: dict) -> None:
    """Add a signal to the explanation queue. Drops oldest if queue is full."""
    signal_id = sig.get("id")
    if signal_id is None:
        return
    try:
        _Q.put_nowait((signal_id, sig))
    except queue.Full:
        try:
            _Q.get_nowait()
            _Q.put_nowait((signal_id, sig))
            log.warning("Explanation queue full — dropped oldest item")
        except queue.Empty:
            pass


def ollama_status() -> dict:
    """Return {reachable: bool, model: str, url: str}."""
    url = _ollama_url()
    model = _ollama_model()
    try:
        req = urllib.request.Request(f"{url}/api/tags", method="GET")
        urllib.request.urlopen(req, timeout=5)
        return {"reachable": True, "model": model, "url": url}
    except Exception:
        return {"reachable": False, "model": model, "url": url}
```

> **Note on `get_app_config_cached`:** The explainer calls `db.get_app_config()` on every signal — that's a DB read per trade. That is fine for the low volume of this app. Use `db.get_app_config` directly; do NOT add a caching layer. Remove the import of `get_app_config_cached` and replace all three config reads at the top of functions with `db.get_app_config(...)` calls directly (already shown correctly above — the import line is wrong; remove it, the functions already call `db.get_app_config`).

Fix the import at the top of the file — remove the `get_app_config_cached` import line entirely. The three helper functions already call `db.get_app_config(...)` so no import is needed.

Correct top-of-file imports:
```python
from . import db
```

- [ ] **Step 2: Verify syntax**

```bash
cd c:\TradeBot
python -c "from server import ai_explainer; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add server/ai_explainer.py
git commit -m "feat: ai_explainer — async queue daemon for per-trade Ollama explanations"
```

---

## Task 3: `server/ai_tuner.py` — weekly parameter tuner

**Files:**
- Create: `server/ai_tuner.py`

- [ ] **Step 1: Create the file**

```python
"""Weekly strategy parameter tuner — uses Ollama to suggest param improvements."""
import json
import logging
import urllib.error
import urllib.request

from . import db, notifications, strategies

log = logging.getLogger("ai_tuner")

MIN_TRADES = 10


def _ollama_url() -> str:
    return db.get_app_config("ai_ollama_url", "http://localhost:11434")


def _ollama_model() -> str:
    return db.get_app_config("ai_ollama_model", "llama3")


def _tuner_enabled() -> bool:
    return db.get_app_config("ai_tuner_enabled", "true") == "true"


def _call_ollama(prompt: str) -> str | None:
    payload = json.dumps({
        "model": _ollama_model(),
        "prompt": prompt,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{_ollama_url()}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip()
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


def _build_prompt(strategy_label: str, current_params: dict,
                  bounds_summary: str, perf: dict) -> str:
    return (
        "You are a trading strategy optimizer. Suggest parameter adjustments "
        "as valid JSON only — no explanation outside the JSON block.\n\n"
        f"Strategy: {strategy_label}\n"
        f"Current params: {json.dumps(current_params)}\n"
        f"Param bounds: {bounds_summary}\n\n"
        "Performance last 90 days:\n"
        f"- Total trades: {perf['total_trades']}, "
        f"Win rate: {perf['win_rate']}%, "
        f"Avg P&L: ${perf['avg_pnl']}\n\n"
        "Suggest new params that may improve win rate.\n"
        'Reply with ONLY: {"params": {...}, "rationale": "..."}'
    )


def _bounds_summary(schema: list[dict]) -> str:
    parts = []
    for p in schema:
        if p.get("type") == "number":
            parts.append(f"{p['key']}: [{p.get('min', '?')}–{p.get('max', '?')}]")
    return ", ".join(parts) if parts else "no numeric params"


def _validate_params(proposed: dict, schema: list[dict]) -> dict | None:
    """Return validated params or None if any value is out of bounds."""
    validated = {}
    schema_map = {p["key"]: p for p in schema}
    for key, val in proposed.items():
        if key not in schema_map:
            continue
        p = schema_map[key]
        if p.get("type") == "number":
            try:
                val = float(val)
            except (TypeError, ValueError):
                log.warning("Tuner: non-numeric value for %s: %r", key, val)
                return None
            lo = p.get("min")
            hi = p.get("max")
            if (lo is not None and val < lo) or (hi is not None and val > hi):
                log.warning("Tuner: %s=%s out of bounds [%s, %s]", key, val, lo, hi)
                return None
        validated[key] = val
    return validated if validated else None


def run_tuning() -> dict:
    """
    Run one tuning cycle over all eligible strategies.
    Returns a summary dict: {tuned: int, skipped: int, error: str | None}
    """
    if not _tuner_enabled():
        log.info("AI tuner disabled — skipping")
        return {"tuned": 0, "skipped": 0, "error": None}

    all_strats = db.get_strategies()
    tuned_results = []
    skipped = 0

    for s in all_strats:
        if not s["enabled"]:
            skipped += 1
            continue
        if s["name"] not in strategies.REGISTRY:
            skipped += 1
            continue
        cls = strategies.REGISTRY[s["name"]]
        schema = cls.params_schema  # list of {key, label, type, min, max, default, hint}

        perf = db.get_strategy_perf_90d(s["name"])
        if perf["total_trades"] < MIN_TRADES:
            log.info("Tuner: %s has only %d trades — skipping", s["name"], perf["total_trades"])
            skipped += 1
            continue

        strat_label = s["name"].replace("_", " ").title()
        prompt = _build_prompt(strat_label, s["params"], _bounds_summary(schema), perf)
        raw = _call_ollama(prompt)
        if raw is None:
            log.warning("Tuner: Ollama unreachable — aborting tuning run")
            return {"tuned": 0, "skipped": skipped, "error": "Ollama unreachable"}

        # Extract JSON — Ollama sometimes wraps it in markdown fences
        try:
            # Strip ```json ... ``` if present
            text = raw.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            parsed = json.loads(text)
            proposed_params = parsed["params"]
            rationale = str(parsed.get("rationale", ""))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            log.warning("Tuner: malformed JSON from Ollama for %s: %s", s["name"], exc)
            skipped += 1
            continue

        validated = _validate_params(proposed_params, schema)
        if validated is None:
            log.warning("Tuner: out-of-bounds params for %s — skipping", s["name"])
            skipped += 1
            continue

        # Merge validated changes onto existing params (only keys in schema)
        new_params = dict(s["params"])
        new_params.update(validated)

        if new_params == s["params"]:
            log.info("Tuner: no change suggested for %s", s["name"])
            skipped += 1
            continue

        db.log_tuning_run(s["name"], s["params"], new_params, rationale, perf["win_rate"])
        db.upsert_strategy(s["name"], enabled=True, params=new_params)
        tuned_results.append({
            "strategy": strat_label,
            "old_params": s["params"],
            "new_params": new_params,
            "rationale": rationale,
            "win_rate_before": perf["win_rate"],
        })
        log.info("Tuner: updated params for %s", s["name"])

    if tuned_results:
        _notify_tuning(tuned_results)

    return {"tuned": len(tuned_results), "skipped": skipped, "error": None}


def _notify_tuning(results: list[dict]) -> None:
    lines = [f"🤖 AI Tuner adjusted {len(results)} strategy(s):\n"]
    for r in results:
        lines.append(f"• {r['strategy']} — win rate was {r['win_rate_before']}%")
        lines.append(f"  Reason: {r['rationale'][:120]}")
    text = "\n".join(lines)
    notifications._send_async(notifications._send_telegram, text)
    notifications._send_async(notifications._send_slack, text)
    notifications._send_async(notifications._send_discord, text)
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "from server import ai_tuner; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add server/ai_tuner.py
git commit -m "feat: ai_tuner — weekly Ollama-powered strategy parameter optimizer"
```

---

## Task 4: Engine wiring — enqueue on signal, weekly timer

**Files:**
- Modify: `server/engine.py`

- [ ] **Step 1: Import `ai_explainer` and `ai_tuner` at the top of `engine.py`**

The current import line (line 7) is:
```python
from . import alpaca_client, crypto, db, notifications, risk, strategies
```

Change it to:
```python
from . import ai_explainer, ai_tuner, alpaca_client, crypto, db, notifications, risk, strategies
```

- [ ] **Step 2: Call `ai_explainer.enqueue()` after `db.log_signal()` in the order-submit block**

In `run_tick()`, find the successful order submit block where `db.log_signal(...)` is called (around line 188). The block looks like:

```python
                    db.log_signal(s["name"], sig.symbol, sig.side, display_qty,
                                  sig.reason, order["id"], order["status"], account_id=acct_id)
                    notifications.notify_trade(...)
```

Add the enqueue call immediately after `db.log_signal(...)`:

```python
                    db.log_signal(s["name"], sig.symbol, sig.side, display_qty,
                                  sig.reason, order["id"], order["status"], account_id=acct_id)
                    # Enqueue for AI explanation (fire-and-forget, non-blocking)
                    try:
                        with db.get_conn() as _c:
                            _row = _c.execute(
                                "SELECT id FROM signals ORDER BY id DESC LIMIT 1"
                            ).fetchone()
                        if _row:
                            ai_explainer.enqueue({
                                "id": _row["id"],
                                "ts": db.now_iso(),
                                "strategy": s["name"],
                                "symbol": sig.symbol,
                                "side": sig.side,
                                "reason": sig.reason,
                            })
                    except Exception:
                        pass  # never let explainer failure affect order flow
                    notifications.notify_trade(...)
```

- [ ] **Step 3: Add the weekly tuner timer**

`db.log_signal` returns nothing currently. To get the newly-inserted signal ID without a second query, update `db.log_signal` to return the row id. In `server/db.py`, change:

```python
def log_signal(strategy: str, symbol: str, side: str, qty: float, reason: str,
               order_id: str | None = None, status: str = "ok",
               blocked: bool = False, account_id: int | None = None):
    with get_conn() as c:
        c.execute(
            """INSERT INTO signals(ts, strategy, symbol, side, qty, reason, order_id, status, blocked, account_id)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (now_iso(), strategy, symbol, side, qty, reason, order_id, status, int(blocked), account_id),
        )
```

to:

```python
def log_signal(strategy: str, symbol: str, side: str, qty: float, reason: str,
               order_id: str | None = None, status: str = "ok",
               blocked: bool = False, account_id: int | None = None) -> int:
    with get_conn() as c:
        cur = c.execute(
            """INSERT INTO signals(ts, strategy, symbol, side, qty, reason, order_id, status, blocked, account_id)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (now_iso(), strategy, symbol, side, qty, reason, order_id, status, int(blocked), account_id),
        )
        return cur.lastrowid
```

- [ ] **Step 4: Simplify the enqueue call in `engine.py` now that `log_signal` returns the id**

Replace the enqueue block added in Step 2 with the simpler version:

```python
                    sig_id = db.log_signal(s["name"], sig.symbol, sig.side, display_qty,
                                           sig.reason, order["id"], order["status"],
                                           account_id=acct_id)
                    try:
                        ai_explainer.enqueue({
                            "id": sig_id,
                            "ts": db.now_iso(),
                            "strategy": s["name"],
                            "symbol": sig.symbol,
                            "side": sig.side,
                            "reason": sig.reason,
                        })
                    except Exception:
                        pass
                    notifications.notify_trade(
                        s["name"], sig.symbol, sig.side,
                        final_qty, sig.notional, sig.reason, order["id"]
                    )
```

- [ ] **Step 5: Add weekly tuner timer to `start()` function**

First, add `threading` to the imports at the top of `engine.py` (line 2):

```python
import logging
import threading
import uuid
```

Find the `start()` function in `engine.py`. After `engine.start(interval_seconds=60)` is called from `lifespan` in `main.py`, we need the weekly timer to fire. Add a helper at module level in `engine.py` and call it from `start()`.

At the end of `engine.py` (after `last_run()`), add:

```python
def _schedule_weekly_tuner():
    """Fire ai_tuner.run_tuning() every Sunday at 11 PM ET, then reschedule."""
    import zoneinfo
    from datetime import datetime, timedelta, timezone
    now_et = datetime.now(timezone.utc).astimezone(zoneinfo.ZoneInfo("America/New_York"))
    # Find next Sunday 23:00 ET
    days_until_sunday = (6 - now_et.weekday()) % 7  # Monday=0, Sunday=6
    if days_until_sunday == 0 and now_et.hour >= 23:
        days_until_sunday = 7  # already past 11pm Sunday — wait for next week
    next_run = now_et.replace(hour=23, minute=0, second=0, microsecond=0) + timedelta(days=days_until_sunday)
    delay_s = (next_run - now_et).total_seconds()
    log.info("Weekly tuner scheduled in %.0f seconds (next Sunday 11pm ET)", delay_s)

    def _fire():
        try:
            result = ai_tuner.run_tuning()
            log.info("Weekly tuner complete: %s", result)
        except Exception:
            log.exception("Weekly tuner failed")
        _schedule_weekly_tuner()  # reschedule for next week

    threading.Timer(delay_s, _fire).start()
```

Then in the existing `start()` function, add a call to `_schedule_weekly_tuner()` after the scheduler starts:

```python
def start(interval_seconds: int = 60):
    global _scheduler
    ...
    _scheduler.start()
    ai_explainer.start()          # ← add this line
    _schedule_weekly_tuner()      # ← add this line
```

- [ ] **Step 6: Verify server starts without errors**

```bash
python -m uvicorn server.main:app --port 8000
```
Expected: server starts, log shows `"ai-explainer"` thread started and weekly tuner scheduled. Stop with Ctrl+C.

- [ ] **Step 7: Commit**

```bash
git add server/engine.py server/db.py
git commit -m "feat: wire ai_explainer and weekly ai_tuner into engine lifecycle"
```

---

## Task 5: API endpoints

**Files:**
- Modify: `server/main.py`

- [ ] **Step 1: Import the new modules at the top of `main.py`**

Change line 15:
```python
from . import alpaca_client, auth, backtest as bt_mod, crypto, db, engine, notifications, risk, scanner, strategies
```
to:
```python
from . import ai_explainer, ai_tuner, alpaca_client, auth, backtest as bt_mod, crypto, db, engine, notifications, risk, scanner, strategies
```

- [ ] **Step 2: Add a Pydantic model for AI settings PATCH**

After the other Pydantic models near the top of `main.py` (search for `class BacktestRequest`), add:

```python
class AiSettingsBody(BaseModel):
    ollama_url:              str | None = None
    ollama_model:            str | None = None
    explanations_enabled:    bool | None = None
    tuner_enabled:           bool | None = None
```

- [ ] **Step 3: Add the 6 AI endpoints**

After the existing `/api/engine/run_now` endpoint (around line 719 in the original), add:

```python
@app.get("/api/signals/{signal_id}/explanation")
def signal_explanation(signal_id: int, request: Request):
    _require_auth(request)
    text = db.get_signal_explanation(signal_id)
    return {"explanation": text, "ready": text is not None}


@app.get("/api/ai/status")
def ai_status(request: Request):
    _require_auth(request)
    return ai_explainer.ollama_status()


@app.patch("/api/ai/settings")
def ai_settings_patch(body: AiSettingsBody, request: Request):
    _require_auth(request)
    if body.ollama_url is not None:
        db.set_app_config("ai_ollama_url", body.ollama_url.strip())
    if body.ollama_model is not None:
        db.set_app_config("ai_ollama_model", body.ollama_model.strip())
    if body.explanations_enabled is not None:
        db.set_app_config("ai_explanations_enabled", "true" if body.explanations_enabled else "false")
    if body.tuner_enabled is not None:
        db.set_app_config("ai_tuner_enabled", "true" if body.tuner_enabled else "false")
    return {"ok": True}


@app.get("/api/ai/settings")
def ai_settings_get(request: Request):
    _require_auth(request)
    return {
        "ollama_url":           db.get_app_config("ai_ollama_url", "http://localhost:11434"),
        "ollama_model":         db.get_app_config("ai_ollama_model", "llama3"),
        "explanations_enabled": db.get_app_config("ai_explanations_enabled", "true") == "true",
        "tuner_enabled":        db.get_app_config("ai_tuner_enabled", "true") == "true",
    }


@app.get("/api/ai/tuning-log")
def ai_tuning_log(request: Request):
    _require_auth(request)
    return db.list_tuning_log()


@app.post("/api/ai/tune-now")
def ai_tune_now(request: Request):
    _require_auth(request)
    import threading
    result_holder = {}
    def _run():
        result_holder["result"] = ai_tuner.run_tuning()
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=120)
    return result_holder.get("result", {"tuned": 0, "skipped": 0, "error": "timeout"})


@app.post("/api/ai/tuning-log/{run_id}/revert")
def ai_tuning_revert(run_id: int, request: Request):
    _require_auth(request)
    ok = db.revert_tuning_run(run_id)
    if not ok:
        raise HTTPException(404, "Tuning run not found or strategy no longer exists")
    return {"ok": True}
```

- [ ] **Step 4: Verify endpoints are registered**

```bash
python -m uvicorn server.main:app --port 8000
```
In another terminal:
```bash
curl -s http://localhost:8000/api/ai/status
```
Expected: `{"reachable": false, "model": "llama3", "url": "http://localhost:11434"}` (reachable=false if Ollama not running, which is fine).

- [ ] **Step 5: Commit**

```bash
git add server/main.py
git commit -m "feat: API endpoints for AI explanation polling, status, settings, tuning log"
```

---

## Task 6: Logs page UI — explain button

**Files:**
- Modify: `server/static/logs.html`
- Modify: `server/static/app.js`

- [ ] **Step 1: Add explain column to logs table header**

In `server/static/logs.html`, change line 138-140:

```html
          <colgroup><col style="width:90px"><col style="width:90px"><col style="width:70px"><col style="width:50px"><col style="width:60px"><col><col style="width:70px"></colgroup>
          <thead><tr><th>Time</th><th>Strategy</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Reason</th><th>Status</th></tr></thead>
          <tbody id="logs-body"><tr><td colspan="7" class="state-empty">Loading&hellip;</td></tr></tbody>
```

to:

```html
          <colgroup><col style="width:90px"><col style="width:90px"><col style="width:70px"><col style="width:50px"><col style="width:60px"><col><col style="width:70px"><col style="width:32px"></colgroup>
          <thead><tr><th>Time</th><th>Strategy</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Reason</th><th>Status</th><th></th></tr></thead>
          <tbody id="logs-body"><tr><td colspan="8" class="state-empty">Loading&hellip;</td></tr></tbody>
```

- [ ] **Step 2: Update `initLogs()` in `app.js` to render the explain button and inline panel**

Replace the `fetchSignals` inner function in `initLogs()` (lines 2634–2670) with:

```javascript
  async function fetchSignals() {
    const tbody = document.getElementById('logs-body');
    try {
      const sigs = await api('/api/signals?limit=200', { key: 'logs-signals' });
      const filtered = currentFilter === 'all' ? sigs : sigs.filter(s => s.status === currentFilter);
      tbody.innerHTML = '';
      if (!filtered.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="state-empty">No signals.</td></tr>';
        return;
      }
      const statusCls = { filled: 'b-enabled', blocked: 'b-notrun', error: 'b-error', pending: 'b-disabled' };
      filtered.slice(0, 100).forEach(s => {
        const tr = document.createElement('tr');
        tr.dataset.sigId = s.id;
        const fields = [fmt.time(s.ts), s.strategy, s.symbol, '', (s.qty||0).toFixed(2), s.reason, '', ''];
        fields.forEach((v, i) => {
          const td = document.createElement('td');
          if (i === 3) {
            const tag = document.createElement('span');
            tag.className = 'badge ' + (s.side === 'buy' ? 'b-buy' : 'b-sell');
            tag.textContent = s.side === 'buy' ? 'Buy' : 'Sell';
            td.appendChild(tag);
          } else if (i === 6) {
            const badge = document.createElement('span');
            badge.className = 'badge ' + (statusCls[s.status] || 'b-disabled');
            badge.textContent = s.status;
            td.appendChild(badge);
          } else if (i === 7) {
            // Only show explain button for non-blocked, non-error signals with a real symbol
            if (s.status !== 'blocked' && s.status !== 'error' && s.symbol && s.symbol !== '-') {
              const btn = document.createElement('button');
              btn.className = 'btn btn-sm btn-ghost';
              btn.style.cssText = 'padding:2px 6px;font-size:11px;line-height:1.4;';
              btn.title = 'AI Explanation';
              btn.textContent = 'ℹ';
              btn.onclick = () => toggleExplanation(s.id, tr);
              td.appendChild(btn);
            }
          } else { td.textContent = v; }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    } catch (e) {
      if (e.name === 'AbortError') return;
      tbody.innerHTML = '<tr><td colspan="8" class="state-error">Failed to load — retrying in 30s</td></tr>';
      throw e;
    }
  }
```

- [ ] **Step 3: Add `toggleExplanation()` function before `initLogs()`**

Insert this function just before `// initLogs — logs.html` (line 2628):

```javascript
// ── AI explanation inline panel ────────────────────────────────────────────
const _explainPollers = {};

async function toggleExplanation(sigId, tr) {
  const existing = tr.nextSibling;
  if (existing && existing.dataset.explainRow === String(sigId)) {
    existing.remove();
    if (_explainPollers[sigId]) { clearInterval(_explainPollers[sigId]); delete _explainPollers[sigId]; }
    return;
  }
  const expRow = document.createElement('tr');
  expRow.dataset.explainRow = sigId;
  const td = document.createElement('td');
  td.colSpan = 8;
  td.style.cssText = 'padding:.6rem 1rem;background:var(--bg2);border-top:none;';
  td.innerHTML = '<span class="badge b-notrun" style="font-size:11px;">Generating…</span>';
  expRow.appendChild(td);
  tr.after(expRow);

  async function checkExplanation() {
    try {
      const d = await api(`/api/signals/${sigId}/explanation`);
      if (d.ready && d.explanation) {
        clearInterval(_explainPollers[sigId]);
        delete _explainPollers[sigId];
        td.innerHTML = `<span style="font-size:12px;color:var(--text);line-height:1.5;">${escHtml(d.explanation)}</span>`;
      }
    } catch (_) {}
  }

  await checkExplanation();
  if (!d || !d.ready) {
    _explainPollers[sigId] = setInterval(checkExplanation, 2000);
  }
}
```

> **Note:** The `if (!d || !d.ready)` check above references `d` which is out of scope. Replace the last 3 lines of `toggleExplanation` with:

```javascript
  const first = await api(`/api/signals/${sigId}/explanation`).catch(() => null);
  if (first && first.ready && first.explanation) {
    td.innerHTML = `<span style="font-size:12px;color:var(--text);line-height:1.5;">${escHtml(first.explanation)}</span>`;
  } else {
    _explainPollers[sigId] = setInterval(checkExplanation, 2000);
  }
}
```

Replace the full `toggleExplanation` function with the corrected version:

```javascript
// ── AI explanation inline panel ────────────────────────────────────────────
const _explainPollers = {};

async function toggleExplanation(sigId, tr) {
  const existing = tr.nextSibling;
  if (existing && existing.dataset.explainRow === String(sigId)) {
    existing.remove();
    if (_explainPollers[sigId]) { clearInterval(_explainPollers[sigId]); delete _explainPollers[sigId]; }
    return;
  }
  const expRow = document.createElement('tr');
  expRow.dataset.explainRow = sigId;
  const td = document.createElement('td');
  td.colSpan = 8;
  td.style.cssText = 'padding:.6rem 1rem;background:var(--bg2);border-top:none;';
  td.innerHTML = '<span class="badge b-notrun" style="font-size:11px;">Generating…</span>';
  expRow.appendChild(td);
  tr.after(expRow);

  async function checkExplanation() {
    try {
      const d = await api(`/api/signals/${sigId}/explanation`);
      if (d.ready && d.explanation) {
        clearInterval(_explainPollers[sigId]);
        delete _explainPollers[sigId];
        td.innerHTML = `<span style="font-size:12px;color:var(--text);line-height:1.5;">${escHtml(d.explanation)}</span>`;
      }
    } catch (_) {}
  }

  const first = await api(`/api/signals/${sigId}/explanation`).catch(() => null);
  if (first && first.ready && first.explanation) {
    td.innerHTML = `<span style="font-size:12px;color:var(--text);line-height:1.5;">${escHtml(first.explanation)}</span>`;
  } else {
    _explainPollers[sigId] = setInterval(checkExplanation, 2000);
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add server/static/logs.html server/static/app.js
git commit -m "feat: logs page — AI explanation button with inline panel and polling"
```

---

## Task 7: AI Tuning page

**Files:**
- Create: `server/static/ai-tuning.html`
- Modify: `server/static/index.html`
- Modify: `server/static/app.js`

- [ ] **Step 1: Create `ai-tuning.html`**

Copy the structure of an existing page like `risk.html` as a template. The full file:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AI Tuning — TradeBot</title>
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body data-page="ai-tuning">

<div class="app-shell">

  <!-- Sidebar (copy from index.html lines 16–100 verbatim) -->
  <!-- IMPORTANT: copy the full sidebar block from server/static/index.html -->

  <main class="main-content">
    <div class="topbar">
      <div style="display:flex;align-items:center;gap:.75rem;">
        <div id="market-chip" class="market-chip"></div>
      </div>
      <div class="topbar-right">
        <span id="user-label" style="font-size:12px;color:var(--muted);"></span>
        <button class="btn btn-sm btn-ghost" id="logout-btn">Logout</button>
      </div>
    </div>

    <div class="page-header">
      <h1 class="page-title">AI Parameter Tuning</h1>
      <p class="page-subtitle">Weekly automated strategy optimization powered by local AI</p>
    </div>

    <!-- Status card -->
    <div class="card" style="margin-bottom:1rem;">
      <div class="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div style="font-size:14px;font-weight:600;margin-bottom:.25rem;">Ollama Status</div>
          <div style="display:flex;align-items:center;gap:.5rem;">
            <span id="ai-status-dot" style="width:8px;height:8px;border-radius:50%;background:#64748B;display:inline-block;"></span>
            <span id="ai-status-label" style="font-size:12px;color:var(--muted);">Checking…</span>
          </div>
        </div>
        <div style="display:flex;gap:.5rem;align-items:center;">
          <span id="tune-msg" style="font-size:12px;color:var(--muted);"></span>
          <button id="tune-now-btn" class="btn btn-sm btn-primary">Run Tuning Now</button>
        </div>
      </div>
    </div>

    <!-- Tuning log -->
    <div class="card">
      <div style="font-size:14px;font-weight:600;margin-bottom:.75rem;">Tuning History</div>
      <div class="dtable-wrap">
        <table class="dtable">
          <thead>
            <tr>
              <th>Date</th>
              <th>Strategy</th>
              <th>Win Rate Before</th>
              <th>Changes Made</th>
              <th>Rationale</th>
              <th></th>
            </tr>
          </thead>
          <tbody id="tuning-log-body">
            <tr><td colspan="6" class="state-empty">No tuning runs yet. The AI will analyze your strategies every Sunday at 11 PM.</td></tr>
          </tbody>
        </table>
      </div>
    </div>

  </main>

</div>

<script src="/static/app.js"></script>
</body>
</html>
```

> **Important:** After creating the file, copy the full sidebar block from `server/static/index.html` (lines 16–100) and paste it in place of the `<!-- Sidebar -->` comment. The sidebar is identical across all pages.

- [ ] **Step 2: Add nav link in `index.html` sidebar**

In `server/static/index.html`, after the Risk nav link (line 62, the Logs link), add the AI Tuning link between Risk and Logs:

```html
    <a href="/static/ai-tuning.html" class="nav-item" data-page="ai-tuning">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3M4.22 19.78l2.12-2.12M17.66 6.34l2.12-2.12"/></svg>
      AI Tuning
    </a>
```

Place it between the Risk and Logs nav items.

Also add this same nav link to the sidebar in `ai-tuning.html` (so the active state highlights correctly when on the AI Tuning page).

- [ ] **Step 3: Add `initAiTuning()` to `app.js`**

After the `initLogs()` function and before the next section, add:

```javascript
// initAiTuning — ai-tuning.html
// ─────────────────────────────────────────
async function initAiTuning() {
  initClockChip(document.getElementById('market-chip'));

  async function loadStatus() {
    try {
      const s = await api('/api/ai/status');
      const dot   = document.getElementById('ai-status-dot');
      const label = document.getElementById('ai-status-label');
      if (dot)   dot.style.background   = s.reachable ? '#10B981' : '#EF4444';
      if (label) label.textContent = s.reachable
        ? `Connected — model: ${s.model}`
        : `Offline (${s.url})`;
    } catch (_) {}
  }

  async function loadLog() {
    const tbody = document.getElementById('tuning-log-body');
    if (!tbody) return;
    try {
      const rows = await api('/api/ai/tuning-log');
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="state-empty">No tuning runs yet. The AI will analyze your strategies every Sunday at 11 PM.</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map(r => {
        const changes = Object.entries(r.new_params)
          .filter(([k, v]) => r.old_params[k] !== v)
          .map(([k, v]) => `${k}: ${r.old_params[k]} → ${v}`)
          .join(', ') || 'No changes';
        return `<tr>
          <td style="white-space:nowrap;">${fmt.time(r.created_at)}</td>
          <td>${escHtml(r.strategy.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase()))}</td>
          <td>${r.win_rate_before !== null ? r.win_rate_before + '%' : '—'}</td>
          <td style="font-size:11px;font-family:monospace;">${escHtml(changes)}</td>
          <td style="font-size:11px;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escHtml(r.rationale)}">${escHtml(r.rationale)}</td>
          <td><button class="btn btn-sm" style="font-size:11px;background:rgba(239,68,68,.1);color:#EF4444;border-color:rgba(239,68,68,.3);" onclick="revertTuning(${r.id})">Revert</button></td>
        </tr>`;
      }).join('');
    } catch (_) {
      tbody.innerHTML = '<tr><td colspan="6" class="state-error">Failed to load tuning log.</td></tr>';
    }
  }

  document.getElementById('tune-now-btn')?.addEventListener('click', async () => {
    const btn = document.getElementById('tune-now-btn');
    const msg = document.getElementById('tune-msg');
    btn.disabled = true;
    btn.textContent = 'Running…';
    if (msg) msg.textContent = '';
    try {
      const result = await api('/api/ai/tune-now', { method: 'POST' });
      if (msg) msg.textContent = result.error
        ? `Error: ${result.error}`
        : `Done — ${result.tuned} updated, ${result.skipped} skipped`;
      await loadLog();
    } catch (e) {
      if (msg) msg.textContent = `Error: ${e.message}`;
    } finally {
      btn.disabled = false;
      btn.textContent = 'Run Tuning Now';
    }
  });

  await Promise.all([loadStatus(), loadLog()]);
}

window.revertTuning = async function(runId) {
  if (!confirm('Revert this tuning change? The strategy params will be restored to their previous values.')) return;
  try {
    await api(`/api/ai/tuning-log/${runId}/revert`, { method: 'POST' });
    const tbody = document.getElementById('tuning-log-body');
    // Re-load the log
    const rows = await api('/api/ai/tuning-log');
    if (tbody) {
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="state-empty">No tuning runs yet.</td></tr>';
      } else {
        // trigger re-render by calling initAiTuning's loadLog — simplest: reload
        location.reload();
      }
    }
  } catch (e) {
    alert(`Revert failed: ${e.message}`);
  }
};
```

- [ ] **Step 4: Register `initAiTuning` in the page router**

In `app.js`, find the `PAGE_INITS` object (around line 320–340, where `logs: initLogs` is defined). Add:

```javascript
    'ai-tuning': initAiTuning,
```

- [ ] **Step 5: Commit**

```bash
git add server/static/ai-tuning.html server/static/index.html server/static/app.js
git commit -m "feat: AI Tuning page — tuning log table with Revert buttons and Run Now"
```

---

## Task 8: Settings page — AI Assistant section

**Files:**
- Modify: `server/static/settings.html`
- Modify: `server/static/app.js`

- [ ] **Step 1: Add AI Assistant card to `settings.html`**

In `server/static/settings.html`, find the License card (`<!-- License card -->`, around line 305). Insert the AI card before it:

```html
    <!-- AI Assistant card -->
    <div class="card" id="ai-card" style="margin-top:1rem;">
      <div class="flex items-center justify-between mb-3">
        <div style="font-size:14px;font-weight:600;">AI Assistant</div>
        <div style="display:flex;align-items:center;gap:.5rem;">
          <span id="ai-dot" style="width:8px;height:8px;border-radius:50%;background:#64748B;display:inline-block;"></span>
          <span id="ai-dot-label" style="font-size:11px;color:var(--muted);">Checking…</span>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label class="field-label" for="ai-ollama-url">Ollama URL</label>
          <input id="ai-ollama-url" class="input-field" placeholder="http://localhost:11434">
        </div>
        <div>
          <label class="field-label" for="ai-ollama-model">Model</label>
          <input id="ai-ollama-model" class="input-field" placeholder="llama3">
        </div>
      </div>
      <div class="flex gap-4 mb-3" style="flex-wrap:wrap;">
        <label style="display:flex;align-items:center;gap:.5rem;cursor:pointer;font-size:13px;">
          <input type="checkbox" id="ai-explanations-enabled" style="width:15px;height:15px;accent-color:#3B82F6;">
          Enable trade explanations
        </label>
        <label style="display:flex;align-items:center;gap:.5rem;cursor:pointer;font-size:13px;">
          <input type="checkbox" id="ai-tuner-enabled" style="width:15px;height:15px;accent-color:#3B82F6;">
          Enable weekly parameter tuning
        </label>
      </div>
      <div class="flex gap-2 items-center flex-wrap">
        <button id="ai-save-btn" class="btn btn-sm btn-primary">Save AI Settings</button>
        <button id="ai-tune-now-btn" class="btn btn-sm">Run Tuning Now</button>
        <span id="ai-save-msg" class="field-msg hidden"></span>
      </div>
    </div>
```

- [ ] **Step 2: Add AI settings load/save to `initSettings()` in `app.js`**

Find `initSettings()` (search for `async function initSettings`). At the end of the function, before the final closing `}`, add:

```javascript
  // ── AI settings ───────────────────────────────────────────────────────────
  async function loadAiSettings() {
    try {
      const [s, status] = await Promise.all([
        api('/api/ai/settings'),
        api('/api/ai/status'),
      ]);
      const urlEl   = document.getElementById('ai-ollama-url');
      const modelEl = document.getElementById('ai-ollama-model');
      const expEl   = document.getElementById('ai-explanations-enabled');
      const tunEl   = document.getElementById('ai-tuner-enabled');
      const dot     = document.getElementById('ai-dot');
      const dotLbl  = document.getElementById('ai-dot-label');
      if (urlEl)   urlEl.value   = s.ollama_url;
      if (modelEl) modelEl.value = s.ollama_model;
      if (expEl)   expEl.checked = s.explanations_enabled;
      if (tunEl)   tunEl.checked = s.tuner_enabled;
      if (dot)     dot.style.background = status.reachable ? '#10B981' : '#EF4444';
      if (dotLbl)  dotLbl.textContent   = status.reachable ? 'Connected' : 'Offline';
    } catch (_) {}
  }

  document.getElementById('ai-save-btn')?.addEventListener('click', async () => {
    const msg = document.getElementById('ai-save-msg');
    try {
      await api('/api/ai/settings', {
        method: 'PATCH',
        body: JSON.stringify({
          ollama_url:           document.getElementById('ai-ollama-url')?.value?.trim(),
          ollama_model:         document.getElementById('ai-ollama-model')?.value?.trim(),
          explanations_enabled: document.getElementById('ai-explanations-enabled')?.checked,
          tuner_enabled:        document.getElementById('ai-tuner-enabled')?.checked,
        }),
      });
      if (msg) { msg.textContent = 'Saved'; msg.classList.remove('hidden'); setTimeout(() => msg.classList.add('hidden'), 2500); }
    } catch (e) {
      if (msg) { msg.textContent = e.message; msg.classList.remove('hidden'); }
    }
  });

  document.getElementById('ai-tune-now-btn')?.addEventListener('click', async () => {
    const btn = document.getElementById('ai-tune-now-btn');
    const msg = document.getElementById('ai-save-msg');
    btn.disabled = true; btn.textContent = 'Running…';
    try {
      const result = await api('/api/ai/tune-now', { method: 'POST' });
      if (msg) {
        msg.textContent = result.error ? `Error: ${result.error}` : `Done — ${result.tuned} updated`;
        msg.classList.remove('hidden');
        setTimeout(() => msg.classList.add('hidden'), 4000);
      }
    } catch (e) {
      if (msg) { msg.textContent = e.message; msg.classList.remove('hidden'); }
    } finally {
      btn.disabled = false; btn.textContent = 'Run Tuning Now';
    }
  });

  loadAiSettings();
```

- [ ] **Step 3: Commit**

```bash
git add server/static/settings.html server/static/app.js
git commit -m "feat: settings page AI Assistant section — Ollama config, toggles, Run Tuning Now"
```

---

## Task 9: Copy sidebar into `ai-tuning.html` and update all sidebars

**Files:**
- Modify: `server/static/ai-tuning.html`
- (Review) all other `.html` pages

The sidebar is duplicated across all HTML files. Each page's sidebar must include the new AI Tuning nav link.

- [ ] **Step 1: Copy the full sidebar from `index.html` into `ai-tuning.html`**

Read `server/static/index.html` lines 16–100. The sidebar block starts with `<aside class="sidebar">` and ends with `</aside>`. Replace the `<!-- Sidebar -->` placeholder comment in `ai-tuning.html` with this full block (which now includes the AI Tuning nav link added in Task 7 Step 2).

- [ ] **Step 2: Add the AI Tuning nav link to every other page's sidebar**

Every `.html` file in `server/static/` (except `login.html`, `license.html`, `setup.html`, `mockup-*.html`) has a sidebar. In each one, find the Risk nav link block and add the AI Tuning link after it:

```html
    <a href="/static/ai-tuning.html" class="nav-item" data-page="ai-tuning">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3M4.22 19.78l2.12-2.12M17.66 6.34l2.12-2.12"/></svg>
      AI Tuning
    </a>
```

Pages to update (add the nav link to each):
- `server/static/backtesting.html`
- `server/static/balances.html`
- `server/static/bots.html`
- `server/static/logs.html`
- `server/static/performance.html`
- `server/static/positions.html`
- `server/static/risk.html`
- `server/static/settings.html`
- `server/static/apikeys.html`
- `server/static/help.html`

In each file, search for the string `data-page="risk"` to find the Risk nav link, then add the AI Tuning link immediately after the closing `</a>` of the Risk link.

- [ ] **Step 3: Commit**

```bash
git add server/static/
git commit -m "feat: add AI Tuning nav link to all page sidebars"
```

---

## Task 10: Final smoke test

- [ ] **Step 1: Start the server**

```bash
cd c:\TradeBot
python -m uvicorn server.main:app --port 8000
```

Check for no startup errors.

- [ ] **Step 2: Verify DB migrations**

```bash
python -c "
import sqlite3, os
db = sqlite3.connect('trading.db')
cols = [r[1] for r in db.execute('PRAGMA table_info(signals)')]
print('ai_explanation in signals:', 'ai_explanation' in cols)
tables = [r[0] for r in db.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")]
print('ai_tuning_log exists:', 'ai_tuning_log' in tables)
"
```
Expected:
```
ai_explanation in signals: True
ai_tuning_log exists: True
```

- [ ] **Step 3: Test AI status endpoint**

```bash
curl -s -b "tb_session=<your_session_cookie>" http://localhost:8000/api/ai/status
```
Expected: `{"reachable": false, "model": "llama3", "url": "http://localhost:11434"}`

- [ ] **Step 4: Test AI settings round-trip**

```bash
curl -s -X PATCH http://localhost:8000/api/ai/settings \
  -H "Content-Type: application/json" \
  -b "tb_session=<cookie>" \
  -d '{"ollama_model": "llama3:8b", "explanations_enabled": true}'
curl -s -b "tb_session=<cookie>" http://localhost:8000/api/ai/settings
```
Expected: second call returns `"ollama_model": "llama3:8b"`.

- [ ] **Step 5: Test tuning log (empty state)**

```bash
curl -s -b "tb_session=<cookie>" http://localhost:8000/api/ai/tuning-log
```
Expected: `[]`

- [ ] **Step 6: Navigate to `/static/ai-tuning.html` in the browser**

Verify:
- Sidebar shows "AI Tuning" link, highlighted as active
- Ollama Status shows red dot + "Offline" (Ollama not running)
- Tuning history shows empty state message
- "Run Tuning Now" button is visible

- [ ] **Step 7: Navigate to `/static/logs.html`**

Verify:
- Table has 8 columns (new empty column header at right)
- For filled signals, an ℹ button appears in the last column
- Clicking ℹ shows the "Generating…" pill

- [ ] **Step 8: Navigate to `/static/settings.html`**

Verify:
- "AI Assistant" section appears before License section
- Ollama URL field shows `http://localhost:11434`
- Both toggles are checked by default
- Saving shows "Saved" message

- [ ] **Step 9: Final commit**

```bash
git add -A
git commit -m "feat: complete AI trade explanation and weekly tuning feature"
```
