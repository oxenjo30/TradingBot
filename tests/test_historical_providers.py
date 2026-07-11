"""Task 6 — Historical provider contracts and point-in-time data.

Deterministic, NO-NETWORK tests. Providers are exercised through recorded /
synthetic fixtures only. See:
  - plan Task 6
  - spec §9 (historical data contract), §10.1 (temporal integrity),
    §19.11 + §19.13 "Corporate actions and total return"
"""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from server.historical import (
    AssetClass,
    AdjustmentPolicy,
    AsOfPolicy,
    CorporateAction,
    CorporateActionType,
    HistoricalRequest,
    HistoricalDataset,
    HistoricalProvider,
    AlpacaHistoricalProvider,
    BinanceHistoricalProvider,
    HistoricalDataError,
    ProviderAssetClassError,
    validate_bars,
    fingerprint_bars,
    apply_split_to_bars,
    apply_split_to_position_state,
    dividend_cash_credit,
)


# ── helpers ─────────────────────────────────────────────────────────────────────

def _bar(t, o, h, l, c, v=1_000_000.0):
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}


def _daily(start: str, count: int, base=100.0):
    """count consecutive UTC daily bars starting at `start` (YYYY-MM-DD)."""
    from datetime import timedelta
    d = date.fromisoformat(start)
    out = []
    for i in range(count):
        o = base + i
        out.append(_bar(d.isoformat() + "T00:00:00+00:00", o, o + 1, o - 1, o + 0.5))
        d += timedelta(days=1)
    return out


def _req(asset_class=AssetClass.STOCK, provider="alpaca", symbol="AAPL",
         start="2024-01-01", end="2024-01-10", timeframe="1D"):
    return HistoricalRequest(
        asset_class=asset_class,
        provider=provider,
        symbol=symbol,
        start=date.fromisoformat(start),
        end=date.fromisoformat(end),
        timeframe=timeframe,
    )


# ── validation: sorted / unique / finite / consistent OHLC ───────────────────────

class TestBarValidation:
    def test_valid_bars_pass(self):
        bars = _daily("2024-01-01", 5)
        out = validate_bars(bars)
        assert len(out) == 5
        # sorted ascending by timestamp
        assert [b["t"] for b in out] == sorted(b["t"] for b in bars)

    def test_unsorted_bars_are_sorted(self):
        bars = _daily("2024-01-01", 3)
        shuffled = [bars[2], bars[0], bars[1]]
        out = validate_bars(shuffled)
        assert [b["t"] for b in out] == [b["t"] for b in bars]

    def test_duplicate_timestamp_rejected(self):
        bars = _daily("2024-01-01", 2)
        dup = bars + [dict(bars[0])]
        with pytest.raises(HistoricalDataError):
            validate_bars(dup)

    def test_non_finite_value_rejected(self):
        bars = _daily("2024-01-01", 2)
        bars[1]["c"] = float("nan")
        with pytest.raises(HistoricalDataError):
            validate_bars(bars)

    def test_infinite_value_rejected(self):
        bars = _daily("2024-01-01", 2)
        bars[1]["h"] = float("inf")
        with pytest.raises(HistoricalDataError):
            validate_bars(bars)

    def test_high_below_low_rejected(self):
        bars = _daily("2024-01-01", 2)
        bars[0]["h"] = 90.0
        bars[0]["l"] = 95.0
        with pytest.raises(HistoricalDataError):
            validate_bars(bars)

    def test_open_outside_high_low_rejected(self):
        bars = _daily("2024-01-01", 1)
        bars[0]["o"] = bars[0]["h"] + 10.0
        with pytest.raises(HistoricalDataError):
            validate_bars(bars)

    def test_negative_price_rejected(self):
        bars = _daily("2024-01-01", 1)
        bars[0]["l"] = -1.0
        with pytest.raises(HistoricalDataError):
            validate_bars(bars)

    def test_negative_volume_rejected(self):
        bars = _daily("2024-01-01", 1)
        bars[0]["v"] = -5.0
        with pytest.raises(HistoricalDataError):
            validate_bars(bars)

    def test_undeclared_gap_rejected_when_no_calendar(self):
        # A daily series with a hole and no declared trading calendar / allowed
        # gap fails closed rather than silently accepting missing data.
        bars = _daily("2024-01-01", 5)
        del bars[2]  # drop 2024-01-03
        with pytest.raises(HistoricalDataError):
            validate_bars(bars, max_gap_days=1)

    def test_declared_weekend_gap_allowed(self):
        # Fri 2024-01-05 then Mon 2024-01-08 — a >1 day gap allowed by calendar.
        bars = [
            _bar("2024-01-05T00:00:00+00:00", 100, 101, 99, 100.5),
            _bar("2024-01-08T00:00:00+00:00", 100, 101, 99, 100.5),
        ]
        out = validate_bars(bars, allowed_gap_starts={date(2024, 1, 5)}, max_gap_days=1)
        assert len(out) == 2

    def test_empty_dataset_rejected(self):
        with pytest.raises(HistoricalDataError):
            validate_bars([])


