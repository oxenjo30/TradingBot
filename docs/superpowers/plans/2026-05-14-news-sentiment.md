# News Sentiment Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch Google News RSS headlines per ticker, score them with Claude Haiku, and use that score to gate or boost trade signals — with a live sentiment heatmap card on the dashboard.

**Architecture:** A new `server/sentiment.py` module handles fetch → score → cache. The engine calls `sentiment.get_sentiment(symbol)` after risk checks; scores below −0.3 block the trade, scores above +0.3 boost notional by 1.25×. The dashboard shows a refreshing heatmap card. Settings live on the Risk page.

**Tech Stack:** Python `urllib` + `xml.etree.ElementTree` (stdlib only), Claude Haiku API (same pattern as `ai_explainer.py`), FastAPI, vanilla JS, SQLite via `server/db.py`.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `server/sentiment.py` | **Create** | Fetch, score, cache — all sentiment logic |
| `server/db.py` | **Modify** | Add `sentiment_score` column to `signals`, extend `log_signal()` |
| `server/main.py` | **Modify** | Add `GET /api/sentiment`, extend settings endpoints |
| `server/engine.py` | **Modify** | Gate/boost signals using sentiment score |
| `server/static/index.html` | **Modify** | Add Market Sentiment card HTML |
| `server/static/app.js` | **Modify** | Add `loadSentiment()` function |
| `server/static/risk.html` | **Modify** | Add News Sentiment settings section |
| `tests/test_sentiment.py` | **Create** | Unit tests for sentiment module |

---

## Task 1: Create `server/sentiment.py` — fetch and score

**Files:**
- Create: `server/sentiment.py`
- Test: `tests/test_sentiment.py`

- [ ] **Step 1: Write failing tests for `fetch_headlines`**

Create `tests/test_sentiment.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
import xml.etree.ElementTree as ET


def _mock_rss(titles: list[str]) -> bytes:
    items = "".join(f"<item><title>{t}</title></item>" for t in titles)
    return f"""<?xml version="1.0"?><rss><channel>{items}</channel></rss>""".encode()


def test_fetch_headlines_stock_query(monkeypatch):
    """fetch_headlines builds correct URL for stock symbols."""
    calls = []
    def fake_urlopen(req, timeout=10):
        calls.append(req.full_url)
        resp = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.read.return_value = _mock_rss(["AAPL beats earnings"])
        return resp
    monkeypatch.setattr("server.sentiment.urllib.request.urlopen", fake_urlopen)
    from server.sentiment import fetch_headlines
    result = fetch_headlines("AAPL")
    assert len(calls) == 1
    assert "AAPL" in calls[0]
    assert "stock" in calls[0]
    assert result == ["AAPL beats earnings"]


def test_fetch_headlines_crypto_query(monkeypatch):
    """fetch_headlines strips /USDT and uses 'crypto' for crypto pairs."""
    calls = []
    def fake_urlopen(req, timeout=10):
        calls.append(req.full_url)
        resp = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.read.return_value = _mock_rss(["BTC rallies"])
        return resp
    monkeypatch.setattr("server.sentiment.urllib.request.urlopen", fake_urlopen)
    from server.sentiment import fetch_headlines
    result = fetch_headlines("BTC/USDT")
    assert "BTC" in calls[0]
    assert "crypto" in calls[0]
    assert "USDT" not in calls[0]
    assert result == ["BTC rallies"]


def test_fetch_headlines_returns_max_5(monkeypatch):
    """fetch_headlines returns at most 5 headlines."""
    def fake_urlopen(req, timeout=10):
        resp = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.read.return_value = _mock_rss([f"Headline {i}" for i in range(10)])
        return resp
    monkeypatch.setattr("server.sentiment.urllib.request.urlopen", fake_urlopen)
    from server.sentiment import fetch_headlines
    result = fetch_headlines("AAPL")
    assert len(result) == 5


def test_fetch_headlines_returns_empty_on_error(monkeypatch):
    """fetch_headlines returns [] when network fails."""
    import urllib.error
    def fake_urlopen(req, timeout=10):
        raise urllib.error.URLError("timeout")
    monkeypatch.setattr("server.sentiment.urllib.request.urlopen", fake_urlopen)
    from server.sentiment import fetch_headlines
    result = fetch_headlines("AAPL")
    assert result == []


def test_score_headlines_returns_neutral_on_empty():
    """score_headlines returns neutral score when no headlines provided."""
    from server.sentiment import score_headlines
    result = score_headlines("AAPL", [])
    assert result["score"] == 0.0
    assert result["reason"] == "no data"


def test_score_headlines_clamps_score(monkeypatch):
    """score_headlines clamps score to [-1.0, 1.0]."""
    def fake_call_claude(prompt):
        return '{"score": 5.0, "reason": "extreme"}'
    monkeypatch.setattr("server.sentiment._call_claude", fake_call_claude)
    from server import sentiment
    result = sentiment.score_headlines("AAPL", ["great news"])
    assert result["score"] == 1.0


def test_get_sentiment_caches_result(monkeypatch):
    """get_sentiment returns cached result within TTL."""
    fetch_count = [0]
    def fake_fetch(symbol):
        fetch_count[0] += 1
        return ["good news"]
    def fake_score(symbol, headlines):
        return {"score": 0.5, "reason": "positive"}
    monkeypatch.setattr("server.sentiment.fetch_headlines", fake_fetch)
    monkeypatch.setattr("server.sentiment.score_headlines", fake_score)
    monkeypatch.setattr("server.sentiment.db.get_app_config", lambda k, d="": "sk-ant-test")
    from server import sentiment
    sentiment._cache.clear()
    r1 = sentiment.get_sentiment("AAPL")
    r2 = sentiment.get_sentiment("AAPL")
    assert fetch_count[0] == 1
    assert r1["score"] == r2["score"]
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd C:\TradeBot
python -m pytest tests/test_sentiment.py -v 2>&1 | head -40
```

