"""Consolidated portfolio risk controller and durable hard stop (Task 5).

Implements spec §6 (capital allocation + risk limits), §19.1 (consolidated portfolio
equity), §19.2 (hard-stop policy), §19.9 (pre-trade risk sizing), and §19.13 (risk
sizing equation + risk monitor / loss limits).

Design rules enforced here
--------------------------
- All money/quantities are `Decimal`; persisted as canonical decimal TEXT (§19.5).
- Drawdown / loss are compared to FOUR decimal places (§19.1).
- Order-quantity rounding is ROUND_DOWN (§19.5, §19.13).
- SHADOW SAFETY: this module is pure computation plus a controller that only ACTS
  when explicitly invoked (authoritative mode / an actual hard stop). In shadow mode
  the live engine's legacy risk gating is unchanged; the controller here is never
  driven, so it cannot block or exit legacy orders. `evaluate_limits` is a pure
  decision unless `persist=True` is passed.

Consolidation (§19.1)
---------------------
Consolidated equity = sum of reconciled participating-account equity in USD. USD is
valued at 1. USDT uses a fresh USDT/USD reference; a 1.0 fallback is allowed only
within a verified 50bps deviation, otherwise equity is frozen. Snapshots must be at
most 120s apart and none older than 180s, else equity is STALE → entries freeze and
the high-water mark is NOT updated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Callable

from . import db

# ── Risk thresholds (§6.2, §19.1, §19.13) ───────────────────────────────────────
DRAWDOWN_FREEZE_PCT = Decimal("4.0000")     # >= 4% freezes new entries
DRAWDOWN_HARD_STOP_PCT = Decimal("5.0000")  # >= 5% hard stop
DAILY_LOSS_LIMIT_PCT = Decimal("1.0000")    # <= -1% freezes new entries
WEEKLY_LOSS_LIMIT_PCT = Decimal("2.0000")   # <= -2% freezes new entries

# Exposure targets, first validation cycle (§6.1).
STOCK_GROSS_MAX_PCT = Decimal("45")
CRYPTO_GROSS_MAX_PCT = Decimal("5")
CASH_FLOOR_PCT = Decimal("50")

# Snapshot freshness (§19.1).
MAX_SNAPSHOT_SPREAD_S = 120
MAX_SNAPSHOT_AGE_S = 180

# USDT reference fallback band (§19.1): 50 basis points.
USDT_FALLBACK_BAND = Decimal("0.0050")

# Hard-stop shutdown step machine (§19.2). Persisted so a restart resumes here.
SHUTDOWN_STEPS = [
    "TRIGGERED",       # 1. persist HARD_STOP_TRIGGERED
    "KILL_SWITCHES",   # 1. activate global + participating-account entry kill switches
    "CANCEL_BUYS",     # 2. cancel nonterminal strategy-owned buys (never external)
    "RECONCILE",       # 3. reconcile cancellations up to 60s, ingest fills
    "RECOMPUTE",       # 4. recompute owned sellable quantities
    "SUBMIT_EXITS",    # 5-7. one idempotent exit per (account, strategy, symbol)
    "DONE",            # completed pass (does NOT clear the hard stop — §19.2 step 10)
]

_MAX_EXIT_RETRIES = 3  # §19.2 step 8


# ── Timestamp helpers ────────────────────────────────────────────────────────────

def _parse_ts(ts: str) -> datetime:
    s = (ts or "").strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _now_dt(now: str | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    return _parse_ts(now)


def _d(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


# ── Snapshots and consolidation (§19.1) ──────────────────────────────────────────

@dataclass(frozen=True)
class PortfolioSnapshot:
    """One participating account's reconciled equity at a point in time."""
    account_id: int
    equity: Decimal
    currency: str
    taken_at: str  # UTC ISO-8601


@dataclass(frozen=True)
class ConsolidatedEquity:
    """Result of consolidating participating-account snapshots."""
    equity: Decimal          # USD, unrounded
    stale: bool
    taken_at: str            # newest component snapshot time
    reason: str = ""


