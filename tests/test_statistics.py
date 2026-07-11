"""Task 9 — Statistics + statistical gate (spec §11, §12, §19.10, §19.13).

Deterministic, NO-NETWORK, Decimal-based tests for:
  - moving-block bootstrap 95% intervals for daily net return + expectancy
    (20-session stock blocks, 14-day crypto blocks)
  - the statistical gate: lower bound > 0 -> PASS; wholly negative -> FAIL;
    spanning zero -> INCONCLUSIVE (NOT a pass)
  - profit concentration (divide by total positive P&L before losses) and loss
    concentration reported separately
  - the 12 hard §12 acceptance criteria, each as a distinct checkable predicate.

The bootstrap is seeded, so intervals are reproducible.
"""
from decimal import Decimal

import pytest

from server import statistics as st

D = Decimal


# ── default constants must equal the real spec values ────────────────────────────

def test_default_block_sizes_match_spec():
    # §19.10: 20-session stock blocks, 14-day crypto blocks.
    assert st.STOCK_BLOCK == 20
    assert st.CRYPTO_BLOCK == 14
    assert st.DEFAULT_CONFIDENCE == D("0.95")


# ── moving-block bootstrap ───────────────────────────────────────────────────────

class TestBootstrap:
    def test_ci_ordering_and_reproducibility(self):
        series = [D("0.01"), D("0.02"), D("-0.005"), D("0.015"), D("0.008"),
                  D("0.012"), D("-0.002"), D("0.02"), D("0.01"), D("0.005")]
        lo1, pt1, hi1 = st.moving_block_bootstrap_ci(
            series, block_size=3, n_resamples=500, seed=42)
        lo2, pt2, hi2 = st.moving_block_bootstrap_ci(
            series, block_size=3, n_resamples=500, seed=42)
        # reproducible with the same seed
        assert (lo1, pt1, hi1) == (lo2, pt2, hi2)
        # ordering
        assert lo1 <= pt1 <= hi1
        # returns Decimals
        assert isinstance(lo1, Decimal) and isinstance(hi1, Decimal)

    def test_all_positive_series_has_positive_lower_bound(self):
        series = [D("0.01")] * 40
        lo, pt, hi = st.moving_block_bootstrap_ci(
            series, block_size=20, n_resamples=300, seed=7)
        # a constant positive series must bootstrap to a positive lower bound
        assert lo > 0

    def test_all_negative_series_has_negative_upper_bound(self):
        series = [D("-0.01")] * 40
        lo, pt, hi = st.moving_block_bootstrap_ci(
            series, block_size=20, n_resamples=300, seed=7)
        assert hi < 0

    def test_empty_series_raises(self):
        with pytest.raises(ValueError):
            st.moving_block_bootstrap_ci([], block_size=3, n_resamples=10, seed=1)


# ── statistical gate (§19.13 "Statistical gate") ─────────────────────────────────

class TestGate:
    def test_lower_bound_positive_passes(self):
        assert st.classify_ci(D("0.001"), D("0.02")) is st.GateVerdict.PASS

    def test_wholly_negative_fails(self):
        assert st.classify_ci(D("-0.02"), D("-0.001")) is st.GateVerdict.FAIL

    def test_spanning_zero_is_inconclusive_not_pass(self):
        v = st.classify_ci(D("-0.01"), D("0.02"))
        assert v is st.GateVerdict.INCONCLUSIVE
        assert v is not st.GateVerdict.PASS

    def test_zero_lower_bound_is_not_a_pass(self):
        # lower bound must be strictly > 0
        assert st.classify_ci(D("0"), D("0.02")) is not st.GateVerdict.PASS

    def test_gate_from_series_uses_bootstrap_lower_bound(self):
        pos = [D("0.01")] * 40
        neg = [D("-0.01")] * 40
        assert st.gate_series(pos, block_size=20, n_resamples=200, seed=3) \
            is st.GateVerdict.PASS
        assert st.gate_series(neg, block_size=20, n_resamples=200, seed=3) \
            is st.GateVerdict.FAIL


# ── profit / loss concentration (§19.10) ─────────────────────────────────────────

