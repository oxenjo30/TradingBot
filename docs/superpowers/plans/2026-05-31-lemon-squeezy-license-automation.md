# Lemon Squeezy License Automation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a Lemon Squeezy payment confirms, TradeBot auto-generates a license key, stores it, and emails the buyer — with a seller admin panel to view/revoke/resend keys.

**Architecture:** New `server/lemon.py` handles webhook verification + key generation + email dispatch. `server/db.py` gains an `issued_licenses` table. Five new routes in `server/main.py`. Admin UI added to `server/static/settings.html`.

**Tech Stack:** FastAPI, SQLite (existing), Python hmac/hashlib, existing SMTP notifications, existing `mint_key()` in `server/license.py`

---

### Task 1: Add `issued_licenses` table to DB + query methods

**Files:**
- Modify: `server/db.py`
- Test: `tests/test_lemon.py` (create new)

- [ ] **Step 1: Write failing tests for DB methods**

Create `tests/test_lemon.py`:

```python
import pytest
import sqlite3
from pathlib import Path


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    db_mod.init_db()
    return db_mod


def test_add_issued_license(tmp_db):
    tmp_db.add_issued_license("order_001", "buyer@test.com", "KEY-ABC")
    rows = tmp_db.list_issued_licenses()
    assert len(rows) == 1
    assert rows[0]["order_id"] == "order_001"
    assert rows[0]["buyer_email"] == "buyer@test.com"
    assert rows[0]["license_key"] == "KEY-ABC"
    assert rows[0]["revoked"] == 0


def test_duplicate_order_id_ignored(tmp_db):
    tmp_db.add_issued_license("order_001", "buyer@test.com", "KEY-ABC")
    tmp_db.add_issued_license("order_001", "buyer@test.com", "KEY-ABC")  # duplicate
    assert len(tmp_db.list_issued_licenses()) == 1


def test_revoke_license(tmp_db):
    tmp_db.add_issued_license("order_002", "buyer2@test.com", "KEY-DEF")
    row = tmp_db.list_issued_licenses()[0]
    tmp_db.revoke_issued_license(row["id"])
    updated = tmp_db.list_issued_licenses()[0]
    assert updated["revoked"] == 1


def test_list_issued_licenses_search(tmp_db):
    tmp_db.add_issued_license("order_003", "alice@test.com", "KEY-GHI")
    tmp_db.add_issued_license("order_004", "bob@test.com", "KEY-JKL")
    results = tmp_db.list_issued_licenses(search="alice")
    assert len(results) == 1
    assert results[0]["buyer_email"] == "alice@test.com"


def test_get_issued_license_by_id(tmp_db):
    tmp_db.add_issued_license("order_005", "carol@test.com", "KEY-MNO")
    row = tmp_db.list_issued_licenses()[0]
    fetched = tmp_db.get_issued_license(row["id"])
    assert fetched["buyer_email"] == "carol@test.com"


def test_update_resent_at(tmp_db):
    tmp_db.add_issued_license("order_006", "dave@test.com", "KEY-PQR")
    row = tmp_db.list_issued_licenses()[0]
    tmp_db.update_resent_at(row["id"])
    updated = tmp_db.get_issued_license(row["id"])
    assert updated["resent_at"] is not None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd C:\TradeBot && .venv\Scripts\pytest tests/test_lemon.py -v 2>&1 | head -30
```
Expected: `AttributeError: module 'server.db' has no attribute 'add_issued_license'`

- [ ] **Step 3: Add `issued_licenses` table to `server/db.py` schema**

Find the `SCHEMA` string (the multi-line SQL at the top of db.py). Add after the last `CREATE TABLE` block:

```python
"""
CREATE TABLE IF NOT EXISTS issued_licenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    TEXT UNIQUE NOT NULL,
    buyer_email TEXT NOT NULL,
    license_key TEXT NOT NULL,
    issued_at   TEXT NOT NULL DEFAULT (datetime('now')),
    revoked     INTEGER NOT NULL DEFAULT 0,
    resent_at   TEXT
);
"""
```

- [ ] **Step 4: Add 5 query methods to `server/db.py`**

