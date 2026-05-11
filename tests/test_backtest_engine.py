"""Unit tests for BacktestEngine."""
import pytest
import server.db as db_mod
import server.alpaca_client as alpaca_mod
from server.strategies.base import Strategy, Signal
from server.strategies import REGISTRY
from typing import ClassVar


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    db_mod.init_db()


def _make_bars(start_date: str, count: int, base_open: float = 100.0) -> list[dict]:
    """Generate `count` daily bars with linearly increasing prices."""
    from datetime import date, timedelta
    d = date.fromisoformat(start_date)
    bars = []
    for i in range(count):
        o = round(base_open + i, 2)
        bars.append({
            "t": d.isoformat() + "T14:30:00+00:00",
            "o": o,
            "h": round(o * 1.01, 2),
            "l": round(o * 0.99, 2),
            "c": round(o * 1.005, 2),
            "v": 500_000.0,
        })
        d += timedelta(days=1)
    return bars


class _BuyDay1SellDay3(Strategy):
    """Buys AAPL on evaluate() call 1, sells on call 3 (if holding)."""
    name = "_test_bt_b1s3"
    label = "Test B1S3"
    default_params: ClassVar[dict] = {}

    def __init__(self, params):
        super().__init__(params)
        self._day = 0

    def evaluate(self, positions):
        self._day += 1
        if self._day == 1 and "AAPL" not in positions:
            return [Signal("AAPL", "buy", "test", qty=1)]
        if self._day == 3 and "AAPL" in positions:
            return [Signal("AAPL", "sell", "test", qty=1)]
        return []


@pytest.fixture(autouse=True)
def register_test_strategy(monkeypatch):
    monkeypatch.setitem(REGISTRY, "_test_bt_b1s3", _BuyDay1SellDay3)


def _run_engine(monkeypatch, bars, **kwargs):
    from datetime import date
    from server.backtest import BacktestEngine

    monkeypatch.setattr(
        alpaca_mod,
        "get_recent_bars",
        lambda symbol, days=60: bars,
    )

    defaults = dict(
        strategy_name="_test_bt_b1s3",
        symbols=["AAPL"],
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 10),
        initial_capital=10_000.0,
        position_size_pct=50.0,
        commission_pct=0.0,
        slippage_pct=0.0,
    )
    defaults.update(kwargs)
    return BacktestEngine().run(**defaults)


def test_equity_curve_length(monkeypatch):
    """Equity curve has one entry per trading day in [start, end]."""
    bars = _make_bars("2024-01-02", 12)
    result = _run_engine(monkeypatch, bars)
    # bars 0–8 cover 2024-01-02 to 2024-01-10 (9 days)
    assert len(result["equity_curve"]) == 9


def test_buy_then_sell_produces_trade(monkeypatch):
    """BUY on day1 / SELL on day3 produces exactly one closed trade."""
    bars = _make_bars("2024-01-02", 12)
    result = _run_engine(monkeypatch, bars)
    assert result["total_trades"] == 1
    trade = result["trades"][0]
    assert trade["symbol"] == "AAPL"
    assert trade["side"] == "sell"


def test_fill_at_next_bar_open(monkeypatch):
    """BUY signal on day1 fills at day2 open (no slippage/commission)."""
    bars = _make_bars("2024-01-02", 12)
    # Day1 open=100, Day2 open=101 → fill price should be 101.0
    result = _run_engine(monkeypatch, bars)
    # The buy fill on day2 at 101.0 → position qty = floor(5000/101) = 49
    # SELL fills on day4 at open=103 → proceeds = 49*103 = 5047
    # pnl = 5047 - 49*101 = 5047 - 4949 = 98
    trade = result["trades"][0]
    assert trade["price"] == pytest.approx(103.0, abs=1e-3)
    assert trade["pnl"] == pytest.approx(98.0, abs=0.5)


def test_commission_deducted(monkeypatch):
    """Commission reduces cash on both buy and sell legs."""
    bars = _make_bars("2024-01-02", 12)
    result_no_fee = _run_engine(monkeypatch, bars, commission_pct=0.0)
    result_with_fee = _run_engine(monkeypatch, bars, commission_pct=1.0)
    assert result_with_fee["equity_curve"][-1]["equity"] < result_no_fee["equity_curve"][-1]["equity"]


def test_slippage_worsens_fills(monkeypatch):
    """Slippage reduces equity vs no-slippage run."""
    bars = _make_bars("2024-01-02", 12)
    result_clean = _run_engine(monkeypatch, bars, slippage_pct=0.0)
    result_slip = _run_engine(monkeypatch, bars, slippage_pct=1.0)
    assert result_slip["equity_curve"][-1]["equity"] < result_clean["equity_curve"][-1]["equity"]


def test_no_trades_win_rate_null(monkeypatch):
    """When no signals fire, win_rate_pct is None."""
    class _NoOp(Strategy):
        name = "_test_bt_noop"
        default_params: ClassVar[dict] = {}
        def evaluate(self, positions): return []

    monkeypatch.setitem(REGISTRY, "_test_bt_noop", _NoOp)
    bars = _make_bars("2024-01-02", 12)
    monkeypatch.setattr(alpaca_mod, "get_recent_bars", lambda symbol, days=60: bars)
    from datetime import date
    from server.backtest import BacktestEngine
    result = BacktestEngine().run(
        strategy_name="_test_bt_noop",
        symbols=["AAPL"],
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 10),
        initial_capital=10_000.0,
        position_size_pct=2.0,
        commission_pct=0.0,
        slippage_pct=0.0,
    )
    assert result["win_rate_pct"] is None
    assert result["total_trades"] == 0


def test_unknown_strategy_raises(monkeypatch):
    from datetime import date
    from server.backtest import BacktestEngine
    bars = _make_bars("2024-01-02", 5)
    monkeypatch.setattr(alpaca_mod, "get_recent_bars", lambda symbol, days=60: bars)
    with pytest.raises(ValueError, match="Unknown strategy"):
        BacktestEngine().run(
            strategy_name="does_not_exist",
            symbols=["AAPL"],
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 5),
            initial_capital=10_000.0,
            position_size_pct=2.0,
            commission_pct=0.0,
            slippage_pct=0.0,
        )


def test_no_data_raises(monkeypatch):
    from datetime import date
    from server.backtest import BacktestEngine
    monkeypatch.setattr(alpaca_mod, "get_recent_bars", lambda symbol, days=60: [])
    with pytest.raises(ValueError, match="No historical data"):
        BacktestEngine().run(
            strategy_name="_test_bt_b1s3",
            symbols=["AAPL"],
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 10),
            initial_capital=10_000.0,
            position_size_pct=2.0,
            commission_pct=0.0,
            slippage_pct=0.0,
        )


def test_result_saved_to_db(monkeypatch):
    """run() auto-saves result; returned id matches DB entry."""
    bars = _make_bars("2024-01-02", 12)
    result = _run_engine(monkeypatch, bars)
    assert "id" in result
    run = db_mod.get_backtest_run(result["id"])
    assert run is not None
    assert run["strategy"] == "_test_bt_b1s3"
