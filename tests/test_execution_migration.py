"""Task 10 — shadow migration, bootstrap classification, cutover guards, rollback.

RED-first tests (spec §14 rollout, §16 operational controls, §19.6 bootstrap
classification, §19.7 order-path coverage, §19.8 migration authority + rollback).

Every test uses a COPIED legacy DB fixture: a fresh init_db() database seeded with
legacy `signals` / `open_trades` rows (the pre-ledger world), then COPIED so a
dry-run runs against the copy without mutating the "production" original.

Migration guarantees proved here:
  - additive, transactional, VERSIONED, RERUNNABLE (run twice → no error, no row loss)
  - unknown legacy inventory is QUARANTINED, never auto-adopted as an owned lot
  - classification: legacy_verified (confirmed terminal broker order) vs
    legacy_unverified vs external/manual (uncovered broker qty); age never infers owner
  - owner adoption requires evidence + exact account/symbol/qty/owner + audit reason,
    and adopted qty cannot exceed the unexplained reconciled amount
  - CUTOVER is GATED: blocked unless every guard passes (backup marker, zero unknown
    nonterminal orders, reconciliation pass, paper-accounts-only, retention capability,
    golden compatibility). Default stays SHADOW.
  - authority switch is ATOMIC; the old submit path FAILS CLOSED after the switch
  - a retention gap (downtime beyond broker fill retention) FREEZES rather than adopts
  - post-cutover rollback is FORWARD recovery and leaves the account FAIL-CLOSED until
    a fresh reconciliation passes

No network. DB is an isolated per-test SQLite file under tmp_path.
"""
from __future__ import annotations

import shutil
from decimal import Decimal

import pytest


# ── Isolated DB + a copied-legacy-DB fixture ─────────────────────────────────────

@pytest.fixture
def db(tmp_path, monkeypatch):
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "prod.db")
    db_mod.init_db()
    return db_mod


@pytest.fixture
def acct(db):
    """A real PAPER broker account row so account FKs resolve and paper-only guard passes."""
    return db.create_broker_account(
        label="paper-mig", api_key_enc="k", api_secret_enc="s",
        account_type="paper", broker="alpaca",
    )


def _seed_legacy_inventory(db, account_id):
    """Seed the pre-ledger world: legacy open_trades (open buys) + signals.

    sma_cross opened 5 AAPL @100 and 3 MSFT @200 (legacy attribution present).
    A bare 'manual' open buy for TSLA exists with NO strategy evidence.
    """
    db.record_open_trade("sma_cross", "AAPL", account_id, 5.0, 100.0)
    db.record_open_trade("sma_cross", "MSFT", account_id, 3.0, 200.0)
    db.record_open_trade("manual", "TSLA", account_id, 2.0, 300.0)


def _copy_db(src_path, dst_path):
    shutil.copy2(src_path, dst_path)
    return dst_path


# ── Schema versioning (additive, rerunnable) ─────────────────────────────────────

def test_schema_version_is_set_and_monotonic(db):
    import server.migration as mig
    v = mig.current_schema_version(db)
    assert isinstance(v, int)
    assert v >= mig.LEDGER_SCHEMA_VERSION


def test_run_shadow_migration_is_rerunnable_no_row_loss(db, acct):
    import server.migration as mig
    _seed_legacy_inventory(db, acct)

    def _counts():
        with db.get_conn() as c:
            ot = c.execute("SELECT COUNT(*) AS n FROM open_trades").fetchone()["n"]
            lots = c.execute("SELECT COUNT(*) AS n FROM position_lots").fetchone()["n"]
        return ot, lots

    r1 = mig.run_shadow_migration(db, acct)
    ot1, lots1 = _counts()
    # Legacy source rows are NOT destroyed (additive migration).
    assert ot1 == 3
    assert lots1 >= 3

    # Rerun: no error, and NO row growth / loss (idempotent).
    r2 = mig.run_shadow_migration(db, acct)
    ot2, lots2 = _counts()
    assert ot2 == ot1
    assert lots2 == lots1
    assert r2["classified"] == r1["classified"]


# ── Bootstrap classification (§19.6) ─────────────────────────────────────────────

def test_legacy_inventory_is_quarantined_not_owned(db, acct):
    """Classified legacy lots must NOT be sellable by the strategy that legacy
    attribution names — ownership is not auto-adopted (§19.6)."""
    import server.migration as mig
    _seed_legacy_inventory(db, acct)
    mig.run_shadow_migration(db, acct)
    # The real strategy owns NOTHING adoptable yet — legacy is quarantined.
    assert db.get_sellable_qty("sma_cross", acct, "AAPL") == Decimal("0")
    assert db.get_strategy_positions("sma_cross", acct) == {}


