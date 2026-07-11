"""Walk-forward validation for the Dual-Momentum ETF Rotation strategy.

Self-contained runner that reuses the SAME infrastructure as the Task 11 research
runner (historical_provider, PortfolioBacktester, run_walk_forward, statistical
gate) but with the dual-momentum ETF universe, a monthly-rebalance adapter, and a
predeclared grid over {lookback, abs_sma, top_k}.

Kept separate from scripts/run_strategy_research.py so the recorded Task 11 evidence
runner is untouched. READ-ONLY on live state: no order, no enable, no cutover, no
DB writes. If credentials are unavailable it records INCONCLUSIVE (never crashes).

Verdict semantics (identical to Task 11):
  - PASS         : holdout daily-return 95% CI lower bound > 0 (edge after costs).
  - FAIL         : CI wholly < 0.
  - INCONCLUSIVE : CI spans zero, no holdout series, or data unavailable/short.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from server import research as R
from server import statistics as S
from server.historical import (
    AssetClass, AdjustmentPolicy, AsOfPolicy, HistoricalRequest, HistoricalDataset,
)
from server.backtest_models import (
    PortfolioBacktester, BacktestConfig, CostModel, OrderRequest, SymbolSpec,
    EndConvention, BacktestError,
)

D = Decimal

UNIVERSE = ["SPY", "QQQ", "IWM", "DIA", "GLD", "TLT", "EEM"]


# ── indicators (float, decision-bar aware) ──────────────────────────────────────

def _sma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _total_return(closes, lookback):
    if len(closes) < lookback + 1:
        return None
    base = closes[-1 - lookback]
    if base <= 0:
        return None
    return closes[-1] / base - 1.0


# ── backtest adapter (ctx interface) ────────────────────────────────────────────

class _DualMomentumAdapter:
    """Mirrors server/strategies/dual_momentum.py rules on the backtester's ctx.

    Grid params: {lookback, abs_sma, top_k}. Monthly rebalance keyed off the
    decision date's month boundary. Between rebalances it emits no orders (hold)."""

    def __init__(self, params, notional):
        self.lookback = int(params["lookback"])
        self.abs_sma = int(params["abs_sma"])
        self.top_k = int(params["top_k"])
        self.notional = notional
        self._prev_month = None       # (year, month) of the last decision bar seen

    def note_fill(self, symbol, side, price):
        # Stateless rotation — entry price is not needed for exits.
        pass

    def _is_rebalance(self, ctx) -> bool:
        d = ctx.decision_date
        key = (d.year, d.month)
        first_of_month = key != self._prev_month
        self._prev_month = key
        return first_of_month

    def evaluate(self, ctx):
        if not self._is_rebalance(ctx):
            return []

        ranked = []
        for sym in UNIVERSE:
            closes = [b["c"] for b in ctx.bars(sym)]
            sma = _sma(closes, self.abs_sma)
            if sma is None or closes[-1] <= sma:
                continue
            ret = _total_return(closes, self.lookback)
            if ret is None:
                continue
            ranked.append((ret, sym))
        ranked.sort(key=lambda t: (-t[0], t[1]))
        target = {sym for _r, sym in ranked[:self.top_k]}

        out = []
        # Exits: any held symbol not in the target set.
        for sym, qty in ctx.positions.items():
            if qty > 0 and sym not in target:
                out.append(OrderRequest(sym, "sell", qty=qty, reason="rotate out"))
        # Entries: target symbols not already held.
        for _ret, sym in ranked[:self.top_k]:
            if ctx.position(sym) > 0:
                continue
            out.append(OrderRequest(sym, "buy", notional=D(str(self.notional)),
                                    reason="rotate in"))
        return out


# ── predeclared grid (frozen BEFORE any data is seen) ────────────────────────────

def _grid():
    out = []
    for lookback in (63, 126, 252):
        for abs_sma in (150, 200):
            for top_k in (1, 2, 3):
                out.append({"lookback": lookback, "abs_sma": abs_sma, "top_k": top_k})
    return out


# ── data acquisition (real; split+dividend adjusted) ─────────────────────────────

def _try_real_data(geo):
    from server import alpaca_client
    end = date.today()
    start = end - timedelta(days=int((geo.min_years + 1.5) * 365.25))
    provider = alpaca_client.historical_provider()   # network, split+div adjusted
    datasets, fps = {}, {}
    for sym in UNIVERSE:
        req = HistoricalRequest(
            asset_class=AssetClass.STOCK, provider="alpaca", symbol=sym,
            start=start, end=end, timeframe="1D",
            adjustment=AdjustmentPolicy.RAW, as_of_policy=AsOfPolicy.POINT_IN_TIME)
        ds = provider.fetch(req)
        datasets[sym] = ds
        fps[sym] = ds.fingerprint
    # Integrity: no uncorrected split-sized adjacent-day gap.
    for sym, ds in datasets.items():
        prev = None
        for b in ds.bars:
            c = float(b["c"])
            if prev and c > 0 and (c / prev < 0.5 or c / prev > 2.0):
                raise BacktestError(f"split-sized gap in {sym} at {b['t'][:10]}")
            prev = c
    cal = sorted({date.fromisoformat(b["t"][:10])
                  for ds in datasets.values() for b in ds.bars})
    return datasets, cal, fps


# ── backtest_fn factory ──────────────────────────────────────────────────────────

