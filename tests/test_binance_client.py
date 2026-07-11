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


class TestGetAccountSummary:
    def setup_method(self):
        import importlib, server.binance_client as m
        importlib.reload(m)
        self.BinanceAccountClient = m.BinanceAccountClient

    def _make(self, balance_data):
        mock_ex = MagicMock()
        mock_ex.load_markets.return_value = {}
        mock_ex.fetch_balance.return_value = balance_data
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
        assert pos["avg_entry_price"] == 0.0
        assert pos["unrealized_pl"] == 0.0

    def test_usdt_excluded_from_positions(self):
        client = self._make({"total": {"USDT": 5000.0}, "free": {"USDT": 5000.0}})
        assert client.get_positions() == []

    def test_dust_amounts_excluded(self):
        client = self._make(
            balance={"total": {"BTC": 0.0000001, "USDT": 1000.0}, "free": {"BTC": 0.0000001, "USDT": 1000.0}},
            ticker_prices={"BTC/USDT": 60000.0},
        )
        assert client.get_positions() == []


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
        # Patch server.db.get_conn so the symbol lookup returns only BTC/USDT,
        # avoiding shared test-DB pollution from other tests' signals rows.
        import server.db as db_mod
        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [{"symbol": "BTC"}]
        with patch.object(db_mod, "get_conn", return_value=mock_conn):
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


# ── Task 3: normalized acknowledgement + fill lookup (spec §5, §19.3, §19.4) ─────

class TestNormalizedLookup:
    """get_order / get_order_by_client_id normalize the ccxt status vocabulary
    through OrderState, and expose it as authoritative lookup for recovery."""

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
            c._account_id = 7
            return c

    def test_capability_flag_supports_authoritative_lookup(self):
        mock_ex = MagicMock()
        client = self._make(mock_ex)
        assert client.supports_authoritative_lookup is True

    def test_get_order_normalizes_open_status(self):
        from server.execution_models import OrderState
        mock_ex = MagicMock()
        mock_ex.fetch_order.return_value = {
            "id": "111", "clientOrderId": "cid-1", "symbol": "BTC/USDT",
            "side": "buy", "amount": 0.01, "filled": 0.0, "average": None,
            "status": "open",
        }
        client = self._make(mock_ex)
        o = client.get_order("111", symbol="BTC")
        assert o["state"] == OrderState.ACKNOWLEDGED.value
        assert o["broker_order_id"] == "111"
        assert o["filled_qty"] == "0"

    def test_get_order_normalizes_closed_as_filled(self):
        from server.execution_models import OrderState
        mock_ex = MagicMock()
        mock_ex.fetch_order.return_value = {
            "id": "111", "clientOrderId": "cid-1", "symbol": "BTC/USDT",
            "side": "buy", "amount": 0.01, "filled": 0.01, "average": 60000.0,
            "status": "closed",
        }
        client = self._make(mock_ex)
        o = client.get_order("111", symbol="BTC")
        assert o["state"] == OrderState.FILLED.value

    def test_get_order_by_client_id_returns_single_match(self):
        mock_ex = MagicMock()
        mock_ex.fetch_order.return_value = {
            "id": "111", "clientOrderId": "cid-x", "symbol": "BTC/USDT",
            "side": "buy", "amount": 0.01, "filled": 0.01, "average": 60000.0,
            "status": "closed",
        }
        client = self._make(mock_ex)
        o = client.get_order_by_client_id("cid-x", symbol="BTC")
        assert o is not None
        assert o["client_order_id"] == "cid-x"
        # ccxt binance supports fetch by clientOrderId param
        _, kwargs = mock_ex.fetch_order.call_args
        assert kwargs.get("params", {}).get("origClientOrderId") == "cid-x" or \
               "cid-x" in str(mock_ex.fetch_order.call_args)

    def test_get_order_by_client_id_none_when_missing(self):
        import ccxt
        mock_ex = MagicMock()
        mock_ex.fetch_order.side_effect = ccxt.OrderNotFound("not found")
        client = self._make(mock_ex)
        assert client.get_order_by_client_id("nope", symbol="BTC") is None


