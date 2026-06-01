import os
import pytest
from cryptography.fernet import Fernet
from unittest.mock import patch


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isolated in-memory-style DB per test."""
    key = Fernet.generate_key().decode()
    os.environ["DB_SECRET_KEY"] = key
    import server.crypto as crypto
    crypto.init_crypto()
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    db_mod.init_db()
    return db_mod


def _insert_run(db, strategy="RSI Mean Reversion", win_rate=0.62,
                total_return=18.4, total_trades=183):
    """Helper: insert a backtest_run and return its id."""
    params = {
        "strategy": strategy, "symbols": ["AAPL"],
        "start_date": "2025-01-01", "end_date": "2025-04-30",
        "initial_capital": 10000, "position_size_pct": 10,
        "commission_pct": 0.1, "slippage_pct": 0.05,
    }
    results = {
        "total_return_pct": total_return,
        "max_drawdown_pct": -5.0,
        "win_rate_pct": win_rate,
        "sharpe_ratio": 1.2,
        "total_trades": total_trades,
        "equity_curve": [],
        "trades": [],
        "symbol_breakdown": [],
    }
    return db.save_backtest_run(params, results)


def _insert_perf_row(db, strategy="RSI Mean Reversion", pnl=50.0, pnl_pct=1.5,
                     date="2025-05-01"):
    """Helper: insert a strategy_perf row."""
    with db.get_conn() as c:
        c.execute(
            "INSERT INTO strategy_perf (date, strategy, symbol, side, qty, notional, "
            "entry_price, exit_price, pnl, pnl_pct) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (date, strategy, "AAPL", "sell", 10, 1000, 150.0, 155.0, pnl, pnl_pct)
        )


# ── set_benchmark ─────────────────────────────────────────────────────────────

def test_set_benchmark_sets_flag(db):
    run_a = _insert_run(db)
    run_b = _insert_run(db)
    # Set run_a as benchmark
    assert db.set_benchmark(run_a) is True
    with db.get_conn() as c:
        row_a = c.execute("SELECT is_benchmark FROM backtest_runs WHERE id=?", (run_a,)).fetchone()
        row_b = c.execute("SELECT is_benchmark FROM backtest_runs WHERE id=?", (run_b,)).fetchone()
    assert row_a["is_benchmark"] == 1
    assert row_b["is_benchmark"] == 0


def test_set_benchmark_clears_previous_for_same_strategy(db):
    run_a = _insert_run(db)
    run_b = _insert_run(db)
    db.set_benchmark(run_a)
    db.set_benchmark(run_b)
    with db.get_conn() as c:
        row_a = c.execute("SELECT is_benchmark FROM backtest_runs WHERE id=?", (run_a,)).fetchone()
        row_b = c.execute("SELECT is_benchmark FROM backtest_runs WHERE id=?", (run_b,)).fetchone()
    assert row_a["is_benchmark"] == 0
    assert row_b["is_benchmark"] == 1


def test_set_benchmark_does_not_affect_other_strategies(db):
    run_rsi = _insert_run(db, strategy="RSI Mean Reversion")
    run_gc  = _insert_run(db, strategy="Golden Cross")
    db.set_benchmark(run_gc)  # only sets benchmark for Golden Cross
    with db.get_conn() as c:
        row_rsi = c.execute("SELECT is_benchmark FROM backtest_runs WHERE id=?", (run_rsi,)).fetchone()
    assert row_rsi["is_benchmark"] == 0  # RSI benchmark unchanged


def test_set_benchmark_unknown_run_returns_false(db):
    assert db.set_benchmark(99999) is False


# ── get_benchmark ─────────────────────────────────────────────────────────────

def test_get_benchmark_returns_none_when_none_set(db):
    assert db.get_benchmark("RSI Mean Reversion") is None


def test_get_benchmark_returns_correct_fields(db):
    run_id = _insert_run(db, win_rate=0.62, total_return=18.4, total_trades=183)
    db.set_benchmark(run_id)
    bm = db.get_benchmark("RSI Mean Reversion")
    assert bm is not None
    assert bm["id"] == run_id
    assert bm["win_rate_pct"] == pytest.approx(0.62)
    assert bm["avg_return_pct"] == pytest.approx(18.4 / 183)
    assert bm["total_trades"] == 183
    assert "start_date" in bm
    assert "end_date" in bm
    assert "name" in bm


def test_get_benchmark_zero_trades_guard(db):
    run_id = _insert_run(db, total_trades=0, total_return=0.0)
    db.set_benchmark(run_id)
    bm = db.get_benchmark("RSI Mean Reversion")
    assert bm["avg_return_pct"] == 0.0  # no ZeroDivisionError


# ── get_live_health_stats ─────────────────────────────────────────────────────

def test_get_live_health_stats_empty(db):
    stats = db.get_live_health_stats("RSI Mean Reversion")
    assert stats["total_trades"] == 0
    assert stats["live_win_rate"] == 0.0
    assert stats["live_avg_return_pct"] == 0.0
    assert stats["last_trade_at"] is None


def test_get_live_health_stats_counts_correctly(db):
    # 3 wins (pnl > 0), 1 loss (pnl < 0)
    _insert_perf_row(db, pnl=50.0,  pnl_pct=1.5,  date="2025-05-01")
    _insert_perf_row(db, pnl=30.0,  pnl_pct=0.9,  date="2025-05-02")
    _insert_perf_row(db, pnl=-20.0, pnl_pct=-0.6, date="2025-05-03")
    _insert_perf_row(db, pnl=10.0,  pnl_pct=0.3,  date="2025-05-04")
    stats = db.get_live_health_stats("RSI Mean Reversion")
    assert stats["total_trades"] == 4
    assert stats["live_win_rate"] == pytest.approx(3 / 4)
    assert stats["live_avg_return_pct"] == pytest.approx((1.5 + 0.9 - 0.6 + 0.3) / 4)
    assert stats["last_trade_at"] == "2025-05-04"


# ── list_backtest_runs_with_benchmark ─────────────────────────────────────────

def test_list_backtest_runs_with_benchmark_includes_is_benchmark(db):
    run_id = _insert_run(db)
    db.set_benchmark(run_id)
    runs = db.list_backtest_runs_with_benchmark()
    assert len(runs) == 1
    assert "is_benchmark" in runs[0]
    assert runs[0]["is_benchmark"] == 1


# ── API tests ─────────────────────────────────────────────────────────────────

def test_strategy_health_endpoint_returns_all_strategies(client):
    """GET /api/strategy-health returns one entry per registered strategy."""
    from server.strategies import REGISTRY
    r = client.get("/api/strategy-health")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == len(REGISTRY)
    names = {item["strategy"] for item in data}
    assert names == set(REGISTRY.keys())


def test_strategy_health_no_benchmark_state(client):
    """Strategies with no benchmark → drift_status='no_benchmark', benchmark fields null."""
    r = client.get("/api/strategy-health")
    assert r.status_code == 200
    for item in r.json():
        assert item["drift_status"] == "no_benchmark"
        assert item["benchmark_run_id"] is None


def test_strategy_health_no_data_state(client):
    """Benchmark set but fewer than 10 live trades → drift_status='no_data'."""
    import server.db as db_mod
    from server.strategies import REGISTRY
    strategy_name = next(iter(REGISTRY))
    # Insert a benchmark run
    params = {
        "strategy": strategy_name, "symbols": ["AAPL"],
        "start_date": "2025-01-01", "end_date": "2025-04-30",
        "initial_capital": 10000, "position_size_pct": 10,
        "commission_pct": 0.1, "slippage_pct": 0.05,
    }
    results = {
        "total_return_pct": 18.4, "max_drawdown_pct": -5.0,
        "win_rate_pct": 0.62, "sharpe_ratio": 1.2,
        "total_trades": 183, "equity_curve": [], "trades": [], "symbol_breakdown": [],
    }
    run_id = db_mod.save_backtest_run(params, results)
    db_mod.set_benchmark(run_id)
    # Insert only 5 live trades (< 10 threshold)
    with db_mod.get_conn() as c:
        for i in range(5):
            c.execute(
                "INSERT INTO strategy_perf (date, strategy, symbol, side, qty, "
                "notional, entry_price, exit_price, pnl, pnl_pct) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"2025-05-0{i+1}", strategy_name, "AAPL", "sell",
                 10, 1000, 150.0, 155.0, 50.0, 1.5)
            )
    r = client.get("/api/strategy-health")
    assert r.status_code == 200
    item = next(x for x in r.json() if x["strategy"] == strategy_name)
    assert item["drift_status"] == "no_data"
    assert item["benchmark_run_id"] == run_id  # benchmark fields still populated
    assert item["benchmark_win_rate"] == pytest.approx(0.62)


def test_set_benchmark_endpoint_returns_ok(client):
    import server.db as db_mod
    from server.strategies import REGISTRY
    strategy_name = next(iter(REGISTRY))
    params = {
        "strategy": strategy_name, "symbols": ["AAPL"],
        "start_date": "2025-01-01", "end_date": "2025-04-30",
        "initial_capital": 10000, "position_size_pct": 10,
        "commission_pct": 0.1, "slippage_pct": 0.05,
    }
    results = {
        "total_return_pct": 18.4, "max_drawdown_pct": -5.0,
        "win_rate_pct": 0.62, "sharpe_ratio": 1.2,
        "total_trades": 183, "equity_curve": [], "trades": [], "symbol_breakdown": [],
    }
    run_id = db_mod.save_backtest_run(params, results)
    r = client.post(f"/api/backtest/runs/{run_id}/set-benchmark")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    # Verify DB state
    bm = db_mod.get_benchmark(strategy_name)
    assert bm is not None
    assert bm["id"] == run_id


def test_set_benchmark_endpoint_404(client):
    r = client.post("/api/backtest/runs/99999/set-benchmark")
    assert r.status_code == 404


def test_backtest_runs_list_includes_is_benchmark(client):
    import server.db as db_mod
    from server.strategies import REGISTRY
    strategy_name = next(iter(REGISTRY))
    params = {
        "strategy": strategy_name, "symbols": ["AAPL"],
        "start_date": "2025-01-01", "end_date": "2025-04-30",
        "initial_capital": 10000, "position_size_pct": 10,
        "commission_pct": 0.1, "slippage_pct": 0.05,
    }
    results = {
        "total_return_pct": 18.4, "max_drawdown_pct": -5.0,
        "win_rate_pct": 0.62, "sharpe_ratio": 1.2,
        "total_trades": 183, "equity_curve": [], "trades": [], "symbol_breakdown": [],
    }
    db_mod.save_backtest_run(params, results)
    r = client.get("/api/backtest/runs")
    assert r.status_code == 200
    runs = r.json()
    assert len(runs) == 1
    assert "is_benchmark" in runs[0]
    assert runs[0]["is_benchmark"] == 0
