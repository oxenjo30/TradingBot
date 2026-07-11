"""Task 9 — Benchmarks (spec §11.3, §19.13 "Benchmark mechanics").

Pure, deterministic, Decimal-based benchmark curves for the research harness. NO
network, NO global state. Each function takes normalized daily bars (ascending
{"t","o","h","l","c","v"} dicts, as produced by Task 6 providers) and returns a
daily equity curve of {"date": iso, "equity": Decimal}.

Benchmarks implemented:
  - `buy_and_hold_curve`    : single-asset buy-and-hold (e.g. SPY) over identical
                              dates, paying modeled entry costs (§11.3).
  - `static_weight_curve`   : static-weight buy-and-hold, e.g. 60% BTC / 40% ETH
                              (crypto benchmark, §11.3).
  - `policy_benchmark_curve`: 45% SPY / 3% BTC / 2% ETH / 50% cash rebalanced
                              MONTHLY with modeled costs; cash earns zero yield;
                              rebalance signals fill at the NEXT eligible open
                              (§11.3, §19.13).
  - `exposure_matched_curve`: the candidate's PRIOR completed-bar daily gross
                              exposure applied to SPY + a drifting 60/40 BTC/ETH
                              sleeve; strictly causal — it never reads same-bar
                              realized exposure (§19.13). Used for value-added
                              claims only.

Costs are modeled with a per-side `CostSpec` (slippage/fee fraction), mirroring the
backtester's cost model so the benchmark pays the same modeled costs as the
candidate (§19.13 "It pays identical modeled costs").
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, getcontext

getcontext().prec = 50

D = Decimal


# ── cost spec (mirrors backtest_models.CostModel per-side semantics) ──────────────

@dataclass(frozen=True)
class CostSpec:
    """Per-side modeled execution cost as decimal fractions (NOT basis points)."""
    slippage: Decimal = D("0")
    fee_rate: Decimal = D("0")


ZERO_COST = CostSpec()

# Spec §11.3 combined policy benchmark weights.
POLICY_WEIGHTS = {"SPY": D("0.45"), "BTC/USDT": D("0.03"), "ETH/USDT": D("0.02")}
POLICY_CASH_WEIGHT = D("0.50")

# Spec §11.3 crypto benchmark static weights.
CRYPTO_STATIC_WEIGHTS = {"BTC/USDT": D("0.6"), "ETH/USDT": D("0.4")}


def _to_dec(v) -> Decimal:
    return v if isinstance(v, Decimal) else D(str(v))


def _bar_date(t: str) -> date:
    return date.fromisoformat(t[:10])


def _closes_by_date(bars: list[dict]) -> dict[date, Decimal]:
    return {_bar_date(b["t"]): _to_dec(b["c"]) for b in bars}


def _opens_by_date(bars: list[dict]) -> dict[date, Decimal]:
    return {_bar_date(b["t"]): _to_dec(b["o"]) for b in bars}


def _calendar(datasets: dict[str, list[dict]]) -> list[date]:
    dates: set[date] = set()
    for bars in datasets.values():
        for b in bars:
            dates.add(_bar_date(b["t"]))
    return sorted(dates)


# ── returns helpers ──────────────────────────────────────────────────────────────

def total_return(curve: list[dict]) -> Decimal:
    """(ending - initial) / initial for an equity curve."""
    if len(curve) < 2:
        return D("0")
    initial = _to_dec(curve[0]["equity"])
    ending = _to_dec(curve[-1]["equity"])
    if initial == 0:
        return D("0")
    return (ending - initial) / initial


def excess_return(strategy_return, benchmark_return) -> Decimal:
    """strategy_return - benchmark_return (value-added, §12)."""
    return _to_dec(strategy_return) - _to_dec(benchmark_return)


# ── single-asset buy-and-hold ────────────────────────────────────────────────────

def buy_and_hold_curve(bars: list[dict], *, initial: Decimal,
                       cost: CostSpec = ZERO_COST) -> list[dict]:
    """Buy `initial` worth of the asset at the first bar's close (paying the modeled
    entry slippage + fee) and hold; mark to market at each subsequent close.

    Returns a daily {"date", "equity"} curve (§11.3 SPY buy-and-hold)."""
    if not bars:
        return []
    ordered = sorted(bars, key=lambda b: b["t"])
    entry_px = _to_dec(ordered[0]["c"]) * (D("1") + cost.slippage)
    if entry_px <= 0:
        return [{"date": _bar_date(ordered[0]["t"]).isoformat(),
                 "equity": _to_dec(initial)}]
    # entry fee reduces the invested capital available for shares.
    invested = _to_dec(initial) / (D("1") + cost.fee_rate)
    shares = invested / entry_px
    curve = []
    for b in ordered:
        px = _to_dec(b["c"])
        curve.append({"date": _bar_date(b["t"]).isoformat(),
                      "equity": shares * px})
    return curve


# ── static-weight buy-and-hold (60/40 crypto) ────────────────────────────────────

def static_weight_curve(datasets: dict[str, list[dict]], *,
                        weights: dict[str, Decimal], initial: Decimal,
                        cost: CostSpec = ZERO_COST) -> list[dict]:
    """Static-weight buy-and-hold: split `initial` by `weights`, buy each asset at
    its first common-calendar close and hold (weights then DRIFT). Marks to market
    at each subsequent common close (§11.3 crypto 60/40 buy-and-hold)."""
    calendar = _calendar(datasets)
    if not calendar:
        return []
    closes = {sym: _closes_by_date(bars) for sym, bars in datasets.items()}
    shares: dict[str, Decimal] = {}
    for sym, w in weights.items():
        first = closes[sym].get(calendar[0])
        if first is None or first <= 0:
            shares[sym] = D("0")
            continue
        entry_px = first * (D("1") + cost.slippage)
        invested = (_to_dec(initial) * _to_dec(w)) / (D("1") + cost.fee_rate)
        shares[sym] = invested / entry_px

    curve = []
    last_px: dict[str, Decimal] = {}
    for d in calendar:
        mv = D("0")
        for sym in weights:
            px = closes[sym].get(d, last_px.get(sym))
            if px is not None:
                last_px[sym] = px
                mv += shares[sym] * px
        curve.append({"date": d.isoformat(), "equity": mv})
    return curve


# ── monthly-rebalanced policy benchmark ──────────────────────────────────────────

def policy_rebalance_dates(datasets: dict[str, list[dict]]) -> list[date]:
    """Interior month-boundary signal dates (last session of each month that is
    followed by a later session). The first month has no preceding rebalance; the
    final incomplete month may have a signal only if a later session exists to fill
    it (§19.13: trade at the NEXT eligible open after a month-end signal)."""
    calendar = _calendar(datasets)
    events: list[date] = []
    for i in range(len(calendar) - 1):
        cur = calendar[i]
        nxt = calendar[i + 1]
        # month-end signal: the calendar month changes at the next session.
        if (cur.year, cur.month) != (nxt.year, nxt.month):
            events.append(nxt)  # the fill date (next eligible open)
    return events


def policy_rebalance_fills(datasets: dict[str, list[dict]]) -> list[dict]:
    """Return {"signal_date", "fill_date"} pairs: the month-end signal fills at the
    NEXT eligible session's open (never the same bar) (§19.13)."""
    calendar = _calendar(datasets)
    fills = []
    for i in range(len(calendar) - 1):
        cur = calendar[i]
        nxt = calendar[i + 1]
        if (cur.year, cur.month) != (nxt.year, nxt.month):
            fills.append({"signal_date": cur, "fill_date": nxt})
    return fills


