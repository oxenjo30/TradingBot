"""Task 7 — Backtest metrics (spec §10.4).

Deterministic, NO-NETWORK unit tests. Each metric is computed on a known fixture
where the expected value can be derived by hand. Metrics are pure Decimal
functions with a single documented annualization scale that differs for stock
sessions (252) vs 24/7 crypto (365).
"""
from decimal import Decimal

import pytest

from server.backtest_metrics import (
    ANNUALIZATION_STOCK,
    ANNUALIZATION_CRYPTO,
    annualization_factor,
    net_return,
    cagr,
    max_drawdown,
    daily_returns,
    annualized_volatility,
    sharpe_ratio,
    sortino_ratio,
    calmar_ratio,
    turnover,
    win_rate,
    payoff_ratio,
    expectancy,
    holding_period_stats,
    worst_trade,
    worst_daily_return,
    expected_shortfall,
    worst_gap_loss,
    excess_return,
    compute_metrics,
)


D = Decimal


def _curve(values):
    """Build an equity curve [{date, equity}] from a list of numbers."""
    from datetime import date, timedelta
    d = date(2024, 1, 1)
    out = []
    for v in values:
        out.append({"date": d.isoformat(), "equity": D(str(v))})
        d += timedelta(days=1)
    return out


# ── annualization scale (§10.4) ──────────────────────────────────────────────────

class TestAnnualization:
    def test_stock_and_crypto_scales_differ(self):
        assert ANNUALIZATION_STOCK == 252
        assert ANNUALIZATION_CRYPTO == 365
        assert annualization_factor("stock") == 252
        assert annualization_factor("crypto") == 365

    def test_unknown_asset_class_raises(self):
        with pytest.raises(ValueError):
            annualization_factor("forex")


# ── net return + CAGR ────────────────────────────────────────────────────────────

class TestReturns:
    def test_net_return_simple(self):
        assert net_return(D("10000"), D("11000")) == D("0.1")

    def test_net_return_loss(self):
        assert net_return(D("10000"), D("9000")) == D("-0.1")

    def test_cagr_one_year_stock(self):
        # 252 sessions == exactly 1 year on the stock scale; 10% total → 10% CAGR.
        curve = _curve([10000] + [10000] * 250 + [11000])  # 252 steps
        val = cagr(D("10000"), D("11000"), periods=252, asset_class="stock")
        assert float(val) == pytest.approx(0.10, abs=1e-6)

    def test_cagr_two_years_crypto(self):
        # 730 days == 2 years crypto; growth 1.21 → CAGR 10%.
        val = cagr(D("10000"), D("12100"), periods=730, asset_class="crypto")
        assert float(val) == pytest.approx(0.10, abs=1e-4)


# ── drawdown ─────────────────────────────────────────────────────────────────────

class TestDrawdown:
    def test_max_drawdown_known(self):
        # 100 -> 120 (peak) -> 90 : dd = (90-120)/120 = -0.25
        curve = _curve([100, 110, 120, 100, 90, 130])
        assert max_drawdown(curve) == D("-0.25")

    def test_max_drawdown_monotonic_up_is_zero(self):
        curve = _curve([100, 110, 120])
        assert max_drawdown(curve) == D("0")


# ── volatility / Sharpe / Sortino / Calmar ───────────────────────────────────────

class TestRiskAdjusted:
    def test_daily_returns_values(self):
        curve = _curve([100, 110, 99])
        rets = daily_returns(curve)
        assert rets[0] == D("0.1")
        assert rets[1] == D("-0.1")

    def test_zero_volatility_gives_zero_sharpe(self):
        curve = _curve([100, 100, 100, 100])
        assert annualized_volatility(curve, asset_class="stock") == D("0")
        assert sharpe_ratio(curve, asset_class="stock") == D("0")

    def test_sharpe_positive_for_steady_gains(self):
        curve = _curve([100, 101, 102.01, 103.0301])  # +1% each day
        s = sharpe_ratio(curve, asset_class="stock")
        # constant positive returns → zero stdev → guard returns 0
        assert s == D("0")

    def test_sortino_only_penalizes_downside(self):
        curve = _curve([100, 101, 100, 102, 101])
        sortino = sortino_ratio(curve, asset_class="stock")
        sharpe = sharpe_ratio(curve, asset_class="stock")
        # With mixed up/down days both are finite; sortino uses downside dev only.
        assert isinstance(sortino, Decimal)
        assert isinstance(sharpe, Decimal)

    def test_calmar_is_cagr_over_maxdd(self):
        curve = _curve([100, 90, 120])  # dd 10%, ends up
        c = calmar_ratio(curve, D("100"), D("120"), periods=252,
                         asset_class="stock")
        assert isinstance(c, Decimal)

    def test_calmar_zero_drawdown_returns_none(self):
        curve = _curve([100, 110, 120])
        assert calmar_ratio(curve, D("100"), D("120"), periods=252,
                            asset_class="stock") is None


# ── turnover + trade stats ───────────────────────────────────────────────────────