def test_classification_legacy_verified_requires_terminal_broker_order(db, acct):
    """A legacy holding covered by a CONFIRMED TERMINAL broker order classifies as
    legacy_verified; one without such evidence is legacy_unverified (§19.6)."""
    import server.migration as mig
    _seed_legacy_inventory(db, acct)
    # Evidence: an authoritative TERMINAL (FILLED) broker order that covers AAPL 5.
    oid = db.create_order_intent(account_id=acct, strategy="sma_cross",
                                 client_order_id="legacy-aapl-1", symbol="AAPL",
                                 side="buy", order_type="market", requested_qty="5")
    db.bind_order_ack(oid, broker_order_id="broker-aapl-1", state="FILLED")

    rows = mig.classify_bootstrap_inventory(db, acct)
    by_sym = {r["symbol"]: r for r in rows}
    assert by_sym["AAPL"]["classification"] == "legacy_verified"
    # MSFT has legacy attribution but NO terminal broker order → unverified.
    assert by_sym["MSFT"]["classification"] == "legacy_unverified"


def test_uncovered_broker_quantity_is_external_manual(db, acct):
    """Broker holds quantity with no matching internal lot/legacy record → external/manual
    quarantine; a strategy can never sell it (§19.6)."""
    import server.migration as mig
    _seed_legacy_inventory(db, acct)
    mig.run_shadow_migration(db, acct)
    # Broker reports 9 DOGE we have no internal record of at all.
    rows = mig.reconcile_after_migration(
        db, acct, broker_positions={"DOGE": "9"})
    doge = [r for r in rows if r["symbol"] == "DOGE"][0]
    assert doge["classification"] == "external/manual"
    assert doge["status"] == "FROZEN"


def test_ownership_never_inferred_by_age(db, acct):
    """Even the OLDEST legacy lot is not auto-adopted to a strategy (§19.6)."""
    import server.migration as mig
    _seed_legacy_inventory(db, acct)
    mig.run_shadow_migration(db, acct)
    # No strategy owns anything by virtue of being oldest.
    assert db.get_strategy_positions("sma_cross", acct) == {}
    assert db.get_strategy_positions("manual", acct) == {}


# ── Owner adoption (evidence-bounded) ────────────────────────────────────────────

def test_owner_adoption_requires_audit_reason(db, acct):
    import server.migration as mig
    _seed_legacy_inventory(db, acct)
    mig.run_shadow_migration(db, acct)
    with pytest.raises(ValueError):
        mig.adopt_owner(db, account_id=acct, symbol="AAPL", owner="sma_cross",
                        qty="5", unexplained_qty="5", reason="")


def test_owner_adoption_cannot_exceed_unexplained_reconciled_amount(db, acct):
    """Adopted qty cannot exceed the unexplained reconciled amount (§19.6)."""
    import server.migration as mig
    _seed_legacy_inventory(db, acct)
    mig.run_shadow_migration(db, acct)
    with pytest.raises(ValueError):
        mig.adopt_owner(db, account_id=acct, symbol="AAPL", owner="sma_cross",
                        qty="5", unexplained_qty="3", reason="operator confirmed")


def test_owner_adoption_makes_quantity_owned_and_audits(db, acct):
    import server.migration as mig
    _seed_legacy_inventory(db, acct)
    mig.run_shadow_migration(db, acct)
    n_before = len(db.list_audit(limit=500))
    mig.adopt_owner(db, account_id=acct, symbol="AAPL", owner="sma_cross",
                    qty="5", unexplained_qty="5", reason="operator confirmed AAPL 5")
    assert db.get_sellable_qty("sma_cross", acct, "AAPL") == Decimal("5")
    audits = db.list_audit(limit=500)
    assert len(audits) > n_before
    assert any(a["action"] == "owner_adopted" for a in audits)


# ── Dry-run report (against a COPIED legacy DB) ──────────────────────────────────

