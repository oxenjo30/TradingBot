"""Task 7 — Deterministic portfolio backtester core (spec §10.1–§10.3).

A single-asset-class, portfolio-aware, cost-aware, decimal-safe backtest engine
driven by explicit `HistoricalDataset` inputs (Task 6). This is backtest/research
infrastructure ONLY; it never touches the live trading engine.

Guarantees (spec §10):
  §10.1 Temporal integrity
    - The strategy sees only bars completed at the decision timestamp; the
      DecisionContext exposes bars up to AND INCLUDING the decision bar, never a
      future bar.
    - Orders fill strictly AFTER the signal timestamp: a signal emitted on the
      decision bar is queued and filled at the NEXT bar's open.
    - A future sentinel bar cannot change an earlier signal (the loop only ever
      reads past/current bars when deciding).
    - Any strategy exception or missing required data FAILS the run
      (`BacktestError`); it is never converted into a zero-signal "success".

  §10.2 Execution model
    - Next-bar open fills, adverse slippage, crypto maker/taker fee, quantity
      precision + minimum notional, adverse gap execution (the fill uses the
      next bar's actual open, including gaps), deterministic order priority,
      cash reservation for simultaneous orders, explicit rejection, and an
      explicit end-of-test liquidation/carry convention (reported in results).

  §10.3 Portfolio accounting (Decimal, unrounded)
    - Cash can never go negative (no margin): buys are reduced or rejected.
    - Simultaneous orders reserve cash BEFORE fills, in deterministic priority.
    - BOTH identities hold to the penny:
        account:     ending_cash + ending_market_value == ending_equity
        attribution: initial_equity + gross_realized + gross_unrealized
                     + income + external_flows
                     - entry_fees - exit_fees - other_costs == ending_equity
      Gross realized/unrealized EXCLUDE all fees/costs. Net lot P&L is a derived
      reporting value and is NEVER substituted into the gross identity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_DOWN
from enum import Enum

from . import backtest_metrics as metrics
from .historical import HistoricalDataset

D = Decimal


class BacktestError(Exception):
    """The backtest run is invalid: missing data, temporal violation, or a
    strategy exception. Never downgraded to a zero-signal success (spec §10.1)."""


class EndConvention(str, Enum):
    """How open positions at the end of the test are handled (reported)."""
    LIQUIDATE = "liquidate"   # close all at the final bar's close, realize P&L
    CARRY = "carry"           # leave open, mark to market at the final close


# ── cost model (§10.2) ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CostModel:
    """Per-side execution costs in decimal fractions (NOT basis points).

    `slippage` widens the fill adversely each way. `fee_rate` is a proportional
    broker fee charged on notional (crypto). Stock regulatory sell costs, when
    known, use `sell_fee_rate` (0 by default; assumptions are replaced by
    authoritative schedules where available — spec §10.2)."""
    slippage: Decimal = D("0")
    fee_rate: Decimal = D("0")
    sell_fee_rate: Decimal = D("0")

    @classmethod
    def zero(cls, asset_class: str = "stock") -> "CostModel":
        return cls(slippage=D("0"), fee_rate=D("0"), sell_fee_rate=D("0"))

    @classmethod
    def baseline(cls, asset_class: str) -> "CostModel":
        """Spec §10.2 baseline cost assumptions.

        Stocks: 10bps one-way slippage, no explicit per-share fee here.
        Crypto: 10bps fee + 5bps slippage each way."""
        ac = (asset_class or "").lower()
        if ac == "stock":
            return cls(slippage=D("0.001"), fee_rate=D("0"), sell_fee_rate=D("0"))
        if ac == "crypto":
            return cls(slippage=D("0.0005"), fee_rate=D("0.001"),
                       sell_fee_rate=D("0.001"))
        raise ValueError(f"unknown asset_class for cost baseline: {asset_class!r}")

    @classmethod
    def stress(cls, asset_class: str) -> "CostModel":
        """Spec §10.2 stressed cost assumptions."""
        ac = (asset_class or "").lower()
        if ac == "stock":
            return cls(slippage=D("0.002"), fee_rate=D("0"), sell_fee_rate=D("0"))
        if ac == "crypto":
            return cls(slippage=D("0.002"), fee_rate=D("0.002"),
                       sell_fee_rate=D("0.002"))
        raise ValueError(f"unknown asset_class for cost stress: {asset_class!r}")


# ── symbol trading spec (§10.2 precision / min notional) ─────────────────────────

@dataclass(frozen=True)
class SymbolSpec:
    """Exchange constraints: quantity precision and minimum notional."""
    qty_precision: int = 0            # decimal places allowed for quantity
    min_notional: Decimal = D("0")    # minimum order value; below → rejected

    def round_qty(self, qty: Decimal) -> Decimal:
        """Round quantity DOWN to the allowed precision (spec §19.5)."""
        if self.qty_precision <= 0:
            return qty.to_integral_value(rounding=ROUND_DOWN)
        quantum = D(1).scaleb(-self.qty_precision)
        return qty.quantize(quantum, rounding=ROUND_DOWN)


# ── order request from the strategy ──────────────────────────────────────────────

@dataclass(frozen=True)
class OrderRequest:
    """A backtest strategy's intent, emitted from a completed decision bar.

    Exactly one of `qty` / `notional` sizing is used; `qty` takes precedence."""
    symbol: str
    side: str  # "buy" | "sell"
    qty: Decimal | None = None
    notional: Decimal | None = None
    reason: str = ""


# ── config ────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: Decimal
    asset_class: str
    cost_model: CostModel
    symbols: dict[str, SymbolSpec] = field(default_factory=dict)
    end_convention: EndConvention = EndConvention.LIQUIDATE

    def spec_for(self, symbol: str) -> SymbolSpec:
        return self.symbols.get(symbol, SymbolSpec())


# ── decision context (§10.1) ─────────────────────────────────────────────────────

class DecisionContext:
    """Read-only view the strategy sees on a decision bar.

    Exposes bars completed up to and INCLUDING the decision bar (never future
    bars) and current owned positions. `bars(symbol)` returns the ascending list
    of completed bars; the last element is the decision bar itself."""

    def __init__(self, decision_date: date, completed_bars: dict[str, list[dict]],
                 positions: dict[str, Decimal], equity: Decimal = D("0")):
        self.decision_date = decision_date
        self._bars = completed_bars
        self._positions = positions
        self.equity = equity  # decision-time (last-close) portfolio equity

    @property
    def symbols(self) -> list[str]:
        return sorted(self._bars.keys())

    def bars(self, symbol: str) -> list[dict]:
        return self._bars.get(symbol, [])

    def position(self, symbol: str) -> Decimal:
        return self._positions.get(symbol, D("0"))

    @property
    def positions(self) -> dict[str, Decimal]:
        return dict(self._positions)


# ── result ────────────────────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    equity_curve: list[dict]
    trades: list[dict]
    fills: list[dict]
    rejections: list[dict]
    metrics: dict
    attribution: dict
    ending_cash: Decimal
    ending_market_value: Decimal
    ending_equity: Decimal
    end_convention: EndConvention


# ── internal lot ──────────────────────────────────────────────────────────────────

@dataclass
class _Lot:
    symbol: str
    qty: Decimal              # remaining quantity
    gross_entry: Decimal      # mid (pre-slippage) entry price per unit
    entry_date: str


# ── the engine ────────────────────────────────────────────────────────────────────

class PortfolioBacktester:
    """Deterministic portfolio backtester over explicit HistoricalDatasets."""

    def __init__(self, datasets: dict[str, HistoricalDataset], strategy,
                 config: BacktestConfig):
        self._datasets = datasets
        self._strategy = strategy
        self._cfg = config

    # ---- helpers ----

    def _bar_date(self, t: str) -> date:
        return date.fromisoformat(t[:10])

    def _cost(self) -> CostModel:
        return self._cfg.cost_model

    # ---- main ----

    def run(self) -> BacktestResult:
        cfg = self._cfg
        if not self._datasets:
            raise BacktestError("no datasets supplied to backtester")

        # Per-symbol ascending bars indexed by date. Datasets are already
        # validated + sorted by Task 6, but we re-key defensively.
        bars_by_symbol: dict[str, dict[date, dict]] = {}
        all_dates: set[date] = set()
        for sym, ds in self._datasets.items():
            if not ds.bars:
                raise BacktestError(f"empty dataset for {sym}")
            by_date: dict[date, dict] = {}
            for b in ds.bars:
                d = self._bar_date(b["t"])
                by_date[d] = b
                all_dates.add(d)
            bars_by_symbol[sym] = by_date

        calendar = sorted(all_dates)
        if not calendar:
            raise BacktestError("empty trading calendar")

        cash = D(str(cfg.initial_capital))
        lots: dict[str, list[_Lot]] = {}          # symbol -> FIFO lots
        pending: list[OrderRequest] = []          # queued from prior bar
        equity_curve: list[dict] = []
        fills: list[dict] = []
        rejections: list[dict] = []
        trades: list[dict] = []

        # accounting accumulators (fee/cost-free gross components) ------------
        gross_realized = D("0")
        entry_fees = D("0")
        exit_fees = D("0")
        other_costs = D("0")     # slippage drag on both sides
        income = D("0")          # dividends etc. (none in v1 core)
        external_flows = D("0")  # deposits/withdrawals (none in v1 core)
        total_costs = D("0")     # entry_fees + exit_fees + other_costs (report)

        # completed-bar history per symbol, grown as the loop advances -------
        completed: dict[str, list[dict]] = {s: [] for s in bars_by_symbol}
        last_close: dict[str, Decimal] = {}

        for cur in calendar:
            # ---- Step A: execute pending orders at THIS bar's open ----------
            # Fills happen strictly after the signal (queued on a prior bar).
            # Deterministic priority: process sells first so their proceeds are
            # available for cash reservation, then buys in symbol order.
            sells = [o for o in pending if o.side == "sell"]
            buys = [o for o in pending if o.side == "buy"]
            # deterministic ordering
            sells.sort(key=lambda o: o.symbol)
            buys.sort(key=lambda o: o.symbol)

            for order in sells:
                cash, realized, xfee, xslip = self._fill_sell(
                    order, cur, bars_by_symbol, lots, cash, fills, rejections,
                    trades,
                )
                gross_realized += realized
                exit_fees += xfee
                other_costs += xslip
                total_costs += xfee + xslip

            for order in buys:
                cash, efee, eslip = self._fill_buy(
                    order, cur, bars_by_symbol, lots, cash, fills, rejections,
                )
                entry_fees += efee
                other_costs += eslip
                total_costs += efee + eslip

            pending = []

            # ---- Step B: mark to market at THIS bar's close -----------------
            mkt_value = D("0")
            for sym, sym_lots in lots.items():
                bar = bars_by_symbol[sym].get(cur)
                if bar is not None:
                    last_close[sym] = D(str(bar["c"]))
                px = last_close.get(sym)
                if px is None:
                    # A held lot with no price anywhere is missing required data.
                    raise BacktestError(
                        f"missing price to mark {sym} on {cur}"
                    )
                qty_held = sum((l.qty for l in sym_lots), D("0"))
                mkt_value += qty_held * px

            # Also refresh last_close for symbols with a bar today (flat ones).
            for sym, by_date in bars_by_symbol.items():
                bar = by_date.get(cur)
                if bar is not None:
                    last_close[sym] = D(str(bar["c"]))

            equity = cash + mkt_value
            equity_curve.append({
                "date": cur.isoformat(),
                "cash": cash,
                "market_value": mkt_value,
                "equity": equity,
            })

            # ---- Step C: decision using ONLY completed bars -----------------
            for sym, by_date in bars_by_symbol.items():
                bar = by_date.get(cur)
                if bar is not None:
                    completed[sym].append(bar)

            positions = {
                sym: sum((l.qty for l in sym_lots), D("0"))
                for sym, sym_lots in lots.items()
                if sum((l.qty for l in sym_lots), D("0")) > 0
            }
            ctx = DecisionContext(cur, {s: list(v) for s, v in completed.items()
                                        if v}, positions, equity=equity)
            try:
                new_orders = self._strategy.evaluate(ctx)
            except BacktestError:
                raise
            except Exception as exc:  # strategy failure invalidates the run
                raise BacktestError(
                    f"strategy.evaluate raised on {cur}: {exc}"
                ) from exc
            if new_orders:
                pending.extend(new_orders)

        # ---- End convention (reported) -------------------------------------
        gross_unrealized = D("0")
        ending_market_value = D("0")
        final_date_str = calendar[-1].isoformat()

        if cfg.end_convention is EndConvention.LIQUIDATE:
            # Close all open lots at the final bar's close.
            for sym in sorted(lots.keys()):
                sym_lots = lots[sym]
                px = last_close.get(sym)
                if px is None:
                    raise BacktestError(f"cannot liquidate {sym}: no price")
                cost = self._cost()
                for lot in list(sym_lots):
                    if lot.qty <= 0:
                        continue
                    fill_px = px * (D("1") - cost.slippage)
                    proceeds = lot.qty * fill_px
                    fee = proceeds * cost.sell_fee_rate
                    slip = lot.qty * (px - fill_px)
                    cash += proceeds - fee
                    realized = lot.qty * (px - lot.gross_entry)
                    gross_realized += realized
                    exit_fees += fee
                    other_costs += slip
                    total_costs += fee + slip
                    trades.append({
                        "date": final_date_str,
                        "symbol": sym,
                        "side": "sell",
                        "qty": lot.qty,
                        "price": fill_px,
                        "gross_notional": proceeds,
                        "pnl": realized - fee - slip,   # NET (derived reporting)
                        "gross_pnl": realized,          # gross, fee-free
                        "holding_days": self._holding_days(
                            lot.entry_date, final_date_str),
                        "year": self._bar_date(final_date_str).year,
                    })
                sym_lots.clear()
            ending_market_value = D("0")
        else:  # CARRY
            for sym in sorted(lots.keys()):
                sym_lots = lots[sym]
                px = last_close.get(sym)
                if px is None:
                    raise BacktestError(f"cannot mark {sym}: no price")
                for lot in sym_lots:
                    if lot.qty <= 0:
                        continue
                    ending_market_value += lot.qty * px
                    gross_unrealized += lot.qty * (px - lot.gross_entry)

        ending_cash = cash
        ending_equity = ending_cash + ending_market_value

        attribution = {
            "initial_equity": D(str(cfg.initial_capital)),
            "gross_realized_pnl": gross_realized,
            "gross_unrealized_pnl": gross_unrealized,
            "income": income,
            "external_flows": external_flows,
            "entry_fees": entry_fees,
            "exit_fees": exit_fees,
            "other_costs": other_costs,
        }

        # per-symbol daily bars for gap-loss metric
        per_symbol_bars = {s: list(ds.bars) for s, ds in self._datasets.items()}

        m = metrics.compute_metrics(
            equity_curve=equity_curve,
            trades=trades,
            initial_equity=D(str(cfg.initial_capital)),
            ending_equity=ending_equity,
            asset_class=cfg.asset_class,
            per_symbol_bars=per_symbol_bars,
            total_costs=total_costs,
        )

        return BacktestResult(
            equity_curve=equity_curve,
            trades=trades,
            fills=fills,
            rejections=rejections,
            metrics=m,
            attribution=attribution,
            ending_cash=ending_cash,
            ending_market_value=ending_market_value,
            ending_equity=ending_equity,
            end_convention=cfg.end_convention,
        )

    # ---- fill primitives ----

    def _fill_buy(self, order, cur, bars_by_symbol, lots, cash, fills,
                  rejections):
        """Fill a buy at THIS bar's open with adverse slippage + fee, respecting
        cash (no negative cash), precision, and minimum notional.

        Returns (new_cash, entry_fee, entry_slippage_cost)."""
        cost = self._cost()
        spec = self._cfg.spec_for(order.symbol)
        bar = bars_by_symbol.get(order.symbol, {}).get(cur)
        if bar is None:
            rejections.append({"symbol": order.symbol, "side": "buy",
                               "date": cur.isoformat(), "reason": "no_bar"})
            return cash, D("0"), D("0")

        mid = D(str(bar["o"]))
        fill_px = mid * (D("1") + cost.slippage)
        if fill_px <= 0:
            rejections.append({"symbol": order.symbol, "side": "buy",
                               "date": cur.isoformat(), "reason": "bad_price"})
            return cash, D("0"), D("0")

        # requested quantity (qty precedence over notional)
        if order.qty is not None:
            want = D(str(order.qty))
        elif order.notional is not None:
            want = D(str(order.notional)) / fill_px
        else:
            want = D("0")
        want = spec.round_qty(want)
        if want <= 0:
            rejections.append({"symbol": order.symbol, "side": "buy",
                               "date": cur.isoformat(), "reason": "zero_qty"})
            return cash, D("0"), D("0")

        # Cash reservation: reduce qty until (qty*fill_px + fee) <= cash.
        # fee = qty * fill_px * fee_rate, so affordable notional solves:
        #   qty*fill_px*(1+fee_rate) <= cash
        max_notional = cash / (D("1") + cost.fee_rate)
        affordable = spec.round_qty(max_notional / fill_px)
        qty = min(want, affordable)
        if qty <= 0:
            rejections.append({"symbol": order.symbol, "side": "buy",
                               "date": cur.isoformat(),
                               "reason": "insufficient_cash"})
            return cash, D("0"), D("0")

        notional = qty * fill_px
        if notional < spec.min_notional:
            rejections.append({"symbol": order.symbol, "side": "buy",
                               "date": cur.isoformat(),
                               "reason": "min_notional"})
            return cash, D("0"), D("0")

        fee = notional * cost.fee_rate
        slip = qty * (fill_px - mid)
        cash = cash - notional - fee
        lots.setdefault(order.symbol, []).append(
            _Lot(symbol=order.symbol, qty=qty, gross_entry=mid,
                 entry_date=cur.isoformat()))
        fills.append({
            "symbol": order.symbol, "side": "buy", "date": cur.isoformat(),
            "qty": qty, "price": fill_px, "mid": mid, "fee": fee, "slippage": slip,
        })
        if qty < want:
            rejections.append({"symbol": order.symbol, "side": "buy",
                               "date": cur.isoformat(), "reason": "reduced",
                               "requested": want, "filled": qty})
        return cash, fee, slip

    def _fill_sell(self, order, cur, bars_by_symbol, lots, cash, fills,
                   rejections, trades):
        """Fill a sell at THIS bar's open (including adverse gaps) against owned
        FIFO lots only. Never sells more than owned.

        Returns (new_cash, gross_realized, exit_fee, exit_slippage_cost)."""
        cost = self._cost()
        spec = self._cfg.spec_for(order.symbol)
        sym_lots = lots.get(order.symbol, [])
        owned = sum((l.qty for l in sym_lots), D("0"))
        if owned <= 0:
            rejections.append({"symbol": order.symbol, "side": "sell",
                               "date": cur.isoformat(), "reason": "not_owned"})
            return cash, D("0"), D("0"), D("0")

        bar = bars_by_symbol.get(order.symbol, {}).get(cur)
        if bar is None:
            rejections.append({"symbol": order.symbol, "side": "sell",
                               "date": cur.isoformat(), "reason": "no_bar"})
            return cash, D("0"), D("0"), D("0")

        want = D(str(order.qty)) if order.qty is not None else owned
        qty = spec.round_qty(min(want, owned))
        if qty <= 0:
            rejections.append({"symbol": order.symbol, "side": "sell",
                               "date": cur.isoformat(), "reason": "zero_qty"})
            return cash, D("0"), D("0"), D("0")

        mid = D(str(bar["o"]))  # next-bar open, includes adverse gap
        fill_px = mid * (D("1") - cost.slippage)
        proceeds = qty * fill_px
        fee = proceeds * cost.sell_fee_rate
        slip = qty * (mid - fill_px)
        cash = cash + proceeds - fee

        # FIFO attribution against owned lots (spec §19.5: oldest lot first).
        remaining = qty
        realized = D("0")
        earliest_entry = None
        while remaining > 0 and sym_lots:
            lot = sym_lots[0]
            if earliest_entry is None:
                earliest_entry = lot.entry_date
            take = min(lot.qty, remaining)
            realized += take * (mid - lot.gross_entry)
            lot.qty -= take
            remaining -= take
            if lot.qty <= 0:
                sym_lots.pop(0)

        # net trade pnl (derived-only reporting value; NOT used in gross identity)
        net_pnl = realized - fee - slip
        holding_days = (self._holding_days(earliest_entry, cur.isoformat())
                        if earliest_entry else None)
        fills.append({
            "symbol": order.symbol, "side": "sell", "date": cur.isoformat(),
            "qty": qty, "price": fill_px, "mid": mid, "fee": fee, "slippage": slip,
        })
        trades.append({
            "date": cur.isoformat(),
            "symbol": order.symbol,
            "side": "sell",
            "qty": qty,
            "price": fill_px,
            "gross_notional": proceeds,
            "pnl": net_pnl,                 # NET (after this trade's costs)
            "gross_pnl": realized,          # gross realized for this close
            "holding_days": holding_days,
            "year": self._bar_date(cur.isoformat()).year,
        })
        return cash, realized, fee, slip

    def _holding_days(self, entry: str, exit_: str) -> int:
        return (date.fromisoformat(exit_[:10]) - date.fromisoformat(entry[:10])).days
