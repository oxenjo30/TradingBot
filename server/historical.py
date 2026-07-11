"""Task 6 — Historical provider contracts and point-in-time data.

Explicit stock/crypto historical providers for the backtester and research
harness. This is backtest/research infrastructure only; it does NOT touch the
live trading engine. The live adapters (`get_recent_bars`, order methods) are
untouched — the provider layer is added ALONGSIDE them.

See docs/superpowers/specs/2026-07-11-trading-strategy-rebuild-design.md:
  - §9   Historical data contract (declared request fields; normalized, sorted,
         validated response; provenance + deterministic data fingerprint).
  - §10.1 Temporal integrity (decision-time bars; no future leakage).
  - §19.11 / §19.13 "Corporate actions and total return":
      * ONE point-in-time corporate-action policy covering OHLC, volume, shares,
        ATR, fills, lots, dividends, symbol changes, delistings.
      * Point-in-time splits divide pre-split prices and multiply pre-split
        volumes from the effective date onward; position state transforms by the
        same ratio WITHOUT creating P&L.
      * Cash dividends are credited as CASH (never back-adjusted into prices).
      * Symbol changes preserve the instrument ID and lot ownership.
      * Unsupported mergers/spinoffs FREEZE the instrument (fail closed) and make
        the affected validation segment ineligible.
      * Future-known back-adjustment at decision time is prohibited unless labeled
        RETROSPECTIVE and kept on one transformed scale.

Hard rules (Phase 0 anti-patterns):
  - Stock and crypto providers CANNOT silently substitute for each other. A
    mismatched asset class raises `ProviderAssetClassError`; there is NO fallback.
  - Exceptions / missing required data FAIL the request (`HistoricalDataError`);
    they are never converted into empty/zero-bar "success".
"""
from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum

from .execution_models import decimal_text

# Providers only support daily bars in this design (spec §9 / §11.1).
_SUPPORTED_TIMEFRAMES = frozenset({"1D", "1d", "1Day", "day", "daily"})


# ── enums / policies (§9) ────────────────────────────────────────────────────────

class AssetClass(str, Enum):
    STOCK = "stock"
    CRYPTO = "crypto"


class AdjustmentPolicy(str, Enum):
    RAW = "raw"                       # no split adjustment
    SPLIT_ADJUSTED = "split_adjusted"  # point-in-time split-adjusted OHLCV


class AsOfPolicy(str, Enum):
    # Decision-time view: only events with effective_date <= as_of are applied.
    POINT_IN_TIME = "point_in_time"
    # Retrospective view: ALL known splits applied on one transformed scale.
    # Permitted only when explicitly labeled (spec §19.11).
    RETROSPECTIVE = "retrospective"


class CorporateActionType(str, Enum):
    SPLIT = "split"
    DIVIDEND = "dividend"
    SYMBOL_CHANGE = "symbol_change"
    DELISTING = "delisting"
    MERGER = "merger"
    SPINOFF = "spinoff"


# ── exceptions ───────────────────────────────────────────────────────────────────

class HistoricalDataError(Exception):
    """Missing, stale, inconsistent, or unsupported historical data.

    The request FAILS; it is never converted into empty/zero-bar success (§10.1)."""


class ProviderAssetClassError(HistoricalDataError):
    """A request's asset class / provider does not match this provider.

    Raised so a stock request to the crypto provider (or vice versa) fails loudly
    rather than silently falling back to the other asset class (Phase 0)."""


# ── corporate action record ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class CorporateAction:
    """A single point-in-time corporate action.

    `ratio` is new-shares-per-old-share for a SPLIT (2 means 2:1). `cash_amount`
    is per-share for a DIVIDEND, or the total per-share cash consideration for a
    DELISTING/MERGER. `supported` is False when the provider cannot supply explicit
    event terms — such events fail closed (freeze the instrument)."""
    type: CorporateActionType
    symbol: str
    effective_date: date
    ratio: Decimal | None = None
    cash_amount: Decimal | None = None
    payable_date: date | None = None
    new_symbol: str | None = None
    instrument_id: str | None = None
    supported: bool = True


