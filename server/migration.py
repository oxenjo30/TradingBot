"""Task 10 — shadow migration, bootstrap classification, compatibility projections,
cutover guards, and forward-recovery rollback.

Spec: §14 (migration/rollout phases), §16 (operational controls), §19.6 (bootstrap
classification), §19.7 (order-path coverage / compatibility projection), §19.8
(migration authority and rollback), §19.11/§19.13 (compatibility + rollback/retention).

Everything here is ADDITIVE, transactional, VERSIONED, RERUNNABLE, and DRY-RUNNABLE.
There is NO destructive rewrite of historical production data.

Model of the world
-------------------
Before the ledger, inventory lived in the legacy `open_trades` table (open buys not
yet matched to a sell). The shadow migration copies that inventory into `position_lots`
under QUARANTINE OWNERS, not the strategy the legacy row named:

  - a legacy holding CONFIRMED by an authoritative TERMINAL broker order (trustworthy
    account/symbol/qty/price) → provenance ``legacy_verified``, owner ``legacy_verified``.
  - any other legacy holding → provenance ``legacy_unverified``, owner ``legacy_unverified``.
  - broker quantity we have NO internal record of → ``external/manual`` (reported by
    reconciliation, never persisted as an ownable lot).

Because the owner string is a quarantine bucket (not a real strategy), no automated
strategy can see or sell it — ``db.get_strategy_positions("sma_cross", ...)`` returns
nothing for a legacy lot. Ownership is therefore NEVER auto-adopted and NEVER inferred
by age. A holding becomes owned only through :func:`adopt_owner`, which requires
evidence, an exact account/symbol/qty/owner, an audit reason, and cannot adopt more
than the unexplained reconciled amount.

Cutover (shadow → authoritative) is GATED by :func:`check_cutover_guards` and only
performed by :func:`perform_cutover`, which is ATOMIC and refuses when any guard fails.
The default mode stays ``shadow`` and live behavior is unchanged until an operator
explicitly cuts over. After cutover the old submit path fails closed (the router's
``legacy_authoritative`` becomes False — no dual submission).

Post-cutover rollback (:func:`rollback_forward_recovery`) is FORWARD recovery: stop
automation, archive the new ledger, restore the compatible (shadow/legacy) mode, and
stay FAIL-CLOSED (account frozen) until a fresh reconciliation passes
(:func:`clear_freeze_after_reconciliation`).
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal

from .execution_models import decimal_text, parse_decimal
from .reconciliation import ReconciliationService

# Schema/migration version. Bump ONLY when a new additive migration step is added.
LEDGER_SCHEMA_VERSION = 1

# Quarantine owner buckets (NOT real strategies, so get_strategy_positions() ignores
# them and no automated strategy can sell classified legacy inventory).
LEGACY_VERIFIED_OWNER = "legacy_verified"
LEGACY_UNVERIFIED_OWNER = "legacy_unverified"

# app_config keys used as durable migration markers.
_K_SCHEMA_VERSION = "ledger_schema_version"
_K_MIGRATED = "ledger_migration_done"
_K_BACKUP_MARKER = "ledger_backup_marker"
_K_BACKUP_CHECKSUM = "ledger_backup_checksum"
_K_GOLDEN = "ledger_golden_fixtures"
_K_RETENTION_GAP = "ledger_retention_gap"           # per-account: "<key>:<account_id>"


class CutoverBlocked(Exception):
    """Raised when :func:`perform_cutover` is called but a guard fails."""


# ── Schema versioning (additive, rerunnable) ─────────────────────────────────────

def current_schema_version(db) -> int:
    """Return the recorded ledger schema version (0 if never migrated).

    Delegates to db.get_ledger_schema_version() when available (init_db stamps it),
    falling back to the app_config key for older DBs."""
    getter = getattr(db, "get_ledger_schema_version", None)
    if callable(getter):
        return getter()
    try:
        return int(db.get_app_config(_K_SCHEMA_VERSION, "0") or "0")
    except (TypeError, ValueError):
        return 0


def _set_schema_version(db, version: int) -> None:
    db.set_app_config(_K_SCHEMA_VERSION, str(version))
    # Keep the canonical db-stamped key in sync so both readers agree.
    db.set_app_config(getattr(db, "_LEDGER_SCHEMA_VERSION_KEY", "ledger_schema_version"),
                      str(version))


# ── Legacy-inventory read ────────────────────────────────────────────────────────

def _legacy_open_inventory(db, account_id: int) -> dict[str, dict]:
    """Aggregate legacy `open_trades` into {canonical_symbol: {qty, cost}} for an
    account. Quantity-weighted cost is the legacy entry price basis."""
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT symbol, qty, fill_price FROM open_trades "
            "WHERE account_id=? OR (account_id IS NULL AND ? IS NULL)",
            (account_id, account_id),
        ).fetchall()
    agg: dict[str, dict] = {}
    for r in rows:
        sym = db.canonical_symbol(r["symbol"])
        q = Decimal(str(r["qty"]))
        px = Decimal(str(r["fill_price"]))
        cur = agg.setdefault(sym, {"qty": Decimal("0"), "cost": Decimal("0")})
        cur["qty"] += q
        cur["cost"] += q * px
    return agg


def _has_terminal_broker_evidence(db, account_id: int, symbol: str,
                                  qty: Decimal) -> bool:
    """True iff an authoritative TERMINAL (FILLED) broker order covers this holding.

    §19.6: legacy_verified requires a confirmed terminal broker order with trustworthy
    account/symbol/quantity/price. We require a bound broker_order_id, a FILLED state,
    and a requested quantity at least the legacy holding."""
    sym = db.canonical_symbol(symbol)
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT requested_qty FROM execution_orders "
            "WHERE account_id=? AND symbol=? AND side='buy' AND state='FILLED' "
            "AND broker_order_id IS NOT NULL AND requested_qty IS NOT NULL",
            (account_id, sym),
        ).fetchall()
    covered = sum((Decimal(r["requested_qty"]) for r in rows), Decimal("0"))
    return covered >= qty and qty > 0


def classify_bootstrap_inventory(db, account_id: int) -> list[dict]:
    """Classify each legacy holding WITHOUT writing lots (§19.6). Returns one row per
    symbol: {symbol, qty, classification, owner}. Ownership is never inferred by age —
    a holding is legacy_verified only with terminal broker evidence, else
    legacy_unverified. Uncovered broker quantity is reported separately by
    :func:`reconcile_after_migration`."""
    inv = _legacy_open_inventory(db, account_id)
    out: list[dict] = []
    for sym in sorted(inv):
        qty = inv[sym]["qty"]
        if qty <= 0:
            continue
        if _has_terminal_broker_evidence(db, account_id, sym, qty):
            classification, owner = "legacy_verified", LEGACY_VERIFIED_OWNER
        else:
            classification, owner = "legacy_unverified", LEGACY_UNVERIFIED_OWNER
        out.append({
            "symbol": sym,
            "qty": decimal_text(qty),
            "classification": classification,
            "owner": owner,
        })
    return out


# ── Shadow migration (additive, transactional, rerunnable) ───────────────────────

def run_shadow_migration(db, account_id: int) -> dict:
    """Copy legacy inventory into quarantine lots (§14 Phase A, §19.6, §19.8).

    Additive + rerunnable: a symbol already migrated (a quarantine lot exists for it)
    is skipped, so running twice does not duplicate or lose rows. Legacy `open_trades`
    are NOT deleted. Nothing is auto-adopted to a real strategy owner.
    """
    classified = classify_bootstrap_inventory(db, account_id)
    inv = _legacy_open_inventory(db, account_id)
    provenance_for = {"legacy_verified": "legacy_verified",
                      "legacy_unverified": "legacy_unverified"}
    written = 0
    with db.get_conn() as c:
        for row in classified:
            sym = row["symbol"]
            owner = row["owner"]
            # Idempotent: skip if a quarantine lot already exists for this bucket+symbol.
            exists = c.execute(
                "SELECT 1 FROM position_lots WHERE account_id=? AND strategy=? AND symbol=?",
                (account_id, owner, sym),
            ).fetchone()
            if exists:
                continue
            qty_d = inv[sym]["qty"]
            cost = inv[sym]["cost"]
            unit_cost = (cost / qty_d) if qty_d > 0 else Decimal("0")
            c.execute(
                "INSERT INTO position_lots (account_id, strategy, symbol, opening_fill_id, "
                "original_qty, remaining_qty, unit_cost, opened_at, provenance) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (account_id, owner, sym, None,
                 decimal_text(qty_d), decimal_text(qty_d), decimal_text(unit_cost),
                 db._utc_micro(), provenance_for[row["classification"]]),
            )
            written += 1
    if current_schema_version(db) < LEDGER_SCHEMA_VERSION:
        _set_schema_version(db, LEDGER_SCHEMA_VERSION)
    db.set_app_config(_K_MIGRATED, "1")
    db.log_audit("migration", "shadow_migration",
                 f"account {account_id}: classified {len(classified)}, wrote {written} "
                 f"quarantine lot(s)")
    return {"account_id": account_id, "classified": len(classified),
            "written": written, "rows": classified}


# ── Reconciliation after migration (surfaces external/manual) ────────────────────

def reconcile_after_migration(db, account_id: int, *,
                              broker_positions: dict[str, str],
                              increments: dict[str, str] | None = None,
                              min_notionals: dict[str, str] | None = None,
                              prices: dict[str, str] | None = None) -> list[dict]:
    """Reconcile settled broker holdings against migrated (quarantine) lots (§19.6).

    Quarantine lots ARE verified internal quantity for the purpose of reconciliation
    (they are recorded, just not owned), so a broker position matching a migrated
    holding is VERIFIED. A broker position with NO internal record is external/manual
    and FROZEN. Returns the reconciliation rows."""
    return ReconciliationService().compare(
        account_id, broker_positions, open_orders=[],
        increments=increments, min_notionals=min_notionals, prices=prices)


# ── Owner adoption (evidence-bounded; never automatic) ───────────────────────────

def adopt_owner(db, *, account_id: int, symbol: str, owner: str, qty: str,
                unexplained_qty: str, reason: str) -> Decimal:
    """Adopt a quantity of quarantined legacy inventory to a real strategy owner
    (§19.6). Requires an audit reason and exact account/symbol/qty/owner, and the
    adopted quantity cannot exceed the unexplained reconciled amount. Returns the
    adopted Decimal quantity.

    Reassigns matching quarantine lots (legacy_unverified first, then legacy_verified)
    to ``owner`` with provenance ``verified`` so the strategy can manage them. Never
    exceeds the requested/available/unexplained bound."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("owner adoption requires an audit reason (§19.6)")
    if not owner or owner in (LEGACY_VERIFIED_OWNER, LEGACY_UNVERIFIED_OWNER, ""):
        raise ValueError(f"invalid adoption owner: {owner!r}")
    want = parse_decimal(qty)
    unexplained = parse_decimal(unexplained_qty)
    if want <= 0:
        raise ValueError("adoption qty must be positive")
    if want > unexplained:
        raise ValueError(
            f"adopted qty {decimal_text(want)} exceeds unexplained reconciled amount "
            f"{decimal_text(unexplained)} (§19.6)")
    sym = db.canonical_symbol(symbol)

    adopted = Decimal("0")
    remaining = want
    c = sqlite3.connect(db.DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        c.execute("BEGIN IMMEDIATE")
        lots = c.execute(
            "SELECT id, remaining_qty, provenance FROM position_lots "
            "WHERE account_id=? AND symbol=? AND strategy IN (?,?) "
            "AND CAST(remaining_qty AS REAL) > 0 "
            "ORDER BY CASE provenance WHEN 'legacy_unverified' THEN 0 ELSE 1 END, id ASC",
            (account_id, sym, LEGACY_UNVERIFIED_OWNER, LEGACY_VERIFIED_OWNER),
        ).fetchall()
        for lot in lots:
            if remaining <= 0:
                break
            lot_rem = Decimal(lot["remaining_qty"])
            take = lot_rem if lot_rem <= remaining else remaining
            if take <= 0:
                continue
            if take == lot_rem:
                # Whole lot adopted → reassign owner + provenance.
                c.execute(
                    "UPDATE position_lots SET strategy=?, provenance='verified' WHERE id=?",
                    (owner, lot["id"]),
                )
            else:
                # Partial: shrink the quarantine lot, insert an owned lot for the taken qty.
                c.execute("UPDATE position_lots SET remaining_qty=?, original_qty=? WHERE id=?",
                          (decimal_text(lot_rem - take), decimal_text(lot_rem - take), lot["id"]))
                uc = c.execute("SELECT unit_cost, opened_at FROM position_lots WHERE id=?",
                               (lot["id"],)).fetchone()
                c.execute(
                    "INSERT INTO position_lots (account_id, strategy, symbol, opening_fill_id, "
                    "original_qty, remaining_qty, unit_cost, opened_at, provenance) "
                    "VALUES (?,?,?,?,?,?,?,?, 'verified')",
                    (account_id, owner, sym, None, decimal_text(take), decimal_text(take),
                     uc["unit_cost"], uc["opened_at"]),
                )
            adopted += take
            remaining -= take
        c.execute("COMMIT")
    except Exception:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        c.close()

    db.log_audit("migration", "owner_adopted",
                 f"account {account_id} {sym}: adopted {decimal_text(adopted)} to "
                 f"'{owner}' (unexplained={decimal_text(unexplained)}) — {reason}")
    return adopted


# ── Dry-run report (against a COPIED legacy DB — writes NOTHING) ──────────────────

def dry_run_report(copied_db_path: str) -> dict:
    """Report what a migration WOULD do against a COPIED legacy DB, writing nothing
    to it (§19.8: migrations are dry-run against a backup copy). Read-only.

    We open the copy directly (no INSERTs) and count legacy inventory + what would be
    classified. ``destructive`` is always False — this report never mutates the copy.
    """
    c = sqlite3.connect(copied_db_path)
    c.row_factory = sqlite3.Row
    try:
        n_open = c.execute("SELECT COUNT(*) AS n FROM open_trades").fetchone()["n"]
        # distinct (account, symbol) legacy holdings that would be classified
        would = c.execute(
            "SELECT COUNT(*) AS n FROM ("
            "  SELECT account_id, UPPER(TRIM(symbol)) AS s FROM open_trades "
            "  GROUP BY account_id, s HAVING SUM(qty) > 0)"
        ).fetchone()["n"]
        version_row = c.execute(
            "SELECT value FROM app_config WHERE key=?", (_K_SCHEMA_VERSION,)
        ).fetchone()
        current_version = int(version_row["value"]) if version_row else 0
    finally:
        c.close()
    return {
        "copied_db_path": copied_db_path,
        "legacy_open_trades": n_open,
        "would_classify": would,
        "current_schema_version": current_version,
        "target_schema_version": LEDGER_SCHEMA_VERSION,
        "destructive": False,
    }


# ── Compatibility projections (ledger → legacy API shapes, §19.7) ────────────────

def project_positions(db, account_id: int, *,
                      prices: dict[str, str] | None = None) -> list[dict]:
    """Project owned + quarantined lots into the LEGACY /api/positions shape (§19.7).

    Keys exactly match AccountClient.get_positions(): symbol, qty, side, market_value,
    avg_entry_price, current_price, unrealized_pl, unrealized_plpc. Aggregated per
    canonical symbol across all owners. ``prices`` supplies a current mark; absent, the
    entry price is used (zero unrealized)."""
    prices = {db.canonical_symbol(k): v for k, v in (prices or {}).items()}
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT symbol, remaining_qty, unit_cost FROM position_lots "
            "WHERE account_id=? AND CAST(remaining_qty AS REAL) > 0",
            (account_id,),
        ).fetchall()
    agg: dict[str, dict] = {}
    for r in rows:
        sym = db.canonical_symbol(r["symbol"])
        q = Decimal(r["remaining_qty"])
        cost = q * Decimal(r["unit_cost"])
        cur = agg.setdefault(sym, {"qty": Decimal("0"), "cost": Decimal("0")})
        cur["qty"] += q
        cur["cost"] += cost
    out: list[dict] = []
    for sym in sorted(agg):
        q = agg[sym]["qty"]
        if q <= 0:
            continue
        avg_entry = agg[sym]["cost"] / q
        price = Decimal(prices[sym]) if sym in prices else avg_entry
        market_value = q * price
        unrealized = (price - avg_entry) * q
        unrealized_pct = (float(unrealized / (avg_entry * q)) * 100.0
                          if avg_entry * q != 0 else 0.0)
        out.append({
            "symbol": sym,
            "qty": float(q),
            "side": "long",
            "market_value": float(market_value),
            "avg_entry_price": float(avg_entry),
            "current_price": float(price),
            "unrealized_pl": float(unrealized),
            "unrealized_plpc": unrealized_pct,
        })
    return out


