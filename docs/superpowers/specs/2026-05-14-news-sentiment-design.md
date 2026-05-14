# News Sentiment Analysis — Design Spec

## Goal

Fetch Google News RSS headlines per ticker, score them with Claude Haiku, and use that score to gate or boost trade signals. Show a live sentiment heatmap card on the dashboard that respects dark/light mode.

## Architecture

### New file: `server/sentiment.py`

Single module with three responsibilities — fetch, score, cache. No external dependencies beyond `urllib` (already used in `ai_explainer.py`) and the existing Claude API call pattern.

**Fetch:**
- `fetch_headlines(symbol: str) -> list[str]` — builds `https://news.google.com/rss/search?q={symbol}+stock&hl=en-US&gl=US&ceid=US:en`, parses RSS XML with `xml.etree.ElementTree`, returns up to 5 `<title>` strings. For crypto symbols (contains `/`), strips the `/USDT` suffix and appends `crypto` instead of `stock`.

**Score:**
- `score_headlines(symbol: str, headlines: list[str]) -> dict` — sends headlines to Claude Haiku via `urllib` (same pattern as `ai_explainer._call_claude`). Prompt asks for JSON: `{"score": float, "reason": "one sentence"}`. Score is −1.0 (very negative) to +1.0 (very positive). Returns `{"score": 0.0, "reason": "no data"}` on failure.

**Cache:**
- Module-level dict `_cache: dict[str, dict]` — keyed by symbol, value is `{score, reason, fetched_at}`. TTL = 15 minutes. `get_sentiment(symbol: str) -> dict` checks cache first, fetches+scores if stale. Thread-safe via a single `threading.Lock`.

**Public API:**
```python
def get_sentiment(symbol: str) -> dict:
    """Returns {score: float, reason: str, fetched_at: str}. Cached 15 min."""

def get_all_cached() -> list[dict]:
    """Returns [{symbol, score, reason, fetched_at}] for all cached symbols."""

def is_enabled() -> bool:
    """Reads ai_sentiment_enabled from app_config."""
```

---

### Engine integration: `server/engine.py`

After risk checks pass and `final_qty` is calculated, before order submission:

```python
if sentiment.is_enabled():
    sent = sentiment.get_sentiment(sig.symbol)
    score = sent["score"]
    block_thresh = float(db.get_app_config("sentiment_block_threshold", "-0.3"))
    boost_thresh  = float(db.get_app_config("sentiment_boost_threshold", "0.3"))
    boost_mult    = float(db.get_app_config("sentiment_boost_multiplier", "1.25"))

    if score < block_thresh:
        db.log_signal(..., status="blocked", reason=f"{sig.reason} | sentiment blocked: {sent['reason']}")
        continue

    if score > boost_thresh and sig.notional:
        sig = Signal(symbol=sig.symbol, side=sig.side, reason=sig.reason,
                     notional=sig.notional * boost_mult)
```

Sentiment score is passed to `db.log_signal()` via a new `sentiment_score` parameter.

---

### DB changes: `server/db.py`

**Migration** (added to `init_db()` alongside existing `ALTER TABLE` migrations):
```sql
ALTER TABLE signals ADD COLUMN sentiment_score REAL DEFAULT NULL;
```

**`log_signal()`** gains an optional `sentiment_score: float | None = None` parameter, written to the new column.

No separate sentiment table — scores live in the signal row where they're needed.

---

### New API endpoint: `server/main.py`

```
GET /api/sentiment
```
Returns current cache for all symbols across all enabled strategies:
```json
[
  {"symbol": "AAPL", "score": 0.72, "reason": "Strong earnings beat expectations", "fetched_at": "2026-05-14T10:30:00"},
  {"symbol": "BTC/USDT", "score": -0.41, "reason": "Regulatory crackdown fears", "fetched_at": "2026-05-14T10:28:00"}
]
```

**Settings endpoints** — extend existing `GET /api/ai/settings` and `PATCH /api/ai/settings` (same `AiSettingsBody`) with four new fields:
- `sentiment_enabled: bool`
- `sentiment_block_threshold: float`
- `sentiment_boost_threshold: float`
- `sentiment_boost_multiplier: float`

---

### Dashboard card: `server/static/index.html` + `server/static/app.js`

A new **"Market Sentiment"** card added to `index.html` below the existing overview cards.

**Layout:** One row per cached ticker. Columns: Symbol | Score bar | Label | Claude's reasoning.

**Score bar:** A small inline bar (−1 to +1 range) filled with:
- Red (`#EF4444`) for score < −0.3
- Yellow (`#F59E0B`) for −0.3 to +0.3
- Green (`#10B981`) for score > +0.3

**Dark/light mode:** All colors use `var(--border)`, `var(--muted)`, `var(--text)`, `var(--card)`, `var(--bg)` — same CSS variables used across the app. Score bar background uses `rgba()` values consistent with existing badge styles.

**Refresh:** `loadSentiment()` called on page load and every 15 minutes via `setInterval`.

**Empty state:** If no sentiment data yet, shows "Sentiment data will appear once the engine runs." using the existing `.state-empty` class.

**JS function in `app.js`:**
```javascript
async function loadSentiment() {
  // fetch /api/sentiment, render rows into #sentiment-tbody
}
```

---

### Settings UI: `server/static/risk.html`

A new **"News Sentiment"** section added at the bottom of the Risk settings page (below the existing crypto risk section), following the same card + input pattern.

Controls:
- Toggle: Enable/disable sentiment filtering (same toggle style as kill switch)
- Number input: Block threshold (default −0.3, range −1 to 0)
- Number input: Boost threshold (default +0.3, range 0 to 1)
- Number input: Boost multiplier (default 1.25×, range 1.0 to 2.0)

All inputs use existing `.risk-input` / `.ai-input` CSS classes and respect dark/light mode via CSS variables.

---

## Data Flow

```
Engine tick
  → strategy.evaluate() → Signal
  → risk.check_all() passes
  → sentiment.get_sentiment(symbol)  ← cache hit (fast) or fetch+score (15-min TTL)
      → Google News RSS fetch
      → Claude Haiku scores headlines
  → score < block_thresh → log blocked signal, continue
  → score > boost_thresh → inflate notional by boost_mult
  → submit order
  → log_signal(..., sentiment_score=score)
```

---

## Settings stored in `app_config`

| Key | Default | Description |
|-----|---------|-------------|
| `sentiment_enabled` | `"false"` | Master on/off switch |
| `sentiment_block_threshold` | `"-0.3"` | Score below this blocks the trade |
| `sentiment_boost_threshold` | `"0.3"` | Score above this boosts notional |
| `sentiment_boost_multiplier` | `"1.25"` | Notional multiplier on strong positive |

Sentiment starts **disabled by default** — user explicitly enables it on the Risk page.

---

## Error Handling

- Google News RSS unreachable → `fetch_headlines` returns `[]`, score defaults to `0.0` (neutral), trade proceeds normally
- Claude API fails → score defaults to `0.0` (neutral), trade proceeds normally
- Never block a trade due to a sentiment fetch failure — fail open, not closed

---

## Out of Scope

- Per-strategy sentiment enable/disable (global toggle only)
- Storing historical sentiment scores in a dedicated table
- Sentiment-based sell signals (only affects buys)
- Multiple news sources (Google RSS only for now)