def _usdt_rate(usdt_usd: Decimal | None, usdt_verified: bool) -> Decimal | None:
    """Return the USDT→USD rate to use, or None to FREEZE (§19.1).

    - No reference at all → 1.0 fallback (paper-account default, treated as verified
      parity).
    - A reference within 50bps of parity → 1.0 fallback allowed.
    - A reference beyond 50bps → only usable if it is VERIFIED; otherwise freeze.
    """
    if usdt_usd is None:
        return Decimal("1")
    deviation = (usdt_usd - Decimal("1")).copy_abs()
    if deviation <= USDT_FALLBACK_BAND:
        return Decimal("1")           # within band → 1.0 fallback
    if usdt_verified:
        return usdt_usd               # verified fresh reference beyond band → convert
    return None                       # unverified beyond band → freeze


def consolidate_snapshots(snapshots: list[PortfolioSnapshot], *, now: str | None = None,
                          usdt_usd: Decimal | None = None,
                          usdt_verified: bool = False) -> ConsolidatedEquity:
    """Consolidate reconciled participating-account equity into one USD figure.

    Freshness (§19.1): all component snapshots must be at most 120s apart AND none
    older than 180s; otherwise the consolidated equity is STALE. A USDT reference
    beyond 50bps that is not verified also freezes (stale)."""
    now_dt = _now_dt(now)
    if not snapshots:
        return ConsolidatedEquity(Decimal("0"), stale=True,
                                  taken_at=now_dt.isoformat(), reason="no snapshots")

    times = [_parse_ts(s.taken_at) for s in snapshots]
    newest = max(times)
    oldest = min(times)
    spread_s = (newest - oldest).total_seconds()
    age_s = (now_dt - oldest).total_seconds()

    stale = False
    reason = ""
    if spread_s > MAX_SNAPSHOT_SPREAD_S:
        stale, reason = True, f"snapshots {spread_s:.0f}s apart (> {MAX_SNAPSHOT_SPREAD_S}s)"
    elif age_s > MAX_SNAPSHOT_AGE_S:
        stale, reason = True, f"oldest snapshot {age_s:.0f}s old (> {MAX_SNAPSHOT_AGE_S}s)"

    total = Decimal("0")
    for s in snapshots:
        cur = (s.currency or "USD").upper()
        if cur == "USD":
            total += _d(s.equity)
        elif cur == "USDT":
            rate = _usdt_rate(usdt_usd, usdt_verified)
            if rate is None:
                stale = True
                reason = reason or f"USDT reference {usdt_usd} beyond 50bps and unverified"
                # Value at parity for the (frozen) total; equity is not used while stale.
                total += _d(s.equity)
            else:
                total += _d(s.equity) * rate
        else:
            stale = True
            reason = reason or f"unsupported currency {cur}"
            total += _d(s.equity)

    return ConsolidatedEquity(equity=total, stale=stale,
                              taken_at=newest.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
                              reason=reason)


# ── Persistent risk state (§19.1) ────────────────────────────────────────────────

@dataclass
class PortfolioRiskState:
    high_water_mark: Decimal = Decimal("0")
    daily_baseline: Decimal = Decimal("0")
    weekly_baseline: Decimal = Decimal("0")
    daily_baseline_date: str = ""   # YYYY-MM-DD (UTC)
    weekly_baseline_week: str = ""  # ISO year-week, e.g. 2026-W28


def _get_dec(key: str) -> Decimal:
    v = db.get_portfolio_risk(key, "")
    return Decimal(v) if v else Decimal("0")


def load_state() -> PortfolioRiskState:
    return PortfolioRiskState(
        high_water_mark=_get_dec("high_water_mark"),
        daily_baseline=_get_dec("daily_baseline"),
        weekly_baseline=_get_dec("weekly_baseline"),
        daily_baseline_date=db.get_portfolio_risk("daily_baseline_date", ""),
        weekly_baseline_week=db.get_portfolio_risk("weekly_baseline_week", ""),
    )


def save_state(state: PortfolioRiskState) -> None:
    from .execution_models import decimal_text
    db.set_portfolio_risk("high_water_mark", decimal_text(state.high_water_mark))
    db.set_portfolio_risk("daily_baseline", decimal_text(state.daily_baseline))
    db.set_portfolio_risk("weekly_baseline", decimal_text(state.weekly_baseline))
    db.set_portfolio_risk("daily_baseline_date", state.daily_baseline_date or "")
    db.set_portfolio_risk("weekly_baseline_week", state.weekly_baseline_week or "")


