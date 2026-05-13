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
