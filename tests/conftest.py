import base64
import os
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from unittest.mock import patch
from fastapi.testclient import TestClient

# ── Test license keypair ──────────────────────────────────────────────────────
# Generate a throwaway Ed25519 keypair ONCE at import time (conftest is imported
# before any test module). The private key signs test keys via mint_test_key();
# the public key is injected into server.license so verification succeeds.
_test_priv = Ed25519PrivateKey.generate()
_TEST_PRIVATE_B64 = base64.b64encode(
    _test_priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
).decode()
_TEST_PUBLIC_B64 = base64.b64encode(
    _test_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
).decode()
os.environ["TRADEBOT_LICENSE_PRIVATE_KEY"] = _TEST_PRIVATE_B64
os.environ["TRADEBOT_LICENSE_PUBLIC_KEY"] = _TEST_PUBLIC_B64


def mint_test_key(machine_id: str = "ANY", days: int = 365) -> str:
    """Mint a license key signed by the test keypair. Importable by any test module."""
    import server.license as lic
    return lic.mint_key(machine_id=machine_id, days=days)


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
            # Store a valid license key so _require_auth license check passes
            db_mod.set_license_key(mint_test_key())
            yield tc
