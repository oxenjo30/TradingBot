import os
import pytest
from cryptography.fernet import Fernet
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def fernet_key():
    """Generate a valid Fernet key once per session and initialise crypto."""
    key = Fernet.generate_key().decode()
    os.environ["DB_SECRET_KEY"] = key
    import server.crypto as crypto
    crypto.init_crypto()
    yield key


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient with an isolated SQLite DB per test. Engine threads are mocked."""
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    # Strip any real Alpaca keys so _migrate_env_account() is a no-op in tests
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    with patch("server.engine.start"), patch("server.engine.shutdown"):
        from server.main import app
        with TestClient(app, raise_server_exceptions=True) as tc:
            yield tc