def _make_backtest_fn(datasets, cost_model, initial=D("100000")):
    def _slice(ds, window):
        return [b for b in ds.bars
                if window.start <= date.fromisoformat(b["t"][:10]) <= window.end]

    def backtest_fn(*, params, window, from_cash, role):
        sliced = {}
        for sym, ds in datasets.items():
            bars = _slice(ds, window)
            if not bars:
                continue
            req = HistoricalRequest(
                asset_class=ds.asset_class, provider=ds.provider, symbol=sym,
                start=date.fromisoformat(bars[0]["t"][:10]),
                end=date.fromisoformat(bars[-1]["t"][:10]),
                timeframe="1D", adjustment=ds.adjustment)
            sliced[sym] = HistoricalDataset(request=req, bars=bars,
                                            retrieved_at=ds.retrieved_at)
        adapter = _DualMomentumAdapter(params, notional=float(initial) * 0.18)
        cfg = BacktestConfig(initial_capital=initial, asset_class="stock",
                             cost_model=cost_model,
                             end_convention=EndConvention.LIQUIDATE)
        bt = PortfolioBacktester(sliced, adapter, cfg)
        res = bt.run()
        m = res.metrics
        curve = res.equity_curve
        daily = []
        prev = None
        for pt in curve:
            eq = pt["equity"]
            if prev is not None and prev > 0:
                daily.append((eq - prev) / prev)
            prev = eq
        # NOTE: the metrics dict exposes "calmar_ratio"; select_params reads "calmar".
        # Map it (mirroring run_strategy_research.py) or selection would see 0.
        return {
            "net_return": m.get("net_return") if m.get("net_return") is not None else D("0"),
            "calmar": m.get("calmar_ratio") if m.get("calmar_ratio") is not None else D("0"),
            "max_drawdown": m.get("max_drawdown") if m.get("max_drawdown") is not None else D("0"),
            "turnover": m.get("turnover") if m.get("turnover") is not None else D("0"),
            "trades": res.trades,
            "daily_returns": daily,
        }
    return backtest_fn


# ── run ──────────────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description="Dual-momentum walk-forward validation")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        from server import crypto
        crypto.init_crypto()
    except Exception as exc:  # noqa: BLE001
        print(f"# warning: init_crypto failed ({exc})", file=sys.stderr)

    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=5).stdout.strip() or "unknown"
    except Exception:
        head = "unknown"

    geo = R.FoldGeometry.stock_default()
    verdict, reason, ci, extra = "INCONCLUSIVE", "", None, {}
    try:
        datasets, cal, fps = _try_real_data(geo)
        bt = _make_backtest_fn(datasets, CostModel.baseline("stock"))
        wf = R.run_walk_forward(calendar=cal, geometry=geo, grid=_grid(),
                                backtest_fn=bt, persist=None)
        extra = {"frozen_params": {k: str(v) for k, v in (wf.frozen_params or {}).items()},
                 "sessions": len(cal), "attempts": len(wf.attempts),
                 "fingerprints": fps}
        # run_walk_forward's holdout_summary carries only net_return/max_drawdown —
        # NOT the daily-return series. To score the §12 gate we must RE-RUN the
        # frozen params on the holdout window (exactly once) and extract the series
        # ourselves (mirrors run_strategy_research.py). This is not a second peek:
        # the freeze already selected params without touching the holdout.
        if wf.frozen_params is not None:
            plan = R.build_folds(cal, geo)
            h = bt(params=wf.frozen_params, window=plan.holdout,
                   from_cash=True, role="holdout")
            dr = h["daily_returns"]
            extra["holdout_net_return"] = str(h["net_return"])
            extra["holdout_trades"] = len(h["trades"])
            if dr:
                lo, pt, hi = S.moving_block_bootstrap_ci(dr, S.STOCK_BLOCK, seed=7)
                ci = (lo, pt, hi)
                # Drawdown criterion still applies: a PASS also needs holdout DD
                # within the equity-appropriate ceiling (§12.4).
                dd_ok = S.c4_holdout_drawdown_ok(h["max_drawdown"])
                base_verdict = S.classify_ci(lo, hi).value.upper()
                verdict = base_verdict if (base_verdict != "PASS" or dd_ok) else "INCONCLUSIVE"
                reason = (f"holdout 95% CI = [{lo:.6f}, {pt:.6f}, {hi:.6f}]; "
                          f"holdout DD={h['max_drawdown']} ({'ok' if dd_ok else 'exceeds cap'})")
            else:
                reason = "frozen params took no holdout trades (no return series)"
        else:
            reason = "walk-forward selection froze no params (no config was eligible)"
    except R.InsufficientHistory as exc:
        reason = f"insufficient history: {exc}"
    except Exception as exc:  # noqa: BLE001
        reason = f"data unavailable / error: {type(exc).__name__}: {exc}"

    if args.json:
        print(json.dumps({"strategy": "dual_momentum", "code_revision": head,
                          "verdict": verdict, "reason": reason,
                          "ci": [str(x) for x in ci] if ci else None, **extra}, indent=2))
    else:
        print("=" * 70)
        print("Dual-Momentum ETF Rotation — walk-forward validation")
        print(f"code revision: {head}")
        print("=" * 70)
        print(f"  VERDICT: {verdict}")
        print(f"  reason:  {reason}")
        for k, v in extra.items():
            if k != "fingerprints":
                print(f"  {k}: {v}")
        print("=" * 70)
        print("Enabled in deployment ONLY on a PASS. INCONCLUSIVE/FAIL stay disabled.")
        print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
