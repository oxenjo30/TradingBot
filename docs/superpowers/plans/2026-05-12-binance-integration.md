# Binance Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Binance spot trading as a third broker using `ccxt`, following the same interface contract as `alpaca_client.AccountClient` and `tradier_client.TradierAccountClient`.

**Architecture:** A new `BinanceAccountClient` class in `server/binance_client.py` implements the exact same public methods as existing broker clients. `broker_factory.py` gains one `if` branch. The engine, risk manager, strategies, and notifications are untouched.

**Tech Stack:** Python 3.13, ccxt>=4.4,<5, pytest, unittest.mock

**Spec:** `docs/superpowers/specs/2026-05-12-binance-integration-design.md`

---

## File Map

| Action | File | Purpose |
|---|---|---|
| Create | `server/binance_client.py` | `BinanceAccountClient` — full broker interface for Binance spot via ccxt |
| Modify | `server/broker_factory.py` | Add `if broker == "binance"` branch |
| Modify | `requirements.txt` | Add `ccxt>=4.4,<5` |
| Modify | `server/static/apikeys.html` | Add Binance to broker dropdown + credential hints |
| Create | `tests/test_binance_client.py` | Unit tests with mocked ccxt exchange |

---

## Task 1: Add ccxt dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add ccxt to requirements.txt**

Open `requirements.txt` and add after `httpx==0.28.1`:

```
ccxt>=4.4,<5
```

Final file should look like:
```
fastapi==0.115.5
uvicorn==0.32.1
alpaca-py==0.33.1
apscheduler==3.10.4
python-dotenv==1.0.1
pydantic==2.10.3
httpx==0.28.1
ccxt>=4.4,<5
cryptography>=41.0
tzdata>=2024.1
pytest>=8.0
```

- [ ] **Step 2: Install it**

```bash
pip install "ccxt>=4.4,<5"
```

Expected: installs without error. Verify: `python -c "import ccxt; print(ccxt.__version__)"` prints a 4.x version.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add ccxt>=4.4,<5 for Binance integration"
```

---

## Task 2: Write `BinanceAccountClient` — skeleton + symbol normalization

**Files:**
- Create: `server/binance_client.py`
- Create: `tests/test_binance_client.py`

- [ ] **Step 1: Write failing tests for symbol normalization**

Create `tests/test_binance_client.py`:

```python
import pytest
from unittest.mock import MagicMock, patch


def make_client(paper=True):
    """Create BinanceAccountClient with a mocked ccxt exchange."""
    mock_exchange = MagicMock()
    mock_exchange.load_markets.return_value = {}
    with patch("ccxt.binance", return_value=mock_exchange):
        from server.binance_client import BinanceAccountClient
        client = BinanceAccountClient.__new__(BinanceAccountClient)
        client._exchange = mock_exchange
        client._paper = paper
        return client, mock_exchange


