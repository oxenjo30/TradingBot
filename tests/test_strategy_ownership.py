"""Task 2 — strategy-owned lots, sellable quantity, and exit reservations.

RED-first tests for strategy ownership enforcement (spec §4.3, §19.5).

Ownership rules under test:
  - A strategy can only ever sell ITS OWN lots; a Bollinger exit can never sell an
    SMA-owned lot (§4.3 anti-pattern).
  - Sellable quantity = remaining owned lots minus reserved nonterminal exits;
    two concurrent exits cannot reserve more than the owned quantity (§19.5).
  - Selection keys ALWAYS include strategy + account + canonical symbol, so account
    IDs isolate entry prices and positions.
  - Oversized exits round DOWN; a zero sellable is rejected/returns 0.

No network calls. Uses an isolated per-test SQLite DB.
"""
from decimal import Decimal

import pytest


# ── DB isolation ────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path, monkeypatch):
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "ownership.db")
    db_mod.init_db()
    return db_mod


def _open_lot(db, strategy, account_id, symbol, qty, price, *, side="buy",
              fee="0", cid=None):
    """Create a buy order + ingest a fill so a strategy-owned lot exists.

    Returns the created execution_order id. Uses the Task 1 ledger primitives so
    lots are created the same way production will create them.
    """
    import uuid
    cid = cid or f"{strategy}-{uuid.uuid4().hex[:12]}"
    oid = db.create_order_intent(
        account_id=account_id, strategy=strategy, client_order_id=cid,
        symbol=symbol, side=side, order_type="market", requested_qty=qty,
    )
    db.bind_order_ack(oid, broker_order_id=f"bro-{cid}", state="ACKNOWLEDGED")
    db.insert_fill_and_apply_fifo(
        oid, broker_fill_id=f"f-{cid}", qty=qty, price=price,
        fee=fee, fee_currency="USD", filled_at="2026-06-18T00:00:00.000000Z",
    )
    return oid


# ── A strategy cannot sell another strategy's lot (§4.3) ─────────────────────────

def test_strategy_cannot_sell_another_strategys_lot(db):
    _open_lot(db, "sma_cross", 23, "AAPL", "10", "100")
    # bollinger owns nothing on this account/symbol → 0 sellable
    assert db.get_sellable_qty("bollinger", 23, "AAPL") == Decimal("0")
    # sma_cross owns the full 10
    assert db.get_sellable_qty("sma_cross", 23, "AAPL") == Decimal("10")


def test_get_strategy_positions_only_returns_owned(db):
    _open_lot(db, "sma_cross", 23, "AAPL", "10", "100")
    _open_lot(db, "bollinger", 23, "MSFT", "5", "200")
    sma = db.get_strategy_positions("sma_cross", 23)
    assert "AAPL" in sma and "MSFT" not in sma
    assert Decimal(str(sma["AAPL"])) == Decimal("10")
    boll = db.get_strategy_positions("bollinger", 23)
    assert "MSFT" in boll and "AAPL" not in boll


# ── Concurrent exit reservations cannot exceed owned quantity (§19.5) ─────────────

def test_two_concurrent_exits_cannot_reserve_more_than_owned(db):
    _open_lot(db, "sma_cross", 23, "AAPL", "10", "100")
    r1 = db.reserve_exit_qty("sma_cross", 23, "AAPL", "7")
    assert Decimal(str(r1)) == Decimal("7")
    # only 3 remain sellable
    assert db.get_sellable_qty("sma_cross", 23, "AAPL") == Decimal("3")
    # a second exit asking for 7 can only get the remaining 3 (round down to available)
    r2 = db.reserve_exit_qty("sma_cross", 23, "AAPL", "7")
    assert Decimal(str(r2)) == Decimal("3")
    # nothing left
    assert db.get_sellable_qty("sma_cross", 23, "AAPL") == Decimal("0")
    # a third exit gets nothing
    r3 = db.reserve_exit_qty("sma_cross", 23, "AAPL", "1")
    assert Decimal(str(r3)) == Decimal("0")


def test_release_reservation_restores_sellable(db):
    _open_lot(db, "sma_cross", 23, "AAPL", "10", "100")
    rid = db.reserve_exit_qty("sma_cross", 23, "AAPL", "4")
    assert Decimal(str(rid)) == Decimal("4")
    assert db.get_sellable_qty("sma_cross", 23, "AAPL") == Decimal("6")
    db.release_exit_reservation("sma_cross", 23, "AAPL", "4")
    assert db.get_sellable_qty("sma_cross", 23, "AAPL") == Decimal("10")


def test_reserve_exit_rounds_down_and_never_oversells(db):
    _open_lot(db, "sma_cross", 23, "AAPL", "10", "100")
    # ask for far more than owned → capped at owned, rounded down
    got = db.reserve_exit_qty("sma_cross", 23, "AAPL", "999")
    assert Decimal(str(got)) == Decimal("10")


# ── Account IDs isolate entry prices and positions (§4.3, §19.5) ──────────────────

def test_account_ids_isolate_entry_prices(db):
    _open_lot(db, "sma_cross", 23, "AAPL", "10", "100")
    _open_lot(db, "sma_cross", 99, "AAPL", "10", "250")
    p23 = db.get_strategy_entry_price("sma_cross", 23, "AAPL")
    p99 = db.get_strategy_entry_price("sma_cross", 99, "AAPL")
    assert Decimal(str(p23)) == Decimal("100")
    assert Decimal(str(p99)) == Decimal("250")


def test_account_ids_isolate_sellable_qty(db):
    _open_lot(db, "sma_cross", 23, "AAPL", "10", "100")
    assert db.get_sellable_qty("sma_cross", 23, "AAPL") == Decimal("10")
    # a different account owns nothing
    assert db.get_sellable_qty("sma_cross", 99, "AAPL") == Decimal("0")


def test_canonical_symbol_lookup_is_case_insensitive(db):
    _open_lot(db, "sma_cross", 23, "AAPL", "10", "100")
    # canonical symbol keys mean lowercase lookups still match
    assert db.get_sellable_qty("sma_cross", 23, "aapl") == Decimal("10")
    assert db.get_strategy_entry_price("sma_cross", 23, "aapl") is not None


# ── Sells reduce owned quantity via FIFO (foundation for exits) ──────────────────

def test_sell_fill_reduces_owned_quantity(db):
    _open_lot(db, "sma_cross", 23, "AAPL", "10", "100")
    # a subsequent sell fill of 4 by the SAME strategy reduces remaining to 6
    _open_lot(db, "sma_cross", 23, "AAPL", "4", "120", side="sell", cid="sell-1")
    assert db.get_sellable_qty("sma_cross", 23, "AAPL") == Decimal("6")


def test_entry_price_none_when_not_owned(db):
    _open_lot(db, "sma_cross", 23, "AAPL", "10", "100")
    assert db.get_strategy_entry_price("bollinger", 23, "AAPL") is None
