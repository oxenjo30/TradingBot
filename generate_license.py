"""
TradeBot License Key Generator -- SELLER USE ONLY
Run: python generate_license.py

Reads TRADEBOT_LICENSE_SECRET from environment (or prompts).
"""
import os
import sys


def main():
    secret = os.environ.get("TRADEBOT_LICENSE_SECRET", "").strip()
    if not secret:
        secret = input("Enter seller secret (never share this): ").strip()
    if len(secret) < 16:
        print("Secret must be at least 16 characters.")
        sys.exit(1)

    print("\n=== TradeBot License Generator ===")
    print("Machine ID (leave blank for universal key): ", end="")
    machine_id = input().strip() or "ANY"

    print("License duration in days (e.g. 365): ", end="")
    try:
        days = int(input().strip())
    except ValueError:
        print("Invalid number.")
        sys.exit(1)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from server.license import mint_key
    key = mint_key(secret, machine_id=machine_id, days=days)

    print("\n=== LICENSE KEY ===")
    print(key)
    print("==================")
    print(f"Machine : {machine_id}")
    print(f"Duration: {days} days")
    print("\nSend this key to the customer. Keep the seller secret private.")


if __name__ == "__main__":
    main()