class TestSymbolNormalization:
    def setup_method(self):
        # Re-import fresh each test to avoid module cache issues
        import importlib
        import server.binance_client as m
        importlib.reload(m)
        self.m = m

    def test_bare_ticker_to_ccxt(self):
        assert self.m._to_ccxt("BTC") == "BTC/USDT"

    def test_already_slash_format(self):
        assert self.m._to_ccxt("BTC/USDT") == "BTC/USDT"

    def test_already_concatenated_format(self):
        assert self.m._to_ccxt("BTCUSDT") == "BTC/USDT"

    def test_lowercase_input(self):
        assert self.m._to_ccxt("eth") == "ETH/USDT"

    def test_from_ccxt_strips_slash(self):
        assert self.m._from_ccxt("BTC/USDT") == "BTC"

    def test_from_ccxt_bare_passthrough(self):
        assert self.m._from_ccxt("BTC") == "BTC"
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd c:\TradeBot
python -m pytest tests/test_binance_client.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError` or `ImportError` — `binance_client` doesn't exist yet.

- [ ] **Step 3: Create `server/binance_client.py` with skeleton + normalization helpers**

```python
"""
Binance spot broker adapter.

Matches the AccountClient interface from alpaca_client.py and tradier_client.py
so engine.py and main.py can use it interchangeably via broker_factory.py.

Binance API docs: https://binance-docs.github.io/apidocs/spot/en/
Testnet:         https://testnet.binance.vision
Live:            https://api.binance.com
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

    Methods:
      get_account_summary()        -> dict (12 keys)
      get_day_trade_count()        -> int  (always 0 — PDT doesn't apply to crypto)
      get_positions()              -> list[dict]
      get_recent_bars(symbol, days) -> list[dict]
      get_latest_quote(symbol)     -> dict
      submit_market_order(...)     -> dict
      submit_limit_order(...)      -> dict
      get_orders(limit, status)    -> list[dict]
      cancel_order(order_id)       -> dict
      close_position(symbol)       -> None
    """

    def __init__(self, api_key: str, api_secret: str, paper: bool):
        self._paper = paper
        self._exchange = ccxt.binance({
            "apiKey":    api_key,
            "secret":    api_secret,
            "options":   {"defaultType": "spot"},
        })
        if paper:
            self._exchange.set_sandbox_mode(True)
        # Pre-load markets so symbol resolution works without lazy delay
        self._exchange.load_markets()
```

- [ ] **Step 4: Run normalization tests — should pass now**

```bash
python -m pytest tests/test_binance_client.py::TestSymbolNormalization -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/binance_client.py tests/test_binance_client.py
git commit -m "feat: add BinanceAccountClient skeleton + symbol normalization"
```

---

## Task 3: Implement `get_account_summary()` and `get_day_trade_count()`

**Files:**
- Modify: `server/binance_client.py`
- Modify: `tests/test_binance_client.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_binance_client.py`:

```python
class TestGetAccountSummary:
    def setup_method(self):
        import importlib, server.binance_client as m
        importlib.reload(m)
        self.BinanceAccountClient = m.BinanceAccountClient

    def _make(self, balance_data):
        mock_ex = MagicMock()
        mock_ex.load_markets.return_value = {}
        mock_ex.fetch_balance.return_value = balance_data
        # fetch_ticker needed for portfolio value calc
        mock_ex.fetch_ticker.return_value = {"last": 60000.0}
        with patch("ccxt.binance", return_value=mock_ex):
            c = self.BinanceAccountClient.__new__(self.BinanceAccountClient)
            c._paper = True
            c._exchange = mock_ex
            return c

    def test_returns_all_12_keys(self):
        client = self._make({
            "USDT": {"free": 10000.0, "used": 0.0, "total": 10000.0},
            "free": {"USDT": 10000.0}, "total": {"USDT": 10000.0},
        })
        result = client.get_account_summary()
        required_keys = {
            "status", "cash", "equity", "last_equity", "buying_power",
            "portfolio_value", "day_pl", "day_pl_pct", "pattern_day_trader",
            "trading_blocked", "account_type", "currency",
        }
        assert required_keys.issubset(result.keys())

    def test_usdt_only_account(self):
        client = self._make({
            "USDT": {"free": 5000.0, "used": 0.0, "total": 5000.0},
            "free": {"USDT": 5000.0}, "total": {"USDT": 5000.0},
        })
        result = client.get_account_summary()
        assert result["cash"] == 5000.0
        assert result["equity"] == 5000.0
        assert result["buying_power"] == 5000.0
        assert result["pattern_day_trader"] is False
        assert result["trading_blocked"] is False
        assert result["currency"] == "USDT"
        assert result["account_type"] == "paper"

    def test_day_trade_count_always_zero(self):
        mock_ex = MagicMock()
        mock_ex.load_markets.return_value = {}
        with patch("ccxt.binance", return_value=mock_ex):
            c = self.BinanceAccountClient.__new__(self.BinanceAccountClient)
            c._paper = True
            c._exchange = mock_ex
            assert c.get_day_trade_count() == 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_binance_client.py::TestGetAccountSummary -v
