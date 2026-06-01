import hashlib
import hmac
import json
import os
import pytest
import sqlite3
from pathlib import Path


SIGNING_SECRET = "test-signing-secret-abc123"


def _make_signature(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


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


def test_count_issued_licenses(tmp_db):
    assert tmp_db.count_issued_licenses() == 0
    tmp_db.add_issued_license("order_c1", "count@test.com", "KEY-CNT")
    assert tmp_db.count_issued_licenses() == 1
    assert tmp_db.count_issued_licenses(search="count") == 1
    assert tmp_db.count_issued_licenses(search="nomatch") == 0


def test_get_issued_license_not_found(tmp_db):
    assert tmp_db.get_issued_license(9999) is None


def test_verify_signature_valid():
    from server.lemon import verify_signature
    body = b'{"meta":{"event_name":"order_created"}}'
    sig = _make_signature(body, SIGNING_SECRET)
    verify_signature(body, sig, SIGNING_SECRET)  # should not raise


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


from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    db_mod.init_db()
    # The webhook reads the signing secret from encrypted DB config
    # (Settings -> License Management), not from the env var.
    db_mod.set_app_config_secure("lemon_signing_secret", SIGNING_SECRET)
    # License signing key is provided by the conftest test keypair (TRADEBOT_LICENSE_PRIVATE_KEY).
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
