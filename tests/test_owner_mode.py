# tests/test_owner_mode.py
"""Owner-mode gate: /api/admin/* returns 403 unless TRADEBOT_OWNER_MODE is set."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


def test_owner_mode_enabled_truthy(monkeypatch):
    import server.main as main
    for val in ("1", "true", "yes", "TRUE", "Yes"):
        monkeypatch.setenv("TRADEBOT_OWNER_MODE", val)
        assert main.owner_mode_enabled() is True


def test_owner_mode_enabled_falsy(monkeypatch):
    import server.main as main
    monkeypatch.delenv("TRADEBOT_OWNER_MODE", raising=False)
    assert main.owner_mode_enabled() is False
    for val in ("", "0", "no", "off", "false"):
        monkeypatch.setenv("TRADEBOT_OWNER_MODE", val)
        assert main.owner_mode_enabled() is False


def test_admin_licenses_403_when_not_owner(client, monkeypatch):
    monkeypatch.delenv("TRADEBOT_OWNER_MODE", raising=False)
    r = client.get("/api/admin/licenses")
    assert r.status_code == 403


def test_admin_licenses_200_when_owner(client, monkeypatch):
    monkeypatch.setenv("TRADEBOT_OWNER_MODE", "1")
    r = client.get("/api/admin/licenses")
    assert r.status_code == 200
    assert "licenses" in r.json()


def test_admin_revoke_404_when_owner(client, monkeypatch):
    """Happy path through the owner gate on a POST admin endpoint: gate passes,
    handler runs (404 for an unknown id — not 403)."""
    monkeypatch.setenv("TRADEBOT_OWNER_MODE", "1")
    r = client.post("/api/admin/licenses/999999/revoke")
    assert r.status_code == 404


def test_admin_endpoint_401_not_403_when_unauthenticated(tmp_path, monkeypatch):
    """Auth fires before the owner check: an unauthenticated caller must get 401,
    never 403 (which would leak that the endpoint exists). Owner mode is ON to
    prove the 401 comes from _require_auth, not the owner gate."""
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "owner_401.db")
    monkeypatch.setenv("TRADEBOT_OWNER_MODE", "1")
    with patch("server.auth.password_is_set", return_value=False), \
         patch("server.auth.setup_complete", return_value=True):
        with patch("server.engine.start"), patch("server.engine.shutdown"):
            from server.main import app
            with TestClient(app, raise_server_exceptions=True) as tc:
                r = tc.get("/api/admin/licenses")
    assert r.status_code == 401


def test_admin_export_403_when_not_owner(client, monkeypatch):
    monkeypatch.delenv("TRADEBOT_OWNER_MODE", raising=False)
    r = client.get("/api/admin/licenses/export")
    assert r.status_code == 403


def test_admin_resend_403_when_not_owner(client, monkeypatch):
    monkeypatch.delenv("TRADEBOT_OWNER_MODE", raising=False)
    r = client.post("/api/admin/licenses/1/resend")
    assert r.status_code == 403


def test_admin_revoke_403_when_not_owner(client, monkeypatch):
    monkeypatch.delenv("TRADEBOT_OWNER_MODE", raising=False)
    r = client.post("/api/admin/licenses/1/revoke")
    assert r.status_code == 403


def test_lemon_config_get_403_when_not_owner(client, monkeypatch):
    monkeypatch.delenv("TRADEBOT_OWNER_MODE", raising=False)
    r = client.get("/api/admin/lemon-config")
    assert r.status_code == 403


def test_lemon_config_patch_403_when_not_owner(client, monkeypatch):
    monkeypatch.delenv("TRADEBOT_OWNER_MODE", raising=False)
    r = client.patch("/api/admin/lemon-config", json={"signing_secret": "x"})
    assert r.status_code == 403


def test_app_info_reports_owner_mode(client, monkeypatch):
    monkeypatch.setenv("TRADEBOT_OWNER_MODE", "1")
    r = client.get("/api/app-info")
    assert r.status_code == 200
    assert r.json()["owner_mode"] is True

    monkeypatch.delenv("TRADEBOT_OWNER_MODE", raising=False)
    r = client.get("/api/app-info")
    assert r.status_code == 200
    assert r.json()["owner_mode"] is False


def test_app_info_401_when_unauthenticated(tmp_path, monkeypatch):
    """/api/app-info requires auth: unauthenticated callers get 401."""
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "appinfo_401.db")
    with patch("server.auth.password_is_set", return_value=False), \
         patch("server.auth.setup_complete", return_value=True):
        with patch("server.engine.start"), patch("server.engine.shutdown"):
            from server.main import app
            with TestClient(app, raise_server_exceptions=True) as tc:
                r = tc.get("/api/app-info")
    assert r.status_code == 401
