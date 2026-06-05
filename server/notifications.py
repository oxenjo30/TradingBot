"""Email and Telegram trade notifications."""
import logging
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx

from . import db

log = logging.getLogger("notifications")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _settings():
    return db.get_notification_settings()


def _send_async(fn, *args, **kwargs):
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


# ── Email ─────────────────────────────────────────────────────────────────────

def _build_smtp(smtp_host: str, port: int, user: str, password: str):
    """Connect, STARTTLS, login — raises descriptive exceptions on failure."""
    try:
        srv = smtplib.SMTP(smtp_host, port, timeout=15)
    except OSError as e:
        raise RuntimeError(f"Cannot reach {smtp_host}:{port} — check SMTP server and port. ({e})")
    try:
        srv.starttls()
    except smtplib.SMTPException as e:
        srv.quit()
        raise RuntimeError(f"STARTTLS failed — server may not support it. ({e})")
    try:
        srv.login(user, password)
    except smtplib.SMTPAuthenticationError:
        srv.quit()
        host = (smtp_host or "").lower()
        if "gmail" in host:
            raise RuntimeError(
                "Gmail login failed. You must use an App Password, NOT your regular Gmail password.\n"
                "Create one at: myaccount.google.com → Security → App Passwords\n"
                "(Requires 2-Step Verification to be enabled on your Google account first.)"
            )
        raise RuntimeError(
            f"SMTP login failed for {user} on {smtp_host}. Check the username and password "
            "(for most hosts this is the full email address and its mailbox password). "
            "If your provider requires it, use an app-specific password."
        )
    except smtplib.SMTPException as e:
        srv.quit()
        raise RuntimeError(f"SMTP login error: {e}")
    return srv


def send_email_direct(to: str, smtp: str, port: int, user: str,
                      password: str, subject: str, body: str):
    """Send an email with explicit credentials — raises on any failure."""
    if not to or not smtp or not user or not password:
        raise RuntimeError("Email settings incomplete — fill in all fields and Save before testing.")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[TradeBot] {subject}"
    msg["From"]    = user
    msg["To"]      = to
    msg.attach(MIMEText(body, "html"))
    srv = _build_smtp(smtp, int(port or 587), user, password)
    try:
        srv.send_message(msg)
        log.info("email sent: %s → %s", subject, to)
    finally:
        srv.quit()


def _send_email(subject: str, body: str):
    """Background email using saved DB settings — silently skips if not configured."""
    s = _settings()
    if not s["email_enabled"] or not s["email_to"] or not s["email_pass"]:
        return
    try:
        send_email_direct(
            s["email_to"], s["email_smtp"], int(s["email_port"] or 587),
            s["email_user"], s["email_pass"], subject, body
        )
    except Exception as e:
        log.warning("email failed: %s", e)


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram_direct(token: str, chat_id: str, text: str):
    """Send a Telegram message — raises descriptive exception on failure."""
    if not token or not chat_id:
        raise RuntimeError("Telegram settings incomplete — fill in Bot Token and Chat ID, then Save.")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = httpx.post(url, json={"chat_id": chat_id, "text": text,
                                   "parse_mode": "HTML"}, timeout=12)
        data = r.json()
        if not data.get("ok"):
            desc = data.get("description", "unknown error")
            if "chat not found" in desc.lower():
                raise RuntimeError(
                    f"Chat ID '{chat_id}' not found. "
                    "Make sure you have sent at least one message to your bot first."
                )
            if "unauthorized" in desc.lower():
                raise RuntimeError(
                    "Bot token is invalid. Double-check the token from @BotFather."
                )
            raise RuntimeError(f"Telegram error: {desc}")
        log.info("telegram sent")
    except httpx.ConnectError:
        raise RuntimeError("Cannot reach Telegram — check your internet connection.")