Add after the `set_license_key` function (around line 430):

```python
# ── Issued licenses (Lemon Squeezy automation) ────────────────────────────────

def add_issued_license(order_id: str, buyer_email: str, license_key: str) -> None:
    """Insert a new issued license. Silently ignores duplicate order_id."""
    with get_conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO issued_licenses (order_id, buyer_email, license_key) "
            "VALUES (?, ?, ?)",
            (order_id, buyer_email, license_key),
        )


def list_issued_licenses(search: str = "", page: int = 1,
                         per_page: int = 20) -> list[dict]:
    offset = (page - 1) * per_page
    with get_conn() as c:
        if search:
            rows = c.execute(
                "SELECT * FROM issued_licenses WHERE buyer_email LIKE ? "
                "ORDER BY issued_at DESC LIMIT ? OFFSET ?",
                (f"%{search}%", per_page, offset),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM issued_licenses ORDER BY issued_at DESC "
                "LIMIT ? OFFSET ?",
                (per_page, offset),
            ).fetchall()
    return [dict(r) for r in rows]


def count_issued_licenses(search: str = "") -> int:
    with get_conn() as c:
        if search:
            row = c.execute(
                "SELECT COUNT(*) FROM issued_licenses WHERE buyer_email LIKE ?",
                (f"%{search}%",),
            ).fetchone()
        else:
            row = c.execute("SELECT COUNT(*) FROM issued_licenses").fetchone()
    return row[0]


def get_issued_license(license_id: int) -> dict | None:
    with get_conn() as c:
        row = c.execute(
            "SELECT * FROM issued_licenses WHERE id=?", (license_id,)
        ).fetchone()
    return dict(row) if row else None


def revoke_issued_license(license_id: int) -> None:
    with get_conn() as c:
        c.execute(
            "UPDATE issued_licenses SET revoked=1 WHERE id=?", (license_id,)
        )


def update_resent_at(license_id: int) -> None:
    with get_conn() as c:
        c.execute(
            "UPDATE issued_licenses SET resent_at=datetime('now') WHERE id=?",
            (license_id,),
        )
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
.venv\Scripts\pytest tests/test_lemon.py -v 2>&1 | head -40
```
Expected: all 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/db.py tests/test_lemon.py
git commit -m "feat: add issued_licenses table and query methods to db"
```

---

### Task 2: Create `server/lemon.py` — webhook verification + key generation + email

**Files:**
- Create: `server/lemon.py`
- Test: `tests/test_lemon.py` (extend)

- [ ] **Step 1: Write failing tests for lemon.py**

Append to `tests/test_lemon.py`:

```python
import hashlib
import hmac
import json
import os


SIGNING_SECRET = "test-signing-secret-abc123"


