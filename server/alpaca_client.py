from datetime import datetime, timedelta, timezone
import threading
from typing import Literal

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame

from .config import ALPACA_API_KEY, ALPACA_API_SECRET, PAPER

_bt = threading.local()

_trading: TradingClient | None = None
_data: StockHistoricalDataClient | None = None


def trading() -> TradingClient:
    global _trading
    from .config import ALPACA_API_KEY, ALPACA_API_SECRET, PAPER  # re-read after setup
    if _trading is None or not ALPACA_API_KEY:
        _trading = TradingClient(ALPACA_API_KEY, ALPACA_API_SECRET, paper=PAPER)
    return _trading


def data() -> StockHistoricalDataClient:
    global _data
    if _data is None:
        _data = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)
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


def get_recent_bars(symbol: str, days: int = 60) -> list[dict]:
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
    """Equity curve via Alpaca portfolio history."""
    import httpx
    base = "https://paper-api.alpaca.markets" if PAPER else "https://api.alpaca.markets"
    url = f"{base}/v2/account/portfolio/history"
    headers = {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_API_SECRET,
    }
    params = {"period": period, "timeframe": timeframe}
    r = httpx.get(url, headers=headers, params=params, timeout=15.0)
    r.raise_for_status()
    return r.json()


class AccountClient:
    """Per-account Alpaca client with the same interface as the module-level functions.
    get_account_summary() returns identical 11-key dict so risk.check_all() works unchanged.
    get_positions() returns 3 fields only (symbol, qty, side) — sufficient for engine sizing.
    """

    def __init__(self, api_key: str, api_secret: str, paper: bool):
        self._t = TradingClient(api_key, api_secret, paper=paper)
        self._d = StockHistoricalDataClient(api_key, api_secret)
        self._paper = paper

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
        o = self._t.submit_order(req)
        return {
            "id": str(o.id),
            "symbol": o.symbol,
            "side": str(o.side).lower().replace("orderside.", ""),
            "qty": float(o.qty) if o.qty else None,
            "status": str(o.status).lower().replace("orderstatus.", ""),
        }
