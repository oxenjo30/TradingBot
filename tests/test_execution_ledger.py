"""Task 1 — decimal execution schema and order state model.

RED-first tests for the additive execution ledger. Covers:
  - canonical decimal text normalization (spec §19.5)
  - OrderState terminal/nonterminal classification (spec §19.3)
  - rerunnable additive schema (plan Task 1 Step 4)
  - fill-insert idempotency (duplicate-equal returns same id; conflict raises)

No network calls. Uses an isolated per-test SQLite DB.
"""
from decimal import Decimal

import pytest


# ── DB isolation ────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point db at an isolated file and initialise the schema."""
    import server.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ledger.db")
    db.init_db()
    return db


def _table_names(db) -> set[str]:
    with db.get_conn() as c:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


# ── Decimal normalization (spec §19.5) ──────────────────────────────────────────

def test_decimal_text_rejects_exponent():
    from server.execution_models import decimal_text
    with pytest.raises(ValueError):
        decimal_text("1e-8")


def test_decimal_text_rejects_too_many_fractional_digits():
    from server.execution_models import decimal_text
    # 18 fractional digits is the max allowed; 19 must reject.
    decimal_text("0.123456789012345678")          # 18 → ok
    with pytest.raises(ValueError):
        decimal_text("0.1234567890123456789")      # 19 → reject


def test_decimal_text_normalizes_negative_zero_and_roundtrips():
    from server.execution_models import decimal_text, parse_decimal
    assert decimal_text("-0") == "0"
    assert decimal_text(Decimal("-0.0")) == "0"
    # round-trip: text → Decimal → text is stable and exponent-free
    t = decimal_text("123.45000")
    assert "e" not in t.lower()
    assert parse_decimal(t) == Decimal("123.45")


# ── Order state model (spec §19.3) ──────────────────────────────────────────────

def test_order_states_terminal_classification():
    from server.execution_models import OrderState
    terminal = {OrderState.FILLED, OrderState.CANCELED,
                OrderState.REJECTED, OrderState.EXPIRED}
    nonterminal = {OrderState.INTENT_PERSISTED, OrderState.SUBMITTING,
                   OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED,
                   OrderState.CANCEL_PENDING, OrderState.UNKNOWN}
    for s in terminal:
        assert s.is_terminal, f"{s} should be terminal"
    for s in nonterminal:
        assert not s.is_terminal, f"{s} should be nonterminal"


def test_acknowledgement_states_are_not_fills():
    """accepted/pending/new/open must never classify as filled (plan anti-pattern)."""
    from server.execution_models import OrderState
    for name in ("ACKNOWLEDGED", "SUBMITTING", "PARTIALLY_FILLED"):
        assert getattr(OrderState, name) is not OrderState.FILLED


# ── Schema (plan Task 1 Step 4) ─────────────────────────────────────────────────

def test_execution_schema_is_rerunnable(tmp_db):
    tmp_db.init_db()  # second call must not error
    names = _table_names(tmp_db)
    assert {
        "execution_orders", "execution_fills", "fee_adjustments",
        "position_lots", "lot_matches", "reconciliation_snapshots",
        "portfolio_risk_state",
    } <= names


def test_existing_tables_still_present(tmp_db):
    """Additive migration must not drop existing tables."""
    names = _table_names(tmp_db)
    assert {"signals", "open_trades", "broker_accounts", "strategy_accounts"} <= names


# ── Persistence primitives + fill idempotency (plan Task 1 Step 5) ──────────────

def test_create_intent_and_lookup_by_client_id(tmp_db):
    oid = tmp_db.create_order_intent(
        account_id=23, strategy="liquid_stock_trend", client_order_id="cid-abc123",
        symbol="AAPL", side="buy", order_type="market", requested_qty="10",
    )
    found = tmp_db.get_order_by_client_id(23, "cid-abc123")
    assert found is not None
    assert found["id"] == oid
    assert found["state"] == "INTENT_PERSISTED"


def test_duplicate_client_order_id_is_rejected(tmp_db):
    tmp_db.create_order_intent(
        account_id=23, strategy="s", client_order_id="dup1",
        symbol="AAPL", side="buy", order_type="market", requested_qty="1",
    )
    with pytest.raises(Exception):
        tmp_db.create_order_intent(
            account_id=23, strategy="s", client_order_id="dup1",
            symbol="AAPL", side="buy", order_type="market", requested_qty="1",
        )


def test_fill_insert_is_idempotent_on_equal_duplicate(tmp_db):
    oid = tmp_db.create_order_intent(
        account_id=23, strategy="s", client_order_id="cid-fill",
        symbol="AAPL", side="buy", order_type="market", requested_qty="10",
    )
    tmp_db.bind_order_ack(oid, broker_order_id="bro-1", state="ACKNOWLEDGED")
    fill = dict(broker_fill_id="f-1", qty="10", price="100.00",
                fee="0.05", fee_currency="USD", filled_at="2026-06-18T00:00:00.000000Z")
    id1 = tmp_db.insert_fill_and_apply_fifo(oid, **fill)
    id2 = tmp_db.insert_fill_and_apply_fifo(oid, **fill)   # same identity → same row
    assert id1 == id2


def test_conflicting_duplicate_fill_raises(tmp_db):
    from server.execution_models import LedgerConflict
    oid = tmp_db.create_order_intent(
        account_id=23, strategy="s", client_order_id="cid-conf",
        symbol="AAPL", side="buy", order_type="market", requested_qty="10",
    )
    tmp_db.bind_order_ack(oid, broker_order_id="bro-2", state="ACKNOWLEDGED")
    tmp_db.insert_fill_and_apply_fifo(
        oid, broker_fill_id="f-9", qty="10", price="100.00",
        fee="0.05", fee_currency="USD", filled_at="2026-06-18T00:00:00.000000Z")
    with pytest.raises(LedgerConflict):
        # same broker_fill_id, DIFFERENT price → conflict
        tmp_db.insert_fill_and_apply_fifo(
            oid, broker_fill_id="f-9", qty="10", price="999.99",
            fee="0.05", fee_currency="USD", filled_at="2026-06-18T00:00:00.000000Z")