# ── deterministic fingerprint ────────────────────────────────────────────────────

class TestFingerprint:
    def test_same_data_same_fingerprint(self):
        a = _daily("2024-01-01", 5)
        b = _daily("2024-01-01", 5)
        assert fingerprint_bars(a) == fingerprint_bars(b)

    def test_order_independent(self):
        a = _daily("2024-01-01", 5)
        b = list(reversed(_daily("2024-01-01", 5)))
        assert fingerprint_bars(a) == fingerprint_bars(b)

    def test_different_data_different_fingerprint(self):
        a = _daily("2024-01-01", 5)
        b = _daily("2024-01-01", 5)
        b[2]["c"] = b[2]["c"] + 0.01
        assert fingerprint_bars(a) != fingerprint_bars(b)

    def test_float_noise_does_not_change_fingerprint(self):
        # 100.5 vs 100.50 vs 100.500000001-ish canonicalization: identical value
        # canonical text yields identical fingerprint.
        a = [_bar("2024-01-01T00:00:00+00:00", 100.0, 101.0, 99.0, 100.5)]
        b = [_bar("2024-01-01T00:00:00+00:00", 100.00, 101.000, 99.0, 100.50)]
        assert fingerprint_bars(a) == fingerprint_bars(b)

    def test_dataset_exposes_fingerprint(self):
        bars = _daily("2024-01-01", 5)
        ds = HistoricalDataset(
            request=_req(),
            bars=bars,
            retrieved_at="2024-02-01T00:00:00+00:00",
        )
        assert ds.fingerprint == fingerprint_bars(bars)
        assert ds.provider == "alpaca"
        assert ds.asset_class is AssetClass.STOCK
        assert ds.timeframe == "1D"


# ── provider separation: mismatch raises, NO fallback ────────────────────────────

