"""DB-layer tests for backtest_runs CRUD."""
import json
import pytest
import server.db as db_mod


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    db_mod.init_db()


_PARAMS = {
    "strategy": "sma_cross",
    "symbols": ["AAPL"],
    "start_date": "2024-01-01",
    "end_date": "2024-12-31",
    "initial_capital": 10000.0,
    "position_size_pct": 2.0,
    "commission_pct": 0.1,
    "slippage_pct": 0.05,
}

_RESULTS = {
    "total_return_pct": 12.3,
    "max_drawdown_pct": -4.5,
    "win_rate_pct": 60.0,
    "sharpe_ratio": 1.1,
    "total_trades": 5,
    "equity_curve": [{"date": "2024-01-02", "equity": 10000.0}],
    "trades": [{"date": "2024-01-05", "symbol": "AAPL", "side": "sell",
                "qty": 10, "price": 185.0, "pnl": 50.0}],
}


def test_save_returns_int():
    run_id = db_mod.save_backtest_run(_PARAMS, _RESULTS)
    assert isinstance(run_id, int)
    assert run_id >= 1


def test_list_returns_summary_only():
    db_mod.save_backtest_run(_PARAMS, _RESULTS)
    rows = db_mod.list_backtest_runs()
    assert len(rows) == 1
    row = rows[0]
    assert row["strategy"] == "sma_cross"
    assert row["symbols"] == ["AAPL"]
    assert "equity_curve" not in row
    assert "trades" not in row


def test_list_excludes_equity_curve_and_trades():
    db_mod.save_backtest_run(_PARAMS, _RESULTS)
    rows = db_mod.list_backtest_runs()
    assert "equity_curve" not in rows[0]
    assert "trades" not in rows[0]


def test_get_includes_equity_and_trades():
    run_id = db_mod.save_backtest_run(_PARAMS, _RESULTS)
    run = db_mod.get_backtest_run(run_id)
    assert run is not None
    assert run["equity_curve"] == _RESULTS["equity_curve"]
    assert run["trades"] == _RESULTS["trades"]
    assert run["symbols"] == ["AAPL"]


def test_get_unknown_returns_none():
    assert db_mod.get_backtest_run(9999) is None


def test_delete_removes_run():
    run_id = db_mod.save_backtest_run(_PARAMS, _RESULTS)
    result = db_mod.delete_backtest_run(run_id)
    assert result is True
    assert db_mod.get_backtest_run(run_id) is None


def test_delete_unknown_returns_false():
    assert db_mod.delete_backtest_run(9999) is False


def test_rename_updates_name():
    run_id = db_mod.save_backtest_run(_PARAMS, _RESULTS)
    result = db_mod.rename_backtest_run(run_id, "My Best Run")
    assert result is True
    run = db_mod.get_backtest_run(run_id)
    assert run["name"] == "My Best Run"


def test_rename_unknown_returns_false():
    assert db_mod.rename_backtest_run(9999, "x") is False


def test_win_rate_null_preserved():
    results_no_trades = dict(_RESULTS, win_rate_pct=None, total_trades=0, trades=[])
    run_id = db_mod.save_backtest_run(_PARAMS, results_no_trades)
    run = db_mod.get_backtest_run(run_id)
    assert run["win_rate_pct"] is None


def test_list_ordered_newest_first():
    db_mod.save_backtest_run(_PARAMS, _RESULTS)
    db_mod.save_backtest_run(dict(_PARAMS, strategy="momentum"), _RESULTS)
    rows = db_mod.list_backtest_runs()
    assert rows[0]["strategy"] == "momentum"
