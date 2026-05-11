# Backtesting Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full backtesting feature — backend engine that simulates any registered strategy against historical Alpaca OHLCV data, REST API to run/save/compare results, and a frontend UI on `backtesting.html`.

**Architecture:** A thread-local override in `alpaca_client.get_recent_bars` intercepts calls from strategies during the simulation loop so the live APScheduler engine never sees the override. `BacktestEngine.run()` is a synchronous method dispatched via `asyncio.to_thread` from an async FastAPI endpoint; results are auto-saved to a new `backtest_runs` SQLite table. The frontend stacks a config card above a results section (hidden until first run) above a permanent history list.

**Tech Stack:** Python 3.13, FastAPI + Pydantic v2, SQLite3, `statistics` stdlib, vanilla JS + Tailwind CDN + ApexCharts CDN (no build step).

---

## File Map

| Action | File |
|--------|------|
| Modify | `server/alpaca_client.py` |
| Modify | `server/strategies/base.py` |
| Create | `tests/test_backtest_alpaca.py` |
| Modify | `server/db.py` |
| Create | `tests/test_db_backtest.py` |
| Create | `server/backtest.py` |
| Create | `tests/test_backtest_engine.py` |
| Modify | `server/main.py` |
| Create | `tests/test_api_backtest.py` |
| Modify | `server/static/backtesting.html` |
| Modify | `server/static/app.js` |

---

## Task 1: Thread-local patch in alpaca_client + BarsProvider protocol in base.py

**Files:**
- Modify: `server/alpaca_client.py`
- Modify: `server/strategies/base.py`
- Create: `tests/test_backtest_alpaca.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backtest_alpaca.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_backtest_alpaca.py -v
```

Expected: All 5 tests FAIL — `_bt` not defined, `BarsProvider` not importable.

- [ ] **Step 3: Add thread-local to `server/alpaca_client.py`**

At the top of the file, after `from .config import ...`, add:

```python
import threading

_bt = threading.local()
```

Then replace the existing `get_recent_bars` function (lines 147–167) with:

```python
def get_recent_bars(symbol: str, days: int = 60) -> list[dict]:
    if getattr(_bt, "bars", None) is not None:
        sym = symbol.upper()
        cutoff = _bt.current_date.isoformat()
        return [b for b in _bt.bars.get(sym, []) if b["t"][:10] <= cutoff]

    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    start = end - timedelta(days=days)
    req = StockBarsRequest(
        symbol_or_symbols=symbol.upper(),
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )
    bars = data().get_stock_bars(req)
    out = []
    for b in bars[symbol.upper()]:
        out.append({
            "t": b.timestamp.isoformat(),
            "o": float(b.open),
            "h": float(b.high),
            "l": float(b.low),
            "c": float(b.close),
            "v": float(b.volume),
        })
    return out
```

- [ ] **Step 4: Add `BarsProvider` protocol to `server/strategies/base.py`**

Change the first line from:

```python
from typing import Literal, ClassVar
```

to:

```python
from typing import Literal, ClassVar, Protocol, runtime_checkable
```

Then add this block immediately after the imports (before the `Signal` dataclass):

```python
@runtime_checkable
class BarsProvider(Protocol):
    def get_bars(self, symbol: str, limit: int) -> list[dict]: ...
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_backtest_alpaca.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 6: Run full test suite to check no regressions**

```
pytest --tb=short -q
```

Expected: All previously passing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add server/alpaca_client.py server/strategies/base.py tests/test_backtest_alpaca.py
git commit -m "feat: add thread-local backtest override to alpaca_client + BarsProvider protocol"
```

---

## Task 2: `backtest_runs` table + 5 CRUD functions in `db.py`

**Files:**
- Modify: `server/db.py`
- Create: `tests/test_db_backtest.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_db_backtest.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_db_backtest.py -v
```

Expected: All tests FAIL — `save_backtest_run` not defined.

- [ ] **Step 3: Add `backtest_runs` table to the SCHEMA constant in `server/db.py`**

Locate the closing `"""` of the SCHEMA string (after the `strategy_accounts` table and two index lines). Add before that closing `"""`:

```sql
CREATE TABLE IF NOT EXISTS backtest_runs (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at        TEXT NOT NULL,
  name              TEXT,
  strategy          TEXT NOT NULL,
  symbols           TEXT NOT NULL,
  start_date        TEXT NOT NULL,
  end_date          TEXT NOT NULL,
  initial_capital   REAL NOT NULL,
  position_size_pct REAL NOT NULL,
  commission_pct    REAL NOT NULL,
  slippage_pct      REAL NOT NULL,
  total_return_pct  REAL,
  max_drawdown_pct  REAL,
  win_rate_pct      REAL,
  sharpe_ratio      REAL,
  total_trades      INTEGER,
  equity_curve      TEXT,
  trades            TEXT
);
```