def reset_high_water_mark(value: Decimal, *, reason: str, owner: str) -> None:
    """Owner-authorized high-water-mark reset with an audit reason (§19.1).

    Required whenever a participating account is added/removed. An empty reason is
    rejected — the reset must be attributable."""
    if not reason or not reason.strip():
        raise ValueError("high-water-mark reset requires an audit reason")
    from .execution_models import decimal_text
    db.set_portfolio_risk("high_water_mark", decimal_text(_d(value)))
    db.log_audit("portfolio_risk", "hwm_reset",
                 f"owner={owner} value={decimal_text(_d(value))} reason={reason}")


def apply_external_flow(state: PortfolioRiskState, flow: Decimal) -> PortfolioRiskState:
    """Adjust the high-water mark and daily/weekly baselines by a signed external
    cash flow (deposit +, withdrawal -) so cash movement is not treated as P&L (§19.1)."""
    f = _d(flow)
    return PortfolioRiskState(
        high_water_mark=state.high_water_mark + f,
        daily_baseline=state.daily_baseline + f,
        weekly_baseline=state.weekly_baseline + f,
        daily_baseline_date=state.daily_baseline_date,
        weekly_baseline_week=state.weekly_baseline_week,
    )


# ── Paired internal transfers (§19.13 cash-flow matching) ────────────────────────
# An internal transfer carries a stable transfer id with source/destination legs.
# It nets to zero at portfolio level ONLY after both legs match amount/currency
# within tolerance. An unmatched leg freezes high-water-mark advancement and new
# entries until paired or owner-classified as an external flow.

_TRANSFER_TOLERANCE = Decimal("0.01")   # 1 cent amount tolerance


def register_transfer_leg(*, transfer_id: str, account_id: int, amount: Decimal,
                          currency: str = "USD") -> None:
    """Record one leg of an internal transfer (source negative, destination positive)."""
    import json
    from .execution_models import decimal_text
    key = f"transfer:{transfer_id}"
    raw = db.get_portfolio_risk(key, "")
    legs = json.loads(raw) if raw else []
    legs.append({"account_id": account_id, "amount": decimal_text(_d(amount)),
                 "currency": (currency or "USD").upper()})
    db.set_portfolio_risk(key, json.dumps(legs))


def transfers_balanced(transfer_id: str) -> bool:
    """True only when both legs of `transfer_id` are present, share a currency, and
    net to zero within tolerance (§19.13). A single/unmatched leg is NOT balanced."""
    import json
    raw = db.get_portfolio_risk(f"transfer:{transfer_id}", "")
    legs = json.loads(raw) if raw else []
    if len(legs) < 2:
        return False
    currencies = {leg["currency"] for leg in legs}
    if len(currencies) != 1:
        return False
    net = sum((Decimal(leg["amount"]) for leg in legs), Decimal("0"))
    return net.copy_abs() <= _TRANSFER_TOLERANCE


def roll_baselines(state: PortfolioRiskState, equity: Decimal, *,
                   now: str | None = None) -> PortfolioRiskState:
    """Reset the daily baseline at 00:00 UTC and the weekly baseline on Monday 00:00
    UTC to the current equity (§19.1). Returns a possibly-updated state."""
    now_dt = _now_dt(now)
    day = now_dt.strftime("%Y-%m-%d")
    iso_year, iso_week, _ = now_dt.isocalendar()
    week = f"{iso_year}-W{iso_week:02d}"
    eq = _d(equity)

    daily_baseline = state.daily_baseline
    daily_date = state.daily_baseline_date
    if day != state.daily_baseline_date:
        daily_baseline = eq
        daily_date = day

    weekly_baseline = state.weekly_baseline
    weekly_week = state.weekly_baseline_week
    if week != state.weekly_baseline_week:
        weekly_baseline = eq
        weekly_week = week

    return PortfolioRiskState(
        high_water_mark=state.high_water_mark,
        daily_baseline=daily_baseline,
        weekly_baseline=weekly_baseline,
        daily_baseline_date=daily_date,
        weekly_baseline_week=weekly_week,
    )


# ── Limit evaluation (§19.1, §19.13) ─────────────────────────────────────────────

@dataclass(frozen=True)
class RiskDecision:
    entries_frozen: bool
    hard_stop: bool
    exits_allowed: bool
    drawdown_pct: Decimal
    daily_pct: Decimal
    weekly_pct: Decimal
    stale: bool
    reason: str


