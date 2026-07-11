"""Task 7 — Backtest metrics (spec §10.4, §19.11).

Pure, deterministic, Decimal-based performance metrics for the portfolio
backtester. This module has NO network and NO global state; every function is a
pure computation over an equity curve, closed trades, and per-symbol bars.

Design rules (spec §10.4):
  - One documented annualization scale, chosen by asset class: stock sessions use
    252, 24/7 crypto uses 365. Stock and crypto are NOT annualized identically.
  - Metrics are computed on Decimal inputs. Reporting-only rounding happens at the
    projection boundary (backtest.py), never inside the authoritative numbers.
  - Tail-loss trio (spec §19.11): worst daily return, 95% historical expected
    shortfall, worst next-open gap loss.

The equity curve is a list of {"date": iso, "equity": Decimal[, "cash": Decimal,
"market_value": Decimal]}. Closed trades are dicts with at least "pnl" (Decimal),
and optionally "gross_notional", "holding_days", "symbol", "year".
"""
from __future__ import annotations

from decimal import Decimal, getcontext

# Give Decimal enough precision for sqrt / division chains without float drift.
getcontext().prec = 50

D = Decimal

# ── annualization scale (§10.4) ──────────────────────────────────────────────────

ANNUALIZATION_STOCK = 252
ANNUALIZATION_CRYPTO = 365


def annualization_factor(asset_class: str) -> int:
    """Trading periods per year for the given asset class (spec §10.4).

    Stock sessions (252) and 24/7 crypto (365) use DIFFERENT scales, applied
    consistently everywhere annualization occurs."""
    ac = (asset_class or "").lower()
    if ac == "stock":
        return ANNUALIZATION_STOCK
    if ac == "crypto":
        return ANNUALIZATION_CRYPTO
    raise ValueError(f"unknown asset_class for annualization: {asset_class!r}")


# ── decimal sqrt ──────────────────────────────────────────────────────────────────

def _sqrt(x: Decimal) -> Decimal:
    if x <= 0:
        return D("0")
    return x.sqrt()


def _to_dec(v) -> Decimal:
    return v if isinstance(v, Decimal) else D(str(v))


# ── returns ─────────────────────────────────────────────────────────────────────

def net_return(initial: Decimal, ending: Decimal) -> Decimal:
    """(ending - initial) / initial."""
    initial = _to_dec(initial)
    ending = _to_dec(ending)
    if initial == 0:
        return D("0")
    return (ending - initial) / initial


def cagr(initial: Decimal, ending: Decimal, *, periods: int,
         asset_class: str) -> Decimal:
    """Compound annual growth rate.

    `periods` is the number of elapsed trading periods; years = periods / scale.
    Uses the asset-class annualization scale (§10.4). Non-positive equity or
    zero elapsed time yields 0."""
    initial = _to_dec(initial)
    ending = _to_dec(ending)
    if initial <= 0 or ending <= 0 or periods <= 0:
        return D("0")
    scale = annualization_factor(asset_class)
    years = D(periods) / D(scale)
    if years <= 0:
        return D("0")
    # (ending/initial) ** (1/years) - 1 via Decimal ln/exp for precision.
    growth = ending / initial
    return (growth ** (D(1) / years)) - D(1)


# ── drawdown ─────────────────────────────────────────────────────────────────────

def max_drawdown(equity_curve: list[dict]) -> Decimal:
    """Maximum peak-to-trough drawdown as a non-positive fraction."""
    peak = None
    worst = D("0")
    for pt in equity_curve:
        eq = _to_dec(pt["equity"])
        if peak is None or eq > peak:
            peak = eq
        if peak and peak > 0:
            dd = (eq - peak) / peak
            if dd < worst:
                worst = dd
    return worst


# ── daily returns / volatility / risk-adjusted ───────────────────────────────────

def daily_returns(equity_curve: list[dict]) -> list[Decimal]:
    """Period-over-period simple returns from the equity curve."""
    eqs = [_to_dec(pt["equity"]) for pt in equity_curve]
    out: list[Decimal] = []
    for i in range(1, len(eqs)):
        prev = eqs[i - 1]
        if prev == 0:
            out.append(D("0"))
        else:
            out.append((eqs[i] - prev) / prev)
    return out


def _mean(vals: list[Decimal]) -> Decimal:
    if not vals:
        return D("0")
    return sum(vals, D("0")) / D(len(vals))


def _pstdev_sample(vals: list[Decimal]) -> Decimal:
    """Sample standard deviation (n-1)."""
    n = len(vals)
    if n < 2:
        return D("0")
    m = _mean(vals)
    var = sum(((v - m) ** 2 for v in vals), D("0")) / D(n - 1)
    return _sqrt(var)