Expected: `ModuleNotFoundError: No module named 'server.sentiment'`

- [ ] **Step 3: Create `server/sentiment.py`**

```python
"""News sentiment — fetches Google News RSS, scores with Claude Haiku, caches 15 min."""
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from . import db

log = logging.getLogger("sentiment")

_cache: dict[str, dict] = {}   # {symbol: {score, reason, fetched_at, cached_at}}
_lock  = threading.Lock()
_TTL   = 900  # 15 minutes


def _claude_api_key() -> str:
    return db.get_app_config("ai_claude_api_key", "")


def _claude_model() -> str:
    return db.get_app_config("ai_claude_model", "claude-haiku-4-5-20251001")


def is_enabled() -> bool:
    return db.get_app_config("sentiment_enabled", "false") == "true"


def fetch_headlines(symbol: str) -> list[str]:
    """Fetch up to 5 headlines from Google News RSS for symbol."""
    if "/" in symbol:
        base = symbol.split("/")[0]
        query = f"{base} crypto"
    else:
        query = f"{symbol} stock"
    url = (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    )
    req = urllib.request.Request(url, headers={"User-Agent": "TradeBot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
        titles = [item.findtext("title") or "" for item in root.iter("item")]
        return [t for t in titles if t][:5]
    except Exception as e:
        log.debug("sentiment fetch failed for %s: %s", symbol, e)
        return []


def _call_claude(prompt: str) -> str | None:
    api_key = _claude_api_key()
    if not api_key:
        return None
    payload = json.dumps({
        "model": _claude_model(),
        "max_tokens": 128,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data["content"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        log.warning("sentiment: Claude HTTP %d — %s", e.code, e.read().decode(errors="replace")[:200])
        return None
    except Exception as e:
        log.debug("sentiment: Claude call failed: %s", e)
        return None


def score_headlines(symbol: str, headlines: list[str]) -> dict:
    """Score headlines using Claude. Returns {score: float, reason: str}."""
    if not headlines:
        return {"score": 0.0, "reason": "no data"}
    prompt = (
        "You are a financial news sentiment analyzer.\n"
        f"Symbol: {symbol}\n"
        f"Headlines:\n" + "\n".join(f"- {h}" for h in headlines) + "\n\n"
        "Score the overall sentiment from -1.0 (very negative) to +1.0 (very positive).\n"
        "Reply with ONLY valid JSON: {\"score\": <float>, \"reason\": \"<one sentence>\"}"
    )
    raw = _call_claude(prompt)
    if not raw:
        return {"score": 0.0, "reason": "no data"}
    try:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        parsed = json.loads(text)
        score  = float(parsed["score"])
        score  = max(-1.0, min(1.0, score))  # clamp
        reason = str(parsed.get("reason", ""))
        return {"score": score, "reason": reason}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        log.debug("sentiment: bad JSON from Claude for %s: %s", symbol, e)
        return {"score": 0.0, "reason": "no data"}


def get_sentiment(symbol: str) -> dict:
    """Return {score, reason, fetched_at} for symbol. Cached 15 min. Fail-open (0.0 on error)."""
    with _lock:
        cached = _cache.get(symbol)
        if cached and (time.monotonic() - cached["cached_at"]) < _TTL:
            return cached

    headlines = fetch_headlines(symbol)
    result    = score_headlines(symbol, headlines)
    entry = {
        "symbol":     symbol,
        "score":      result["score"],
        "reason":     result["reason"],
        "fetched_at": db.now_iso(),
        "cached_at":  time.monotonic(),
    }
    with _lock:
        _cache[symbol] = entry
    return entry


def get_all_cached() -> list[dict]:
    """Return all cached sentiment entries (excluding internal cached_at field)."""
    with _lock:
        return [
            {k: v for k, v in entry.items() if k != "cached_at"}
            for entry in _cache.values()
        ]
```