- [ ] **Step 4: Add the 5 CRUD functions to `server/db.py`**

Append to the end of `db.py` (after `reset_consecutive_losses`):

```python
# ── Backtest Runs ─────────────────────────────────────────────────────────────

def save_backtest_run(params: dict, results: dict) -> int:
    with get_conn() as c:
        cur = c.execute(
            """INSERT INTO backtest_runs (
                created_at, name, strategy, symbols, start_date, end_date,
                initial_capital, position_size_pct, commission_pct, slippage_pct,
                total_return_pct, max_drawdown_pct, win_rate_pct, sharpe_ratio,
                total_trades, equity_curve, trades
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now_iso(),
                None,
                params["strategy"],
                json.dumps(params["symbols"]),
                params["start_date"],
                params["end_date"],
                params["initial_capital"],
                params["position_size_pct"],
                params["commission_pct"],
                params["slippage_pct"],
                results.get("total_return_pct"),
                results.get("max_drawdown_pct"),
                results.get("win_rate_pct"),
                results.get("sharpe_ratio"),
                results.get("total_trades"),
                json.dumps(results.get("equity_curve", [])),
                json.dumps(results.get("trades", [])),
            ),
        )
        return cur.lastrowid


def list_backtest_runs() -> list[dict]:
    with get_conn() as c:
        rows = c.execute(
            """SELECT id, created_at, name, strategy, symbols, start_date, end_date,
                      initial_capital, position_size_pct, commission_pct, slippage_pct,
                      total_return_pct, max_drawdown_pct, win_rate_pct, sharpe_ratio, total_trades
               FROM backtest_runs ORDER BY id DESC"""
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["symbols"] = json.loads(d["symbols"])
        result.append(d)
    return result


def get_backtest_run(run_id: int) -> dict | None:
    with get_conn() as c:
        r = c.execute(
            "SELECT * FROM backtest_runs WHERE id=?", (run_id,)
        ).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["symbols"] = json.loads(d["symbols"])
    d["equity_curve"] = json.loads(d["equity_curve"]) if d["equity_curve"] else []
    d["trades"] = json.loads(d["trades"]) if d["trades"] else []
    return d


def delete_backtest_run(run_id: int) -> bool:
    with get_conn() as c:
        cur = c.execute("DELETE FROM backtest_runs WHERE id=?", (run_id,))
        return cur.rowcount > 0


def rename_backtest_run(run_id: int, name: str) -> bool:
    with get_conn() as c:
        cur = c.execute(
            "UPDATE backtest_runs SET name=? WHERE id=?", (name, run_id)
        )
        return cur.rowcount > 0
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_db_backtest.py -v
```

Expected: All 11 tests PASS.

- [ ] **Step 6: Run full test suite**

```
pytest --tb=short -q
```

Expected: All previously passing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add server/db.py tests/test_db_backtest.py
git commit -m "feat: add backtest_runs table and 5 CRUD functions to db.py"
```

---

## Task 3: `BacktestEngine` in `server/backtest.py`

**Files:**
- Create: `server/backtest.py`
- Create: `tests/test_backtest_engine.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backtest_engine.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_backtest_engine.py -v
```

Expected: All tests FAIL — `server.backtest` module does not exist.

- [ ] **Step 3: Create `server/backtest.py`**

```python
import math
from datetime import date
from statistics import mean, stdev

from . import alpaca_client, db
from . import strategies as strat_mod


