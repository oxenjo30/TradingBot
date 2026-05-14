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
            return {k: v for k, v in cached.items() if k != "cached_at"}

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
    return {k: v for k, v in entry.items() if k != "cached_at"}


def get_all_cached() -> list[dict]:
    """Return all cached sentiment entries (excluding internal cached_at field)."""
    with _lock:
        return [
            {k: v for k, v in entry.items() if k != "cached_at"}
            for entry in _cache.values()
        ]
