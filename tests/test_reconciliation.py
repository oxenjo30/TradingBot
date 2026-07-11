"""Task 2 — broker reconciliation and external/manual quarantine.

RED-first tests for ReconciliationService.compare (spec §19.6).

Rules under test:
  - Settled broker quantity is compared against verified internal lots per
    canonical (account, symbol).
  - Quantity tolerance = one broker increment; value tolerance = max($1, minimum
    notional). Within tolerance → DUST; above tolerance → FROZEN.
  - Broker quantity with no matching internal lots is `external/manual` and cannot
    be sold by automated strategies.
  - Snapshots have stable IDs persisted to reconciliation_snapshots.

No network calls. Uses an isolated per-test SQLite DB.
"""
from decimal import Decimal

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "recon.db")
    db_mod.init_db()
    return db_mod


def _open_lot(db, strategy, account_id, symbol, qty, price):
    import uuid
    cid = f"{strategy}-{uuid.uuid4().hex[:12]}"
    oid = db.create_order_intent(
        account_id=account_id, strategy=strategy, client_order_id=cid,
        symbol=symbol, side="buy", order_type="market", requested_qty=qty,
    )
    db.bind_order_ack(oid, broker_order_id=f"bro-{cid}", state="ACKNOWLEDGED")
    db.insert_fill_and_apply_fifo(
        oid, broker_fill_id=f"f-{cid}", qty=qty, price=price,
        fee="0", fee_currency="USD", filled_at="2026-06-18T00:00:00.000000Z",
    )


def _svc():
    from server.reconciliation import ReconciliationService
    return ReconciliationService()


# ── Exact match → VERIFIED ───────────────────────────────────────────────────────

def test_exact_match_is_verified(db):
    _open_lot(db, "sma_cross", 23, "AAPL", "10", "100")
    rows = _svc().compare(23, broker_positions={"AAPL": "10"}, open_orders=[])
    row = next(r for r in rows if r["symbol"] == "AAPL")
    assert row["status"] == "VERIFIED"
    assert Decimal(str(row["delta"])) == Decimal("0")


# ── Dust tolerance → DUST, and it does NOT freeze the account ────────────────────

def test_dust_delta_does_not_freeze(db):
    _open_lot(db, "sma_cross", 23, "BTC", "1", "50000")
    # broker shows a tiny excess within one broker increment / $1 value tolerance
    rows = _svc().compare(
        23,
        broker_positions={"BTC": "1.0000004"},
        open_orders=[],
        increments={"BTC": "0.000001"},
        min_notionals={"BTC": "1"},
        prices={"BTC": "50000"},
    )
    row = next(r for r in rows if r["symbol"] == "BTC")
    assert row["status"] == "DUST"
    assert not _svc().is_frozen(rows)


# ── Material delta → FROZEN ──────────────────────────────────────────────────────

def test_material_delta_freezes(db):
    _open_lot(db, "sma_cross", 23, "AAPL", "10", "100")
    # broker shows 4 fewer shares — well beyond tolerance
    rows = _svc().compare(
        23,
        broker_positions={"AAPL": "6"},
        open_orders=[],
        increments={"AAPL": "1"},
        min_notionals={"AAPL": "1"},
        prices={"AAPL": "100"},
    )
    row = next(r for r in rows if r["symbol"] == "AAPL")
    assert row["status"] == "FROZEN"
    assert _svc().is_frozen(rows)


# ── Unknown broker quantity → external/manual (quarantined) ──────────────────────

def test_unknown_broker_quantity_is_quarantined(db):
    # internal owns nothing on DOGE; broker holds 100 → external/manual
    rows = _svc().compare(23, broker_positions={"DOGE": "100"}, open_orders=[])
    row = next(r for r in rows if r["symbol"] == "DOGE")
    assert row["status"] == "FROZEN"
    assert row["classification"] == "external/manual"


def test_external_quantity_is_not_sellable_by_strategy(db):
    # even after reconciliation reports it, no strategy owns external qty
    _svc().compare(23, broker_positions={"DOGE": "100"}, open_orders=[])
    assert db.get_sellable_qty("sma_cross", 23, "DOGE") == Decimal("0")


# ── Open orders are reported as reservations, not as missing inventory ───────────

def test_open_sell_order_reservation_does_not_freeze(db):
    _open_lot(db, "sma_cross", 23, "AAPL", "10", "100")
    # broker settled qty is 6 because 4 are tied up in an open sell order
    open_orders = [{"symbol": "AAPL", "side": "sell", "qty": "4"}]
    rows = _svc().compare(
        23,
        broker_positions={"AAPL": "6"},
        open_orders=open_orders,
        increments={"AAPL": "1"},
        min_notionals={"AAPL": "1"},
        prices={"AAPL": "100"},
    )
    row = next(r for r in rows if r["symbol"] == "AAPL")
    # settled(6) + open sell reservation(4) == internal(10) → reconciled
    assert row["status"] == "VERIFIED"


# ── Snapshots persist with stable IDs ────────────────────────────────────────────

def test_snapshot_ids_are_persisted_and_stable(db):
    _open_lot(db, "sma_cross", 23, "AAPL", "10", "100")
    rows = _svc().compare(23, broker_positions={"AAPL": "10"}, open_orders=[])
    row = next(r for r in rows if r["symbol"] == "AAPL")
    assert "snapshot_id" in row and isinstance(row["snapshot_id"], int)
    with db.get_conn() as c:
        n = c.execute(
            "SELECT COUNT(*) AS n FROM reconciliation_snapshots WHERE account_id=?",
            (23,),
        ).fetchone()["n"]
    assert n >= 1


def test_canonical_symbol_matching(db):
    # internal stores AAPL; broker reports lowercase aapl → must still match
    _open_lot(db, "sma_cross", 23, "AAPL", "10", "100")
    rows = _svc().compare(23, broker_positions={"aapl": "10"}, open_orders=[])
    row = next(r for r in rows if r["symbol"].upper() == "AAPL")
    assert row["status"] == "VERIFIED"