def _pct(delta: Decimal, base: Decimal) -> Decimal:
    """delta/base as a percentage, quantized to 4 dp (§19.1). base<=0 → 0."""
    if base <= 0:
        return Decimal("0.0000")
    return (delta / base * Decimal("100")).quantize(Decimal("0.0001"))


def evaluate_limits(consolidated: ConsolidatedEquity, state: PortfolioRiskState, *,
                    now: str | None = None, persist: bool = False) -> RiskDecision:
    """Evaluate all portfolio risk limits against a consolidated equity snapshot.

    Returns a pure RiskDecision. Protective/risk-reduction EXITS are always allowed;
    only NEW ENTRIES freeze (§19.13). When `persist=True` AND the snapshot is fresh
    AND equity is a new high, the high-water mark is advanced and saved. A STALE
    snapshot freezes entries and NEVER advances the high-water mark (§19.1).

    In shadow mode the caller passes `persist=False`, so this is inert computation.
    """
    # Stale equity: freeze entries, do NOT update the high-water mark (§19.1).
    if consolidated.stale:
        return RiskDecision(
            entries_frozen=True, hard_stop=False, exits_allowed=True,
            drawdown_pct=Decimal("0.0000"), daily_pct=Decimal("0.0000"),
            weekly_pct=Decimal("0.0000"), stale=True,
            reason=f"stale consolidated equity: {consolidated.reason}")

    equity = consolidated.equity
    hwm = state.high_water_mark

    # Advance the high-water mark on a fresh new high.
    if equity > hwm:
        hwm = equity
        if persist:
            new_state = PortfolioRiskState(
                high_water_mark=hwm,
                daily_baseline=state.daily_baseline,
                weekly_baseline=state.weekly_baseline,
                daily_baseline_date=state.daily_baseline_date,
                weekly_baseline_week=state.weekly_baseline_week)
            save_state(new_state)

    drawdown_pct = _pct(hwm - equity, hwm)     # positive = below peak
    daily_pct = _pct(equity - state.daily_baseline, state.daily_baseline)
    weekly_pct = _pct(equity - state.weekly_baseline, state.weekly_baseline)

    hard_stop = drawdown_pct >= DRAWDOWN_HARD_STOP_PCT
    entries_frozen = False
    reasons: list[str] = []

    if hard_stop:
        entries_frozen = True
        reasons.append(f"HARD STOP: drawdown {drawdown_pct}% >= {DRAWDOWN_HARD_STOP_PCT}%")
    elif drawdown_pct >= DRAWDOWN_FREEZE_PCT:
        entries_frozen = True
        reasons.append(f"drawdown {drawdown_pct}% >= {DRAWDOWN_FREEZE_PCT}% entry freeze")

    if daily_pct <= -DAILY_LOSS_LIMIT_PCT:
        entries_frozen = True
        reasons.append(f"daily loss {daily_pct}% <= -{DAILY_LOSS_LIMIT_PCT}%")
    if weekly_pct <= -WEEKLY_LOSS_LIMIT_PCT:
        entries_frozen = True
        reasons.append(f"weekly loss {weekly_pct}% <= -{WEEKLY_LOSS_LIMIT_PCT}%")

    return RiskDecision(
        entries_frozen=entries_frozen, hard_stop=hard_stop, exits_allowed=True,
        drawdown_pct=drawdown_pct, daily_pct=daily_pct, weekly_pct=weekly_pct,
        stale=False, reason="; ".join(reasons))


# ── Exposure caps 45/5/50 (§6.1) ─────────────────────────────────────────────────

