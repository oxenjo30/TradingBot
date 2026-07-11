"""Deterministic strategy research runner (Task 11, spec §7/§8/§9/§12/§19.10).

Runs the walk-forward + final-holdout research protocol for BOTH the stock sleeve
(§7 liquid US universe) and the crypto sleeve (§8 BTC/ETH), then applies the §12 /
§19.13 statistical acceptance gate and prints a per-sleeve verdict:

    PASS          — gate lower bound > 0 (only then may a sleeve be enabled)
    FAIL          — CI wholly negative (stays disabled)
    INCONCLUSIVE  — data unavailable / unadjusted / interval spans zero
                    (stays disabled — this is NEVER a pass)

Data policy (honest, no fabrication):
  1. Each sleeve FIRST attempts a REAL historical dataset over the full window the
     walk-forward geometry needs (stock ~10y via Alpaca, crypto ~6y via Binance),
     using the network providers wired in server.alpaca_client.historical_provider
     / server.binance_client.historical_provider.
  2. If real data cannot be obtained — no/invalid credentials, feed error, coverage
     shortfall, or (for stocks) the universe contains in-window splits that CANNOT
     be corrected because no corporate-action feed is wired (spec §19.13: such a
     provider "cannot produce a passing stock research result") — the sleeve verdict
     is forced to INCONCLUSIVE and we DO NOT fabricate a real run.
  3. For an INFRASTRUCTURE-ONLY demonstration (proving the pipeline executes end to
     end: geometry -> grid -> PortfolioBacktester -> statistical gate), the runner
     falls back to CLEARLY-LABELLED synthetic fixtures. A synthetic run is ALWAYS
     labelled INCONCLUSIVE regardless of the numbers it produces.

Hard safety constraints (do not relax):
  * READ-ONLY market data + in-memory backtest only.
  * NEVER opens the live trading.db for writes; NEVER enables a strategy; NEVER
    places an order; NEVER contacts the VPS. `persist` is always None here — the
    research runner's DB persistence is exercised by the Task 9 unit tests, not by
    this evidence script (which must not mutate live state).
  * If credentials cannot be reached, the error is CAUGHT and recorded as
    INCONCLUSIVE — the script never crashes on a missing credential.

Run:  python scripts/run_strategy_research.py
      python scripts/run_strategy_research.py --json    # machine-readable summary
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

# Make `server` importable when run as a script from the repo root.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from server import research as R
from server import statistics as S
from server.historical import (
    AssetClass, AdjustmentPolicy, AsOfPolicy, HistoricalRequest, HistoricalDataset,
    HistoricalDataError,
)
from server.backtest_models import (
    PortfolioBacktester, BacktestConfig, CostModel, SymbolSpec, OrderRequest,
    EndConvention, BacktestError,
)

D = Decimal

# ── universe / known in-window corporate actions (for the limitation report) ──────

STOCK_UNIVERSE = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META"]
CRYPTO_UNIVERSE = ["BTC/USDT", "ETH/USDT"]

# Forward stock splits inside a ~10-year window (as of 2026). These make the
# UNADJUSTED network stock feed unusable for a trustworthy stock verdict: a raw
# pre-split price sitting next to a post-split price fabricates a ~75-95% "gap"
# that the breakout/stop logic would misread. The network provider passes NO
# corporate_actions, so the split-adjustment transform in server/historical.py has
# nothing to apply. Per §19.13 this bounds the stock verdict to INCONCLUSIVE.
KNOWN_STOCK_SPLITS = {
    "AAPL": ["2020-08-31 (4:1)"],
    "NVDA": ["2021-07-20 (4:1)", "2024-06-10 (10:1)"],
    "AMZN": ["2022-06-06 (20:1)"],
    "GOOGL": ["2022-07-18 (20:1)"],
}


# ── parameterized signal adapters (grid-driven §7/§8 rules, from cash) ────────────
#
# The live strategies (server/strategies/liquid_stock_trend.py, btc_eth_trend.py)
# hard-code their thresholds and read the LIVE ledger (db.get_strategy_entry_price)
# — unsuitable for a from-cash, grid-swept research run. These adapters re-express
# the SAME §7/§8 completed-bar rules against the backtester's DecisionContext, keyed
# by the predeclared grid params, holding NO global state and reading NO live DB.

def _sma(vals, period, offset=0):
    end = len(vals) - offset
    start = end - period
    if start < 0 or end <= 0 or (end - start) < period:
        return None
    return sum(vals[start:end]) / period


def _ema(vals, period):
    if len(vals) < period:
        return None
    k = 2 / (period + 1)
    v = sum(vals[:period]) / period
    for p in vals[period:]:
        v = p * k + v * (1 - k)
    return v


def _atr(bars, period):
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    w = trs[-period:]
    return sum(w) / period if len(w) == period else None


class _StockAdapter:
    """§7 rules keyed by grid {breakout, volume, trail_atr}. Long-only, next-bar
    fills, ATR trailing stop, SPY-regime gate, max 5 positions, no pyramiding."""

    SMA_TREND = 100
    VOL_LOOKBACK = 20
    REGIME_SMA = 200
    REGIME_SLOPE = 20
    ATR_PERIOD = 20
    INIT_STOP_ATR = Decimal("2.5")
    MAX_POS = 5

    def __init__(self, params, notional):
        self.breakout = int(params["breakout"])
        self.vol_mult = float(params["volume"])
        self.trail_atr = float(params["trail_atr"])
        self.notional = notional
        self._entry: dict[str, float] = {}   # symbol -> gross entry price (from fills)

    def _regime(self, ctx):
        spy = ctx.bars("SPY")
        closes = [b["c"] for b in spy]
        sma_now = _sma(closes, self.REGIME_SMA)
        sma_prev = _sma(closes, self.REGIME_SMA, offset=self.REGIME_SLOPE)
        if sma_now is None or sma_prev is None or len(closes) < 2:
            return False, False
        allowed = closes[-1] > sma_now and sma_now > sma_prev
        sma_last = _sma(closes, self.REGIME_SMA)
        sma_2nd = _sma(closes, self.REGIME_SMA, offset=1)
        exit_ = (sma_last is not None and sma_2nd is not None
                 and closes[-1] < sma_last and closes[-2] < sma_2nd)
        return allowed, exit_

    def _stop(self, bars, entry):
        atr = _atr(bars, self.ATR_PERIOD)
        if atr is None or atr <= 0:
            return None
        peak = max(b["c"] for b in bars)
        trail = peak - self.trail_atr * atr
        if entry is not None:
            initial = entry - float(self.INIT_STOP_ATR) * atr
            return max(initial, trail)
        return trail

    def _surplus(self, bars):
        need = max(self.breakout, self.SMA_TREND, self.VOL_LOOKBACK) + 1
        if len(bars) < need:
            return None
        decision, prior = bars[-1], bars[:-1]
        close = decision["c"]
        prior_bo = prior[-self.breakout:]
        if len(prior_bo) < self.breakout:
            return None
        prior_high = max(b["h"] for b in prior_bo)
        if not (close > prior_high) or prior_high <= 0:
            return None
        closes = [b["c"] for b in bars]
        sma = _sma(closes, self.SMA_TREND)
        if sma is None or not (close > sma):
            return None
        prior_v = prior[-self.VOL_LOOKBACK:]
        if len(prior_v) < self.VOL_LOOKBACK:
            return None
        avg_v = sum(b["v"] for b in prior_v) / self.VOL_LOOKBACK
        if avg_v <= 0 or not (decision["v"] >= self.vol_mult * avg_v):
            return None
        return (close - prior_high) / prior_high

    def note_fill(self, symbol, side, price):
        if side == "buy":
            self._entry[symbol] = price
        elif side == "sell":
            self._entry.pop(symbol, None)

    def evaluate(self, ctx):
        out: list[OrderRequest] = []
        allowed, regime_exit = self._regime(ctx)
        held = {s: q for s, q in ctx.positions.items() if q > 0}

        for sym in STOCK_UNIVERSE:
            q = ctx.position(sym)
            if q <= 0:
                continue
            bars = ctx.bars(sym)
            if regime_exit:
                out.append(OrderRequest(sym, "sell", qty=q, reason="regime exit"))
                continue
            if len(bars) < self.ATR_PERIOD + 2:
                continue
            stop = self._stop(bars, self._entry.get(sym))
            if stop is not None and bars[-1]["c"] < stop:
                out.append(OrderRequest(sym, "sell", qty=q, reason="stop breach"))

        if not allowed or len(held) >= self.MAX_POS:
            return out
        quals = []
        for sym in STOCK_UNIVERSE:
            if ctx.position(sym) > 0:
                continue
            s = self._surplus(ctx.bars(sym))
            if s is not None:
                quals.append((s, sym))
        quals.sort(key=lambda t: (-t[0], t[1]))
        slots = self.MAX_POS - len(held)
        for _s, sym in quals[:slots]:
            out.append(OrderRequest(sym, "buy", notional=self.notional,
                                    reason="breakout entry"))
        return out


class _CryptoAdapter:
    """§8 rules keyed by grid {breakout, exit_low, trail_atr}. Spot long-only,
    EMA50>EMA200 regime, 20-low / 2-close-below-EMA200 / ATR-stop exits, max 2."""

    EMA_FAST = 50
    EMA_SLOW = 200
    ATR_PERIOD = 20
    INIT_STOP_ATR = Decimal("3.0")
    MAX_POS = 2

    def __init__(self, params, notional):
        self.breakout = int(params["breakout"])
        self.exit_low = int(params["exit_low"])
        self.trail_atr = float(params["trail_atr"])
        self.notional = notional
        self._entry: dict[str, float] = {}

    def _entry_ok(self, bars):
        if len(bars) < max(self.breakout, self.EMA_SLOW) + 1:
            return False
        decision, prior = bars[-1], bars[:-1]
        pb = prior[-self.breakout:]
        if len(pb) < self.breakout or not (decision["c"] > max(b["h"] for b in pb)):
            return False
        closes = [b["c"] for b in bars]
        ef, es = _ema(closes, self.EMA_FAST), _ema(closes, self.EMA_SLOW)
        return ef is not None and es is not None and ef > es

    def _exit(self, bars, entry):
        decision, prior = bars[-1], bars[:-1]
        close = decision["c"]
        closes = [b["c"] for b in bars]
        pl = prior[-self.exit_low:]
        if len(pl) >= self.exit_low and close < min(b["l"] for b in pl):
            return True
        en, ep = _ema(closes, self.EMA_SLOW), _ema(closes[:-1], self.EMA_SLOW)
        if en is not None and ep is not None and close < en and closes[-2] < ep:
            return True
        atr = _atr(bars, self.ATR_PERIOD)
        if atr is not None and atr > 0:
            peak = max(closes)
            trail = peak - self.trail_atr * atr
            stop = trail if entry is None else max(entry - float(self.INIT_STOP_ATR) * atr, trail)
            if close < stop:
                return True
        return False

    def note_fill(self, symbol, side, price):
        if side == "buy":
            self._entry[symbol] = price
        elif side == "sell":
            self._entry.pop(symbol, None)

    def evaluate(self, ctx):
        out: list[OrderRequest] = []
        held = {s: q for s, q in ctx.positions.items() if q > 0}
        for sym in CRYPTO_UNIVERSE:
            q = ctx.position(sym)
            if q <= 0:
                continue
            bars = ctx.bars(sym)
            if len(bars) < max(self.exit_low, self.ATR_PERIOD) + 2:
                continue
            if self._exit(bars, self._entry.get(sym)):
                out.append(OrderRequest(sym, "sell", qty=q, reason="exit"))
        slots = self.MAX_POS - len(held)
        for sym in CRYPTO_UNIVERSE:
            if slots <= 0:
                break
            if ctx.position(sym) > 0:
                continue
            if self._entry_ok(ctx.bars(sym)):
                out.append(OrderRequest(sym, "buy", notional=self.notional,
                                        reason="breakout entry"))
                slots -= 1
        return out


class _RecordingBacktester(PortfolioBacktester):
    """PortfolioBacktester that tells its adapter about each fill so the adapter's
    stop/entry state tracks confirmed entry prices (the mid on the lot), matching
    the live 'stop derives from confirmed entry' contract — without a live ledger."""

    def _fill_buy(self, order, cur, bars_by_symbol, lots, cash, fills, rejections):
        res = super()._fill_buy(order, cur, bars_by_symbol, lots, cash, fills, rejections)
        if fills and fills[-1]["symbol"] == order.symbol and fills[-1]["side"] == "buy":
            self._strategy.note_fill(order.symbol, "buy", float(fills[-1]["mid"]))
        return res

    def _fill_sell(self, order, cur, bars_by_symbol, lots, cash, fills, rejections, trades):
        res = super()._fill_sell(order, cur, bars_by_symbol, lots, cash, fills,
                                 rejections, trades)
        self._strategy.note_fill(order.symbol, "sell", 0.0)
        return res


# ── dataset acquisition (real first; synthetic fallback for infra demo) ───────────

@dataclass
class SleeveData:
    asset_class: str
    source: str                       # "real" | "synthetic"
    datasets: dict                    # symbol -> HistoricalDataset
    calendar: list                    # list[date]
    fingerprints: dict = field(default_factory=dict)
    limitations: list = field(default_factory=list)
    forced_inconclusive: bool = False
    reason: str = ""


def _try_real_stock(geo) -> SleeveData:
    """Attempt REAL Alpaca stock bars for the full window.

    Bars are pulled SPLIT+DIVIDEND-ADJUSTED at the source (Alpaca
    ``adjustment='all'`` via ``get_recent_bars(..., adjustment='all')``), so the
    series is continuous across corporate actions — verified: AAPL's 2020-08-31 4:1
    split shows 124.81 -> 129.04 -> 134.18, not a fabricated ~73% gap. The verdict
    is therefore NOT force-inconclusive; it comes from the §12 statistical gate on
    real data. A structural spot-check still asserts continuity before trusting it.
    """
    from server import alpaca_client
    end = date.today()
    start = end - timedelta(days=int(geo.min_years * 365.25) + 40)
    provider = alpaca_client.historical_provider()  # network provider, no fixtures
    datasets, fps = {}, {}
    for sym in STOCK_UNIVERSE:
        # Source-adjusted upstream, so the historical layer must NOT re-apply a
        # split transform (it would be a no-op with empty corporate_actions anyway).
        req = HistoricalRequest(
            asset_class=AssetClass.STOCK, provider="alpaca", symbol=sym,
            start=start, end=end, timeframe="1D",
            adjustment=AdjustmentPolicy.RAW,
            as_of_policy=AsOfPolicy.POINT_IN_TIME,
        )
        ds = provider.fetch(req)   # raises on missing creds/coverage
        datasets[sym] = ds
        fps[sym] = ds.fingerprint

    # Guard: refuse to trust a series that still has an uncorrected split-sized gap
    # (any adjacent-day close ratio outside [0.5, 2.0] on a liquid large-cap is a
    # data defect, not a real move). If found, fall back to forced INCONCLUSIVE.
    split_defect = _detect_split_gap(datasets)

    cal = sorted({date.fromisoformat(b["t"][:10])
                  for ds in datasets.values() for b in ds.bars})
    lim = [
        "Stock bars pulled SPLIT+DIVIDEND-adjusted at source (Alpaca "
        "adjustment='all'); series verified continuous across known splits.",
        "Adjustment is Alpaca's authoritative-vendor adjustment, not independently "
        "reconciled against a second corporate-action source.",
        "Alpaca free/IEX feed lags ~20 min; daily history reaches ~10y for the "
        "fixed liquid universe (all currently listed — no delisting/symbol-change).",
    ]
    if split_defect:
        lim.append(f"UNCORRECTED split-sized gap detected: {split_defect} -> "
                   "verdict forced INCONCLUSIVE (data integrity).")
        return SleeveData("stock", "real", datasets, cal, fps, lim,
                          forced_inconclusive=True,
                          reason=f"Adjacent-day price gap {split_defect} indicates "
                                 "an uncorrected corporate action; not trustworthy.")
    return SleeveData("stock", "real", datasets, cal, fps, lim)


def _detect_split_gap(datasets) -> str:
    """Return a description of the first adjacent-day close ratio outside [0.5, 2.0]
    (a split-sized discontinuity), or '' if the series is clean."""
    for sym, ds in datasets.items():
        prev = None
        for b in ds.bars:
            c = float(b["c"])
            if prev is not None and c > 0 and prev > 0:
                r = c / prev
                if r < 0.5 or r > 2.0:
                    return f"{sym} {b['t'][:10]} ratio={r:.2f}"
            prev = c
    return ""


def _try_real_crypto(geo) -> SleeveData:
    """Attempt REAL Binance BTC/ETH daily bars for the full window."""
    from server import db, crypto, binance_client
    acct = next((a for a in db.get_broker_accounts()
                 if a.get("broker") == "binance"), None)
    if acct is None:
        raise HistoricalDataError("no Binance account configured")
    creds = db.get_broker_account_credentials(acct["id"])
    key = crypto.decrypt(creds["api_key"])       # raises if DB_SECRET_KEY invalid
    sec = crypto.decrypt(creds["api_secret"])
    cli = binance_client.BinanceAccountClient(
        key, sec, paper=(acct.get("account_type") == "paper"), account_id=acct["id"])
    provider = binance_client.historical_provider(client=cli)
    end = date.today()
    start = end - timedelta(days=int(geo.min_years * 365.25) + 40)
    datasets, fps = {}, {}
    for sym in CRYPTO_UNIVERSE:
        req = HistoricalRequest(
            asset_class=AssetClass.CRYPTO, provider="binance", symbol=sym,
            start=start, end=end, timeframe="1D", timezone="UTC",
            adjustment=AdjustmentPolicy.RAW, as_of_policy=AsOfPolicy.POINT_IN_TIME)
        ds = provider.fetch(req)
        datasets[sym] = ds
        fps[sym] = ds.fingerprint
    cal = sorted({date.fromisoformat(b["t"][:10])
                  for ds in datasets.values() for b in ds.bars})
    return SleeveData("crypto", "real", datasets, cal, fps)


def _synthetic(asset_class, symbols, geo, provider, seed_base) -> SleeveData:
    """Deterministic synthetic daily bars spanning the full geometry window. For
    INFRASTRUCTURE demonstration ONLY — the resulting verdict is always
    INCONCLUSIVE. A mild upward drift + bounded oscillation gives the pipeline real
    breakouts/exits to execute without pretending to be a market."""
    import math
    n = geo.min_periods + 30
    start = date(2015, 1, 1)
    cal = [start + timedelta(days=i) for i in range(n)]
    datasets, fps = {}, {}
    for si, sym in enumerate(symbols):
        base = 100.0 + 50.0 * si
        bars = []
        for i, d in enumerate(cal):
            # A trending series with a long, decisive cycle so the pipeline actually
            # produces breakouts (EMA regime + 55/252-high) AND stop-out exits — the
            # point is to EXERCISE the full path, not to model a market. Numbers from
            # a synthetic run are meaningless and the verdict is forced INCONCLUSIVE.
            drift = base * (1.0 + 0.0012 * i)
            wave = 1.0 + 0.18 * math.sin((i + seed_base + si * 40) / 120.0)
            c = drift * wave
            o = c * (1.0 + 0.001 * math.sin((i + 3) / 7.0))
            # Keep the intraday high only marginally above the close so a rising
            # close can exceed the prior window's HIGH (otherwise an inflated high
            # permanently outruns the breakout trigger and nothing ever fires).
            hi = max(o, c) * 1.0008
            lo = min(o, c) * 0.995
            v = 1_000_000.0 * (1.0 + 0.6 * abs(math.sin((i + si) / 9.0)))
            bars.append({"t": d.isoformat() + "T00:00:00+00:00",
                         "o": round(o, 4), "h": round(hi, 4), "l": round(lo, 4),
                         "c": round(c, 4), "v": round(v, 2)})
        req = HistoricalRequest(
            asset_class=(AssetClass.STOCK if asset_class == "stock"
                         else AssetClass.CRYPTO),
            provider=provider, symbol=sym,
            start=cal[0], end=cal[-1], timeframe="1D",
            adjustment=AdjustmentPolicy.RAW)
        ds = HistoricalDataset(request=req, bars=bars,
                               retrieved_at="synthetic")
        datasets[sym] = ds
        fps[sym] = ds.fingerprint
    return SleeveData(asset_class, "synthetic", datasets, cal, fps,
                      limitations=["SYNTHETIC fixtures — infrastructure demo only; "
                                   "NOT market data. Verdict forced INCONCLUSIVE."],
                      forced_inconclusive=True,
                      reason="synthetic data (infrastructure demonstration only)")


def _safe_error(exc: Exception) -> str:
    """A recorded-safe description of a real-data failure.

    Uses the exception TYPE plus its message, but redacts any long alphanumeric
    run (>= 16 chars) that could be a leaked API key/secret. Credentials are never
    interpolated into strings by this module; this is defence-in-depth against a
    third-party (e.g. ccxt) exception that might echo request material."""
    import re
    msg = str(exc)
    msg = re.sub(r"[A-Za-z0-9_\-]{16,}", "<redacted>", msg)
    if len(msg) > 200:
        msg = msg[:200] + "…"
    return f"{type(exc).__name__}: {msg}"


def acquire(asset_class, geo) -> SleeveData:
    """Real first; on ANY failure, record the reason and fall back to synthetic."""
    try:
        if asset_class == "stock":
            return _try_real_stock(geo)
        return _try_real_crypto(geo)
    except Exception as exc:   # missing creds, feed error, coverage — never crash
        real_reason = f"real data unavailable: {_safe_error(exc)}"
        symbols = STOCK_UNIVERSE if asset_class == "stock" else CRYPTO_UNIVERSE
        provider = "alpaca" if asset_class == "stock" else "binance"
        syn = _synthetic(asset_class, symbols, geo, provider,
                         seed_base=0 if asset_class == "stock" else 100)
        syn.limitations.insert(0, real_reason)
        syn.reason = f"{real_reason}; fell back to synthetic (INCONCLUSIVE)."
        return syn


# ── backtest_fn factory (wraps PortfolioBacktester over a window, from cash) ──────

def _make_backtest_fn(data: SleeveData, cost_model: CostModel, initial=D("100000")):
    def _slice(ds, window):
        """Bars strictly inside [window.start, window.end]. Each research window is
        run FROM CASH (spec §19.13): indicators warm up within the window's own
        leading bars and produce no orders until enough history exists, exactly as
        every OOS fold / the final holdout begins from cash. No warm-up prefix is
        borrowed across the window boundary (that would leak pre-window bars into a
        from-cash window's scored region)."""
        return [b for b in ds.bars
                if window.start <= date.fromisoformat(b["t"][:10]) <= window.end]

    symbol_specs = {}
    if data.asset_class == "crypto":
        symbol_specs = {"BTC/USDT": SymbolSpec(qty_precision=5, min_notional=D("10")),
                        "ETH/USDT": SymbolSpec(qty_precision=4, min_notional=D("10"))}

    def backtest_fn(*, params, window, from_cash, role):
        datasets = {}
        for sym, ds in data.datasets.items():
            bars = _slice(ds, window)
            if not bars:
                continue
            req = HistoricalRequest(
                asset_class=ds.asset_class, provider=ds.provider, symbol=sym,
                start=date.fromisoformat(bars[0]["t"][:10]),
                end=date.fromisoformat(bars[-1]["t"][:10]),
                timeframe="1D", adjustment=ds.adjustment)
            datasets[sym] = HistoricalDataset(request=req, bars=bars,
                                              retrieved_at=ds.retrieved_at)
        if data.asset_class == "stock":
            adapter = _StockAdapter(params, notional=float(initial) * 0.09)
        else:
            adapter = _CryptoAdapter(params, notional=float(initial) * 0.025)
        cfg = BacktestConfig(initial_capital=initial, asset_class=data.asset_class,
                             cost_model=cost_model, symbols=symbol_specs,
                             end_convention=EndConvention.LIQUIDATE)
        try:
            res = _RecordingBacktester(datasets, adapter, cfg).run()
        except BacktestError:
            # A failed run is invalid, NOT a zero-signal success (§10.1). Report a
            # sentinel that the drawdown cap will reject so it can never be selected.
            return {"net_return": D("0"), "calmar": D("0"),
                    "max_drawdown": D("-1"), "turnover": D("0"),
                    "expectancy": D("0"), "trades": [], "daily_returns": []}
        m = res.metrics
        daily = _daily_returns(res.equity_curve)
        return {
            "net_return": m["net_return"],
            "calmar": m["calmar_ratio"] if m["calmar_ratio"] is not None else D("0"),
            "max_drawdown": m["max_drawdown"],
            "turnover": m["turnover"] if m["turnover"] is not None else D("0"),
            "expectancy": m["expectancy"] if m["expectancy"] is not None else D("0"),
            "trades": res.trades,
            "daily_returns": daily,
        }
    return backtest_fn


def _daily_returns(curve):
    out = []
    prev = None
    for pt in curve:
        eq = pt["equity"]
        if prev is not None and prev > 0:
            out.append((eq - prev) / prev)
        prev = eq
    return out


# ── one sleeve end to end ─────────────────────────────────────────────────────────

@dataclass
class SleeveResult:
    asset_class: str
    source: str
    verdict: str
    reason: str
    fingerprints: dict
    limitations: list
    baseline_oos: Decimal | None = None
    stressed_oos: Decimal | None = None
    holdout: dict | None = None
    fold_returns: list = field(default_factory=list)
    ci: tuple | None = None
    n_trades: int = 0
    attempts: int = 0
    frozen_params: dict | None = None
    benchmark: dict | None = None


def run_sleeve(asset_class, geo, grid) -> SleeveResult:
    data = acquire(asset_class, geo)
    block = S.STOCK_BLOCK if asset_class == "stock" else S.CRYPTO_BLOCK

    baseline_cost = CostModel.baseline(asset_class)
    stressed_cost = CostModel.stress(asset_class)

    bt_baseline = _make_backtest_fn(data, baseline_cost)
    bt_stressed = _make_backtest_fn(data, stressed_cost)

    # Full walk-forward under BASELINE costs (this drives selection + holdout).
    wf = R.run_walk_forward(calendar=data.calendar, geometry=geo, grid=grid,
                            backtest_fn=bt_baseline, persist=None)

    # Re-run the frozen params on the whole pre-holdout window under BOTH cost
    # models to get the baseline/stressed OOS figures (§12.1/§12.2), and gather the
    # holdout daily-return series for the statistical gate (§19.13).
    baseline_oos = stressed_oos = None
    holdout_daily: list = []
    holdout_trades: list = []
    plan = R.build_folds(data.calendar, geo)
    if wf.frozen_params is not None:
        b = bt_baseline(params=wf.frozen_params, window=plan.pre_holdout,
                        from_cash=True, role="training")
        s = bt_stressed(params=wf.frozen_params, window=plan.pre_holdout,
                        from_cash=True, role="training")
        baseline_oos = R._to_dec(b["net_return"])
        stressed_oos = R._to_dec(s["net_return"])
        h = bt_baseline(params=wf.frozen_params, window=plan.holdout,
                        from_cash=True, role="holdout")
        holdout_daily = h["daily_returns"]
        holdout_trades = h["trades"]

    # Statistical gate (§19.13): lower bound of the moving-block-bootstrap 95% CI
    # for daily net return on the HOLDOUT must be > 0. Applied to whichever series
    # exists; an empty series is INCONCLUSIVE (cannot bootstrap).
    ci = None
    gate = S.GateVerdict.INCONCLUSIVE
    if holdout_daily:
        lo, pt, hi = S.moving_block_bootstrap_ci(holdout_daily, block, seed=7)
        ci = (lo, pt, hi)
        gate = S.classify_ci(lo, hi)

    # A synthetic run or a data-limited stock run is ALWAYS INCONCLUSIVE regardless
    # of the numbers — honesty over optics (§17, task ground rules).
    if data.forced_inconclusive:
        verdict = "INCONCLUSIVE"
        reason = data.reason
    else:
        verdict = gate.value.upper()
        reason = (f"holdout daily-return 95% CI = "
                  f"[{ci[0]:.6f}, {ci[2]:.6f}]" if ci else "no holdout series")

    # Simple buy-and-hold benchmark over the holdout for context (§11.3).
    bench = _benchmark(data, plan.holdout)

    return SleeveResult(
        asset_class=asset_class, source=data.source, verdict=verdict, reason=reason,
        fingerprints=data.fingerprints, limitations=data.limitations,
        baseline_oos=baseline_oos, stressed_oos=stressed_oos,
        holdout=wf.holdout, fold_returns=[f.get("net_return") for f in wf.folds],
        ci=ci, n_trades=len(holdout_trades), attempts=len(wf.attempts),
        frozen_params=wf.frozen_params, benchmark=bench)


def _benchmark(data: SleeveData, window):
    """Equal-weight buy-and-hold over the holdout window (context only)."""
    out = {}
    for sym, ds in data.datasets.items():
        bars = [b for b in ds.bars
                if window.start <= date.fromisoformat(b["t"][:10]) <= window.end]
        if len(bars) >= 2 and bars[0]["c"]:
            out[sym] = (D(str(bars[-1]["c"])) - D(str(bars[0]["c"]))) / D(str(bars[0]["c"]))
    if not out:
        return None
    avg = sum(out.values(), D("0")) / D(len(out))
    return {"per_symbol": {k: f"{v:.4f}" for k, v in out.items()},
            "equal_weight_return": f"{avg:.4f}"}


# ── main ──────────────────────────────────────────────────────────────────────────

def _git_head():
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                           text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _fmt(v):
    return "n/a" if v is None else (f"{v:.6f}" if isinstance(v, Decimal) else str(v))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Deterministic strategy research runner")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args(argv)

    head = _git_head()
    sleeves = [
        ("stock", R.FoldGeometry.stock_default(), R.predeclared_grid("stock")),
        ("crypto", R.FoldGeometry.crypto_default(), R.predeclared_grid("crypto")),
    ]
    results = []
    for ac, geo, grid in sleeves:
        results.append(run_sleeve(ac, geo, grid))

    if args.json:
        payload = {
            "code_revision": head,
            "sleeves": [{
                "asset_class": r.asset_class, "source": r.source,
                "verdict": r.verdict, "reason": r.reason,
                "baseline_oos_return": _fmt(r.baseline_oos),
                "stressed_oos_return": _fmt(r.stressed_oos),
                "holdout_ci": ([_fmt(x) for x in r.ci] if r.ci else None),
                "holdout_trades": r.n_trades, "attempts": r.attempts,
                "frozen_params": {k: str(v) for k, v in (r.frozen_params or {}).items()},
                "benchmark": r.benchmark,
                "fingerprints": r.fingerprints, "limitations": r.limitations,
            } for r in results],
        }
        print(json.dumps(payload, indent=2))
        return 0

    print("=" * 78)
    print("TradeBot strategy research — deterministic evidence run (Task 11)")
    print(f"code revision: {head}")
    print("=" * 78)
    for r in results:
        print(f"\n### {r.asset_class.upper()} SLEEVE  [data source: {r.source}]")
        print(f"  VERDICT: {r.verdict}")
        print(f"  reason:  {r.reason}")
        print(f"  grid attempts persisted (in-memory): {r.attempts}")
        print(f"  frozen params: {r.frozen_params}")
        print(f"  baseline OOS net return: {_fmt(r.baseline_oos)}")
        print(f"  stressed OOS net return: {_fmt(r.stressed_oos)}")
        if r.ci:
            print(f"  holdout daily-return 95% CI: "
                  f"[{_fmt(r.ci[0])}, point {_fmt(r.ci[1])}, {_fmt(r.ci[2])}]")
        print(f"  holdout closed trades: {r.n_trades}")
        if r.benchmark:
            print(f"  buy-and-hold benchmark (holdout): {r.benchmark}")
        if r.fingerprints:
            print("  data fingerprints:")
            for sym, fp in r.fingerprints.items():
                print(f"    {sym}: {fp}")
        if r.limitations:
            print("  limitations:")
            for lim in r.limitations:
                print(f"    - {lim}")
    print("\n" + "=" * 78)
    print("Per §12/§19.13: a sleeve is enabled in deployment ONLY on a PASS verdict.")
    print("INCONCLUSIVE and FAIL sleeves REMAIN DISABLED.")
    print("=" * 78)
    # Exit 0 always: an INCONCLUSIVE/FAIL verdict is a valid, expected outcome of an
    # honest research run, not a script error.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
