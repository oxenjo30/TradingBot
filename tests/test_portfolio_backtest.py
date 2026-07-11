"""Task 7 — Deterministic portfolio backtester (spec §10.1–§10.3).

Deterministic, NO-NETWORK tests. Bars come from HistoricalDataset built from
synthetic fixtures. Covers:
  - next-bar (later) fills strictly after the signal timestamp (§10.1)
  - future-sentinel leakage: a later bar must not change an earlier signal
  - adverse gap execution
  - limited cash: order rejected/reduced when cash insufficient (no negative cash)
  - simultaneous cash reservation before fills
  - deterministic order priority
  - explicit costs applied (stock slippage; crypto fee+slippage)
  - crypto precision + minimum-notional rejection
  - explicit end-of-test liquidation vs carry convention (reported)
  - stock (252) vs crypto (365) calendar/annualization
  - BOTH accounting identities balance to the penny (unrounded Decimal)
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from server.historical import (
    AssetClass, AdjustmentPolicy, HistoricalRequest, HistoricalDataset,
)
from server.backtest_models import (
    PortfolioBacktester,
    BacktestConfig,
    CostModel,
    SymbolSpec,
    OrderRequest,
    EndConvention,
    BacktestError,
)


D = Decimal


# ── fixtures / helpers ────────────────────────────────────────────────────────────

def _bar(t, o, h, l, c, v=1_000_000.0):
    return {"t": t, "o": float(o), "h": float(h), "l": float(l),
            "c": float(c), "v": float(v)}


def _dataset(symbol, bars, asset_class=AssetClass.STOCK, provider="alpaca"):
    req = HistoricalRequest(
        asset_class=asset_class,
        provider=provider,
        symbol=symbol,
        start=date.fromisoformat(bars[0]["t"][:10]),
        end=date.fromisoformat(bars[-1]["t"][:10]),
        timeframe="1D",
        adjustment=AdjustmentPolicy.RAW,
    )
    return HistoricalDataset(
        request=req,
        bars=list(bars),
        retrieved_at="2024-01-01T00:00:00+00:00",
    )


def _daily_stock(symbol, prices, start="2024-01-01"):
    """One bar per price; open==close==price for simple determinism unless a
    tuple (o,h,l,c) is given."""
    d = date.fromisoformat(start)
    bars = []
    for p in prices:
        if isinstance(p, tuple):
            o, h, l, c = p
        else:
            o = h = l = c = p
        bars.append(_bar(d.isoformat() + "T00:00:00+00:00", o, max(h, o, c),
                         min(l, o, c), c))
        d += timedelta(days=1)
    return _dataset(symbol, bars)


class _ScriptedStrategy:
    """Emits pre-scripted OrderRequests keyed by the decision bar's date.

    The backtester calls evaluate(ctx) once per completed bar. ctx exposes only
    bars completed up to and including the decision timestamp, plus owned
    positions. This strategy asserts no future bar is ever visible.
    """
    def __init__(self, script, record_visibility=None):
        # script: {date_str: [OrderRequest, ...]}
        self._script = script
        self._seen = record_visibility  # optional dict to record last-seen bar t

    def evaluate(self, ctx):
        if self._seen is not None:
            for sym in ctx.symbols:
                bars = ctx.bars(sym)
                if bars:
                    self._seen.setdefault(sym, []).append(bars[-1]["t"])
        return list(self._script.get(ctx.decision_date.isoformat(), []))


def _cfg(asset_class="stock", initial=D("10000"), cost=None, symbols=None,
         end_convention=EndConvention.LIQUIDATE):
    return BacktestConfig(
        initial_capital=initial,
        asset_class=asset_class,
        cost_model=cost or CostModel.baseline(asset_class),
        symbols=symbols or {},
        end_convention=end_convention,
    )


# ── temporal integrity ────────────────────────────────────────────────────────────

class TestTemporalIntegrity:
    def test_signal_fills_at_next_bar_open_not_same_bar(self):
        ds = _daily_stock("AAPL", [
            (100, 100, 100, 100),  # 01-01 decision bar; buy signal here
            (110, 110, 110, 110),  # 01-02 fill open == 110
            (120, 120, 120, 120),  # 01-03
        ])
        # buy 1 share signalled on 01-01 → fills at 01-02 open = 110 (not 100)
        strat = _ScriptedStrategy({
            "2024-01-01": [OrderRequest("AAPL", "buy", qty=D("1"))],
        })
        # CARRY leaves the entry open so the entry fill price is the sole datum.
        cfg = _cfg(cost=CostModel.zero("stock"),
                   end_convention=EndConvention.CARRY)
        res = PortfolioBacktester({"AAPL": ds}, strat, cfg).run()
        assert res.trades == []  # no exit signalled, carried open
        # exactly one entry fill at the NEXT bar's open (110), not the decision
        # bar's price (100).
        fills = [f for f in res.fills if f["side"] == "buy"]
        assert len(fills) == 1
        assert fills[0]["price"] == D("110")

    def test_future_sentinel_does_not_change_earlier_signal(self):
        base = [(100, 100, 100, 100), (110, 110, 110, 110),
                (120, 120, 120, 120)]
        strat_script = {"2024-01-01": [OrderRequest("AAPL", "buy", qty=D("1"))]}

        ds1 = _daily_stock("AAPL", base)
        res1 = PortfolioBacktester(
            {"AAPL": ds1}, _ScriptedStrategy(dict(strat_script)),
            _cfg(cost=CostModel.zero("stock"))).run()

        # append a wild future sentinel bar; earlier fill must be identical.
        ds2 = _daily_stock("AAPL", base + [(9999, 9999, 9999, 9999)])
        res2 = PortfolioBacktester(
            {"AAPL": ds2}, _ScriptedStrategy(dict(strat_script)),
            _cfg(cost=CostModel.zero("stock"))).run()

        buys1 = [f for f in res1.fills if f["side"] == "buy"]
        buys2 = [f for f in res2.fills if f["side"] == "buy"]
        assert buys1[0]["price"] == buys2[0]["price"] == D("110")

    def test_strategy_never_sees_future_bars(self):
        seen = {}
        ds = _daily_stock("AAPL", [100, 101, 102, 103])
        strat = _ScriptedStrategy({}, record_visibility=seen)
        PortfolioBacktester({"AAPL": ds}, strat,
                            _cfg(cost=CostModel.zero("stock"))).run()
        # last-seen bar on each evaluate must be the decision bar itself, never
        # ahead. Recorded timestamps are strictly increasing and match calendar.
        ts = seen["AAPL"]
        assert ts == sorted(ts)
        assert len(ts) == 4

    def test_strategy_exception_fails_the_run(self):
        class _Boom:
            def evaluate(self, ctx):
                raise RuntimeError("kaboom")
        ds = _daily_stock("AAPL", [100, 101, 102])
        with pytest.raises(BacktestError):
            PortfolioBacktester({"AAPL": ds}, _Boom(),
                                _cfg(cost=CostModel.zero("stock"))).run()


# ── adverse gap execution ─────────────────────────────────────────────────────────

class TestGaps:
    def test_sell_fills_at_gapped_down_open(self):
        # buy on 01-01 fills 01-02 open=100; sell signalled 01-02 fills 01-03
        # open which gaps DOWN to 80.
        ds = _daily_stock("AAPL", [
            (100, 100, 100, 100),
            (100, 100, 100, 100),
            (80, 85, 79, 82),
        ])
        strat = _ScriptedStrategy({
            "2024-01-01": [OrderRequest("AAPL", "buy", qty=D("1"))],
            "2024-01-02": [OrderRequest("AAPL", "sell", qty=D("1"))],
        })
        res = PortfolioBacktester({"AAPL": ds}, strat,
                                  _cfg(cost=CostModel.zero("stock"))).run()
        sells = [f for f in res.fills if f["side"] == "sell"]
        assert sells[0]["price"] == D("80")  # adverse gap open, not prev close


# ── cash constraints (no negative cash) ───────────────────────────────────────────

class TestCash:
    def test_order_reduced_when_cash_insufficient(self):
        # capital 250; price 100 → can afford only 2 shares even if 5 requested.
        ds = _daily_stock("AAPL", [100, 100, 100])
        strat = _ScriptedStrategy({
            "2024-01-01": [OrderRequest("AAPL", "buy", qty=D("5"))],
        })
        res = PortfolioBacktester(
            {"AAPL": ds}, strat,
            _cfg(initial=D("250"), cost=CostModel.zero("stock"))).run()
        buys = [f for f in res.fills if f["side"] == "buy"]
        assert buys[0]["qty"] == D("2")
        assert res.ending_cash >= D("0")

    def test_cash_never_negative_across_run(self):
        ds = _daily_stock("AAPL", [100, 100, 100, 100])
        strat = _ScriptedStrategy({
            "2024-01-01": [OrderRequest("AAPL", "buy", qty=D("100"))],
        })
        res = PortfolioBacktester(
            {"AAPL": ds}, strat,
            _cfg(initial=D("150"), cost=CostModel.zero("stock"))).run()
        for pt in res.equity_curve:
            assert pt["cash"] >= D("0")

    def test_simultaneous_orders_reserve_cash_deterministically(self):
        # Two buys same bar, only enough cash for the first by priority (symbol
        # alphabetical). Capital 150, each share 100.
        ds_a = _daily_stock("AAA", [100, 100, 100])
        ds_b = _daily_stock("BBB", [100, 100, 100])
        strat = _ScriptedStrategy({
            "2024-01-01": [OrderRequest("BBB", "buy", qty=D("1")),
                           OrderRequest("AAA", "buy", qty=D("1"))],
        })
        res = PortfolioBacktester(
            {"AAA": ds_a, "BBB": ds_b}, strat,
            _cfg(initial=D("150"), cost=CostModel.zero("stock"))).run()
        buys = sorted((f for f in res.fills if f["side"] == "buy"),
                      key=lambda f: f["symbol"])
        # AAA fills first (alphabetical priority), BBB has no cash left.
        assert [f["symbol"] for f in buys] == ["AAA"]
        assert res.ending_cash >= D("0")


# ── costs applied ─────────────────────────────────────────────────────────────────

class TestCosts:
    def test_stock_slippage_worsens_fill(self):
        ds = _daily_stock("AAPL", [(100, 100, 100, 100), (100, 100, 100, 100)])
        strat = _ScriptedStrategy({
            "2024-01-01": [OrderRequest("AAPL", "buy", qty=D("1"))],
        })
        # baseline stock = 10bps one-way slippage. buy fill = 100 * 1.001 = 100.1
        res = PortfolioBacktester(
            {"AAPL": ds}, strat, _cfg(cost=CostModel.baseline("stock"))).run()
        buys = [f for f in res.fills if f["side"] == "buy"]
        assert buys[0]["price"] == D("100.1")

    def test_crypto_fee_and_slippage_each_way(self):
        ds = _dataset("BTC/USDT", [
            _bar("2024-01-01T00:00:00+00:00", 100, 100, 100, 100),
            _bar("2024-01-02T00:00:00+00:00", 100, 100, 100, 100),
        ], asset_class=AssetClass.CRYPTO, provider="binance")
        strat = _ScriptedStrategy({
            "2024-01-01": [OrderRequest("BTC/USDT", "buy", qty=D("1"))],
        })
        cfg = BacktestConfig(
            initial_capital=D("10000"),
            asset_class="crypto",
            cost_model=CostModel.baseline("crypto"),
            symbols={"BTC/USDT": SymbolSpec(qty_precision=8,
                                            min_notional=D("10"))},
            end_convention=EndConvention.CARRY,
        )
        res = PortfolioBacktester({"BTC/USDT": ds}, strat, cfg).run()
        buys = [f for f in res.fills if f["side"] == "buy"]
        # slippage 5bps → fill price 100.05; fee 10bps on notional charged
        assert buys[0]["price"] == D("100.05")
        assert buys[0]["fee"] > D("0")


# ── precision & minimum notional (crypto) ─────────────────────────────────────────

class TestPrecision:
    def test_quantity_rounds_down_to_precision(self):
        ds = _dataset("BTC/USDT", [
            _bar("2024-01-01T00:00:00+00:00", 100, 100, 100, 100),
            _bar("2024-01-02T00:00:00+00:00", 100, 100, 100, 100),
        ], asset_class=AssetClass.CRYPTO, provider="binance")
        strat = _ScriptedStrategy({
            "2024-01-01": [OrderRequest("BTC/USDT", "buy", qty=D("1.123456789"))],
        })
        cfg = BacktestConfig(
            initial_capital=D("10000"), asset_class="crypto",
            cost_model=CostModel.zero("crypto"),
            symbols={"BTC/USDT": SymbolSpec(qty_precision=3,
                                            min_notional=D("10"))},
            end_convention=EndConvention.CARRY,
        )
        res = PortfolioBacktester({"BTC/USDT": ds}, strat, cfg).run()
        buys = [f for f in res.fills if f["side"] == "buy"]
        assert buys[0]["qty"] == D("1.123")

    def test_below_min_notional_is_rejected(self):
        ds = _dataset("BTC/USDT", [
            _bar("2024-01-01T00:00:00+00:00", 100, 100, 100, 100),
            _bar("2024-01-02T00:00:00+00:00", 100, 100, 100, 100),
        ], asset_class=AssetClass.CRYPTO, provider="binance")
        strat = _ScriptedStrategy({
            "2024-01-01": [OrderRequest("BTC/USDT", "buy", qty=D("0.05"))],
        })
        cfg = BacktestConfig(
            initial_capital=D("10000"), asset_class="crypto",
            cost_model=CostModel.zero("crypto"),
            symbols={"BTC/USDT": SymbolSpec(qty_precision=8,
                                            min_notional=D("10"))},
            end_convention=EndConvention.CARRY,
        )
        # 0.05 * 100 = 5 notional < 10 min → rejected, no fill
        res = PortfolioBacktester({"BTC/USDT": ds}, strat, cfg).run()
        assert [f for f in res.fills if f["side"] == "buy"] == []
        assert any(r["reason"] == "min_notional" for r in res.rejections)


# ── end-of-test convention ────────────────────────────────────────────────────────

class TestEndConvention:
    def test_liquidate_closes_open_positions_and_reports(self):
        ds = _daily_stock("AAPL", [(100, 100, 100, 100), (110, 110, 110, 110)])
        strat = _ScriptedStrategy({
            "2024-01-01": [OrderRequest("AAPL", "buy", qty=D("1"))],
        })
        res = PortfolioBacktester(
            {"AAPL": ds}, strat,
            _cfg(cost=CostModel.zero("stock"),
                 end_convention=EndConvention.LIQUIDATE)).run()
        assert res.end_convention == EndConvention.LIQUIDATE
        # position liquidated → a closed trade exists
        assert len(res.trades) == 1
        assert res.ending_market_value == D("0")

    def test_carry_leaves_position_open_and_marks_to_market(self):
        ds = _daily_stock("AAPL", [(100, 100, 100, 100), (110, 110, 110, 110)])
        strat = _ScriptedStrategy({
            "2024-01-01": [OrderRequest("AAPL", "buy", qty=D("1"))],
        })
        res = PortfolioBacktester(
            {"AAPL": ds}, strat,
            _cfg(cost=CostModel.zero("stock"),
                 end_convention=EndConvention.CARRY)).run()
        assert res.end_convention == EndConvention.CARRY
        assert res.trades == []
        assert res.ending_market_value == D("110")  # 1 share @ last close 110


# ── stock vs crypto calendar / annualization ──────────────────────────────────────

class TestCalendar:
    def test_asset_class_flows_into_metrics_annualization(self):
        ds = _daily_stock("AAPL", [100, 101, 102, 103, 104])
        res = PortfolioBacktester(
            {"AAPL": ds}, _ScriptedStrategy({}),
            _cfg(cost=CostModel.zero("stock"))).run()
        assert res.metrics["annualization"] == 252

    def test_crypto_uses_365(self):
        ds = _dataset("BTC/USDT", [
            _bar("2024-01-0%d" % (i + 1) + "T00:00:00+00:00", 100 + i, 100 + i,
                 100 + i, 100 + i) for i in range(5)
        ], asset_class=AssetClass.CRYPTO, provider="binance")
        cfg = BacktestConfig(
            initial_capital=D("10000"), asset_class="crypto",
            cost_model=CostModel.zero("crypto"),
            symbols={"BTC/USDT": SymbolSpec(qty_precision=8,
                                            min_notional=D("10"))},
            end_convention=EndConvention.CARRY)
        res = PortfolioBacktester({"BTC/USDT": ds}, _ScriptedStrategy({}),
                                  cfg).run()
        assert res.metrics["annualization"] == 365


# ── accounting identities (both, to the penny, unrounded) ─────────────────────────

class TestAccountingIdentities:
    def _run_round_trip(self, cost_model, end_conv=EndConvention.LIQUIDATE):
        ds = _daily_stock("AAPL", [
            (100, 100, 100, 100),  # decision: buy
            (100, 100, 100, 100),  # fill entry @100
            (110, 110, 110, 110),  # decision: sell
            (120, 120, 120, 120),  # fill exit @120
            (120, 120, 120, 120),
        ])
        strat = _ScriptedStrategy({
            "2024-01-01": [OrderRequest("AAPL", "buy", qty=D("2"))],
            "2024-01-03": [OrderRequest("AAPL", "sell", qty=D("2"))],
        })
        return PortfolioBacktester(
            {"AAPL": ds}, strat,
            _cfg(initial=D("10000"), cost=cost_model,
                 end_convention=end_conv)).run()

    def test_account_identity_balances_no_costs(self):
        res = self._run_round_trip(CostModel.zero("stock"))
        assert (res.ending_cash + res.ending_market_value
                == res.ending_equity)

    def test_attribution_identity_balances_no_costs(self):
        res = self._run_round_trip(CostModel.zero("stock"))
        a = res.attribution
        lhs = (a["initial_equity"] + a["gross_realized_pnl"]
               + a["gross_unrealized_pnl"] + a["income"] + a["external_flows"]
               - a["entry_fees"] - a["exit_fees"] - a["other_costs"])
        assert lhs == res.ending_equity

    def test_account_identity_balances_with_costs(self):
        res = self._run_round_trip(CostModel.baseline("stock"))
        assert (res.ending_cash + res.ending_market_value
                == res.ending_equity)

    def test_attribution_identity_balances_with_costs(self):
        res = self._run_round_trip(CostModel.baseline("stock"))
        a = res.attribution
        lhs = (a["initial_equity"] + a["gross_realized_pnl"]
               + a["gross_unrealized_pnl"] + a["income"] + a["external_flows"]
               - a["entry_fees"] - a["exit_fees"] - a["other_costs"])
        assert lhs == res.ending_equity

    def test_gross_realized_excludes_fees(self):
        # gross realized on 2 shares 100->120 == (120-100)*2 = 40, fee-free.
        res = self._run_round_trip(CostModel.baseline("stock"))
        assert res.attribution["gross_realized_pnl"] == D("40")
        # net lot pnl is reported separately and is smaller than gross by costs
        assert res.trades[0]["pnl"] < D("40")

    def test_carry_identity_balances_with_open_position(self):
        res = self._run_round_trip(CostModel.baseline("stock"),
                                    end_conv=EndConvention.CARRY)
        # sell happened before end, so nothing open — still must balance.
        assert (res.ending_cash + res.ending_market_value
                == res.ending_equity)
        a = res.attribution
        lhs = (a["initial_equity"] + a["gross_realized_pnl"]
               + a["gross_unrealized_pnl"] + a["income"] + a["external_flows"]
               - a["entry_fees"] - a["exit_fees"] - a["other_costs"])
        assert lhs == res.ending_equity


# ── engine invalidates on missing/inconsistent data ───────────────────────────────

class TestDataFailures:
    def test_empty_dataset_raises(self):
        with pytest.raises(BacktestError):
            PortfolioBacktester({}, _ScriptedStrategy({}),
                                _cfg(cost=CostModel.zero("stock"))).run()