def test_dry_run_reports_without_mutating_copy(db, acct, tmp_path, monkeypatch):
    """A dry-run runs against a COPIED legacy DB and writes NOTHING to it (§19.8)."""
    import server.db as db_mod
    import server.migration as mig
    _seed_legacy_inventory(db, acct)

    copy_path = _copy_db(db_mod.DB_PATH, tmp_path / "backup-copy.db")

    def _lot_count(path):
        import sqlite3
        c = sqlite3.connect(path)
        try:
            return c.execute("SELECT COUNT(*) FROM position_lots").fetchone()[0]
        finally:
            c.close()

    before = _lot_count(copy_path)
    report = mig.dry_run_report(str(copy_path))
    after = _lot_count(copy_path)
    assert before == after                       # copy untouched
    assert report["legacy_open_trades"] == 3
    assert report["would_classify"] >= 3
    assert report["destructive"] is False


# ── Cutover guards (§19.8) ───────────────────────────────────────────────────────

def _pass_all_guards(db, mig, acct):
    """Make every cutover guard pass for the account."""
    mig.run_shadow_migration(db, acct)
    mig.set_backup_marker(db, "backup-2026-07-11.tar.gz", "deadbeef")
    mig.record_golden_fixtures(db, {"health": {"ok": True}})   # baseline snapshot
    # Reconcile clean (no unexplained broker qty).
    mig.reconcile_after_migration(db, acct, broker_positions={})


def test_cutover_blocked_without_backup_marker(db, acct):
    import server.migration as mig
    mig.run_shadow_migration(db, acct)
    mig.record_golden_fixtures(db, {"health": {"ok": True}})
    mig.reconcile_after_migration(db, acct, broker_positions={})
    report = mig.check_cutover_guards(db, [acct],
                                      golden_live={"health": {"ok": True}})
    assert report["ok"] is False
    assert "backup" in report["failed"]


def test_cutover_blocked_with_unknown_nonterminal_order(db, acct):
    import server.migration as mig
    _pass_all_guards(db, mig, acct)
    # An UNKNOWN nonterminal order must block cutover (§19.8).
    oid = db.create_order_intent(account_id=acct, strategy="sma_cross",
                                 client_order_id="ambig-1", symbol="AAPL",
                                 side="buy", order_type="market", requested_qty="1")
    db.bind_order_ack(oid, broker_order_id=None, state="UNKNOWN")
    report = mig.check_cutover_guards(db, [acct],
                                      golden_live={"health": {"ok": True}})
    assert report["ok"] is False
    assert "unknown_nonterminal_orders" in report["failed"]


def test_cutover_blocked_with_live_account(db):
    import server.migration as mig
    live = db.create_broker_account(label="live-acct", api_key_enc="k",
                                    api_secret_enc="s", account_type="live",
                                    broker="alpaca")
    _pass_all_guards(db, mig, live)
    report = mig.check_cutover_guards(db, [live],
                                      golden_live={"health": {"ok": True}})
    assert report["ok"] is False
    assert "paper_accounts_only" in report["failed"]


def test_cutover_blocked_on_golden_mismatch(db, acct):
    import server.migration as mig
    _pass_all_guards(db, mig, acct)
    # Live golden differs from the recorded baseline shape → mismatch blocks cutover.
    report = mig.check_cutover_guards(
        db, [acct], golden_live={"health": {"ok": True, "EXTRA_FIELD": 1}})
    assert report["ok"] is False
    assert "golden_compatibility" in report["failed"]


def test_cutover_blocked_on_retention_gap(db, acct):
    """A retention gap (broker fill retention exceeded) FREEZES → blocks cutover."""
    import server.migration as mig
    _pass_all_guards(db, mig, acct)
    mig.mark_retention_gap(db, acct, True)
    report = mig.check_cutover_guards(db, [acct],
                                      golden_live={"health": {"ok": True}})
    assert report["ok"] is False
    assert "retention_capability" in report["failed"]


def test_cutover_allowed_when_all_guards_pass(db, acct):
    import server.migration as mig
    _pass_all_guards(db, mig, acct)
    report = mig.check_cutover_guards(db, [acct],
                                      golden_live={"health": {"ok": True}})
    assert report["ok"] is True, report
    assert report["failed"] == []


# ── Atomic authority switch + old-path fail-closed ───────────────────────────────

def test_default_stays_shadow(db):
    import server.execution_router as router
    assert router.execution_ledger_mode() == "shadow"


def test_perform_cutover_is_atomic_and_switches_authority(db, acct):
    import server.migration as mig
    import server.execution_router as router
    _pass_all_guards(db, mig, acct)
    assert router.execution_ledger_mode() == "shadow"
    mig.perform_cutover(db, [acct], golden_live={"health": {"ok": True}})
    assert router.execution_ledger_mode() == "authoritative"


