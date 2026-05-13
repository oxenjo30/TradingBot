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
        db.upsert_strategy(s["name"], enabled=s["enabled"], params=new_params)
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
    lines = [f"AI Tuner adjusted {len(results)} strategy(s):\n"]
    for r in results:
        lines.append(f"- {r['strategy']} — win rate was {r['win_rate_before']}%")
        lines.append(f"  Reason: {r['rationale'][:120]}")
    text = "\n".join(lines)
    notifications._send_async(notifications._send_telegram, text)
    notifications._send_async(notifications._send_slack, text)
    notifications._send_async(notifications._send_discord, text)
