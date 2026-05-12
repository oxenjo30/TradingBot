"""Async trade signal explainer — calls Ollama in a background thread."""
import json
import logging
import queue
import threading
import urllib.error
import urllib.request

from . import db

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
            _Q.task_done()
            break
        signal_id, sig = item
        try:
            if _explanations_enabled():
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
        except queue.Empty:
            pass
        try:
            _Q.put_nowait((signal_id, sig))
            log.warning("Explanation queue full — dropped oldest item")
        except queue.Full:
            log.warning("Explanation queue full — could not enqueue signal %d", signal_id)


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
