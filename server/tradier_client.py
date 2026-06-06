"""
Tradier broker adapter.

Matches the AccountClient interface from alpaca_client.py so the engine and
main.py can use it interchangeably.

Tradier REST docs: https://documentation.tradier.com/brokerage-api
Paper (sandbox): https://sandbox.tradier.com/v1/
Live:            https://api.tradier.com/v1/
"""

from typing import Literal
import httpx

PAPER_BASE = "https://sandbox.tradier.com/v1"
LIVE_BASE  = "https://api.tradier.com/v1"


class TradierAccountClient:
    """
    Per-account Tradier client.  Same public interface as alpaca_client.AccountClient:
      get_account_summary()   -> dict (11 keys)
      get_day_trade_count()   -> int
      get_positions()         -> list[dict]
      submit_market_order()   -> dict
    """

    def __init__(self, api_key: str, api_secret: str, paper: bool):
        # Tradier uses a Bearer token; api_key is the access token, api_secret unused
        self._token = api_key
        self._paper = paper
        self._base  = PAPER_BASE if paper else LIVE_BASE
        self._account_id: str | None = None  # fetched lazily

    # ── internal helpers ───────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    @staticmethod
    def _raise_for_status(r: httpx.Response) -> None:
        """Like httpx.raise_for_status() but includes Tradier's response body in the
        message. Tradier returns the real reason (e.g. "Invalid parameter,
        quantity: must be greater than 0.") in the body, which the default
        raise_for_status() discards behind a generic 'Client error 400' link."""
        if r.is_success:
            return
        detail = (r.text or "").strip()
        if detail:
            raise httpx.HTTPStatusError(
                f"Tradier {r.status_code}: {detail}", request=r.request, response=r
            )
        r.raise_for_status()

    def _get(self, path: str, params: dict | None = None) -> dict:
        r = httpx.get(f"{self._base}{path}", headers=self._headers(),
                      params=params, timeout=15.0)
        self._raise_for_status(r)
        return r.json()

    def _post(self, path: str, data: dict) -> dict:
        r = httpx.post(f"{self._base}{path}", headers=self._headers(),
                       data=data, timeout=15.0)
        self._raise_for_status(r)
        return r.json()

    def _delete(self, path: str) -> dict:
        r = httpx.delete(f"{self._base}{path}", headers=self._headers(), timeout=15.0)
        self._raise_for_status(r)
        return r.json()

    def _account_id_str(self) -> str:
        if self._account_id:
            return self._account_id
        data = self._get("/user/profile")
        accounts = data.get("profile", {}).get("account", [])
        if isinstance(accounts, dict):
            accounts = [accounts]
        if not accounts:
            raise RuntimeError("No Tradier accounts found for this token")
        self._account_id = str(accounts[0]["account_number"])
        return self._account_id

    # ── public interface ───────────────────────────────────────────────────

    def get_account_summary(self) -> dict:
        acct_id = self._account_id_str()
        data    = self._get(f"/accounts/{acct_id}/balances")
        b       = data.get("balances", {})

        equity       = float(b.get("total_equity", 0) or 0)
        cash         = float(b.get("cash", {}).get("cash_available", 0) or
                             b.get("total_cash", 0) or 0)
        buying_power = float(b.get("buying_power", 0) or 0)
        # Tradier doesn't expose yesterday's equity directly; use open_pl as proxy
        open_pl      = float(b.get("open_pl", 0) or 0)
        last_equity  = equity - open_pl if open_pl else equity

        return {
            "status": "active",
            "cash": cash,
            "equity": equity,
            "last_equity": last_equity,
            "buying_power": buying_power,
            "portfolio_value": equity,
            "day_pl": open_pl,
            "day_pl_pct": ((open_pl / last_equity) * 100) if last_equity else 0.0,
            "pattern_day_trader": False,
            "trading_blocked": False,
            "account_type": "paper" if self._paper else "live",
        }

    def get_day_trade_count(self) -> int:
        # Tradier sandbox doesn't enforce PDT; return 0
        return 0

    def get_positions(self) -> list[dict]:
        acct_id = self._account_id_str()
        data    = self._get(f"/accounts/{acct_id}/positions")
        raw     = data.get("positions", {})
        if raw == "null" or not raw:
            return []
        positions = raw.get("position", [])
        if isinstance(positions, dict):
            positions = [positions]
        # Fetch quotes for all symbols in one call to enrich current_price / P&L
        symbols = [p["symbol"] for p in positions]
        quotes: dict[str, float] = {}
        if symbols:
            try:
                data = self._get("/markets/quotes", params={"symbols": ",".join(symbols)})
                raw_q = data.get("quotes", {}).get("quote", [])
                if isinstance(raw_q, dict):
                    raw_q = [raw_q]
                for q in raw_q:
                    mid = (float(q.get("bid", 0) or 0) + float(q.get("ask", 0) or 0)) / 2
                    if not mid:
                        mid = float(q.get("last", 0) or 0)
                    quotes[q["symbol"]] = mid
            except Exception:
                pass

        out = []
        for p in positions:
            qty  = float(p.get("quantity", 0))
            side = "long" if qty >= 0 else "short"
            cost = float(p.get("cost_basis", 0) or 0)
            avg  = (cost / abs(qty)) if qty else 0.0
            sym  = p["symbol"]
            current_price = quotes.get(sym, 0.0)
            market_value  = current_price * abs(qty) if current_price else cost
            unrealized_pl = (current_price - avg) * abs(qty) if current_price else 0.0
            unrealized_plpc = ((current_price - avg) / avg * 100) if avg and current_price else 0.0
            out.append({
                "symbol":          sym,
                "qty":             abs(qty),
                "side":            side,
                "avg_entry_price": avg,
                "current_price":   current_price,
                "market_value":    market_value,
                "unrealized_pl":   unrealized_pl,
                "unrealized_plpc": unrealized_plpc,
                "change_today":    0.0,
            })
        return out

    def submit_market_order(self, symbol: str, side: Literal["buy", "sell"],
                            qty: float | None = None,
                            notional: float | None = None,
                            client_order_id: str | None = None) -> dict:
        if qty is None and notional is None:
            raise ValueError("qty or notional required")

        # Tradier requires share quantity; if notional given, fetch quote to estimate qty
        if qty is None:
            quote = self.get_latest_quote(symbol)
            mid   = (quote["bid"] + quote["ask"]) / 2 or quote["ask"]
            # A zero/missing quote (common for thinly-traded micro-caps or a feed
            # gap) would make notional//mid divide by zero or size a bogus order
            # that Tradier rejects with a 400. Fail with a clear reason instead.
            if not mid or mid <= 0:
                raise ValueError(
                    f"no valid Tradier quote for {symbol} (bid={quote['bid']}, "
                    f"ask={quote['ask']}); cannot size a ${notional:.2f} order"
                )
            qty = max(1, int(notional // mid))

        acct_id = self._account_id_str()
        payload = {
            "class":    "equity",
            "symbol":   symbol.upper(),
            "side":     side,
            "quantity": str(int(qty)),
            "type":     "market",
            "duration": "day",
        }
        if client_order_id:
            payload["tag"] = client_order_id[:255]

        data  = self._post(f"/accounts/{acct_id}/orders", payload)
        order = data.get("order", {})
        return {
            "id":     str(order.get("id", "")),
            "symbol": symbol.upper(),
            "side":   side,
            "qty":    float(qty),
            "status": str(order.get("status", "pending")).lower(),
        }

    def submit_limit_order(self, symbol: str, side: Literal["buy", "sell"],
                           qty: float, limit_price: float,
                           client_order_id: str | None = None) -> dict:
        acct_id = self._account_id_str()
        payload = {
            "class":    "equity",
            "symbol":   symbol.upper(),
            "side":     side,
            "quantity": str(int(qty)),
            "type":     "limit",
            "price":    str(round(limit_price, 2)),
            "duration": "day",
        }
        if client_order_id:
            payload["tag"] = client_order_id[:255]

        data  = self._post(f"/accounts/{acct_id}/orders", payload)
        order = data.get("order", {})
        return {
            "id":          str(order.get("id", "")),
            "symbol":      symbol.upper(),
            "side":        side,
            "qty":         float(qty),
            "limit_price": round(limit_price, 2),
            "status":      str(order.get("status", "pending")).lower(),
        }

    def cancel_order(self, order_id: str):
        acct_id = self._account_id_str()
        self._delete(f"/accounts/{acct_id}/orders/{order_id}")

    def get_orders(self, limit: int = 50, status: str = "all") -> list[dict]:
        acct_id = self._account_id_str()
        params  = {}
        if status != "all":
            params["status"] = status
        data   = self._get(f"/accounts/{acct_id}/orders", params=params)
        raw    = data.get("orders", {})
        if not raw or raw == "null":
            return []
        orders = raw.get("order", [])
        if isinstance(orders, dict):
            orders = [orders]
        out = []
        for o in orders[:limit]:
            out.append({
                "id":               str(o.get("id", "")),
                "client_order_id":  o.get("tag", ""),
                "symbol":           o.get("symbol", ""),
                "side":             str(o.get("side", "")).lower(),
                "qty":              float(o.get("quantity", 0) or 0),
                "filled_qty":       float(o.get("exec_quantity", 0) or 0),
                "filled_avg_price": float(o.get("avg_fill_price", 0) or 0) or None,
                "type":             str(o.get("type", "market")).lower(),
                "status":           str(o.get("status", "")).lower(),
                "submitted_at":     o.get("create_date"),
                "filled_at":        o.get("last_fill_date"),
            })
        return out

    def close_position(self, symbol: str):
        positions = self.get_positions()
        for p in positions:
            if p["symbol"].upper() == symbol.upper():
                sell_side = "sell" if p["side"] == "long" else "buy"
                self.submit_market_order(symbol, sell_side, qty=p["qty"])
                return
        raise ValueError(f"No open position for {symbol}")

    def get_latest_quote(self, symbol: str) -> dict:
        data  = self._get("/markets/quotes", params={"symbols": symbol.upper()})
        quote = data.get("quotes", {}).get("quote", {})
        if isinstance(quote, list):
            quote = quote[0]
        return {
            "symbol": symbol.upper(),
            "bid":    float(quote.get("bid", 0) or 0),
            "ask":    float(quote.get("ask", 0) or 0),
            "ts":     quote.get("trade_date", ""),
        }

    def get_recent_bars(self, symbol: str, days: int = 60) -> list[dict]:
        from datetime import datetime, timedelta, timezone
        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        data  = self._get("/markets/history", params={
            "symbol":   symbol.upper(),
            "interval": "daily",
            "start":    start.strftime("%Y-%m-%d"),
            "end":      end.strftime("%Y-%m-%d"),
        })
        history = data.get("history", {})
        if not history or history == "null":
            return []
        days_data = history.get("day", [])
        if isinstance(days_data, dict):
            days_data = [days_data]
        return [
            {
                "t": d["date"],
                "o": float(d["open"]),
                "h": float(d["high"]),
                "l": float(d["low"]),
                "c": float(d["close"]),
                "v": float(d["volume"]),
            }
            for d in days_data
        ]

    def is_market_open(self) -> bool:
        data = self._get("/markets/clock")
        return data.get("clock", {}).get("state") == "open"

    def get_clock(self) -> dict:
        data  = self._get("/markets/clock")
        clock = data.get("clock", {})
        return {
            "is_open":    clock.get("state") == "open",
            "next_open":  clock.get("next_open", ""),
            "next_close": clock.get("next_close", ""),
            "timestamp":  clock.get("timestamp", ""),
        }