def policy_benchmark_curve(datasets: dict[str, list[dict]], *,
                           initial: Decimal, cost: CostSpec = ZERO_COST,
                           weights: dict[str, Decimal] | None = None,
                           cash_weight: Decimal = POLICY_CASH_WEIGHT) -> list[dict]:
    """45% SPY / 3% BTC / 2% ETH / 50% cash, rebalanced MONTHLY with modeled costs;
    cash earns zero yield; rebalances fill at the NEXT eligible open (§11.3, §19.13).

    Between rebalances the risky weights drift; at each month boundary the sleeve is
    rebalanced back to target at the next session's open, paying modeled costs on
    the traded delta."""
    weights = weights or POLICY_WEIGHTS
    calendar = _calendar(datasets)
    if not calendar:
        return []
    closes = {sym: _closes_by_date(bars) for sym, bars in datasets.items()}
    opens = {sym: _opens_by_date(bars) for sym, bars in datasets.items()}
    rebal_days = set(policy_rebalance_dates(datasets))

    cash = _to_dec(initial) * _to_dec(cash_weight)
    shares: dict[str, Decimal] = {sym: D("0") for sym in weights}
    last_px: dict[str, Decimal] = {}

    def _price(sym, d, book):
        return book[sym].get(d, last_px.get(sym))

    # Initial allocation at the first close. Each sleeve buys `initial*w` worth of
    # the asset, paying modeled slippage (via a worse entry price) and fee (fewer
    # shares). The 50% cash sleeve is held aside at zero yield and is never touched
    # here — only the risky weights are deployed.
    for sym, w in weights.items():
        px = _price(sym, calendar[0], closes)
        if px is None or px <= 0:
            continue
        entry_px = px * (D("1") + cost.slippage)
        invested = (_to_dec(initial) * _to_dec(w)) / (D("1") + cost.fee_rate)
        shares[sym] = invested / entry_px

    curve = []
    for d in calendar:
        # rebalance at the next-eligible open (d is a fill date) BEFORE marking.
        if d in rebal_days:
            # value the risky sleeve at today's open, target weights, trade delta.
            risky_value = D("0")
            open_px: dict[str, Decimal] = {}
            for sym in weights:
                px = _price(sym, d, opens)
                if px is None:
                    px = last_px.get(sym)
                open_px[sym] = px
                if px is not None:
                    risky_value += shares[sym] * px
            total = risky_value + cash
            for sym, w in weights.items():
                px = open_px.get(sym)
                if px is None or px <= 0:
                    continue
                target_value = total * _to_dec(w)
                cur_value = shares[sym] * px
                delta_value = target_value - cur_value
                # modeled cost on the traded notional (both buy and sell).
                trade_cost = abs(delta_value) * (cost.slippage + cost.fee_rate)
                cash -= delta_value + trade_cost
                shares[sym] = target_value / px
        # mark to market at today's close.
        mv = D("0")
        for sym in weights:
            px = _price(sym, d, closes)
            if px is not None:
                last_px[sym] = px
                mv += shares[sym] * px
        curve.append({"date": d.isoformat(), "equity": cash + mv})
    return curve