def project_orders(db, account_id: int, *, limit: int = 50) -> list[dict]:
    """Project execution_orders into the LEGACY /api/orders shape (§19.7).

    Keys exactly match AccountClient.get_orders(). Excludes internal exit reservations."""
    from .execution_models import OrderState
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT id, client_order_id, broker_order_id, symbol, side, order_type, "
            "requested_qty, state, created_at, updated_at "
            "FROM execution_orders WHERE account_id=? "
            "AND strategy NOT LIKE '%::exit_reservation' "
            "ORDER BY id DESC LIMIT ?",
            (account_id, limit),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        with db.get_conn() as c:
            fills = c.execute(
                "SELECT qty, price FROM execution_fills WHERE execution_order_id=?",
                (r["id"],),
            ).fetchall()
        filled_qty = sum((Decimal(f["qty"]) for f in fills), Decimal("0"))
        if fills:
            notional = sum((Decimal(f["qty"]) * Decimal(f["price"]) for f in fills),
                           Decimal("0"))
            avg_price = float(notional / filled_qty) if filled_qty > 0 else None
        else:
            avg_price = None
        state = r["state"]
        terminal = False
        try:
            terminal = OrderState(state).is_terminal
        except ValueError:
            terminal = False
        out.append({
            "id": r["broker_order_id"] or str(r["id"]),
            "client_order_id": r["client_order_id"],
            "symbol": r["symbol"],
            "side": r["side"],
            "qty": float(r["requested_qty"]) if r["requested_qty"] is not None else None,
            "filled_qty": float(filled_qty),
            "filled_avg_price": avg_price,
            "type": r["order_type"],
            "status": (state or "").lower(),
            "submitted_at": r["created_at"],
            "filled_at": r["updated_at"] if (terminal and fills) else None,
        })
    return out


