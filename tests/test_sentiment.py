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
