"""Unit tests for server/crypto.py — Fernet encryption module."""
import os
import pytest
from cryptography.fernet import Fernet


def test_encrypt_decrypt_roundtrip():
    from server import crypto
    plaintext = "my-secret-api-key-1234"
    assert crypto.decrypt(crypto.encrypt(plaintext)) == plaintext


def test_encrypt_produces_different_ciphertext_each_time():
    from server import crypto
    ct1 = crypto.encrypt("same-input")
    ct2 = crypto.encrypt("same-input")
    assert ct1 != ct2  # Fernet uses a random IV per encryption


def test_decrypt_invalid_token_raises_value_error():
    from server import crypto
    with pytest.raises(ValueError, match="Failed to decrypt"):
        crypto.decrypt("this-is-not-valid-ciphertext")


def test_decrypt_wrong_key_raises_value_error():
    from server import crypto
    # Encrypt with the current key, then switch keys and try to decrypt
    ct = crypto.encrypt("secret")
    other_key = Fernet.generate_key().decode()
    old_env = os.environ.get("DB_SECRET_KEY")
    try:
        os.environ["DB_SECRET_KEY"] = other_key
        import server.crypto as crypto_mod
        crypto_mod._fernet = Fernet(other_key.encode())
        with pytest.raises(ValueError):
            crypto_mod.decrypt(ct)
    finally:
        # Restore
        if old_env:
            os.environ["DB_SECRET_KEY"] = old_env
            crypto_mod._fernet = Fernet(old_env.encode())


def test_init_crypto_invalid_key_raises_runtime_error(monkeypatch):
    import server.crypto as crypto_mod
    monkeypatch.setenv("DB_SECRET_KEY", "not-a-valid-fernet-key")
    with pytest.raises(RuntimeError, match="not a valid Fernet key"):
        crypto_mod.init_crypto()
    # _fernet must be unchanged (still valid from session fixture)
    assert crypto_mod._fernet is not None


def test_init_crypto_missing_key_is_noop(monkeypatch):
    import server.crypto as crypto_mod
    prev = crypto_mod._fernet
    monkeypatch.delenv("DB_SECRET_KEY", raising=False)
    crypto_mod.init_crypto()  # should not raise
    # _fernet is left as-is when key is missing
    assert crypto_mod._fernet is prev


def test_generate_key_returns_valid_fernet_key():
    from server.crypto import generate_key
    key = generate_key()
    Fernet(key.encode())  # raises if invalid