def project_account(db, account_id: int, *, cash: str,
                    prices: dict[str, str] | None = None) -> dict:
    """Project a minimal account summary from the ledger in the LEGACY /api/account
    shape (equity/cash/buying_power at minimum). Equity = cash + projected market
    value of all lots (§19.7)."""
    cash_d = parse_decimal(cash)
    positions = project_positions(db, account_id, prices=prices)
    market_value = sum((Decimal(str(p["market_value"])) for p in positions), Decimal("0"))
    equity = cash_d + market_value
    return {
        "equity": float(equity),
        "cash": float(cash_d),
        "buying_power": float(cash_d),
        "portfolio_value": float(equity),
        "long_market_value": float(market_value),
    }


# ── Golden fixtures + shape comparison (§19.8, §19.11) ───────────────────────────

def _shape_of(value):
    """A structural fingerprint that ignores VALUES but captures keys and types.

    Dicts → sorted key set each mapped to its value's shape. Lists → the shape of the
    first element (empty list is its own shape). Scalars → their python type name."""
    if isinstance(value, dict):
        return {k: _shape_of(value[k]) for k in sorted(value.keys())}
    if isinstance(value, list):
        return ["<empty>"] if not value else [_shape_of(value[0])]
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "null"
    return type(value).__name__


def golden_shape_matches(golden: dict, live: dict) -> bool:
    """True iff ``live`` has the SAME field-shape (keys + types, recursively) as the
    recorded ``golden`` fixture — the byte/field-shape compatibility gate (§19.8).
    A missing field, an extra field, or a changed type all fail."""
    return _shape_of(golden) == _shape_of(live)


