# Owner Mode + Asymmetric Licensing — Design Spec

**Date:** 2026-06-01
**Goal:** Separate the **seller/owner** instance from **buyer** copies so that (a) buyers cannot forge license keys even with full source + their own `.env`, and (b) seller-only tooling (License Management) is hidden from buyers and blocked server-side.

## Problem

Today there is no buyer-vs-owner distinction:

1. **Licensing is symmetric HMAC.** `license.py` signs (`mint_key`) and verifies (`verify_key`) license keys with the same `TRADEBOT_LICENSE_SECRET`. The buyer's runtime (`check_stored_license` → `_get_seller_secret`) needs that secret to verify, so the secret must live on every buyer's machine. Anyone with it can mint unlimited valid keys — the entire licensing model is crackable.
2. **Seller tooling is exposed to buyers.** The "License Management" panel in `settings.html` (lists buyer emails / order IDs, revoke / resend / export CSV) is always rendered for any authenticated user, and the `/api/admin/licenses/*` endpoints are protected only by the shared dashboard password (`_require_auth`). There is no owner gate.

Note: a buyer's `issued_licenses` table is empty (only the seller's Lemon webhook writes to it), so the panel leaks no customer data on a buyer's box — but it is confusing tooling and an unguarded endpoint. The real risk is #1.

## Part A — Asymmetric licensing (the security fix)

**Crypto:** Ed25519 via the already-installed `cryptography` library (`>=41`, already used by `crypto.py` for Fernet). **No new dependency.**

**Keypair:**
- **Private key** — signs license keys. Lives ONLY on the owner instance, in env var `TRADEBOT_LICENSE_PRIVATE_KEY`. Never ships to buyers.
- **Public key** — verifies license keys. Baked into the buyer build as a default constant `LICENSE_PUBLIC_KEY` in `license.py`. May be overridden by env `TRADEBOT_LICENSE_PUBLIC_KEY`, defaulting to the source constant. It can verify but cannot mint.

**Key envelope (unchanged shape):** base64-url of `{"p": payload, "s": signature}` where `payload` is the compact JSON string `{"m": machine_id, "exp": expiry_unix}`. Only the signature algorithm changes: HMAC-SHA256 → Ed25519 signature over the UTF-8 bytes of `payload`. The signature is stored base64-encoded inside `s`.

**`license.py` changes:**
- `mint_key(machine_id: str, days: int) -> str` — loads the **private key** from `TRADEBOT_LICENSE_PRIVATE_KEY`, signs the payload, returns the bundle. Raises `RuntimeError` if the private key is absent (so buyer builds physically cannot mint).
- `verify_key(key: str, machine_id: str | None = None) -> dict` — loads the **public key** (constant or env), verifies the Ed25519 signature, then checks expiry and machine binding exactly as today (`MACHINE_ANY`, `exp`, machine_id match). Returns `{"valid": True, "days_remaining": N, "machine_id": ...}`. Raises `LicenseError` on malformed/invalid/expired/machine-mismatch.
- `check_stored_license()` — calls `verify_key(key)` (public key only). **The buyer runtime no longer needs any secret.** Keep the existing 1-hour in-process cache and `invalidate_cache()`.
- **Remove** `_get_seller_secret()` and `_read_env_secret()` (HMAC seller-secret path) — clean cutover, no legacy.
- Keep `get_machine_id()`, `MACHINE_ANY`, `LicenseError`, `_cache`/`_CACHE_TTL` unchanged.

**Callers to update (verified locations):**
- `main.py:407,410` — `/api/license/activate`: `from .license import verify_key, _get_seller_secret, ...` and `verify_key(body.key, _get_seller_secret())` → drop the secret import, call `verify_key(body.key)`.
- `lemon.py:110,143` — webhook auto-issue: `from server.license import mint_key, _get_seller_secret` and `mint_key(_get_seller_secret(), machine_id="ANY", days=days)` → `from server.license import mint_key` and `mint_key(machine_id="ANY", days=days)`. The webhook now mints with the private key (owner instance).
- `main.py:9` comment mentions `TRADEBOT_LICENSE_SECRET` — update to reference the private key var.

**Test-suite impact (verified — non-trivial, budget for it):**
The shared fixture and several license tests assume the HMAC `mint_key(secret, ...)` / `verify_key(key, secret, ...)` signatures and set `TRADEBOT_LICENSE_SECRET`:
- `tests/conftest.py:8,34` — sets `TRADEBOT_LICENSE_SECRET` and calls `mint_key(secret, "ANY", 365)` to make `_require_auth`'s license check pass for **most** authed tests. Must switch to: generate a throwaway test keypair once, set `TRADEBOT_LICENSE_PRIVATE_KEY` (and the public key), and mint with the new signature. This unblocks the whole suite.
- `tests/test_license.py` — rewrite to the new signatures (mint with private key, verify with public key; keep the same scenarios: valid, expired, machine-bound, tampered, MACHINE_ANY).
- `tests/test_license_api.py:3,39,70`, `tests/test_export.py:2`, `tests/test_lemon.py:152` — replace `TRADEBOT_LICENSE_SECRET` setup and `mint_key("…secret…", …)` calls with the new keypair-based helper (put a small `_test_keypair()` / `mint_test_key()` helper in `conftest.py` and reuse it).
- `tests/test_lemon.py` `SIGNING_SECRET` (the Lemon **webhook** signing secret, line 10) is unrelated and stays.

**Clean cutover:** New asymmetric format only. Any previously issued HMAC keys stop validating. Acceptable because the product is pre-launch (no real buyers yet); if a test key exists, re-issue it.