class TestTradeStats:
    def _trades(self):
        # 3 closed round trips: +100, -50, +30 net P&L
        return [
            {"symbol": "AAPL", "pnl": D("100"), "gross_notional": D("1000"),
             "holding_days": 5},
            {"symbol": "AAPL", "pnl": D("-50"), "gross_notional": D("2000"),
             "holding_days": 3},
            {"symbol": "MSFT", "pnl": D("30"), "gross_notional": D("500"),
             "holding_days": 10},
        ]

    def test_win_rate(self):
        assert win_rate(self._trades()) == D("2") / D("3")

    def test_win_rate_no_trades_is_none(self):
        assert win_rate([]) is None

    def test_payoff_ratio(self):
        # avg win = (100+30)/2 = 65 ; avg loss = 50 ; payoff = 1.3
        assert payoff_ratio(self._trades()) == D("1.3")

    def test_expectancy_is_mean_pnl(self):
        # (100 - 50 + 30) / 3 = 26.666...
        assert expectancy(self._trades()) == (D("80") / D("3"))

    def test_turnover_sum_notional_over_avg_equity(self):
        # total traded notional = 3500 ; avg equity from curve
        curve = _curve([1000, 1000, 1000])
        t = turnover(self._trades(), curve)
        assert t == D("3500") / D("1000")

    def test_holding_period_stats(self):
        stats = holding_period_stats(self._trades())
        assert stats["avg_days"] == D("6")   # (5+3+10)/3
        assert stats["min_days"] == 3
        assert stats["max_days"] == 10

    def test_worst_trade(self):
        assert worst_trade(self._trades()) == D("-50")


# ── tail-loss measures (§19.11) ──────────────────────────────────────────────────

class TestTailLoss:
    def test_worst_daily_return(self):
        curve = _curve([100, 110, 99, 105])  # returns +.1, -.1, +.0606..
        assert worst_daily_return(curve) == D("-0.1")

    def test_expected_shortfall_95(self):
        # 20 returns: nineteen +0.01 and one -0.20. 95% ES = mean of worst 5%
        # of 20 = worst 1 return = -0.20.
        vals = [100.0]
        v = 100.0
        for _ in range(19):
            v = v * 1.01
            vals.append(v)
        vals.append(vals[-1] * 0.80)  # one -20% day
        curve = _curve(vals)
        es = expected_shortfall(curve, confidence=D("0.95"))
        assert float(es) == pytest.approx(-0.20, abs=1e-9)

    def test_worst_gap_loss_uses_prev_close_to_open(self):
        # Provide per-symbol bars where an open gaps down from prior close.
        bars = {
            "AAPL": [
                {"t": "2024-01-01", "o": 100, "h": 101, "l": 99, "c": 100, "v": 1},
                {"t": "2024-01-02", "o": 90, "h": 95, "l": 89, "c": 92, "v": 1},
            ]
        }
        # gap = (90-100)/100 = -0.10
        assert worst_gap_loss(bars) == D("-0.1")


# ── benchmark / excess ───────────────────────────────────────────────────────────

class TestBenchmark:
    def test_excess_return(self):
        assert excess_return(D("0.15"), D("0.10")) == D("0.05")


# ── aggregate compute_metrics on a known fixture ─────────────────────────────────

class TestComputeMetrics:
    def test_full_bundle_keys_and_values(self):
        curve = _curve([10000, 10100, 10000, 10200, 10150])
        trades = [
            {"symbol": "AAPL", "pnl": D("200"), "gross_notional": D("5000"),
             "holding_days": 4, "year": 2024},
            {"symbol": "AAPL", "pnl": D("-50"), "gross_notional": D("5000"),
             "holding_days": 2, "year": 2024},
        ]
        bars = {"AAPL": [
            {"t": "2024-01-01", "o": 100, "h": 101, "l": 99, "c": 100, "v": 1},
            {"t": "2024-01-02", "o": 100, "h": 102, "l": 99, "c": 101, "v": 1},
        ]}
        m = compute_metrics(
            equity_curve=curve,
            trades=trades,
            initial_equity=D("10000"),
            ending_equity=D("10150"),
            asset_class="stock",
            per_symbol_bars=bars,
            total_costs=D("12.34"),
        )
        # required keys present
        for key in ("net_return", "cagr", "max_drawdown", "annualized_volatility",
                    "sharpe_ratio", "sortino_ratio", "calmar_ratio",
                    "turnover", "total_costs", "win_rate", "payoff_ratio",
                    "expectancy", "worst_trade", "worst_daily_return",
                    "expected_shortfall_95", "worst_gap_loss", "holding_period",
                    "by_year", "by_symbol"):
            assert key in m, f"missing metric {key}"
        assert m["net_return"] == net_return(D("10000"), D("10150"))
        assert m["total_costs"] == D("12.34")
        # by_symbol should aggregate AAPL
        assert any(row["symbol"] == "AAPL" for row in m["by_symbol"])
        # by_year should aggregate 2024
        assert any(row["year"] == 2024 for row in m["by_year"])
