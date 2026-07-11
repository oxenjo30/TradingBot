"""Task 9 — Benchmarks (spec §11.3, §19.13 "Benchmark mechanics").

Deterministic, NO-NETWORK, Decimal tests for:
  - stock benchmark: SPY buy-and-hold over identical dates/policy
  - crypto benchmark: static 60% BTC / 40% ETH buy-and-hold
  - combined policy benchmark: 45% SPY / 3% BTC / 2% ETH / 50% cash rebalanced
    monthly with modeled costs, cash at zero yield, trading at the next eligible
    open after a month-end signal
  - combined exposure-matched benchmark: uses the candidate's PRIOR completed-bar
    daily gross exposure (causal) applied to SPY + a drifting 60/40 BTC/ETH sleeve;
    it never reads same-bar realized exposure.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from server import benchmarks as bm

D = Decimal


def _bar(t, price, v=1_000_000.0):
    return {"t": t, "o": float(price), "h": float(price), "l": float(price),
            "c": float(price), "v": float(v)}


def _series(prices, start="2020-01-01"):
    d = date.fromisoformat(start)
    bars = []
    for p in prices:
        bars.append(_bar(d.isoformat() + "T00:00:00+00:00", p))
        d += timedelta(days=1)
    return bars


# ── SPY buy-and-hold ─────────────────────────────────────────────────────────────

class TestBuyAndHold:
    def test_buy_and_hold_return_matches_price_change(self):
        bars = _series([100, 110, 120])
        # zero-cost buy-and-hold: 100 -> 120 = +20%
        curve = bm.buy_and_hold_curve(bars, initial=D("10000"),
                                      cost=bm.ZERO_COST)
        assert curve[-1]["equity"] == D("12000")
        assert bm.total_return(curve) == D("0.2")

    def test_buy_and_hold_pays_entry_cost(self):
        bars = _series([100, 100])
        curve = bm.buy_and_hold_curve(bars, initial=D("10000"),
                                      cost=bm.CostSpec(slippage=D("0.001")))
        # entry slips 10bps -> fewer shares -> ending equity slightly < 10000
        assert curve[-1]["equity"] < D("10000")


# ── static 60/40 BTC/ETH ─────────────────────────────────────────────────────────

class TestStaticWeights:
    def test_60_40_split_buy_and_hold(self):
        btc = _series([100, 200])   # BTC doubles
        eth = _series([100, 100])   # ETH flat
        curve = bm.static_weight_curve(
            {"BTC/USDT": btc, "ETH/USDT": eth},
            weights={"BTC/USDT": D("0.6"), "ETH/USDT": D("0.4")},
            initial=D("10000"), cost=bm.ZERO_COST)
        # 60% doubles (6000 -> 12000), 40% flat (4000) => 16000 => +60%
        assert curve[-1]["equity"] == D("16000")
        assert bm.total_return(curve) == D("0.6")


# ── combined policy benchmark (monthly rebalance) ────────────────────────────────

class TestPolicyBenchmark:
    def test_policy_weights_are_the_spec_defaults(self):
        # §11.3: 45% SPY, 3% BTC, 2% ETH, 50% cash.
        assert bm.POLICY_WEIGHTS == {
            "SPY": D("0.45"), "BTC/USDT": D("0.03"), "ETH/USDT": D("0.02"),
        }
        assert bm.POLICY_CASH_WEIGHT == D("0.50")

    def test_policy_holds_50pct_cash_at_zero_yield(self):
        # all risky assets flat -> equity unchanged; cash earns zero.
        spy = _series([100] * 40)
        btc = _series([100] * 40)
        eth = _series([100] * 40)
        curve = bm.policy_benchmark_curve(
            {"SPY": spy, "BTC/USDT": btc, "ETH/USDT": eth},
            initial=D("10000"), cost=bm.ZERO_COST)
        assert curve[-1]["equity"] == D("10000")

    def test_policy_rebalances_monthly_not_daily(self):
        # A rebalance event only occurs at month boundaries. With a 40-day series
        # spanning two calendar months there is at most one interior rebalance.
        spy = _series([100 + i for i in range(40)], start="2020-01-15")
        btc = _series([100] * 40, start="2020-01-15")
        eth = _series([100] * 40, start="2020-01-15")
        events = bm.policy_rebalance_dates(
            {"SPY": spy, "BTC/USDT": btc, "ETH/USDT": eth})
        # crosses Jan->Feb once inside the window
        assert len(events) == 1
        assert events[0].month == 2

    def test_policy_rebalance_trades_at_next_eligible_open(self):
        # month-end signal fills at the NEXT session's open, never same bar.
        spy = _series([100 + i for i in range(40)], start="2020-01-28")
        btc = _series([100] * 40, start="2020-01-28")
        eth = _series([100] * 40, start="2020-01-28")
        fills = bm.policy_rebalance_fills(
            {"SPY": spy, "BTC/USDT": btc, "ETH/USDT": eth})
        # each rebalance fill dated strictly after its month-end signal date
        for f in fills:
            assert f["fill_date"] > f["signal_date"]


# ── exposure-matched benchmark (causal, prior completed bar) ─────────────────────

class TestExposureMatched:
    def test_uses_prior_bar_exposure_not_same_bar(self):
        # candidate exposure series indexed by date; the benchmark on day t must
        # use exposure from day t-1 (prior completed bar), never day t.
        spy = _series([100, 110, 121, 133.1])  # +10% per day
        btc = _series([100, 100, 100, 100])
        eth = _series([100, 100, 100, 100])
        # candidate is fully invested in stock from the 2nd day onward.
        exposure = {
            spy[0]["t"][:10]: {"stock": D("0"), "crypto": D("0")},
            spy[1]["t"][:10]: {"stock": D("1"), "crypto": D("0")},
            spy[2]["t"][:10]: {"stock": D("1"), "crypto": D("0")},
            spy[3]["t"][:10]: {"stock": D("1"), "crypto": D("0")},
        }
        curve = bm.exposure_matched_curve(
            {"SPY": spy, "BTC/USDT": btc, "ETH/USDT": eth},
            prior_exposure=exposure, initial=D("10000"), cost=bm.ZERO_COST)
        # On day 2 (index1) the benchmark uses day1's PRIOR exposure = 0 (from
        # index0's recorded exposure), so it earns nothing that day. It only
        # starts earning once the prior-day exposure is > 0. This proves it does
        # not read same-bar exposure (which would already be 1 on day index1).
        rets = [pt["equity"] for pt in curve]
        # first return (index0->index1) must be flat because prior exposure was 0.
        assert rets[1] == rets[0]

    def test_exposure_matched_is_causal_shift(self):
        # Explicitly assert the benchmark never consults the same-bar exposure key.
        seen = []

        class _SpyReader(dict):
            def __getitem__(self, k):
                seen.append(k)
                return super().__getitem__(k)

        spy = _series([100, 110, 120])
        btc = _series([100, 100, 100])
        eth = _series([100, 100, 100])
        exposure = _SpyReader({
            spy[0]["t"][:10]: {"stock": D("0"), "crypto": D("0")},
            spy[1]["t"][:10]: {"stock": D("1"), "crypto": D("0")},
            spy[2]["t"][:10]: {"stock": D("1"), "crypto": D("0")},
        })
        bm.exposure_matched_curve(
            {"SPY": spy, "BTC/USDT": btc, "ETH/USDT": eth},
            prior_exposure=exposure, initial=D("10000"), cost=bm.ZERO_COST)
        # the LAST bar's own date must never be read as a same-bar exposure lookup
        assert spy[-1]["t"][:10] not in seen


# ── excess return / value-added ──────────────────────────────────────────────────

class TestExcessReturn:
    def test_value_added_over_benchmark(self):
        assert bm.excess_return(D("0.10"), D("0.06")) == D("0.04")
        assert bm.excess_return(D("0.02"), D("0.05")) == D("-0.03")