class BacktestEngine:

    def run(
        self,
        strategy_name: str,
        symbols: list[str],
        start_date: date,
        end_date: date,
        initial_capital: float,
        position_size_pct: float,
        commission_pct: float,
        slippage_pct: float,
    ) -> dict:
        if strategy_name not in strat_mod.REGISTRY:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        symbols_up = [s.upper() for s in symbols]

        # 1. Fetch full history (extra 200-day buffer for strategy lookback windows)
        lookback_days = (end_date - start_date).days + 200
        all_bars: dict[str, list[dict]] = {}
        for sym in symbols_up:
            bars = alpaca_client.get_recent_bars(sym, days=lookback_days)
            in_range = [b for b in bars if start_date.isoformat() <= b["t"][:10] <= end_date.isoformat()]
            if not in_range:
                raise ValueError(f"No historical data found for {sym} in the given date range")
            all_bars[sym] = sorted(bars, key=lambda b: b["t"])

        # 2. Build trading calendar — union of dates across symbols within [start, end]
        all_dates: set[str] = set()
        for bars in all_bars.values():
            for b in bars:
                d = b["t"][:10]
                if start_date.isoformat() <= d <= end_date.isoformat():
                    all_dates.add(d)
        trading_calendar = sorted(all_dates)

        # 3. Instantiate strategy restricted to user-specified symbols
        strategy = strat_mod.build(
            strategy_name,
            {"symbols": symbols_up, "use_scanner": False},
        )

        # 4. Simulation state
        cash = float(initial_capital)
        positions: dict[str, dict] = {}   # {sym: {"qty": float, "entry_price": float}}
        last_close: dict[str, float] = {}
        equity_curve: list[dict] = []
        closed_trades: list[dict] = []
        pending_fills: list[tuple[str, str]] = []  # (sym, "buy"|"sell")
        portfolio_equity = float(initial_capital)

        try:
            alpaca_client._bt.bars = all_bars

            for date_str in trading_calendar:
                alpaca_client._bt.current_date = date.fromisoformat(date_str)

                # Step A: Execute pending fills at today's open
                next_pending: list[tuple[str, str]] = []
                for sym, side in pending_fills:
                    bar = next(
                        (b for b in all_bars.get(sym, []) if b["t"][:10] == date_str),
                        None,
                    )
                    if bar is None:
                        next_pending.append((sym, side))  # defer: no bar today
                        continue
                    if side == "buy" and sym not in positions:
                        fill_price = bar["o"] * (1 + slippage_pct / 100)
                        notional = portfolio_equity * position_size_pct / 100
                        qty = math.floor(notional / fill_price)
                        if qty > 0:
                            cost = qty * fill_price
                            commission = cost * commission_pct / 100
                            cash -= cost + commission
                            positions[sym] = {"qty": float(qty), "entry_price": fill_price}
                    elif side == "sell" and sym in positions:
                        pos = positions.pop(sym)
                        fill_price = bar["o"] * (1 - slippage_pct / 100)
                        proceeds = pos["qty"] * fill_price
                        commission = proceeds * commission_pct / 100
                        cash += proceeds - commission
                        pnl = (proceeds - commission) - pos["qty"] * pos["entry_price"]
                        closed_trades.append({
                            "date": date_str,
                            "symbol": sym,
                            "side": "sell",
                            "qty": pos["qty"],
                            "price": round(fill_price, 4),
                            "pnl": round(pnl, 4),
                        })
                pending_fills = next_pending

                # Step B: Mark-to-market at close
                mkt_value = 0.0
                for sym, pos in positions.items():
                    bar = next(
                        (b for b in all_bars.get(sym, []) if b["t"][:10] == date_str),
                        None,
                    )
                    if bar:
                        mkt_value += pos["qty"] * bar["c"]
                        last_close[sym] = bar["c"]
                    elif sym in last_close:
                        mkt_value += pos["qty"] * last_close[sym]
                portfolio_equity = cash + mkt_value
                equity_curve.append({"date": date_str, "equity": round(portfolio_equity, 2)})

                # Step C: Generate signals for next fill
                simple_pos = {sym: pos["qty"] for sym, pos in positions.items()}
                try:
                    signals = strategy.evaluate(simple_pos)
                except Exception:
                    signals = []
                for sig in signals:
                    sym_up = sig.symbol.upper()
                    if sig.side == "buy" and sym_up not in positions:
                        if not any(p[0] == sym_up and p[1] == "buy" for p in pending_fills):
                            pending_fills.append((sym_up, "buy"))
                    elif sig.side == "sell" and sym_up in positions:
                        pending_fills.append((sym_up, "sell"))

        finally:
            alpaca_client._bt.bars = None
            alpaca_client._bt.current_date = None

        # 5. Summary stats
        final_equity = equity_curve[-1]["equity"] if equity_curve else initial_capital
        total_return_pct = (final_equity - initial_capital) / initial_capital * 100

        peak = float(initial_capital)
        max_drawdown_pct = 0.0
        for point in equity_curve:
            eq = point["equity"]
            if eq > peak:
                peak = eq
            dd = (eq - peak) / peak * 100 if peak > 0 else 0.0
            if dd < max_drawdown_pct:
                max_drawdown_pct = dd

        total_trades = len(closed_trades)
        win_rate_pct: float | None
        if total_trades > 0:
            winners = sum(1 for t in closed_trades if t["pnl"] > 0)
            win_rate_pct = winners / total_trades * 100
        else:
            win_rate_pct = None

        equities = [p["equity"] for p in equity_curve]
        if len(equities) >= 2:
            daily_returns = [
                (equities[i] - equities[i - 1]) / equities[i - 1]
                for i in range(1, len(equities))
            ]
            std = stdev(daily_returns) if len(daily_returns) >= 2 else 0.0
            sharpe_ratio = (mean(daily_returns) / std * (252 ** 0.5)) if std > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        result: dict = {
            "total_return_pct": round(total_return_pct, 4),
            "max_drawdown_pct": round(max_drawdown_pct, 4),
            "win_rate_pct": round(win_rate_pct, 2) if win_rate_pct is not None else None,
            "sharpe_ratio": round(sharpe_ratio, 4),
            "total_trades": total_trades,
            "equity_curve": equity_curve,
            "trades": closed_trades,
        }

        # 6. Persist and attach id
        run_id = db.save_backtest_run(
            {
                "strategy": strategy_name,
                "symbols": symbols,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "initial_capital": initial_capital,
                "position_size_pct": position_size_pct,
                "commission_pct": commission_pct,
                "slippage_pct": slippage_pct,
            },
            result,
        )
        result["id"] = run_id
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_backtest_engine.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 5: Run full test suite**