def _send_telegram(text: str):
    """Background Telegram message using saved DB settings."""
    s = _settings()
    if not s["telegram_enabled"] or not s["telegram_token"] or not s["telegram_chat_id"]:
        return
    try:
        send_telegram_direct(s["telegram_token"], s["telegram_chat_id"], text)
    except Exception as e:
        log.warning("telegram failed: %s", e)


# ── Slack ──────────────────────────────────────────────────────────────────────

def send_slack_direct(webhook_url: str, text: str):
    """POST a message to a Slack incoming webhook URL."""
    try:
        r = httpx.post(webhook_url, json={"text": text}, timeout=10)
        r.raise_for_status()
        log.info("slack sent")
    except Exception as e:
        log.warning("slack failed: %s", e)
        raise

def _send_slack(text: str):
    s = _settings()
    if not s.get("slack_enabled") or not s.get("slack_webhook_url"):
        return
    _send_async(send_slack_direct, s["slack_webhook_url"], text)


# ── Discord ───────────────────────────────────────────────────────────────────

def send_discord_direct(webhook_url: str, content: str):
    """POST a message to a Discord webhook URL."""
    try:
        r = httpx.post(webhook_url, json={"content": content}, timeout=10)
        if r.status_code not in (200, 204):
            r.raise_for_status()
        log.info("discord sent")
    except Exception as e:
        log.warning("discord failed: %s", e)
        raise

def _send_discord(text: str):
    s = _settings()
    if not s.get("discord_enabled") or not s.get("discord_webhook_url"):
        return
    _send_async(send_discord_direct, s["discord_webhook_url"], text)


# ── Public API ────────────────────────────────────────────────────────────────

def notify_trade(strategy: str, symbol: str, side: str, qty,
                 notional, reason: str, order_id: str):
    s = _settings()
    if not s.get("notify_on_trade"):
        return

    side_emoji = "🟢 BUY" if side == "buy" else "🔴 SELL"
    amount = f"${notional:.2f}" if notional else f"{qty} shares"

    subject = f"{side_emoji} {symbol} — {amount}"
    html = f"""
    <div style="font-family:sans-serif;max-width:480px">
      <h2 style="color:{'#16c784' if side=='buy' else '#ea3943'}">{side_emoji} {symbol}</h2>
      <table style="width:100%;border-collapse:collapse">
        <tr><td style="padding:6px 0;color:#888">Strategy</td><td><b>{strategy}</b></td></tr>
        <tr><td style="padding:6px 0;color:#888">Amount</td><td><b>{amount}</b></td></tr>
        <tr><td style="padding:6px 0;color:#888">Signal</td><td>{reason}</td></tr>
        <tr><td style="padding:6px 0;color:#888">Order ID</td><td style="font-size:.8em">{order_id}</td></tr>
      </table>
      <p style="color:#888;font-size:.8em;margin-top:1rem">TradeBot — Automated Trading</p>
    </div>"""

    tg = f"{side_emoji} <b>{symbol}</b> — {amount}\n📋 {strategy}\n💬 {reason}"
    plain = f"TradeBot | {side_emoji} {symbol} — {amount} [{strategy}]"
    _send_async(_send_email, subject, html)
    _send_async(_send_telegram, tg)
    _send_async(_send_slack, plain)
    _send_async(_send_discord, plain)


def notify_risk_block(symbol: str, side: str, reason: str):
    s = _settings()
    if not s.get("notify_on_block"):
        return

    subject = f"⚠️ Trade Blocked — {symbol}"
    html = f"""
    <div style="font-family:sans-serif">
      <h2 style="color:#f0b90b">⚠️ Trade Blocked</h2>
      <p><b>{side.upper()} {symbol}</b> was blocked by risk controls.</p>
      <p style="color:#888">{reason}</p>
    </div>"""
    tg = f"⚠️ <b>Trade Blocked</b>\n{side.upper()} {symbol}\n{reason}"
    plain = f"TradeBot | BLOCKED {side.upper()} {symbol}: {reason}"
    _send_async(_send_email, subject, html)
    _send_async(_send_telegram, tg)
    _send_async(_send_slack, plain)
    _send_async(_send_discord, plain)


