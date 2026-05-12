"""License key generation and verification for TradeBot."""
import base64
import hashlib
import hmac
import json
import os
import platform
import time
import uuid

SELLER_SECRET = os.environ.get("TRADEBOT_LICENSE_SECRET", "CHANGE-ME-32-CHARS-SELLER-SECRET!")
MACHINE_ANY = "ANY"


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
    from .db import get_app_config
    key = get_app_config("license_key", "")
    if not key:
        return {"valid": False, "reason": "No license key entered.", "days_remaining": 0}
    try:
        result = verify_key(key, SELLER_SECRET)
        return {**result, "reason": ""}
    except LicenseError as e:
        return {"valid": False, "reason": str(e), "days_remaining": 0}
