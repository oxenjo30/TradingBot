"""Simple session-based auth. Password stored as bcrypt hash in DB."""
import hashlib
import hmac
import os
import time
from .db import get_conn, init_db

SESSION_TTL = 60 * 60 * 24  # 24 hours
_sessions: dict[str, float] = {}  # token → expiry_ts


# ── Password ──────────────────────────────────────────────────────────────────

def _hash_pw(password: str) -> str:
    salt = os.urandom(32).hex()
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310_000)
    return f"{salt}:{h.hex()}"


def _verify_pw(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split(":", 1)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310_000)
        return hmac.compare_digest(candidate.hex(), h)
    except Exception:
        return False


def set_password(password: str):
    hashed = _hash_pw(password)
    with get_conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO app_config(key, value) VALUES('password_hash', ?)",
            (hashed,)
        )


def get_password_hash() -> str | None:
    with get_conn() as c:
        row = c.execute(
            "SELECT value FROM app_config WHERE key='password_hash'"
        ).fetchone()
    return row["value"] if row else None


def password_is_set() -> bool:
    return get_password_hash() is not None


def check_password(password: str) -> bool:
    h = get_password_hash()
    if not h:
        return False
    return _verify_pw(password, h)


# ── Sessions ──────────────────────────────────────────────────────────────────

def create_session() -> str:
    token = os.urandom(32).hex()
    _sessions[token] = time.time() + SESSION_TTL
    return token


def validate_session(token: str | None) -> bool:
    if not token:
        return False
    expiry = _sessions.get(token)
    if not expiry:
        return False
    if time.time() > expiry:
        _sessions.pop(token, None)
        return False
    # refresh TTL on activity
    _sessions[token] = time.time() + SESSION_TTL
    return True


def revoke_session(token: str):
    _sessions.pop(token, None)


# ── Setup state ───────────────────────────────────────────────────────────────

def setup_complete() -> bool:
    with get_conn() as c:
        row = c.execute(
            "SELECT value FROM app_config WHERE key='setup_complete'"
        ).fetchone()
    return row is not None and row["value"] == "true"


def mark_setup_complete():
    with get_conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO app_config(key, value) VALUES('setup_complete', 'true')"
        )