class TestFillLookupRealExecutions:
    """When the exchange exposes per-execution trades with stable ids, use them
    directly as authoritative fills."""

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
            c._account_id = 7
            return c

    def test_get_order_fills_from_real_trades(self):
        mock_ex = MagicMock()
        mock_ex.fetch_order.return_value = {
            "id": "111", "symbol": "BTC/USDT", "clientOrderId": "c",
            "filled": 0.02, "average": 60000.0, "status": "closed", "side": "buy",
            "amount": 0.02,
        }
        mock_ex.fetch_order_trades.return_value = [
            {"id": "t1", "order": "111", "amount": 0.01, "price": 60000.0,
             "fee": {"cost": 0.5, "currency": "USDT"},
             "timestamp": 1718722800000},
            {"id": "t2", "order": "111", "amount": 0.01, "price": 60010.0,
             "fee": {"cost": 0.5, "currency": "USDT"},
             "timestamp": 1718722801000},
        ]
        client = self._make(mock_ex)
        fills = client.get_order_fills("111", symbol="BTC")
        assert len(fills) == 2
        assert fills[0].broker_fill_id == "t1"
        assert fills[0].qty == "0.01"
        assert fills[0].fee == "0.5"
        assert fills[0].fee_currency == "USDT"


class TestSyntheticMonotonicFills:
    """When only aggregate cumulative filled qty + avg price is available (no
    per-execution trades), emit deterministic monotonic synthetic deltas keyed by
    (account_id, broker_order_id, cumulative_filled_qty, snapshot_version). A
    regressing/conflicting cumulative snapshot must FREEZE (§19.4)."""

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
            c._account_id = 7
            return c

    def _order(self, filled, avg, status="open"):
        return {
            "id": "111", "symbol": "BTC/USDT", "clientOrderId": "c",
            "filled": filled, "average": avg, "status": status, "side": "buy",
            "amount": 0.03, "lastTradeTimestamp": 1718722800000,
        }

    def test_first_snapshot_emits_one_delta(self):
        mock_ex = MagicMock()
        mock_ex.fetch_order.return_value = self._order(0.01, 60000.0)
        mock_ex.fetch_order_trades.return_value = []   # no per-execution data
        client = self._make(mock_ex)
        fills = client.get_order_fills("111", symbol="BTC")
        assert len(fills) == 1
        assert fills[0].qty == "0.01"
        # synthetic id is deterministic and keyed by cumulative qty + snapshot version
        assert "111" in fills[0].broker_fill_id

    def test_growing_snapshot_emits_only_new_delta(self):
        mock_ex = MagicMock()
        mock_ex.fetch_order_trades.return_value = []
        client = self._make(mock_ex)

        mock_ex.fetch_order.return_value = self._order(0.01, 60000.0)
        first = client.get_order_fills("111", symbol="BTC")
        assert len(first) == 1

        # cumulative grows to 0.03 → only the 0.02 delta is new
        mock_ex.fetch_order.return_value = self._order(0.03, 60005.0, status="closed")
        second = client.get_order_fills("111", symbol="BTC")
        assert len(second) == 1
        assert second[0].qty == "0.02"

    def test_duplicate_snapshot_is_idempotent(self):
        mock_ex = MagicMock()
        mock_ex.fetch_order_trades.return_value = []
        mock_ex.fetch_order.return_value = self._order(0.01, 60000.0)
        client = self._make(mock_ex)
        first = client.get_order_fills("111", symbol="BTC")
        second = client.get_order_fills("111", symbol="BTC")   # identical snapshot
        assert len(first) == 1
        assert second == []           # no new deltas from a repeated snapshot

    def test_regressing_snapshot_freezes(self):
        from server.binance_client import SnapshotRegressionError
        mock_ex = MagicMock()
        mock_ex.fetch_order_trades.return_value = []
        client = self._make(mock_ex)
        mock_ex.fetch_order.return_value = self._order(0.03, 60000.0)
        client.get_order_fills("111", symbol="BTC")
        # cumulative filled qty DROPS → regression → must raise (freeze upstream)
        mock_ex.fetch_order.return_value = self._order(0.01, 60000.0)
        with pytest.raises(SnapshotRegressionError):
            client.get_order_fills("111", symbol="BTC")



