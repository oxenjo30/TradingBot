# Owner Mode + Asymmetric Licensing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the crackable symmetric-HMAC license scheme with asymmetric Ed25519 signing (buyers get a verify-only public key, cannot mint), and hide/block seller-only tooling (License Management + `/api/admin/*`) behind an owner-mode flag.

**Architecture:** `license.py` mints with a private key held only on the owner instance (env `TRADEBOT_LICENSE_PRIVATE_KEY`) and verifies with a public key baked into every build (constant `LICENSE_PUBLIC_KEY`, env-overridable). Owner mode is a server-side network gate: `_require_owner()` returns 403 on the six `/api/admin/*` endpoints when `TRADEBOT_OWNER_MODE` is unset, and an authenticated `/api/app-info` tells the UI whether to render the License Management panel.

**Tech Stack:** Python 3, FastAPI, `cryptography` (Ed25519, already installed for Fernet), pytest, vanilla JS frontend.

---

## Spec reference

Design spec: `docs/superpowers/specs/2026-06-01-owner-mode-and-asymmetric-licensing-design.md`

## Key signatures (used across tasks — keep consistent)

- `license.py`:
  - `mint_key(machine_id: str, days: int) -> str` — signs with the private key from `TRADEBOT_LICENSE_PRIVATE_KEY`; `RuntimeError` if absent.
  - `verify_key(key: str, machine_id: str | None = None) -> dict` — verifies with the public key; `LicenseError` on malformed/invalid/expired/machine-mismatch.
  - `check_stored_license() -> dict` — unchanged signature; internally calls `verify_key(key)` (no secret).
  - Constant `LICENSE_PUBLIC_KEY: str` (base64, env-overridable via `TRADEBOT_LICENSE_PUBLIC_KEY`).
- `main.py`:
  - `owner_mode_enabled() -> bool`
  - `_require_owner(request: Request) -> None` — calls `_require_auth`, then 403 if not owner.
- `tests/conftest.py` (test helper, importable by other test modules):
  - `mint_test_key(machine_id: str = "ANY", days: int = 365) -> str`

## File structure

| File | Responsibility | Action |
|------|----------------|--------|
| `server/license.py` | Ed25519 mint/verify + machine/expiry checks | Modify (rewrite crypto) |
| `scripts/gen_license_keys.py` | One-off keypair generator CLI | Create |
| `server/lemon.py` | Webhook auto-issue minting | Modify (line 6, 39 of the function) |
| `server/main.py` | owner helpers, `/api/app-info`, gate `/api/admin/*`, license caller | Modify |
| `server/static/settings.html` | Hide License Management card by default | Modify (markup) |
| `server/static/app.js` | Fetch `/api/app-info`, reveal card if owner | Modify (`initSettings`) |
| `.env.example` | Document new env vars, remove old | Modify |
| `tests/conftest.py` | Keypair fixture + `mint_test_key` helper | Modify |
| `tests/test_license.py` | Rewrite to new signatures | Modify |
| `tests/test_license_asymmetric.py` | Asymmetric-specific tests | Create |
| `tests/test_owner_mode.py` | Owner-gate tests | Create |
| `tests/test_license_api.py` | Use keypair helper | Modify |
| `tests/test_export.py` | Use keypair helper | Modify |
| `tests/test_lemon.py` | Use keypair helper | Modify |

---

## Task 0: Create the development branch

- [ ] **Step 1: Create and switch to a feature branch**

We are on `master`. Do not implement on master.

Run:
```bash
git checkout -b feat/asymmetric-licensing-owner-mode
```

- [ ] **Step 2: Confirm working tree state**

Run: `git status`
Expected: on branch `feat/asymmetric-licensing-owner-mode`. (Pre-existing uncommitted changes in `server/db.py`, `server/engine.py`, `server/main.py`, `server/static/app.js`, `server/static/landing.html`, `start.bat`, `.gitignore` may be present — leave them; this plan only touches the files listed above, and you will stage selectively per task.)

---

## Task 1: Rewrite `license.py` to Ed25519

**Files:**
- Modify: `server/license.py`
- Test: `tests/test_license_asymmetric.py` (created here), `tests/test_license.py` (updated in Task 5)

This task depends on a test keypair. Define it inline in the test file for now (Task 5 moves the shared one into conftest).

- [ ] **Step 1: Write the failing test**

Create `tests/test_license_asymmetric.py`:

