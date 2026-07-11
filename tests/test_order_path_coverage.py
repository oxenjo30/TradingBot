"""Task 4 — every order path routes through the execution ledger.

RED-first tests (spec §19.7 complete order-path coverage, §19.8 shadow vs
authoritative). All SIX order paths — automated (engine), manual (POST /api/orders),
webhook, take-profit, close-position, close-all — must:

  - persist an execution INTENT in the ledger, and
  - NEVER mutate strategy lots before CONFIRMED fills (acknowledgement is not a fill).

Owner tagging (§19.7):
  - automated  → the strategy name
  - manual     → "manual"
  - webhook    → "webhook"
  - take-profit→ the ORIGINAL opening strategy
  - close-position / close-all → only the selected owner(s)

Feature flags (§19.8):
  - execution_ledger_mode = 'shadow' (DEFAULT) | 'authoritative'
  - automation_quiesced
  In SHADOW mode the ledger RECORDS an observation intent but MUST NOT submit through
  the new path or mutate legacy positions — the legacy engine stays authoritative and
  live behavior is unchanged. In AUTHORITATIVE mode the legacy direct-submit path is
  disabled and orders flow through ExecutionService with fills ingested later.

No network calls. Brokers are fakes; DB is an isolated per-test SQLite file.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest


# ── DB isolation ────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path, monkeypatch):
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "paths.db")
    db_mod.init_db()
    return db_mod


@pytest.fixture
def acct(db):
    """A real paper broker account row so account-level FKs (kill switch) resolve."""
    return db.create_broker_account(
        label="paper-paths", api_key_enc="k", api_secret_enc="s",
        account_type="paper", broker="binance",
    )


# ── Fake capability-complete broker (no network) ─────────────────────────────────

class FakeBroker:
    supports_authoritative_lookup = True

    def __init__(self):
        self.submit_calls: list[dict] = []
        self.orders: dict[str, dict] = {}
        self.by_client: dict[str, list[dict]] = {}
        self.fills_by_order: dict[str, list] = {}

    def submit_market_order(self, symbol, side, qty=None, notional=None, client_order_id=None):
        self.submit_calls.append(dict(symbol=symbol, side=side, qty=qty,
                                      notional=notional, client_order_id=client_order_id))
        boid = f"bro-{len(self.orders) + 1}"
        order = {"broker_order_id": boid, "client_order_id": client_order_id,
                 "symbol": symbol, "side": side,
                 "requested_qty": str(qty) if qty is not None else None,
                 "state": "ACKNOWLEDGED"}
        self.orders[boid] = order
        self.by_client.setdefault(client_order_id, []).append(order)
        return {"id": boid, "symbol": symbol, "side": side, "qty": qty, "status": "accepted"}

    def get_order(self, order_id, symbol=None):
        return self.orders.get(order_id)

    def get_order_by_client_id(self, client_id, symbol=None):
        m = self.by_client.get(client_id, [])
        return m[0] if len(m) == 1 else (None if not m else m[0])

    def get_order_fills(self, order_id, since=None, symbol=None):
        return list(self.fills_by_order.get(order_id, []))


def _pending_orders(db, account_id):
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT id, strategy, symbol, side, requested_qty, requested_notional, state "
            "FROM execution_orders WHERE account_id=? AND strategy NOT LIKE '%::exit_reservation' "
            "ORDER BY id",
            (account_id,)).fetchall()
    return [dict(r) for r in rows]


def _lot_count(db):
    with db.get_conn() as c:
        return c.execute("SELECT COUNT(*) AS n FROM position_lots").fetchone()["n"]


# ── Feature flags: default is SHADOW (do NOT change live behavior) ────────────────

def test_default_mode_is_shadow(db):
    import server.execution_router as router
    assert router.execution_ledger_mode() == "shadow"


def test_default_automation_not_quiesced(db):
    import server.execution_router as router
    # Default keeps current behavior — automation is not quiesced by default.
    assert router.automation_quiesced() is False


def test_mode_is_settable_to_authoritative(db):
    import server.execution_router as router
    db.set_app_config("execution_ledger_mode", "authoritative")
    assert router.execution_ledger_mode() == "authoritative"


def test_unknown_mode_falls_back_to_shadow(db):
    import server.execution_router as router
    db.set_app_config("execution_ledger_mode", "garbage")
    # Fail safe: an unrecognized value must NEVER silently enable authoritative.
    assert router.execution_ledger_mode() == "shadow"


# ── SHADOW mode: records an observation intent, does NOT submit / mutate lots ─────

def test_shadow_records_intent_without_submitting_or_mutating_lots(db, acct):
    import server.execution_router as router
    broker = FakeBroker()
    res = router.route_order(
        broker=broker, account_id=acct, owner="liquid_stock_trend",
        symbol="AAPL", side="buy", qty="10",
    )
    # Shadow mode: an intent is persisted (observation) ...
    orders = _pending_orders(db, acct)
    assert len(orders) == 1
    assert orders[0]["strategy"] == "liquid_stock_trend"
    assert orders[0]["side"] == "buy"
    # ... but the NEW path did NOT submit to the broker ...
    assert broker.submit_calls == []
    # ... and NO lot was created (no fill ingested) — legacy stays authoritative.
    assert _lot_count(db) == 0
    # The router tells the caller the legacy path is still authoritative.
    assert res["mode"] == "shadow"
    assert res["legacy_authoritative"] is True


# ── AUTHORITATIVE mode: submits through the ledger, no lot before fills ───────────

def test_authoritative_submits_through_ledger_and_no_lot_before_fills(db, acct):
    import server.execution_router as router
    db.set_app_config("execution_ledger_mode", "authoritative")
    broker = FakeBroker()
    res = router.route_order(
        broker=broker, account_id=acct, owner="liquid_stock_trend",
        symbol="AAPL", side="buy", qty="10",
    )
    assert res["mode"] == "authoritative"
    assert res["legacy_authoritative"] is False
    # Submitted exactly once through the new path.
    assert len(broker.submit_calls) == 1
    order = db.get_execution_order(res["order_id"])
    assert order["broker_order_id"] is not None
    assert order["state"] == "ACKNOWLEDGED"          # ack, NOT filled
    # Acknowledgement is NOT a fill: no lot yet.
    assert _lot_count(db) == 0


def test_authoritative_lot_appears_only_after_confirmed_fill(db, acct):
    import server.execution_router as router
    from server.execution_service import ExecutionService
    from server.execution_models import Fill
    db.set_app_config("execution_ledger_mode", "authoritative")
    broker = FakeBroker()
    res = router.route_order(broker=broker, account_id=acct, owner="s",
                             symbol="AAPL", side="buy", qty="10")
    boid = db.get_execution_order(res["order_id"])["broker_order_id"]
    broker.fills_by_order[boid] = [
        Fill(broker_fill_id="f-1", broker_order_id=boid, qty="10", price="100",
             fee="0", fee_currency="USD", filled_at="2026-06-18T15:00:00.000000Z"),
    ]
    ExecutionService(broker, account_id=acct).poll_account()
    assert db.get_sellable_qty("s", acct, "AAPL") == Decimal("10")


# ── Manual path (POST /api/orders) owner-tags "manual" ───────────────────────────

def test_manual_order_records_intent_tagged_manual(client, monkeypatch):
    """POST /api/orders records an execution intent owned by 'manual' (§19.7)."""
    import server.db as db
    from server.main import app  # noqa: F401  (ensures app import)
    acct_id = _make_paper_account(client)
    fake = _install_fake_broker(monkeypatch, "alpaca")
    r = client.post("/api/orders", json={
        "symbol": "AAPL", "qty": 3, "side": "buy", "account_id": acct_id})
    assert r.status_code == 200, r.text
    rows = _pending_orders(db, acct_id)
    assert any(o["strategy"] == "manual" and o["side"] == "buy" for o in rows), rows


# ── Webhook path owner-tags "webhook" ────────────────────────────────────────────

def test_webhook_order_records_intent_tagged_webhook(client, monkeypatch):
    import server.db as db
    acct_id = _make_paper_account(client)
    db.set_webhook_token("tok-123")
    _install_fake_broker(monkeypatch, "alpaca")
    r = client.post("/api/webhook/signal",
                    headers={"X-Webhook-Token": "tok-123"},
                    json={"symbol": "AAPL", "side": "buy", "qty": 2,
                          "account_id": acct_id})
    assert r.status_code == 200, r.text
    rows = _pending_orders(db, acct_id)
    assert any(o["strategy"] == "webhook" and o["side"] == "buy" for o in rows), rows


# ── Take-profit sells ONLY that strategy's OWNED quantity ─────────────────────────

def test_take_profit_sells_only_owned_quantity(db, acct):
    """Take-profit must sell only the ORIGINAL opening strategy's OWNED lots, never
    the full broker position (spec §4.3, §19.7)."""
    import server.execution_router as router
    # sma_cross owns 4 of AAPL; the broker position shows 10 (rest is manual/other).
    _open_owned_lot(db, "sma_cross", acct, "AAPL", "4", "100")
    broker = FakeBroker()
    live_position = {"symbol": "AAPL", "qty": 10.0, "unrealized_plpc": 0.20,
                     "market_value": 1200.0, "current_price": 120.0, "side": "long"}
    router.route_take_profit(
        broker=broker, account_id=acct, position=live_position,
        take_profit_pct=0.05,
    )
    orders = _pending_orders(db, acct)
    tp = [o for o in orders if o["side"] == "sell"]
    assert len(tp) == 1
    # The sell intent quantity is clamped to the strategy's OWNED 4, not 10.
    assert Decimal(tp[0]["requested_qty"]) == Decimal("4")
    assert tp[0]["strategy"] == "sma_cross"


def test_take_profit_skips_when_strategy_owns_nothing(db, acct):
    """If no strategy owns the broker position, take-profit creates no exit."""
    import server.execution_router as router
    broker = FakeBroker()
    live_position = {"symbol": "AAPL", "qty": 10.0, "unrealized_plpc": 0.20,
                     "market_value": 1200.0, "current_price": 120.0, "side": "long"}
    router.route_take_profit(broker=broker, account_id=acct,
                             position=live_position, take_profit_pct=0.05)
    assert [o for o in _pending_orders(db, acct) if o["side"] == "sell"] == []


# ── Close-position requires an owner selection ───────────────────────────────────

def test_close_position_requires_owner_selection(client, monkeypatch):
    """A manual close must name the owner(s) it affects; without one it is rejected
    (§19.7 — explicit closes affect only selected owners)."""
    acct_id = _make_paper_account(client)
    _install_fake_broker(monkeypatch, "alpaca")
    # No owner query param → 400.
    r = client.delete(f"/api/positions/AAPL?account_id={acct_id}")
    assert r.status_code == 400, r.text


def test_close_position_records_intent_for_selected_owner(client, monkeypatch):
    import server.db as db
    acct_id = _make_paper_account(client)
    _open_owned_lot(db, "sma_cross", acct_id, "AAPL", "5", "100")
    _install_fake_broker(monkeypatch, "alpaca")
    r = client.delete(f"/api/positions/AAPL?account_id={acct_id}&owner=sma_cross")
    assert r.status_code == 200, r.text
    rows = _pending_orders(db, acct_id)
    assert any(o["strategy"] == "sma_cross" and o["side"] == "sell" for o in rows), rows


def test_close_position_does_not_touch_other_owners(client, monkeypatch):
    import server.db as db
    acct_id = _make_paper_account(client)
    _open_owned_lot(db, "sma_cross", acct_id, "AAPL", "5", "100")
    _open_owned_lot(db, "bollinger", acct_id, "AAPL", "7", "100")
    _install_fake_broker(monkeypatch, "alpaca")
    client.delete(f"/api/positions/AAPL?account_id={acct_id}&owner=sma_cross")
    rows = [o for o in _pending_orders(db, acct_id) if o["side"] == "sell"]
    # Only sma_cross gets a close intent; bollinger is untouched.
    assert all(o["strategy"] == "sma_cross" for o in rows), rows


# ── Close-all affects only selected owner(s) unless multiple explicitly named ─────

def test_close_all_requires_owner_selection(client, monkeypatch):
    acct_id = _make_paper_account(client)
    _install_fake_broker(monkeypatch, "alpaca")
    r = client.delete(f"/api/positions?account_id={acct_id}")
    assert r.status_code == 400, r.text


def test_close_all_records_intents_only_for_selected_owner(client, monkeypatch):
    import server.db as db
    acct_id = _make_paper_account(client)
    _open_owned_lot(db, "sma_cross", acct_id, "AAPL", "5", "100")
    _open_owned_lot(db, "sma_cross", acct_id, "MSFT", "3", "200")
    _open_owned_lot(db, "bollinger", acct_id, "TSLA", "2", "300")
    _install_fake_broker(monkeypatch, "alpaca")
    r = client.delete(f"/api/positions?account_id={acct_id}&owner=sma_cross")
    assert r.status_code == 200, r.text
    rows = [o for o in _pending_orders(db, acct_id) if o["side"] == "sell"]
    owners = {o["strategy"] for o in rows}
    assert owners == {"sma_cross"}, rows
    # both sma_cross symbols got an exit
    syms = {o["symbol"] for o in rows}
    assert syms == {"AAPL", "MSFT"}, rows


def test_close_all_multiple_owners_when_explicitly_named(client, monkeypatch):
    import server.db as db
    acct_id = _make_paper_account(client)
    _open_owned_lot(db, "sma_cross", acct_id, "AAPL", "5", "100")
    _open_owned_lot(db, "bollinger", acct_id, "TSLA", "2", "300")
    _install_fake_broker(monkeypatch, "alpaca")
    r = client.delete(f"/api/positions?account_id={acct_id}&owner=sma_cross,bollinger")
    assert r.status_code == 200, r.text
    rows = [o for o in _pending_orders(db, acct_id) if o["side"] == "sell"]
    assert {o["strategy"] for o in rows} == {"sma_cross", "bollinger"}, rows


# ── Never mutate lots before confirmed fills (all API paths) ──────────────────────

def test_manual_order_does_not_create_lot_before_fill(client, monkeypatch):
    import server.db as db
    acct_id = _make_paper_account(client)
    _install_fake_broker(monkeypatch, "alpaca")
    client.post("/api/orders", json={"symbol": "AAPL", "qty": 3, "side": "buy",
                                     "account_id": acct_id})
    # Acknowledgement is not a fill: no verified lot from a mere manual buy ack.
    with db.get_conn() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM position_lots").fetchone()["n"]
    assert n == 0


# ── helpers that create owned lots / accounts / fake brokers ─────────────────────

def _open_owned_lot(db, strategy, account_id, symbol, qty, price):
    import uuid
    cid = f"{strategy}-{uuid.uuid4().hex[:12]}"
    oid = db.create_order_intent(account_id=account_id, strategy=strategy,
                                 client_order_id=cid, symbol=symbol, side="buy",
                                 order_type="market", requested_qty=qty)
    db.bind_order_ack(oid, broker_order_id=f"bro-{cid}", state="ACKNOWLEDGED")
    db.insert_fill_and_apply_fifo(oid, broker_fill_id=f"f-{cid}", qty=qty, price=price,
                                  fee="0", fee_currency="USD",
                                  filled_at="2026-06-18T00:00:00.000000Z")
    return oid


def _make_paper_account(client):
    r = client.post("/api/broker-accounts", json={
        "label": "acct", "api_key": "KEY1234", "api_secret": "SEC5678",
        "account_type": "paper", "broker": "alpaca"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _install_fake_broker(monkeypatch, broker):
    """Patch _get_broker_client so API endpoints use a capability-complete fake."""
    import server.main as main
    fake = FakeBroker()
    fake.get_positions = lambda: []
    fake.close_position = lambda *a, **k: None
    fake.close_all_positions = lambda *a, **k: None
    fake.get_account_summary = lambda: {"equity": 10000.0, "cash": 10000.0,
                                        "buying_power": 10000.0}
    fake.get_latest_quote = lambda *a, **k: {"bid": 100.0, "ask": 100.0, "price": 100.0}
    monkeypatch.setattr(main, "_get_broker_client", lambda account_id=None: fake)
    return fake
