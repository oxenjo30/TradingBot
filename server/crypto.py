from cryptography.fernet import Fernet, InvalidToken
import os, logging

log = logging.getLogger(__name__)
_fernet: Fernet | None = None


def init_crypto() -> None:
    """Load and validate DB_SECRET_KEY. No-op if key is absent — encrypt()/decrypt() will raise instead."""
    global _fernet
    raw = os.environ.get("DB_SECRET_KEY", "")
    if not raw:
        log.warning("DB_SECRET_KEY not set — broker credential encryption unavailable.")
        return
    reinit = _fernet is not None
    try:
        _fernet = Fernet(raw.encode())
        log.info("DB_SECRET_KEY loaded and validated%s.", " (re-initialised)" if reinit else "")
    except Exception as exc:
        raise RuntimeError(
            "DB_SECRET_KEY is not a valid Fernet key. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        ) from exc


def generate_key() -> str:
    """Generate a new Fernet key. Used by setup_complete() on first run."""
    return Fernet.generate_key().decode()


def encrypt(plaintext: str) -> str:
    if _fernet is None:
        raise RuntimeError("crypto not initialised — DB_SECRET_KEY missing or invalid")
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if _fernet is None:
        raise RuntimeError("crypto not initialised — DB_SECRET_KEY missing or invalid")
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Failed to decrypt credential — ciphertext is invalid or the key has changed."
        ) from exc