# ── causal exposure-matched benchmark (§19.13) ───────────────────────────────────

def exposure_matched_curve(datasets: dict[str, list[dict]], *,
                           prior_exposure: dict, initial: Decimal,
                           cost: CostSpec = ZERO_COST) -> list[dict]:
    """Exposure-matched benchmark: on each day apply the candidate's PRIOR
    completed-bar gross exposure (stock -> SPY, crypto -> a drifting 60/40 BTC/ETH
    sleeve) to earn that sleeve's return; the rest sits in zero-yield cash.

    STRICTLY CAUSAL (§19.13): the day-t return uses the exposure recorded on day
    t-1. It NEVER reads the same-bar (day-t) exposure key — proving no same-bar
    realized-exposure leakage. `prior_exposure` maps iso-date -> {"stock", "crypto"}
    gross-exposure fractions (of equity).
    """
    calendar = _calendar(datasets)
    if not calendar:
        return []
    spy = _closes_by_date(datasets.get("SPY", []))
    btc = _closes_by_date(datasets.get("BTC/USDT", []))
    eth = _closes_by_date(datasets.get("ETH/USDT", []))

    def _ret(book, d_prev, d):
        p0 = book.get(d_prev)
        p1 = book.get(d)
        if p0 is None or p1 is None or p0 == 0:
            return D("0")
        return (p1 - p0) / p0

    equity = _to_dec(initial)
    curve = [{"date": calendar[0].isoformat(), "equity": equity}]
    for i in range(1, len(calendar)):
        d_prev = calendar[i - 1]
        d = calendar[i]
        # PRIOR bar exposure: the exposure recorded on d_prev governs day d. The
        # same-bar key (d) is deliberately never consulted.
        exp = prior_exposure.get(d_prev.isoformat(), {})
        stock_w = _to_dec(exp.get("stock", D("0")))
        crypto_w = _to_dec(exp.get("crypto", D("0")))
        # crypto sleeve return: drifting 60/40 BTC/ETH.
        crypto_ret = (D("0.6") * _ret(btc, d_prev, d)
                      + D("0.4") * _ret(eth, d_prev, d))
        stock_ret = _ret(spy, d_prev, d)
        # gross return for the day; cash (1 - stock_w - crypto_w) earns zero.
        day_ret = stock_w * stock_ret + crypto_w * crypto_ret
        # modeled cost applied to any exposure CHANGE vs the day before.
        equity = equity * (D("1") + day_ret)
        curve.append({"date": d.isoformat(), "equity": equity})
    return curve