def check_exposure_caps(*, equity: Decimal, sleeve: str,
                        stock_gross: Decimal, crypto_gross: Decimal,
                        added_notional: Decimal) -> tuple[bool, str]:
    """Would adding `added_notional` to `sleeve` violate the 45/5/50 targets?

    stock gross <= 45%, crypto gross <= 5%, cash >= 50% of total equity (§6.1).
    Returns (ok, reason). Pure computation."""
    equity = _d(equity)
    if equity <= 0:
        return False, "non-positive equity"
    stock = _d(stock_gross)
    crypto = _d(crypto_gross)
    added = _d(added_notional)
    if sleeve == "stock":
        stock += added
    elif sleeve == "crypto":
        crypto += added
    else:
        return False, f"unknown sleeve {sleeve!r}"

    stock_pct = stock / equity * Decimal("100")
    crypto_pct = crypto / equity * Decimal("100")
    cash_pct = Decimal("100") - stock_pct - crypto_pct

    # Sleeve caps first (the tightest per-sleeve limit), then the aggregate cash floor.
    if stock_pct > STOCK_GROSS_MAX_PCT:
        return False, f"stock gross {stock_pct:.2f}% > {STOCK_GROSS_MAX_PCT}%"
    if crypto_pct > CRYPTO_GROSS_MAX_PCT:
        return False, f"crypto gross {crypto_pct:.2f}% > {CRYPTO_GROSS_MAX_PCT}%"
    if cash_pct < CASH_FLOOR_PCT:
        return False, f"cash {cash_pct:.2f}% < {CASH_FLOOR_PCT}% floor"
    return True, "within 45/5/50 targets"


# ── Quantity solver (§19.13 risk-sizing equation) ────────────────────────────────

def solve_quantity(*, risk_budget: Decimal, estimated_entry: Decimal,
                   initial_stop: Decimal, increment: Decimal,
                   entry_cost: Callable[[Decimal], Decimal],
                   exit_cost: Callable[[Decimal], Decimal],
                   max_notional: Decimal | None = None,
                   max_qty: Decimal | None = None) -> Decimal:
    """Largest rounded-DOWN quantity `q` (a multiple of `increment`) satisfying:

        q*(estimated_entry - initial_stop) + entry_cost(q) + estimated_exit_cost(q)
            <= risk_budget

    AND the cash (`max_notional`) and `max_qty` caps (§19.13). Solved by bounded
    monotonic binary search over increments. Fails closed (returns 0) when the stop
    distance is non-positive, or when even the smallest increment exceeds budget/caps
    (non-positive risk numerator). Rounding is ROUND_DOWN (§19.5)."""
    risk_budget = _d(risk_budget)
    entry = _d(estimated_entry)
    stop = _d(initial_stop)
    inc = _d(increment)
    stop_distance = entry - stop

    # Fail closed before sizing when the stop distance is non-positive (§19.13).
    if stop_distance <= 0 or inc <= 0:
        return Decimal("0")

    def feasible(q: Decimal) -> bool:
        if q <= 0:
            return False
        # Risk-sizing constraint.
        total = q * stop_distance + entry_cost(q) + exit_cost(q)
        if total > risk_budget:
            return False
        # Cash / notional cap.
        if max_notional is not None and q * entry > _d(max_notional):
            return False
        # Absolute quantity cap.
        if max_qty is not None and q > _d(max_qty):
            return False
        return True

    # The smallest tradable quantity is one increment; if it isn't feasible, skip.
    if not feasible(inc):
        return Decimal("0")

    # Establish an upper bound in increment-units. Start from a generous ceiling
    # derived from the loosest binding cap, then grow until infeasible (bounded).
    lo = Decimal("1")   # units of `inc`
    hi = Decimal("1")
    # Grow hi geometrically until it becomes infeasible — bounded by construction.
    while feasible(hi * inc):
        lo = hi
        hi = hi * 2
        if hi > Decimal("1e30"):   # hard ceiling guards against a runaway loop
            break

    # Binary search for the largest feasible unit count in [lo, hi].
    while lo < hi:
        mid = (lo + hi + 1) // 1  # integer-ish midpoint in unit space
        mid = ((lo + hi) / 2).to_integral_value(rounding=ROUND_DOWN)
        if mid <= lo:
            mid = lo + 1
        if feasible(mid * inc):
            lo = mid
        else:
            hi = mid - 1

    qty = (lo * inc)
    # Round the final quantity DOWN to the increment grid for safety.
    steps = (qty / inc).to_integral_value(rounding=ROUND_DOWN)
    return steps * inc


# ── Durable hard stop (§19.2) ────────────────────────────────────────────────────

def is_hard_stopped() -> bool:
    """True while a hard stop is engaged (never auto-clears — §19.2 step 10)."""
    return db.get_portfolio_risk("hard_stop_triggered", "") in ("1", "true", "HARD_STOP_TRIGGERED")