class TestProviderSeparation:
    def test_alpaca_provider_rejects_crypto_request(self):
        prov = AlpacaHistoricalProvider(bars_by_symbol={"BTC": _daily("2024-01-01", 5)})
        req = _req(asset_class=AssetClass.CRYPTO, provider="alpaca", symbol="BTC")
        with pytest.raises(ProviderAssetClassError):
            prov.fetch(req)

    def test_binance_provider_rejects_stock_request(self):
        prov = BinanceHistoricalProvider(bars_by_symbol={"AAPL": _daily("2024-01-01", 5)})
        req = _req(asset_class=AssetClass.STOCK, provider="binance", symbol="AAPL")
        with pytest.raises(ProviderAssetClassError):
            prov.fetch(req)

    def test_alpaca_provider_rejects_wrong_provider_id(self):
        prov = AlpacaHistoricalProvider(bars_by_symbol={"AAPL": _daily("2024-01-01", 5)})
        req = _req(asset_class=AssetClass.STOCK, provider="binance", symbol="AAPL")
        with pytest.raises(ProviderAssetClassError):
            prov.fetch(req)

    def test_no_silent_fallback_to_alpaca_for_crypto(self):
        # The crypto provider must NEVER reach into the stock provider. Give the
        # binance provider no data for the symbol and prove it raises a missing-data
        # error rather than returning alpaca data.
        prov = BinanceHistoricalProvider(bars_by_symbol={})
        req = _req(asset_class=AssetClass.CRYPTO, provider="binance", symbol="BTC")
        with pytest.raises(HistoricalDataError):
            prov.fetch(req)

    def test_class_declares_asset_class(self):
        assert AlpacaHistoricalProvider.asset_class is AssetClass.STOCK
        assert BinanceHistoricalProvider.asset_class is AssetClass.CRYPTO
        assert issubclass(AlpacaHistoricalProvider, HistoricalProvider)
        assert issubclass(BinanceHistoricalProvider, HistoricalProvider)


# ── exact range + timeframe enforcement ──────────────────────────────────────────

class TestRangeAndTimeframe:
    def test_fetch_returns_only_requested_range(self):
        bars = _daily("2024-01-01", 20)
        prov = AlpacaHistoricalProvider(bars_by_symbol={"AAPL": bars})
        req = _req(start="2024-01-05", end="2024-01-09")
        ds = prov.fetch(req)
        days = {b["t"][:10] for b in ds.bars}
        assert min(days) == "2024-01-05"
        assert max(days) == "2024-01-09"
        assert "2024-01-04" not in days
        assert "2024-01-10" not in days

    def test_unsupported_timeframe_rejected(self):
        prov = AlpacaHistoricalProvider(bars_by_symbol={"AAPL": _daily("2024-01-01", 5)})
        req = _req(timeframe="1Min")
        with pytest.raises(HistoricalDataError):
            prov.fetch(req)

    def test_binance_only_supports_daily(self):
        prov = BinanceHistoricalProvider(bars_by_symbol={"BTC": _daily("2024-01-01", 5)})
        req = _req(asset_class=AssetClass.CRYPTO, provider="binance",
                   symbol="BTC", timeframe="1H")
        with pytest.raises(HistoricalDataError):
            prov.fetch(req)

    def test_coverage_shortfall_rejected(self):
        # Requested window extends past available data → unsupported coverage.
        bars = _daily("2024-01-01", 5)  # only through 2024-01-05
        prov = AlpacaHistoricalProvider(bars_by_symbol={"AAPL": bars})
        req = _req(start="2024-01-01", end="2024-01-31")
        with pytest.raises(HistoricalDataError):
            prov.fetch(req)


# ── stale / missing data failure (raises, not empty) ─────────────────────────────

class TestStaleAndMissing:
    def test_missing_symbol_raises_not_empty(self):
        prov = AlpacaHistoricalProvider(bars_by_symbol={"AAPL": _daily("2024-01-01", 5)})
        req = _req(symbol="TSLA")
        with pytest.raises(HistoricalDataError):
            prov.fetch(req)

    def test_empty_series_raises_not_empty(self):
        prov = AlpacaHistoricalProvider(bars_by_symbol={"AAPL": []})
        req = _req(symbol="AAPL")
        with pytest.raises(HistoricalDataError):
            prov.fetch(req)

    def test_provider_exception_propagates_not_swallowed(self):
        class _Boom(AlpacaHistoricalProvider):
            def _raw_bars(self, symbol):
                raise RuntimeError("upstream down")
        prov = _Boom(bars_by_symbol={"AAPL": _daily("2024-01-01", 5)})
        with pytest.raises(RuntimeError):
            prov.fetch(_req())


# ── split transformation correctness ─────────────────────────────────────────────

