# tests/test_license_api.py
import os
from tests.conftest import mint_test_key

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

import server.auth as _auth
_auth.password_is_set = lambda: False
_auth.setup_complete  = lambda: False


@pytest.fixture
def client(tmp_path, monkeypatch):
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    with patch("server.engine.start"), patch("server.engine.shutdown"):
        from server.main import app
        with TestClient(app, raise_server_exceptions=True) as tc:
            yield tc


def test_get_license_status_no_key(client):
    r = client.get("/api/license/status")
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is False
    assert "reason" in data


def test_activate_license_bad_key(client):
    r = client.post("/api/license/activate", json={"key": "notakey"})
    assert r.status_code == 422


def test_license_status_after_valid_key(client):
    key = mint_test_key(machine_id="ANY", days=30)
    r = client.post("/api/license/activate", json={"key": key})
    assert r.status_code == 200
    assert r.json()["valid"] is True


def test_license_status_without_key_returns_invalid(tmp_path, monkeypatch):
    """License status endpoint returns valid=False when no key is stored."""
    import server.db as db_mod
    monkeypatch.setenv("TRADEBOT_DB", str(tmp_path / "no_lic.db"))
    db_mod.init_db()
    import server.auth as auth_mod
    monkeypatch.setattr(auth_mod, "password_is_set", lambda: False)
    monkeypatch.setattr(auth_mod, "setup_complete", lambda: False)
    from fastapi.testclient import TestClient
    from server.main import app as _app
    c = TestClient(_app)
    r = c.get("/api/license/status")
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_delete_license_deactivates(tmp_path, monkeypatch):
    """DELETE /api/license clears the stored key."""
    import server.db as db_mod
    monkeypatch.setenv("TRADEBOT_DB", str(tmp_path / "deact.db"))
    db_mod.init_db()
    import server.auth as auth_mod
    monkeypatch.setattr(auth_mod, "password_is_set", lambda: False)
    monkeypatch.setattr(auth_mod, "setup_complete", lambda: False)
    db_mod.set_license_key(mint_test_key(machine_id="ANY", days=30))
    from fastapi.testclient import TestClient
    from server.main import app as _app
    c = TestClient(_app)
    # Deactivation now requires an explicit confirmation so a stray DELETE can't
    # silently lock the user out.
    r = c.request("DELETE", "/api/license", json={"confirm": True})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert db_mod.get_license_key() == ""
