"""Task 9 — Statistics and the statistical acceptance gate (spec §11, §12, §19.10,
§19.13 "Statistical gate").

Pure, deterministic, Decimal-based. NO network, NO global mutable state. This is
research/reporting infrastructure ONLY; it never touches the live engine and it
never enables a strategy — it produces PASS / FAIL / INCONCLUSIVE evidence.

Contents:
  - moving-block bootstrap 95% confidence intervals for the MEAN of a daily-return
    or per-trade-expectancy series (§19.10): 20-session stock blocks, 14-day
    crypto blocks. Seeded, so intervals are reproducible.
  - the statistical gate (§19.13): lower bound > 0 -> PASS; wholly negative -> FAIL;
    spanning zero -> INCONCLUSIVE (which is explicitly NOT a pass).
  - profit concentration (divide by total positive P&L BEFORE losses) and loss
    concentration (reported separately) (§19.10).
  - the twelve hard §12 acceptance criteria, each a distinct checkable predicate,
    plus `evaluate_all_criteria` that bundles them.
"""
from __future__ import annotations

import random
from decimal import Decimal, getcontext
from enum import Enum

# Enough precision for long division/sqrt chains without float drift.
getcontext().prec = 50

D = Decimal

# Spec §19.10 moving-block sizes and confidence.
STOCK_BLOCK = 20
CRYPTO_BLOCK = 14
DEFAULT_CONFIDENCE = D("0.95")

# Spec §12 numeric thresholds.
DRAWDOWN_CEILING = D("-0.05")          # combined max drawdown at/below 5%
MIN_FOLD_WIN_RATE = D("0.60")          # positive in >= 60% of folds
MIN_STOCK_TRADES = 100                 # >= 100 closed stock trades
MIN_CRYPTO_ROUND_TRIPS = 20            # >= 20 crypto round trips (else inconclusive)
MAX_CONCENTRATION = D("0.35")          # no symbol/year > 35% of net profit
MIN_NEIGHBOR_CALMAR_FRAC = D("0.70")   # neighbors retain >= 70% of selected Calmar


class GateVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


def _to_dec(v) -> Decimal:
    return v if isinstance(v, Decimal) else D(str(v))


# ── moving-block bootstrap (§19.10) ──────────────────────────────────────────────

def _mean(vals: list[Decimal]) -> Decimal:
    if not vals:
        return D("0")
    return sum(vals, D("0")) / D(len(vals))


def moving_block_bootstrap_ci(series, block_size: int, *,
                              confidence: Decimal = DEFAULT_CONFIDENCE,
                              n_resamples: int = 1000,
                              seed: int = 0) -> tuple[Decimal, Decimal, Decimal]:
    """Moving-block bootstrap CI for the MEAN of `series`.

    Resamples overlapping blocks of length `block_size` (a stationary-block-style
    scheme that preserves short-range autocorrelation, §19.10) until at least
    len(series) observations are gathered, computes the resample mean, and returns
    the `(lower, point, upper)` percentile interval at the requested confidence.

    Deterministic for a fixed `seed`. Raises ValueError on an empty series.
    """
    data = [_to_dec(x) for x in series]
    n = len(data)
    if n == 0:
        raise ValueError("cannot bootstrap an empty series")
    block = max(1, min(int(block_size), n))
    point = _mean(data)

    rng = random.Random(seed)
    n_blocks = (n + block - 1) // block
    max_start = n - block  # inclusive; overlapping blocks (wrap not needed)

    means: list[Decimal] = []
    for _ in range(int(n_resamples)):
        sample: list[Decimal] = []
        for _b in range(n_blocks):
            start = rng.randint(0, max_start) if max_start > 0 else 0
            sample.extend(data[start:start + block])
        sample = sample[:n]  # trim to the original length
        means.append(_mean(sample))

    means.sort()
    m = len(means)
    tail = (D("1") - _to_dec(confidence)) / D("2")
    lo_idx = int((tail * D(m)).to_integral_value(rounding="ROUND_FLOOR"))
    hi_idx = int(((D("1") - tail) * D(m)).to_integral_value(rounding="ROUND_CEILING")) - 1
    lo_idx = max(0, min(lo_idx, m - 1))
    hi_idx = max(0, min(hi_idx, m - 1))
    return means[lo_idx], point, means[hi_idx]


# ── statistical gate (§19.13) ────────────────────────────────────────────────────

