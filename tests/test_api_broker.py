"""API endpoint tests for /api/broker-accounts."""
import pytest
from unittest.mock import patch, MagicMock


BASE = "/api/broker-accounts"


def _create(client, label="Test", key="TESTKEY1234", secret="TESTSECRET56", acct_type="paper"):
    r = client.post(BASE, json={
        "label": label, "api_key": key, "api_secret": secret, "account_type": acct_type
    })
    assert r.status_code == 201, r.text
    return r.json()


# ── list ───────────────────────────────────────────────────────────────────────

def test_list_empty(client):
    r = client.get(BASE)
    assert r.status_code == 200
    assert r.json() == []


# ── create ─────────────────────────────────────────────────────────────────────

def test_create_returns_masked_key(client):
    data = _create(client, key="TESTKEY1234")
    assert data["label"] == "Test"
    assert data["account_type"] == "paper"
    assert data["api_key"].startswith("****")
    assert data["api_key"].endswith("1234")  # last 4 chars of plaintext key
    assert "api_secret" not in data


def test_create_live_account(client):
    data = _create(client, label="Live", acct_type="live")
    assert data["account_type"] == "live"


def test_create_duplicate_label_returns_400(client):
    _create(client, label="Dup")
    r = client.post(BASE, json={
        "label": "Dup", "api_key": "K2", "api_secret": "S2", "account_type": "paper"
    })
    assert r.status_code == 400


# ── get single ────────────────────────────────────────────────────────────────

def test_get_account(client):
    created = _create(client, label="GetMe")
    r = client.get(f"{BASE}/{created['id']}")
    assert r.status_code == 200
    assert r.json()["label"] == "GetMe"


def test_get_account_not_found(client):
    assert client.get(f"{BASE}/9999").status_code == 404


# ── patch ─────────────────────────────────────────────────────────────────────

def test_patch_label(client):
    acct_id = _create(client, label="PatchMe")["id"]
    r = client.patch(f"{BASE}/{acct_id}", json={"label": "Patched"})
    assert r.status_code == 200
    assert r.json()["label"] == "Patched"


def test_patch_account_type(client):
    acct_id = _create(client, label="TypeChange")["id"]
    r = client.patch(f"{BASE}/{acct_id}", json={"account_type": "live"})
    assert r.status_code == 200
    assert r.json()["account_type"] == "live"


def test_patch_empty_body_returns_422(client):
    acct_id = _create(client)["id"]
    r = client.patch(f"{BASE}/{acct_id}", json={})
    assert r.status_code == 422


def test_patch_not_found(client):
    assert client.patch(f"{BASE}/9999", json={"label": "x"}).status_code == 404


# ── rotate credentials ────────────────────────────────────────────────────────

def test_rotate_credentials_updates_masked_key(client):
    acct_id = _create(client, key="OLDKEYABCD")["id"]
    r = client.put(f"{BASE}/{acct_id}/credentials", json={
        "api_key": "NEWKEYwxyz", "api_secret": "NEWSECRET99"
    })
    assert r.status_code == 200
    assert r.json()["api_key"].endswith("wxyz")  # last 4 of "NEWKEYwxyz"


def test_rotate_credentials_not_found(client):
    r = client.put(f"{BASE}/9999/credentials", json={
        "api_key": "K", "api_secret": "S"
    })
    assert r.status_code == 404


# ── assignments ───────────────────────────────────────────────────────────────

def test_assignments_empty(client):
    acct_id = _create(client)["id"]
    r = client.get(f"{BASE}/{acct_id}/assignments")
    assert r.status_code == 200
    assert r.json() == {"strategies": []}


def test_assignments_not_found(client):
    assert client.get(f"{BASE}/9999/assignments").status_code == 404


# ── status (live Alpaca call — mocked) ────────────────────────────────────────

def test_status_success(client):
    acct_id = _create(client)["id"]
    mock_summary = {
        "equity": 10000.0, "cash": 5000.0, "buying_power": 5000.0,
        "daytrade_count": 0, "pdt_protection": False,
        "portfolio_value": 10000.0, "last_equity": 9800.0,
        "long_market_value": 5000.0, "short_market_value": 0.0,
        "initial_margin": 0.0, "maintenance_margin": 0.0,
    }
    with patch("server.alpaca_client.AccountClient") as MockAC:
        MockAC.return_value.get_account_summary.return_value = mock_summary
        r = client.get(f"{BASE}/{acct_id}/status")
    assert r.status_code == 200
    assert r.json()["equity"] == 10000.0


def test_status_bad_credentials_returns_400(client):
    acct_id = _create(client)["id"]
    with patch("server.alpaca_client.AccountClient") as MockAC:
        MockAC.return_value.get_account_summary.side_effect = Exception("auth failed")
        r = client.get(f"{BASE}/{acct_id}/status")
    assert r.status_code == 400


def test_status_not_found(client):
    assert client.get(f"{BASE}/9999/status").status_code == 404


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete_account(client):
    acct_id = _create(client, label="DeleteMe")["id"]
    assert client.delete(f"{BASE}/{acct_id}").status_code == 200
    assert client.get(f"{BASE}/{acct_id}").status_code == 404


def test_delete_not_found(client):
    assert client.delete(f"{BASE}/9999").status_code == 404
