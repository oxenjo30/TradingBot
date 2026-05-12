# tests/test_license_api.py
import os
os.environ.setdefault("TRADEBOT_LICENSE_SECRET", "test-secret-32-chars-seller-key!!")

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

import server.auth as _auth
_auth.password_is_set = lambda: False


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
    import server.license as lic_mod
    key = lic_mod.mint_key("test-secret-32-chars-seller-key!!", "ANY", 30)
    r = client.post("/api/license/activate", json={"key": key})
    assert r.status_code == 200
    assert r.json()["valid"] is True