```
pytest --tb=short -q
```

Expected: All previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add server/backtest.py tests/test_backtest_engine.py
git commit -m "feat: add BacktestEngine with thread-local isolation and auto-save"
```

---

## Task 4: REST API endpoints in `server/main.py`

**Files:**
- Modify: `server/main.py`
- Create: `tests/test_api_backtest.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_backtest.py`:

```python
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
                  initial_capital, position_size_pct, commission_pct, slippage_pct):
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_api_backtest.py -v
```

Expected: All tests FAIL — `/api/backtest` endpoints do not exist.

- [ ] **Step 3: Add imports to `server/main.py`**

Change line 1 from:

```python
import logging
import os
from contextlib import asynccontextmanager
from typing import Literal
```

to:

```python
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal
```

Change the pydantic import line from:

```python
from pydantic import BaseModel, Field, model_validator
```

to:

```python
from pydantic import BaseModel, Field, field_validator, model_validator
```

Change the relative imports line from:

```python
from . import alpaca_client, auth, crypto, db, engine, notifications, risk, scanner, strategies
```

to:

```python
from . import alpaca_client, auth, backtest as bt_mod, crypto, db, engine, notifications, risk, scanner, strategies
```

- [ ] **Step 4: Add Pydantic models and 5 endpoints to `server/main.py`**

Find the end of the file (or a logical grouping point after the existing endpoints) and append:

```python
# ── Backtesting ───────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    strategy:          str
    symbols:           list[str] = Field(..., min_length=1)
    start_date:        date
    end_date:          date
    initial_capital:   float = 10000.0
    position_size_pct: float = 2.0
    commission_pct:    float = 0.1
    slippage_pct:      float = 0.05

    @field_validator("end_date", mode="after")
    @classmethod
    def end_after_start(cls, v, info):
        if info.data.get("start_date") and v <= info.data["start_date"]:
            raise ValueError("end_date must be after start_date")
        return v


class BacktestRunPatch(BaseModel):
    name: str = Field(..., max_length=200)


