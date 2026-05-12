"""License key generation and verification for TradeBot."""
import base64
import hashlib
import hmac
import json
import os
import platform
import time
import uuid

MACHINE_ANY = "ANY"

# Embedded fallback — never changes, survives .env edits or deletions
_EMBEDDED_SECRET = "<REDACTED>"

# In-process cache: once valid, skip re-verification for 1 hour
_cache: dict = {}
_CACHE_TTL = 3600  # seconds


def _get_seller_secret() -> str:
    """Return the seller secret. Env var takes priority; embedded constant is the fallback."""
    return (
        os.environ.get("TRADEBOT_LICENSE_SECRET")
        or _read_env_secret()
        or _EMBEDDED_SECRET
    )


def _read_env_secret() -> str:
    """Try to read TRADEBOT_LICENSE_SECRET directly from .env without altering os.environ."""
    try:
        from pathlib import Path
        env_path = Path(__file__).parent.parent / ".env"
        for line in env_path.read_text().splitlines():
            if line.startswith("TRADEBOT_LICENSE_SECRET="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


class LicenseError(Exception):
    pass


def get_machine_id() -> str:
    raw = f"{platform.node()}|{uuid.getnode()}|{platform.machine()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def mint_key(secret: str, machine_id: str, days: int) -> str:
    expiry = int(time.time()) + days * 86400
    payload = json.dumps({"m": machine_id, "exp": expiry}, separators=(",", ":"))
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    bundle = json.dumps({"p": payload, "s": sig}, separators=(",", ":"))
    return base64.urlsafe_b64encode(bundle.encode()).decode()


def verify_key(key: str, secret: str, machine_id: str | None = None) -> dict:
    try:
        bundle = json.loads(base64.urlsafe_b64decode(key.encode()))
        payload_str = bundle["p"]
        sig = bundle["s"]
    except Exception:
        raise LicenseError("invalid: key is malformed")

    expected_sig = hmac.new(secret.encode(), payload_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        raise LicenseError("invalid: signature mismatch")

    payload = json.loads(payload_str)
    now = int(time.time())

    if payload["exp"] < now:
        raise LicenseError("expired: license key has expired")

    if payload["m"] != MACHINE_ANY:
        actual = machine_id or get_machine_id()
        if payload["m"] != actual:
            raise LicenseError("machine: key is locked to a different machine")

    days_remaining = max(0, (payload["exp"] - now) // 86400)
    return {"valid": True, "days_remaining": days_remaining, "machine_id": payload["m"]}


def check_stored_license() -> dict:
    """Verify the stored license key. Result is cached for 1 hour to avoid per-request overhead."""
    global _cache
    now = time.time()

    # Return cached result if still fresh
    if _cache.get("valid") and now < _cache.get("expires_at", 0):
        return {k: v for k, v in _cache.items() if k != "expires_at"}

    from .db import get_app_config
    key = get_app_config("license_key", "")
    if not key:
        result = {"valid": False, "reason": "No license key entered.", "days_remaining": 0}
        _cache = {}
        return result

    try:
        result = verify_key(key, _get_seller_secret())
        result["reason"] = ""
        # Cache valid result for 1 hour
        _cache = {**result, "expires_at": now + _CACHE_TTL}
        return result
    except LicenseError as e:
        _cache = {}
        return {"valid": False, "reason": str(e), "days_remaining": 0}


def invalidate_cache() -> None:
    """Call after storing a new license key so the next request re-verifies."""
    global _cache
    _cache = {}
