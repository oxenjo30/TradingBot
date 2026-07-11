"""Tests for the backtest thread-local override in alpaca_client."""
import threading
import pytest
import server.alpaca_client as ac


@pytest.fixture(autouse=True)
def _reset_bt():
    """Ensure _bt state is clean before and after every test."""
    ac._bt.bars = None
    ac._bt.current_date = None
    yield
    ac._bt.bars = None
    ac._bt.current_date = None


def test_bt_thread_local_not_active_by_default():
    """Without setting _bt.bars, get_recent_bars should NOT short-circuit."""
    # Verify attribute is absent (or None) on a fresh thread-local
    assert not getattr(ac._bt, "bars", None)


def test_bt_override_filters_by_date():
    """When _bt.bars is set, get_recent_bars returns bars up to current_date."""
    from datetime import date

    bars = [
        {"t": "2024-01-02T00:00:00+00:00", "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 1e6},
        {"t": "2024-01-03T00:00:00+00:00", "o": 101.0, "h": 102.0, "l": 100.0, "c": 101.5, "v": 1e6},
        {"t": "2024-01-04T00:00:00+00:00", "o": 102.0, "h": 103.0, "l": 101.0, "c": 102.5, "v": 1e6},
    ]
    ac._bt.bars = {"AAPL": bars}
    ac._bt.current_date = date(2024, 1, 3)

    try:
        result = ac.get_recent_bars("AAPL", days=60)
        assert len(result) == 2
        assert result[-1]["t"][:10] == "2024-01-03"
    finally:
        ac._bt.bars = None
        ac._bt.current_date = None


def test_bt_override_unknown_symbol_returns_empty():
    """Symbol not in _bt.bars returns empty list, no API call made."""
    from datetime import date

    ac._bt.bars = {"MSFT": []}
    ac._bt.current_date = date(2024, 1, 3)
    try:
        result = ac.get_recent_bars("AAPL", days=60)
        assert result == []
    finally:
        ac._bt.bars = None
        ac._bt.current_date = None


def test_bt_thread_isolation():
    """Thread-local override in one thread does not bleed into another."""
    from datetime import date

    bars = [{"t": "2024-01-02T00:00:00+00:00", "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 1e6}]

    seen_in_other_thread: list[bool] = []

    def _check():
        seen_in_other_thread.append(getattr(ac._bt, "bars", None) is not None)

    ac._bt.bars = {"AAPL": bars}
    ac._bt.current_date = date(2024, 1, 2)
    t = threading.Thread(target=_check)
    t.start()
    t.join()
    ac._bt.bars = None
    ac._bt.current_date = None

    assert seen_in_other_thread == [False]


def test_bars_provider_protocol():
    """BarsProvider protocol is structurally satisfied by a duck-typed class."""
    from server.strategies.base import BarsProvider

    class _MockProvider:
        def get_bars(self, symbol: str, limit: int) -> list[dict]:
            return []

    # Protocol check: runtime_checkable lets us use isinstance
    assert isinstance(_MockProvider(), BarsProvider)


# ── Split/dividend adjustment (research/backtest path) ──────────────────────────
#
# The live signal path must keep pulling RAW bars (default), but the historical
# research provider needs split+dividend-adjusted bars so a 10-year backtest is not
# poisoned by a split appearing as a price crash (e.g. AAPL 4:1 on 2020-08-31).

class _FakeBar:
    def __init__(self, ts, o, h, l, c, v):
        from datetime import datetime, timezone
        self.timestamp = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
        self.open, self.high, self.low, self.close, self.volume = o, h, l, c, v


class _CaptureData:
    """Stand-in for alpaca_client.data(): records the request it is handed."""
    def __init__(self):
        self.last_request = None

    def get_stock_bars(self, req):
        self.last_request = req
        sym = req.symbol_or_symbols
        return {sym: [_FakeBar("2024-01-02T00:00:00", 100, 101, 99, 100.5, 1e6)]}


def test_get_recent_bars_defaults_to_raw(monkeypatch):
    """Default call sends no split/dividend adjustment — live signals unchanged."""
    cap = _CaptureData()
    monkeypatch.setattr(ac, "data", lambda: cap)
    ac.get_recent_bars("AAPL", days=30)
    adj = getattr(cap.last_request, "adjustment", None)
    # Either the SDK default (raw / None) — never split or all.
    assert adj in (None, "raw") or getattr(adj, "value", None) in (None, "raw")


def test_get_recent_bars_passes_adjustment_all(monkeypatch):
    """adjustment='all' propagates to the StockBarsRequest (split + dividend)."""
    cap = _CaptureData()
    monkeypatch.setattr(ac, "data", lambda: cap)
    ac.get_recent_bars("AAPL", days=3650, adjustment="all")
    adj = getattr(cap.last_request, "adjustment", None)
    val = getattr(adj, "value", adj)
    assert val == "all"


def test_network_historical_provider_requests_adjusted(monkeypatch):
    """The research network provider pulls split+dividend-adjusted bars, not raw."""
    seen = {}

    def _fake_recent(symbol, days=60, adjustment="raw"):
        seen["adjustment"] = adjustment
        return [{"t": "2016-07-15T00:00:00+00:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]

    monkeypatch.setattr(ac, "get_recent_bars", _fake_recent)
    prov = ac.historical_provider()          # network provider (no fixtures)
    prov._raw_bars("AAPL")
    assert seen["adjustment"] == "all"