class TestSplitTransformation:
    def test_split_divides_prices_multiplies_volume_from_effective_date(self):
        # 2:1 split effective 2024-01-03. Bars on/after that date in the event-aware
        # view have pre-split prices divided by 2 and volumes multiplied by 2.
        bars = [
            _bar("2024-01-01T00:00:00+00:00", 200, 202, 198, 200, 100),
            _bar("2024-01-02T00:00:00+00:00", 200, 202, 198, 200, 100),
            _bar("2024-01-03T00:00:00+00:00", 100, 101, 99, 100, 200),
        ]
        split = CorporateAction(
            type=CorporateActionType.SPLIT,
            symbol="AAPL",
            effective_date=date(2024, 1, 3),
            ratio=Decimal("2"),  # 2 new shares per 1 old
        )
        out = apply_split_to_bars(bars, [split])
        # Bars before effective date are divided by 2 (back into the adjusted scale)
        assert Decimal(str(out[0]["o"])) == Decimal("100")
        assert Decimal(str(out[0]["v"])) == Decimal("200")
        assert Decimal(str(out[1]["c"])) == Decimal("100")
        # Bar on/after effective date already on new scale — unchanged.
        assert Decimal(str(out[2]["o"])) == Decimal("100")
        assert Decimal(str(out[2]["v"])) == Decimal("200")

    def test_split_transforms_position_state_without_pnl(self):
        # A held lot of 10 shares @ $200 with peak/stop transforms by the split
        # ratio: 20 shares @ $100, same market value (no P&L created).
        state = {
            "qty": Decimal("10"),
            "avg_price": Decimal("200"),
            "peak_close": Decimal("210"),
            "stop": Decimal("190"),
            "entry_atr": Decimal("5"),
        }
        split = CorporateAction(
            type=CorporateActionType.SPLIT, symbol="AAPL",
            effective_date=date(2024, 1, 3), ratio=Decimal("2"),
        )
        new = apply_split_to_position_state(state, split)
        assert new["qty"] == Decimal("20")
        assert new["avg_price"] == Decimal("100")
        assert new["peak_close"] == Decimal("105")
        assert new["stop"] == Decimal("95")
        assert new["entry_atr"] == Decimal("2.5")
        # market value invariant
        assert new["qty"] * new["avg_price"] == state["qty"] * state["avg_price"]


# ── dividend as cash (NOT price back-adjust) ─────────────────────────────────────

class TestDividendAsCash:
    def test_dividend_credited_as_cash_not_into_price(self):
        bars = _daily("2024-01-01", 5, base=100.0)
        before = [dict(b) for b in bars]
        div = CorporateAction(
            type=CorporateActionType.DIVIDEND, symbol="AAPL",
            effective_date=date(2024, 1, 3),          # ex-date
            payable_date=date(2024, 1, 10),
            cash_amount=Decimal("0.50"),              # per share
        )
        # Prices must be identical: dividends are never back-adjusted into prices.
        out = apply_split_to_bars(bars, [div])
        for b0, b1 in zip(before, out):
            assert Decimal(str(b0["c"])) == Decimal(str(b1["c"]))
            assert Decimal(str(b0["o"])) == Decimal(str(b1["o"]))

    def test_dividend_cash_credit_helper(self):
        div = CorporateAction(
            type=CorporateActionType.DIVIDEND, symbol="AAPL",
            effective_date=date(2024, 1, 3),
            payable_date=date(2024, 1, 10),
            cash_amount=Decimal("0.50"),
        )
        # Entitled 100 shares on the ex-date → $50 cash on the payable date.
        credit = dividend_cash_credit(div, shares_held_on_ex_date=Decimal("100"))
        assert credit == Decimal("50.00")

    def test_dividend_not_entitled_pays_zero(self):
        div = CorporateAction(
            type=CorporateActionType.DIVIDEND, symbol="AAPL",
            effective_date=date(2024, 1, 3),
            payable_date=date(2024, 1, 10),
            cash_amount=Decimal("0.50"),
        )
        assert dividend_cash_credit(div, shares_held_on_ex_date=Decimal("0")) == Decimal("0")