# ── request contract (§9) ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HistoricalRequest:
    """A fully-declared historical data request (§9).

    Declares asset class, provider, symbol, start/end, timeframe, timezone/calendar,
    adjustment policy, and point-in-time/as-of policy."""
    asset_class: AssetClass
    provider: str
    symbol: str
    start: date
    end: date
    timeframe: str = "1D"
    timezone: str = "UTC"
    calendar: str | None = None
    adjustment: AdjustmentPolicy = AdjustmentPolicy.SPLIT_ADJUSTED
    as_of_policy: AsOfPolicy = AsOfPolicy.POINT_IN_TIME
    as_of: date | None = None
    instrument_id: str | None = None

    def __post_init__(self):
        if self.start > self.end:
            raise HistoricalDataError(
                f"start {self.start} is after end {self.end}"
            )


# ── dataset contract (§9) ────────────────────────────────────────────────────────

@dataclass
class HistoricalDataset:
    """Normalized, sorted, validated bars plus provenance + fingerprint (§9).

    `bars` are ascending-by-timestamp OHLCV dicts ({"t","o","h","l","c","v"}).
    `fingerprint` is a deterministic content hash used to make backtest runs
    reproducible (Task 7 persists it alongside provider/asset_class/timeframe/
    adjustment/retrieved_at)."""
    request: HistoricalRequest
    bars: list[dict]
    retrieved_at: str
    resolved_symbol: str | None = None
    instrument_id: str | None = None
    corporate_actions: list[CorporateAction] = field(default_factory=list)
    delisting: CorporateAction | None = None
    limitations: list[str] = field(default_factory=list)
    fingerprint: str = field(default="", init=False)

    def __post_init__(self):
        if self.resolved_symbol is None:
            self.resolved_symbol = self.request.symbol
        if self.instrument_id is None:
            self.instrument_id = self.request.instrument_id
        self.fingerprint = fingerprint_bars(self.bars)

    # provenance accessors (Task 7 persistence reads these)
    @property
    def provider(self) -> str:
        return self.request.provider

    @property
    def asset_class(self) -> AssetClass:
        return self.request.asset_class

    @property
    def timeframe(self) -> str:
        return self.request.timeframe

    @property
    def adjustment(self) -> AdjustmentPolicy:
        return self.request.adjustment

    def provenance(self) -> dict:
        """Reproducibility metadata for persistence (Task 7)."""
        return {
            "provider": self.provider,
            "asset_class": self.asset_class.value,
            "symbol": self.request.symbol,
            "resolved_symbol": self.resolved_symbol,
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "adjustment": self.adjustment.value,
            "as_of_policy": self.request.as_of_policy.value,
            "as_of": self.request.as_of.isoformat() if self.request.as_of else None,
            "start": self.request.start.isoformat(),
            "end": self.request.end.isoformat(),
            "retrieved_at": self.retrieved_at,
            "fingerprint": self.fingerprint,
            "bar_count": len(self.bars),
            "limitations": list(self.limitations),
        }


# ── validation helpers (§9) ──────────────────────────────────────────────────────

def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError) as exc:
        raise HistoricalDataError(f"non-numeric bar value: {v!r}") from exc