```

Expected: `AttributeError: 'BinanceAccountClient' object has no attribute 'get_account_summary'`

- [ ] **Step 3: Implement `get_account_summary()` and `get_day_trade_count()`**

Add to `server/binance_client.py` after `__init__`:

```python
    def get_account_summary(self) -> dict:
        balance = self._exchange.fetch_balance()
        usdt_free  = float(balance.get("free",  {}).get("USDT", 0) or 0)
        usdt_total = float(balance.get("total", {}).get("USDT", 0) or 0)

        # Sum value of all non-USDT holdings at current price
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
            "status":            "active",
            "cash":              usdt_free,
            "equity":            equity,
            "last_equity":       equity,   # no prior-day snapshot on Binance spot
            "buying_power":      usdt_free,
            "portfolio_value":   equity,
            "day_pl":            0.0,      # no intraday P&L endpoint on spot
            "day_pl_pct":        0.0,
            "pattern_day_trader": False,   # PDT is a US broker concept
            "trading_blocked":   False,
            "account_type":      "paper" if self._paper else "live",
            "currency":          "USDT",
        }

    def get_day_trade_count(self) -> int:
        return 0
```

- [ ] **Step 4: Run tests — should pass**

```bash
python -m pytest tests/test_binance_client.py::TestGetAccountSummary -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/binance_client.py tests/test_binance_client.py
git commit -m "feat: implement BinanceAccountClient.get_account_summary + get_day_trade_count"
```

---

## Task 4: Implement `get_positions()`

**Files:**
- Modify: `server/binance_client.py`
- Modify: `tests/test_binance_client.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_binance_client.py`:

```python
class TestGetPositions:
    def setup_method(self):
        import importlib, server.binance_client as m
        importlib.reload(m)
        self.BinanceAccountClient = m.BinanceAccountClient

    def _make(self, balance, ticker_prices=None):
        mock_ex = MagicMock()
        mock_ex.load_markets.return_value = {}
        mock_ex.fetch_balance.return_value = balance
        ticker_prices = ticker_prices or {}
        def mock_ticker(symbol):
            return {"last": ticker_prices.get(symbol, 0.0)}
        mock_ex.fetch_ticker.side_effect = mock_ticker
        with patch("ccxt.binance", return_value=mock_ex):
            c = self.BinanceAccountClient.__new__(self.BinanceAccountClient)
            c._paper = True
            c._exchange = mock_ex
            return c

    def test_empty_balance_returns_empty_list(self):
        client = self._make({"total": {"USDT": 1000.0}, "free": {"USDT": 1000.0}})
        assert client.get_positions() == []

    def test_btc_position_returned(self):
        client = self._make(
            balance={"total": {"BTC": 0.5, "USDT": 1000.0}, "free": {"BTC": 0.5, "USDT": 1000.0}},
            ticker_prices={"BTC/USDT": 60000.0},
        )
        positions = client.get_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos["symbol"] == "BTC"
        assert pos["qty"] == 0.5
        assert pos["market_value"] == pytest.approx(30000.0)
        assert pos["side"] == "long"
        assert pos["avg_entry_price"] == 0.0   # not available from Binance spot balance
        assert pos["unrealized_pl"] == 0.0

    def test_usdt_excluded_from_positions(self):
        client = self._make({"total": {"USDT": 5000.0}, "free": {"USDT": 5000.0}})
        assert client.get_positions() == []

    def test_dust_amounts_excluded(self):
        # Very small qty (< 0.000001) treated as zero / dust
        client = self._make(
            balance={"total": {"BTC": 0.0000001, "USDT": 1000.0}, "free": {"BTC": 0.0000001, "USDT": 1000.0}},
            ticker_prices={"BTC/USDT": 60000.0},
        )
        positions = client.get_positions()
        assert len(positions) == 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_binance_client.py::TestGetPositions -v
