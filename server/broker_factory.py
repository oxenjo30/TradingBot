"""
Returns the correct AccountClient subclass for a given broker string.
Add new brokers here — engine.py and main.py stay unchanged.
"""

from typing import Literal


def get_account_client(broker: str, api_key: str, api_secret: str, paper: bool,
                       account_id: int | None = None):
    """Return an AccountClient instance for the given broker."""
    broker = (broker or "alpaca").lower()

    if broker == "alpaca":
        from .alpaca_client import AccountClient
        return AccountClient(api_key=api_key, api_secret=api_secret, paper=paper,
                             account_id=account_id)

    if broker == "tradier":
        from .tradier_client import TradierAccountClient
        return TradierAccountClient(api_key=api_key, api_secret=api_secret, paper=paper,
                                    account_id=account_id)

    if broker == "binance":
        from .binance_client import BinanceAccountClient
        return BinanceAccountClient(api_key=api_key, api_secret=api_secret, paper=paper,
                                    account_id=account_id)

    raise ValueError(f"Unsupported broker: {broker!r}. Supported: alpaca, tradier, binance")


def supports_automation(client) -> bool:
    """Broker capability gate (spec §19.4).

    An adapter may drive automated execution ONLY if it can provide authoritative
    order lookup by broker/client id and authoritative (or monotonic-synthetic)
    fills. Adapters advertise this via `supports_authoritative_lookup` AND by
    implementing get_order / get_order_by_client_id / get_order_fills. A client that
    lacks any of these is UNSUPPORTED and automation must fail closed."""
    if not getattr(client, "supports_authoritative_lookup", False):
        return False
    return all(callable(getattr(client, m, None))
               for m in ("get_order", "get_order_by_client_id", "get_order_fills"))