```python
# tests/test_license_asymmetric.py
"""Ed25519 asymmetric licensing: mint with private key, verify with public key."""
import base64
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


def _make_keypair():
    """Return (private_b64, public_b64) raw Ed25519 keys, base64-encoded."""
    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(priv_raw).decode(), base64.b64encode(pub_raw).decode()


@pytest.fixture
def keypair(monkeypatch):
    priv_b64, pub_b64 = _make_keypair()
    monkeypatch.setenv("TRADEBOT_LICENSE_PRIVATE_KEY", priv_b64)
    import server.license as lic
    monkeypatch.setattr(lic, "LICENSE_PUBLIC_KEY", pub_b64)
    return priv_b64, pub_b64


def test_mint_then_verify_valid(keypair):
    import server.license as lic
    key = lic.mint_key(machine_id="ANY", days=30)
    result = lic.verify_key(key, machine_id="ANY")
    assert result["valid"] is True
    assert result["days_remaining"] > 0
    assert result["days_remaining"] <= 30


def test_expired_key_raises(keypair):
    import server.license as lic
    key = lic.mint_key(machine_id="ANY", days=-1)
    with pytest.raises(lic.LicenseError, match="expired"):
        lic.verify_key(key, machine_id="ANY")


def test_wrong_machine_raises(keypair):
    import server.license as lic
    key = lic.mint_key(machine_id="MACHINE-A", days=30)
    with pytest.raises(lic.LicenseError, match="machine"):
        lic.verify_key(key, machine_id="MACHINE-B")


def test_universal_key_verifies_anywhere(keypair):
    import server.license as lic
    key = lic.mint_key(machine_id="ANY", days=365)
    result = lic.verify_key(key, machine_id="SOME-REAL-MACHINE")
    assert result["valid"] is True


def test_tampered_payload_raises(keypair):
    import server.license as lic
    key = lic.mint_key(machine_id="ANY", days=30)
    bad = key[:-4] + "XXXX"
    with pytest.raises(lic.LicenseError, match="invalid"):
        lic.verify_key(bad, machine_id="ANY")


def test_wrong_public_key_rejects(monkeypatch):
    """A key minted under one private key fails verification under a different public key."""
    import server.license as lic
    priv_a, _pub_a = _make_keypair()
    _priv_b, pub_b = _make_keypair()
    monkeypatch.setenv("TRADEBOT_LICENSE_PRIVATE_KEY", priv_a)
    key = lic.mint_key(machine_id="ANY", days=30)
    monkeypatch.setattr(lic, "LICENSE_PUBLIC_KEY", pub_b)
    with pytest.raises(lic.LicenseError, match="invalid"):
        lic.verify_key(key, machine_id="ANY")


def test_mint_without_private_key_raises(monkeypatch):
    """Buyer build (no private key) physically cannot mint."""
    import server.license as lic
    monkeypatch.delenv("TRADEBOT_LICENSE_PRIVATE_KEY", raising=False)
    with pytest.raises(RuntimeError, match="private key"):
        lic.mint_key(machine_id="ANY", days=30)


def test_verify_with_no_public_key_configured(monkeypatch):
    """Buyer build with an empty/invalid public key surfaces a clear LicenseError, not a crash."""
    import server.license as lic
    priv, _pub = _make_keypair()
    monkeypatch.setenv("TRADEBOT_LICENSE_PRIVATE_KEY", priv)
    key = lic.mint_key(machine_id="ANY", days=30)
    monkeypatch.setattr(lic, "LICENSE_PUBLIC_KEY", "")
    monkeypatch.delenv("TRADEBOT_LICENSE_PUBLIC_KEY", raising=False)
    with pytest.raises(lic.LicenseError, match="verifier not configured"):
        lic.verify_key(key, machine_id="ANY")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_license_asymmetric.py -v`
Expected: FAIL — `mint_key()` currently requires a `secret` positional arg / `TypeError`, and there is no `LICENSE_PUBLIC_KEY`.

- [ ] **Step 3: Rewrite `server/license.py`**

Replace the entire contents of `server/license.py` with:

