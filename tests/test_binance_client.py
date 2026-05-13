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