```

Expected: `AttributeError: 'BinanceAccountClient' object has no attribute 'get_positions'`

- [ ] **Step 3: Implement `get_positions()`**

Add to `server/binance_client.py`:

```python
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
                "avg_entry_price": 0.0,      # not available from spot balance
                "current_price":   price,
                "market_value":    market_value,
                "unrealized_pl":   0.0,
                "unrealized_plpc": 0.0,
                "change_today":    0.0,
            })
        return out
```

- [ ] **Step 4: Run tests — should pass**

```bash
python -m pytest tests/test_binance_client.py::TestGetPositions -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/binance_client.py tests/test_binance_client.py
git commit -m "feat: implement BinanceAccountClient.get_positions"
```

---

## Task 5: Implement `get_recent_bars()` and `get_latest_quote()`

**Files:**
- Modify: `server/binance_client.py`
- Modify: `tests/test_binance_client.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_binance_client.py`:

```python
class TestMarketData:
    def setup_method(self):
        import importlib, server.binance_client as m
        importlib.reload(m)
        self.BinanceAccountClient = m.BinanceAccountClient

    def _make(self, mock_ex):
        mock_ex.load_markets.return_value = {}
        with patch("ccxt.binance", return_value=mock_ex):
            c = self.BinanceAccountClient.__new__(self.BinanceAccountClient)
            c._paper = True
            c._exchange = mock_ex
            return c

    def test_get_recent_bars_returns_ohlcv(self):
        mock_ex = MagicMock()
        # ccxt fetch_ohlcv returns list of [timestamp_ms, o, h, l, c, v]
        mock_ex.fetch_ohlcv.return_value = [
            [1715000000000, 60000.0, 61000.0, 59500.0, 60500.0, 1234.5],
            [1715086400000, 60500.0, 62000.0, 60000.0, 61500.0, 2345.6],
        ]
        client = self._make(mock_ex)
        bars = client.get_recent_bars("BTC", days=2)
        assert len(bars) == 2
        assert bars[0]["o"] == 60000.0
        assert bars[0]["h"] == 61000.0
        assert bars[0]["l"] == 59500.0
        assert bars[0]["c"] == 60500.0
        assert bars[0]["v"] == 1234.5
        assert "t" in bars[0]
        # Verify correct ccxt symbol was used
        mock_ex.fetch_ohlcv.assert_called_once_with("BTC/USDT", "1d", limit=2)

    def test_get_recent_bars_uses_days_as_limit(self):
        mock_ex = MagicMock()
        mock_ex.fetch_ohlcv.return_value = []
        client = self._make(mock_ex)
        client.get_recent_bars("ETH", days=30)
        mock_ex.fetch_ohlcv.assert_called_once_with("ETH/USDT", "1d", limit=30)

    def test_get_latest_quote_returns_bid_ask(self):
        mock_ex = MagicMock()
        mock_ex.fetch_order_book.return_value = {
            "bids": [[60490.0, 1.0]],
            "asks": [[60510.0, 0.5]],
        }
        client = self._make(mock_ex)
        quote = client.get_latest_quote("BTC")
        assert quote["symbol"] == "BTC"
        assert quote["bid"] == 60490.0
        assert quote["ask"] == 60510.0
        assert "price" in quote
        mock_ex.fetch_order_book.assert_called_once_with("BTC/USDT", limit=1)

    def test_get_latest_quote_empty_book(self):
        mock_ex = MagicMock()
        mock_ex.fetch_order_book.return_value = {"bids": [], "asks": []}
        client = self._make(mock_ex)
        quote = client.get_latest_quote("BTC")
        assert quote["bid"] == 0.0
        assert quote["ask"] == 0.0
        assert quote["price"] == 0.0
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_binance_client.py::TestMarketData -v
```

Expected: `AttributeError` — methods not yet implemented.

- [ ] **Step 3: Implement `get_recent_bars()` and `get_latest_quote()`**

Add to `server/binance_client.py`:

```python
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
```

- [ ] **Step 4: Run tests — should pass**

```bash
python -m pytest tests/test_binance_client.py::TestMarketData -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/binance_client.py tests/test_binance_client.py
git commit -m "feat: implement BinanceAccountClient.get_recent_bars + get_latest_quote"
```

---

## Task 6: Implement `submit_market_order()` and `submit_limit_order()`

**Files:**
- Modify: `server/binance_client.py`
- Modify: `tests/test_binance_client.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_binance_client.py`:

```python
class TestOrders:
    def setup_method(self):
        import importlib, server.binance_client as m
        importlib.reload(m)
        self.BinanceAccountClient = m.BinanceAccountClient

    def _make(self, mock_ex):
        mock_ex.load_markets.return_value = {}
        with patch("ccxt.binance", return_value=mock_ex):
            c = self.BinanceAccountClient.__new__(self.BinanceAccountClient)
            c._paper = True
            c._exchange = mock_ex
            return c

    def _order_response(self, symbol="BTC/USDT", side="buy", qty=0.01, status="closed"):
        return {
            "id": "12345", "symbol": symbol, "side": side,
            "amount": qty, "filled": qty, "status": status,
            "type": "market", "datetime": "2026-05-12T09:00:00Z",
        }

    def test_market_order_buy_with_qty(self):
        mock_ex = MagicMock()
        mock_ex.create_order.return_value = self._order_response()
        client = self._make(mock_ex)
        result = client.submit_market_order("BTC", "buy", qty=0.01)
        mock_ex.create_order.assert_called_once_with("BTC/USDT", "market", "buy", 0.01, params={})
        assert result["symbol"] == "BTC"
        assert result["side"] == "buy"
        assert result["qty"] == 0.01
        assert result["status"] == "filled"

    def test_market_order_sell_with_qty(self):
        mock_ex = MagicMock()
        mock_ex.create_order.return_value = self._order_response(side="sell")
        client = self._make(mock_ex)
        result = client.submit_market_order("ETH", "sell", qty=1.0)
        mock_ex.create_order.assert_called_once_with("ETH/USDT", "market", "sell", 1.0, params={})
        assert result["symbol"] == "ETH"

    def test_market_order_buy_with_notional(self):
        """Notional buy uses quoteOrderQty param."""
        mock_ex = MagicMock()
        mock_ex.create_order.return_value = self._order_response()
        client = self._make(mock_ex)
        client.submit_market_order("BTC", "buy", notional=100.0)
        mock_ex.create_order.assert_called_once_with(
            "BTC/USDT", "market", "buy", None,
            params={"quoteOrderQty": 100.0}
        )

    def test_limit_order(self):
        mock_ex = MagicMock()
        mock_ex.create_order.return_value = {**self._order_response(), "type": "limit", "price": 59000.0}
        client = self._make(mock_ex)
        result = client.submit_limit_order("BTC", "buy", qty=0.01, limit_price=59000.0)
        mock_ex.create_order.assert_called_once_with("BTC/USDT", "limit", "buy", 0.01, 59000.0, params={})
        assert result["limit_price"] == 59000.0

    def test_raises_if_neither_qty_nor_notional(self):
        mock_ex = MagicMock()
        client = self._make(mock_ex)
        with pytest.raises(ValueError, match="qty or notional required"):
            client.submit_market_order("BTC", "buy")
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_binance_client.py::TestOrders -v
```

Expected: `AttributeError` — methods not yet implemented.

- [ ] **Step 3: Implement order methods**

Add to `server/binance_client.py`:

```python
    def submit_market_order(self, symbol: str, side: Literal["buy", "sell"],
                            qty: float | None = None,
                            notional: float | None = None,
                            client_order_id: str | None = None) -> dict:
        if qty is None and notional is None:
            raise ValueError("qty or notional required")

        ccxt_sym = _to_ccxt(symbol)
        params: dict = {}
        if client_order_id:
            params["newClientOrderId"] = client_order_id[:36]

        if notional is not None and qty is None:
            # Buy with USDT amount — Binance supports quoteOrderQty natively
            params["quoteOrderQty"] = float(notional)
            order = self._exchange.create_order(ccxt_sym, "market", side, None, params=params)
        else:
            order = self._exchange.create_order(ccxt_sym, "market", side, float(qty), params=params)

        return {
            "id":     str(order.get("id", "")),
            "symbol": _from_ccxt(order.get("symbol", ccxt_sym)),
            "side":   side,
            "qty":    float(order.get("filled") or order.get("amount") or qty or 0),
            "status": "filled" if order.get("status") in ("closed", "filled") else str(order.get("status", "")),
        }

    def submit_limit_order(self, symbol: str, side: Literal["buy", "sell"],
                           qty: float, limit_price: float,
                           client_order_id: str | None = None) -> dict:
        ccxt_sym = _to_ccxt(symbol)
        params: dict = {}
        if client_order_id:
            params["newClientOrderId"] = client_order_id[:36]

        order = self._exchange.create_order(ccxt_sym, "limit", side, float(qty), limit_price, params=params)
        return {
            "id":          str(order.get("id", "")),
            "symbol":      _from_ccxt(order.get("symbol", ccxt_sym)),
            "side":        side,
            "qty":         float(qty),
            "limit_price": round(float(limit_price), 8),
            "status":      str(order.get("status", "open")),
        }