def validate_bars(bars: list[dict], *,
                  allowed_gap_starts: set[date] | None = None,
                  max_gap_days: int | None = None) -> list[dict]:
    """Return a sorted, validated copy of `bars` or raise HistoricalDataError.

    Rejects: empty datasets, duplicate timestamps, non-finite values, negative
    prices/volume, inconsistent OHLC (high<low, open/close outside [low,high]),
    and undeclared gaps larger than `max_gap_days` (unless the gap start is in
    `allowed_gap_starts`, e.g. a Friday before a weekend)."""
    if not bars:
        raise HistoricalDataError("empty dataset: missing required data")

    parsed: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for b in bars:
        t = b.get("t")
        if not t:
            raise HistoricalDataError(f"bar missing timestamp: {b!r}")
        if t in seen:
            raise HistoricalDataError(f"duplicate timestamp: {t}")
        seen.add(t)

        o, h, l, c = (_num(b.get("o")), _num(b.get("h")),
                      _num(b.get("l")), _num(b.get("c")))
        v = _num(b.get("v", 0))
        for name, val in (("o", o), ("h", h), ("l", l), ("c", c), ("v", v)):
            if not math.isfinite(val):
                raise HistoricalDataError(f"non-finite {name} at {t}: {val!r}")
        if o < 0 or h < 0 or l < 0 or c < 0:
            raise HistoricalDataError(f"negative price at {t}")
        if v < 0:
            raise HistoricalDataError(f"negative volume at {t}")
        if h < l:
            raise HistoricalDataError(f"inconsistent OHLC at {t}: high {h} < low {l}")
        if not (l <= o <= h):
            raise HistoricalDataError(f"open {o} outside [low {l}, high {h}] at {t}")
        if not (l <= c <= h):
            raise HistoricalDataError(f"close {c} outside [low {l}, high {h}] at {t}")
        parsed.append((t, b))

    parsed.sort(key=lambda x: x[0])
    ordered = [b for _, b in parsed]

    if max_gap_days is not None:
        allowed = allowed_gap_starts or set()
        prev_d: date | None = None
        for t, _b in parsed:
            d = _bar_date(t)
            if prev_d is not None:
                gap = (d - prev_d).days
                if gap > max_gap_days and prev_d not in allowed:
                    raise HistoricalDataError(
                        f"undeclared gap of {gap} days after {prev_d} "
                        f"(max {max_gap_days}); declare the trading calendar"
                    )
            prev_d = d

    return ordered


def _bar_date(t: str) -> date:
    return date.fromisoformat(t[:10])


# ── deterministic fingerprint (§9) ───────────────────────────────────────────────

def fingerprint_bars(bars: list[dict]) -> str:
    """SHA-256 over canonical decimal text of each bar, sorted by timestamp.

    Deterministic and order-independent: identical numeric content — regardless of
    input order or float formatting (100.5 == 100.50) — yields the same digest;
    any change to any value changes it (§9)."""
    rows = []
    for b in bars:
        rows.append("|".join([
            str(b["t"]),
            decimal_text(Decimal(str(b["o"]))),
            decimal_text(Decimal(str(b["h"]))),
            decimal_text(Decimal(str(b["l"]))),
            decimal_text(Decimal(str(b["c"]))),
            decimal_text(Decimal(str(b.get("v", 0)))),
        ]))
    rows.sort()
    payload = "\n".join(rows).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


# ── point-in-time event transformations (§19.11 / §19.13) ────────────────────────

def _split_factor(actions: list[CorporateAction], *,
                  as_of: date | None,
                  retrospective: bool) -> dict[date, Decimal]:
    """Map each split's effective_date -> ratio, filtered by the as-of policy.

    Under point-in-time (default), only splits with effective_date <= as_of are
    applied (no future-known back-adjustment at decision time). Under the
    retrospective policy, all known splits are applied on one transformed scale.
    """
    out: dict[date, Decimal] = {}
    for a in actions:
        if a.type is not CorporateActionType.SPLIT or a.ratio is None:
            continue
        if not retrospective and as_of is not None and a.effective_date > as_of:
            continue
        out[a.effective_date] = a.ratio
    return out


def apply_split_to_bars(bars: list[dict],
                        actions: list[CorporateAction],
                        *, as_of: date | None = None,
                        retrospective: bool = False) -> list[dict]:
    """Apply point-in-time splits to OHLCV (§19.13).

    From each split's effective date onward the provider view is already on the
    new (post-split) scale. To place the WHOLE series on that single consistent
    scale, pre-split bars (strictly before the effective date) have their prices
    DIVIDED by the ratio and volumes MULTIPLIED by the ratio. Bars on/after the
    effective date are left unchanged. Dividends and other non-split actions never
    alter prices here (dividends are credited as cash separately).
    """
    factors = _split_factor(actions, as_of=as_of, retrospective=retrospective)
    if not factors:
        return [dict(b) for b in bars]

    out = []
    for b in bars:
        bd = _bar_date(b["t"])
        # Cumulative ratio of all splits whose effective date is AFTER this bar.
        ratio = Decimal("1")
        for eff, r in factors.items():
            if bd < eff:
                ratio *= r
        nb = dict(b)
        if ratio != Decimal("1"):
            nb["o"] = _scaled(b["o"], ratio, divide=True)
            nb["h"] = _scaled(b["h"], ratio, divide=True)
            nb["l"] = _scaled(b["l"], ratio, divide=True)
            nb["c"] = _scaled(b["c"], ratio, divide=True)
            nb["v"] = _scaled(b.get("v", 0), ratio, divide=False)
        out.append(nb)
    return out


