"""
Binance spot broker adapter.

Matches the AccountClient interface from alpaca_client.py and tradier_client.py
so engine.py and main.py can use it interchangeably via broker_factory.py.
"""

from typing import Literal
import ccxt


class SnapshotRegressionError(Exception):
    """A cumulative-fill snapshot regressed or conflicted with a prior snapshot.

    When a broker exposes only monotonic cumulative filled quantity + avg price
    (no per-execution trades), a later snapshot whose cumulative filled qty is
    SMALLER than a previously-observed one is impossible under monotonicity. That
    means the ledger and the broker disagree, so the account must freeze rather
    than emit a negative/guessed synthetic delta (spec §19.4)."""


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


def _now_micro() -> str:
    """UTC ISO-8601 with microseconds (fallback fill timestamp)."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


class BinanceAccountClient:
    """
    Per-account Binance client. Same public interface as alpaca_client.AccountClient
    and tradier_client.TradierAccountClient.
    """

    # Binance/ccxt exposes authoritative lookup by broker order id AND client order
    # id (origClientOrderId) plus per-execution trades — so automation is supported
    # (spec §19.4). The execution service gates on this flag.
    supports_authoritative_lookup = True

    def __init__(self, api_key: str, api_secret: str, paper: bool, account_id: int | None = None):
        self._paper = paper
        self._account_id = account_id
        # Highest cumulative filled qty seen per broker order id, for deterministic
        # synthetic monotonic fill deltas when per-execution trades are unavailable
        # (spec §19.4). Maps broker_order_id -> (cumulative_qty_text, snapshot_version).
        self._synthetic_cursor: dict[str, tuple[str, int]] = {}
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

    def _compute_pnl_from_trades(self) -> dict:
        """
        Fetch all trade history from Binance and compute per-asset P&L.

        Returns:
            {
              "by_asset": {
                "ETH": {
                  "avg_cost": float,      # avg buy price of currently held qty
                  "total_bought": float,  # total USDT spent buying
                  "total_sold": float,    # total USDT received from selling
                  "realized_pnl": float,  # profit/loss on closed portions
                },
                ...
              },
              "total_realized_pnl": float,
              "total_bought": float,
              "total_sold": float,
            }
        """
        self._ensure_markets()
        balance = self._exchange.fetch_balance()
        held_assets = [
            a for a, q in (balance.get("total") or {}).items()
            if a not in self._STABLES and q and float(q) > 0.000001
        ]
        # Also include assets that had trades but may be fully sold
        traded_assets = set(held_assets)

        by_asset: dict = {}

        for asset in traded_assets:
            sym = f"{asset}/USDT"
            try:
                trades = self._exchange.fetch_my_trades(sym, limit=500)
            except Exception:
                continue

            total_bought = 0.0   # total USDT spent
            total_sold   = 0.0   # total USDT received
            buy_qty      = 0.0   # running qty bought
            buy_cost     = 0.0   # running cost of buys
            realized_pnl = 0.0

            for t in sorted(trades, key=lambda x: x.get("timestamp") or 0):
                qty   = float(t.get("amount") or 0)
                price = float(t.get("price")  or 0)
                cost  = float(t.get("cost")   or qty * price)

                if t["side"] == "buy":
                    buy_qty   += qty
                    buy_cost  += cost
                    total_bought += cost
                else:
                    # Realized P&L = sell proceeds - proportional buy cost
                    if buy_qty > 0:
                        avg_buy = buy_cost / buy_qty
                        sell_qty = min(qty, buy_qty)
                        realized_pnl += (price - avg_buy) * sell_qty
                        buy_cost -= avg_buy * sell_qty
                        buy_qty  -= sell_qty
                    total_sold += cost

            avg_cost = (buy_cost / buy_qty) if buy_qty > 0.000001 else 0.0

            by_asset[asset] = {
                "avg_cost":      avg_cost,
                "total_bought":  total_bought,
                "total_sold":    total_sold,
                "realized_pnl":  realized_pnl,
            }

        total_realized = sum(v["realized_pnl"] for v in by_asset.values())
        total_bought   = sum(v["total_bought"]  for v in by_asset.values())
        total_sold     = sum(v["total_sold"]    for v in by_asset.values())

        return {
            "by_asset":            by_asset,
            "total_realized_pnl":  total_realized,
            "total_bought":        total_bought,
            "total_sold":          total_sold,
        }

    # Stablecoins treated as $1 cash — included in equity and buying power
    _STABLES = {"USDT", "USDC", "BUSD", "TUSD", "FDUSD", "DAI", "USDS"}

    def get_account_summary(self) -> dict:
        balance = self._exchange.fetch_balance()
        totals = balance.get("total") or {}
        free   = balance.get("free")  or {}

        # All stablecoins count as cash (1:1 USD)
        stable_total = sum(
            float(totals.get(s, 0) or 0) for s in self._STABLES
        )
        stable_free = sum(
            float(free.get(s, 0) or 0) for s in self._STABLES
        )

        # Value non-stable crypto holdings at current price
        crypto_value = 0.0
        for asset, qty in totals.items():
            if asset in self._STABLES or not qty or float(qty) <= 0.000001:
                continue
            try:
                ticker = self._exchange.fetch_ticker(_to_ccxt(asset))
                crypto_value += float(qty) * float(ticker.get("last", 0) or 0)
            except Exception:
                pass

        equity = stable_total + crypto_value

        # Real P&L from trade history
        try:
            pnl = self._compute_pnl_from_trades()
            realized_pnl = pnl["total_realized_pnl"]
            total_bought = pnl["total_bought"]
            total_sold   = pnl["total_sold"]
            pnl_by_asset = pnl["by_asset"]
        except Exception:
            realized_pnl = 0.0
            total_bought = 0.0
            total_sold   = 0.0
            pnl_by_asset = {}

        return {
            "status":             "active",
            "cash":               stable_free,
            "equity":             equity,
            "last_equity":        equity,
            "buying_power":       stable_free,
            "portfolio_value":    equity,
            "day_pl":             realized_pnl,
            "day_pl_pct":         0.0,
            "realized_pnl":       realized_pnl,
            "total_bought":       total_bought,
            "total_sold":         total_sold,
            "pnl_by_symbol":      pnl_by_asset,
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

        # Get trade-based cost basis for real avg price and unrealized P&L
        try:
            pnl = self._compute_pnl_from_trades()
            cost_rows = pnl["by_asset"]
        except Exception:
            cost_rows = {}

        out = []
        for asset, qty in totals.items():
            qty = float(qty or 0)
            if asset in self._STABLES or qty < 0.000001:
                continue
            try:
                ticker       = self._exchange.fetch_ticker(_to_ccxt(asset))
                price        = float(ticker.get("last", 0) or 0)
                market_value = qty * price
            except Exception:
                price        = 0.0
                market_value = 0.0

            cb       = cost_rows.get(asset, {})
            avg_cost = float(cb.get("avg_cost", 0) or 0)
            if avg_cost > 0:
                cost_basis      = avg_cost * qty
                unrealized_pl   = market_value - cost_basis
                unrealized_plpc = (unrealized_pl / cost_basis * 100) if cost_basis else 0.0
            else:
                unrealized_pl   = 0.0
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

    # ── Normalized acknowledgement + fill lookup (Task 3, §5, §19.3, §19.4) ──────

    @staticmethod
    def _dtext(v) -> str:
        from .execution_models import decimal_text
        from decimal import Decimal
        # ccxt returns floats; route through Decimal(str(...)) to avoid float noise.
        return decimal_text(Decimal(str(v if v is not None else 0)))

    def _normalize_order(self, o: dict) -> dict:
        """Map a ccxt order dict to the normalized acknowledgement shape (§5)."""
        from decimal import Decimal
        from .execution_models import normalize_state
        filled = Decimal(str(o.get("filled") or 0))
        requested = Decimal(str(o.get("amount") or 0)) if o.get("amount") is not None else None
        state = normalize_state(o.get("status"), filled_qty=filled, requested_qty=requested)
        avg = o.get("average")
        return {
            "broker_order_id": str(o.get("id", "")),
            "client_order_id": o.get("clientOrderId", "") or "",
            "symbol":          _from_ccxt(o.get("symbol", "")),
            "side":            str(o.get("side", "")).lower(),
            "requested_qty":   self._dtext(o.get("amount")) if o.get("amount") is not None else None,
            "filled_qty":      self._dtext(filled),
            "avg_price":       self._dtext(avg) if avg else None,
            "state":           state.value,
            "raw_status":      str(o.get("status", "")).lower(),
        }

    def get_order(self, order_id: str, symbol: str | None = None) -> dict | None:
        """Authoritative lookup by broker order id (§5). Returns None if not found."""
        self._ensure_markets()
        ccxt_sym = _to_ccxt(symbol) if symbol else None
        try:
            o = self._exchange.fetch_order(order_id, ccxt_sym)
        except ccxt.OrderNotFound:
            return None
        return self._normalize_order(o) if o else None

    def get_order_by_client_id(self, client_id: str, symbol: str | None = None) -> dict | None:
        """Authoritative recovery lookup by client order id (§19.3).

        Binance supports fetch by origClientOrderId. Returns the single normalized
        order, or None if the exchange has no such order."""
        self._ensure_markets()
        ccxt_sym = _to_ccxt(symbol) if symbol else None
        try:
            o = self._exchange.fetch_order(None, ccxt_sym,
                                           params={"origClientOrderId": client_id})
        except ccxt.OrderNotFound:
            return None
        except Exception:
            return None
        if not o:
            return None
        return self._normalize_order(o)

    def get_order_fills(self, order_id: str, since=None, symbol: str | None = None) -> list:
        """Return authoritative fills for an order (§5, §19.4).

        Preferred source: per-execution trades (stable trade ids). If the exchange
        has no per-execution trades but the order shows cumulative filled quantity,
        emit deterministic MONOTONIC synthetic deltas keyed by
        (account_id, broker_order_id, cumulative_filled_qty, snapshot_version). A
        cumulative snapshot that REGRESSES raises SnapshotRegressionError (freeze)."""
        from decimal import Decimal
        from datetime import datetime, timezone
        from .execution_models import Fill, synthetic_fill_id

        self._ensure_markets()
        ccxt_sym = _to_ccxt(symbol) if symbol else None

        # 1) Try authoritative per-execution trades.
        trades = []
        try:
            trades = self._exchange.fetch_order_trades(order_id, ccxt_sym,
                                                       since=since, params={}) or []
        except Exception:
            trades = []
        if trades:
            out = []
            for t in trades:
                ts = t.get("timestamp")
                at = (datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                      .strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z") if ts else _now_micro()
                feeobj = t.get("fee") or {}
                out.append(Fill(
                    broker_fill_id=str(t.get("id", "")),
                    broker_order_id=str(t.get("order", order_id) or order_id),
                    qty=self._dtext(t.get("amount")),
                    price=self._dtext(t.get("price")),
                    fee=self._dtext(feeobj.get("cost", 0)),
                    fee_currency=str(feeobj.get("currency") or "USDT"),
                    filled_at=at,
                ))
            return out

        # 2) Synthetic monotonic deltas from cumulative filled snapshot (§19.4).
        try:
            o = self._exchange.fetch_order(order_id, ccxt_sym)
        except Exception:
            return []
        if not o:
            return []
        cumulative = Decimal(str(o.get("filled") or 0))
        if cumulative <= 0:
            return []
        avg = o.get("average")
        if getattr(self, "_synthetic_cursor", None) is None:
            self._synthetic_cursor = {}
        prev_text, version = self._synthetic_cursor.get(order_id, ("0", 0))
        prev = Decimal(prev_text)
        if cumulative < prev:
            raise SnapshotRegressionError(
                f"order {order_id} cumulative filled regressed {prev_text} -> "
                f"{self._dtext(cumulative)} (account {self._account_id})"
            )
        if cumulative == prev:
            return []                        # duplicate snapshot → idempotent no-op
        delta = cumulative - prev
        acct = self._account_id if self._account_id is not None else 0
        cum_text = self._dtext(cumulative)
        new_version = version + 1
        ts = o.get("lastTradeTimestamp") or o.get("timestamp")
        at = (datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
              .strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z") if ts else _now_micro()
        fill = Fill(
            broker_fill_id=synthetic_fill_id(acct, order_id, cum_text, new_version),
            broker_order_id=str(order_id),
            qty=self._dtext(delta),
            price=self._dtext(avg) if avg else "0",
            fee="0",
            fee_currency="USDT",
            filled_at=at,
        )
        self._synthetic_cursor[order_id] = (cum_text, new_version)
        return [fill]