def classify_ci(lower: Decimal, upper: Decimal) -> GateVerdict:
    """Classify a confidence interval per the spec statistical gate.

    lower > 0                 -> PASS
    upper < 0 (wholly < 0)    -> FAIL
    otherwise (spans zero)    -> INCONCLUSIVE (never a pass)
    A lower bound of exactly 0 is NOT a pass (strict inequality)."""
    lo = _to_dec(lower)
    hi = _to_dec(upper)
    if lo > 0:
        return GateVerdict.PASS
    if hi < 0:
        return GateVerdict.FAIL
    return GateVerdict.INCONCLUSIVE


def gate_series(series, block_size: int, *,
                confidence: Decimal = DEFAULT_CONFIDENCE,
                n_resamples: int = 1000, seed: int = 0) -> GateVerdict:
    """Bootstrap `series` and classify the resulting interval (§19.13)."""
    lo, _pt, hi = moving_block_bootstrap_ci(
        series, block_size, confidence=confidence,
        n_resamples=n_resamples, seed=seed)
    return classify_ci(lo, hi)


# ── profit / loss concentration (§19.10) ─────────────────────────────────────────

def profit_concentration(trades: list[dict], *, key: str) -> dict:
    """Fraction of TOTAL POSITIVE P&L contributed by each `key` group.

    The denominator is the sum of positive trade P&L across all trades BEFORE any
    losses are netted (§19.10). Loss trades never enter the numerator or the
    denominator. Groups with no positive contribution are omitted."""
    total_positive = sum((_to_dec(t["pnl"]) for t in trades
                          if _to_dec(t["pnl"]) > 0), D("0"))
    if total_positive <= 0:
        return {}
    out: dict = {}
    for t in trades:
        pnl = _to_dec(t["pnl"])
        if pnl <= 0:
            continue
        k = t.get(key)
        out[k] = out.get(k, D("0")) + pnl / total_positive
    return out


def max_profit_concentration(trades: list[dict], *, key: str) -> Decimal:
    """Largest single-group share of total positive P&L (0 when none positive)."""
    conc = profit_concentration(trades, key=key)
    if not conc:
        return D("0")
    return max(conc.values())


def loss_concentration(trades: list[dict], *, key: str) -> dict:
    """Fraction of TOTAL LOSSES contributed by each `key` group, reported
    separately from profit concentration (§19.10). Uses absolute loss magnitudes."""
    total_loss = sum((abs(_to_dec(t["pnl"])) for t in trades
                      if _to_dec(t["pnl"]) < 0), D("0"))
    if total_loss <= 0:
        return {}
    out: dict = {}
    for t in trades:
        pnl = _to_dec(t["pnl"])
        if pnl >= 0:
            continue
        k = t.get(key)
        out[k] = out.get(k, D("0")) + abs(pnl) / total_loss
    return out


# ── the twelve §12 acceptance criteria (each a distinct predicate) ───────────────

def c1_positive_oos_return_baseline(oos_return_baseline) -> bool:
    """§12.1 — Positive net out-of-sample return after baseline costs."""
    return _to_dec(oos_return_baseline) > 0


def c2_positive_oos_return_stressed(oos_return_stressed) -> bool:
    """§12.2 — Positive net out-of-sample return under stressed costs."""
    return _to_dec(oos_return_stressed) > 0


def c3_aggregate_drawdown_ok(aggregate_drawdown) -> bool:
    """§12.3 — Combined max drawdown at or below 5% over aggregate OOS results.
    Drawdown is a non-positive fraction; -0.05 (exactly 5%) passes."""
    return _to_dec(aggregate_drawdown) >= DRAWDOWN_CEILING


def c4_holdout_drawdown_ok(holdout_drawdown) -> bool:
    """§12.4 — Combined max drawdown at or below 5% in the final untouched holdout."""
    return _to_dec(holdout_drawdown) >= DRAWDOWN_CEILING


def c5_fold_win_rate_ok(fold_pnls) -> bool:
    """§12.5 — Positive net result in at least 60% of walk-forward folds."""
    pnls = [_to_dec(p) for p in fold_pnls]
    if not pnls:
        return False
    wins = sum(1 for p in pnls if p > 0)
    return (D(wins) / D(len(pnls))) >= MIN_FOLD_WIN_RATE


def c6_stock_trade_count_ok(stock_trade_count: int) -> bool:
    """§12.6 — At least 100 closed stock trades across the available history."""
    return int(stock_trade_count) >= MIN_STOCK_TRADES


