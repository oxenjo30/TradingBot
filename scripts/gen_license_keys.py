"""Generate an Ed25519 license-signing keypair for TradeBot (owner use only).

Run once on the owner's machine:

    python scripts/gen_license_keys.py

- PRIVATE key  -> paste into your owner .env as TRADEBOT_LICENSE_PRIVATE_KEY
                  (never commit it, never ship it to buyers).
- PUBLIC key   -> paste into server/license.py as the LICENSE_PUBLIC_KEY constant
                  (this is safe to ship — it can only verify, not mint).
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> None:
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
    priv_b64 = base64.b64encode(priv_raw).decode()
    pub_b64 = base64.b64encode(pub_raw).decode()

    print("=" * 70)
    print("TradeBot license keypair generated. Keep the PRIVATE key secret.")
    print("=" * 70)
    print()
    print("1) Owner .env (never commit / ship):")
    print(f"   TRADEBOT_LICENSE_PRIVATE_KEY={priv_b64}")
    print()
    print("2) server/license.py constant (safe to ship in builds):")
    print(f'   LICENSE_PUBLIC_KEY = "{pub_b64}"')
    print()


if __name__ == "__main__":
    main()
