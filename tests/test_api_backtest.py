"""API tests for the 5 /api/backtest endpoints."""
import pytest

_BASE_RESULT = {
    "total_return_pct": 10.0,
    "max_drawdown_pct": -2.0,
    "win_rate_pct": 66.7,
    "sharpe_ratio": 1.2,
    "total_trades": 3,
    "equity_curve": [{"date": "2024-01-02", "equity": 10000.0}],
    "trades": [],
}

_VALID_BODY = {
    "strategy": "sma_cross",
    "symbols": ["AAPL"],
    "start_date": "2024-01-01",
    "end_date": "2024-12-31",
}


@pytest.fixture()
def mock_engine(monkeypatch):
    """Patches BacktestEngine.run to skip Alpaca calls but still saves to DB."""
    import server.backtest as bt_mod
    import server.db as db_mod
    from datetime import date

    def _fake_run(self, strategy_name, symbols, start_date, end_date,
                  initial_capital, position_size_pct, commission_pct, slippage_pct,
                  strategy_params=None):
        result = dict(_BASE_RESULT)
        run_id = db_mod.save_backtest_run(
            {
                "strategy": strategy_name,
                "symbols": symbols,
                "start_date": start_date.isoformat() if isinstance(start_date, date) else start_date,
                "end_date": end_date.isoformat() if isinstance(end_date, date) else end_date,
                "initial_capital": initial_capital,
                "position_size_pct": position_size_pct,
                "commission_pct": commission_pct,
                "slippage_pct": slippage_pct,
            },
            result,
        )
        result["id"] = run_id
        return result

    monkeypatch.setattr(bt_mod.BacktestEngine, "run", _fake_run)


def test_run_backtest_returns_result(client, mock_engine):
    res = client.post("/api/backtest", json=_VALID_BODY)
    assert res.status_code == 200
    data = res.json()
    assert data["total_return_pct"] == 10.0
    assert isinstance(data["id"], int)


def test_run_backtest_end_before_start_is_422(client):
    res = client.post("/api/backtest", json={
        **_VALID_BODY,
        "start_date": "2024-12-31",
        "end_date": "2024-01-01",
    })
    assert res.status_code == 422


def test_run_backtest_empty_symbols_is_422(client):
    res = client.post("/api/backtest", json={**_VALID_BODY, "symbols": []})
    assert res.status_code == 422


def test_run_backtest_engine_value_error_is_400(client, monkeypatch):
    import server.backtest as bt_mod

    def _raise(*a, **kw):
        raise ValueError("Unknown strategy: bad_one")

    monkeypatch.setattr(bt_mod.BacktestEngine, "run", _raise)
    res = client.post("/api/backtest", json=_VALID_BODY)
    assert res.status_code == 400
    assert "Unknown strategy" in res.json()["detail"]


def test_list_runs_empty(client):
    res = client.get("/api/backtest/runs")
    assert res.status_code == 200
    assert res.json() == []


def test_list_runs_after_save(client, mock_engine):
    client.post("/api/backtest", json=_VALID_BODY)
    res = client.get("/api/backtest/runs")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) >= 1
    assert "equity_curve" not in rows[0]
    assert rows[0]["strategy"] == "sma_cross"


def test_get_run_detail(client, mock_engine):
    run_res = client.post("/api/backtest", json=_VALID_BODY)
    run_id = run_res.json()["id"]
    res = client.get(f"/api/backtest/runs/{run_id}")
    assert res.status_code == 200
    data = res.json()
    assert "equity_curve" in data
    assert data["strategy"] == "sma_cross"


def test_get_run_not_found(client):
    res = client.get("/api/backtest/runs/9999")
    assert res.status_code == 404


def test_patch_run_name(client, mock_engine):
    run_res = client.post("/api/backtest", json=_VALID_BODY)
    run_id = run_res.json()["id"]
    res = client.patch(f"/api/backtest/runs/{run_id}", json={"name": "My Run"})
    assert res.status_code == 200
    detail = client.get(f"/api/backtest/runs/{run_id}").json()
    assert detail["name"] == "My Run"


def test_patch_run_not_found(client):
    res = client.patch("/api/backtest/runs/9999", json={"name": "x"})
    assert res.status_code == 404


def test_delete_run(client, mock_engine):
    run_res = client.post("/api/backtest", json=_VALID_BODY)
    run_id = run_res.json()["id"]
    res = client.delete(f"/api/backtest/runs/{run_id}")
    assert res.status_code == 200
    assert client.get(f"/api/backtest/runs/{run_id}").status_code == 404


def test_delete_run_not_found(client):
    res = client.delete("/api/backtest/runs/9999")
    assert res.status_code == 404