class TestConcentration:
    def _trades(self):
        # symbol/year keyed closed trades with pnl
        return [
            {"symbol": "AAA", "year": 2020, "pnl": D("100")},
            {"symbol": "AAA", "year": 2021, "pnl": D("50")},
            {"symbol": "BBB", "year": 2020, "pnl": D("-30")},
            {"symbol": "CCC", "year": 2022, "pnl": D("50")},
        ]

    def test_profit_concentration_divides_by_positive_pnl_only(self):
        # total POSITIVE pnl = 100 + 50 + 50 = 200 (losses excluded from denom)
        conc = st.profit_concentration(self._trades(), key="symbol")
        # AAA positive contribution = 150 -> 150/200 = 0.75
        assert conc["AAA"] == D("0.75")
        # BBB has no positive contribution
        assert conc.get("BBB", D("0")) == D("0")

    def test_max_profit_concentration(self):
        assert st.max_profit_concentration(self._trades(), key="symbol") == D("0.75")

    def test_loss_concentration_reported_separately(self):
        loss = st.loss_concentration(self._trades(), key="symbol")
        # total losses (abs) = 30 -> BBB is the only loser -> 100%
        assert loss["BBB"] == D("1")
        # winners contribute nothing to loss concentration
        assert loss.get("AAA", D("0")) == D("0")

    def test_no_positive_pnl_returns_empty(self):
        trades = [{"symbol": "X", "year": 2020, "pnl": D("-5")}]
        assert st.profit_concentration(trades, key="symbol") == {}


# ── the 12 hard §12 acceptance criteria as predicates ────────────────────────────

class TestAcceptanceCriteria:
    """Each §12 criterion is a distinct checkable predicate returning bool.

    The tests here pin the predicate semantics; the research harness composes them.
    """

    def test_c1_positive_net_oos_return_baseline(self):
        assert st.c1_positive_oos_return_baseline(D("0.05")) is True
        assert st.c1_positive_oos_return_baseline(D("0")) is False
        assert st.c1_positive_oos_return_baseline(D("-0.01")) is False

    def test_c2_positive_net_oos_return_stressed(self):
        assert st.c2_positive_oos_return_stressed(D("0.01")) is True
        assert st.c2_positive_oos_return_stressed(D("-0.001")) is False

    def test_c3_aggregate_drawdown_at_or_below_cap(self):
        # drawdown stored as a non-positive fraction; equity-appropriate 20% cap
        assert st.c3_aggregate_drawdown_ok(D("-0.20")) is True    # exactly 20%
        assert st.c3_aggregate_drawdown_ok(D("-0.07")) is True    # normal equity DD
        assert st.c3_aggregate_drawdown_ok(D("-0.2001")) is False

    def test_c4_holdout_drawdown_at_or_below_cap(self):
        assert st.c4_holdout_drawdown_ok(D("-0.20")) is True
        assert st.c4_holdout_drawdown_ok(D("-0.25")) is False

    def test_c5_positive_in_at_least_60pct_of_folds(self):
        assert st.c5_fold_win_rate_ok([D("1"), D("1"), D("-1"), D("1"), D("1")]) is True  # 4/5=80%
        assert st.c5_fold_win_rate_ok([D("1"), D("-1"), D("-1")]) is False  # 1/3=33%
        assert st.c5_fold_win_rate_ok([D("1"), D("-1")]) is False  # 1/2=50% < 60%

    def test_c6_at_least_100_closed_stock_trades(self):
        assert st.c6_stock_trade_count_ok(100) is True
        assert st.c6_stock_trade_count_ok(99) is False

    def test_c7_crypto_round_trips_fewer_than_20_is_inconclusive(self):
        assert st.c7_crypto_round_trips(20) is st.GateVerdict.PASS
        assert st.c7_crypto_round_trips(19) is st.GateVerdict.INCONCLUSIVE
        # never silently a pass
        assert st.c7_crypto_round_trips(0) is not st.GateVerdict.PASS

    def test_c8_no_single_symbol_or_year_over_35pct_of_profit(self):
        ok_trades = [
            {"symbol": "A", "year": 2020, "pnl": D("30")},
            {"symbol": "B", "year": 2021, "pnl": D("30")},
            {"symbol": "C", "year": 2022, "pnl": D("40")},
        ]
        # max symbol share = 40/100 = 40% > 35% -> fails
        assert st.c8_concentration_ok(ok_trades) is False
        spread = [
            {"symbol": "A", "year": 2020, "pnl": D("30")},
            {"symbol": "B", "year": 2021, "pnl": D("30")},
            {"symbol": "C", "year": 2022, "pnl": D("30")},
            {"symbol": "D", "year": 2023, "pnl": D("10")},
        ]
        # max symbol share 30/100 = 30% <= 35%; max year share also <= 35%
        assert st.c8_concentration_ok(spread) is True

    def test_c9_neighboring_params_retain_70pct_of_calmar(self):
        # selected calmar positive; neighbors retain >= 70%
        assert st.c9_neighbor_robustness_ok(
            selected_calmar=D("1.0"),
            neighbor_calmars=[D("0.8"), D("0.75"), D("0.9")]) is True
        # a neighbor drops below 70%
        assert st.c9_neighbor_robustness_ok(
            selected_calmar=D("1.0"),
            neighbor_calmars=[D("0.8"), D("0.5")]) is False
        # non-positive selected calmar => fails outright
        assert st.c9_neighbor_robustness_ok(
            selected_calmar=D("-0.1"),
            neighbor_calmars=[D("1"), D("1")]) is False
        assert st.c9_neighbor_robustness_ok(
            selected_calmar=D("0"),
            neighbor_calmars=[D("1")]) is False

    def test_c10_positive_net_expectancy(self):
        assert st.c10_positive_expectancy(D("0.01")) is True
        assert st.c10_positive_expectancy(D("0")) is False
        assert st.c10_positive_expectancy(D("-0.5")) is False

    def test_c11_no_integrity_failures(self):
        assert st.c11_integrity_ok(
            leakage=False, negative_cash=False, ownership_violation=False,
            reconciliation_failure=False, data_integrity_failure=False) is True
        assert st.c11_integrity_ok(
            leakage=True, negative_cash=False, ownership_violation=False,
            reconciliation_failure=False, data_integrity_failure=False) is False

    def test_c12_every_attempt_visible(self):
        # criterion 12: all attempted configs + failed criteria remain visible.
        report = {"attempts": [{"params": {}, "metrics": {}}],
                  "failed_criteria": ["c5"]}
        assert st.c12_visibility_ok(report) is True
        assert st.c12_visibility_ok({"attempts": []}) is False


