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
