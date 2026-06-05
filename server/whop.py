"""Whop webhook handler — verifies payment, issues license key, emails buyer with download token."""
import hashlib
import hmac
import logging
import os
import secrets

log = logging.getLogger("whop")


class WhopWebhookError(Exception):
    pass


def _svix_secret_bytes(secret: str) -> bytes:
    """Whop/Svix signing secrets look like 'whsec_<base64>'. The HMAC key is the
    base64-decoded portion after the prefix. If no prefix/decoding fails, fall back
    to the raw secret bytes (covers older 'sha256=<hex>' style secrets)."""
    import base64
    s = secret.strip()
    if s.startswith("whsec_"):
        s = s[len("whsec_"):]
    try:
        return base64.b64decode(s)
    except Exception:
        return secret.encode()


def verify_signature(body: bytes, signature: str, secret: str,
                     webhook_id: str = "", timestamp: str = "") -> None:
    """Verify a Whop (Svix) webhook signature.

    Whop signs with Svix: the signed content is "{id}.{timestamp}.{body}", HMAC-
    SHA256 with the base64-decoded secret, and the `webhook-signature` header is a
    space-separated list of "v1,<base64sig>" entries. We accept if ANY entry matches.

    Falls back to the legacy plain-body HMAC (hex, optional 'sha256=' prefix) when
    no id/timestamp are supplied, so older configurations still verify.
    """
    import base64
    key = _svix_secret_bytes(secret)

    # Svix mode: needs id + timestamp
    if webhook_id and timestamp:
        signed = f"{webhook_id}.{timestamp}.".encode() + body
        expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
        for part in signature.split():
            # each part is like "v1,<sig>"
            ver, _, sig = part.partition(",")
            if sig and hmac.compare_digest(sig, expected):
                return
        raise WhopWebhookError("invalid signature")

    # Legacy fallback: HMAC of the raw body, hex digest, optional 'sha256=' prefix.
    sig = signature[7:] if signature.startswith("sha256=") else signature
    expected_hex = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hex, sig):
        raise WhopWebhookError("invalid signature")


def extract_order_data(payload: dict) -> tuple[str, str]:
    """Return (order_id, buyer_email) from a Whop webhook payload.

    Whop's real payload shape (captured from a live webhook):
      { "type": "payment.succeeded", "data": { "id": "pay_…",
        "user": { "email": "…" }, "membership": {…}, … } }
    The event name is in `type` (NOT `event`), and the buyer email is at
    data.user.email. We only act on completed payments / valid memberships.
    """
    event = payload.get("type", "") or payload.get("event", "")  # `type` is current; `event` legacy
    if event not in ("payment.succeeded", "membership.went_valid", "membership.created"):
        raise WhopWebhookError(f"unhandled event type: {event}")

    try:
        data = payload.get("data", {}) or {}
        order_id = str(data.get("id", ""))
        user = data.get("user", {}) or {}
        # email may be at data.user.email (current) or data.user_email (legacy fallback)
        buyer_email = user.get("email", "") or data.get("user_email", "")
    except (KeyError, TypeError, AttributeError) as e:
        raise WhopWebhookError(f"malformed payload: {e}")

    if not order_id:
        raise WhopWebhookError("missing order_id in payload")
    if not buyer_email:
        raise WhopWebhookError("missing buyer email in payload")

    return order_id, buyer_email


def generate_download_token() -> str:
    return secrets.token_urlsafe(32)


