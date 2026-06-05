"""Gumroad webhook (Ping) handler — verifies a sale, issues a license key, emails
the buyer a one-time download link.

Gumroad's "Ping" (Settings → Advanced → Ping) POSTs application/x-www-form-urlencoded
data on every sale — NOT JSON. Key fields we use:
    seller_id          our account id — the authenticity signal for the Ping
    sale_id            unique per purchase → our order_id (idempotency)
    email              buyer email
    product_permalink  e.g. "oxchvv" — to ignore sales of other products
    refunded/disputed  "true"/"false" — skip non-completed sales

Mirrors server/whop.py and server/lemon.py: verify → extract → mint key → store →
mint download token → email.
"""
import logging
import os
import secrets

log = logging.getLogger("gumroad")


class GumroadWebhookError(Exception):
    pass


def verify_seller(form: dict, expected_seller_id: str) -> None:
    """Raise GumroadWebhookError if the Ping's seller_id doesn't match ours.

    The Ping has no signing secret; the seller_id is the authenticity check. We
    only mint a license when the sale genuinely belongs to our Gumroad account.
    """
    seller_id = (form.get("seller_id") or "").strip()
    if not expected_seller_id:
        raise RuntimeError(
            "Gumroad seller ID is not set. Add it in Settings → License Management."
        )
    if not seller_id or seller_id != expected_seller_id:
        raise GumroadWebhookError(
            f"seller_id mismatch (got {seller_id!r})"
        )


def extract_order_data(form: dict) -> tuple[str, str]:
    """Return (sale_id, buyer_email). Raise GumroadWebhookError for refunds,
    disputes, or missing data."""
    # Skip refunded / disputed / test pings that aren't a completed sale.
    if (form.get("refunded") or "").lower() == "true":
        raise GumroadWebhookError("sale refunded — not issuing")
    if (form.get("disputed") or "").lower() == "true":
        raise GumroadWebhookError("sale disputed — not issuing")

    sale_id = (form.get("sale_id") or "").strip()
    buyer_email = (form.get("email") or "").strip()

    if not sale_id:
        raise GumroadWebhookError("missing sale_id in payload")
    if not buyer_email:
        raise GumroadWebhookError("missing buyer email in payload")

    return sale_id, buyer_email


def generate_download_token() -> str:
    return secrets.token_urlsafe(32)


def build_license_email_html(buyer_email: str, license_key: str, download_url: str) -> str:
    """HTML email body for license + download delivery (matches the Whop email)."""
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


def process_webhook(form: dict) -> dict:
    """Full pipeline: verify seller → extract → mint key → store → token → email.

    `form` is the parsed application/x-www-form-urlencoded body (a plain dict).
    Returns dict with sale_id, buyer_email, license_key, emailed, duplicate.
    Raises GumroadWebhookError on verification/extraction failure.
    """
    from server import db
    from server.license import mint_key
    from server.notifications import send_email_direct

    expected_seller_id = db.get_app_config_secure("gumroad_seller_id", "")
    verify_seller(form, expected_seller_id)

    # Optional: only honor sales of our product if a permalink is configured.
    want_permalink = db.get_app_config("gumroad_permalink", "")
    if want_permalink:
        got = (form.get("product_permalink") or "").strip()
        # product_permalink may be a full URL or just the slug
        if want_permalink not in got:
            raise GumroadWebhookError(
                f"product_permalink mismatch (got {got!r}, want {want_permalink!r})"
            )

    sale_id, buyer_email = extract_order_data(form)

    # Idempotency — return existing record if this sale was already processed.
    existing = db.list_issued_licenses(search=buyer_email)
    for row in existing:
        if row["order_id"] == sale_id:
            log.info("duplicate gumroad sale_id %s — skipping", sale_id)
            return {
                "order_id": sale_id,
                "buyer_email": buyer_email,
                "license_key": row["license_key"],
                "emailed": False,
                "duplicate": True,
            }

    days = int(os.environ.get("LICENSE_DURATION_DAYS", "36500"))
    license_key = mint_key(machine_id="ANY", days=days)
    db.add_issued_license(sale_id, buyer_email, license_key)

    token = generate_download_token()
    db.create_download_token(token, buyer_email, license_key, expires_hours=72, max_attempts=3)

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

    log.info("gumroad license issued: sale=%s email=%s emailed=%s", sale_id, buyer_email, emailed)
    return {
        "order_id": sale_id,
        "buyer_email": buyer_email,
        "license_key": license_key,
        "emailed": emailed,
        "duplicate": False,
    }