def test_perform_cutover_refuses_when_guard_fails(db, acct):
    """Cutover must NOT flip authority when any guard fails (§19.8)."""
    import server.migration as mig
    import server.execution_router as router
    mig.run_shadow_migration(db, acct)   # no backup marker, no golden → guards fail
    with pytest.raises(mig.CutoverBlocked):
        mig.perform_cutover(db, [acct], golden_live={"health": {"ok": True}})
    # Authority did NOT change — still shadow.
    assert router.execution_ledger_mode() == "shadow"


def test_old_submit_path_fails_closed_after_switch(db, acct):
    """After cutover, the legacy direct-submit path must fail closed (no dual
    submission). route_order reports legacy_authoritative False (§19.8)."""
    import server.migration as mig
    import server.execution_router as router

    class FakeBroker:
        supports_authoritative_lookup = True
        def __init__(self): self.submit_calls = []
        def submit_market_order(self, symbol, side, qty=None, notional=None, client_order_id=None):
            self.submit_calls.append((symbol, side, qty))
            return {"id": "b-1", "status": "accepted"}
        def get_order(self, oid, symbol=None): return {"broker_order_id": "b-1", "state": "ACKNOWLEDGED"}
        def get_order_by_client_id(self, cid, symbol=None): return None
        def get_order_fills(self, oid, since=None, symbol=None): return []

    _pass_all_guards(db, mig, acct)
    mig.perform_cutover(db, [acct], golden_live={"health": {"ok": True}})
    broker = FakeBroker()
    res = router.route_order(broker=broker, account_id=acct, owner="sma_cross",
                             symbol="AAPL", side="buy", qty="1")
    # Legacy bookkeeping is no longer authoritative — the caller must not run it.
    assert res["legacy_authoritative"] is False
    assert res["mode"] == "authoritative"


# ── Forward-recovery rollback (§19.8, §19.13) ────────────────────────────────────

def test_rollback_forward_recovery_leaves_fail_closed(db, acct):
    """Post-cutover rollback = FORWARD recovery: stop automation, archive the new
    ledger, restore compatible mode, and stay fail-closed until a fresh
    reconciliation passes (§19.8)."""
    import server.migration as mig
    import server.execution_router as router
    _pass_all_guards(db, mig, acct)
    mig.perform_cutover(db, [acct], golden_live={"health": {"ok": True}})
    assert router.execution_ledger_mode() == "authoritative"

    plan = mig.rollback_forward_recovery(db, [acct], archive_path="/backups/ledger.db")
    # Automation quiesced, authority restored to shadow (legacy authoritative again).
    assert router.automation_quiesced() is True
    assert router.execution_ledger_mode() == "shadow"
    # Account stays frozen (fail-closed) until reconciliation passes.
    assert db.get_account_kill_switch(acct) is True
    # The plan documents the ordered forward-recovery steps.
    steps = " ".join(plan["steps"]).lower()
    assert "stop automation" in steps or "quiesce" in steps
    assert "archive" in steps
    assert "reconcil" in steps


def test_rollback_clears_freeze_only_after_reconciliation_passes(db, acct):
    import server.migration as mig
    _pass_all_guards(db, mig, acct)
    mig.perform_cutover(db, [acct], golden_live={"health": {"ok": True}})
    mig.rollback_forward_recovery(db, [acct], archive_path="/backups/ledger.db")
    assert db.get_account_kill_switch(acct) is True
    # A clean reconciliation (no unexplained broker qty) is required to clear freeze.
    cleared = mig.clear_freeze_after_reconciliation(
        db, acct, broker_positions={}, reason="operator cleared after recon")
    assert cleared is True
    assert db.get_account_kill_switch(acct) is False


def test_rollback_freeze_not_cleared_when_reconciliation_fails(db, acct):
    import server.migration as mig
    _pass_all_guards(db, mig, acct)
    mig.perform_cutover(db, [acct], golden_live={"health": {"ok": True}})
    mig.rollback_forward_recovery(db, [acct], archive_path="/backups/ledger.db")
    # Reconciliation still finds unexplained broker qty → freeze NOT cleared.
    cleared = mig.clear_freeze_after_reconciliation(
        db, acct, broker_positions={"XYZ": "5"}, reason="attempt")
    assert cleared is False
    assert db.get_account_kill_switch(acct) is True