@app.post("/api/backtest")
async def run_backtest(req: BacktestRequest, request: Request):
    _require_auth(request)
    engine_bt = bt_mod.BacktestEngine()
    try:
        result = await asyncio.to_thread(
            engine_bt.run,
            req.strategy,
            req.symbols,
            req.start_date,
            req.end_date,
            req.initial_capital,
            req.position_size_pct,
            req.commission_pct,
            req.slippage_pct,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return result


@app.get("/api/backtest/runs")
async def list_backtest_runs(request: Request):
    _require_auth(request)
    return db.list_backtest_runs()


@app.get("/api/backtest/runs/{run_id}")
async def get_backtest_run(run_id: int, request: Request):
    _require_auth(request)
    run = db.get_backtest_run(run_id)
    if run is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return run


@app.patch("/api/backtest/runs/{run_id}")
async def patch_backtest_run(run_id: int, body: BacktestRunPatch, request: Request):
    _require_auth(request)
    if not db.rename_backtest_run(run_id, body.name):
        raise HTTPException(404, f"Run {run_id} not found")
    return {"status": "ok"}


@app.delete("/api/backtest/runs/{run_id}")
async def delete_backtest_run(run_id: int, request: Request):
    _require_auth(request)
    if not db.delete_backtest_run(run_id):
        raise HTTPException(404, f"Run {run_id} not found")
    return {"status": "ok"}
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_api_backtest.py -v
```

Expected: All 12 tests PASS.

- [ ] **Step 6: Run full test suite**

```
pytest --tb=short -q
```

Expected: All previously passing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add server/main.py tests/test_api_backtest.py
git commit -m "feat: add 5 /api/backtest REST endpoints with Pydantic validation"
```

---

## Task 5: Rewrite `server/static/backtesting.html`

**Files:**
- Modify: `server/static/backtesting.html`

_(No automated tests — verify manually in browser after Task 6 is complete.)_

- [ ] **Step 1: Replace the full content of `server/static/backtesting.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Backtesting Studio &ndash; TradeBot</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/apexcharts"></script>
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body data-page="backtesting">

<!-- Sidebar -->
<aside class="sidebar">
  <div class="logo">
    <div class="logo-mark icon-blue">
      <svg width="18" height="18" viewBox="0 0 22 22" fill="none">
        <path d="M11 2L20 7.5V14.5L11 20L2 14.5V7.5L11 2Z" fill="url(#lgs)"/>
        <defs><linearGradient id="lgs" x1="2" y1="2" x2="20" y2="20">
          <stop stop-color="#3B82F6"/><stop offset="1" stop-color="#8B5CF6"/>
        </linearGradient></defs>
      </svg>
    </div>
    <span class="logo-text">TradeBot</span>
  </div>

  <nav class="nav">
    <p class="nav-section">Overview</p>
    <a href="/static/index.html" class="nav-item" data-page="index">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
      Dashboard
    </a>
    <p class="nav-section">Analysis</p>
    <a href="/static/performance.html" class="nav-item" data-page="performance">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
      Performance
    </a>
    <a href="/static/backtesting.html" class="nav-item" data-page="backtesting">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
      Backtesting
    </a>
    <p class="nav-section">Portfolio</p>
    <a href="/static/positions.html" class="nav-item" data-page="positions">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
      Positions &amp; Orders
    </a>
    <a href="/static/balances.html" class="nav-item" data-page="balances">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>
      Balances
    </a>
    <a href="/static/bots.html" class="nav-item" data-page="bots">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="2" height="2"/><rect x="13" y="9" width="2" height="2"/><path d="M9 13a3 3 0 0 0 6 0"/></svg>
      Bots &amp; Strategies
    </a>
    <p class="nav-section">System</p>
    <a href="/static/risk.html" class="nav-item" data-page="risk">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
      Risk
    </a>
    <a href="/static/logs.html" class="nav-item" data-page="logs">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
      Logs &amp; Signals
    </a>
    <a href="/static/apikeys.html" class="nav-item" data-page="apikeys">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
      Broker Accounts
    </a>
    <a href="/static/settings.html" class="nav-item" data-page="settings">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
      Settings
    </a>
  </nav>

  <div class="sidebar-footer">
    <div class="paper-card">
      <p class="paper-label">Paper Trading Mode</p>
      <p style="font-size:12px;color:#E6EBF5;margin-top:2px;">Safe sandbox environment</p>
      <a href="#" class="go-live">Go Live &rarr;</a>
    </div>
  </div>
</aside>

<!-- Page wrapper -->
<div class="main">

  <!-- Header -->
  <header class="page-header">
    <div class="title-wrap flex-1 min-w-0">
      <div class="page-title">Backtesting Studio</div>
      <div class="page-sub">Test strategies against historical OHLCV data</div>
    </div>
    <div class="search-bar">
      <svg width="14" height="14" fill="none" stroke="#64748B" stroke-width="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <span class="search-text">Search&hellip;</span>
    </div>
    <div class="bell-wrap">
      <svg width="18" height="18" fill="none" stroke="#64748B" stroke-width="1.8" viewBox="0 0 24 24"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
    </div>
    <div id="market-chip" class="market-chip">US Equities&hellip;</div>
    <span id="paper-badge" class="plan-badge hidden">Paper Mode</span>
    <div class="flex items-center gap-2">
      <div class="avatar">JR</div>
      <div class="hidden md:block">
        <div style="font-size:13px;font-weight:600;">Trader</div>
        <div class="text-muted" style="font-size:11px;">Admin</div>
      </div>
      <div class="online-dot"></div>
    </div>
  </header>

  <!-- Main -->
  <main class="content flex flex-col gap-4">

    <!-- Error banner -->
    <div id="bt-error" class="hidden" style="padding:.65rem 1rem;border-radius:8px;background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.3);color:#EF4444;font-size:13px;"></div>

    <!-- Config card -->
    <div class="card">
      <div style="font-size:14px;font-weight:600;margin-bottom:1rem;">Configuration</div>

      <!-- Row 1: strategy, symbols, dates -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
        <div class="form-group">
          <label class="form-label">Strategy</label>
          <select id="bt-strategy" class="input-field">
            <option value="">Loading&hellip;</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Symbols (comma-separated)</label>
          <input id="bt-symbols" type="text" class="input-field" placeholder="AAPL, MSFT" value="AAPL">
        </div>
        <div class="form-group">
          <label class="form-label">Start Date</label>
          <input id="bt-start" type="date" class="input-field">
        </div>
        <div class="form-group">
          <label class="form-label">End Date</label>
          <input id="bt-end" type="date" class="input-field">
        </div>
      </div>

      <!-- Row 2: sizing params -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <div class="form-group">
          <label class="form-label">Initial Capital ($)</label>
          <input id="bt-capital" type="number" class="input-field" value="10000" min="1" step="100">
        </div>
        <div class="form-group">
          <label class="form-label">Position Size (%)</label>
          <input id="bt-possize" type="number" class="input-field" value="2" min="0.01" max="100" step="0.01">
        </div>
        <div class="form-group">
          <label class="form-label">Commission (%)</label>
          <input id="bt-commission" type="number" class="input-field" value="0.1" min="0" step="0.01">
        </div>
        <div class="form-group">
          <label class="form-label">Slippage (%)</label>
          <input id="bt-slippage" type="number" class="input-field" value="0.05" min="0" step="0.01">
        </div>
      </div>

      <div class="flex justify-end">
        <button id="bt-run-btn" class="btn btn-primary" onclick="runBacktest()">Run Backtest</button>
      </div>
    </div>

    <!-- Results section (hidden until first run) -->
    <div id="bt-results" class="hidden flex flex-col gap-4">

      <!-- Stat pills -->
      <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div class="card" style="text-align:center;padding:.875rem;">
          <div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.3rem;">Total Return</div>
          <div id="bt-stat-return" style="font-size:20px;font-weight:700;">&mdash;</div>
        </div>
        <div class="card" style="text-align:center;padding:.875rem;">
          <div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.3rem;">Max Drawdown</div>
          <div id="bt-stat-drawdown" style="font-size:20px;font-weight:700;color:#EF4444;">&mdash;</div>
        </div>
        <div class="card" style="text-align:center;padding:.875rem;">
          <div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.3rem;">Win Rate</div>
          <div id="bt-stat-winrate" style="font-size:20px;font-weight:700;">&mdash;</div>
        </div>
        <div class="card" style="text-align:center;padding:.875rem;">
          <div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.3rem;">Sharpe Ratio</div>
          <div id="bt-stat-sharpe" style="font-size:20px;font-weight:700;">&mdash;</div>
        </div>
        <div class="card" style="text-align:center;padding:.875rem;">
          <div class="text-muted" style="font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.3rem;">Total Trades</div>
          <div id="bt-stat-trades" style="font-size:20px;font-weight:700;">&mdash;</div>
        </div>
      </div>

      <!-- Equity curve chart -->
      <div class="card">
        <div style="font-size:14px;font-weight:600;margin-bottom:.875rem;">Equity Curve</div>
        <div id="bt-chart" style="min-height:280px;"></div>
      </div>

      <!-- Name / save row -->
      <div class="card">
        <div style="font-size:14px;font-weight:600;margin-bottom:.875rem;">Label This Run</div>
        <div class="flex gap-3 items-center">
          <input id="bt-run-name" type="text" class="input-field" style="flex:1;" placeholder="Optional label&hellip;">
          <button class="btn btn-ghost btn-sm" onclick="renameRun()">Save Name</button>
        </div>
      </div>

      <!-- Trades table -->
      <div class="card">
        <div style="font-size:14px;font-weight:600;margin-bottom:.875rem;">Trades</div>
        <table class="dtable">
          <thead><tr>
            <th>Date</th><th>Symbol</th><th>Side</th><th>Shares</th><th>Fill Price</th><th>P&amp;L</th>
          </tr></thead>
          <tbody id="bt-trades-body">
            <tr><td colspan="6" class="state-empty">No trades yet.</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- History section (always visible) -->
    <div class="card">
      <div style="font-size:14px;font-weight:600;margin-bottom:.875rem;">Saved Runs</div>
      <div id="bt-history-list">
        <div class="state-empty">No saved runs yet.</div>
      </div>
    </div>

  </main>
</div>

<script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add server/static/backtesting.html
git commit -m "feat: rewrite backtesting.html with stacked layout (config + results + history)"
```

---

## Task 6: Add `initBacktesting` and helpers to `server/static/app.js`

**Files:**
- Modify: `server/static/app.js`

_(No automated tests — verified manually in browser.)_

- [ ] **Step 1: Add `backtesting: initBacktesting` to `PAGE_INIT`**

In `app.js`, locate the `PAGE_INIT` block:

```javascript
const PAGE_INIT = {
  index:       initDashboard,
  bots:        initBots,
  positions:   initPositions,
  performance: initPerformance,
  balances:    initBalances,
  logs:        initLogs,
  apikeys:     initApiKeys,
  risk:        initRisk,
  settings:    initSettings,
  // login excluded — uses own inline script
};
```

Replace with:

```javascript
const PAGE_INIT = {
  index:        initDashboard,
  bots:         initBots,
  positions:    initPositions,
  performance:  initPerformance,
  balances:     initBalances,
  logs:         initLogs,
  apikeys:      initApiKeys,
  risk:         initRisk,
  settings:     initSettings,
  backtesting:  initBacktesting,
  // login excluded — uses own inline script
};
```

- [ ] **Step 2: Append the 7 backtesting functions to the end of `app.js`**

```javascript
// ─────────────────────────────────────────
// initBacktesting — backtesting.html
// ─────────────────────────────────────────

let _btCurrentRunId = null;
let _btEquityChart  = null;

async function initBacktesting() {
  // Populate strategy dropdown from /api/strategies
  try {
    const strats = await api('/api/strategies');
    const sel = document.getElementById('bt-strategy');
    sel.innerHTML = strats
      .filter(s => !s.hidden)
      .map(s => `<option value="${s.name}">${s.label}</option>`)
      .join('');
  } catch (e) {
    console.error('initBacktesting: failed to load strategies', e);
  }

  // Default date range: last 365 days
  const today    = new Date().toISOString().slice(0, 10);
  const yearAgo  = new Date(Date.now() - 365 * 86400_000).toISOString().slice(0, 10);
  document.getElementById('bt-end').value   = today;
  document.getElementById('bt-start').value = yearAgo;

  // Load history
  try {
    const runs = await api('/api/backtest/runs');
    renderHistory(runs);
  } catch (e) {
    console.error('initBacktesting: failed to load history', e);
  }
}

async function runBacktest() {
  const btn   = document.getElementById('bt-run-btn');
  const errEl = document.getElementById('bt-error');
  errEl.classList.add('hidden');

  const rawSymbols = document.getElementById('bt-symbols').value;
  const symbols = rawSymbols.split(',').map(s => s.trim()).filter(Boolean);

  const body = {
    strategy:          document.getElementById('bt-strategy').value,
    symbols,
    start_date:        document.getElementById('bt-start').value,
    end_date:          document.getElementById('bt-end').value,
    initial_capital:   parseFloat(document.getElementById('bt-capital').value),
    position_size_pct: parseFloat(document.getElementById('bt-possize').value),
    commission_pct:    parseFloat(document.getElementById('bt-commission').value),
    slippage_pct:      parseFloat(document.getElementById('bt-slippage').value),
  };

  btn.disabled = true;
  btn.innerHTML = '<svg style="width:14px;height:14px;animation:spin 1s linear infinite;margin-right:6px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>Running&hellip;';

  try {
    const res = await fetch('/api/backtest', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    });
    if (res.status === 401) { location.href = '/static/login.html'; return; }
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    renderResults(data);
    try { renderHistory(await api('/api/backtest/runs')); } catch (_) { /* non-fatal */ }
  } catch (e) {
    errEl.textContent = e.message;
    errEl.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Run Backtest';
  }
}

function renderResults(data) {
  _btCurrentRunId = data.id;
  document.getElementById('bt-results').classList.remove('hidden');

  // Stat pills
  const retEl = document.getElementById('bt-stat-return');
  retEl.textContent = fmt.pct(data.total_return_pct);
  retEl.style.color = (data.total_return_pct >= 0) ? 'var(--green)' : 'var(--red)';

  document.getElementById('bt-stat-drawdown').textContent = fmt.pct(data.max_drawdown_pct);
  document.getElementById('bt-stat-winrate').textContent  = fmt.pct(data.win_rate_pct);
  document.getElementById('bt-stat-sharpe').textContent   =
    data.sharpe_ratio != null ? Number(data.sharpe_ratio).toFixed(2) : '—';
  document.getElementById('bt-stat-trades').textContent   = data.total_trades ?? '—';

  // Equity curve chart
  if (_btEquityChart) { _btEquityChart.destroy(); _btEquityChart = null; }
  const chartDates  = (data.equity_curve || []).map(p => p.date);
  const chartValues = (data.equity_curve || []).map(p => p.equity);

  _btEquityChart = new ApexCharts(document.getElementById('bt-chart'), {
    chart:  { type: 'area', height: 280, background: 'transparent',
              toolbar: { show: false }, animations: { enabled: false },
              sparkline: { enabled: false } },
    series: [{ name: 'Equity', data: chartValues }],
    xaxis:  { categories: chartDates,
              labels: { style: { colors: '#64748B', fontSize: '11px' },
                        rotate: -30, hideOverlappingLabels: true },
              axisBorder: { show: false }, axisTicks: { show: false } },
    yaxis:  { labels: { style: { colors: '#64748B', fontSize: '11px' },
                        formatter: v => '$' + Math.round(v).toLocaleString() } },
    fill:   { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.3, opacityTo: 0.02 } },
    stroke: { width: 2, curve: 'smooth' },
    colors: ['#3B82F6'],
    grid:   { borderColor: 'rgba(30,45,69,.6)', strokeDashArray: 3 },
    tooltip: { theme: 'dark', y: { formatter: v => '$' + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) } },
    theme:  { mode: 'dark' },
    dataLabels: { enabled: false },
  });
  _btEquityChart.render();

  // Reset name input
  document.getElementById('bt-run-name').value = data.name || '';

  // Trades table
  const tbody = document.getElementById('bt-trades-body');
  const trades = data.trades || [];
  if (trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="state-empty">No closed trades.</td></tr>';
  } else {
    tbody.innerHTML = trades.map(t => {
      const pnlColor = t.pnl >= 0 ? 'var(--green)' : 'var(--red)';
      const pnlSign  = t.pnl >= 0 ? '+' : '';
      return `<tr>
        <td>${t.date}</td>
        <td>${t.symbol}</td>
        <td><span class="badge b-${t.side === 'buy' ? 'buy' : 'sell'}">${t.side.toUpperCase()}</span></td>
        <td>${t.qty}</td>
        <td>${fmt.usd(t.price)}</td>
        <td style="color:${pnlColor};">${pnlSign}${fmt.usd(Math.abs(t.pnl))}</td>
      </tr>`;
    }).join('');
  }
}

function renderHistory(runs) {
  const el = document.getElementById('bt-history-list');
  if (!runs || runs.length === 0) {
    el.innerHTML = '<div class="state-empty">No saved runs yet.</div>';
    return;
  }
  el.innerHTML = runs.map(r => {
    const syms  = Array.isArray(r.symbols) ? r.symbols.join(', ') : r.symbols;
    const label = r.name || fmt.time(r.created_at);
    const retColor = r.total_return_pct >= 0 ? 'var(--green)' : 'var(--red)';
    return `<div style="display:flex;align-items:center;gap:10px;padding:.55rem 0;border-bottom:1px solid rgba(30,45,69,.7);">
      <div style="flex:1;min-width:0;">
        <div style="font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${label}</div>
        <div class="text-muted" style="font-size:11px;">${r.strategy} &middot; ${syms}</div>
      </div>
      <div style="font-size:13px;color:${retColor};min-width:52px;text-align:right;">${fmt.pct(r.total_return_pct)}</div>
      <div style="font-size:12px;color:#EF4444;min-width:52px;text-align:right;">${fmt.pct(r.max_drawdown_pct)}</div>
      <div style="font-size:12px;color:var(--muted);min-width:42px;text-align:right;">${fmt.pct(r.win_rate_pct)}</div>
      <button class="btn btn-sm btn-ghost" onclick="loadRun(${r.id})">Load</button>
      <button class="btn btn-sm btn-ghost" style="color:#EF4444;" onclick="deleteRun(${r.id})">Delete</button>
    </div>`;
  }).join('');
}

async function loadRun(id) {
  try {
    const data = await api(`/api/backtest/runs/${id}`);
    renderResults(data);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (e) {
    console.error('loadRun error', e);
  }
}

async function deleteRun(id) {
  try {
    const res = await fetch(`/api/backtest/runs/${id}`, { method: 'DELETE' });
    if (!res.ok) return;
    if (_btCurrentRunId === id) {
      document.getElementById('bt-results').classList.add('hidden');
      _btCurrentRunId = null;
    }
    renderHistory(await api('/api/backtest/runs'));
  } catch (e) {
    console.error('deleteRun error', e);
  }
}

async function renameRun() {
  if (!_btCurrentRunId) return;
  const name = document.getElementById('bt-run-name').value.trim();
  if (!name) return;
  try {
    await api(`/api/backtest/runs/${_btCurrentRunId}`, {
      method:  'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ name }),
    });
    renderHistory(await api('/api/backtest/runs'));
  } catch (e) {
    console.error('renameRun error', e);
  }
}
```

Also add the spinner keyframe to `styles.css` (append at end if not already present):

Check whether `@keyframes spin` exists in `styles.css`:

```
grep -n "keyframes spin" server/static/styles.css
```

If not found, append to `server/static/styles.css`:

```css
@keyframes spin { to { transform: rotate(360deg); } }
```

- [ ] **Step 3: Commit**

```bash
git add server/static/app.js server/static/styles.css
git commit -m "feat: add initBacktesting and 6 helper functions to app.js"
```

---

## Final Verification

After all 6 tasks are committed:

- [ ] Start the server: `python -m uvicorn server.main:app --reload`
- [ ] Open `http://localhost:8000/static/backtesting.html`
- [ ] Verify strategy dropdown populates from `/api/strategies`
- [ ] Run a backtest (AAPL, any 1-year range, any strategy)
- [ ] Verify equity curve renders, stat pills show values, trades table renders
- [ ] Verify "Save Name" renames the run and updates the history list
- [ ] Verify "Load" in history restores results
- [ ] Verify "Delete" removes the run from history
- [ ] Run full test suite one final time: `pytest --tb=short -q`