def _make_signature(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature_valid():
    from server.lemon import verify_signature
    body = b'{"meta":{"event_name":"order_created"}}'
    sig = _make_signature(body, SIGNING_SECRET)
    # Should not raise
    verify_signature(body, sig, SIGNING_SECRET)


def test_verify_signature_invalid():
    from server.lemon import verify_signature, LemonWebhookError
    body = b'{"meta":{"event_name":"order_created"}}'
    with pytest.raises(LemonWebhookError, match="signature"):
        verify_signature(body, "badsignature", SIGNING_SECRET)


def test_extract_order_data_valid():
    from server.lemon import extract_order_data
    payload = {
        "meta": {"event_name": "order_created"},
        "data": {
            "id": "ls_order_123",
            "attributes": {
                "user_email": "buyer@example.com",
                "status": "paid",
            }
        }
    }
    order_id, email = extract_order_data(payload)
    assert order_id == "ls_order_123"
    assert email == "buyer@example.com"


def test_extract_order_data_not_paid():
    from server.lemon import extract_order_data, LemonWebhookError
    payload = {
        "meta": {"event_name": "order_created"},
        "data": {
            "id": "ls_order_456",
            "attributes": {
                "user_email": "buyer@example.com",
                "status": "pending",
            }
        }
    }
    with pytest.raises(LemonWebhookError, match="not paid"):
        extract_order_data(payload)


def test_build_license_email_html():
    from server.lemon import build_license_email_html
    html = build_license_email_html(
        buyer_email="buyer@example.com",
        license_key="TB-TESTKEY-12345",
        download_url="https://lemonsqueezy.com/download/abc",
    )
    assert "TB-TESTKEY-12345" in html
    assert "https://lemonsqueezy.com/download/abc" in html
    assert "buyer@example.com" in html
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv\Scripts\pytest tests/test_lemon.py::test_verify_signature_valid -v
```
Expected: `ModuleNotFoundError: No module named 'server.lemon'`

- [ ] **Step 3: Create `server/lemon.py`**

```python
"""Lemon Squeezy webhook handler — verifies payment, issues license key, emails buyer."""
import hashlib
import hmac
import logging
import os

log = logging.getLogger("lemon")


class LemonWebhookError(Exception):
    pass


def verify_signature(body: bytes, signature: str, secret: str) -> None:
    """Raise LemonWebhookError if the HMAC-SHA256 signature does not match."""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise LemonWebhookError("invalid signature")


def extract_order_data(payload: dict) -> tuple[str, str]:
    """Return (order_id, buyer_email) from a Lemon Squeezy webhook payload.
    Raises LemonWebhookError if the order is not paid or data is missing.
    """
    try:
        data = payload["data"]
        attrs = data["attributes"]
        order_id = str(data["id"])
        buyer_email = attrs["user_email"]
        status = attrs.get("status", "")
    except (KeyError, TypeError) as e:
        raise LemonWebhookError(f"malformed payload: {e}")

    if status != "paid":
        raise LemonWebhookError(f"order not paid (status={status})")

    if not buyer_email:
        raise LemonWebhookError("missing buyer email in payload")

    return order_id, buyer_email


def build_license_email_html(buyer_email: str, license_key: str,
                              download_url: str) -> str:
    """Return an HTML email body for license delivery."""
    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #F1F5F9; margin: 0; padding: 32px; color: #0F172A; }}
  .card {{ background: #FFFFFF; border-radius: 12px; max-width: 560px;
           margin: 0 auto; padding: 40px; box-shadow: 0 2px 8px rgba(0,0,0,.08); }}
  .logo  {{ font-size: 22px; font-weight: 800; color: #3B82F6; margin-bottom: 8px; }}
  .title {{ font-size: 20px; font-weight: 700; margin-bottom: 6px; }}
  .sub   {{ color: #64748B; font-size: 14px; margin-bottom: 28px; }}
  .key-box {{ background: #0F172A; border-radius: 8px; padding: 16px 20px;
              font-family: 'Courier New', monospace; font-size: 15px;
              color: #93C5FD; letter-spacing: 1px; margin: 16px 0 24px;
              word-break: break-all; }}
  .btn {{ display: inline-block; background: #3B82F6; color: #fff;
          text-decoration: none; border-radius: 8px; padding: 12px 24px;
          font-weight: 600; font-size: 14px; margin-bottom: 28px; }}
  .steps {{ background: #F8FAFC; border-radius: 8px; padding: 20px;
            margin-bottom: 24px; }}
  .steps h3 {{ margin: 0 0 12px; font-size: 13px; text-transform: uppercase;
               letter-spacing: .05em; color: #64748B; }}
  .steps ol {{ margin: 0; padding-left: 20px; font-size: 13px;
               color: #334155; line-height: 2; }}
  .footer {{ font-size: 12px; color: #94A3B8; text-align: center;
             margin-top: 24px; }}
</style>
</head>
<body>
<div class="card">
  <div class="logo">TradeBot</div>
  <div class="title">Your License Key is Ready</div>
  <div class="sub">Thank you for your purchase, {buyer_email}</div>

  <p style="font-size:13px;color:#475569;margin-bottom:6px;">
    <strong>Your license key:</strong>
  </p>
  <div class="key-box">{license_key}</div>

  <a href="{download_url}" class="btn">&#8595; Download TradeBot</a>

  <div class="steps">
    <h3>Quick Start</h3>
    <ol>
      <li>Download and extract the zip file</li>
      <li>Double-click <strong>setup.bat</strong> to install</li>
      <li>Open <strong>http://localhost:8000</strong> in your browser</li>
      <li>Enter your license key above when prompted</li>
    </ol>
  </div>

  <p style="font-size:13px;color:#475569;">
    Need help? Refer to the <strong>TradeBot_Installation_Guide.pdf</strong>
    included in the download, or reply to this email.
  </p>

  <div class="footer">TradeBot &mdash; Automated Algorithmic Trading Platform</div>
</div>
</body>
</html>
"""


def process_webhook(body: bytes, signature: str) -> dict:
    """Full pipeline: verify → extract → mint key → store → email.

    Returns a dict with keys: order_id, buyer_email, license_key, emailed (bool).
    Raises LemonWebhookError on signature failure.
    Duplicate order_id is silently ignored (returns existing record info).
    """
    import json
    from server import db
    from server.license import mint_key, _get_seller_secret
    from server.notifications import send_email_direct

    signing_secret = os.environ.get("LEMON_SQUEEZY_SIGNING_SECRET", "")
    if not signing_secret:
        raise RuntimeError(
            "LEMON_SQUEEZY_SIGNING_SECRET is not set in .env"
        )

    verify_signature(body, signature, signing_secret)

    payload = json.loads(body)
    order_id, buyer_email = extract_order_data(payload)

    # Idempotency — if already issued, skip
    existing = db.list_issued_licenses(search=buyer_email)
    for row in existing:
        if row["order_id"] == order_id:
            log.info("duplicate order_id %s — skipping", order_id)
            return {
                "order_id": order_id,
                "buyer_email": buyer_email,
                "license_key": row["license_key"],
                "emailed": False,
                "duplicate": True,
            }

    # Generate license key
    days = int(os.environ.get("LICENSE_DURATION_DAYS", "36500"))
    license_key = mint_key(_get_seller_secret(), machine_id="ANY", days=days)

    # Store in DB
    db.add_issued_license(order_id, buyer_email, license_key)

    # Send email
    download_url = os.environ.get("LICENSE_DOWNLOAD_URL", "")
    html = build_license_email_html(buyer_email, license_key, download_url)
    emailed = False
    try:
        s = db.get_app_config
        smtp_host  = db.get_app_config("email_smtp", "")
        smtp_port  = int(db.get_app_config("email_port", "587"))
        smtp_user  = db.get_app_config("email_user", "")
        smtp_pass  = db.get_app_config("email_pass", "")
        if smtp_host and smtp_user and smtp_pass:
            send_email_direct(
                buyer_email, smtp_host, smtp_port, smtp_user, smtp_pass,
                "Your TradeBot License Key", html,
            )
            emailed = True
        else:
            log.warning("SMTP not configured — license stored but email not sent for %s",
                        buyer_email)
    except Exception as e:
        log.error("Failed to send license email to %s: %s", buyer_email, e)

    log.info("license issued: order=%s email=%s emailed=%s", order_id, buyer_email, emailed)
    return {
        "order_id": order_id,
        "buyer_email": buyer_email,
        "license_key": license_key,
        "emailed": emailed,
        "duplicate": False,
    }
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
.venv\Scripts\pytest tests/test_lemon.py -v 2>&1 | head -50
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/lemon.py tests/test_lemon.py
git commit -m "feat: add lemon.py webhook handler with signature verification and email"
```

---

### Task 3: Register routes in `server/main.py`

**Files:**
- Modify: `server/main.py`
- Test: `tests/test_lemon.py` (extend with route tests)

- [ ] **Step 1: Write failing route tests**

Append to `tests/test_lemon.py`:

```python
import hashlib
import hmac
import json
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    db_mod.init_db()
    monkeypatch.setenv("LEMON_SQUEEZY_SIGNING_SECRET", SIGNING_SECRET)
    monkeypatch.setenv("TRADEBOT_LICENSE_SECRET", "test-seller-secret-32-chars-long!")
    monkeypatch.setenv("LICENSE_DURATION_DAYS", "36500")
    monkeypatch.setenv("LICENSE_DOWNLOAD_URL", "https://lemonsqueezy.com/dl/test")
    from server.main import app
    return TestClient(app)


def _webhook_payload(order_id="ls_001", email="buyer@test.com", status="paid"):
    return json.dumps({
        "meta": {"event_name": "order_created"},
        "data": {
            "id": order_id,
            "attributes": {"user_email": email, "status": status}
        }
    }).encode()


def test_webhook_valid_signature(client):
    body = _webhook_payload()
    sig = _make_signature(body, SIGNING_SECRET)
    resp = client.post("/api/lemon/webhook",
                       content=body,
                       headers={"X-Signature": sig,
                                "Content-Type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["order_id"] == "ls_001"


def test_webhook_bad_signature(client):
    body = _webhook_payload()
    resp = client.post("/api/lemon/webhook",
                       content=body,
                       headers={"X-Signature": "badsig",
                                "Content-Type": "application/json"})
    assert resp.status_code == 401


def test_webhook_not_paid(client):
    body = _webhook_payload(status="pending")
    sig = _make_signature(body, SIGNING_SECRET)
    resp = client.post("/api/lemon/webhook",
                       content=body,
                       headers={"X-Signature": sig,
                                "Content-Type": "application/json"})
    assert resp.status_code == 200  # not paid = skip gracefully


def test_webhook_duplicate_idempotent(client):
    body = _webhook_payload()
    sig = _make_signature(body, SIGNING_SECRET)
    client.post("/api/lemon/webhook", content=body,
                headers={"X-Signature": sig, "Content-Type": "application/json"})
    resp2 = client.post("/api/lemon/webhook", content=body,
                        headers={"X-Signature": sig, "Content-Type": "application/json"})
    assert resp2.status_code == 200
    assert resp2.json()["duplicate"] is True
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv\Scripts\pytest tests/test_lemon.py::test_webhook_valid_signature -v
```
Expected: `404 Not Found` (route doesn't exist yet)

- [ ] **Step 3: Add routes to `server/main.py`**

Find the section with other `@app.post` routes (after the license routes around line 378). Add:

```python
# ── Lemon Squeezy webhook + admin ─────────────────────────────────────────────

@app.post("/api/lemon/webhook")
async def lemon_webhook(request: Request):
    """Receive Lemon Squeezy payment webhook, issue license key, email buyer."""
    from .lemon import process_webhook, LemonWebhookError
    body = await request.body()
    signature = request.headers.get("X-Signature", "")
    try:
        result = process_webhook(body, signature)
        return result
    except LemonWebhookError as e:
        if "signature" in str(e):
            raise HTTPException(401, str(e))
        # Non-signature errors (not paid, malformed) — log and return 200
        # so Lemon Squeezy doesn't retry endlessly
        log.warning("lemon webhook skipped: %s", e)
        return {"skipped": True, "reason": str(e)}
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@app.get("/api/admin/licenses")
def admin_list_licenses(request: Request, page: int = 1,
                        per_page: int = 20, search: str = ""):
    _require_auth(request)
    licenses = db.list_issued_licenses(search=search, page=page, per_page=per_page)
    total = db.count_issued_licenses(search=search)
    return {"total": total, "page": page, "per_page": per_page, "licenses": licenses}


@app.post("/api/admin/licenses/{license_id}/revoke")
def admin_revoke_license(request: Request, license_id: int):
    _require_auth(request)
    row = db.get_issued_license(license_id)
    if not row:
        raise HTTPException(404, "License not found")
    db.revoke_issued_license(license_id)
    return {"ok": True}


@app.post("/api/admin/licenses/{license_id}/resend")
def admin_resend_license(request: Request, license_id: int):
    _require_auth(request)
    from .lemon import build_license_email_html, LemonWebhookError
    from .notifications import send_email_direct
    row = db.get_issued_license(license_id)
    if not row:
        raise HTTPException(404, "License not found")
    download_url = os.environ.get("LICENSE_DOWNLOAD_URL", "")
    html = build_license_email_html(row["buyer_email"], row["license_key"], download_url)
    smtp_host = db.get_app_config("email_smtp", "")
    smtp_port = int(db.get_app_config("email_port", "587"))
    smtp_user = db.get_app_config("email_user", "")
    smtp_pass = db.get_app_config("email_pass", "")
    if not smtp_host or not smtp_user or not smtp_pass:
        raise HTTPException(400, "SMTP not configured in Settings")
    send_email_direct(row["buyer_email"], smtp_host, smtp_port,
                      smtp_user, smtp_pass, "Your TradeBot License Key", html)
    db.update_resent_at(license_id)
    return {"ok": True}


@app.get("/api/admin/licenses/export")
def admin_export_licenses(request: Request):
    _require_auth(request)
    import csv, io
    rows = db.list_issued_licenses(per_page=100000)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["order_id", "buyer_email", "license_key", "issued_at", "revoked", "resent_at"])
    for r in rows:
        w.writerow([r["order_id"], r["buyer_email"], r["license_key"],
                    r["issued_at"], r["revoked"], r.get("resent_at", "")])
    from fastapi.responses import Response
    return Response(content=out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=licenses.csv"})
```

Also add `import os` near the top of `main.py` if not already present.

- [ ] **Step 4: Run all lemon route tests**

```bash
.venv\Scripts\pytest tests/test_lemon.py -v 2>&1 | tail -20
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/main.py
git commit -m "feat: register lemon webhook and admin license routes"
```

---

### Task 4: Update `.env.example` with new variables

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Add the 3 new variables**

Open `.env.example` and append:

```
# ── Lemon Squeezy License Automation ─────────────────────────────────────────
# Signing secret from Lemon Squeezy Dashboard → Webhooks → Signing secret
LEMON_SQUEEZY_SIGNING_SECRET=

# Number of days the issued license is valid (36500 = ~100 years = lifetime)
LICENSE_DURATION_DAYS=36500

# Lemon Squeezy download URL shown in the buyer's email
# Find it in LS Dashboard → Products → your product → Files → Copy link
LICENSE_DOWNLOAD_URL=
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: add LEMON_SQUEEZY_SIGNING_SECRET, LICENSE_DURATION_DAYS, LICENSE_DOWNLOAD_URL to .env.example"
```

---

### Task 5: Add License Management section to `settings.html`

**Files:**
- Modify: `server/static/settings.html`

- [ ] **Step 1: Add the License Management section HTML**

Find the closing `</div>` of the last settings section (just before `</div><!-- /help-content -->` or the equivalent wrapper). Add a new collapsible section:

```html
<!-- ── License Management ──────────────────────────────────────────────── -->
<div class="settings-section" id="license-mgmt-section">
  <div class="settings-section-header" onclick="toggleSection('license-mgmt')">
    <div>
      <div class="settings-section-title">License Management</div>
      <div class="settings-section-sub">View, revoke, and resend issued license keys</div>
    </div>
    <svg id="license-mgmt-chevron" width="16" height="16" fill="none"
         stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"
         style="transition:transform .2s;flex-shrink:0">
      <polyline points="6 9 12 15 18 9"/>
    </svg>
  </div>
  <div id="license-mgmt-body" style="display:none;padding:1rem 0 .5rem;">

    <!-- Stats row -->
    <div style="display:flex;gap:1rem;margin-bottom:1rem;flex-wrap:wrap;">
      <div class="stat-pill">Total: <strong id="lm-total">—</strong></div>
      <div class="stat-pill">Active: <strong id="lm-active">—</strong></div>
      <div class="stat-pill">Revoked: <strong id="lm-revoked">—</strong></div>
      <button class="btn btn-sm btn-ghost" style="margin-left:auto"
              onclick="exportLicenses()">&#8595; Export CSV</button>
    </div>

    <!-- Search -->
    <div style="margin-bottom:.75rem;">
      <input id="lm-search" class="input-field" style="max-width:280px;font-size:13px;"
             placeholder="Search by email…"
             oninput="loadLicenses(1)">
    </div>

    <!-- Table -->
    <div style="overflow-x:auto;">
      <table class="help-table" id="lm-table" style="font-size:12px;">
        <thead>
          <tr>
            <th>Email</th>
            <th>Order ID</th>
            <th>Issued</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="lm-tbody">
          <tr><td colspan="5" style="text-align:center;color:var(--muted);padding:1.5rem;">
            Loading…</td></tr>
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    <div style="display:flex;gap:.5rem;justify-content:flex-end;margin-top:.75rem;">
      <button class="btn btn-sm btn-ghost" id="lm-prev" onclick="loadLicenses(lmPage-1)">
        ← Prev</button>
      <span id="lm-page-info" style="font-size:12px;color:var(--muted);align-self:center;"></span>
      <button class="btn btn-sm btn-ghost" id="lm-next" onclick="loadLicenses(lmPage+1)">
        Next →</button>
    </div>

  </div>
</div>
```

- [ ] **Step 2: Add JavaScript for the License Management section**

Find the closing `</script>` tag at the bottom of settings.html. Add before it:

```javascript
// ── License Management ─────────────────────────────────────────────────────
let lmPage = 1;
const LM_PER_PAGE = 20;

async function loadLicenses(page = 1) {
  lmPage = Math.max(1, page);
  const search = document.getElementById('lm-search')?.value || '';
  const resp = await apiFetch(
    `/api/admin/licenses?page=${lmPage}&per_page=${LM_PER_PAGE}&search=${encodeURIComponent(search)}`
  );
  if (!resp?.licenses) return;

  const total   = resp.total;
  const active  = resp.licenses.filter(l => !l.revoked).length;
  const revoked = resp.licenses.filter(l => l.revoked).length;

  document.getElementById('lm-total').textContent   = total;
  document.getElementById('lm-active').textContent  = active;
  document.getElementById('lm-revoked').textContent = revoked;

  const totalPages = Math.ceil(total / LM_PER_PAGE);
  document.getElementById('lm-page-info').textContent =
    `Page ${lmPage} of ${totalPages || 1}`;
  document.getElementById('lm-prev').disabled = lmPage <= 1;
  document.getElementById('lm-next').disabled = lmPage >= totalPages;

  const tbody = document.getElementById('lm-tbody');
  if (!resp.licenses.length) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:1.5rem;">
      No licenses found</td></tr>`;
    return;
  }

  tbody.innerHTML = resp.licenses.map(l => {
    const maskedKey = l.license_key.slice(0, 8) + '…' + l.license_key.slice(-6);
    const statusBadge = l.revoked
      ? `<span class="help-badge red">Revoked</span>`
      : `<span class="help-badge green">Active</span>`;
    const issued = l.issued_at ? l.issued_at.slice(0, 10) : '—';
    return `<tr>
      <td>${escHtml(l.buyer_email)}</td>
      <td style="font-family:monospace;font-size:11px;">${escHtml(l.order_id)}</td>
      <td>${issued}</td>
      <td>${statusBadge}</td>
      <td style="white-space:nowrap;">
        <button class="btn btn-sm btn-ghost" style="font-size:11px;"
                onclick="copyToClipboard('${escHtml(l.license_key)}', this)">Copy Key</button>
        <button class="btn btn-sm btn-ghost" style="font-size:11px;"
                onclick="resendLicense(${l.id}, this)">Resend</button>
        ${!l.revoked ? `<button class="btn btn-sm" style="font-size:11px;background:rgba(239,68,68,.1);color:#EF4444;border-color:rgba(239,68,68,.3);"
                onclick="revokeLicense(${l.id}, this)">Revoke</button>` : ''}
      </td>
    </tr>`;
  }).join('');
}

async function revokeLicense(id, btn) {
  if (!confirm('Revoke this license key? The buyer will no longer be able to activate it.')) return;
  btn.disabled = true;
  await apiFetch(`/api/admin/licenses/${id}/revoke`, { method: 'POST' });
  loadLicenses(lmPage);
}

async function resendLicense(id, btn) {
  btn.disabled = true;
  btn.textContent = 'Sending…';
  const resp = await apiFetch(`/api/admin/licenses/${id}/resend`, { method: 'POST' });
  if (resp?.ok) {
    btn.textContent = 'Sent ✓';
  } else {
    btn.textContent = 'Failed';
    btn.disabled = false;
  }
}

function exportLicenses() {
  window.location.href = '/api/admin/licenses/export';
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
                  .replace(/"/g,'&quot;');
}

// Load licenses when section is expanded
const _origToggle = window.toggleSection;
window.toggleSection = function(id) {
  _origToggle && _origToggle(id);
  if (id === 'license-mgmt') {
    setTimeout(() => loadLicenses(1), 50);
  }
};
```

- [ ] **Step 3: Verify the section renders — start the server and open Settings**

```bash
.venv\Scripts\python -m uvicorn server.main:app --port 8000 --reload
```

Open `http://localhost:8000/static/settings.html` → scroll to bottom → expand "License Management" → confirm table loads (empty is fine).

- [ ] **Step 4: Commit**

```bash
git add server/static/settings.html
git commit -m "feat: add License Management admin section to settings.html"
```

---

### Task 6: End-to-end manual test + final verification

**No new files — this task verifies everything works together.**

- [ ] **Step 1: Run the full test suite**

```bash
.venv\Scripts\pytest tests/test_lemon.py -v
```
Expected: all tests PASS, 0 failures.

- [ ] **Step 2: Test the webhook manually with curl**

Start the server:
```bash
.venv\Scripts\python -m uvicorn server.main:app --port 8000
```

In a second terminal, set the signing secret and fire a test webhook:

```bash
python -c "
import hashlib, hmac, json, urllib.request

SIGNING_SECRET = 'your-actual-LEMON_SQUEEZY_SIGNING_SECRET-here'
payload = json.dumps({
    'meta': {'event_name': 'order_created'},
    'data': {
        'id': 'test_order_001',
        'attributes': {
            'user_email': 'testbuyer@example.com',
            'status': 'paid'
        }
    }
}).encode()

sig = hmac.new(SIGNING_SECRET.encode(), payload, hashlib.sha256).hexdigest()
req = urllib.request.Request(
    'http://localhost:8000/api/lemon/webhook',
    data=payload,
    headers={'X-Signature': sig, 'Content-Type': 'application/json'},
    method='POST'
)
with urllib.request.urlopen(req) as r:
    print(r.read().decode())
"
```

Expected output: `{"order_id": "test_order_001", "buyer_email": "testbuyer@example.com", "license_key": "...", "emailed": false, "duplicate": false}`

- [ ] **Step 3: Verify key stored in DB**

```bash
python -c "
import sqlite3
db = sqlite3.connect('trading.db')
db.row_factory = sqlite3.Row
rows = db.execute('SELECT id, order_id, buyer_email, issued_at, revoked FROM issued_licenses').fetchall()
for r in rows: print(dict(r))
db.close()
"
```
Expected: one row with `order_id=test_order_001`.

- [ ] **Step 4: Test duplicate idempotency — fire the same webhook again**

Re-run the curl command from Step 2. Expected: `{"duplicate": true}` — no second row in DB.

- [ ] **Step 5: Test bad signature**

```bash
python -c "
import json, urllib.request
payload = json.dumps({'meta': {}, 'data': {'id': 'x', 'attributes': {}}}).encode()
req = urllib.request.Request(
    'http://localhost:8000/api/lemon/webhook',
    data=payload,
    headers={'X-Signature': 'badsig', 'Content-Type': 'application/json'},
    method='POST'
)
try:
    urllib.request.urlopen(req)
except urllib.error.HTTPError as e:
    print('Status:', e.code)  # expect 401
"
```
Expected: `Status: 401`

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "test: end-to-end manual verification of lemon squeezy license automation"
git push origin master
```

---

## Lemon Squeezy Dashboard Setup (after deploy to VPS)

After deploying to your VPS, configure Lemon Squeezy:

1. Go to **LS Dashboard → Webhooks → Add webhook**
2. URL: `https://your-vps-ip:8000/api/lemon/webhook`
3. Events: check **order_created**
4. Copy the **Signing secret** → paste into your VPS `.env` as `LEMON_SQUEEZY_SIGNING_SECRET`
5. Set `LICENSE_DOWNLOAD_URL` in `.env` to your LS product download URL
6. Restart TradeBot: `sudo systemctl restart tradebot`