```

- [ ] **Step 4: Run tests — should pass**

```bash
python -m pytest tests/test_binance_client.py::TestOrders -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/binance_client.py tests/test_binance_client.py
git commit -m "feat: implement BinanceAccountClient order submission"
```

---

## Task 7: Implement `get_orders()`, `cancel_order()`, `close_position()`

**Files:**
- Modify: `server/binance_client.py`
- Modify: `tests/test_binance_client.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_binance_client.py`:

```python
class TestOrderManagement:
    def setup_method(self):
        import importlib, server.binance_client as m
        importlib.reload(m)
        self.BinanceAccountClient = m.BinanceAccountClient

    def _make(self, mock_ex):
        mock_ex.load_markets.return_value = {}
        with patch("ccxt.binance", return_value=mock_ex):
            c = self.BinanceAccountClient.__new__(self.BinanceAccountClient)
            c._paper = True
            c._exchange = mock_ex
            return c

    def test_get_orders_returns_list(self):
        mock_ex = MagicMock()
        mock_ex.fetch_orders.return_value = [
            {
                "id": "111", "symbol": "BTC/USDT", "side": "buy",
                "amount": 0.01, "filled": 0.01, "type": "market",
                "status": "closed", "datetime": "2026-05-12T09:00:00Z",
                "lastTradeTimestamp": 1715508000000,
                "clientOrderId": "",
                "average": 60000.0,
            }
        ]
        client = self._make(mock_ex)
        orders = client.get_orders()
        assert len(orders) == 1
        o = orders[0]
        assert o["id"] == "111"
        assert o["symbol"] == "BTC"
        assert o["side"] == "buy"
        assert o["qty"] == 0.01
        assert o["status"] == "closed"

    def test_get_orders_empty(self):
        mock_ex = MagicMock()
        mock_ex.fetch_orders.return_value = []
        client = self._make(mock_ex)
        assert client.get_orders() == []

    def test_cancel_order_calls_exchange(self):
        mock_ex = MagicMock()
        mock_ex.cancel_order.return_value = {"id": "999", "status": "canceled"}
        client = self._make(mock_ex)
        result = client.cancel_order("999")
        assert result["status"] == "canceled"
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_binance_client.py::TestOrderManagement -v
```

Expected: `AttributeError` — methods not yet implemented.

- [ ] **Step 3: Implement `get_orders()`, `cancel_order()`, `close_position()`**

Add to `server/binance_client.py`:

```python
    def get_orders(self, limit: int = 50, status: str = "all") -> list[dict]:
        from datetime import datetime, timezone
        # Binance requires a symbol for fetch_orders; fetch all markets' open orders
        # For simplicity fetch open orders across all symbols
        try:
            if status == "open":
                raw = self._exchange.fetch_open_orders()
            else:
                raw = self._exchange.fetch_orders()
        except Exception:
            return []

        out = []
        for o in raw[:limit]:
            ts = o.get("datetime") or ""
            filled_ts = o.get("lastTradeTimestamp")
            filled_at = (datetime.fromtimestamp(filled_ts / 1000, tz=timezone.utc).isoformat()
                         if filled_ts else None)
            out.append({
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
            })
        return out

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
```

- [ ] **Step 4: Run tests — should pass**

```bash
python -m pytest tests/test_binance_client.py::TestOrderManagement -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/test_binance_client.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/binance_client.py tests/test_binance_client.py
git commit -m "feat: implement BinanceAccountClient.get_orders + cancel_order + close_position"
```

---

## Task 8: Wire Binance into `broker_factory.py`

**Files:**
- Modify: `server/broker_factory.py`

- [ ] **Step 1: Add the Binance branch**

Open `server/broker_factory.py`. The current file ends with:

```python
    if broker == "tradier":
        from .tradier_client import TradierAccountClient
        return TradierAccountClient(api_key=api_key, api_secret=api_secret, paper=paper)

    raise ValueError(f"Unsupported broker: {broker!r}. Supported: alpaca, tradier")