def _scaled(value, ratio: Decimal, *, divide: bool):
    d = Decimal(str(value))
    result = (d / ratio) if divide else (d * ratio)
    # Preserve numeric type expectation of callers: bars carry floats/Decimals.
    return float(result) if isinstance(value, float) else result


def apply_split_to_position_state(state: dict, split: CorporateAction) -> dict:
    """Transform held-lot state by a split ratio WITHOUT creating P&L (§19.13).

    qty *= ratio; per-share prices (avg_price, peak_close, stop, entry_atr) /= ratio.
    Market value (qty * avg_price) is invariant. Keys absent from `state` are left
    untouched."""
    if split.type is not CorporateActionType.SPLIT or split.ratio is None:
        raise HistoricalDataError("apply_split_to_position_state requires a SPLIT")
    r = split.ratio
    out = dict(state)
    if "qty" in out and out["qty"] is not None:
        out["qty"] = Decimal(str(out["qty"])) * r
    for price_key in ("avg_price", "peak_close", "stop", "entry_atr"):
        if price_key in out and out[price_key] is not None:
            out[price_key] = Decimal(str(out[price_key])) / r
    return out


def dividend_cash_credit(action: CorporateAction,
                         shares_held_on_ex_date: Decimal) -> Decimal:
    """Cash credited for a dividend: per-share amount * entitled shares (§19.13).

    Dividends are credited to cash on the payable date when the position was
    entitled on the ex-date. They are never back-adjusted into prices."""
    if action.type is not CorporateActionType.DIVIDEND or action.cash_amount is None:
        raise HistoricalDataError("dividend_cash_credit requires a DIVIDEND with cash_amount")
    held = Decimal(str(shares_held_on_ex_date))
    if held <= 0:
        return Decimal("0")
    return (action.cash_amount * held).quantize(Decimal("0.01"))


# ── provider base + concrete providers ───────────────────────────────────────────

