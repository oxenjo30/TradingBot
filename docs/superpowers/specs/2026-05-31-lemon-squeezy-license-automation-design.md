# Lemon Squeezy License Automation — Design Spec

**Date:** 2026-05-31
**Status:** Approved

---

## Goal

When a buyer completes a purchase on Lemon Squeezy, TradeBot automatically:
1. Receives a signed webhook from Lemon Squeezy
2. Generates a unique lifetime license key
3. Stores the issued key in the database
4. Emails the buyer their license key + Lemon Squeezy download link + PDF guide

The seller sees all issued keys in a new "License Management" section in Settings and can revoke or resend any key.

---

## Architecture

```
Lemon Squeezy payment confirmed
        │
        │  POST /api/lemon/webhook
        │  Header: X-Signature (HMAC-SHA256)
        ▼
server/lemon.py
  ├── verify_signature(body_bytes, header) → raises 401 if invalid
  ├── extract order_id, buyer_email from payload
  ├── mint_key(secret, machine_id="ANY", days=LICENSE_DURATION_DAYS)
  ├── db.add_issued_license(order_id, buyer_email, license_key)
  └── send_license_email(buyer_email, license_key)
        │
        ▼
server/notifications.py
  └── send_email_direct(to, smtp, port, user, password, subject, html_body)
        uses existing SMTP settings from DB

server/db.py
  └── issued_licenses table
        id, order_id, buyer_email, license_key,
        issued_at, revoked, resent_at

server/main.py
  ├── POST /api/lemon/webhook          (public — no auth, verified by signature)
  ├── GET  /api/admin/licenses         (auth required)
  ├── POST /api/admin/licenses/{id}/revoke  (auth required)
  ├── POST /api/admin/licenses/{id}/resend  (auth required)
  └── GET  /api/admin/licenses/export  (auth required)

server/static/settings.html
  └── "License Management" collapsible section (bottom of page)
```

---

## New Files

| File | Responsibility |
|---|---|
| `server/lemon.py` | Webhook signature verification, license generation, email dispatch |
| `tests/test_lemon.py` | Unit + integration tests for all lemon.py functions |

---

## Modified Files

| File | Change |
|---|---|
| `server/db.py` | Add `issued_licenses` table to schema + 5 query methods |
| `server/main.py` | Register 5 new routes |
| `server/static/settings.html` | Add License Management section at bottom |
| `.env.example` | Document 3 new env variables |

---

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS issued_licenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    TEXT UNIQUE NOT NULL,
    buyer_email TEXT NOT NULL,
    license_key TEXT NOT NULL,
    issued_at   TEXT NOT NULL DEFAULT (datetime('now')),
    revoked     INTEGER NOT NULL DEFAULT 0,
    resent_at   TEXT
);
```

---

## Environment Variables

```
LEMON_SQUEEZY_SIGNING_SECRET=   # from LS Dashboard → Webhooks → Signing secret
LICENSE_DURATION_DAYS=36500     # 100 years = lifetime license
LICENSE_DOWNLOAD_URL=           # Lemon Squeezy product download URL shown in email
```

---

## API Endpoints

### POST /api/lemon/webhook
- **Auth:** None (public) — verified by HMAC-SHA256 signature
- **Idempotent:** duplicate `order_id` is silently ignored (returns 200)
- **On success:** key generated, stored, email sent → returns 200
- **On bad signature:** returns 401
- **On missing SMTP:** key still stored, email failure logged as warning (not 500)

### GET /api/admin/licenses
- **Auth:** `_require_auth(request)`
- **Query params:** `page=1`, `per_page=20`, `search=email@example.com`
- **Returns:** `{total, page, licenses: [{id, order_id, buyer_email, license_key, issued_at, revoked, resent_at}]}`

### POST /api/admin/licenses/{id}/revoke
- **Auth:** `_require_auth(request)`
- Sets `revoked=1` in DB

### POST /api/admin/licenses/{id}/resend
- **Auth:** `_require_auth(request)`
- Re-sends the license email, updates `resent_at`

### GET /api/admin/licenses/export
- **Auth:** `_require_auth(request)`
- Returns CSV: `order_id,buyer_email,license_key,issued_at,revoked`

---

## Email Content

**Subject:** Your TradeBot License Key

**HTML body includes:**
- License key in a styled code block
- Download link (from `LICENSE_DOWNLOAD_URL` env var)
- Link to PDF guide (same as download URL or attachment)
- 4-step quick-start instructions
- Support contact

---

## Admin UI (settings.html)

Collapsible section at bottom of Settings page:

```
┌─ License Management ──────────────────────────────────┐
│  Issued: 42   Active: 40   Revoked: 2    [Export CSV] │
│  [Search by email...]                                  │
│                                                        │
│  EMAIL               ORDER ID     ISSUED    STATUS     │
│  john@email.com      ls_abc123    2026-05   Active [▼] │
│    Key: TB-xxxx...xxxx  [Copy] [Resend] [Revoke]       │
└────────────────────────────────────────────────────────┘
```

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Invalid webhook signature | Return 401, log warning |
| Duplicate order_id | Return 200, skip (idempotent) |
| SMTP not configured | Store key in DB, log warning, return 200 |
| SMTP send fails | Store key in DB, log error, return 200 (seller can resend) |
| DB error | Return 500, log error |
| Missing LEMON_SQUEEZY_SIGNING_SECRET | Return 500 with clear message |

---

## Testing Checklist

1. Invalid signature → 401
2. Valid webhook → key in DB + email sent
3. Duplicate order_id → 200, no duplicate row
4. SMTP failure → key still stored, no 500
5. Revoke endpoint → `revoked=1` in DB
6. Resend endpoint → email sent, `resent_at` updated
7. Admin list → pagination + search work
8. Export → valid CSV with all fields
9. Missing `LEMON_SQUEEZY_SIGNING_SECRET` → clear error