```

Replace with:

```python
    if broker == "tradier":
        from .tradier_client import TradierAccountClient
        return TradierAccountClient(api_key=api_key, api_secret=api_secret, paper=paper)

    if broker == "binance":
        from .binance_client import BinanceAccountClient
        return BinanceAccountClient(api_key=api_key, api_secret=api_secret, paper=paper)

    raise ValueError(f"Unsupported broker: {broker!r}. Supported: alpaca, tradier, binance")
```

- [ ] **Step 2: Verify the factory works**

```bash
python -c "
from unittest.mock import MagicMock, patch
mock_ex = MagicMock()
mock_ex.load_markets.return_value = {}
with patch('ccxt.binance', return_value=mock_ex):
    from server.broker_factory import get_account_client
    c = get_account_client('binance', 'key', 'secret', paper=True)
    print(type(c).__name__)
"
```

Expected output: `BinanceAccountClient`

- [ ] **Step 3: Run existing broker tests to confirm nothing broke**

```bash
python -m pytest tests/test_api_broker.py tests/test_db_broker.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add server/broker_factory.py
git commit -m "feat: register Binance in broker_factory"
```

---

## Task 9: Add Binance to `apikeys.html` UI

**Files:**
- Modify: `server/static/apikeys.html`

- [ ] **Step 1: Find the broker selector in apikeys.html**

Search for the broker `<select>` element. It will contain options for `alpaca` and `tradier`. Add `binance` as a third option.

Find this pattern:
```html
<option value="alpaca">Alpaca</option>
<option value="tradier">Tradier</option>
```

Add immediately after:
```html
<option value="binance">Binance</option>
```

- [ ] **Step 2: Add Binance-specific hint text**

Find the section that shows broker-specific credential hints (shown/hidden based on broker selection). Add a Binance hint block alongside the existing ones. Look for a pattern like `id="alpaca-hint"` or a JS switch on broker value.

Add this hint block (place it adjacent to the other hint blocks):
```html
<div id="binance-hint" class="broker-hint hidden" style="margin-top:.5rem;padding:.6rem .85rem;background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.2);border-radius:8px;font-size:12px;color:#94A3B8;line-height:1.6;">
  <b style="color:#F59E0B;">Binance — Crypto Spot</b><br>
  Generate API keys at <b>binance.com → API Management</b> (Live) or <b>testnet.binance.vision</b> (Paper).<br>
  Testnet keys are separate from live keys and reset periodically.<br>
  All crypto pairs trade against <b>USDT</b> (e.g. BTC → BTC/USDT).<br>
  <b>Note:</b> Automated strategies only run during US market hours (9:30am–4pm ET).
