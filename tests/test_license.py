# tests/test_license.py
import pytest
from server.license import (
    get_machine_id, mint_key, verify_key, LicenseError
)

SELLER_SECRET = "test-seller-secret-32-chars-long!"

def test_machine_id_is_stable():
    assert get_machine_id() == get_machine_id()
    assert len(get_machine_id()) == 64  # sha256 hex

def test_mint_and_verify_valid_key():
    key = mint_key(SELLER_SECRET, machine_id="ANY", days=30)
    result = verify_key(key, SELLER_SECRET, machine_id="ANY")
    assert result["valid"] is True
    assert result["days_remaining"] > 0

def test_expired_key_raises():
    key = mint_key(SELLER_SECRET, machine_id="ANY", days=-1)
    with pytest.raises(LicenseError, match="expired"):
        verify_key(key, SELLER_SECRET, machine_id="ANY")

def test_wrong_machine_raises():
    key = mint_key(SELLER_SECRET, machine_id="MACHINE-A", days=30)
    with pytest.raises(LicenseError, match="machine"):
        verify_key(key, SELLER_SECRET, machine_id="MACHINE-B")

def test_tampered_key_raises():
    key = mint_key(SELLER_SECRET, machine_id="ANY", days=30)
    bad = key[:-4] + "XXXX"
    with pytest.raises(LicenseError, match="invalid"):
        verify_key(bad, SELLER_SECRET, machine_id="ANY")

def test_universal_key():
    key = mint_key(SELLER_SECRET, machine_id="ANY", days=365)
    result = verify_key(key, SELLER_SECRET, machine_id="SOME-REAL-MACHINE")
    assert result["valid"] is True

def test_store_and_retrieve_license(tmp_path, monkeypatch):
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    db_mod.init_db()
    from server.db import set_license_key, get_license_key
    assert get_license_key() == ""
    set_license_key("MYKEY123")
    assert get_license_key() == "MYKEY123"