def build_license_email_html(buyer_email: str, license_key: str, download_url: str) -> str:
    """Return HTML email body for license + download delivery."""
    return f"""<!DOCTYPE html>
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
  .warning {{ background: #FEF3C7; border-radius: 8px; padding: 12px 16px;
              font-size: 12px; color: #92400E; margin-bottom: 20px; }}
  .steps {{ background: #F8FAFC; border-radius: 8px; padding: 20px;
            margin-bottom: 24px; }}
  .steps h3 {{ margin: 0 0 12px; font-size: 13px; text-transform: uppercase;
               letter-spacing: .05em; color: #64748B; }}
  .steps ol {{ margin: 0; padding-left: 20px; font-size: 13px;
               color: #334155; line-height: 2; }}
  .footer {{ font-size: 12px; color: #94A3B8; text-align: center; margin-top: 24px; }}
</style>
</head>
<body>
<div class="card">
  <div class="logo">PrimusTrader</div>
  <div class="title">Your License Key is Ready</div>
  <div class="sub">Thank you for your purchase, {buyer_email}</div>
  <p style="font-size:13px;color:#475569;margin-bottom:6px;"><strong>Your license key:</strong></p>
  <div class="key-box">{license_key}</div>
  <a href="{download_url}" class="btn">&#8595; Download PrimusTrader</a>
  <div class="warning">
    &#9888; This download link is valid for <strong>72 hours</strong> and
    <strong>3 downloads</strong>. Save the zip file after downloading.
  </div>
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
    Need help? Reply to this email and we will get back to you.
  </p>
  <div class="footer">PrimusTrader &mdash; Automated Algorithmic Trading Platform</div>
</div>
</body>
</html>"""


def process_webhook(body: bytes, signature: str,
                    webhook_id: str = "", timestamp: str = "") -> dict:
    """Full pipeline: verify → extract → mint key → store → generate download token → email.

    Returns dict with order_id, buyer_email, license_key, emailed, duplicate.
    Raises WhopWebhookError on signature failure or unhandled event.
    `webhook_id`/`timestamp` are the Svix webhook-id / webhook-timestamp headers,
    required for signature verification of current Whop payloads.
    """
    import json
    from server import db
    from server.license import mint_key
    from server.notifications import send_email_direct

    signing_secret = db.get_app_config_secure("whop_signing_secret", "")
    if not signing_secret:
        raise RuntimeError(
            "Whop signing secret is not set. "
            "Add it in Settings → License Management."
        )

    if signature:
        verify_signature(body, signature, signing_secret, webhook_id, timestamp)

    payload = json.loads(body)
    order_id, buyer_email = extract_order_data(payload)

    # Idempotency — return existing record if order already processed
    existing = db.list_issued_licenses(search=buyer_email)
    for row in existing:
        if row["order_id"] == order_id:
            log.info("duplicate whop order_id %s — skipping", order_id)
            return {
                "order_id": order_id,
                "buyer_email": buyer_email,
                "license_key": row["license_key"],
                "emailed": False,
                "duplicate": True,
            }

    # Generate license key
    days = int(os.environ.get("LICENSE_DURATION_DAYS", "36500"))
    license_key = mint_key(machine_id="ANY", days=days)

    # Store license in DB
    db.add_issued_license(order_id, buyer_email, license_key)

    # Generate a one-time download token (72h, 3 attempts)
    token = generate_download_token()
    db.create_download_token(token, buyer_email, license_key, expires_hours=72, max_attempts=3)

    # Build download URL
    base_url = os.environ.get("APP_BASE_URL", "https://primustrader.com")
    download_url = f"{base_url}/download/{token}"

    html = build_license_email_html(buyer_email, license_key, download_url)
    emailed = False
    try:
        smtp_host = db.get_app_config("email_smtp", "")
        smtp_port = int(db.get_app_config("email_port", "587"))
        smtp_user = db.get_app_config("email_user", "")
        smtp_pass = db.get_app_config_secure("email_pass", "")
        if smtp_host and smtp_user and smtp_pass:
            send_email_direct(
                buyer_email, smtp_host, smtp_port, smtp_user, smtp_pass,
                "Your PrimusTrader License Key & Download", html,
            )
            emailed = True
        else:
            log.warning("SMTP not configured — license stored but email not sent for %s", buyer_email)
    except Exception as e:
        log.error("Failed to send license email to %s: %s", buyer_email, e)

    log.info("whop license issued: order=%s email=%s emailed=%s", order_id, buyer_email, emailed)
    return {
        "order_id": order_id,
        "buyer_email": buyer_email,
        "license_key": license_key,
        "emailed": emailed,
        "duplicate": False,
    }