**Key generation:** A one-off CLI `scripts/gen_license_keys.py` prints a fresh Ed25519 keypair:
- the **private key** (base64) → user places in their owner `.env` as `TRADEBOT_LICENSE_PRIVATE_KEY`
- the **public key** (base64) → user pastes into `license.py` as the `LICENSE_PUBLIC_KEY` constant (and/or buyer `.env`)
The script is documented in `.env.example`. The keypair is generated by the USER (not in any agent session) so the private key never leaks.

## Part B — Owner-mode gating (hide seller tooling)

**Flag helper** (in `main.py` or a tiny config module):
```python
def owner_mode_enabled() -> bool:
    return os.environ.get("TRADEBOT_OWNER_MODE", "").strip().lower() in ("1", "true", "yes")
```

**Server enforcement (the network boundary):**
- New helper `_require_owner(request)`: calls `_require_auth(request)`, then raises `HTTPException(403, "owner only")` if `not owner_mode_enabled()`.
- Apply `_require_owner` to all four seller endpoints: `GET /api/admin/licenses`, `POST /api/admin/licenses/{id}/revoke`, `POST /api/admin/licenses/{id}/resend`, `GET /api/admin/licenses/export`. Buyers get **403** even if they know the URLs.

**Expose flag to authenticated UI:**
- Add an authenticated `GET /api/app-info` returning `{"owner_mode": owner_mode_enabled()}` (extensible for future fields). Protected by `_require_auth`. (Chosen over `/api/health` because `/api/health` is intentionally public and the flag should not be world-readable.)

**Frontend (`settings.html` + `app.js`):**
- The License Management section (`#license-mgmt-section`) starts **hidden** (add a `hidden` class / `display:none` by default in markup).
- On settings init, fetch `/api/app-info`; if `owner_mode` is true, reveal the section and wire its load. Otherwise leave it hidden and do NOT call `loadLicenses()`/`exportLicenses()`.
- Buyer sees a clean Settings page; owner sees the panel exactly as before.

**Honest limitation (documented, not a defect):** Owner mode is a server-side network gate (403) plus UI hygiene. A buyer who edits the Python could flip the flag locally — but they would see an **empty** `issued_licenses` table and still cannot mint keys (no private key). The real protection of the business is Part A. This caveat is stated so expectations are correct.

## Config / docs

`.env.example` additions (commented, buyer-safe defaults):
```
# ── Owner / seller instance only ─────────────────────────────────────────────
# Set to 1 ONLY on the seller's own machine to unlock License Management tools.
# Buyer copies leave this unset.
# TRADEBOT_OWNER_MODE=

# Ed25519 license signing key — OWNER INSTANCE ONLY. Generate with:
#   python scripts/gen_license_keys.py
# Put the PRIVATE key here (never ship it). The PUBLIC key is baked into the app.
# TRADEBOT_LICENSE_PRIVATE_KEY=
```
Remove the old `TRADEBOT_LICENSE_SECRET=` line (no longer used). `DB_SECRET_KEY` is unrelated and stays.

## Components & boundaries

- `server/license.py` — Ed25519 mint/verify + machine/expiry checks (single responsibility: license key crypto + validation). Buyer needs only the public key.
- `scripts/gen_license_keys.py` — one-off keypair generator (no app coupling).
- `server/main.py` — `owner_mode_enabled()`, `_require_owner()`, `/api/app-info`, owner gate on `/api/admin/*`, updated license callers.
- `server/lemon.py` — webhook minting updated to new `mint_key` signature.
- `server/static/settings.html` + `server/static/app.js` — hide License Management unless owner_mode.

## Error handling

- `mint_key` with no private key → `RuntimeError` (buyer builds can't mint).
- `verify_key` malformed/invalid signature/expired/wrong machine → `LicenseError` with the same reason strings the UI already shows.
- `/api/admin/*` without owner mode → `403`.
- Public key missing/invalid in a buyer build → `verify_key` raises `LicenseError("invalid: verifier not configured")` and `check_stored_license` returns `{valid: False, reason: ...}` (license screen shown), rather than crashing.

## Testing

- `test_license_asymmetric.py`:
  - mint with private key → verify with public key → valid; `days_remaining` correct.
  - tampered payload / wrong signature → `LicenseError`.
  - expired `exp` → `LicenseError("expired: …")`.
  - machine-bound key on wrong machine → `LicenseError("machine: …")`; `MACHINE_ANY` passes anywhere.
  - `mint_key` with private key absent → `RuntimeError`.
  - a buyer build (public key only, no private key) can verify a key minted by the private key but cannot mint.
- `test_owner_mode.py`:
  - `owner_mode_enabled()` true for `1/true/yes`, false otherwise.
  - `/api/admin/licenses` (and revoke/resend/export) → 403 when owner mode off (authed), 200 when on.
  - `/api/app-info` returns the correct `owner_mode` boolean (and requires auth).
- Update/adjust any existing license tests that relied on the HMAC `secret` argument.

## Out of scope

- No second login / real RBAC (single dashboard password unchanged).
- No changes to buyer trading features, alerts (Email/Slack/Discord), or the buyer activation screen (`license.html`) beyond what the new verify path requires.
- No automatic re-issue of old keys (clean cutover).

## Success criteria

- A buyer build contains only the public key: can verify their key, cannot mint a new valid key.
- `/api/admin/licenses/*` returns 403 on a buyer (non-owner) instance.
- License Management panel is hidden in buyer Settings, visible+working on the owner instance.
- `gen_license_keys.py` produces a usable keypair; documented in `.env.example`.
- Existing test suite still green (minus intentionally updated HMAC-era license tests).