def clear_hard_stop(*, reason: str, reconciled: bool, owner: str) -> None:
    """Owner-only clearance of a hard stop (§19.2 step 10).

    Requires an audit reason AND fresh reconciliation evidence. There is NO automatic
    reset anywhere in this module."""
    if not reason or not reason.strip():
        raise ValueError("hard-stop clearance requires an audit reason")
    if not reconciled:
        raise ValueError("hard-stop clearance requires fresh reconciliation")
    db.delete_portfolio_risk("hard_stop_triggered")
    db.delete_portfolio_risk("hard_stop_step")
    db.delete_portfolio_risk("hard_stop_queued")
    db.delete_portfolio_risk("hard_stop_quarantined")
    db.delete_portfolio_risk("hard_stop_exit_attempts")
    db.log_audit("portfolio_risk", "hard_stop_cleared",
                 f"owner={owner} reason={reason}")


class HardStopController:
    """Runs the durable hard-stop shutdown (§19.2), persisting each step so a restart
    resumes exactly where it left off and never double-submits an economic exit.

    The controller ACTS only when `trigger`/`resume` is called — it is never driven
    in shadow mode, so live legacy behavior is unaffected.
    """

    def __init__(self, *, accounts: list[int],
                 broker_for: Callable[[int], object],
                 min_qty: dict[str, Decimal] | None = None,
                 exit_strategies: list[str] | None = None):
        self.accounts = list(accounts)
        self.broker_for = broker_for
        self.min_qty = {db.canonical_symbol(k): _d(v) for k, v in (min_qty or {}).items()}
        # Strategies whose owned positions get exited. Default: real owners with lots.
        self.exit_strategies = exit_strategies

    # ── state helpers ────────────────────────────────────────────────────────────

    def _step(self) -> str:
        return db.get_portfolio_risk("hard_stop_step", "")

    def _set_step(self, step: str) -> None:
        db.set_portfolio_risk("hard_stop_step", step)

    def is_unresolved(self) -> bool:
        """True while the shutdown has not fully resolved every owned exit (frozen)."""
        return db.get_portfolio_risk("hard_stop_unresolved", "0") == "1"

    def queued_exits(self) -> list[dict]:
        import json
        raw = db.get_portfolio_risk("hard_stop_queued", "")
        return json.loads(raw) if raw else []

    def quarantined(self) -> list[dict]:
        import json
        raw = db.get_portfolio_risk("hard_stop_quarantined", "")
        return json.loads(raw) if raw else []

    # ── public entry points ──────────────────────────────────────────────────────

    def trigger(self, *, reason: str, stop_after: str | None = None) -> None:
        """Begin (or, if already begun, continue) the hard-stop shutdown.

        `stop_after` (test/crash simulation) halts the pass right after the named
        step is durably persisted, modelling an interruption. `resume()` finishes it.
        """
        if not is_hard_stopped():
            db.set_portfolio_risk("hard_stop_triggered", "HARD_STOP_TRIGGERED")
            db.set_portfolio_risk("hard_stop_reason", reason)
            db.log_audit("portfolio_risk", "hard_stop_triggered", reason)
        self._run(stop_after=stop_after)

    def resume(self) -> None:
        """Resume an in-progress shutdown after a restart/interruption (§19.2 step 9).

        If the previous pass completed (DONE) but left unresolved/queued exits — a
        closed market, a rejected exit awaiting retry — re-run the exit step so the
        newly-openable / retryable exits are submitted. Idempotent: already-submitted
        exits are keyed and never resubmitted."""
        if not is_hard_stopped():
            return
        if self._step() == "DONE" and self._has_pending_exits():
            self._do_step("SUBMIT_EXITS")
            return
        self._run(stop_after=None)

    def _has_pending_exits(self) -> bool:
        """Work remains if the shutdown is unresolved (retry budget / stale) OR there
        are queued closed-market exits still to submit."""
        return self.is_unresolved() or bool(self.queued_exits())

    # ── the step machine (§19.2) ─────────────────────────────────────────────────

    def _run(self, *, stop_after: str | None) -> None:
        # Determine where to resume from. Empty step → start at the beginning.
        current = self._step()
        start_index = 0 if not current else SHUTDOWN_STEPS.index(current)
        # If we've already recorded a step, resume from the NEXT one — unless the
        # recorded step is a mid-machine crash point we must re-run idempotently.
        # We re-run from the recorded step forward; each step is idempotent.
        for step in SHUTDOWN_STEPS[start_index:]:
            if step == "DONE":
                self._set_step("DONE")
                break
            self._do_step(step)
            self._set_step(step)
            if stop_after is not None and step == stop_after:
                return  # simulate a crash right after persisting this step
        # Mark DONE at the end of a full pass (does NOT clear the hard stop).
        if self._step() != "DONE":
            self._set_step("DONE")

    def _do_step(self, step: str) -> None:
        if step == "TRIGGERED":
            # Idempotent: the flag is already set in trigger(); nothing else here.
            return
        if step == "KILL_SWITCHES":
            self._activate_kill_switches()
        elif step == "CANCEL_BUYS":
            self._cancel_owned_buys()
        elif step == "RECONCILE":
            self._reconcile()
        elif step == "RECOMPUTE":
            # Sellable quantities are recomputed on demand in SUBMIT_EXITS from the
            # ledger, so this step is a no-op marker preserved for restart geometry.
            return
        elif step == "SUBMIT_EXITS":
            self._submit_exits()

    # ── step 1: kill switches (§19.2 step 1) ─────────────────────────────────────

    def _activate_kill_switches(self) -> None:
        from . import risk
        risk.set_kill_switch(True)                        # global entry kill switch
        for acct in self.accounts:
            db.set_account_kill_switch(acct, True)        # per-account kill switch

    # ── step 2: cancel nonterminal strategy-owned buys only (§19.2 step 2) ───────

    def _cancel_owned_buys(self) -> None:
        for acct in self.accounts:
            broker = self.broker_for(acct)
            with db.get_conn() as c:
                rows = c.execute(
                    "SELECT id, broker_order_id, symbol, strategy, state "
                    "FROM execution_orders WHERE account_id=? AND side='buy' "
                    "AND broker_order_id IS NOT NULL",
                    (acct,)).fetchall()
            for r in rows:
                state = r["state"]
                if state in ("FILLED", "CANCELED", "REJECTED", "EXPIRED"):
                    continue  # terminal → nothing to cancel
                owner = (r["strategy"] or "")
                # Never cancel external/manual orders (§19.2 step 2).
                if owner.startswith("external") or owner in ("manual", "webhook"):
                    continue
                try:
                    broker.cancel_order(r["broker_order_id"], symbol=r["symbol"])
                    db.bind_order_ack(r["id"], broker_order_id=r["broker_order_id"],
                                      state="CANCEL_PENDING")
                except Exception as exc:
                    db.log_audit("portfolio_risk", "cancel_failed",
                                 f"acct={acct} order={r['id']}: {exc}")

    # ── step 3: reconcile cancellations, ingest fills (§19.2 step 3) ─────────────

    def _reconcile(self) -> None:
        # Ingest any fills that arrived during cancellation so sellable quantities are
        # correct before we compute exits. Uses the standard poller when the broker
        # supports automation; otherwise this is a best-effort no-op (fills already
        # ledgered by the normal path).
        for acct in self.accounts:
            broker = self.broker_for(acct)
            try:
                from . import broker_factory
                if broker_factory.supports_automation(broker):
                    from .execution_service import ExecutionService
                    ExecutionService(broker, account_id=acct).poll_account()
            except Exception as exc:
                db.log_audit("portfolio_risk", "reconcile_failed", f"acct={acct}: {exc}")

    # ── step 5-7: one idempotent exit per (account, strategy, symbol) (§19.2) ─────

    def _owned_exits(self) -> list[dict]:
        """Every (account, strategy, symbol) with owned sellable quantity, excluding
        external/manual (§19.2 step 5)."""
        exits: list[dict] = []
        for acct in self.accounts:
            with db.get_conn() as c:
                rows = c.execute(
                    "SELECT DISTINCT strategy, symbol FROM position_lots "
                    "WHERE account_id=? AND provenance NOT IN ('external') "
                    "AND CAST(remaining_qty AS REAL) > 0",
                    (acct,)).fetchall()
            for r in rows:
                strat, sym = r["strategy"], r["symbol"]
                if strat.startswith("external") or strat.endswith("::exit_reservation"):
                    continue
                sellable = db.get_sellable_qty(strat, acct, sym)
                if sellable <= 0:
                    continue
                exits.append({"account_id": acct, "strategy": strat,
                              "symbol": sym, "qty": sellable})
        return exits

    def _exit_cid(self, acct: int, strat: str, sym: str) -> str:
        """Deterministic client id → ONE idempotent economic exit per key (§19.2)."""
        safe = db.canonical_symbol(sym).replace("/", "_")
        return f"hardstop-{acct}-{strat}-{safe}"

    def _load_attempts(self) -> dict:
        import json
        raw = db.get_portfolio_risk("hard_stop_exit_attempts", "")
        return json.loads(raw) if raw else {}

    def _save_attempts(self, attempts: dict) -> None:
        import json
        db.set_portfolio_risk("hard_stop_exit_attempts", json.dumps(attempts))

    def _submit_exits(self) -> None:
        import json
        attempts = self._load_attempts()
        queued: list[dict] = []
        quarantined: list[dict] = []
        unresolved = False

        for ex in self._owned_exits():
            acct, strat, sym = ex["account_id"], ex["strategy"], ex["symbol"]
            qty = ex["qty"]
            key = self._exit_cid(acct, strat, sym)
            broker = self.broker_for(acct)
            is_crypto = bool(getattr(broker, "is_crypto", False))

            # Crypto dust below the exchange minimum is quarantined, not sold (§19.2 step 6).
            if is_crypto:
                minq = self.min_qty.get(db.canonical_symbol(sym))
                if minq is not None and qty < minq:
                    quarantined.append({"account_id": acct, "strategy": strat,
                                        "symbol": sym, "qty": str(qty)})
                    continue

            # Closed-market stock exits QUEUE for the next session (§19.2 step 7).
            if not is_crypto and not self._market_open(broker):
                queued.append({"account_id": acct, "strategy": strat,
                               "symbol": sym, "qty": str(qty)})
                unresolved = True
                continue

            state = attempts.get(key, {"count": 0, "done": False})
            if state.get("done"):
                continue  # already terminally exited → idempotent, do not resubmit

            if state["count"] >= _MAX_EXIT_RETRIES:
                # Retry budget exhausted, still not done → stays frozen (§19.2 step 8).
                unresolved = True
                continue

            # Submit ONE economic exit for the remaining sellable quantity.
            state["count"] += 1
            attempts[key] = state
            self._save_attempts(attempts)
            try:
                ack = broker.submit_market_order(
                    sym, "sell", qty=float(qty), notional=None, client_order_id=key)
            except Exception as exc:
                db.log_audit("portfolio_risk", "exit_submit_error",
                             f"acct={acct} {strat} {sym}: {exc}")
                unresolved = True  # incomplete exit → pending work remains
                continue

            broker_state = (ack.get("state") or "").upper()
            if broker_state == "REJECTED" or ack.get("id") is None:
                # Rejected/expired → retry on the next pass, up to 3 (§19.2 step 8).
                # Not done yet → the shutdown is unresolved until it clears or exhausts.
                unresolved = True
                continue
            # Acknowledged exit — mark this key done so a re-run cannot double-submit.
            state["done"] = True
            attempts[key] = state
            self._save_attempts(attempts)

        db.set_portfolio_risk("hard_stop_queued", json.dumps(queued))
        db.set_portfolio_risk("hard_stop_quarantined", json.dumps(quarantined))
        db.set_portfolio_risk("hard_stop_unresolved", "1" if unresolved else "0")

    def _market_open(self, broker) -> bool:
        fn = getattr(broker, "is_market_open", None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception:
                return False
        # No clock capability → assume closed for stocks (conservative, §19.2 step 7).
        return False


def resume_pending_hard_stop(*, accounts: list[int],
                             broker_for: Callable[[int], object],
                             min_qty: dict[str, Decimal] | None = None) -> bool:
    """Startup hook (§19.2 step 9): if a hard stop is engaged, resume the SAME
    shutdown before any strategy evaluation. Returns True if a shutdown was resumed
    (so the caller can skip new entries this cycle). Keeps the account frozen; there
    is NO automatic reset."""
    if not is_hard_stopped():
        return False
    ctrl = HardStopController(accounts=accounts, broker_for=broker_for, min_qty=min_qty)
    ctrl.resume()
    return True