# ── symbol change: instrument-id preservation ────────────────────────────────────

class TestSymbolChange:
    def test_symbol_change_preserves_instrument_id(self):
        # FB -> META. The request carries a stable instrument_id; both symbols
        # resolve to the SAME instrument and lot ownership is preserved.
        bars = _daily("2024-01-01", 5)
        prov = AlpacaHistoricalProvider(
            bars_by_symbol={"META": bars},
            corporate_actions=[
                CorporateAction(
                    type=CorporateActionType.SYMBOL_CHANGE, symbol="FB",
                    effective_date=date(2022, 6, 9),
                    new_symbol="META", instrument_id="inst-fb-meta",
                ),
            ],
        )
        req = HistoricalRequest(
            asset_class=AssetClass.STOCK, provider="alpaca", symbol="FB",
            start=date(2024, 1, 1), end=date(2024, 1, 5), timeframe="1D",
            instrument_id="inst-fb-meta",
        )
        ds = prov.fetch(req)
        assert ds.instrument_id == "inst-fb-meta"
        assert ds.resolved_symbol == "META"
        assert len(ds.bars) == 5


# ── delisting handling ───────────────────────────────────────────────────────────

class TestDelisting:
    def test_delisting_with_cash_consideration(self):
        bars = _daily("2024-01-01", 3)
        delist = CorporateAction(
            type=CorporateActionType.DELISTING, symbol="XYZ",
            effective_date=date(2024, 1, 4),
            cash_amount=Decimal("12.34"),
        )
        prov = AlpacaHistoricalProvider(
            bars_by_symbol={"XYZ": bars}, corporate_actions=[delist],
        )
        req = _req(symbol="XYZ", start="2024-01-01", end="2024-01-03")
        ds = prov.fetch(req)
        assert ds.delisting is not None
        assert ds.delisting.cash_amount == Decimal("12.34")
        assert ds.delisting.effective_date == date(2024, 1, 4)

    def test_delisting_without_cash_flags_limitation(self):
        bars = _daily("2024-01-01", 3)
        delist = CorporateAction(
            type=CorporateActionType.DELISTING, symbol="XYZ",
            effective_date=date(2024, 1, 4),
            cash_amount=None,      # no authoritative consideration
        )
        prov = AlpacaHistoricalProvider(
            bars_by_symbol={"XYZ": bars}, corporate_actions=[delist],
        )
        req = _req(symbol="XYZ", start="2024-01-01", end="2024-01-03")
        ds = prov.fetch(req)
        assert ds.delisting is not None
        assert ds.delisting.cash_amount is None
        assert any("delist" in lim.lower() for lim in ds.limitations)


# ── merger / spinoff fail-closed ─────────────────────────────────────────────────

class TestUnsupportedEventsFailClosed:
    def test_unsupported_merger_freezes_instrument(self):
        bars = _daily("2024-01-01", 5)
        merger = CorporateAction(
            type=CorporateActionType.MERGER, symbol="XYZ",
            effective_date=date(2024, 1, 3),
            supported=False,     # provider cannot supply explicit event terms
        )
        prov = AlpacaHistoricalProvider(
            bars_by_symbol={"XYZ": bars}, corporate_actions=[merger],
        )
        req = _req(symbol="XYZ", start="2024-01-01", end="2024-01-05")
        with pytest.raises(HistoricalDataError):
            prov.fetch(req)

    def test_supported_merger_does_not_freeze(self):
        bars = _daily("2024-01-01", 5)
        merger = CorporateAction(
            type=CorporateActionType.MERGER, symbol="XYZ",
            effective_date=date(2024, 1, 3),
            supported=True,
            cash_amount=Decimal("50"),
        )
        prov = AlpacaHistoricalProvider(
            bars_by_symbol={"XYZ": bars}, corporate_actions=[merger],
        )
        req = _req(symbol="XYZ", start="2024-01-01", end="2024-01-05")
        ds = prov.fetch(req)
        assert len(ds.bars) == 5