# ── evaluate_all_criteria bundles the 12 predicates ──────────────────────────────

class TestEvaluateAll:
    def test_all_twelve_criteria_present(self):
        keys = st.criteria_keys()
        assert keys == [f"c{i}" for i in range(1, 13)]

    def test_evaluate_all_returns_per_criterion_and_overall(self):
        inputs = dict(
            oos_return_baseline=D("0.05"),
            oos_return_stressed=D("0.02"),
            aggregate_drawdown=D("-0.03"),
            holdout_drawdown=D("-0.02"),
            fold_pnls=[D("1"), D("1"), D("-1"), D("1"), D("1")],
            stock_trade_count=120,
            crypto_round_trips=25,
            profit_trades=[
                {"symbol": "A", "year": 2020, "pnl": D("30")},
                {"symbol": "B", "year": 2021, "pnl": D("30")},
                {"symbol": "C", "year": 2022, "pnl": D("30")},
                {"symbol": "D", "year": 2023, "pnl": D("10")},
            ],
            selected_calmar=D("1.0"),
            neighbor_calmars=[D("0.8"), D("0.75")],
            expectancy=D("5"),
            integrity=dict(leakage=False, negative_cash=False,
                           ownership_violation=False, reconciliation_failure=False,
                           data_integrity_failure=False),
            report={"attempts": [{"params": {}}], "failed_criteria": []},
        )
        res = st.evaluate_all_criteria(**inputs)
        assert res["overall"] is True
        assert all(res["criteria"][k]["pass"] for k in st.criteria_keys())

    def test_evaluate_all_fails_when_one_criterion_fails(self):
        inputs = dict(
            oos_return_baseline=D("-0.01"),  # C1 fails
            oos_return_stressed=D("0.02"),
            aggregate_drawdown=D("-0.03"),
            holdout_drawdown=D("-0.02"),
            fold_pnls=[D("1"), D("1"), D("1")],
            stock_trade_count=120,
            crypto_round_trips=25,
            profit_trades=[{"symbol": "A", "year": 2020, "pnl": D("100")}],
            selected_calmar=D("1.0"),
            neighbor_calmars=[D("0.9")],
            expectancy=D("5"),
            integrity=dict(leakage=False, negative_cash=False,
                           ownership_violation=False, reconciliation_failure=False,
                           data_integrity_failure=False),
            report={"attempts": [{"params": {}}], "failed_criteria": ["c1"]},
        )
        res = st.evaluate_all_criteria(**inputs)
        assert res["overall"] is False
        assert res["criteria"]["c1"]["pass"] is False