- [ ] **Step 4: Run tests — verify they pass**

```
python -m pytest tests/test_sentiment.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```
git add server/sentiment.py tests/test_sentiment.py
git commit -m "feat: add sentiment module with fetch, score, cache"
```

---

## Task 2: DB migration — add `sentiment_score` to `signals`

**Files:**
- Modify: `server/db.py` (two locations)

- [ ] **Step 1: Write failing test**

Add to `tests/test_sentiment.py`:

```python
def test_log_signal_accepts_sentiment_score():
    """log_signal stores sentiment_score without error."""
    import tempfile, os
    from unittest.mock import patch
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp = f.name
    try:
        with patch("server.db.DB_PATH", tmp):
            from server import db as _db
            _db.init_db()
            sig_id = _db.log_signal(
                "test_strat", "AAPL", "buy", 10.0, "test reason",
                sentiment_score=0.72
            )
            conn = _db.get_conn()
            row = conn.execute("SELECT sentiment_score FROM signals WHERE id=?", (sig_id,)).fetchone()
            assert row[0] == pytest.approx(0.72)
    finally:
        os.unlink(tmp)
```

Run: `python -m pytest tests/test_sentiment.py::test_log_signal_accepts_sentiment_score -v`
Expected: FAIL — `log_signal() got an unexpected keyword argument 'sentiment_score'`

- [ ] **Step 2: Add migration to `init_db()` in `server/db.py`**

Find the block of `ALTER TABLE signals ADD COLUMN` migrations (around line 300–315) and add after the existing `ai_model` migration:

```python
        if "sentiment_score" not in cols:
            c.execute("ALTER TABLE signals ADD COLUMN sentiment_score REAL DEFAULT NULL")
