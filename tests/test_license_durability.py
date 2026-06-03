# tests/test_license_durability.py
"""Once a license key is accepted, it must stay accepted across restarts and
transient verifier-config problems — the user must never be re-asked for a key
they already validated.

The failure mode this guards against: verify_key() raises a CONFIGURATION error
(e.g. "verifier not configured" because the public key env wasn't loaded at some
startup, or a RuntimeError) — which previously returned valid=False and bounced
the user to the license screen, even though the very same key had been accepted
before. Genuine invalidity (expired / tampered / wrong machine) must STILL fail.
"""
import base64
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _keypair():
    p = Ed25519PrivateKey.generate()
    priv = base64.b64encode(p.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption())).decode()
    pub = base64.b64encode(p.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)).decode()
    return priv, pub


@pytest.fixture
def licensed(tmp_path, monkeypatch):
    """A DB with a freshly minted, accepted license under a known keypair."""
    import server.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "dur.db")
    db.init_db()
    priv, pub = _keypair()
    monkeypatch.setenv("TRADEBOT_LICENSE_PRIVATE_KEY", priv)
    monkeypatch.setenv("TRADEBOT_LICENSE_PUBLIC_KEY", pub)
    import server.license as lic
    monkeypatch.setattr(lic, "LICENSE_PUBLIC_KEY", pub)
    lic.invalidate_cache()
    key = lic.mint_key(machine_id="ANY", days=36500)
    # Activate it the way the API does (verify + store + record activation).
    lic.activate_license(key)
    return lic, db, key, priv, pub


def test_accepted_license_survives_verifier_not_configured(licensed, monkeypatch):
    """If the public key is missing on a later run, a previously-accepted key stays valid."""
    lic, db, key, priv, pub = licensed
    lic.invalidate_cache()
    # Simulate the verifier config being gone (e.g. baked key empty + env unset).
    monkeypatch.delenv("TRADEBOT_LICENSE_PUBLIC_KEY", raising=False)
    monkeypatch.setattr(lic, "LICENSE_PUBLIC_KEY", "")
    result = lic.check_stored_license()
    assert result["valid"] is True, (
        "a key that was already accepted must not lock the user out just because "
        "the verifier is temporarily unconfigured"
    )


def test_accepted_license_survives_private_key_runtime_error(licensed, monkeypatch):
    """A RuntimeError path must not lock out a previously-accepted key either."""
    lic, db, key, priv, pub = licensed
    lic.invalidate_cache()
    # Force _load_public_key to blow up with something unexpected.
    def boom():
        raise RuntimeError("transient")
    monkeypatch.setattr(lic, "_load_public_key", boom)
    result = lic.check_stored_license()
    assert result["valid"] is True


def test_expired_key_still_fails_even_if_previously_accepted(tmp_path, monkeypatch):
    """Grace must NOT cover genuine expiry — an expired key must still be rejected."""
    import server.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "exp.db")
    db.init_db()
    priv, pub = _keypair()
    monkeypatch.setenv("TRADEBOT_LICENSE_PRIVATE_KEY", priv)
    monkeypatch.setenv("TRADEBOT_LICENSE_PUBLIC_KEY", pub)
    import server.license as lic
    monkeypatch.setattr(lic, "LICENSE_PUBLIC_KEY", pub)
    lic.invalidate_cache()
    key = lic.mint_key(machine_id="ANY", days=-1)  # already expired
    # Storing/activating an expired key should not mark it accepted...
    try:
        lic.activate_license(key)
    except lic.LicenseError:
        pass
    db.set_license_key(key)  # ensure it's stored regardless
    lic.invalidate_cache()
    result = lic.check_stored_license()
    assert result["valid"] is False
    assert "expired" in result["reason"].lower()


def test_tampered_key_still_fails(licensed, monkeypatch):
    """A tampered key (valid verifier present) must still be rejected — grace is only
    for verifier-CONFIG errors, not signature failures."""
    lic, db, key, priv, pub = licensed
    bad = key[:-6] + "XXXXXX"
    db.set_license_key(bad)
    lic.invalidate_cache()
    result = lic.check_stored_license()
    assert result["valid"] is False
