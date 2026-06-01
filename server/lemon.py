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
  <div class="logo">TradeBot</div>
  <div class="title">Your License Key is Ready</div>
  <div class="sub">Thank you for your purchase, {buyer_email}</div>
  <p style="font-size:13px;color:#475569;margin-bottom:6px;"><strong>Your license key:</strong></p>
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
</html>"""


def process_webhook(body: bytes, signature: str) -> dict:
    """Full pipeline: verify → extract → mint key → store → email.

    Returns dict: order_id, buyer_email, license_key, emailed (bool), duplicate (bool).
    Raises LemonWebhookError on signature failure.
    Duplicate order_id is silently ignored (returns existing record info).
    """
    import json
    from server import db
    from server.license import mint_key
    from server.notifications import send_email_direct

    signing_secret = os.environ.get("LEMON_SQUEEZY_SIGNING_SECRET", "")
    if not signing_secret:
        raise RuntimeError("LEMON_SQUEEZY_SIGNING_SECRET is not set in .env")

    verify_signature(body, signature, signing_secret)

    payload = json.loads(body)
    order_id, buyer_email = extract_order_data(payload)

    # Idempotency — check for existing order_id
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
    license_key = mint_key(machine_id="ANY", days=days)

    # Store in DB
    db.add_issued_license(order_id, buyer_email, license_key)

    # Send email
    download_url = os.environ.get("LICENSE_DOWNLOAD_URL", "")
    html = build_license_email_html(buyer_email, license_key, download_url)
    emailed = False
    try:
        smtp_host = db.get_app_config("email_smtp", "")
        smtp_port = int(db.get_app_config("email_port", "587"))
        smtp_user = db.get_app_config("email_user", "")
        smtp_pass = db.get_app_config("email_pass", "")
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
