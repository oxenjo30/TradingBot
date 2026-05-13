"""
Binance spot broker adapter.

Matches the AccountClient interface from alpaca_client.py and tradier_client.py
so engine.py and main.py can use it interchangeably via broker_factory.py.
"""

from typing import Literal
import ccxt


def _to_ccxt(symbol: str) -> str:
    """Normalise bare ticker or concatenated pair to ccxt slash format.

    BTC       -> BTC/USDT
    BTCUSDT   -> BTC/USDT
    BTC/USDT  -> BTC/USDT  (idempotent)
    """
    s = symbol.upper()
    if "/" in s:
        return s
    if s.endswith("USDT"):
        return s[:-4] + "/USDT"
    return s + "/USDT"


def _from_ccxt(ccxt_symbol: str) -> str:
    """Strip slash quote suffix: BTC/USDT -> BTC."""
    return ccxt_symbol.split("/")[0]


class BinanceAccountClient:
    """
    Per-account Binance client. Same public interface as alpaca_client.AccountClient
    and tradier_client.TradierAccountClient.
    """

    def __init__(self, api_key: str, api_secret: str, paper: bool):
        self._paper = paper
        self._exchange = ccxt.binance({
            "apiKey":  api_key,
            "secret":  api_secret,
            "options": {"defaultType": "spot"},
        })
        if paper:
            self._exchange.set_sandbox_mode(True)
        self._exchange.load_markets()

    def get_account_summary(self) -> dict:
        balance = self._exchange.fetch_balance()
        usdt_free  = float(balance.get("free",  {}).get("USDT", 0) or 0)
        usdt_total = float(balance.get("total", {}).get("USDT", 0) or 0)

        crypto_value = 0.0
        for asset, qty in (balance.get("total") or {}).items():
            if asset == "USDT" or not qty or float(qty) <= 0:
                continue
            try:
                ticker = self._exchange.fetch_ticker(_to_ccxt(asset))
                crypto_value += float(qty) * float(ticker.get("last", 0) or 0)
            except Exception:
                pass

        equity = usdt_total + crypto_value
        return {
            "status":             "active",
            "cash":               usdt_free,
            "equity":             equity,
            "last_equity":        equity,
            "buying_power":       usdt_free,
            "portfolio_value":    equity,
            "day_pl":             0.0,
            "day_pl_pct":         0.0,
            "pattern_day_trader": False,
            "trading_blocked":    False,
            "account_type":       "paper" if self._paper else "live",
            "currency":           "USDT",
        }

    def get_day_trade_count(self) -> int:
        return 0

    def get_positions(self) -> list[dict]:
        balance = self._exchange.fetch_balance()
        totals  = balance.get("total") or {}
        out = []
        for asset, qty in totals.items():
            qty = float(qty or 0)
            if asset == "USDT" or qty < 0.000001:
                continue
            try:
                ticker       = self._exchange.fetch_ticker(_to_ccxt(asset))
                price        = float(ticker.get("last", 0) or 0)
                market_value = qty * price
            except Exception:
                price        = 0.0
                market_value = 0.0
            out.append({
                "symbol":          asset,
                "qty":             qty,
                "side":            "long",
                "avg_entry_price": 0.0,
                "current_price":   price,
                "market_value":    market_value,
                "unrealized_pl":   0.0,
                "unrealized_plpc": 0.0,
                "change_today":    0.0,
            })
        return out

    def get_recent_bars(self, symbol: str, days: int = 60) -> list[dict]:
        from datetime import datetime, timezone
        ohlcv = self._exchange.fetch_ohlcv(_to_ccxt(symbol), "1d", limit=days)
        out = []
        for row in ohlcv:
            ts_ms, o, h, l, c, v = row
            t = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
            out.append({"t": t, "o": float(o), "h": float(h),
                        "l": float(l), "c": float(c), "v": float(v)})
        return out

    def get_latest_quote(self, symbol: str) -> dict:
        book = self._exchange.fetch_order_book(_to_ccxt(symbol), limit=1)
        bid  = float(book["bids"][0][0]) if book.get("bids") else 0.0
        ask  = float(book["asks"][0][0]) if book.get("asks") else 0.0
        mid  = (bid + ask) / 2 if (bid and ask) else (bid or ask)
        return {"symbol": _from_ccxt(_to_ccxt(symbol)), "bid": bid, "ask": ask, "price": mid}
