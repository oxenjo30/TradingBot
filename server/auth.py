"""Simple session-based auth. Password stored as bcrypt hash in DB."""
import hashlib
import hmac
import os
import time
import threading
from .db import get_conn, init_db

SESSION_TTL = 60 * 60 * 24  # 24 hours

# ── Brute-force protection ────────────────────────────────────────────────────
_FAIL_LIMIT   = 5          # lock after this many consecutive failures
_LOCKOUT_SECS = 300        # 5-minute lockout
_fail_lock    = threading.Lock()
_fail_count   = 0          # consecutive failed attempts
_locked_until = 0.0        # epoch timestamp when lockout expires


def check_login_allowed() -> tuple[bool, int]:
    """Return (allowed, seconds_remaining). Call before checking password."""
    global _locked_until
    with _fail_lock:
        remaining = max(0, int(_locked_until - time.time()))
        return (remaining == 0), remaining


def record_login_success():
    global _fail_count, _locked_until
    with _fail_lock:
        _fail_count   = 0
        _locked_until = 0.0


def record_login_failure():
    global _fail_count, _locked_until
    with _fail_lock:
        _fail_count += 1
        if _fail_count >= _FAIL_LIMIT:
            _locked_until = time.time() + _LOCKOUT_SECS


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


# ── Sessions (DB-backed, survive restarts) ────────────────────────────────────

def create_session() -> str:
    from .db import save_session, purge_expired_sessions
    token = os.urandom(32).hex()
    expires_at = time.time() + SESSION_TTL
    save_session(token, expires_at)
    purge_expired_sessions()  # clean up old sessions opportunistically
    return token


def validate_session(token: str | None) -> bool:
    if not token:
        return False
    from .db import load_session, update_session_expiry
    expiry = load_session(token)
    if expiry is None:
        return False
    if time.time() > expiry:
        revoke_session(token)
        return False
    # refresh TTL on activity
    update_session_expiry(token, time.time() + SESSION_TTL)
    return True


def revoke_session(token: str):
    from .db import delete_session
    delete_session(token)


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