class HistoricalProvider(ABC):
    """Abstract single-asset-class historical provider.

    Subclasses declare `asset_class`. `fetch()` enforces asset-class/provider match,
    resolves symbol changes, applies the corporate-action policy, validates, and
    returns a `HistoricalDataset`. Subclasses only implement `_raw_bars(symbol)`."""

    asset_class: AssetClass
    provider_id: str

    def __init__(self, *, bars_by_symbol: dict[str, list[dict]] | None = None,
                 corporate_actions: list[CorporateAction] | None = None):
        # Fixture-driven store (no network). Real network wiring is added by the
        # adapter factory functions, not here — keeps unit tests deterministic.
        self._bars_by_symbol = bars_by_symbol or {}
        self._corporate_actions = list(corporate_actions or [])

    # subclasses override to source raw bars for the (resolved) symbol
    def _raw_bars(self, symbol: str) -> list[dict]:
        return self._bars_by_symbol.get(symbol.upper(), self._bars_by_symbol.get(symbol, []))

    def _check_asset_class(self, req: HistoricalRequest):
        if req.asset_class is not self.asset_class:
            raise ProviderAssetClassError(
                f"{type(self).__name__} serves {self.asset_class.value} only; "
                f"request asked for {req.asset_class.value} — no fallback"
            )
        if req.provider != self.provider_id:
            raise ProviderAssetClassError(
                f"{type(self).__name__} is provider '{self.provider_id}'; "
                f"request named '{req.provider}' — no substitution"
            )

    def _resolve_symbol(self, req: HistoricalRequest) -> tuple[str, str | None]:
        """Follow SYMBOL_CHANGE actions to the current ticker, preserving the
        instrument id (§19.13). Returns (resolved_symbol, instrument_id)."""
        symbol = req.symbol
        instrument_id = req.instrument_id
        for a in self._corporate_actions:
            if (a.type is CorporateActionType.SYMBOL_CHANGE
                    and a.symbol.upper() == symbol.upper()
                    and a.new_symbol):
                symbol = a.new_symbol
                if a.instrument_id and instrument_id is None:
                    instrument_id = a.instrument_id
        return symbol, instrument_id

    def _relevant_actions(self, req: HistoricalRequest,
                          resolved_symbol: str) -> list[CorporateAction]:
        syms = {req.symbol.upper(), resolved_symbol.upper()}
        return [a for a in self._corporate_actions if a.symbol.upper() in syms
                or (a.new_symbol and a.new_symbol.upper() in syms)]

    def fetch(self, req: HistoricalRequest) -> HistoricalDataset:
        self._check_asset_class(req)
        if req.timeframe not in _SUPPORTED_TIMEFRAMES:
            raise HistoricalDataError(
                f"{type(self).__name__} supports daily bars only, not {req.timeframe!r}"
            )

        resolved_symbol, instrument_id = self._resolve_symbol(req)
        actions = self._relevant_actions(req, resolved_symbol)

        # Fail closed on unsupported mergers/spinoffs (§19.13).
        for a in actions:
            if a.type in (CorporateActionType.MERGER, CorporateActionType.SPINOFF) \
                    and not a.supported:
                raise HistoricalDataError(
                    f"unsupported {a.type.value} for {a.symbol} on {a.effective_date}: "
                    f"instrument frozen; validation segment ineligible"
                )

        raw = self._raw_bars(resolved_symbol)  # exceptions propagate (never swallowed)
        if not raw:
            raise HistoricalDataError(
                f"no data for {resolved_symbol} from {self.provider_id} "
                f"({self.asset_class.value}) — not falling back"
            )

        # Restrict to the requested inclusive date range.
        windowed = [b for b in raw
                    if req.start <= _bar_date(b["t"]) <= req.end]
        if not windowed:
            raise HistoricalDataError(
                f"no {resolved_symbol} bars inside {req.start}..{req.end}"
            )

        # Coverage: the available series must actually reach the requested end
        # (within one interval). A window that ends well before req.end is an
        # unsupported-coverage failure, not a silent short return.
        last_avail = max(_bar_date(b["t"]) for b in raw)
        if last_avail < req.end and (req.end - last_avail).days > self._max_stale_days():
            raise HistoricalDataError(
                f"coverage shortfall: {resolved_symbol} ends {last_avail}, "
                f"request end {req.end} (stale/missing)"
            )

        # Apply the point-in-time corporate-action policy.
        retrospective = req.as_of_policy is AsOfPolicy.RETROSPECTIVE
        as_of = req.as_of if req.as_of is not None else req.end
        if req.adjustment is AdjustmentPolicy.SPLIT_ADJUSTED:
            windowed = apply_split_to_bars(
                windowed, actions, as_of=as_of, retrospective=retrospective,
            )

        limitations: list[str] = []
        delisting = None
        for a in actions:
            if a.type is CorporateActionType.DELISTING:
                delisting = a
                if a.cash_amount is None:
                    limitations.append(
                        f"delisting of {a.symbol} on {a.effective_date} has no "
                        f"authoritative cash consideration; valued at last "
                        f"executable price then zero (limitation)"
                    )

        validated = validate_bars(windowed)

        return HistoricalDataset(
            request=req,
            bars=validated,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            resolved_symbol=resolved_symbol,
            instrument_id=instrument_id,
            corporate_actions=actions,
            delisting=delisting,
            limitations=limitations,
        )

    def _max_stale_days(self) -> int:
        """Allowed staleness in days for the last available bar vs request end."""
        return 3  # a daily series may legitimately trail a weekend/holiday


class AlpacaHistoricalProvider(HistoricalProvider):
    """STOCK-ONLY daily provider. Cannot serve crypto requests (§9, Phase 0)."""
    asset_class = AssetClass.STOCK
    provider_id = "alpaca"


class BinanceHistoricalProvider(HistoricalProvider):
    """CRYPTO-ONLY daily UTC provider. Cannot serve stock requests (§9, Phase 0)."""
    asset_class = AssetClass.CRYPTO
    provider_id = "binance"