# ── as-of / point-in-time policy plumbing ────────────────────────────────────────

class TestAsOfPolicy:
    def test_future_split_not_applied_before_asof(self):
        # A split effective AFTER the as-of date must not be applied to earlier
        # decision-time bars (no future-known back-adjustment at decision time).
        bars = [
            _bar("2024-01-01T00:00:00+00:00", 200, 202, 198, 200, 100),
            _bar("2024-01-02T00:00:00+00:00", 200, 202, 198, 200, 100),
        ]
        split = CorporateAction(
            type=CorporateActionType.SPLIT, symbol="AAPL",
            effective_date=date(2024, 6, 1), ratio=Decimal("2"),
        )
        prov = AlpacaHistoricalProvider(
            bars_by_symbol={"AAPL": bars}, corporate_actions=[split],
        )
        req = HistoricalRequest(
            asset_class=AssetClass.STOCK, provider="alpaca", symbol="AAPL",
            start=date(2024, 1, 1), end=date(2024, 1, 2), timeframe="1D",
            adjustment=AdjustmentPolicy.SPLIT_ADJUSTED,
            as_of=date(2024, 1, 2),      # decision time, before the split
        )
        ds = prov.fetch(req)
        # unchanged because the split is in the future relative to as_of
        assert Decimal(str(ds.bars[0]["o"])) == Decimal("200")

    def test_retrospective_scale_applies_all_splits(self):
        bars = [
            _bar("2024-01-01T00:00:00+00:00", 200, 202, 198, 200, 100),
            _bar("2024-01-02T00:00:00+00:00", 200, 202, 198, 200, 100),
        ]
        split = CorporateAction(
            type=CorporateActionType.SPLIT, symbol="AAPL",
            effective_date=date(2024, 6, 1), ratio=Decimal("2"),
        )
        prov = AlpacaHistoricalProvider(
            bars_by_symbol={"AAPL": bars}, corporate_actions=[split],
        )
        req = HistoricalRequest(
            asset_class=AssetClass.STOCK, provider="alpaca", symbol="AAPL",
            start=date(2024, 1, 1), end=date(2024, 1, 2), timeframe="1D",
            adjustment=AdjustmentPolicy.SPLIT_ADJUSTED,
            as_of_policy=AsOfPolicy.RETROSPECTIVE,   # labeled retrospective scale
        )
        ds = prov.fetch(req)
        assert Decimal(str(ds.bars[0]["o"])) == Decimal("100")


# ── adapter integration hooks (live behavior untouched) ──────────────────────────

class TestAdapterHooks:
    def test_alpaca_module_exposes_historical_provider_factory(self):
        import server.alpaca_client as ac
        assert hasattr(ac, "historical_provider")

    def test_binance_module_exposes_historical_provider_factory(self):
        import server.binance_client as bc
        assert hasattr(bc, "historical_provider")

    def test_strategy_base_exposes_historical_request_type(self):
        # base.py re-exports the request/asset-class contract for strategies that
        # want point-in-time data without importing the whole module graph.
        from server.strategies import base
        assert hasattr(base, "HistoricalRequest")
        assert hasattr(base, "AssetClass")

    def test_get_recent_bars_still_works_unchanged(self):
        # Live path must be untouched: the backtest thread-local override still
        # short-circuits get_recent_bars exactly as before.
        import server.alpaca_client as ac
        ac._bt.bars = {"AAPL": _daily("2024-01-01", 3)}
        ac._bt.current_date = date(2024, 1, 2)
        try:
            out = ac.get_recent_bars("AAPL", days=60)
            assert len(out) == 2
        finally:
            ac._bt.bars = None
            ac._bt.current_date = None