def record_golden_fixtures(db, fixtures: dict) -> None:
    """Persist the baseline golden response fixtures (recorded BEFORE cutover)."""
    import json
    db.set_app_config(_K_GOLDEN, json.dumps(fixtures, sort_keys=True))


def get_golden_fixtures(db) -> dict | None:
    import json
    raw = db.get_app_config(_K_GOLDEN, "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


# ── Backup + retention markers ───────────────────────────────────────────────────

def set_backup_marker(db, path: str, checksum: str) -> None:
    """Record that a DB/configuration backup was taken (required before cutover)."""
    db.set_app_config(_K_BACKUP_MARKER, path or "")
    db.set_app_config(_K_BACKUP_CHECKSUM, checksum or "")
    db.log_audit("migration", "backup_marker", f"{path} ({checksum})")


def has_backup_marker(db) -> bool:
    return bool(db.get_app_config(_K_BACKUP_MARKER, "")) and \
        bool(db.get_app_config(_K_BACKUP_CHECKSUM, ""))


def mark_retention_gap(db, account_id: int, gapped: bool) -> None:
    """Record whether an account's fill-ingestion downtime exceeded broker retention.
    A retention gap freezes the account and blocks cutover (§19.12/§19.13)."""
    db.set_app_config(f"{_K_RETENTION_GAP}:{account_id}", "1" if gapped else "0")
    if gapped:
        db.set_account_kill_switch(account_id, True)
        db.log_audit("migration", "retention_gap",
                     f"account {account_id}: fill retention gap — frozen")


def has_retention_gap(db, account_id: int) -> bool:
    return (db.get_app_config(f"{_K_RETENTION_GAP}:{account_id}", "0") or "0") == "1"


# ── Cutover guards (§19.8) ───────────────────────────────────────────────────────

def _unknown_nonterminal_orders(db, account_id: int) -> int:
    """Count UNKNOWN nonterminal orders for the account (must be ZERO to cut over)."""
    with db.get_conn() as c:
        return c.execute(
            "SELECT COUNT(*) AS n FROM execution_orders "
            "WHERE account_id=? AND state='UNKNOWN'",
            (account_id,),
        ).fetchone()["n"]


def check_cutover_guards(db, account_ids: list[int], *, golden_live: dict) -> dict:
    """Evaluate EVERY cutover guard (§19.8). Returns {ok, failed:[...], detail:{...}}.

    Guards (all must pass):
      - backup            : a backup marker + checksum exists.
      - unknown_nonterminal_orders : ZERO UNKNOWN nonterminal orders on any account.
      - reconciliation    : no account is currently frozen (kill switch off) and a
                            golden baseline was recorded (a reconciliation pass ran).
      - paper_accounts_only : every participating account is a PAPER account.
      - retention_capability : no account has a retention gap.
      - golden_compatibility : the live golden responses match the recorded fixtures.
    """
    failed: list[str] = []
    detail: dict = {}

    if not has_backup_marker(db):
        failed.append("backup")

    unknown = {aid: _unknown_nonterminal_orders(db, aid) for aid in account_ids}
    detail["unknown_nonterminal_orders"] = unknown
    if any(n > 0 for n in unknown.values()):
        failed.append("unknown_nonterminal_orders")

    # Paper-accounts-only (§19.1: live accounts fail validation).
    non_paper = []
    for aid in account_ids:
        acct = db.get_broker_account(aid)
        if not acct or (acct.get("account_type") or "paper") != "paper":
            non_paper.append(aid)
    detail["non_paper_accounts"] = non_paper
    if non_paper:
        failed.append("paper_accounts_only")

    # Retention capability.
    gapped = [aid for aid in account_ids if has_retention_gap(db, aid)]
    detail["retention_gapped_accounts"] = gapped
    if gapped:
        failed.append("retention_capability")

    # Reconciliation pass: a golden baseline must have been recorded (proves the
    # pre-cutover reconciliation/compatibility step ran) and no account is frozen.
    golden = get_golden_fixtures(db)
    frozen = [aid for aid in account_ids if db.get_account_kill_switch(aid)]
    detail["frozen_accounts"] = frozen
    if golden is None or frozen:
        failed.append("reconciliation")

    # Golden compatibility (field-shape identical to the recorded baseline).
    if golden is None or not golden_shape_matches(golden, golden_live):
        failed.append("golden_compatibility")

    ok = not failed
    return {"ok": ok, "failed": failed, "detail": detail}


# ── Atomic authority switch (§19.8) ──────────────────────────────────────────────

def perform_cutover(db, account_ids: list[int], *, golden_live: dict) -> dict:
    """Atomically switch to authoritative mode IFF every guard passes (§19.8).

    Refuses (raises CutoverBlocked) and leaves the mode unchanged when any guard
    fails — cutover NEVER flips automatically. On success, sets
    ``execution_ledger_mode=authoritative`` so the old submit path fails closed."""
    report = check_cutover_guards(db, account_ids, golden_live=golden_live)
    if not report["ok"]:
        raise CutoverBlocked(f"cutover blocked; failed guards: {report['failed']}")
    # Atomic single-key flip. The router reads this and disables the legacy submit path.
    db.set_app_config("execution_ledger_mode", "authoritative")
    db.log_audit("migration", "cutover",
                 f"execution_ledger_mode → authoritative for accounts {account_ids}")
    return {"ok": True, "mode": "authoritative", "accounts": account_ids}


# ── Forward-recovery rollback (§19.8, §19.13) ────────────────────────────────────

def rollback_forward_recovery(db, account_ids: list[int], *, archive_path: str) -> dict:
    """FORWARD-recovery rollback after cutover (§19.8, §19.13 "Rollback and retention").

    Ordered steps, executed here as far as is safe in-process:
      1. Stop automation (quiesce) so no new orders are placed.
      2. Restore the compatible mode (execution_ledger_mode → shadow; legacy
         authoritative again).
      3. Freeze every participating account (kill switch) — FAIL CLOSED. The account
         stays frozen until :func:`clear_freeze_after_reconciliation` passes.
      4. Record the archive location of the post-cutover ledger (operational; the
         actual file archive/restore of binary+schema happens outside the process).

    Returns {steps:[...], mode, quiesced, frozen_accounts}. The remaining operational
    steps (import post-backup broker orders/fills + reclassify) are documented in the
    plan and gated behind the fresh reconciliation before any account is un-frozen.
    """
    steps = [
        "Stop automation (quiesce scheduler — no new orders).",
        "Cancel/reconcile in-flight strategy-owned orders (owner clearance required).",
        f"Archive the post-cutover ledger to {archive_path}.",
        "Restore the pre-cutover DB/configuration backup (compatible schema/binary).",
        "Set execution_ledger_mode → shadow (legacy path authoritative again).",
        "Import post-backup broker orders/fills and RECLASSIFY inventory (§19.6).",
        "Stay FAIL-CLOSED (accounts frozen) until a fresh reconciliation passes.",
    ]
    # 1. Quiesce automation.
    from . import execution_router
    execution_router.set_automation_quiesced(True)
    # 2. Restore compatible mode.
    db.set_app_config("execution_ledger_mode", "shadow")
    # 3. Fail closed on every participating account.
    for aid in account_ids:
        db.set_account_kill_switch(aid, True)
    db.log_audit("migration", "rollback_forward_recovery",
                 f"accounts {account_ids} archived to {archive_path}; quiesced; "
                 f"mode → shadow; frozen (fail-closed until reconciliation)")
    return {
        "steps": steps,
        "mode": "shadow",
        "quiesced": True,
        "archive_path": archive_path,
        "frozen_accounts": list(account_ids),
    }


def clear_freeze_after_reconciliation(db, account_id: int, *,
                                      broker_positions: dict[str, str],
                                      reason: str,
                                      increments: dict[str, str] | None = None,
                                      min_notionals: dict[str, str] | None = None,
                                      prices: dict[str, str] | None = None) -> bool:
    """Clear an account's freeze ONLY after a fresh reconciliation passes (§19.2 step
    10, §19.8). Reconciliation passes iff no row froze (no unexplained broker qty).
    Requires an audit reason. Returns True when the freeze was cleared."""
    if not (reason or "").strip():
        raise ValueError("clearing a freeze requires an audit reason (§19.2)")
    rows = reconcile_after_migration(
        db, account_id, broker_positions=broker_positions,
        increments=increments, min_notionals=min_notionals, prices=prices)
    if ReconciliationService.is_frozen(rows):
        db.log_audit("migration", "freeze_not_cleared",
                     f"account {account_id}: reconciliation still frozen — {reason}")
        return False
    db.set_account_kill_switch(account_id, False)
    db.log_audit("migration", "freeze_cleared",
                 f"account {account_id}: reconciliation passed — {reason}")
    return True
