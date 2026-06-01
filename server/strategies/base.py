from dataclasses import dataclass, field
from typing import Literal, ClassVar, Protocol, runtime_checkable

# ── Broker asset-class sets ────────────────────────────────────────────────────
# Add any new stock broker id here and it will automatically get all stock
# strategies without touching individual strategy files.
STOCK_BROKERS:  frozenset[str] = frozenset({"alpaca", "tradier", "ibkr", "schwab",
                                             "tastytrade", "robinhood", "webull",
                                             "fidelity", "etrade", "tradestation"})
CRYPTO_BROKERS: frozenset[str] = frozenset({"binance", "binanceus", "coinbase",
                                             "kraken"})


@runtime_checkable
class BarsProvider(Protocol):
    def get_bars(self, symbol: str, limit: int) -> list[dict]: ...


@dataclass
class Signal:
    symbol: str
    side: Literal["buy", "sell"]
    reason: str
    qty: float | None = None       # shares — set one or the other
    notional: float | None = None  # USD amount

    def __post_init__(self):
        if self.qty is None and self.notional is None:
            raise ValueError(f"Signal for {self.symbol}: qty or notional required")


class Strategy:
    name: ClassVar[str] = "base"
    label: ClassVar[str] = "Base"
    description: ClassVar[str] = ""
    default_params: ClassVar[dict] = {}
    params_schema: ClassVar[list] = []
    auto_trade: ClassVar[bool] = True
    hidden: ClassVar[bool] = False  # if True, excluded from the bots UI list
    # "stock" = any broker in STOCK_BROKERS, "crypto" = any in CRYPTO_BROKERS,
    # or list explicit broker ids for mixed strategies.
    brokers: ClassVar[list[str]] = ["stock"]

    def __init__(self, params: dict):
        merged = dict(self.default_params)
        merged.update(params or {})
        self.params = merged

    def _signal(self, symbol: str, side: Literal["buy", "sell"], reason: str) -> Signal:
        """Build a Signal using this strategy's qty/notional params."""
        notional = self.params.get("notional")
        qty      = self.params.get("qty")
        if notional and float(notional) > 0:
            return Signal(symbol=symbol, side=side, reason=reason,
                          notional=float(notional))
        return Signal(symbol=symbol, side=side, reason=reason,
                      qty=float(qty) if qty else 1.0)

    def evaluate(self, positions: dict[str, float], client=None) -> list[Signal]:
        return []

    def _get_bars(self, client, symbol: str, days: int) -> list[dict]:
        """Fetch bars from the account's broker client, falling back to alpaca."""
        if client is not None and hasattr(client, "get_recent_bars"):
            return client.get_recent_bars(symbol, days=days)
        from .. import alpaca_client
        return alpaca_client.get_recent_bars(symbol, days=days)

    @classmethod
    def describe(cls) -> dict:
        return {
            "name": cls.name,
            "label": cls.label,
            "description": cls.description,
            "default_params": cls.default_params,
            "params_schema": cls.params_schema,
            "auto_trade": cls.auto_trade,
            "hidden": cls.hidden,
            "brokers": cls.brokers,
        }