def annualized_volatility(equity_curve: list[dict], *, asset_class: str) -> Decimal:
    """Std-dev of daily returns scaled by sqrt(periods/year)."""
    rets = daily_returns(equity_curve)
    sd = _pstdev_sample(rets)
    if sd == 0:
        return D("0")
    return sd * _sqrt(D(annualization_factor(asset_class)))


def sharpe_ratio(equity_curve: list[dict], *, asset_class: str,
                 risk_free: Decimal = D("0")) -> Decimal:
    """Annualized Sharpe using daily excess returns. Zero volatility → 0."""
    rets = daily_returns(equity_curve)
    if len(rets) < 2:
        return D("0")
    scale = D(annualization_factor(asset_class))
    rf_daily = _to_dec(risk_free) / scale
    excess = [r - rf_daily for r in rets]
    sd = _pstdev_sample(excess)
    if sd == 0:
        return D("0")
    return (_mean(excess) / sd) * _sqrt(scale)


def sortino_ratio(equity_curve: list[dict], *, asset_class: str,
                  risk_free: Decimal = D("0")) -> Decimal:
    """Annualized Sortino using downside deviation of daily excess returns."""
    rets = daily_returns(equity_curve)
    if len(rets) < 2:
        return D("0")
    scale = D(annualization_factor(asset_class))
    rf_daily = _to_dec(risk_free) / scale
    excess = [r - rf_daily for r in rets]
    downside = [e for e in excess if e < 0]
    if not downside:
        return D("0")
    # Downside deviation uses n (all periods) in the denominator by convention.
    dvar = sum((e ** 2 for e in downside), D("0")) / D(len(excess))
    dd = _sqrt(dvar)
    if dd == 0:
        return D("0")
    return (_mean(excess) / dd) * _sqrt(scale)


def calmar_ratio(equity_curve: list[dict], initial: Decimal, ending: Decimal, *,
                 periods: int, asset_class: str) -> Decimal | None:
    """CAGR / |max drawdown|. None when there is no drawdown (undefined)."""
    mdd = max_drawdown(equity_curve)
    if mdd == 0:
        return None
    c = cagr(initial, ending, periods=periods, asset_class=asset_class)
    return c / abs(mdd)


# ── turnover + trade stats ───────────────────────────────────────────────────────

def turnover(trades: list[dict], equity_curve: list[dict]) -> Decimal:
    """Total traded notional / average equity."""
    total = sum((_to_dec(t.get("gross_notional", 0)) for t in trades), D("0"))
    eqs = [_to_dec(pt["equity"]) for pt in equity_curve]
    if not eqs:
        return D("0")
    avg_eq = _mean(eqs)
    if avg_eq == 0:
        return D("0")
    return total / avg_eq


def win_rate(trades: list[dict]) -> Decimal | None:
    """Fraction of closed trades with positive P&L. None when no trades."""
    if not trades:
        return None
    wins = sum(1 for t in trades if _to_dec(t["pnl"]) > 0)
    return D(wins) / D(len(trades))


def payoff_ratio(trades: list[dict]) -> Decimal | None:
    """Average win / average |loss|. None when either side is empty."""
    wins = [_to_dec(t["pnl"]) for t in trades if _to_dec(t["pnl"]) > 0]
    losses = [abs(_to_dec(t["pnl"])) for t in trades if _to_dec(t["pnl"]) < 0]
    if not wins or not losses:
        return None
    return _mean(wins) / _mean(losses)


def expectancy(trades: list[dict]) -> Decimal | None:
    """Mean net P&L per closed trade. None when no trades."""
    if not trades:
        return None
    return _mean([_to_dec(t["pnl"]) for t in trades])


def holding_period_stats(trades: list[dict]) -> dict:
    """Average / min / max / distribution of holding periods in days."""
    days = [int(t["holding_days"]) for t in trades if t.get("holding_days") is not None]
    if not days:
        return {"avg_days": None, "min_days": None, "max_days": None,
                "distribution": {}}
    dist: dict[int, int] = {}
    for d in days:
        dist[d] = dist.get(d, 0) + 1
    return {
        "avg_days": _mean([D(d) for d in days]),
        "min_days": min(days),
        "max_days": max(days),
        "distribution": dist,
    }


def worst_trade(trades: list[dict]) -> Decimal | None:
    """Most negative closed-trade P&L. None when no trades."""
    if not trades:
        return None
    return min(_to_dec(t["pnl"]) for t in trades)


# ── tail-loss measures (§19.11) ──────────────────────────────────────────────────

def worst_daily_return(equity_curve: list[dict]) -> Decimal | None:
    """Most negative single-period return. None when < 2 points."""
    rets = daily_returns(equity_curve)
    if not rets:
        return None
    return min(rets)