def c7_crypto_round_trips(crypto_round_trips: int) -> GateVerdict:
    """§12.7 — At least 20 crypto round trips; fewer is INCONCLUSIVE, not a pass."""
    return (GateVerdict.PASS if int(crypto_round_trips) >= MIN_CRYPTO_ROUND_TRIPS
            else GateVerdict.INCONCLUSIVE)


def c8_concentration_ok(trades: list[dict]) -> bool:
    """§12.8 — No single stock OR calendar year supplies > 35% of total net profit.

    Concentration is measured against total positive P&L (§19.10) for both the
    symbol and the year grouping; the worse of the two must be <= 35%."""
    max_symbol = max_profit_concentration(trades, key="symbol")
    max_year = max_profit_concentration(trades, key="year")
    return max_symbol <= MAX_CONCENTRATION and max_year <= MAX_CONCENTRATION


def c9_neighbor_robustness_ok(*, selected_calmar, neighbor_calmars) -> bool:
    """§12.9 — Neighboring parameter settings stay profitable and retain >= 70% of
    the selected setting's OOS Calmar. When the selected Calmar is non-positive the
    candidate fails outright."""
    sel = _to_dec(selected_calmar)
    if sel <= 0:
        return False
    floor = MIN_NEIGHBOR_CALMAR_FRAC * sel
    for c in neighbor_calmars:
        cd = _to_dec(c)
        if cd <= 0 or cd < floor:
            return False
    return True


def c10_positive_expectancy(expectancy) -> bool:
    """§12.10 — The selected strategy has positive net expectancy."""
    return _to_dec(expectancy) > 0


def c11_integrity_ok(*, leakage: bool, negative_cash: bool,
                     ownership_violation: bool, reconciliation_failure: bool,
                     data_integrity_failure: bool) -> bool:
    """§12.11 — No temporal leakage, data-integrity, strategy-ownership,
    negative-cash, or ledger-reconciliation failure."""
    return not (leakage or negative_cash or ownership_violation
                or reconciliation_failure or data_integrity_failure)


def c12_visibility_ok(report: dict) -> bool:
    """§12.12 — Every attempted configuration and failed criterion remains visible.

    Requires a non-empty `attempts` list; `failed_criteria` must be present (an
    empty list is fine — it means nothing failed, still visible)."""
    if not isinstance(report, dict):
        return False
    attempts = report.get("attempts")
    if not attempts:
        return False
    return "failed_criteria" in report


def criteria_keys() -> list[str]:
    """The stable ordered list of the twelve criterion keys."""
    return [f"c{i}" for i in range(1, 13)]


def evaluate_all_criteria(*, oos_return_baseline, oos_return_stressed,
                          aggregate_drawdown, holdout_drawdown, fold_pnls,
                          stock_trade_count, crypto_round_trips, profit_trades,
                          selected_calmar, neighbor_calmars, expectancy,
                          integrity: dict, report: dict) -> dict:
    """Evaluate all twelve §12 criteria as distinct predicates and bundle them.

    Returns {"criteria": {c1..c12: {"pass": bool, "detail": ...}}, "overall": bool}.
    `overall` is True only when every applicable criterion passes; C7's
    INCONCLUSIVE counts as NOT passing (never silently a pass)."""
    c7 = c7_crypto_round_trips(crypto_round_trips)
    criteria = {
        "c1": {"pass": c1_positive_oos_return_baseline(oos_return_baseline)},
        "c2": {"pass": c2_positive_oos_return_stressed(oos_return_stressed)},
        "c3": {"pass": c3_aggregate_drawdown_ok(aggregate_drawdown)},
        "c4": {"pass": c4_holdout_drawdown_ok(holdout_drawdown)},
        "c5": {"pass": c5_fold_win_rate_ok(fold_pnls)},
        "c6": {"pass": c6_stock_trade_count_ok(stock_trade_count)},
        "c7": {"pass": c7 is GateVerdict.PASS, "verdict": c7.value},
        "c8": {"pass": c8_concentration_ok(profit_trades)},
        "c9": {"pass": c9_neighbor_robustness_ok(
            selected_calmar=selected_calmar, neighbor_calmars=neighbor_calmars)},
        "c10": {"pass": c10_positive_expectancy(expectancy)},
        "c11": {"pass": c11_integrity_ok(**integrity)},
        "c12": {"pass": c12_visibility_ok(report)},
    }
    overall = all(criteria[k]["pass"] for k in criteria_keys())
    return {"criteria": criteria, "overall": overall}
