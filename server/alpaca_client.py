from datetime import datetime, timedelta, timezone
import threading
from typing import Literal

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import Adjustment

from .config import ALPACA_API_KEY, ALPACA_API_SECRET, PAPER

_bt = threading.local()


def _now_micro() -> str:
    """UTC ISO-8601 with microseconds (fallback fill timestamp)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _db_alpaca_creds() -> tuple[str, str, bool]:
    """Return (api_key, api_secret, paper) from the first Alpaca DB account.
    Falls back to .env values if no DB account exists or decryption fails."""
    try:
        from . import crypto, db
        for acct in db.get_broker_accounts():
            if (acct.get("broker") or "alpaca") == "alpaca":
                creds = db.get_broker_account_credentials(acct["id"])
                key    = crypto.decrypt(creds["api_key"])
                secret = crypto.decrypt(creds["api_secret"])
                paper  = acct.get("account_type", "paper") == "paper"
                return key, secret, paper
    except Exception:
        pass
    return ALPACA_API_KEY, ALPACA_API_SECRET, PAPER

_trading: TradingClient | None = None
_data: StockHistoricalDataClient | None = None


def trading() -> TradingClient:
    global _trading
    key, secret, paper = _db_alpaca_creds()
    if not key:
        raise ValueError("No Alpaca credentials configured. Add an Alpaca account in Settings.")
    # Always re-create so credential rotations take effect without restart
    _trading = TradingClient(key, secret, paper=paper)
    return _trading


def data() -> StockHistoricalDataClient:
    global _data
    key, secret, _ = _db_alpaca_creds()
    if not key:
        raise ValueError("No Alpaca credentials configured. Add an Alpaca account in Settings.")
    # Always re-create so credential rotations take effect without restart
    _data = StockHistoricalDataClient(key, secret)
    return _data


def get_account_summary() -> dict:
    a = trading().get_account()
    equity = float(a.equity)
    last_equity = float(a.last_equity)
    return {
        "status": str(a.status),
        "cash": float(a.cash),
        "equity": equity,
        "last_equity": last_equity,
        "buying_power": float(a.buying_power),
        "portfolio_value": float(a.portfolio_value),
        "day_pl": equity - last_equity,
        "day_pl_pct": ((equity - last_equity) / last_equity * 100) if last_equity else 0.0,
        "pattern_day_trader": bool(a.pattern_day_trader),
        "trading_blocked": bool(a.trading_blocked),
        "account_type": "paper" if PAPER else "live",
    }


def get_positions() -> list[dict]:
    out = []
    for p in trading().get_all_positions():
        out.append({
            "symbol": p.symbol,
            "qty": float(p.qty),
            "side": str(p.side).lower().replace("positionside.", ""),
            "avg_entry_price": float(p.avg_entry_price),
            "current_price": float(p.current_price) if p.current_price else 0.0,
            "market_value": float(p.market_value),
            "unrealized_pl": float(p.unrealized_pl),
            "unrealized_plpc": float(p.unrealized_plpc) * 100,
            "change_today": float(p.change_today) * 100 if p.change_today else 0.0,
        })
    return out


def get_orders(limit: int = 50, status: str = "all") -> list[dict]:
    status_map = {
        "all": QueryOrderStatus.ALL,
        "open": QueryOrderStatus.OPEN,
        "closed": QueryOrderStatus.CLOSED,
    }
    req = GetOrdersRequest(status=status_map.get(status, QueryOrderStatus.ALL), limit=limit)
    out = []
    for o in trading().get_orders(filter=req):
        out.append({
            "id": str(o.id),
            "client_order_id": o.client_order_id,
            "symbol": o.symbol,
            "side": str(o.side).lower().replace("orderside.", ""),
            "qty": float(o.qty) if o.qty else None,
            "filled_qty": float(o.filled_qty) if o.filled_qty else 0.0,
            "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price else None,
            "type": str(o.order_type).lower().replace("ordertype.", ""),
            "status": str(o.status).lower().replace("orderstatus.", ""),
            "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
            "filled_at": o.filled_at.isoformat() if o.filled_at else None,
        })
    return out


def submit_market_order(symbol: str, side: Literal["buy", "sell"],
                        qty: float | None = None,
                        notional: float | None = None,
                        client_order_id: str | None = None) -> dict:
    if qty is None and notional is None:
        raise ValueError("qty or notional required")
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
    req = MarketOrderRequest(
        symbol=symbol.upper(),
        qty=qty if not notional else None,
        notional=round(notional, 2) if notional else None,
        side=order_side,
        time_in_force=TimeInForce.DAY,
        client_order_id=client_order_id,
    )
    o = trading().submit_order(req)
    return {
        "id": str(o.id),
        "symbol": o.symbol,
        "side": str(o.side).lower().replace("orderside.", ""),
        "qty": float(o.qty) if o.qty else None,
        "notional": float(o.notional) if o.notional else None,
        "status": str(o.status).lower().replace("orderstatus.", ""),
    }


def submit_limit_order(symbol: str, side: Literal["buy", "sell"],
                       qty: float, limit_price: float,
                       client_order_id: str | None = None) -> dict:
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
    req = LimitOrderRequest(
        symbol=symbol.upper(),
        qty=qty,
        limit_price=round(limit_price, 2),
        side=order_side,
        time_in_force=TimeInForce.DAY,
        client_order_id=client_order_id,
    )
    o = trading().submit_order(req)
    return {
        "id": str(o.id),
        "symbol": o.symbol,
        "side": str(o.side).lower().replace("orderside.", ""),
        "qty": float(o.qty) if o.qty else None,
        "limit_price": float(o.limit_price) if o.limit_price else None,
        "status": str(o.status).lower().replace("orderstatus.", ""),
    }


def cancel_order(order_id: str):
    trading().cancel_order_by_id(order_id)


def cancel_all_orders():
    trading().cancel_orders()


def close_position(symbol: str):
    trading().close_position(symbol.upper())


def close_all_positions():
    trading().close_all_positions(cancel_orders=True)


def get_latest_quote(symbol: str) -> dict:
    req = StockLatestQuoteRequest(symbol_or_symbols=symbol.upper())
    res = data().get_stock_latest_quote(req)
    q = res[symbol.upper()]
    return {
        "symbol": symbol.upper(),
        "bid": float(q.bid_price),
        "ask": float(q.ask_price),
        "ts": q.timestamp.isoformat(),
    }


_asset_cache: list[dict] = []

def _load_asset_cache():
    global _asset_cache
    try:
        assets = trading().get_all_assets()
        _asset_cache = [
            {"symbol": a.symbol, "name": a.name or "", "tradable": a.tradable}
            for a in assets if a.status.value == "active" and "/" not in a.symbol
        ]
    except Exception:
        _asset_cache = []

def search_assets(q: str, limit: int = 8) -> list[dict]:
    if not _asset_cache:
        _load_asset_cache()
    q = q.upper().strip()
    if not q:
        return []
    # Symbol prefix matches first, then name contains
    sym_matches  = [a for a in _asset_cache if a["symbol"].startswith(q)]
    name_matches = [a for a in _asset_cache if q in a["name"].upper() and not a["symbol"].startswith(q)]
    results = (sym_matches + name_matches)[:limit]
    return [{"symbol": a["symbol"], "name": a["name"], "tradable": a["tradable"]} for a in results]


def get_snapshots(symbols: list[str]) -> list[dict]:
    syms = [s.upper() for s in symbols if s]
    if not syms:
        return []
    req = StockSnapshotRequest(symbol_or_symbols=syms)
    res = data().get_stock_snapshot(req)
    out = []
    for sym in syms:
        snap = res.get(sym)
        if not snap:
            out.append({"symbol": sym, "price": None, "change_pct": None, "volume": None})
            continue
        price = float(snap.latest_trade.price) if snap.latest_trade else None
        prev  = float(snap.previous_daily_bar.close) if snap.previous_daily_bar else None
        vol   = float(snap.daily_bar.volume) if snap.daily_bar else None
        chg   = ((price - prev) / prev * 100) if price and prev else None
        out.append({"symbol": sym, "price": price, "change_pct": chg, "volume": vol, "prev_close": prev})
    return out


def get_recent_bars(symbol: str, days: int = 60, adjustment: str = "raw") -> list[dict]:
    """Daily bars for `symbol`.

    `adjustment` controls corporate-action handling on the Alpaca feed:
      - "raw" (default): live signal path — unchanged behavior.
      - "all"/"split"/"dividend": for the historical/research provider, so a
        multi-year backtest is not poisoned by a split appearing as a price crash
        (e.g. AAPL 4:1 on 2020-08-31 shows as a 73% overnight drop when raw).
    """
    if getattr(_bt, "bars", None) is not None:
        sym = symbol.upper()
        # days is intentionally ignored; caller pre-loads all bars into _bt.bars
        current_date = getattr(_bt, "current_date", None)
        if current_date is None:
            raise RuntimeError("_bt.bars is set but _bt.current_date is not — set both before calling get_recent_bars")
        return [b for b in _bt.bars.get(sym, []) if b["t"][:10] <= current_date.isoformat()]

    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    start = end - timedelta(days=days)
    req = StockBarsRequest(
        symbol_or_symbols=symbol.upper(),
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        adjustment=Adjustment(adjustment),
    )
    bars = data().get_stock_bars(req)
    out = []
    for b in bars[symbol.upper()]:
        out.append({
            "t": b.timestamp.isoformat(),
            "o": float(b.open),
            "h": float(b.high),
            "l": float(b.low),
            "c": float(b.close),
            "v": float(b.volume),
        })
    return out


def is_market_open() -> bool:
    return bool(trading().get_clock().is_open)


def get_clock() -> dict:
    c = trading().get_clock()
    return {
        "is_open": bool(c.is_open),
        "next_open": c.next_open.isoformat(),
        "next_close": c.next_close.isoformat(),
        "timestamp": c.timestamp.isoformat(),
    }


def get_portfolio_history(period: str = "1M", timeframe: str = "1D") -> dict:
    """Equity curve via Alpaca portfolio history — uses first active Alpaca account from DB."""
    import httpx
    from . import crypto, db

    # Prefer DB credentials (entered via Settings) over stale .env values
    api_key, api_secret, paper = ALPACA_API_KEY, ALPACA_API_SECRET, PAPER
    accounts = db.get_broker_accounts()
    for acct in accounts:
        if (acct.get("broker") or "alpaca") == "alpaca":
            try:
                creds = db.get_broker_account_credentials(acct["id"])
                api_key   = crypto.decrypt(creds["api_key"])
                api_secret = crypto.decrypt(creds["api_secret"])
                paper = acct.get("account_type", "paper") == "paper"
                break
            except Exception:
                continue

    base = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
    url = f"{base}/v2/account/portfolio/history"
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }
    params = {"period": period, "timeframe": timeframe}
    r = httpx.get(url, headers=headers, params=params, timeout=15.0)
    r.raise_for_status()
    return r.json()


def historical_provider(bars_by_symbol=None, corporate_actions=None):
    """Build a STOCK-ONLY daily historical provider (Task 6, spec §9).

    Backtest/research infrastructure only — this does NOT change any live trading
    path. When `bars_by_symbol` is supplied (tests / recorded fixtures) the
    provider is fully deterministic and makes no network calls. Otherwise a network
    provider is returned whose `_raw_bars` pulls daily bars via `get_recent_bars`;
    it remains STOCK-ONLY and never falls back to a crypto source.
    """
    from .historical import AlpacaHistoricalProvider

    if bars_by_symbol is not None:
        return AlpacaHistoricalProvider(bars_by_symbol=bars_by_symbol,
                                        corporate_actions=corporate_actions)

    class _NetworkAlpacaProvider(AlpacaHistoricalProvider):
        def _raw_bars(self, symbol: str) -> list[dict]:
            # Wide daily window; fetch() narrows to the requested range. Exceptions
            # propagate (never swallowed into empty success). Split+dividend adjusted
            # so a multi-year series is continuous across corporate actions (§9).
            return get_recent_bars(symbol, days=3650, adjustment="all")

    return _NetworkAlpacaProvider(corporate_actions=corporate_actions)


class SnapshotRegressionError(Exception):
    """A cumulative-fill snapshot regressed vs a prior snapshot (spec §19.4).

    Alpaca exposes only aggregate cumulative filled qty + avg price per order (no
    per-execution trade feed in the base SDK), so synthetic monotonic deltas are
    used. A cumulative filled qty that shrinks between polls is impossible under
    monotonicity and must freeze the account rather than emit a negative delta."""


class AccountClient:
    """Per-account Alpaca client with the same interface as the module-level functions.
    get_account_summary() returns identical 11-key dict so risk.check_all() works unchanged.
    get_positions() returns 3 fields only (symbol, qty, side) — sufficient for engine sizing.
    """

    # Alpaca supports authoritative lookup by broker order id AND client order id.
    supports_authoritative_lookup = True

    def __init__(self, api_key: str, api_secret: str, paper: bool, account_id: int | None = None):
        self._t = TradingClient(api_key, api_secret, paper=paper)
        self._d = StockHistoricalDataClient(api_key, api_secret)
        self._paper = paper
        self._account_id = account_id
        # broker_order_id -> (cumulative_filled_qty_text, snapshot_version)
        self._synthetic_cursor: dict[str, tuple[str, int]] = {}

    def get_account_summary(self) -> dict:
        a = self._t.get_account()
        equity = float(a.equity)
        last_equity = float(a.last_equity)
        return {
            "status": str(a.status),
            "cash": float(a.cash),
            "equity": equity,
            "last_equity": last_equity,
            "buying_power": float(a.buying_power),
            "portfolio_value": float(a.portfolio_value),
            "day_pl": equity - last_equity,
            "day_pl_pct": ((equity - last_equity) / last_equity * 100) if last_equity else 0.0,
            "pattern_day_trader": bool(a.pattern_day_trader),
            "trading_blocked": bool(a.trading_blocked),
            "account_type": "paper" if self._paper else "live",
        }

    def get_day_trade_count(self) -> int:
        try:
            return int(self._t.get_account().daytrade_count or 0)
        except Exception:
            return 0

    def get_positions(self) -> list[dict]:
        out = []
        for p in self._t.get_all_positions():
            out.append({
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": str(p.side).lower().replace("positionside.", ""),
                "market_value": float(p.market_value) if p.market_value else 0.0,
                "avg_entry_price": float(p.avg_entry_price) if p.avg_entry_price else 0.0,
                "current_price": float(p.current_price) if p.current_price else 0.0,
                "unrealized_pl": float(p.unrealized_pl) if p.unrealized_pl else 0.0,
                "unrealized_plpc": float(p.unrealized_plpc) * 100 if p.unrealized_plpc else 0.0,
            })
        return out

    def submit_market_order(self, symbol: str, side: Literal["buy", "sell"],
                            qty: float | None = None,
                            notional: float | None = None,
                            client_order_id: str | None = None) -> dict:
        if qty is None and notional is None:
            raise ValueError("qty or notional required")
        req = MarketOrderRequest(
            symbol=symbol.upper(),
            qty=qty if not notional else None,
            notional=round(notional, 2) if notional else None,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
        )
        try:
            o = self._t.submit_order(req)
        except Exception as e:
            # Alpaca rejects notional/fractional orders for non-fractionable assets.
            # Fall back to a whole-share qty order derived from the notional amount.
            if "not fractionable" in str(e) and notional and not qty:
                quote = get_latest_quote(symbol)
                price = quote.get("ask") or quote.get("bid")
                whole_qty = int(notional // float(price)) if price else 0
                if whole_qty < 1:
                    raise ValueError(
                        f"{symbol} is not fractionable and notional ${notional} is less than one share"
                    ) from e
                req2 = MarketOrderRequest(
                    symbol=symbol.upper(),
                    qty=whole_qty,
                    side=req.side,
                    time_in_force=req.time_in_force,
                    client_order_id=client_order_id,
                )
                o = self._t.submit_order(req2)
            else:
                raise
        return {
            "id": str(o.id),
            "symbol": o.symbol,
            "side": str(o.side).lower().replace("orderside.", ""),
            "qty": float(o.qty) if o.qty else None,
            "status": str(o.status).lower().replace("orderstatus.", ""),
        }

    def get_orders(self, limit: int = 50, status: str = "all") -> list[dict]:
        status_map = {
            "all": QueryOrderStatus.ALL,
            "open": QueryOrderStatus.OPEN,
            "closed": QueryOrderStatus.CLOSED,
        }
        req = GetOrdersRequest(status=status_map.get(status, QueryOrderStatus.ALL), limit=limit)
        out = []
        for o in self._t.get_orders(filter=req):
            out.append({
                "id": str(o.id),
                "client_order_id": o.client_order_id,
                "symbol": o.symbol,
                "side": str(o.side).lower().replace("orderside.", ""),
                "qty": float(o.qty) if o.qty else None,
                "filled_qty": float(o.filled_qty) if o.filled_qty else 0.0,
                "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price else None,
                "type": str(o.order_type).lower().replace("ordertype.", ""),
                "status": str(o.status).lower().replace("orderstatus.", ""),
                "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
                "filled_at": o.filled_at.isoformat() if o.filled_at else None,
            })
        return out

    def cancel_order(self, order_id: str):
        self._t.cancel_order_by_id(order_id)

    def cancel_all_orders(self):
        self._t.cancel_orders()

    def close_position(self, symbol: str):
        self._t.close_position(symbol.upper())

    def close_all_positions(self):
        self._t.close_all_positions(cancel_orders=True)

    # ── Normalized acknowledgement + fill lookup (Task 3, §5, §19.3, §19.4) ──────

    @staticmethod
    def _dtext(v) -> str:
        from decimal import Decimal
        from .execution_models import decimal_text
        return decimal_text(Decimal(str(v if v is not None else 0)))

    def _normalize_order(self, o) -> dict:
        """Map an Alpaca order object to the normalized acknowledgement shape (§5)."""
        from decimal import Decimal
        from .execution_models import normalize_state
        filled = Decimal(str(o.filled_qty or 0))
        requested = Decimal(str(o.qty)) if o.qty else None
        status = str(o.status).lower().replace("orderstatus.", "")
        state = normalize_state(status, filled_qty=filled, requested_qty=requested)
        avg = o.filled_avg_price
        return {
            "broker_order_id": str(o.id),
            "client_order_id": o.client_order_id or "",
            "symbol":          o.symbol,
            "side":            str(o.side).lower().replace("orderside.", ""),
            "requested_qty":   self._dtext(o.qty) if o.qty else None,
            "filled_qty":      self._dtext(filled),
            "avg_price":       self._dtext(avg) if avg else None,
            "state":           state.value,
            "raw_status":      status,
        }

    def get_order(self, order_id: str, symbol: str | None = None) -> dict | None:
        try:
            o = self._t.get_order_by_id(order_id)
        except Exception:
            return None
        return self._normalize_order(o) if o else None

    def get_order_by_client_id(self, client_id: str, symbol: str | None = None) -> dict | None:
        """Authoritative recovery lookup by client order id (§19.3)."""
        try:
            o = self._t.get_order_by_client_id(client_id)
        except Exception:
            return None
        return self._normalize_order(o) if o else None

    def get_order_fills(self, order_id: str, since=None, symbol: str | None = None) -> list:
        """Synthetic monotonic fill deltas from the order's cumulative filled qty
        + avg price (§19.4). Alpaca's base SDK has no per-execution trade feed, so a
        regressing cumulative snapshot raises SnapshotRegressionError (freeze)."""
        from decimal import Decimal
        from .execution_models import Fill, synthetic_fill_id
        try:
            o = self._t.get_order_by_id(order_id)
        except Exception:
            return []
        if not o:
            return []
        cumulative = Decimal(str(o.filled_qty or 0))
        if cumulative <= 0:
            return []
        avg = o.filled_avg_price
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
            return []
        delta = cumulative - prev
        acct = self._account_id if self._account_id is not None else 0
        cum_text = self._dtext(cumulative)
        new_version = version + 1
        at = o.filled_at.isoformat() if getattr(o, "filled_at", None) else _now_micro()
        fill = Fill(
            broker_fill_id=synthetic_fill_id(acct, order_id, cum_text, new_version),
            broker_order_id=str(order_id),
            qty=self._dtext(delta),
            price=self._dtext(avg) if avg else "0",
            fee="0",
            fee_currency="USD",
            filled_at=at,
        )
        self._synthetic_cursor[order_id] = (cum_text, new_version)
        return [fill]