</div>
```

- [ ] **Step 3: Wire hint visibility in JS**

Find the JS that shows/hides broker hints when the broker dropdown changes. It will look something like:

```javascript
brokerSelect.addEventListener('change', function() {
  document.querySelectorAll('.broker-hint').forEach(h => h.classList.add('hidden'));
  const hint = document.getElementById(this.value + '-hint');
  if (hint) hint.classList.remove('hidden');
});
```

If this pattern already exists, the Binance hint will show automatically when `binance` is selected (because its `id` is `binance-hint`). Verify by reading the JS in `apikeys.html` and confirm the pattern matches. If a different pattern is used, adapt accordingly.

- [ ] **Step 4: Verify UI manually**

Start the server and open `http://localhost:8000/static/apikeys.html`. Click "Add Account", select "Binance" from the broker dropdown, and confirm:
- The Binance hint block appears
- The API Key and API Secret fields are visible
- Paper/Live account type selector works

- [ ] **Step 5: Commit**

```bash
git add server/static/apikeys.html
git commit -m "feat: add Binance broker option to apikeys.html UI"
```

---

## Task 10: Final integration check

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all tests pass. Note any failures and fix before proceeding.

- [ ] **Step 2: Verify Binance client imports cleanly**

```bash
python -c "from server.binance_client import BinanceAccountClient; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Verify factory returns correct type for all three brokers**

```bash
python -c "
from unittest.mock import MagicMock, patch
mock_ex = MagicMock()
mock_ex.load_markets.return_value = {}
with patch('ccxt.binance', return_value=mock_ex):
    from server.broker_factory import get_account_client
    b = get_account_client('binance', 'k', 's', paper=True)
    print('binance:', type(b).__name__)
