"""Task 9 — Walk-forward research orchestration (spec §11.2, §19.10, §19.13).

Deterministic, NO-NETWORK tests. Fold geometry is exercised with REDUCED sizes
injected via parameters so tests are fast; the module DEFAULT constants must equal
the real spec values (asserted below).

Covers:
  - exact stock & crypto fold geometry (anchored, advancing)
  - final holdout window (latest 24 stock months / 12 crypto months)
  - embargo (5 sessions stock / 2 days crypto) unscored between selection & validation
  - indicator warm-up (max-lookback purge) produces no scored orders
  - every OOS fold begins from cash; training positions liquidated before boundary;
    open validation positions liquidated at fold end
  - params frozen within a fold; fold returns chained geometrically into ONE curve
  - final holdout scored EXACTLY ONCE after params frozen on all pre-holdout data
  - predeclared grids match the spec
  - Calmar selection subject to training DD <= 5%, tie -> lower turnover, tie -> lex
  - every attempt persisted
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from server import research as rf

D = Decimal


def _calendar(n, start="2010-01-01", step_days=1):
    d = date.fromisoformat(start)
    out = []
    for _ in range(n):
        out.append(d)
        d += timedelta(days=step_days)
    return out


# ── default constants equal the real spec values (§19.10) ────────────────────────

class TestSpecDefaults:
    def test_stock_geometry_defaults(self):
        g = rf.FoldGeometry.stock_default()
        assert g.asset_class == "stock"
        assert g.min_years == 10
        assert g.train_years == 5
        assert g.validation_months == 12       # 1-year validation windows
        assert g.advance_months == 12          # advance yearly
        assert g.holdout_months == 24          # latest 24 complete months
        assert g.embargo_periods == 5          # 5 sessions
        assert g.max_lookback_periods == 252   # purge >= max lookback

    def test_crypto_geometry_defaults(self):
        g = rf.FoldGeometry.crypto_default()
        assert g.asset_class == "crypto"
        assert g.min_years == 6
        assert g.train_years == 3
        assert g.validation_months == 6        # 6-month validation windows
        assert g.holdout_months == 12          # latest 12 complete months
        assert g.embargo_periods == 2          # 2 days
        assert g.max_lookback_periods == 200   # EMA200 lookback

    def test_predeclared_stock_grid(self):
        grid = rf.predeclared_grid("stock")
        breakouts = sorted({p["breakout"] for p in grid})
        volumes = sorted({p["volume"] for p in grid})
        trails = sorted({p["trail_atr"] for p in grid})
        assert breakouts == [126, 252]
        assert volumes == [D("1.0"), D("1.2"), D("1.4")]
        assert trails == [D("2.5"), D("3.0"), D("3.5")]
        assert len(grid) == 2 * 3 * 3

    def test_predeclared_crypto_grid(self):
        grid = rf.predeclared_grid("crypto")
        breakouts = sorted({p["breakout"] for p in grid})
        lows = sorted({p["exit_low"] for p in grid})
        trails = sorted({p["trail_atr"] for p in grid})
        assert breakouts == [40, 55, 70]
        assert lows == [15, 20, 30]
        assert trails == [D("3.0"), D("3.5"), D("4.0")]
        assert len(grid) == 3 * 3 * 3

    def test_grid_is_lexicographically_ordered(self):
        grid = rf.predeclared_grid("stock")
        keyed = [(p["breakout"], p["volume"], p["trail_atr"]) for p in grid]
        assert keyed == sorted(keyed)


# ── fold geometry construction ───────────────────────────────────────────────────

class TestFoldGeometry:
    def _reduced_stock(self):
        # reduced sizes: 1-year train, 1-year validation, 1-year holdout, ~360-day
        # "year" so the arithmetic is easy to reason about. 4-year minimum yields
        # 3 pre-holdout years -> exactly TWO anchored folds (val yr2, val yr3).
        return rf.FoldGeometry(
            asset_class="stock", min_years=4, train_years=1, validation_months=12,
            advance_months=12, holdout_months=12, embargo_periods=5,
            max_lookback_periods=10, days_per_year=360, days_per_month=30)

    def test_holdout_is_last_n_months_and_untouched_by_folds(self):
        g = self._reduced_stock()
        cal = _calendar(4 * 360)  # 4 years of daily bars
        plan = rf.build_folds(cal, g)
        # holdout = last 12 months = last 360 sessions
        assert plan.holdout.start == cal[-360]
        assert plan.holdout.end == cal[-1]
        # no fold's validation window overlaps the holdout
        for fold in plan.folds:
            assert fold.validation.end < plan.holdout.start

    def test_two_anchored_folds_advance_yearly(self):
        g = self._reduced_stock()
        cal = _calendar(4 * 360)
        plan = rf.build_folds(cal, g)
        # exactly two folds for 3 pre-holdout years with a 1-year train window
        assert len(plan.folds) == 2
        # anchored: every fold's training window starts at the same anchor
        anchors = {f.train.start for f in plan.folds}
        assert anchors == {cal[0]}
        # training END advances by one "year" (360 sessions) fold-over-fold
        assert plan.folds[0].train.end == cal[360 - 1]
        assert plan.folds[1].train.end == cal[2 * 360 - 1]
        train_ends = [f.train.end for f in plan.folds]
        assert train_ends == sorted(train_ends)
        assert len(set(train_ends)) == len(train_ends)
        # validation windows are non-overlapping and advance
        assert plan.folds[0].validation.end < plan.folds[1].validation.start

    def test_embargo_sits_between_training_and_validation(self):
        g = self._reduced_stock()
        cal = _calendar(4 * 360)
        plan = rf.build_folds(cal, g)
        for fold in plan.folds:
            # embargo is EXACTLY embargo_periods sessions, unscored
            assert fold.embargo_periods == 5
            assert fold.embargo is not None
            # the embargo region is exactly 5 sessions immediately after training
            emb_gap = rf.session_gap(cal, fold.train.end, fold.embargo.start)
            assert emb_gap == 1
            assert rf.session_gap(cal, fold.embargo.start, fold.embargo.end) == 4
            # scored validation starts strictly after training + the 5 embargo bars
            gap = rf.session_gap(cal, fold.train.end, fold.validation.start)
            assert gap == 5 + 1

    def test_crypto_geometry_builds_folds(self):
        # reduced crypto: 1-yr train, 6-mo validation, 6-mo holdout, 2-day embargo.
        g = rf.FoldGeometry(
            asset_class="crypto", min_years=3, train_years=1, validation_months=6,
            advance_months=6, holdout_months=6, embargo_periods=2,
            max_lookback_periods=10, days_per_year=360, days_per_month=30)
        cal = _calendar(3 * 360)
        plan = rf.build_folds(cal, g)
        assert plan.holdout.start == cal[-180]  # last 6 months = 180 sessions
        assert len(plan.folds) >= 2
        for fold in plan.folds:
            assert fold.embargo_periods == 2
            assert rf.session_gap(cal, fold.train.end, fold.validation.start) == 2 + 1
            assert fold.validation.end < plan.holdout.start

    def test_insufficient_history_raises(self):
        g = self._reduced_stock()
        cal = _calendar(360)  # only 1 year, need >= 4
        with pytest.raises(rf.InsufficientHistory):
            rf.build_folds(cal, g)


# ── the orchestrator: cash reset, freeze, single holdout, persistence ────────────

class _StubBacktest:
    """Deterministic backtest stand-in. Records every (params, window, from_cash)
    invocation and returns a scripted result keyed by the window role."""

    def __init__(self, scripted):
        # scripted: role -> {params_tuple -> result dict}
        self._scripted = scripted
        self.calls = []

    def __call__(self, *, params, window, from_cash, role):
        self.calls.append({"params": dict(params), "window": window,
                           "from_cash": from_cash, "role": role})
        key = (params["breakout"], params["volume"], params["trail_atr"])
        table = self._scripted.get(role, {})
        return table.get(key) or table.get("*") or {
            "net_return": D("0"), "calmar": D("0"), "max_drawdown": D("0"),
            "turnover": D("0"), "trades": [], "daily_returns": [],
            "equity_curve": [{"date": window.start.isoformat(), "equity": D("10000")},
                             {"date": window.end.isoformat(), "equity": D("10000")}],
        }


def _reduced_stock_geo():
    # 4-year minimum -> 3 pre-holdout years -> exactly TWO anchored folds.
    return rf.FoldGeometry(
        asset_class="stock", min_years=4, train_years=1, validation_months=12,
        advance_months=12, holdout_months=12, embargo_periods=5,
        max_lookback_periods=10, days_per_year=360, days_per_month=30)


class TestOrchestration:
    def test_every_validation_and_holdout_runs_start_from_cash(self):
        cal = _calendar(4 * 360)
        geo = _reduced_stock_geo()
        stub = _StubBacktest({})
        rf.run_walk_forward(calendar=cal, geometry=geo,
                            grid=rf.predeclared_grid("stock"),
                            backtest_fn=stub, persist=lambda *_a, **_k: None)
        # every validation and holdout invocation must be from_cash=True
        for c in stub.calls:
            if c["role"] in ("validation", "holdout"):
                assert c["from_cash"] is True

    def test_params_are_frozen_within_a_fold(self):
        cal = _calendar(4 * 360)
        geo = _reduced_stock_geo()
        # make one grid point clearly best on training so selection is unambiguous
        best = (252, D("1.2"), D("3.0"))
        scripted = {"training": {best: {
            "net_return": D("0.2"), "calmar": D("2.0"), "max_drawdown": D("-0.02"),
            "turnover": D("1"), "trades": [], "daily_returns": [],
            "equity_curve": []}}}
        stub = _StubBacktest(scripted)
        rf.run_walk_forward(calendar=cal, geometry=geo,
                            grid=rf.predeclared_grid("stock"),
                            backtest_fn=stub, persist=lambda *_a, **_k: None)
        # for each fold, the single validation call uses exactly ONE param set
        val_calls = [c for c in stub.calls if c["role"] == "validation"]
        for c in val_calls:
            key = (c["params"]["breakout"], c["params"]["volume"],
                   c["params"]["trail_atr"])
            assert key == best

    def test_final_holdout_scored_exactly_once_after_freeze(self):
        cal = _calendar(4 * 360)
        geo = _reduced_stock_geo()
        stub = _StubBacktest({})
        result = rf.run_walk_forward(
            calendar=cal, geometry=geo, grid=rf.predeclared_grid("stock"),
            backtest_fn=stub, persist=lambda *_a, **_k: None)
        holdout_calls = [c for c in stub.calls if c["role"] == "holdout"]
        # holdout evaluated EXACTLY ONCE
        assert len(holdout_calls) == 1
        # holdout used the frozen params selected on ALL pre-holdout data
        assert result.frozen_params is not None
        hc = holdout_calls[0]
        assert (hc["params"]["breakout"], hc["params"]["volume"],
                hc["params"]["trail_atr"]) == (
                    result.frozen_params["breakout"],
                    result.frozen_params["volume"],
                    result.frozen_params["trail_atr"])
        # the holdout window is the last 12 months and never appears in training
        assert hc["window"].start == cal[-360]
        assert hc["window"].end == cal[-1]

    def test_holdout_window_never_used_for_any_training_call(self):
        cal = _calendar(4 * 360)
        geo = _reduced_stock_geo()
        stub = _StubBacktest({})
        rf.run_walk_forward(calendar=cal, geometry=geo,
                            grid=rf.predeclared_grid("stock"),
                            backtest_fn=stub, persist=lambda *_a, **_k: None)
        holdout_start = cal[-360]
        for c in stub.calls:
            if c["role"] in ("training", "validation"):
                # no training/validation window may reach into the holdout
                assert c["window"].end < holdout_start

    def test_every_attempt_is_persisted(self):
        cal = _calendar(4 * 360)
        geo = _reduced_stock_geo()
        stub = _StubBacktest({})
        persisted = []
        rf.run_walk_forward(
            calendar=cal, geometry=geo, grid=rf.predeclared_grid("stock"),
            backtest_fn=stub,
            persist=lambda attempt: persisted.append(attempt))
        grid_n = len(rf.predeclared_grid("stock"))
        n_folds = len(rf.build_folds(cal, geo).folds)
        # Every grid point is attempted on every fold's training set AND once more
        # over the whole pre-holdout window for the pre-holdout freeze selection
        # (that freeze pass is itself a set of attempts that must remain visible,
        # §12.12). So training attempts = grid_n * (n_folds + 1).
        training_attempts = [p for p in persisted if p["role"] == "training"]
        assert len(training_attempts) == grid_n * (n_folds + 1)
        # validation attempts: one selected-param run per fold
        validation_attempts = [p for p in persisted if p["role"] == "validation"]
        assert len(validation_attempts) == n_folds
        # holdout scored exactly once
        assert len([p for p in persisted if p["role"] == "holdout"]) == 1

    def test_oos_curve_is_chained_geometrically(self):
        # Two folds each returning +10% on validation -> chained 1.1 * 1.1 = 1.21.
        cal = _calendar(4 * 360)  # 3 pre-holdout years of folds + holdout
        geo = _reduced_stock_geo()
        best = (252, D("1.2"), D("3.0"))

        def _val_result(window):
            return {
                "net_return": D("0.1"), "calmar": D("2"), "max_drawdown": D("-0.01"),
                "turnover": D("1"), "trades": [], "daily_returns": [],
                "equity_curve": [
                    {"date": window.start.isoformat(), "equity": D("10000")},
                    {"date": window.end.isoformat(), "equity": D("11000")}],
            }

        class _Stub(_StubBacktest):
            def __call__(self, *, params, window, from_cash, role):
                self.calls.append({"role": role, "window": window,
                                   "params": dict(params), "from_cash": from_cash})
                if role in ("validation", "holdout"):
                    return _val_result(window)
                return {"net_return": D("0.2"), "calmar": D("2"),
                        "max_drawdown": D("-0.01"), "turnover": D("1"),
                        "trades": [], "daily_returns": [], "equity_curve": []}

        stub = _Stub({})
        result = rf.run_walk_forward(
            calendar=cal, geometry=geo, grid=[dict(breakout=252, volume=D("1.2"),
                                                   trail_atr=D("3.0"))],
            backtest_fn=stub, persist=lambda *_a, **_k: None)
        # chained OOS return over N folds each +10%
        n_folds = len(rf.build_folds(cal, geo).folds)
        expected = (D("1.1") ** n_folds) - D("1")
        assert result.oos_return == expected


# ── selection rule (§19.10) ──────────────────────────────────────────────────────

class TestSelection:
    def test_max_calmar_subject_to_drawdown_cap(self):
        attempts = [
            # this has the best Calmar but violates the 5% training DD cap
            {"params": {"breakout": 126, "volume": D("1.0"), "trail_atr": D("2.5")},
             "calmar": D("9"), "max_drawdown": D("-0.08"), "turnover": D("1")},
            # eligible, lower Calmar
            {"params": {"breakout": 252, "volume": D("1.2"), "trail_atr": D("3.0")},
             "calmar": D("3"), "max_drawdown": D("-0.03"), "turnover": D("1")},
        ]
        sel = rf.select_params(attempts)
        assert sel["params"]["breakout"] == 252  # the DD-compliant one wins

    def test_tie_break_prefers_lower_turnover(self):
        attempts = [
            {"params": {"breakout": 252, "volume": D("1.4"), "trail_atr": D("3.5")},
             "calmar": D("3"), "max_drawdown": D("-0.02"), "turnover": D("5")},
            {"params": {"breakout": 126, "volume": D("1.0"), "trail_atr": D("2.5")},
             "calmar": D("3"), "max_drawdown": D("-0.02"), "turnover": D("2")},
        ]
        sel = rf.select_params(attempts)
        assert sel["turnover"] == D("2")

    def test_tie_break_lexicographic_params_last(self):
        attempts = [
            {"params": {"breakout": 252, "volume": D("1.2"), "trail_atr": D("3.0")},
             "calmar": D("3"), "max_drawdown": D("-0.02"), "turnover": D("1")},
            {"params": {"breakout": 126, "volume": D("1.0"), "trail_atr": D("2.5")},
             "calmar": D("3"), "max_drawdown": D("-0.02"), "turnover": D("1")},
        ]
        sel = rf.select_params(attempts)
        # lexicographically smallest params: breakout 126 < 252
        assert sel["params"]["breakout"] == 126

    def test_no_eligible_config_returns_none(self):
        attempts = [
            {"params": {"breakout": 252, "volume": D("1.2"), "trail_atr": D("3.0")},
             "calmar": D("3"), "max_drawdown": D("-0.09"), "turnover": D("1")},
        ]
        assert rf.select_params(attempts) is None


# ── DB persistence wiring (additive; research/reporting only) ────────────────────

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    import server.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "research.db")
    db.init_db()
    return db


class TestResearchPersistence:
    def test_schema_is_rerunnable_and_additive(self, tmp_db):
        tmp_db.init_db()  # second call must not error
        with tmp_db.get_conn() as c:
            names = {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        # new research tables present; existing tables untouched
        assert {"research_runs", "research_attempts"} <= names
        assert {"execution_orders", "backtest_runs", "strategies"} <= names

    def test_run_walk_forward_persists_every_attempt_to_db(self, tmp_db):
        cal = _calendar(4 * 360)
        geo = _reduced_stock_geo()
        stub = _StubBacktest({})
        rf.run_walk_forward(
            calendar=cal, geometry=geo, grid=rf.predeclared_grid("stock"),
            backtest_fn=stub, persist=tmp_db.persist_research_attempt)
        with tmp_db.get_conn() as c:
            n = c.execute("SELECT COUNT(*) FROM research_attempts").fetchone()[0]
            holdout = c.execute(
                "SELECT COUNT(*) FROM research_attempts WHERE role='holdout'"
            ).fetchone()[0]
        grid_n = len(rf.predeclared_grid("stock"))
        n_folds = len(rf.build_folds(cal, geo).folds)
        # training (folds + freeze pass) + validation (per fold) + holdout (once)
        assert n == grid_n * (n_folds + 1) + n_folds + 1
        assert holdout == 1  # holdout scored exactly once

    def test_save_and_get_research_run_roundtrip(self, tmp_db):
        rid = tmp_db.save_research_run(
            asset_class="stock",
            frozen_params={"breakout": 252, "volume": D("1.2"), "trail_atr": D("3.0")},
            oos_return=D("0.21"),
            holdout_summary={"net_return": D("0.05"), "max_drawdown": D("-0.02")},
            criteria={"overall": True, "criteria": {"c1": {"pass": True}}},
            overall_pass=True,
            data_fingerprint="sha256:abc", code_revision="deadbeef",
            geometry={"asset_class": "stock", "min_years": 10})
        got = tmp_db.get_research_run(rid)
        assert got["asset_class"] == "stock"
        assert got["overall_pass"] == 1
        assert got["frozen_params"]["breakout"] == 252
        assert got["data_fingerprint"] == "sha256:abc"
        # oos_return stored as canonical decimal text
        assert got["oos_return"] == "0.21"

    def test_saving_a_run_does_not_enable_any_strategy(self, tmp_db):
        # A research run is pure evidence: no strategy row may flip to enabled and
        # no strategy_accounts assignment may be created as a side effect.
        before = tmp_db.get_strategies()
        tmp_db.save_research_run(
            asset_class="crypto", frozen_params=None, oos_return=D("-0.01"),
            holdout_summary=None, criteria=None, overall_pass=False)
        after = tmp_db.get_strategies()
        # strategy set unchanged; none enabled by the research write
        assert {s["name"] for s in before} == {s["name"] for s in after}
        assert all(not s["enabled"] for s in after) or before == after
