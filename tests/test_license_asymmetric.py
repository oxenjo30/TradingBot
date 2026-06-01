# tests/test_license_asymmetric.py
"""Ed25519 asymmetric licensing: mint with private key, verify with public key."""
import base64
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


def _make_keypair():
    """Return (private_b64, public_b64) raw Ed25519 keys, base64-encoded."""
    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(priv_raw).decode(), base64.b64encode(pub_raw).decode()


@pytest.fixture
def keypair(monkeypatch):
    priv_b64, pub_b64 = _make_keypair()
    monkeypatch.setenv("TRADEBOT_LICENSE_PRIVATE_KEY", priv_b64)
    # Patch the baked-in constant and clear the env override so verification
    # uses exactly this keypair regardless of the ambient environment.
    monkeypatch.delenv("TRADEBOT_LICENSE_PUBLIC_KEY", raising=False)
    import server.license as lic
    monkeypatch.setattr(lic, "LICENSE_PUBLIC_KEY", pub_b64)
    return priv_b64, pub_b64


def test_mint_then_verify_valid(keypair):
    import server.license as lic
    key = lic.mint_key(machine_id="ANY", days=30)
    result = lic.verify_key(key, machine_id="ANY")
    assert result["valid"] is True
    assert result["days_remaining"] > 0
    assert result["days_remaining"] <= 30


def test_expired_key_raises(keypair):
    import server.license as lic
    key = lic.mint_key(machine_id="ANY", days=-1)
    with pytest.raises(lic.LicenseError, match="expired"):
        lic.verify_key(key, machine_id="ANY")


def test_wrong_machine_raises(keypair):
    import server.license as lic
    key = lic.mint_key(machine_id="MACHINE-A", days=30)
    with pytest.raises(lic.LicenseError, match="machine"):
        lic.verify_key(key, machine_id="MACHINE-B")


def test_universal_key_verifies_anywhere(keypair):
    import server.license as lic
    key = lic.mint_key(machine_id="ANY", days=365)
    result = lic.verify_key(key, machine_id="SOME-REAL-MACHINE")
    assert result["valid"] is True


def test_tampered_payload_raises(keypair):
    import server.license as lic
    key = lic.mint_key(machine_id="ANY", days=30)
    bad = key[:-4] + "XXXX"
    with pytest.raises(lic.LicenseError, match="invalid"):
        lic.verify_key(bad, machine_id="ANY")


def test_wrong_public_key_rejects(monkeypatch):
    """A key minted under one private key fails verification under a different public key."""
    import server.license as lic
    priv_a, _pub_a = _make_keypair()
    _priv_b, pub_b = _make_keypair()
    monkeypatch.setenv("TRADEBOT_LICENSE_PRIVATE_KEY", priv_a)
    key = lic.mint_key(machine_id="ANY", days=30)
    monkeypatch.setattr(lic, "LICENSE_PUBLIC_KEY", pub_b)
    with pytest.raises(lic.LicenseError, match="invalid"):
        lic.verify_key(key, machine_id="ANY")


def test_mint_without_private_key_raises(monkeypatch):
    """Buyer build (no private key) physically cannot mint."""
    import server.license as lic
    monkeypatch.delenv("TRADEBOT_LICENSE_PRIVATE_KEY", raising=False)
    with pytest.raises(RuntimeError, match="private key"):
        lic.mint_key(machine_id="ANY", days=30)


def test_verify_with_no_public_key_configured(monkeypatch):
    """Buyer build with an empty/invalid public key surfaces a clear LicenseError, not a crash."""
    import server.license as lic
    priv, _pub = _make_keypair()
    monkeypatch.setenv("TRADEBOT_LICENSE_PRIVATE_KEY", priv)
    key = lic.mint_key(machine_id="ANY", days=30)
    monkeypatch.setattr(lic, "LICENSE_PUBLIC_KEY", "")
    monkeypatch.delenv("TRADEBOT_LICENSE_PUBLIC_KEY", raising=False)
    with pytest.raises(lic.LicenseError, match="verifier not configured"):
        lic.verify_key(key, machine_id="ANY")