def expected_shortfall(equity_curve: list[dict], *,
                       confidence: Decimal = D("0.95")) -> Decimal | None:
    """Historical expected shortfall (average of the worst (1-confidence) tail).

    At least one observation is always included so a single catastrophic day is
    not averaged away. Returns a non-positive number, or None with no returns."""
    rets = sorted(daily_returns(equity_curve))
    if not rets:
        return None
    n = len(rets)
    tail_frac = D(1) - _to_dec(confidence)
    k = int((tail_frac * D(n)).to_integral_value(rounding="ROUND_FLOOR"))
    if k < 1:
        k = 1
    tail = rets[:k]
    return _mean(tail)


def worst_gap_loss(per_symbol_bars: dict[str, list[dict]]) -> Decimal | None:
    """Worst overnight/inter-bar open gap loss: min over all symbols/bars of
    (open - prev_close) / prev_close (spec §19.11 "worst next-open gap loss")."""
    worst: Decimal | None = None
    for _sym, bars in per_symbol_bars.items():
        ordered = sorted(bars, key=lambda b: b["t"])
        for i in range(1, len(ordered)):
            prev_c = _to_dec(ordered[i - 1]["c"])
            open_ = _to_dec(ordered[i]["o"])
            if prev_c == 0:
                continue
            gap = (open_ - prev_c) / prev_c
            if worst is None or gap < worst:
                worst = gap
    return worst


# ── benchmark ─────────────────────────────────────────────────────────────────────

def excess_return(strategy_return: Decimal, benchmark_return: Decimal) -> Decimal:
    """strategy_return - benchmark_return."""
    return _to_dec(strategy_return) - _to_dec(benchmark_return)


# ── results by year / symbol ─────────────────────────────────────────────────────

def _by_key(trades: list[dict], key: str) -> list[dict]:
    groups: dict = {}
    for t in trades:
        k = t.get(key)
        if k is None:
            continue
        g = groups.setdefault(k, {"n": 0, "wins": 0, "pnl": D("0")})
        g["n"] += 1
        pnl = _to_dec(t["pnl"])
        g["pnl"] += pnl
        if pnl > 0:
            g["wins"] += 1
    out = []
    for k in sorted(groups):
        g = groups[k]
        out.append({
            key: k,
            "trades": g["n"],
            "wins": g["wins"],
            "win_rate": (D(g["wins"]) / D(g["n"])) if g["n"] else None,
            "total_pnl": g["pnl"],
        })
    return out


def by_symbol(trades: list[dict]) -> list[dict]:
    return _by_key(trades, "symbol")


def by_year(trades: list[dict]) -> list[dict]:
    return _by_key(trades, "year")


# ── aggregate bundle ─────────────────────────────────────────────────────────────

def compute_metrics(*, equity_curve: list[dict], trades: list[dict],
                    initial_equity: Decimal, ending_equity: Decimal,
                    asset_class: str,
                    per_symbol_bars: dict[str, list[dict]] | None = None,
                    total_costs: Decimal = D("0"),
                    benchmark_return: Decimal | None = None) -> dict:
    """Compute the full spec §10.4 metric bundle on one documented scale.

    Returns Decimal-valued metrics (or None where undefined). The caller projects
    these to the legacy float response shape at the API boundary."""
    periods = max(len(equity_curve) - 1, 0)
    scale = annualization_factor(asset_class)
    per_symbol_bars = per_symbol_bars or {}

    m: dict = {
        "asset_class": asset_class,
        "annualization": scale,
        "periods": periods,
        "net_return": net_return(initial_equity, ending_equity),
        "cagr": cagr(initial_equity, ending_equity, periods=periods,
                     asset_class=asset_class),
        "max_drawdown": max_drawdown(equity_curve),
        "annualized_volatility": annualized_volatility(equity_curve,
                                                       asset_class=asset_class),
        "sharpe_ratio": sharpe_ratio(equity_curve, asset_class=asset_class),
        "sortino_ratio": sortino_ratio(equity_curve, asset_class=asset_class),
        "calmar_ratio": calmar_ratio(equity_curve, initial_equity, ending_equity,
                                     periods=periods, asset_class=asset_class),
        "turnover": turnover(trades, equity_curve),
        "total_costs": _to_dec(total_costs),
        "win_rate": win_rate(trades),
        "payoff_ratio": payoff_ratio(trades),
        "expectancy": expectancy(trades),
        "worst_trade": worst_trade(trades),
        "worst_daily_return": worst_daily_return(equity_curve),
        "expected_shortfall_95": expected_shortfall(equity_curve,
                                                    confidence=D("0.95")),
        "worst_gap_loss": worst_gap_loss(per_symbol_bars),
        "holding_period": holding_period_stats(trades),
        "by_year": by_year(trades),
        "by_symbol": by_symbol(trades),
        "total_trades": len(trades),
    }
    if benchmark_return is not None:
        m["benchmark_return"] = _to_dec(benchmark_return)
        m["excess_return"] = excess_return(m["net_return"], benchmark_return)
    return m