```python
"""License key generation and verification for TradeBot.

Asymmetric (Ed25519): the OWNER instance signs keys with a private key
(env TRADEBOT_LICENSE_PRIVATE_KEY); every build verifies with a public key
baked in as LICENSE_PUBLIC_KEY (overridable via env TRADEBOT_LICENSE_PUBLIC_KEY).
A buyer build has only the public key: it can verify but cannot mint.
"""
import base64
import hashlib
import json
import os
import platform
import time
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

MACHINE_ANY = "ANY"

# Public verification key (base64 of the 32-byte raw Ed25519 public key).
# Generated by scripts/gen_license_keys.py and pasted here. The matching private
# key lives ONLY on the owner instance, never in source. Overridable via env for
# testing/rotation. Empty by default until the owner runs the generator.
LICENSE_PUBLIC_KEY = ""

# In-process cache: once valid, skip re-verification for 1 hour
_cache: dict = {}
_CACHE_TTL = 3600  # seconds


class LicenseError(Exception):
    pass


def get_machine_id() -> str:
    raw = f"{platform.node()}|{uuid.getnode()}|{platform.machine()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _load_private_key() -> Ed25519PrivateKey:
    raw_b64 = os.environ.get("TRADEBOT_LICENSE_PRIVATE_KEY", "").strip()
    if not raw_b64:
        raise RuntimeError(
            "TRADEBOT_LICENSE_PRIVATE_KEY is not set. Minting requires the owner "
            "private key. Generate one with: python scripts/gen_license_keys.py"
        )
    try:
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw_b64))
    except Exception as e:
        raise RuntimeError(f"TRADEBOT_LICENSE_PRIVATE_KEY is invalid: {e}")


def _load_public_key() -> Ed25519PublicKey:
    raw_b64 = (os.environ.get("TRADEBOT_LICENSE_PUBLIC_KEY", "").strip()
               or LICENSE_PUBLIC_KEY.strip())
    if not raw_b64:
        raise LicenseError("invalid: verifier not configured")
    try:
        return Ed25519PublicKey.from_public_bytes(base64.b64decode(raw_b64))
    except Exception:
        raise LicenseError("invalid: verifier not configured")


def mint_key(machine_id: str, days: int) -> str:
    """Sign a license key with the owner private key. Raises RuntimeError on buyer builds."""
    priv = _load_private_key()
    expiry = int(time.time()) + days * 86400
    payload = json.dumps({"m": machine_id, "exp": expiry}, separators=(",", ":"))
    sig = priv.sign(payload.encode())
    bundle = json.dumps(
        {"p": payload, "s": base64.b64encode(sig).decode()},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(bundle.encode()).decode()


def verify_key(key: str, machine_id: str | None = None) -> dict:
    """Verify a license key with the public key, then check expiry and machine binding."""
    pub = _load_public_key()
    try:
        bundle = json.loads(base64.urlsafe_b64decode(key.encode()))
        payload_str = bundle["p"]
        sig = base64.b64decode(bundle["s"])
    except Exception:
        raise LicenseError("invalid: key is malformed")

    try:
        pub.verify(sig, payload_str.encode())
    except InvalidSignature:
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
        result = verify_key(key)
        result["reason"] = ""
        # Cache valid result for 1 hour
        _cache = {**result, "expires_at": now + _CACHE_TTL}
        return result
    except (LicenseError, RuntimeError) as e:
        _cache = {}
        return {"valid": False, "reason": str(e), "days_remaining": 0}


def invalidate_cache() -> None:
    """Call after storing a new license key so the next request re-verifies."""
    global _cache
    _cache = {}
```

