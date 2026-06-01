# tests/test_owner_mode.py
"""Owner-mode gate: /api/admin/* returns 403 unless TRADEBOT_OWNER_MODE is set."""
import pytest


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


def test_admin_export_403_when_not_owner(client, monkeypatch):
    monkeypatch.delenv("TRADEBOT_OWNER_MODE", raising=False)
    r = client.get("/api/admin/licenses/export")
    assert r.status_code == 403


def test_lemon_config_403_when_not_owner(client, monkeypatch):
    monkeypatch.delenv("TRADEBOT_OWNER_MODE", raising=False)
    r = client.get("/api/admin/lemon-config")
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
