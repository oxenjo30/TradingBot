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

    def __init__(self, api_key: str, api_secret: str, paper: bool, account_id: int | None = None):
        self._paper = paper
        self._account_id = account_id
        self._exchange = ccxt.binance({
            "apiKey":  api_key,
            "secret":  api_secret,
            "options": {"defaultType": "spot"},
        })
        if paper:
            # Use ccxt's built-in demo trading mode for demo.binance.com keys.
            # This switches URLs to demo-api.binance.com and tells ccxt to skip
            # sapi endpoints that demo doesn't support.
            self._exchange.enable_demo_trading(True)

        # Widen recvWindow and sync clock offset to handle minor system clock drift.
        self._exchange.options["recvWindow"] = 10000
        self._exchange.load_time_difference()

    def _ensure_markets(self):
        """Load markets on first use — avoids slow network call on construction."""
        if not self._exchange.markets:
            self._exchange.load_markets()

    def get_account_summary(self) -> dict:
        from . import db as _db
        balance = self._exchange.fetch_balance()
        usdt_free  = float((balance.get("free")  or {}).get("USDT", 0) or 0)
        usdt_total = float((balance.get("total") or {}).get("USDT", 0) or 0)

        # Value non-USDT holdings at current price (best-effort; skip on error)
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

        # Realized P&L from our own cost basis tracking
        realized_pnl = 0.0
        if self._account_id is not None:
            try:
                realized_pnl = _db.crypto_get_realized_pnl(self._account_id)
            except Exception:
                pass

        return {
            "status":             "active",
            "cash":               usdt_free,
            "equity":             equity,
            "last_equity":        equity,
            "buying_power":       usdt_free,
            "portfolio_value":    equity,
            "day_pl":             realized_pnl,
            "day_pl_pct":         0.0,
            "realized_pnl":       realized_pnl,
            "pattern_day_trader": False,
            "trading_blocked":    False,
            "account_type":       "paper" if self._paper else "live",
            "currency":           "USDT",
        }

    def get_day_trade_count(self) -> int:
        return 0

    def get_positions(self) -> list[dict]:
        from . import db as _db
        balance = self._exchange.fetch_balance()
        totals  = balance.get("total") or {}

        # Load our own cost basis so we can compute real unrealized P&L
        cost_rows = {}
        if self._account_id is not None:
            for cb in _db.crypto_get_cost_basis(self._account_id):
                cost_rows[cb["symbol"].upper()] = cb

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

            cb = cost_rows.get(asset.upper(), {})
            avg_cost = float(cb.get("cost", 0) or 0)
            cb_qty   = float(cb.get("qty", 0) or 0)
            if avg_cost > 0 and cb_qty > 0:
                cost_basis     = avg_cost * min(qty, cb_qty)
                unrealized_pl  = market_value - cost_basis
                unrealized_plpc = (unrealized_pl / cost_basis * 100) if cost_basis else 0.0
            else:
                unrealized_pl  = 0.0
                unrealized_plpc = 0.0

            out.append({
                "symbol":          asset,
                "qty":             qty,
                "side":            "long",
                "avg_entry_price": avg_cost,
                "current_price":   price,
                "market_value":    market_value,
                "unrealized_pl":   unrealized_pl,
                "unrealized_plpc": unrealized_plpc,
                "change_today":    0.0,
            })
        return out

    def get_recent_bars(self, symbol: str, days: int = 60) -> list[dict]:
        from datetime import datetime, timezone
        self._ensure_markets()
        ohlcv = self._exchange.fetch_ohlcv(_to_ccxt(symbol), "1d", limit=days)
        out = []
        for row in ohlcv:
            ts_ms, o, h, l, c, v = row
            t = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
            out.append({"t": t, "o": float(o), "h": float(h),
                        "l": float(l), "c": float(c), "v": float(v)})
        return out

    def get_latest_quote(self, symbol: str) -> dict:
        self._ensure_markets()
        book = self._exchange.fetch_order_book(_to_ccxt(symbol), limit=1)
        bid  = float(book["bids"][0][0]) if book.get("bids") else 0.0
        ask  = float(book["asks"][0][0]) if book.get("asks") else 0.0
        mid  = (bid + ask) / 2 if (bid and ask) else (bid or ask)
        return {"symbol": _from_ccxt(_to_ccxt(symbol)), "bid": bid, "ask": ask, "price": mid}

    def submit_market_order(self, symbol: str, side: Literal["buy", "sell"],
                            qty: float | None = None,
                            notional: float | None = None,
                            client_order_id: str | None = None) -> dict:
        if qty is None and notional is None:
            raise ValueError("qty or notional required")

        self._ensure_markets()
        ccxt_sym = _to_ccxt(symbol)
        params: dict = {}
        if client_order_id:
            params["newClientOrderId"] = client_order_id[:36]

        if notional is not None and qty is None:
            params["quoteOrderQty"] = float(notional)
            order = self._exchange.create_order(ccxt_sym, "market", side, None, params=params)
        else:
            order = self._exchange.create_order(ccxt_sym, "market", side, float(qty), params=params)

        return {
            "id":     str(order.get("id", "")),
            "symbol": _from_ccxt(ccxt_sym),
            "side":   side,
            "qty":    float(order.get("filled") or order.get("amount") or qty or 0),
            "status": "filled" if order.get("status") in ("closed", "filled") else str(order.get("status", "")),
        }

    def submit_limit_order(self, symbol: str, side: Literal["buy", "sell"],
                           qty: float, limit_price: float,
                           client_order_id: str | None = None) -> dict:
        self._ensure_markets()
        ccxt_sym = _to_ccxt(symbol)
        params: dict = {}
        if client_order_id:
            params["newClientOrderId"] = client_order_id[:36]

        order = self._exchange.create_order(ccxt_sym, "limit", side, float(qty), limit_price, params=params)
        return {
            "id":          str(order.get("id", "")),
            "symbol":      _from_ccxt(ccxt_sym),
            "side":        side,
            "qty":         float(qty),
            "limit_price": round(float(limit_price), 8),
            "status":      str(order.get("status", "open")),
        }

    def get_orders(self, limit: int = 50, status: str = "all") -> list[dict]:
        from datetime import datetime, timezone
        from . import db as _db

        def _normalise(o: dict) -> dict:
            ts = o.get("datetime") or ""
            filled_ts = o.get("lastTradeTimestamp")
            filled_at = (datetime.fromtimestamp(filled_ts / 1000, tz=timezone.utc).isoformat()
                         if filled_ts else None)
            return {
                "id":               str(o.get("id", "")),
                "client_order_id":  o.get("clientOrderId", ""),
                "symbol":           _from_ccxt(o.get("symbol", "")),
                "side":             str(o.get("side", "")).lower(),
                "qty":              float(o.get("amount") or 0),
                "filled_qty":       float(o.get("filled") or 0),
                "filled_avg_price": float(o.get("average") or 0) or None,
                "type":             str(o.get("type", "market")).lower(),
                "status":           str(o.get("status", "")).lower(),
                "submitted_at":     ts,
                "filled_at":        filled_at,
            }

        # open-only: Binance supports fetch_open_orders() without a symbol
        if status == "open":
            try:
                raw = self._exchange.fetch_open_orders()
                return [_normalise(o) for o in raw[:limit]]
            except Exception:
                return []

        # all/closed: Binance requires a symbol for fetch_orders().
        # Collect every symbol traded on this account from the signals log,
        # then fan out one call per symbol and merge the results.
        try:
            acct_id = getattr(self, "_account_id", None)
            with _db.get_conn() as c:
                if acct_id is not None:
                    rows = c.execute(
                        "SELECT DISTINCT symbol FROM signals WHERE account_id=? ORDER BY id DESC",
                        (acct_id,),
                    ).fetchall()
                else:
                    rows = c.execute(
                        "SELECT DISTINCT symbol FROM signals ORDER BY id DESC"
                    ).fetchall()
            symbols = [r["symbol"] for r in rows]
        except Exception:
            symbols = []

        raw_all: list[dict] = []
        for sym in symbols:
            ccxt_sym = _to_ccxt(sym)
            try:
                orders = self._exchange.fetch_orders(ccxt_sym)
                raw_all.extend(orders)
            except Exception:
                pass

        # Sort newest-first and apply status filter
        raw_all.sort(key=lambda o: o.get("timestamp") or 0, reverse=True)
        if status == "closed":
            raw_all = [o for o in raw_all if o.get("status") in ("closed", "canceled", "filled")]

        return [_normalise(o) for o in raw_all[:limit]]

    def cancel_order(self, order_id: str) -> dict:
        result = self._exchange.cancel_order(order_id)
        return {
            "id":     str(result.get("id", order_id)),
            "status": str(result.get("status", "canceled")),
        }

    def close_position(self, symbol: str) -> None:
        positions = self.get_positions()
        for p in positions:
            if p["symbol"].upper() == symbol.upper():
                self.submit_market_order(symbol, "sell", qty=p["qty"])
                return
        raise ValueError(f"No open position for {symbol}")
