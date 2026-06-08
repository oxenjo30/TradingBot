"""Regression: background trade notifications must send the REAL secret, not the mask.

get_notification_settings() masks every encrypted secret (telegram_token,
email_pass, slack/discord webhooks) with SECRET_PLACEHOLDER so the secret never
leaves the server toward the UI. The background senders run server-side and were
trusting that masked dict, so a real trade posted the literal "********" as the
token and silently failed — even though "Send Test" worked (it has its own
fallback to the decrypted value).

This test pins the contract: the real token reaches the Telegram API.
"""
from unittest.mock import patch


def _setup_db(tmp_path, monkeypatch):
    import server.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "notif.db")
    db.init_db()
    return db


def test_send_telegram_uses_real_token_not_mask(tmp_path, monkeypatch):
    db = _setup_db(tmp_path, monkeypatch)
    db.set_app_config("telegram_enabled", "true")
    db.set_app_config("telegram_chat_id", "123456")
    db.set_app_config_secure("telegram_token", "REAL-BOT-TOKEN-abc123")
    db.set_app_config("notify_on_trade", "true")

    # Sanity: the settings dict the UI sees DOES mask the token.
    assert db.get_notification_settings()["telegram_token"] == db.SECRET_PLACEHOLDER

    from server import notifications

    sent = {}

    def fake_send(token, chat_id, text):
        sent["token"] = token
        sent["chat_id"] = chat_id

    with patch.object(notifications, "send_telegram_direct", fake_send):
        notifications._send_telegram("hello")

    assert sent.get("token") == "REAL-BOT-TOKEN-abc123", (
        f"expected real token, got {sent.get('token')!r} "
        "(the mask leaked into the live send path)"
    )
    assert sent.get("chat_id") == "123456"


def test_send_telegram_skips_when_disabled(tmp_path, monkeypatch):
    db = _setup_db(tmp_path, monkeypatch)
    db.set_app_config("telegram_enabled", "false")
    db.set_app_config_secure("telegram_token", "REAL-BOT-TOKEN-abc123")
    db.set_app_config("telegram_chat_id", "123456")

    from server import notifications
    with patch.object(notifications, "send_telegram_direct") as m:
        notifications._send_telegram("hello")
    m.assert_not_called()


def test_send_telegram_skips_when_no_token(tmp_path, monkeypatch):
    db = _setup_db(tmp_path, monkeypatch)
    db.set_app_config("telegram_enabled", "true")
    db.set_app_config("telegram_chat_id", "123456")
    # No token stored.

    from server import notifications
    with patch.object(notifications, "send_telegram_direct") as m:
        notifications._send_telegram("hello")
    m.assert_not_called()