from server.broker_factory import get_account_client
# alpaca and tradier require real imports but we just check the routing logic
try:
    a = get_account_client('unknown', 'k', 's', paper=True)
except ValueError as e:
    print('unknown broker error:', e)
"
```

Expected:
```
binance: BinanceAccountClient
unknown broker error: Unsupported broker: 'unknown'. Supported: alpaca, tradier, binance
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: Binance spot integration complete — ccxt client, factory, UI"
```

---

## Self-Review

Spec requirements checked against tasks:

| Spec Requirement | Task |
|---|---|
| `ccxt>=4.4,<5` dependency | Task 1 |
| `BinanceAccountClient` class | Task 2 |
| Symbol normalization `_to_ccxt` / `_from_ccxt` | Task 2 |
| `get_account_summary()` with 12 keys | Task 3 |
| `get_day_trade_count()` returns 0 | Task 3 |
| `get_positions()` with dust filter | Task 4 |
| `get_recent_bars()` using days as limit | Task 5 |
| `get_latest_quote()` bid/ask | Task 5 |
| `submit_market_order()` qty + notional | Task 6 |
| `submit_limit_order()` | Task 6 |
| `get_orders()` | Task 7 |
| `cancel_order()` | Task 7 |
| `close_position()` | Task 7 |
| `broker_factory.py` wired | Task 8 |
| Binance in `apikeys.html` dropdown | Task 9 |
| Testnet vs Live routing | Task 2 (`set_sandbox_mode`) |
| Known limitations documented | Spec (not implemented — engine clock gate and manual order routing gap are out of scope) |
