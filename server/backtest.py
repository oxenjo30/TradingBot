"""Backtest facade (Task 7).

`BacktestEngine.run(...)` keeps its legacy signature and legacy dict response so
the dashboard and existing `/api/backtest` clients are unaffected, but its
INTERNALS now delegate to the deterministic, decimal-safe, portfolio-aware
`PortfolioBacktester` (server/backtest_models.py) driven by explicit
`HistoricalDataset` inputs (server/historical.py).

What changed vs the old float engine:
  - Cash/positions are unrounded Decimal; cash can never go negative.
  - Fills are strictly next-bar open (no look-ahead); a future bar cannot change
    an earlier signal.
  - Costs (slippage as `slippage_pct`, commission as `commission_pct`) map onto
    the engine's CostModel and are applied adversely each way.
  - Reproducibility metadata (provider, timeframe, adjustment policy, data
    fingerprint, cost model, code revision, execution model, end convention) is
    persisted alongside the run.

What did NOT change:
  - The response dict shape: total_return_pct, max_drawdown_pct, win_rate_pct,
    sharpe_ratio, total_trades, equity_curve, trades, symbol_breakdown, id.
  - Legacy strategy contract: strategies still implement `evaluate(positions)`
    and read bars via the alpaca_client `_bt` thread-local (completed bars only).
  - Legacy position sizing: each buy uses `position_size_pct` of decision-time
    portfolio equity.
  - This is backtest-only; the live trading engine is untouched.
"""
from __future__ import annotations

import logging
import subprocess
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN

from . import alpaca_client, db
from . import strategies as strat_mod
from .backtest_models import (
    PortfolioBacktester, BacktestConfig, CostModel, OrderRequest,
    EndConvention, BacktestError,
)
from .historical import (
    AssetClass, AdjustmentPolicy, HistoricalRequest, HistoricalDataset,
)

log = logging.getLogger(__name__)

D = Decimal


def _q2(x: Decimal) -> float:
    """Round a Decimal to 2 dp (reporting only) and return a float."""
    return float(x.quantize(D("0.01"), rounding=ROUND_HALF_EVEN))


def _q4(x: Decimal) -> float:
    return float(x.quantize(D("0.0001"), rounding=ROUND_HALF_EVEN))


def _code_revision() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


