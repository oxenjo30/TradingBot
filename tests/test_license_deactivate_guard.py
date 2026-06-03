# tests/test_license_deactivate_guard.py
"""DELETE /api/license must require an explicit confirmation, so the stored
license key can never be cleared by a stray/accidental request. The clearing
has repeatedly locked the owner out; deactivation must be deliberate."""
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
            # Store + activate a valid key via the conftest test keypair.
            from tests.conftest import mint_test_key
            import server.license as lic
            lic.activate_license(mint_test_key())
            yield tc, db, lic


def test_deactivate_without_confirmation_does_not_clear(client):
    tc, db, lic = client
    assert db.get_license_key()  # key present
    # A bare DELETE (no confirmation) must be REJECTED and must NOT clear the key.
    r = tc.request("DELETE", "/api/license")
    assert r.status_code == 400, "deactivate without confirmation must be rejected"
    assert db.get_license_key(), "the license key must remain intact"


def test_deactivate_with_confirmation_clears(client):
    tc, db, lic = client
    assert db.get_license_key()
    r = tc.request("DELETE", "/api/license", json={"confirm": True})
    assert r.status_code == 200
    assert db.get_license_key() == "", "explicit confirmed deactivate clears the key"