def notify_kill_switch(day_pl_pct: float):
    subject = "🛑 Kill Switch Activated"
    html = f"""
    <div style="font-family:sans-serif">
      <h2 style="color:#ea3943">🛑 Kill Switch Activated</h2>
      <p>Daily loss limit hit. All automated trading has been halted.</p>
      <p style="color:#888">Day P&L: <b>{day_pl_pct:.2f}%</b></p>
      <p>Log into TradeBot to review your positions and re-enable trading.</p>
    </div>"""
    tg = f"🛑 <b>Kill Switch Activated</b>\nDay P&amp;L: {day_pl_pct:.2f}%\nAll auto-trading halted."
    _send_async(_send_email, subject, html)
    _send_async(_send_telegram, tg)


def send_daily_summary(account: dict, signals_today: list):
    s = _settings()
    if not s.get("notify_daily_summary"):
        return

    eq   = account.get("equity", 0)
    pl   = account.get("day_pl", 0)
    plp  = account.get("day_pl_pct", 0)
    sign = "+" if pl >= 0 else ""
    emoji = "📈" if pl >= 0 else "📉"

    trade_rows = "".join(
        f"<tr><td style='padding:4px 8px'>{t.get('symbol','')}</td>"
        f"<td style='padding:4px 8px'>{t.get('side','').upper()}</td>"
        f"<td style='padding:4px 8px'>{t.get('strategy','')}</td></tr>"
        for t in signals_today[:10]
    ) or "<tr><td colspan='3' style='color:#888;padding:4px 8px'>No trades today</td></tr>"

    subject = f"{emoji} Daily Summary — {sign}{plp:.2f}% today"
    html = f"""
    <div style="font-family:sans-serif;max-width:520px">
      <h2>{emoji} TradeBot Daily Summary</h2>
      <table style="width:100%;border-collapse:collapse;margin-bottom:1rem">
        <tr><td style="color:#888;padding:6px 0">Equity</td><td><b>${eq:,.2f}</b></td></tr>
        <tr><td style="color:#888;padding:6px 0">Day P&L</td>
            <td style="color:{'#16c784' if pl>=0 else '#ea3943'}"><b>{sign}${abs(pl):,.2f} ({sign}{plp:.2f}%)</b></td></tr>
      </table>
      <h3>Trades Today</h3>
      <table style="width:100%;border-collapse:collapse;font-size:.9em">
        <tr style="color:#888"><th style="text-align:left;padding:4px 8px">Symbol</th>
          <th style="text-align:left;padding:4px 8px">Side</th>
          <th style="text-align:left;padding:4px 8px">Strategy</th></tr>
        {trade_rows}
      </table>
      <p style="color:#888;font-size:.8em;margin-top:1.5rem">TradeBot</p>
    </div>"""

    tg = f"{emoji} <b>Daily Summary</b>\nEquity: ${eq:,.2f}\nDay P&L: {sign}${abs(pl):,.2f} ({sign}{plp:.2f}%)\nTrades: {len(signals_today)}"
    _send_async(_send_email, subject, html)
    _send_async(_send_telegram, tg)


def notify_price_alert(symbol: str, direction: str, target: float, current_price: float):
    msg = (f"TradeBot | Price Alert: {symbol} is {direction} ${target:.2f} "
           f"(current: ${current_price:.2f})")
    subject = f"Price Alert: {symbol} {direction} ${target:.2f}"
    html = f"""
    <div style="font-family:sans-serif">
      <h2>🔔 Price Alert Triggered</h2>
      <p><b>{symbol}</b> is now {direction} ${target:.2f}</p>
      <p>Current price: <b>${current_price:.2f}</b></p>
    </div>"""
    _send_async(_send_email, subject, html)
    _send_async(_send_telegram, f"🔔 <b>Price Alert</b>\n{msg}")
    _send_async(_send_slack, msg)
    _send_async(_send_discord, msg)
