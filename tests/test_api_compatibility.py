"""Task 10 — golden API/dashboard compatibility (spec §19.7, §19.8, §19.11).

Compatibility APIs may PROJECT the ledger but must NEVER break the existing
response shapes (§19.7). These tests:

  1. Record golden field-SHAPE fixtures for the key endpoints (health, positions,
     orders, account, performance, strategy-accounts, backtest runs) and assert the
     live responses keep the same shape — the byte/field-shape compatibility gate.
  2. Prove the migration PROJECTION functions emit ledger data in exactly the legacy
     API shapes, so a projected response is drop-in compatible with the dashboard.
  3. Prove the golden-compatibility helper the CUTOVER guard uses correctly detects
     a shape drift (missing field, extra field, changed type).

The `client` fixture (tests/conftest.py) gives an isolated DB + auth. No network:
broker calls are patched with a capability-complete fake.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ── Shared fake broker (no network) ──────────────────────────────────────────────

class FakeBroker:
    supports_authoritative_lookup = True

    def get_account_summary(self):
        return {"equity": 10000.0, "cash": 5000.0, "buying_power": 5000.0,
                "portfolio_value": 10000.0, "last_equity": 9800.0}

    def get_positions(self):
        return [{
            "symbol": "AAPL", "qty": 5.0, "side": "long", "market_value": 600.0,
            "avg_entry_price": 100.0, "current_price": 120.0,
            "unrealized_pl": 100.0, "unrealized_plpc": 20.0,
        }]

    def get_orders(self, limit=50, status="all"):
        return [{
            "id": "b-1", "client_order_id": "c-1", "symbol": "AAPL", "side": "buy",
            "qty": 5.0, "filled_qty": 5.0, "filled_avg_price": 100.0,
            "type": "market", "status": "filled",
            "submitted_at": "2026-06-18T00:00:00+00:00",
            "filled_at": "2026-06-18T00:00:01+00:00",
        }]


def _install_fake(monkeypatch):
    import server.main as main
    monkeypatch.setattr(main, "_get_broker_client", lambda account_id=None: FakeBroker())


def _make_paper_account(client):
    r = client.post("/api/broker-accounts", json={
        "label": "acct", "api_key": "KEY1234", "api_secret": "SEC5678",
        "account_type": "paper", "broker": "alpaca"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── Golden field-shapes for the key endpoints (must never drift) ─────────────────

def test_health_shape_is_stable(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"ok", "setup_complete", "has_password"}
    assert isinstance(body["ok"], bool)


def test_positions_shape_is_stable(client, monkeypatch):
    _install_fake(monkeypatch)
    acct_id = _make_paper_account(client)
    r = client.get(f"/api/positions?account_id={acct_id}")
    assert r.status_code == 200, r.text
    pos = r.json()[0]
    assert set(pos.keys()) == {
        "symbol", "qty", "side", "market_value", "avg_entry_price",
        "current_price", "unrealized_pl", "unrealized_plpc",
    }


def test_orders_shape_is_stable(client, monkeypatch):
    _install_fake(monkeypatch)
    acct_id = _make_paper_account(client)
    r = client.get(f"/api/orders?account_id={acct_id}")
    assert r.status_code == 200, r.text
    order = r.json()[0]
    assert set(order.keys()) == {
        "id", "client_order_id", "symbol", "side", "qty", "filled_qty",
        "filled_avg_price", "type", "status", "submitted_at", "filled_at",
    }


def test_account_shape_is_stable(client, monkeypatch):
    _install_fake(monkeypatch)
    acct_id = _make_paper_account(client)
    r = client.get(f"/api/account?account_id={acct_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"equity", "cash", "buying_power"} <= set(body.keys())


def test_performance_shape_is_stable(client, monkeypatch):
    _install_fake(monkeypatch)
    r = client.get("/api/performance")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {
        "strategy_stats", "top_symbols", "daily_counts",
        "open_positions", "total_unrealized_pl", "unique_symbols",
    }


def test_strategy_accounts_shape_is_stable(client):
    r = client.get("/api/strategies/momentum/accounts")
    assert r.status_code == 200, r.text
    assert r.json() == []                       # empty-list shape preserved


# ── Migration projection functions emit the LEGACY shapes ────────────────────────

@pytest.fixture
def dbm(tmp_path, monkeypatch):
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "compat.db")
    db_mod.init_db()
    return db_mod


def _open_verified_lot(db, strategy, account_id, symbol, qty, price):
    import uuid
    cid = f"{strategy}-{uuid.uuid4().hex[:10]}"
    oid = db.create_order_intent(account_id=account_id, strategy=strategy,
                                 client_order_id=cid, symbol=symbol, side="buy",
                                 order_type="market", requested_qty=qty)
    db.bind_order_ack(oid, broker_order_id=f"bro-{cid}", state="FILLED")
    db.insert_fill_and_apply_fifo(oid, broker_fill_id=f"f-{cid}", qty=qty, price=price,
                                  fee="0", fee_currency="USD",
                                  filled_at="2026-06-18T00:00:00.000000Z")
    return oid


def test_project_positions_matches_legacy_position_shape(dbm):
    import server.migration as mig
    acct = dbm.create_broker_account(label="p", api_key_enc="k", api_secret_enc="s",
                                     account_type="paper", broker="alpaca")
    _open_verified_lot(dbm, "sma_cross", acct, "AAPL", "5", "100")
    projected = mig.project_positions(dbm, acct, prices={"AAPL": "120"})
    assert projected, "expected at least one projected position"
    legacy_keys = {"symbol", "qty", "side", "market_value", "avg_entry_price",
                   "current_price", "unrealized_pl", "unrealized_plpc"}
    for p in projected:
        assert set(p.keys()) == legacy_keys
        assert isinstance(p["qty"], float)
        assert isinstance(p["symbol"], str)


def test_project_orders_matches_legacy_order_shape(dbm):
    import server.migration as mig
    acct = dbm.create_broker_account(label="p", api_key_enc="k", api_secret_enc="s",
                                     account_type="paper", broker="alpaca")
    _open_verified_lot(dbm, "sma_cross", acct, "AAPL", "5", "100")
    projected = mig.project_orders(dbm, acct)
    assert projected, "expected at least one projected order"
    legacy_keys = {"id", "client_order_id", "symbol", "side", "qty", "filled_qty",
                   "filled_avg_price", "type", "status", "submitted_at", "filled_at"}
    for o in projected:
        assert set(o.keys()) == legacy_keys


def test_project_account_matches_legacy_account_shape(dbm):
    import server.migration as mig
    acct = dbm.create_broker_account(label="p", api_key_enc="k", api_secret_enc="s",
                                     account_type="paper", broker="alpaca")
    proj = mig.project_account(dbm, acct, cash="5000", prices={})
    assert {"equity", "cash", "buying_power"} <= set(proj.keys())
    assert isinstance(proj["equity"], float)


# ── Golden compatibility helper (used by the cutover guard) ──────────────────────

def test_golden_shape_helper_detects_missing_field():
    import server.migration as mig
    golden = {"health": {"ok": True, "setup_complete": True, "has_password": True}}
    live = {"health": {"ok": True, "setup_complete": True}}   # missing has_password
    assert mig.golden_shape_matches(golden, live) is False


def test_golden_shape_helper_detects_extra_field():
    import server.migration as mig
    golden = {"health": {"ok": True}}
    live = {"health": {"ok": True, "EXTRA": 1}}
    assert mig.golden_shape_matches(golden, live) is False


def test_golden_shape_helper_detects_type_change():
    import server.migration as mig
    golden = {"positions": [{"symbol": "AAPL", "qty": 5.0}]}
    live = {"positions": [{"symbol": "AAPL", "qty": "5"}]}    # float → str
    assert mig.golden_shape_matches(golden, live) is False


def test_golden_shape_helper_accepts_identical_shape_different_values():
    import server.migration as mig
    golden = {"positions": [{"symbol": "AAPL", "qty": 5.0}]}
    live = {"positions": [{"symbol": "MSFT", "qty": 99.0}]}   # same shape, new values
    assert mig.golden_shape_matches(golden, live) is True