class _LegacyStrategyAdapter:
    """Bridges a legacy `Strategy.evaluate(positions)` to the new engine.

    On each decision bar it exposes the completed-bar window through the
    alpaca_client `_bt` thread-local (so legacy strategies fetch only bars
    completed at the decision timestamp — no look-ahead), calls the legacy
    strategy, and translates each `Signal` into an `OrderRequest`. Buys are sized
    to `position_size_pct` of decision-time equity (legacy behavior)."""

    def __init__(self, strategy, all_bars: dict[str, list[dict]],
                 position_size_pct: float):
        self._strategy = strategy
        self._all_bars = all_bars
        self._pct = D(str(position_size_pct)) / D("100")

    def evaluate(self, ctx):
        # Point the legacy bar-fetch at the completed-bar window for this date.
        alpaca_client._bt.bars = self._all_bars
        alpaca_client._bt.current_date = ctx.decision_date
        try:
            simple_positions = {s: float(q) for s, q in ctx.positions.items()}
            signals = self._strategy.evaluate(simple_positions)
        finally:
            alpaca_client._bt.bars = None
            alpaca_client._bt.current_date = None

        orders: list[OrderRequest] = []
        equity = ctx.equity
        for sig in signals:
            sym = sig.symbol.upper()
            if sig.side == "buy":
                if ctx.position(sym) > 0:
                    continue  # no pyramiding in the legacy facade
                notional = equity * self._pct
                if notional <= 0:
                    continue
                orders.append(OrderRequest(sym, "buy", notional=notional,
                                           reason=sig.reason))
            elif sig.side == "sell":
                if ctx.position(sym) <= 0:
                    continue
                orders.append(OrderRequest(sym, "sell",
                                           qty=ctx.position(sym),
                                           reason=sig.reason))
        return orders


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
        strategy_params: dict | None = None,
    ) -> dict:
        if strategy_name not in strat_mod.REGISTRY:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        symbols_up = [s.upper() for s in symbols]

        # 1. Fetch full history (extra 200-day buffer for strategy lookbacks).
        lookback_days = (end_date - start_date).days + 200
        all_bars: dict[str, list[dict]] = {}
        datasets: dict[str, HistoricalDataset] = {}
        for sym in symbols_up:
            try:
                bars = alpaca_client.get_recent_bars(sym, days=lookback_days)
            except KeyError:
                raise ValueError(
                    f"No historical data found for {sym} in the given date range")
            in_range = [b for b in bars
                        if start_date.isoformat() <= b["t"][:10] <= end_date.isoformat()]
            if not in_range:
                raise ValueError(
                    f"No historical data found for {sym} in the given date range")
            all_bars[sym] = sorted(bars, key=lambda b: b["t"])
            # Dataset carries only the in-range window for the deterministic loop;
            # the lookback buffer stays available to strategies via `all_bars`.
            windowed = sorted(in_range, key=lambda b: b["t"])
            req = HistoricalRequest(
                asset_class=AssetClass.STOCK,
                provider="alpaca",
                symbol=sym,
                start=date.fromisoformat(windowed[0]["t"][:10]),
                end=date.fromisoformat(windowed[-1]["t"][:10]),
                timeframe="1D",
                adjustment=AdjustmentPolicy.RAW,
            )
            datasets[sym] = HistoricalDataset(
                request=req, bars=windowed,
                retrieved_at=_now_iso(),
            )

        # 2. Instantiate the legacy strategy restricted to the requested symbols.
        build_params = dict(strategy_params or {})
        build_params.update({"symbols": symbols_up, "use_scanner": False})
        strategy = strat_mod.build(strategy_name, build_params)
        adapter = _LegacyStrategyAdapter(strategy, all_bars, position_size_pct)

        # 3. Cost model from legacy pct params (applied adversely each way).
        cost = CostModel(
            slippage=D(str(slippage_pct)) / D("100"),
            fee_rate=D(str(commission_pct)) / D("100"),
            sell_fee_rate=D(str(commission_pct)) / D("100"),
        )
        cfg = BacktestConfig(
            initial_capital=D(str(initial_capital)),
            asset_class="stock",
            cost_model=cost,
            symbols={},
            end_convention=EndConvention.LIQUIDATE,
        )

        # 4. Run the deterministic engine. Any invalidation fails the run.
        try:
            res = PortfolioBacktester(datasets, adapter, cfg).run()
        except BacktestError as exc:
            raise ValueError(str(exc)) from exc

        # 5. Project the rich result to the legacy dict shape.
        m = res.metrics
        equity_curve = [
            {"date": pt["date"], "equity": _q2(pt["equity"])}
            for pt in res.equity_curve
        ]
        trades = [
            {
                "date": t["date"],
                "symbol": t["symbol"],
                "side": t["side"],
                "qty": float(t["qty"]),
                "price": _q4(t["price"]),
                "pnl": _q4(t["pnl"]),
            }
            for t in res.trades
        ]
        total_return_pct = _q4(m["net_return"] * D("100"))
        max_drawdown_pct = _q4(m["max_drawdown"] * D("100"))
        win_rate_pct = (
            _q2(m["win_rate"] * D("100")) if m["win_rate"] is not None else None
        )
        sharpe_ratio = _q4(m["sharpe_ratio"])

        # Per-symbol breakdown (legacy shape) from the metrics by_symbol rows.
        symbol_breakdown = []
        for row in m["by_symbol"]:
            n = row["trades"]
            symbol_breakdown.append({
                "symbol": row["symbol"],
                "trades": n,
                "wins": row["wins"],
                "win_rate_pct": (round(row["wins"] / n * 100, 1) if n else 0.0),
                "total_pnl": _q2(row["total_pnl"]),
            })

        result: dict = {
            "total_return_pct": total_return_pct,
            "max_drawdown_pct": max_drawdown_pct,
            "win_rate_pct": win_rate_pct,
            "sharpe_ratio": sharpe_ratio,
            "total_trades": m["total_trades"],
            "equity_curve": equity_curve,
            "trades": trades,
            "symbol_breakdown": symbol_breakdown,
        }

        # 6. Reproducibility metadata (spec §9/§10).
        reproducibility = {
            "provider": "alpaca",
            "asset_class": "stock",
            "timeframe": "1D",
            "adjustment": AdjustmentPolicy.RAW.value,
            "as_of_policy": "point_in_time",
            "data_fingerprints": {s: ds.fingerprint for s, ds in datasets.items()},
            "code_revision": _code_revision(),
            "cost_model": {
                "slippage": str(cost.slippage),
                "fee_rate": str(cost.fee_rate),
                "sell_fee_rate": str(cost.sell_fee_rate),
                "commission_pct": commission_pct,
                "slippage_pct": slippage_pct,
            },
            "execution_model": "next_bar_open_adverse_slippage",
            "end_convention": res.end_convention.value,
            "account_identity_balanced": bool(
                res.ending_cash + res.ending_market_value == res.ending_equity),
            "attribution": {k: str(v) for k, v in res.attribution.items()},
            "annualization": m["annualization"],
        }
        result["reproducibility"] = reproducibility

        # 7. Persist and attach id.
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


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
