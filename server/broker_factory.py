"""
Returns the correct AccountClient subclass for a given broker string.
Add new brokers here — engine.py and main.py stay unchanged.
"""

from typing import Literal


def get_account_client(broker: str, api_key: str, api_secret: str, paper: bool):
    """Return an AccountClient instance for the given broker."""
    broker = (broker or "alpaca").lower()

    if broker == "alpaca":
        from .alpaca_client import AccountClient
        return AccountClient(api_key=api_key, api_secret=api_secret, paper=paper)

    if broker == "tradier":
        from .tradier_client import TradierAccountClient
        return TradierAccountClient(api_key=api_key, api_secret=api_secret, paper=paper)

    raise ValueError(f"Unsupported broker: {broker!r}. Supported: alpaca, tradier")
