"""API endpoint tests for /api/strategies/{name}/accounts."""
import pytest

STRATEGY = "momentum"  # must exist in strategies.REGISTRY
UNKNOWN = "nonexistent_xyz"
BASE = f"/api/strategies/{STRATEGY}/accounts"


def _make_account(client, label="Test"):
    r = client.post("/api/broker-accounts", json={
        "label": label, "api_key": "KEY1234", "api_secret": "SEC5678", "account_type": "paper"
    })
    assert r.status_code == 201
    return r.json()["id"]


# ── list ───────────────────────────────────────────────────────────────────────

def test_list_empty(client):
    r = client.get(BASE)
    assert r.status_code == 200
    assert r.json() == []


def test_list_unknown_strategy(client):
    r = client.get(f"/api/strategies/{UNKNOWN}/accounts")
    assert r.status_code == 404


# ── assign ────────────────────────────────────────────────────────────────────

def test_assign_account(client):
    acct_id = _make_account(client)
    r = client.post(BASE, json={"account_id": acct_id, "enabled": True})
    assert r.status_code == 201
    assert any(row["id"] == acct_id for row in r.json())


def test_assign_returns_full_list(client):
    id1 = _make_account(client, "Acct1")
    id2 = _make_account(client, "Acct2")
    client.post(BASE, json={"account_id": id1, "enabled": True})
    r = client.post(BASE, json={"account_id": id2, "enabled": True})
    assert r.status_code == 201
    ids = [row["id"] for row in r.json()]
    assert id1 in ids and id2 in ids


def test_assign_duplicate_returns_409(client):
    acct_id = _make_account(client)
    client.post(BASE, json={"account_id": acct_id, "enabled": True})
    r = client.post(BASE, json={"account_id": acct_id, "enabled": True})
    assert r.status_code == 409


def test_assign_unknown_strategy_returns_404(client):
    acct_id = _make_account(client)
    r = client.post(f"/api/strategies/{UNKNOWN}/accounts",
                    json={"account_id": acct_id, "enabled": True})
    assert r.status_code == 404


def test_assign_unknown_account_returns_404(client):
    r = client.post(BASE, json={"account_id": 9999, "enabled": True})
    assert r.status_code == 404


# ── patch enabled ─────────────────────────────────────────────────────────────

def test_patch_enabled_false(client):
    acct_id = _make_account(client)
    client.post(BASE, json={"account_id": acct_id, "enabled": True})
    r = client.patch(f"{BASE}/{acct_id}", json={"enabled": False})
    assert r.status_code == 200
    row = next(row for row in r.json() if row["id"] == acct_id)
    assert row["enabled"] == 0


def test_patch_not_found_returns_404(client):
    r = client.patch(f"{BASE}/9999", json={"enabled": False})
    assert r.status_code == 404


# ── unassign ──────────────────────────────────────────────────────────────────

def test_unassign(client):
    acct_id = _make_account(client)
    client.post(BASE, json={"account_id": acct_id, "enabled": True})
    r = client.delete(f"{BASE}/{acct_id}")
    assert r.status_code == 200
    assert not any(row["id"] == acct_id for row in client.get(BASE).json())


def test_delete_account_cascades_from_strategy_view(client):
    acct_id = _make_account(client)
    client.post(BASE, json={"account_id": acct_id, "enabled": True})
    client.delete(f"/api/broker-accounts/{acct_id}")
    assert client.get(BASE).json() == []
