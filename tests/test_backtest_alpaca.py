"""Tests for the backtest thread-local override in alpaca_client."""
import threading
import pytest
import server.alpaca_client as ac


def test_bt_thread_local_not_active_by_default():
    """Without setting _bt.bars, get_recent_bars should NOT short-circuit."""
    # Verify attribute is absent (or None) on a fresh thread-local
    assert not getattr(ac._bt, "bars", None)


def test_bt_override_filters_by_date(monkeypatch):
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
