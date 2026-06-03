# tests/test_license_deactivate_guard.py
"""The license-deactivation endpoint was REMOVED entirely: the only code path
that could clear the stored license_key (DELETE /api/license -> set_license_key(""))
repeatedly locked the owner out. There is no longer any way to clear the license
through the app, so it can never be accidentally wiped."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import server.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "deact.db")
    monkeypatch.setattr("server.auth.password_is_set", lambda: False)
    monkeypatch.setattr("server.auth.setup_complete", lambda: False)
    with patch("server.engine.start"), patch("server.engine.shutdown"):
        from server.main import app
        with TestClient(app, raise_server_exceptions=True) as tc:
            from tests.conftest import mint_test_key
            import server.license as lic
            lic.activate_license(mint_test_key())
            yield tc, db, lic


def test_delete_license_endpoint_is_gone(client):
    """DELETE /api/license must no longer exist (405 Method Not Allowed or 404),
    and must NOT clear the stored key under any circumstances."""
    tc, db, lic = client
    assert db.get_license_key()  # key present
    # Try every shape of deactivate request — none may clear the key.
    for body in (None, {}, {"confirm": True}):
        r = tc.request("DELETE", "/api/license", json=body) if body is not None \
            else tc.request("DELETE", "/api/license")
        assert r.status_code in (404, 405), (
            f"DELETE /api/license should be gone, got {r.status_code}"
        )
        assert db.get_license_key(), "the license key must remain intact"
