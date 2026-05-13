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