```

- [ ] **Step 3: Extend `log_signal()` signature in `server/db.py`**

Change the function signature and INSERT at line ~541:

```python
def log_signal(strategy: str, symbol: str, side: str, qty: float, reason: str,
               order_id: str | None = None, status: str = "ok",
               blocked: bool = False, account_id: int | None = None,
               filled_qty: float | None = None, filled_price: float | None = None,
               sentiment_score: float | None = None) -> int:
    with get_conn() as c:
        cur = c.execute(
            """INSERT INTO signals(ts, strategy, symbol, side, qty, reason, order_id, status,
                                   blocked, account_id, filled_qty, filled_price, sentiment_score)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (now_iso(), strategy, symbol, side, qty, reason, order_id, status,
             int(blocked), account_id, filled_qty, filled_price, sentiment_score),
        )
        return cur.lastrowid
```

- [ ] **Step 4: Run test — verify it passes**

```
python -m pytest tests/test_sentiment.py::test_log_signal_accepts_sentiment_score -v
```

Expected: PASS.

- [ ] **Step 5: Run full test suite to check no regressions**

```
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```
git add server/db.py tests/test_sentiment.py
git commit -m "feat: add sentiment_score column to signals table"
```

---

## Task 3: API endpoints — `GET /api/sentiment` and settings

**Files:**
- Modify: `server/main.py` (three locations)

- [ ] **Step 1: Add `sentiment` import to `server/main.py`**

Find the imports block at the top of `server/main.py` where `ai_explainer`, `ai_tuner` are imported and add:

```python
from . import sentiment
```

- [ ] **Step 2: Extend `AiSettingsBody` in `server/main.py`**

Find `class AiSettingsBody(BaseModel):` and add four new optional fields:

```python
class AiSettingsBody(BaseModel):
    ollama_url:                str | None   = None
    ollama_model:              str | None   = None
    explanations_enabled:      bool | None  = None
    tuner_enabled:             bool | None  = None
    tuner_provider:            str | None   = None
    claude_api_key:            str | None   = None
    claude_model:              str | None   = None
    target_win_rate:           float | None = None
    sentiment_enabled:         bool | None  = None
    sentiment_block_threshold: float | None = None
    sentiment_boost_threshold: float | None = None
    sentiment_boost_multiplier:float | None = None
```

- [ ] **Step 3: Extend `GET /api/ai/settings` to return sentiment fields**

Find the `return { ... }` block in `ai_settings_get` and add four lines:

```python
        "target_win_rate":           float(db.get_app_config("ai_target_win_rate", "51")),
        "sentiment_enabled":         db.get_app_config("sentiment_enabled", "false") == "true",
        "sentiment_block_threshold": float(db.get_app_config("sentiment_block_threshold", "-0.3")),
        "sentiment_boost_threshold": float(db.get_app_config("sentiment_boost_threshold", "0.3")),
        "sentiment_boost_multiplier":float(db.get_app_config("sentiment_boost_multiplier", "1.25")),
```

- [ ] **Step 4: Extend `PATCH /api/ai/settings` to save sentiment fields**

In `ai_settings_patch`, after the `target_win_rate` block, add:

```python
    if body.sentiment_enabled is not None:
        db.set_app_config("sentiment_enabled", "true" if body.sentiment_enabled else "false")
    if body.sentiment_block_threshold is not None and -1.0 <= body.sentiment_block_threshold <= 0:
        db.set_app_config("sentiment_block_threshold", str(body.sentiment_block_threshold))
    if body.sentiment_boost_threshold is not None and 0 <= body.sentiment_boost_threshold <= 1.0:
        db.set_app_config("sentiment_boost_threshold", str(body.sentiment_boost_threshold))
    if body.sentiment_boost_multiplier is not None and 1.0 <= body.sentiment_boost_multiplier <= 2.0:
        db.set_app_config("sentiment_boost_multiplier", str(body.sentiment_boost_multiplier))
```

- [ ] **Step 5: Add `GET /api/sentiment` endpoint**

Add after the `ai_tuning_log_get` endpoint:

```python
@app.get("/api/sentiment")
def sentiment_get(request: Request):
    _require_auth(request)
    return sentiment.get_all_cached()
```

- [ ] **Step 6: Verify server starts without errors**

```
python -m uvicorn server.main:app --port 8000 --reload
```

Expected: Server starts, no import errors. Check `http://localhost:8000/api/sentiment` returns `[]`.

- [ ] **Step 7: Commit**

```
git add server/main.py
git commit -m "feat: add /api/sentiment endpoint and sentiment settings"
```

---

## Task 4: Engine integration — gate and boost signals

**Files:**
- Modify: `server/engine.py`

- [ ] **Step 1: Add sentiment import to `server/engine.py`**

Find the existing imports at the top (where `ai_explainer` is imported) and add:

```python
from . import sentiment
```

- [ ] **Step 2: Add sentiment gate/boost block to `run_tick`**

Find the comment `# ── crypto minimum notional guard ($10)` in `engine.py` (around line 253). Insert the sentiment block **before** the submit block but **after** the dust guard. The exact insertion point is after the dust guard `continue` and before `# ── submit ──`:

```python
                # ── sentiment gate / boost ─────────────────────────────────
                if sentiment.is_enabled() and sig.side == "buy":
                    sent        = sentiment.get_sentiment(sig.symbol)
                    sent_score  = sent["score"]
                    block_thresh = float(db.get_app_config("sentiment_block_threshold", "-0.3"))
                    boost_thresh = float(db.get_app_config("sentiment_boost_threshold", "0.3"))
                    boost_mult   = float(db.get_app_config("sentiment_boost_multiplier", "1.25"))
                    if sent_score < block_thresh:
                        error_qty = final_qty if final_qty is not None else (sig.notional or 0)
                        db.log_signal(s["name"], sig.symbol, sig.side, error_qty,
                                      f"{sig.reason} | sentiment blocked: {sent['reason']}",
                                      None, "blocked", blocked=True, account_id=acct_id,
                                      sentiment_score=sent_score)
                        log.info("sentiment blocked %s %s score=%.2f", sig.symbol, sig.side, sent_score)
                        continue
                    if sent_score > boost_thresh and sig.notional:
                        sig = Signal(
                            symbol=sig.symbol, side=sig.side, reason=sig.reason,
                            notional=sig.notional * boost_mult,
                        )
                        log.info("sentiment boost %s notional x%.2f score=%.2f",
                                 sig.symbol, boost_mult, sent_score)
                else:
                    sent_score = None
```

- [ ] **Step 3: Pass `sentiment_score` to `db.log_signal()` on successful order**

Find the `sig_id = db.log_signal(...)` call on successful order submission (around line 284) and add the `sentiment_score` parameter:

```python
                    sig_id = db.log_signal(s["name"], sig.symbol, sig.side, display_qty,
                                           sig.reason, order["id"], order["status"],
                                           account_id=acct_id,
                                           filled_qty=ord_filled_qty,
                                           filled_price=ord_filled_price,
                                           sentiment_score=sent_score)
```

Note: `sent_score` is defined in the sentiment block above. When sentiment is disabled, `sent_score = None` (set in the `else` branch).

- [ ] **Step 4: Verify engine starts and ticks without errors**

Start the server and watch the log for one full tick cycle (60 seconds). Expected: No errors. If sentiment is disabled (default), `sent_score` is always `None` and all behaviour is unchanged.

- [ ] **Step 5: Commit**

```
git add server/engine.py
git commit -m "feat: gate and boost signals with sentiment score in engine"
```

---

## Task 5: Dashboard card — Market Sentiment

**Files:**
- Modify: `server/static/index.html`
- Modify: `server/static/app.js`

- [ ] **Step 1: Add the Market Sentiment card to `index.html`**

Find the last `</div><!-- end card -->` before `</main>` in `server/static/index.html`. Add this card after it (before `</main>`):

```html
<!-- ── Market Sentiment ── -->
<div class="card">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.85rem;flex-wrap:wrap;gap:.5rem;">
    <div>
      <div style="font-size:14px;font-weight:700;">Market Sentiment</div>
      <div style="font-size:12px;color:var(--muted);margin-top:2px;">Claude-scored news headlines per ticker &mdash; refreshes every 15 min.</div>
    </div>
    <span id="sentiment-updated" style="font-size:11px;color:var(--muted);"></span>
  </div>
  <div class="dtable-wrap">
    <table class="dtable">
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Score</th>
          <th>Sentiment</th>
          <th>Reasoning</th>
        </tr>
      </thead>
      <tbody id="sentiment-tbody">
        <tr><td colspan="4" class="state-empty">Sentiment data will appear once the engine runs.</td></tr>
      </tbody>
    </table>
  </div>
</div>
```

- [ ] **Step 2: Add `loadSentiment()` to `app.js`**

Find `async function initDashboard()` (or the equivalent dashboard init function) in `server/static/app.js`. Add `loadSentiment()` to its call list, and add the function itself in the dashboard section:

```javascript
async function loadSentiment() {
  const tbody = document.getElementById('sentiment-tbody');
  if (!tbody) return;
  try {
    const data = await api('/api/sentiment');
    const upd  = document.getElementById('sentiment-updated');
    if (upd) upd.textContent = data.length ? `Updated ${new Date().toLocaleTimeString()}` : '';

    if (!data.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="state-empty">Sentiment data will appear once the engine runs.</td></tr>';
      return;
    }

    // Sort by absolute score descending (most sentiment first)
    data.sort((a, b) => Math.abs(b.score) - Math.abs(a.score));

    tbody.innerHTML = data.map(row => {
      const score    = typeof row.score === 'number' ? row.score : 0;
      const pct      = Math.round(((score + 1) / 2) * 100);  // map -1..1 to 0..100%
      const color    = score > 0.3  ? '#10B981'
                     : score < -0.3 ? '#EF4444'
                     : '#F59E0B';
      const label    = score > 0.3  ? 'Positive'
                     : score < -0.3 ? 'Negative'
                     : 'Neutral';
      const bgColor  = score > 0.3  ? 'rgba(16,185,129,.15)'
                     : score < -0.3 ? 'rgba(239,68,68,.15)'
                     : 'rgba(245,158,11,.15)';
      const barBg    = 'rgba(100,116,139,.15)';
      return `<tr>
        <td style="font-weight:600;">${escHtml(row.symbol)}</td>
        <td>
          <div style="display:flex;align-items:center;gap:.5rem;">
            <div style="width:80px;height:6px;border-radius:3px;background:${barBg};flex-shrink:0;">
              <div style="width:${pct}%;height:100%;border-radius:3px;background:${color};"></div>
            </div>
            <span style="font-size:11px;font-weight:700;color:${color};">${score >= 0 ? '+' : ''}${score.toFixed(2)}</span>
          </div>
        </td>
        <td>
          <span style="font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px;background:${bgColor};color:${color};">
            ${label}
          </span>
        </td>
        <td style="font-size:12px;color:var(--muted);max-width:300px;">${escHtml(row.reason || '—')}</td>
      </tr>`;
    }).join('');
  } catch (_) {
    if (tbody) tbody.innerHTML = '<tr><td colspan="4" class="state-empty">Could not load sentiment data.</td></tr>';
  }
}
```

- [ ] **Step 3: Wire `loadSentiment()` into the dashboard init and set refresh interval**

In the dashboard init function (where `loadPositions()`, `loadBalances()` etc. are called), add:

```javascript
await loadSentiment();
setInterval(loadSentiment, 15 * 60 * 1000);  // refresh every 15 min
```

- [ ] **Step 4: Verify in browser — dark and light mode**

1. Open `http://localhost:8000/static/index.html`
2. Scroll to the bottom — the Market Sentiment card should appear
3. If the engine hasn't run yet, it shows the empty state message
4. Toggle dark/light mode — card should follow the theme (uses `var(--muted)`, `var(--border)`, `dtable` class)

- [ ] **Step 5: Commit**

```
git add server/static/index.html server/static/app.js
git commit -m "feat: add Market Sentiment heatmap card to dashboard"
```

---

## Task 6: Settings UI — News Sentiment section on Risk page

**Files:**
- Modify: `server/static/risk.html`
- Modify: `server/static/app.js`

- [ ] **Step 1: Add News Sentiment settings card to `risk.html`**

Find the last `</div><!-- end card -->` before `</main>` in `server/static/risk.html`. Add this card after all existing cards (before `</main>`):

```html
<!-- ── News Sentiment Settings ── -->
<div class="card">
  <div class="risk-section-hd">
    <div class="risk-section-title">News Sentiment</div>
    <div class="risk-section-desc">
      Claude scores recent headlines per ticker. Negative sentiment blocks buys; positive sentiment boosts position size.
      Requires a Claude API key configured in <a href="/static/ai-tuning.html" style="color:var(--blue);">AI Tuning</a>.
    </div>
  </div>

  <!-- Enable toggle -->
  <div style="display:flex;align-items:center;justify-content:space-between;padding:.75rem 0;border-bottom:1px solid var(--border);margin-bottom:1rem;">
    <div>
      <div style="font-size:13px;font-weight:600;">Enable Sentiment Filtering</div>
      <div style="font-size:12px;color:var(--muted);margin-top:2px;">Off by default — enable once Claude API key is set.</div>
    </div>
    <label class="ks-toggle" style="cursor:pointer;display:flex;align-items:center;gap:.5rem;">
      <input type="checkbox" id="inp-sentiment-enabled" onchange="saveSentimentEnabled(this.checked)" style="display:none;">
      <div id="sentiment-toggle-track" style="width:40px;height:22px;border-radius:11px;background:var(--border);position:relative;transition:background .2s;cursor:pointer;" onclick="document.getElementById('inp-sentiment-enabled').click()">
        <div id="sentiment-toggle-thumb" style="width:18px;height:18px;border-radius:50%;background:#fff;position:absolute;top:2px;left:2px;transition:left .2s;box-shadow:0 1px 3px rgba(0,0,0,.3);"></div>
      </div>
      <span id="sentiment-toggle-label" style="font-size:12px;font-weight:600;color:var(--muted);">OFF</span>
    </label>
  </div>

  <!-- Threshold inputs -->
  <div class="rg3" style="grid-template-columns:repeat(3,1fr);">
    <div class="ri">
      <div class="ri-top">
        <div class="ri-icon" style="background:rgba(239,68,68,.1);">
          <svg width="14" height="14" fill="none" stroke="#EF4444" stroke-width="2" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></svg>
        </div>
        <div><div class="ri-label">Block Threshold</div><div class="ri-desc">Block buy when score is below this (range −1 to 0)</div></div>
      </div>
      <div class="ri-input-row">
        <div class="ri-field"><input id="inp-sentiment-block" type="number" step="0.05" min="-1" max="0" value="-0.3"></div>
        <button class="btn-risksave risk-save-btn" onclick="saveSentimentThresholds()">Save</button>
      </div>
    </div>

    <div class="ri">
      <div class="ri-top">
        <div class="ri-icon" style="background:rgba(16,185,129,.1);">
          <svg width="14" height="14" fill="none" stroke="#10B981" stroke-width="2" viewBox="0 0 24 24"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>
        </div>
        <div><div class="ri-label">Boost Threshold</div><div class="ri-desc">Boost size when score is above this (range 0 to 1)</div></div>
      </div>
      <div class="ri-input-row">
        <div class="ri-field"><input id="inp-sentiment-boost" type="number" step="0.05" min="0" max="1" value="0.3"></div>
      </div>
    </div>

    <div class="ri">
      <div class="ri-top">
        <div class="ri-icon" style="background:rgba(59,130,246,.1);">
          <svg width="14" height="14" fill="none" stroke="#3B82F6" stroke-width="2" viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/></svg>
        </div>
        <div><div class="ri-label">Boost Multiplier</div><div class="ri-desc">Multiply notional by this on positive sentiment</div></div>
      </div>
      <div class="ri-input-row">
        <div class="ri-field"><input id="inp-sentiment-mult" type="number" step="0.05" min="1" max="2" value="1.25"><span class="ri-suffix">&times;</span></div>
      </div>
    </div>
  </div>
  <div id="sentiment-settings-msg" style="font-size:12px;margin-top:.6rem;display:none;"></div>
</div>
```

- [ ] **Step 2: Add sentiment settings JS to `app.js`**

In the Risk page section of `app.js` (near other risk-related functions like `loadRisk()`), add:

```javascript
async function loadSentimentSettings() {
  try {
    const s = await api('/api/ai/settings');
    const enabled = s.sentiment_enabled || false;
    const cb = document.getElementById('inp-sentiment-enabled');
    if (cb) cb.checked = enabled;
    _updateSentimentToggleUI(enabled);
    const block = document.getElementById('inp-sentiment-block');
    const boost = document.getElementById('inp-sentiment-boost');
    const mult  = document.getElementById('inp-sentiment-mult');
    if (block && s.sentiment_block_threshold != null) block.value = s.sentiment_block_threshold;
    if (boost && s.sentiment_boost_threshold != null) boost.value = s.sentiment_boost_threshold;
    if (mult  && s.sentiment_boost_multiplier != null) mult.value = s.sentiment_boost_multiplier;
  } catch (_) {}
}

function _updateSentimentToggleUI(enabled) {
  const track = document.getElementById('sentiment-toggle-track');
  const thumb = document.getElementById('sentiment-toggle-thumb');
  const label = document.getElementById('sentiment-toggle-label');
  if (track) track.style.background = enabled ? 'var(--blue, #3B82F6)' : 'var(--border)';
  if (thumb) thumb.style.left = enabled ? '20px' : '2px';
  if (label) { label.textContent = enabled ? 'ON' : 'OFF'; label.style.color = enabled ? 'var(--blue, #3B82F6)' : 'var(--muted)'; }
}

window.saveSentimentEnabled = async function(enabled) {
  _updateSentimentToggleUI(enabled);
  try {
    await jsonPatch('/api/ai/settings', { sentiment_enabled: enabled });
  } catch (e) {
    const msg = document.getElementById('sentiment-settings-msg');
    if (msg) { msg.style.color = 'var(--red)'; msg.textContent = `Error: ${e.message}`; msg.style.display = ''; }
  }
};

window.saveSentimentThresholds = async function() {
  const block = parseFloat(document.getElementById('inp-sentiment-block')?.value);
  const boost = parseFloat(document.getElementById('inp-sentiment-boost')?.value);
  const mult  = parseFloat(document.getElementById('inp-sentiment-mult')?.value);
  const msg   = document.getElementById('sentiment-settings-msg');
  if (isNaN(block) || block < -1 || block > 0) {
    if (msg) { msg.style.color='var(--red)'; msg.textContent='Block threshold must be between -1 and 0.'; msg.style.display=''; }
    return;
  }
  if (isNaN(boost) || boost < 0 || boost > 1) {
    if (msg) { msg.style.color='var(--red)'; msg.textContent='Boost threshold must be between 0 and 1.'; msg.style.display=''; }
    return;
  }
  if (isNaN(mult) || mult < 1 || mult > 2) {
    if (msg) { msg.style.color='var(--red)'; msg.textContent='Boost multiplier must be between 1 and 2.'; msg.style.display=''; }
    return;
  }
  try {
    await jsonPatch('/api/ai/settings', {
      sentiment_block_threshold:  block,
      sentiment_boost_threshold:  boost,
      sentiment_boost_multiplier: mult,
    });
    if (msg) { msg.style.color='var(--green)'; msg.textContent='Sentiment settings saved.'; msg.style.display=''; setTimeout(()=>msg.style.display='none',3000); }
  } catch (e) {
    if (msg) { msg.style.color='var(--red)'; msg.textContent=`Error: ${e.message}`; msg.style.display=''; }
  }
};
```

- [ ] **Step 3: Call `loadSentimentSettings()` from the Risk page init**

In `app.js`, find `initRisk()` (or the risk page init function) and add `loadSentimentSettings()` to the list of calls:

```javascript
await Promise.all([loadRisk(), loadSentimentSettings()]);
```

- [ ] **Step 4: Verify in browser — dark and light mode**

1. Open `http://localhost:8000/static/risk.html`
2. Scroll to bottom — "News Sentiment" card should appear
3. Toggle the switch ON/OFF — track should turn blue/grey, label should say ON/OFF
4. Change threshold values, click Save — success message appears
5. Toggle dark/light mode — all inputs and labels follow theme

- [ ] **Step 5: Commit**

```
git add server/static/risk.html server/static/app.js
git commit -m "feat: add News Sentiment settings section to Risk page"
```

---

## Task 7: End-to-end smoke test

**Files:** No code changes — verification only.

- [ ] **Step 1: Enable sentiment in the UI**

Go to `http://localhost:8000/static/risk.html` → News Sentiment section → toggle ON.

- [ ] **Step 2: Manually trigger a sentiment fetch via the API**

```
curl -s -b "tb_session=<your-session-cookie>" http://localhost:8000/api/sentiment
```

Expected: `[]` (empty — no tickers cached yet, engine hasn't ticked).

- [ ] **Step 3: Watch engine log for sentiment activity**

Wait for the engine to tick (up to 60 seconds). Watch the server log for lines like:

```
INFO sentiment - sentiment boost ETH/USDT notional x1.25 score=0.45
INFO sentiment - sentiment blocked AAPL buy score=-0.55
```

Or if Claude API key is not valid:
```
DEBUG sentiment - sentiment: Claude call failed: ...
```

If Claude call fails, sentiment defaults to 0.0 (neutral) and the trade proceeds normally — this is correct fail-open behaviour.

- [ ] **Step 4: Check dashboard sentiment card**

Open `http://localhost:8000/static/index.html`. After the engine has run at least one tick with sentiment enabled, the Market Sentiment card should show rows for the tickers that were evaluated.

- [ ] **Step 5: Check signals in the DB have sentiment_score populated**

```python
python -c "
from server import db
sigs = db.recent_signals(10)
for s in sigs:
    print(s['symbol'], s['side'], s.get('sentiment_score'))
"
```

Expected: Recent buy signals show a `sentiment_score` value; sells and pre-feature signals show `None`.

- [ ] **Step 6: Run full test suite**

```
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests pass.

- [ ] **Step 7: Final commit**

```
git add -A
git commit -m "feat: news sentiment analysis — end-to-end smoke test verified"
```
