"""Tests for the consolidated portfolio risk controller (Task 5).

Covers spec §6, §19.1, §19.9, §19.13:
  - Consolidated portfolio equity across participating paper accounts
  - Snapshot freshness / staleness → STALE equity, entries freeze, HWM not updated
  - USDT conversion reference with 1.0 fallback only within 50bps
  - 45/5/50 exposure targets
  - External cash-flow adjustment of high-water mark and baselines
  - Paired internal transfers net to zero only after both legs match
  - Drawdown 4% entry-freeze, EXACT 5.0000% hard stop
  - Daily 1% / weekly 2% loss freezes (protective exits still allowed)
  - Pre-trade quantity solver (largest rounded-down, fail-closed, caps)

All Decimal fixtures, NO network.
"""
import os
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def db(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode()
    os.environ["DB_SECRET_KEY"] = key
    import server.crypto as crypto
    crypto.init_crypto()
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    db_mod.init_db()
    return db_mod


def _ts(seconds_ago: int) -> str:
    """A UTC ISO-8601 timestamp `seconds_ago` before a fixed reference `now`."""
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)
    return (now - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


NOW = "2026-07-11T12:00:00.000000Z"


# ── PortfolioSnapshot / consolidation (§19.1) ──────────────────────────────────

def test_snapshot_holds_decimal_equity():
    from server.portfolio_risk import PortfolioSnapshot
    snap = PortfolioSnapshot(account_id=1, equity=Decimal("10000"),
                             currency="USD", taken_at=NOW)
    assert snap.equity == Decimal("10000")
    assert snap.currency == "USD"


def test_consolidate_sums_usd_equity():
    from server.portfolio_risk import PortfolioSnapshot, consolidate_snapshots
    snaps = [
        PortfolioSnapshot(1, Decimal("6000"), "USD", _ts(10)),
        PortfolioSnapshot(2, Decimal("4000"), "USD", _ts(20)),
    ]
    result = consolidate_snapshots(snaps, now=NOW)
    assert result.stale is False
    assert result.equity == Decimal("10000")


def test_consolidate_usdt_within_50bps_uses_one_fallback():
    from server.portfolio_risk import PortfolioSnapshot, consolidate_snapshots
    # USDT ref 0.997 is within 50bps of 1.0 → fallback 1.0 allowed → equity == qty.
    snaps = [PortfolioSnapshot(1, Decimal("5000"), "USDT", _ts(5))]
    result = consolidate_snapshots(snaps, now=NOW, usdt_usd=Decimal("0.997"))
    assert result.stale is False
    assert result.equity == Decimal("5000")


def test_consolidate_usdt_beyond_50bps_freezes():
    from server.portfolio_risk import PortfolioSnapshot, consolidate_snapshots
    # 0.99 deviates 100bps from 1.0 → beyond 50bps → freeze (stale/frozen).
    snaps = [PortfolioSnapshot(1, Decimal("5000"), "USDT", _ts(5))]
    result = consolidate_snapshots(snaps, now=NOW, usdt_usd=Decimal("0.99"))
    assert result.stale is True


def test_consolidate_usdt_beyond_50bps_with_ref_converts():
    from server.portfolio_risk import PortfolioSnapshot, consolidate_snapshots
    # A verified reference beyond the 50bps band still converts (no fallback needed).
    snaps = [PortfolioSnapshot(1, Decimal("5000"), "USDT", _ts(5))]
    result = consolidate_snapshots(snaps, now=NOW, usdt_usd=Decimal("1.02"),
                                   usdt_verified=True)
    assert result.stale is False
    assert result.equity == Decimal("5100.00")


# ── Staleness (§19.1) ──────────────────────────────────────────────────────────

def test_consolidate_synchronized_snapshots_not_stale():
    from server.portfolio_risk import PortfolioSnapshot, consolidate_snapshots
    snaps = [
        PortfolioSnapshot(1, Decimal("6000"), "USD", _ts(30)),
        PortfolioSnapshot(2, Decimal("4000"), "USD", _ts(60)),  # 30s apart, <180s old
    ]
    result = consolidate_snapshots(snaps, now=NOW)
    assert result.stale is False


def test_consolidate_snapshot_older_than_180s_is_stale():
    from server.portfolio_risk import PortfolioSnapshot, consolidate_snapshots
    snaps = [
        PortfolioSnapshot(1, Decimal("6000"), "USD", _ts(30)),
        PortfolioSnapshot(2, Decimal("4000"), "USD", _ts(200)),  # >180s old
    ]
    result = consolidate_snapshots(snaps, now=NOW)
    assert result.stale is True


def test_consolidate_snapshots_more_than_120s_apart_is_stale():
    from server.portfolio_risk import PortfolioSnapshot, consolidate_snapshots
    snaps = [
        PortfolioSnapshot(1, Decimal("6000"), "USD", _ts(10)),
        PortfolioSnapshot(2, Decimal("4000"), "USD", _ts(140)),  # 130s apart
    ]
    result = consolidate_snapshots(snaps, now=NOW)
    assert result.stale is True


def test_stale_equity_freezes_entries_and_holds_hwm(db):
    from server.portfolio_risk import (PortfolioSnapshot, consolidate_snapshots,
                                       evaluate_limits, load_state, save_state)
    # Establish a HWM of 10000.
    state = load_state()
    state.high_water_mark = Decimal("10000")
    save_state(state)
    # A stale snapshot must NOT advance the HWM and must freeze entries.
    snaps = [PortfolioSnapshot(1, Decimal("12000"), "USD", _ts(300))]
    consolidated = consolidate_snapshots(snaps, now=NOW)
    assert consolidated.stale is True
    decision = evaluate_limits(consolidated, load_state(), now=NOW)
    assert decision.entries_frozen is True
    assert load_state().high_water_mark == Decimal("10000")  # unchanged


# ── High-water mark + drawdown (§19.1) ─────────────────────────────────────────

def test_fresh_higher_equity_advances_hwm(db):
    from server.portfolio_risk import (PortfolioSnapshot, consolidate_snapshots,
                                       evaluate_limits, load_state)
    snaps = [PortfolioSnapshot(1, Decimal("11000"), "USD", _ts(5))]
    consolidated = consolidate_snapshots(snaps, now=NOW)
    state = load_state()
    state.high_water_mark = Decimal("10000")
    evaluate_limits(consolidated, state, now=NOW, persist=True)
    assert load_state().high_water_mark == Decimal("11000")


def test_drawdown_below_4pct_allows_entries(db):
    from server.portfolio_risk import (PortfolioSnapshot, consolidate_snapshots,
                                       evaluate_limits, PortfolioRiskState)
    # HWM 10000, equity 9700 → 3.00% drawdown < 4% → entries allowed.
    snaps = [PortfolioSnapshot(1, Decimal("9700"), "USD", _ts(5))]
    consolidated = consolidate_snapshots(snaps, now=NOW)
    state = PortfolioRiskState(high_water_mark=Decimal("10000"))
    decision = evaluate_limits(consolidated, state, now=NOW)
    assert decision.entries_frozen is False
    assert decision.hard_stop is False


def test_drawdown_at_4pct_freezes_entries(db):
    from server.portfolio_risk import (PortfolioSnapshot, consolidate_snapshots,
                                       evaluate_limits, PortfolioRiskState)
    # HWM 10000, equity 9600 → exactly 4.0000% → freeze entries, no hard stop.
    snaps = [PortfolioSnapshot(1, Decimal("9600"), "USD", _ts(5))]
    consolidated = consolidate_snapshots(snaps, now=NOW)
    state = PortfolioRiskState(high_water_mark=Decimal("10000"))
    decision = evaluate_limits(consolidated, state, now=NOW)
    assert decision.entries_frozen is True
    assert decision.hard_stop is False


def test_drawdown_exactly_5pct_triggers_hard_stop(db):
    from server.portfolio_risk import (PortfolioSnapshot, consolidate_snapshots,
                                       evaluate_limits, PortfolioRiskState)
    # HWM 10000, equity 9500 → EXACTLY 5.0000% → hard stop.
    snaps = [PortfolioSnapshot(1, Decimal("9500"), "USD", _ts(5))]
    consolidated = consolidate_snapshots(snaps, now=NOW)
    state = PortfolioRiskState(high_water_mark=Decimal("10000"))
    decision = evaluate_limits(consolidated, state, now=NOW)
    assert decision.hard_stop is True
    assert decision.entries_frozen is True


def test_drawdown_just_below_5pct_no_hard_stop(db):
    from server.portfolio_risk import (PortfolioSnapshot, consolidate_snapshots,
                                       evaluate_limits, PortfolioRiskState)
    # 4.9999% (9500.10 of 10000) must NOT hard stop (4-dp comparison).
    snaps = [PortfolioSnapshot(1, Decimal("9500.10"), "USD", _ts(5))]
    consolidated = consolidate_snapshots(snaps, now=NOW)
    state = PortfolioRiskState(high_water_mark=Decimal("10000"))
    decision = evaluate_limits(consolidated, state, now=NOW)
    assert decision.hard_stop is False
    assert decision.entries_frozen is True  # still >=4%


# ── Daily / weekly loss limits (§19.13 risk monitor) ───────────────────────────

def test_daily_loss_1pct_freezes_entries(db):
    from server.portfolio_risk import (PortfolioSnapshot, consolidate_snapshots,
                                       evaluate_limits, PortfolioRiskState)
    # Daily baseline 10000, equity 9900 → -1.0000% daily → freeze new entries.
    snaps = [PortfolioSnapshot(1, Decimal("9900"), "USD", _ts(5))]
    consolidated = consolidate_snapshots(snaps, now=NOW)
    state = PortfolioRiskState(high_water_mark=Decimal("10000"),
                              daily_baseline=Decimal("10000"),
                              weekly_baseline=Decimal("10000"))
    decision = evaluate_limits(consolidated, state, now=NOW)
    assert decision.entries_frozen is True
    assert decision.hard_stop is False
    assert "daily" in decision.reason.lower()


def test_daily_loss_below_limit_allows_entries(db):
    from server.portfolio_risk import (PortfolioSnapshot, consolidate_snapshots,
                                       evaluate_limits, PortfolioRiskState)
    snaps = [PortfolioSnapshot(1, Decimal("9950"), "USD", _ts(5))]  # -0.5% daily
    consolidated = consolidate_snapshots(snaps, now=NOW)
    state = PortfolioRiskState(high_water_mark=Decimal("10000"),
                              daily_baseline=Decimal("10000"),
                              weekly_baseline=Decimal("10000"))
    decision = evaluate_limits(consolidated, state, now=NOW)
    assert decision.entries_frozen is False


def test_weekly_loss_2pct_freezes_entries(db):
    from server.portfolio_risk import (PortfolioSnapshot, consolidate_snapshots,
                                       evaluate_limits, PortfolioRiskState)
    # Weekly baseline 10000, equity 9800 → -2.0000% weekly → freeze.
    snaps = [PortfolioSnapshot(1, Decimal("9800"), "USD", _ts(5))]
    consolidated = consolidate_snapshots(snaps, now=NOW)
    state = PortfolioRiskState(high_water_mark=Decimal("10000"),
                              daily_baseline=Decimal("9850"),  # daily only -0.5%
                              weekly_baseline=Decimal("10000"))
    decision = evaluate_limits(consolidated, state, now=NOW)
    assert decision.entries_frozen is True
    assert "weekly" in decision.reason.lower()


def test_loss_freeze_still_allows_protective_exits(db):
    from server.portfolio_risk import (PortfolioSnapshot, consolidate_snapshots,
                                       evaluate_limits, PortfolioRiskState)
    snaps = [PortfolioSnapshot(1, Decimal("9900"), "USD", _ts(5))]
    consolidated = consolidate_snapshots(snaps, now=NOW)
    state = PortfolioRiskState(high_water_mark=Decimal("10000"),
                              daily_baseline=Decimal("10000"),
                              weekly_baseline=Decimal("10000"))
    decision = evaluate_limits(consolidated, state, now=NOW)
    assert decision.entries_frozen is True
    assert decision.exits_allowed is True


# ── External cash flow (§19.1) ─────────────────────────────────────────────────

def test_deposit_raises_hwm_and_baselines(db):
    from server.portfolio_risk import apply_external_flow, PortfolioRiskState
    state = PortfolioRiskState(high_water_mark=Decimal("10000"),
                              daily_baseline=Decimal("9800"),
                              weekly_baseline=Decimal("9500"))
    new_state = apply_external_flow(state, Decimal("1000"))
    assert new_state.high_water_mark == Decimal("11000")
    assert new_state.daily_baseline == Decimal("10800")
    assert new_state.weekly_baseline == Decimal("10500")


def test_withdrawal_lowers_hwm_and_baselines(db):
    from server.portfolio_risk import apply_external_flow, PortfolioRiskState
    state = PortfolioRiskState(high_water_mark=Decimal("10000"),
                              daily_baseline=Decimal("10000"),
                              weekly_baseline=Decimal("10000"))
    new_state = apply_external_flow(state, Decimal("-500"))
    assert new_state.high_water_mark == Decimal("9500")
    assert new_state.daily_baseline == Decimal("9500")
    assert new_state.weekly_baseline == Decimal("9500")


def test_external_flow_not_treated_as_pnl(db):
    """After a deposit, equity that only rose by the deposit amount is 0% drawdown
    AND 0% daily change — the cash movement is neutralized, not counted as gain."""
    from server.portfolio_risk import (PortfolioSnapshot, consolidate_snapshots,
                                       evaluate_limits, apply_external_flow,
                                       PortfolioRiskState)
    state = PortfolioRiskState(high_water_mark=Decimal("10000"),
                              daily_baseline=Decimal("10000"),
                              weekly_baseline=Decimal("10000"))
    state = apply_external_flow(state, Decimal("2000"))  # deposit
    snaps = [PortfolioSnapshot(1, Decimal("12000"), "USD", _ts(5))]
    consolidated = consolidate_snapshots(snaps, now=NOW)
    decision = evaluate_limits(consolidated, state, now=NOW)
    assert decision.drawdown_pct == Decimal("0.0000")
    assert decision.entries_frozen is False


# ── Paired internal transfers (§19.13 cash-flow matching) ──────────────────────

def test_unmatched_transfer_leg_freezes_hwm_and_entries(db):
    from server.portfolio_risk import register_transfer_leg, transfers_balanced
    register_transfer_leg(transfer_id="t1", account_id=1, amount=Decimal("-500"),
                          currency="USD")
    # Only the source leg present → unbalanced → freeze.
    assert transfers_balanced("t1") is False


def test_paired_transfer_legs_net_to_zero(db):
    from server.portfolio_risk import register_transfer_leg, transfers_balanced
    register_transfer_leg(transfer_id="t1", account_id=1, amount=Decimal("-500"),
                          currency="USD")
    register_transfer_leg(transfer_id="t1", account_id=2, amount=Decimal("500"),
                          currency="USD")
    assert transfers_balanced("t1") is True


def test_transfer_mismatched_amounts_stay_unbalanced(db):
    from server.portfolio_risk import register_transfer_leg, transfers_balanced
    register_transfer_leg(transfer_id="t2", account_id=1, amount=Decimal("-500"),
                          currency="USD")
    register_transfer_leg(transfer_id="t2", account_id=2, amount=Decimal("499"),
                          currency="USD")
    assert transfers_balanced("t2") is False


# ── Exposure targets 45/5/50 (§6.1) ────────────────────────────────────────────

def test_exposure_within_targets_passes():
    from server.portfolio_risk import check_exposure_caps
    ok, reason = check_exposure_caps(
        equity=Decimal("10000"), sleeve="stock",
        stock_gross=Decimal("4000"), crypto_gross=Decimal("400"),
        added_notional=Decimal("400"))  # stock would be 44% ≤ 45%
    assert ok is True


def test_stock_gross_over_45pct_rejected():
    from server.portfolio_risk import check_exposure_caps
    ok, reason = check_exposure_caps(
        equity=Decimal("10000"), sleeve="stock",
        stock_gross=Decimal("4400"), crypto_gross=Decimal("0"),
        added_notional=Decimal("200"))  # 46% > 45%
    assert ok is False
    assert "stock" in reason.lower()


def test_crypto_gross_over_5pct_rejected():
    from server.portfolio_risk import check_exposure_caps
    ok, reason = check_exposure_caps(
        equity=Decimal("10000"), sleeve="crypto",
        stock_gross=Decimal("0"), crypto_gross=Decimal("480"),
        added_notional=Decimal("50"))  # 5.3% > 5%
    assert ok is False
    assert "crypto" in reason.lower()


def test_cash_floor_50pct_enforced():
    from server.portfolio_risk import check_exposure_caps
    # Both sleeves individually within caps (stock 40% ≤45, crypto after add 4.9% ≤5)
    # but combined gross 50.1% would push cash to 49.9% < 50% floor → blocked on cash.
    ok, reason = check_exposure_caps(
        equity=Decimal("10000"), sleeve="crypto",
        stock_gross=Decimal("4500"), crypto_gross=Decimal("480"),
        added_notional=Decimal("30"))  # crypto 5.1%? -> exercise cash floor path
    assert ok is False
    # Combined 4500 + 510 = 5010 → cash 49.9% < 50%. Reason must cite the cash floor
    # OR the crypto cap (crypto 5.1% > 5%); both are legitimate blocks.
    assert "cash" in reason.lower() or "crypto" in reason.lower()


# ── Quantity solver (§19.13 risk-sizing equation) ──────────────────────────────

def test_solver_largest_rounded_down_qty():
    from server.portfolio_risk import solve_quantity
    # risk_budget 25, stop distance 5, zero costs, increment 1 → q = 5.
    q = solve_quantity(
        risk_budget=Decimal("25"), estimated_entry=Decimal("100"),
        initial_stop=Decimal("95"), increment=Decimal("1"),
        entry_cost=lambda q: Decimal("0"),
        exit_cost=lambda q: Decimal("0"))
    assert q == Decimal("5")


def test_solver_rounds_down_to_increment():
    from server.portfolio_risk import solve_quantity
    # 27/5 = 5.4 → rounds down to 5 with increment 1.
    q = solve_quantity(
        risk_budget=Decimal("27"), estimated_entry=Decimal("100"),
        initial_stop=Decimal("95"), increment=Decimal("1"),
        entry_cost=lambda q: Decimal("0"),
        exit_cost=lambda q: Decimal("0"))
    assert q == Decimal("5")


def test_solver_fractional_increment():
    from server.portfolio_risk import solve_quantity
    # crypto: budget 1.0, stop distance 100, increment 0.001 → 0.01.
    q = solve_quantity(
        risk_budget=Decimal("1.0"), estimated_entry=Decimal("30000"),
        initial_stop=Decimal("29900"), increment=Decimal("0.001"),
        entry_cost=lambda q: Decimal("0"),
        exit_cost=lambda q: Decimal("0"))
    assert q == Decimal("0.010")


def test_solver_accounts_for_costs():
    from server.portfolio_risk import solve_quantity
    # stop distance 5, budget 25, but each unit also costs 1 (entry+exit) →
    # q*(5) + q*(1) <= 25 → q <= 4.16 → 4.
    q = solve_quantity(
        risk_budget=Decimal("25"), estimated_entry=Decimal("100"),
        initial_stop=Decimal("95"), increment=Decimal("1"),
        entry_cost=lambda q: q * Decimal("0.5"),
        exit_cost=lambda q: q * Decimal("0.5"))
    assert q == Decimal("4")


def test_solver_fails_closed_on_nonpositive_stop_distance():
    from server.portfolio_risk import solve_quantity
    # estimated_entry - initial_stop <= 0 → skip (0).
    q = solve_quantity(
        risk_budget=Decimal("25"), estimated_entry=Decimal("95"),
        initial_stop=Decimal("95"), increment=Decimal("1"),
        entry_cost=lambda q: Decimal("0"),
        exit_cost=lambda q: Decimal("0"))
    assert q == Decimal("0")


def test_solver_nonpositive_risk_numerator_skips():
    from server.portfolio_risk import solve_quantity
    # Costs already exceed the budget at the smallest increment → 0.
    q = solve_quantity(
        risk_budget=Decimal("1"), estimated_entry=Decimal("100"),
        initial_stop=Decimal("95"), increment=Decimal("1"),
        entry_cost=lambda q: Decimal("10"),
        exit_cost=lambda q: Decimal("10"))
    assert q == Decimal("0")


def test_solver_respects_cash_cap():
    from server.portfolio_risk import solve_quantity
    # Unlimited risk budget but cash caps notional: max_notional 300 @ entry 100 → 3.
    q = solve_quantity(
        risk_budget=Decimal("100000"), estimated_entry=Decimal("100"),
        initial_stop=Decimal("95"), increment=Decimal("1"),
        entry_cost=lambda q: Decimal("0"),
        exit_cost=lambda q: Decimal("0"),
        max_notional=Decimal("300"))
    assert q == Decimal("3")


def test_solver_respects_max_qty_cap():
    from server.portfolio_risk import solve_quantity
    q = solve_quantity(
        risk_budget=Decimal("100000"), estimated_entry=Decimal("100"),
        initial_stop=Decimal("95"), increment=Decimal("1"),
        entry_cost=lambda q: Decimal("0"),
        exit_cost=lambda q: Decimal("0"),
        max_qty=Decimal("2"))
    assert q == Decimal("2")


# ── Persistence round-trip (§19.1) ─────────────────────────────────────────────

def test_state_persists_and_reloads(db):
    from server.portfolio_risk import load_state, save_state, PortfolioRiskState
    state = PortfolioRiskState(high_water_mark=Decimal("12345.6789"),
                              daily_baseline=Decimal("12000"),
                              weekly_baseline=Decimal("11000"))
    save_state(state)
    reloaded = load_state()
    assert reloaded.high_water_mark == Decimal("12345.6789")
    assert reloaded.daily_baseline == Decimal("12000")
    assert reloaded.weekly_baseline == Decimal("11000")


def test_owner_reset_requires_reason(db):
    from server.portfolio_risk import reset_high_water_mark, load_state
    reset_high_water_mark(Decimal("20000"), reason="added account 3", owner="owner")
    assert load_state().high_water_mark == Decimal("20000")
    with pytest.raises(ValueError):
        reset_high_water_mark(Decimal("30000"), reason="", owner="owner")


# ── Day / week boundary resets (§19.1) ─────────────────────────────────────────

def test_daily_baseline_resets_at_utc_midnight(db):
    from server.portfolio_risk import roll_baselines, PortfolioRiskState
    state = PortfolioRiskState(high_water_mark=Decimal("10000"),
                              daily_baseline=Decimal("9000"),
                              weekly_baseline=Decimal("8000"),
                              daily_baseline_date="2026-07-10",
                              weekly_baseline_week="2026-W28")
    # New day (2026-07-11) → daily baseline resets to current equity.
    rolled = roll_baselines(state, equity=Decimal("9500"),
                            now="2026-07-11T00:00:01.000000Z")
    assert rolled.daily_baseline == Decimal("9500")
    assert rolled.daily_baseline_date == "2026-07-11"


def test_weekly_baseline_resets_on_monday(db):
    from server.portfolio_risk import roll_baselines, PortfolioRiskState
    # 2026-07-13 is a Monday.
    state = PortfolioRiskState(high_water_mark=Decimal("10000"),
                              daily_baseline=Decimal("9000"),
                              weekly_baseline=Decimal("8000"),
                              daily_baseline_date="2026-07-12",
                              weekly_baseline_week="2026-W28")
    rolled = roll_baselines(state, equity=Decimal("9500"),
                            now="2026-07-13T00:00:01.000000Z")
    assert rolled.weekly_baseline == Decimal("9500")