Note the removals: `_get_seller_secret()`, `_read_env_secret()`, `hmac`/`hashlib.sha256`-for-signing (hashlib stays for `get_machine_id`).

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_license_asymmetric.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add server/license.py tests/test_license_asymmetric.py
git commit -m "feat: switch licensing to asymmetric Ed25519 (verify-only public key in builds)"
```

---

## Task 2: Keypair generator CLI

**Files:**
- Create: `scripts/gen_license_keys.py`

This is a one-off operator tool; test it by running it (no pytest needed, but verify output shape).

- [ ] **Step 1: Create the script**

Create `scripts/gen_license_keys.py`:

```python
"""Generate an Ed25519 license-signing keypair for TradeBot (owner use only).

Run once on the owner's machine:

    python scripts/gen_license_keys.py

- PRIVATE key  -> paste into your owner .env as TRADEBOT_LICENSE_PRIVATE_KEY
                  (never commit it, never ship it to buyers).
- PUBLIC key   -> paste into server/license.py as the LICENSE_PUBLIC_KEY constant
                  (this is safe to ship — it can only verify, not mint).
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> None:
    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    priv_b64 = base64.b64encode(priv_raw).decode()
    pub_b64 = base64.b64encode(pub_raw).decode()

    print("=" * 70)
    print("TradeBot license keypair generated. Keep the PRIVATE key secret.")
    print("=" * 70)
    print()
    print("1) Owner .env (never commit / ship):")
    print(f"   TRADEBOT_LICENSE_PRIVATE_KEY={priv_b64}")
    print()
    print("2) server/license.py constant (safe to ship in builds):")
    print(f'   LICENSE_PUBLIC_KEY = "{pub_b64}"')
    print()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it to verify output**

Run: `python scripts/gen_license_keys.py`
Expected: prints a `TRADEBOT_LICENSE_PRIVATE_KEY=...` line and a `LICENSE_PUBLIC_KEY = "..."` line, both base64. (Do NOT paste this generated key anywhere — the real keypair is generated by the human operator, per the spec. This run only verifies the script works.)

- [ ] **Step 3: Commit**

```bash
git add scripts/gen_license_keys.py
git commit -m "feat: add gen_license_keys.py keypair generator CLI"
```

---

## Task 3: Update `lemon.py` minting caller

**Files:**
- Modify: `server/lemon.py` (the import and `mint_key(...)` call inside the auto-issue function — found at file-relative lines: `from server.license import mint_key, _get_seller_secret` and `license_key = mint_key(_get_seller_secret(), machine_id="ANY", days=days)`)

- [ ] **Step 1: Update the import**

In `server/lemon.py`, change:

```python
    from server.license import mint_key, _get_seller_secret
```
to:
```python
    from server.license import mint_key
```

- [ ] **Step 2: Update the mint call**

In `server/lemon.py`, change:

```python
    license_key = mint_key(_get_seller_secret(), machine_id="ANY", days=days)
```
to:
```python
    license_key = mint_key(machine_id="ANY", days=days)
```

- [ ] **Step 3: Verify lemon.py imports cleanly**

Run: `python -c "import server.lemon"`
Expected: no error (no `ImportError` for `_get_seller_secret`).

- [ ] **Step 4: Commit**

```bash
git add server/lemon.py
git commit -m "refactor: update lemon webhook to asymmetric mint_key signature"
```

---

## Task 4: Update `main.py` license caller + comment

**Files:**
- Modify: `server/main.py` — line 9 comment; the `/api/license/activate` import + call (around lines 416, 419)

- [ ] **Step 1: Update the line-9 comment**

In `server/main.py`, change:

```python
# Load .env before any module reads os.environ (e.g. DB_SECRET_KEY, TRADEBOT_LICENSE_SECRET)
```
to:
```python
# Load .env before any module reads os.environ (e.g. DB_SECRET_KEY, TRADEBOT_LICENSE_PRIVATE_KEY)
```

- [ ] **Step 2: Update the activate import**

In `server/main.py` `license_activate`, change:

```python
    from .license import verify_key, _get_seller_secret, LicenseError, invalidate_cache
```
to:
```python
    from .license import verify_key, LicenseError, invalidate_cache
```

- [ ] **Step 3: Update the verify call**

In `server/main.py` `license_activate`, change:

```python
        result = verify_key(body.key, _get_seller_secret())
```
to:
```python
        result = verify_key(body.key)
```

- [ ] **Step 4: Verify main.py imports cleanly**

Run: `python -c "import server.main"`
Expected: no error.

- [ ] **Step 5: Commit**

```bash
git add server/main.py
git commit -m "refactor: update license activate to asymmetric verify_key signature"
```

---

## Task 5: Migrate the test fixtures to the keypair helper

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/test_license.py`
- Modify: `tests/test_license_api.py`
- Modify: `tests/test_export.py`
- Modify: `tests/test_lemon.py`

This unblocks the whole suite. The conftest sets a throwaway keypair at module top-level (conftest imports before any test module), exposes `mint_test_key()`, and patches `license.LICENSE_PUBLIC_KEY`.

- [ ] **Step 1: Rewrite the top of `tests/conftest.py`**

In `tests/conftest.py`, replace lines 1-8 (imports + the `TRADEBOT_LICENSE_SECRET` setdefault):

```python
import os
import pytest
from cryptography.fernet import Fernet
from unittest.mock import patch
from fastapi.testclient import TestClient

# Ensure license secret is set before any server module imports it
os.environ.setdefault("TRADEBOT_LICENSE_SECRET", "test-secret-32-chars-seller-key!!")
```

with:

```python
import base64
import os
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from unittest.mock import patch
from fastapi.testclient import TestClient

# ── Test license keypair ──────────────────────────────────────────────────────
# Generate a throwaway Ed25519 keypair ONCE at import time (conftest is imported
# before any test module). The private key signs test keys via mint_test_key();
# the public key is injected into server.license so verification succeeds.
_test_priv = Ed25519PrivateKey.generate()
_TEST_PRIVATE_B64 = base64.b64encode(
    _test_priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
).decode()
_TEST_PUBLIC_B64 = base64.b64encode(
    _test_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
).decode()
os.environ["TRADEBOT_LICENSE_PRIVATE_KEY"] = _TEST_PRIVATE_B64
os.environ["TRADEBOT_LICENSE_PUBLIC_KEY"] = _TEST_PUBLIC_B64


def mint_test_key(machine_id: str = "ANY", days: int = 365) -> str:
    """Mint a license key signed by the test keypair. Importable by any test module."""
    import server.license as lic
    return lic.mint_key(machine_id=machine_id, days=days)
```

(Setting `TRADEBOT_LICENSE_PUBLIC_KEY` in env means `license._load_public_key()` picks it up without patching the constant, so `check_stored_license()` works in the running app too.)

- [ ] **Step 2: Update the `client` fixture license setup in `tests/conftest.py`**

In `tests/conftest.py`, replace:

```python
            # Store a valid license key so _require_auth license check passes
            import server.license as lic_mod
            key = lic_mod.mint_key(
                os.environ["TRADEBOT_LICENSE_SECRET"], "ANY", 365
            )
            db_mod.set_license_key(key)
            yield tc
```

with:

```python
            # Store a valid license key so _require_auth license check passes
            db_mod.set_license_key(mint_test_key())
            yield tc
```

- [ ] **Step 3: Rewrite `tests/test_license.py`**

Replace the entire contents of `tests/test_license.py` with:

```python
# tests/test_license.py
import pytest
from server.license import get_machine_id, verify_key, LicenseError
from conftest import mint_test_key


def test_machine_id_is_stable():
    assert get_machine_id() == get_machine_id()
    assert len(get_machine_id()) == 64  # sha256 hex


def test_mint_and_verify_valid_key():
    key = mint_test_key(machine_id="ANY", days=30)
    result = verify_key(key, machine_id="ANY")
    assert result["valid"] is True
    assert result["days_remaining"] > 0


def test_expired_key_raises():
    key = mint_test_key(machine_id="ANY", days=-1)
    with pytest.raises(LicenseError, match="expired"):
        verify_key(key, machine_id="ANY")


def test_wrong_machine_raises():
    key = mint_test_key(machine_id="MACHINE-A", days=30)
    with pytest.raises(LicenseError, match="machine"):
        verify_key(key, machine_id="MACHINE-B")


def test_tampered_key_raises():
    key = mint_test_key(machine_id="ANY", days=30)
    bad = key[:-4] + "XXXX"
    with pytest.raises(LicenseError, match="invalid"):
        verify_key(bad, machine_id="ANY")


def test_universal_key():
    key = mint_test_key(machine_id="ANY", days=365)
    result = verify_key(key, machine_id="SOME-REAL-MACHINE")
    assert result["valid"] is True


def test_store_and_retrieve_license(tmp_path, monkeypatch):
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    db_mod.init_db()
    from server.db import set_license_key, get_license_key
    assert get_license_key() == ""
    set_license_key("MYKEY123")
    assert get_license_key() == "MYKEY123"
```

- [ ] **Step 4: Update `tests/test_license_api.py`**

In `tests/test_license_api.py`, change lines 1-3:

```python
# tests/test_license_api.py
import os
os.environ.setdefault("TRADEBOT_LICENSE_SECRET", "test-secret-32-chars-seller-key!!")
```
to:
```python
# tests/test_license_api.py
import os
from conftest import mint_test_key
```

Change the `test_license_status_after_valid_key` body (lines 37-42):

```python
def test_license_status_after_valid_key(client):
    import server.license as lic_mod
    key = lic_mod.mint_key("test-secret-32-chars-seller-key!!", "ANY", 30)
    r = client.post("/api/license/activate", json={"key": key})
    assert r.status_code == 200
    assert r.json()["valid"] is True
```
to:
```python
def test_license_status_after_valid_key(client):
    key = mint_test_key(machine_id="ANY", days=30)
    r = client.post("/api/license/activate", json={"key": key})
    assert r.status_code == 200
    assert r.json()["valid"] is True
```

Change the `test_delete_license_deactivates` minting (lines 69-71):

```python
    import server.license as lic_mod
    key = lic_mod.mint_key("test-secret-32-chars-seller-key!!", "ANY", 30)
    db_mod.set_license_key(key)
```
to:
```python
    db_mod.set_license_key(mint_test_key(machine_id="ANY", days=30))
```

- [ ] **Step 5: Update `tests/test_export.py`**

In `tests/test_export.py`, remove line 2:

```python
os.environ.setdefault("TRADEBOT_LICENSE_SECRET", "test-secret-32-chars-seller-key!!")
```

(The conftest keypair now covers the license check. If `import os` becomes unused after this removal, leave it — other lines may use it; only delete the `setdefault` line. Verify by reading the surrounding lines before editing.)

- [ ] **Step 6: Update `tests/test_lemon.py`**

In `tests/test_lemon.py`, change line 152:

```python
    monkeypatch.setenv("TRADEBOT_LICENSE_SECRET", "test-seller-secret-32-chars-long!")
```
to:
```python
    # License signing key is provided by the conftest test keypair (TRADEBOT_LICENSE_PRIVATE_KEY).
```

(Leave `SIGNING_SECRET` / `LEMON_SQUEEZY_SIGNING_SECRET` untouched — that is the Lemon webhook secret, unrelated to license signing.)

- [ ] **Step 7: Run the full affected suite**

Run: `python -m pytest tests/test_license.py tests/test_license_api.py tests/test_export.py tests/test_lemon.py tests/test_license_asymmetric.py -v`
Expected: PASS. (If `test_setup_complete_replay_returns_409` or other unrelated pre-existing failures appear in a broader run, they are out of scope — this command targets only the affected files.)

- [ ] **Step 8: Commit**

```bash
git add tests/conftest.py tests/test_license.py tests/test_license_api.py tests/test_export.py tests/test_lemon.py
git commit -m "test: migrate license tests to asymmetric keypair helper"
```

---

## Task 6: Owner-mode helpers + gate `/api/admin/*` + `/api/app-info`

**Files:**
- Modify: `server/main.py` — add `owner_mode_enabled()` and `_require_owner()` near `_require_auth` (after line 98); add `/api/app-info`; swap `_require_auth(request)` → `_require_owner(request)` in the six admin endpoints (`admin_list_licenses`, `admin_revoke_license`, `admin_resend_license`, `admin_export_licenses`, `admin_get_lemon_config`, `admin_patch_lemon_config`).
- Test: `tests/test_owner_mode.py` (created here)

- [ ] **Step 1: Write the failing test**

Create `tests/test_owner_mode.py`:

```python
# tests/test_owner_mode.py
"""Owner-mode gate: /api/admin/* returns 403 unless TRADEBOT_OWNER_MODE is set."""
import pytest


def test_owner_mode_enabled_truthy(monkeypatch):
    import server.main as main
    for val in ("1", "true", "yes", "TRUE", "Yes"):
        monkeypatch.setenv("TRADEBOT_OWNER_MODE", val)
        assert main.owner_mode_enabled() is True


def test_owner_mode_enabled_falsy(monkeypatch):
    import server.main as main
    monkeypatch.delenv("TRADEBOT_OWNER_MODE", raising=False)
    assert main.owner_mode_enabled() is False
    for val in ("", "0", "no", "off", "false"):
        monkeypatch.setenv("TRADEBOT_OWNER_MODE", val)
        assert main.owner_mode_enabled() is False


def test_admin_licenses_403_when_not_owner(client, monkeypatch):
    monkeypatch.delenv("TRADEBOT_OWNER_MODE", raising=False)
    r = client.get("/api/admin/licenses")
    assert r.status_code == 403


def test_admin_licenses_200_when_owner(client, monkeypatch):
    monkeypatch.setenv("TRADEBOT_OWNER_MODE", "1")
    r = client.get("/api/admin/licenses")
    assert r.status_code == 200
    assert "licenses" in r.json()


def test_admin_export_403_when_not_owner(client, monkeypatch):
    monkeypatch.delenv("TRADEBOT_OWNER_MODE", raising=False)
    r = client.get("/api/admin/licenses/export")
    assert r.status_code == 403


def test_lemon_config_403_when_not_owner(client, monkeypatch):
    monkeypatch.delenv("TRADEBOT_OWNER_MODE", raising=False)
    r = client.get("/api/admin/lemon-config")
    assert r.status_code == 403


def test_app_info_reports_owner_mode(client, monkeypatch):
    monkeypatch.setenv("TRADEBOT_OWNER_MODE", "1")
    r = client.get("/api/app-info")
    assert r.status_code == 200
    assert r.json()["owner_mode"] is True

    monkeypatch.delenv("TRADEBOT_OWNER_MODE", raising=False)
    r = client.get("/api/app-info")
    assert r.status_code == 200
    assert r.json()["owner_mode"] is False
```

Note: the `client` fixture (from conftest) runs with `auth.setup_complete()` false in most tests because no password is set, so `_require_auth` passes through; the license check passes via the stored test key. The owner gate is the only thing under test here.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_owner_mode.py -v`
Expected: FAIL — `owner_mode_enabled` does not exist; `/api/app-info` is 404; admin endpoints return 200 (no gate yet).

- [ ] **Step 3: Add the helpers in `server/main.py`**

In `server/main.py`, immediately after `_require_auth` ends (after line 98, the blank line following the function), add:

```python
def owner_mode_enabled() -> bool:
    """True only on the seller's own instance (env TRADEBOT_OWNER_MODE set)."""
    return os.environ.get("TRADEBOT_OWNER_MODE", "").strip().lower() in ("1", "true", "yes")


def _require_owner(request: Request):
    """Require auth AND owner mode. Buyers get 403 on seller-only endpoints."""
    _require_auth(request)
    if not owner_mode_enabled():
        raise HTTPException(403, "owner only")
```

- [ ] **Step 4: Add the `/api/app-info` endpoint**

In `server/main.py`, immediately after the `health()` function (after line 356), add:

```python
@app.get("/api/app-info")
def app_info(request: Request):
    """Authenticated app metadata. Tells the UI whether to show owner-only tooling."""
    _require_auth(request)
    return {"owner_mode": owner_mode_enabled()}
```

- [ ] **Step 5: Gate the six admin endpoints**

In `server/main.py`, in each of these six functions replace the `_require_auth(request)` line with `_require_owner(request)`:
- `admin_list_licenses` (line 460)
- `admin_revoke_license` (line 468)
- `admin_resend_license` (line 478)
- `admin_export_licenses` (line 500)
- `admin_get_lemon_config` (line 522)
- `admin_patch_lemon_config` (line 531)

Each change is exactly:
```python
    _require_auth(request)
```
to:
```python
    _require_owner(request)
```

Since this line is identical in six places, edit each function individually (match on the surrounding function body to keep edits unique).

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest tests/test_owner_mode.py -v`
Expected: PASS (7 tests).

- [ ] **Step 7: Run the license-API suite to confirm no regression**

Run: `python -m pytest tests/test_license_api.py tests/test_export.py tests/test_lemon.py -v`
Expected: PASS. (Note: `test_export.py` hits `/api/admin/licenses/export`. If it now expects 200, it must set owner mode. Check `test_export.py` — if it asserts a successful export, add `monkeypatch.setenv("TRADEBOT_OWNER_MODE", "1")` to that test's setup. Read the test first; update only if it exercises an admin endpoint and expects success.)

- [ ] **Step 8: Fix `test_export.py` owner-mode if needed**

If Step 7 showed `test_export.py` failing with 403, add owner mode to its client/test setup. Read the failing test, then before the export request add:
```python
    monkeypatch.setenv("TRADEBOT_OWNER_MODE", "1")
```
Re-run: `python -m pytest tests/test_export.py -v` → Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add server/main.py tests/test_owner_mode.py tests/test_export.py
git commit -m "feat: owner-mode gate on /api/admin/* + /api/app-info endpoint"
```

---

## Task 7: Hide License Management panel in the buyer UI

**Files:**
- Modify: `server/static/settings.html` — the `#license-mgmt-section` card (line 399) starts hidden.
- Modify: `server/static/app.js` — `initSettings` (around line 4825) fetches `/api/app-info` and reveals the card if owner.

There is no automated frontend test harness; verify manually with the running server + the provided password (`TradeBot123`).

- [ ] **Step 1: Hide the card by default in `settings.html`**

In `server/static/settings.html` line 399, change:

```html
    <div class="card" id="license-mgmt-section">
```
to:
```html
    <div class="card" id="license-mgmt-section" style="display:none;">
```

- [ ] **Step 2: Reveal the card for owners in `app.js` `initSettings`**

First read `server/static/app.js` around `initSettings` (line ~4825) to find the right insertion point and the existing `api()` helper usage. Then add, near the start of `initSettings` (after any existing setup, before it returns):

```javascript
  // Owner-only: reveal the License Management panel only on the seller's instance.
  // Buyers get 403 on /api/admin/* and never see this card.
  try {
    const info = await api('/api/app-info');
    if (info && info.owner_mode) {
      const sec = document.getElementById('license-mgmt-section');
      if (sec) sec.style.display = '';
    }
  } catch (e) {
    // Non-owner or not authed yet — leave the panel hidden.
  }
```

If `initSettings` is not already `async`, make it `async` (change `function initSettings(` to `async function initSettings(`). Verify the function's callers don't depend on a synchronous return value — `initSettings` is an init hook, so an awaited/ignored promise is fine.

- [ ] **Step 3: Manual verification — buyer view (owner mode OFF)**

Start the server WITHOUT owner mode:
```bash
# Ensure TRADEBOT_OWNER_MODE is not set in the environment / .env
python -m uvicorn server.main:app --port 8000
```
Log in with password `TradeBot123`, open Settings. Expected: the License Management card is NOT visible. Confirm `GET /api/admin/licenses` returns 403 (e.g. via browser devtools or `curl` with the session cookie).

- [ ] **Step 4: Manual verification — owner view (owner mode ON)**

Stop the server. Set owner mode and restart:
```powershell
$env:TRADEBOT_OWNER_MODE = "1"
python -m uvicorn server.main:app --port 8000
```
Reload Settings. Expected: the License Management card IS visible; clicking its header expands it and `loadLicenses`/`loadLemonConfig` run without 403.

- [ ] **Step 5: Commit**

```bash
git add server/static/settings.html server/static/app.js
git commit -m "feat: hide License Management panel unless owner mode (UI gate)"
```

---

## Task 8: Update `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Read the current file**

Read `.env.example` to locate the existing `TRADEBOT_LICENSE_SECRET=` line and a sensible insertion point.

- [ ] **Step 2: Remove the obsolete secret line and add the new vars**

Remove the line:
```
TRADEBOT_LICENSE_SECRET=...
```

Add (near the license/seller config, or at the end if none):
```
# ── Owner / seller instance only ─────────────────────────────────────────────
# Set to 1 ONLY on the seller's own machine to unlock License Management tools.
# Buyer copies leave this unset.
# TRADEBOT_OWNER_MODE=

# Ed25519 license signing key — OWNER INSTANCE ONLY. Generate with:
#   python scripts/gen_license_keys.py
# Put the PRIVATE key here (never ship it). The PUBLIC key is baked into the app
# as LICENSE_PUBLIC_KEY in server/license.py.
# TRADEBOT_LICENSE_PRIVATE_KEY=
```

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs: update .env.example for owner mode + asymmetric license keys"
```

---

## Task 9: Full suite + final review

- [ ] **Step 1: Run the entire test suite**

Run: `python -m pytest -v`
Expected: All license/owner/lemon/export tests PASS. Pre-existing unrelated failures (e.g. `test_setup_complete_replay_returns_409`, caused by the uncommitted 8-char password-minimum change) may remain — confirm each remaining failure is unrelated to this work by checking it fails the same way on a stash of your changes. Do NOT fix out-of-scope failures here.

- [ ] **Step 2: Grep for leftover references to the old secret**

Run:
```bash
git grep -n "TRADEBOT_LICENSE_SECRET\|_get_seller_secret\|_read_env_secret"
```
Expected: NO results in `server/` or `tests/` (only this plan/spec may mention them historically). If any code reference remains, fix it.

- [ ] **Step 3: Final code review**

Dispatch a code reviewer (superpowers:requesting-code-review) over the branch diff:
```bash
BASE_SHA=$(git merge-base HEAD master)
HEAD_SHA=$(git rev-parse HEAD)
```
Address Critical/Important findings.

- [ ] **Step 4: Finish the branch**

Use superpowers:finishing-a-development-branch to merge or open a PR.

---

## Self-review notes (verified against the spec)

- **Part A (asymmetric):** Tasks 1–5 cover `license.py` rewrite, generator CLI, both callers (`lemon.py`, `main.py`), and all five affected test files. ✔
- **Part B (owner mode):** Task 6 covers `owner_mode_enabled()`, `_require_owner()`, `/api/app-info`, and the gate. Spec named four `/api/admin/licenses/*` endpoints; investigation found **two additional** seller-only endpoints (`/api/admin/lemon-config` GET+PATCH) — both are gated here. ✔ (Documented deviation from spec, in buyers' favor.)
- **Frontend:** Task 7 hides `#license-mgmt-section`; the inline `loadLicenses`/`exportLicenses`/`toggleLicenseMgmt`/`loadLemonConfig` functions live in `settings.html`'s `<script>` (not app.js) and are never invoked while the card is hidden. ✔
- **Config/docs:** Task 8 updates `.env.example`. ✔
- **Honest limitation** (buyer could flip the flag locally) is inherent and documented in the spec; no task can "fix" it — Part A is the real protection. ✔
- **No placeholders:** every code step shows complete code. **Type/signature consistency:** `mint_key(machine_id, days)`, `verify_key(key, machine_id=None)`, `mint_test_key(machine_id="ANY", days=365)`, `owner_mode_enabled()`, `_require_owner(request)` used identically across all tasks. ✔