class TestGetHistoricalBars:
    """Paginated daily history (research path). Live get_recent_bars is untouched."""

    def _make(self):
        mock_ex = MagicMock()
        mock_ex.load_markets.return_value = {}
        mock_ex.markets = {"BTC/USDT": {}}
        with patch("ccxt.binance", return_value=mock_ex):
            from server.binance_client import BinanceAccountClient
            c = BinanceAccountClient.__new__(BinanceAccountClient)
            c._paper = True
            c._exchange = mock_ex
            return c, mock_ex

    @staticmethod
    def _page(start_ms, n):
        day = 86_400_000
        return [[start_ms + i * day, 1.0, 2.0, 0.5, 1.5, 100.0] for i in range(n)]

    def test_paginates_past_1000_cap(self):
        """Two full pages + a short page assemble into one ascending, de-duped series."""
        c, ex = self._make()
        day = 86_400_000
        base = 1_600_000_000_000
        page1 = self._page(base, 1000)
        page2 = self._page(base + 1000 * day, 1000)
        page3 = self._page(base + 2000 * day, 300)   # short -> stop

        def fake_fetch(sym, tf, since=None, limit=None):
            if since is None or since <= page1[0][0]:
                return page1
            if since <= page2[0][0]:
                return page2
            return page3
        ex.fetch_ohlcv.side_effect = fake_fetch

        bars = c.get_historical_bars("BTC/USDT", days=2300)
        # 1000 + 1000 + 300, no duplicates, strictly ascending timestamps.
        assert len(bars) == 2300
        ts = [b["t"] for b in bars]
        assert ts == sorted(ts)
        assert len(set(ts)) == len(ts)

    def test_dedupes_overlapping_pages(self):
        """Overlapping page boundaries do not double-count a timestamp.

        Models a realistic feed: fetch_ohlcv returns bars at/after `since`, and a
        "sloppy" boundary that also re-serves the bar just before `since`. The true
        continuous series is 1200 bars ending ~now; the overlap must be de-duped.
        """
        from datetime import datetime, timezone
        c, ex = self._make()
        day = 86_400_000
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        # 1200 daily bars ending ~today, so a days=1300 window captures all of them.
        base = now_ms - 1200 * day
        full = self._page(base, 1200)

        def fake_fetch(sym, tf, since=None, limit=None):
            rows = [r for r in full if since is None or r[0] >= since]
            if since is not None:
                prior = [r for r in full if r[0] < since]
                if prior:
                    rows = [prior[-1]] + rows      # boundary overlap to de-dup
            return rows[:1000]
        ex.fetch_ohlcv.side_effect = fake_fetch

        bars = c.get_historical_bars("BTC/USDT", days=1300)
        ts = [b["t"] for b in bars]
        assert len(set(ts)) == len(ts)             # no duplicates despite overlap
        assert len(bars) == 1200                   # exactly the true series length

    def test_stops_when_no_forward_progress(self):
        """A page that does not advance the cursor must not loop forever."""
        c, ex = self._make()
        base = 1_600_000_000_000
        stuck = self._page(base, 1000)             # always same 1000, same last ts
        ex.fetch_ohlcv.return_value = stuck        # never advances
        bars = c.get_historical_bars("BTC/USDT", days=5000)
        # bounded: returns the single page's worth, does not hang
        assert len(bars) == 1000

    def test_empty_feed_returns_empty(self):
        c, ex = self._make()
        ex.fetch_ohlcv.return_value = []
        assert c.get_historical_bars("BTC/USDT", days=2200) == []

    def test_live_get_recent_bars_still_single_call(self):
        """Regression: the LIVE path makes exactly ONE fetch_ohlcv call, unpaginated."""
        c, ex = self._make()
        ex.fetch_ohlcv.return_value = self._page(1_600_000_000_000, 60)
        c.get_recent_bars("BTC/USDT", days=60)
        assert ex.fetch_ohlcv.call_count == 1
