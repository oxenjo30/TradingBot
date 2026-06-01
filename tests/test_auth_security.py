"""Regression tests for security fixes:
- Auth bypass when password_is_set=False but setup is complete
- Setup endpoint replay (POST /api/setup/complete twice → 409)
"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


# ── Auth bypass regression ─────────────────────────────────────────────────────

def test_auth_bypass_blocked_when_setup_complete(tmp_path, monkeypatch):
    """Protected endpoints must return 401 when password_is_set=False but setup is done.

    Regression test for: auth bypass when no password was set but setup was complete.
    Previously any endpoint was accessible without a session token in this state.

    Uses /api/positions which is guarded by _require_auth (unlike /api/strategies).
    """
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "bypass_test.db")

    with patch("server.auth.password_is_set", return_value=False), \
         patch("server.auth.setup_complete", return_value=True):
        with patch("server.engine.start"), patch("server.engine.shutdown"):
            from server.main import app
            with TestClient(app, raise_server_exceptions=True) as tc:
                r = tc.get("/api/positions")

    assert r.status_code == 401, (
        f"Expected 401 when setup complete but no password set, got {r.status_code}"
    )


def test_auth_allowed_during_onboarding(tmp_path, monkeypatch):
    """During initial onboarding (setup not complete, no password), setup-related
    endpoints must be reachable without authentication.
    """
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "onboard_test.db")

    with patch("server.auth.password_is_set", return_value=False), \
         patch("server.auth.setup_complete", return_value=False):
        with patch("server.engine.start"), patch("server.engine.shutdown"):
            from server.main import app
            with TestClient(app, raise_server_exceptions=True) as tc:
                # /api/health is accessible and reports setup state
                r = tc.get("/api/health")

    assert r.status_code == 200, (
        f"Expected 200 for /api/health during onboarding, got {r.status_code}"
    )


# ── Setup endpoint replay regression ──────────────────────────────────────────

def test_setup_complete_replay_returns_409(tmp_path, monkeypatch):
    """POST /api/setup/complete must return 409 if called a second time.

    Regression test for: credential-takeover via unauthenticated replay of setup endpoint.
    Previously anyone could POST to /api/setup/complete and overwrite the admin password.
    """
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "setup_replay.db")

    payload = {
        "broker": "alpaca",
        "api_key": "TESTKEY1234567890",
        "api_secret": "TESTSECRET1234567890123456789012",
        "account_type": "paper",
        "starter_strategy": "SMA Cross",
        "password": "hunter22",  # >= 8 chars (password minimum)
    }

    # The 409 guard in the endpoint calls auth.setup_complete() which reads from DB.
    # We simulate the state transition: first call returns False (setup not done yet),
    # second call returns True (setup_complete was written by the first POST).
    call_count = [0]
    def _setup_complete_stateful():
        call_count[0] += 1
        return call_count[0] > 1  # False on first call, True on subsequent calls

    with patch("server.auth.password_is_set", return_value=False), \
         patch("server.auth.setup_complete", side_effect=_setup_complete_stateful):
        with patch("server.engine.start"), patch("server.engine.shutdown"):
            from server.main import app
            with TestClient(app, raise_server_exceptions=False) as tc:
                r1 = tc.post("/api/setup/complete", json=payload)
                assert r1.status_code == 200, f"First setup call failed: {r1.text}"

                r2 = tc.post("/api/setup/complete", json=payload)
                assert r2.status_code == 409, (
                    f"Expected 409 on replay, got {r2.status_code}: {r2.text}"
                )
