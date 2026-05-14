"""Tests for per-account kill switch and strategy P&L attribution."""
import pytest
import server.db as db_mod


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    db_mod.init_db()


def _make_account(label="Test") -> int:
    from server import crypto
    return db_mod.create_broker_account(label, crypto.encrypt("k"), crypto.encrypt("s"), "paper")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def test_account_kill_switch_default_is_false():
    assert db_mod.get_account_kill_switch(account_id=999) is False


def test_set_and_get_account_kill_switch():
    acct_id = _make_account()
    db_mod.set_account_kill_switch(account_id=acct_id, on=True)
    assert db_mod.get_account_kill_switch(account_id=acct_id) is True


def test_kill_switch_isolated_per_account():
    id1 = _make_account("Acct1")
    id2 = _make_account("Acct2")
    db_mod.set_account_kill_switch(account_id=id1, on=True)
    db_mod.set_account_kill_switch(account_id=id2, on=False)
    assert db_mod.get_account_kill_switch(id1) is True
    assert db_mod.get_account_kill_switch(id2) is False


def test_set_kill_switch_toggle_off():
    acct_id = _make_account()
    db_mod.set_account_kill_switch(account_id=acct_id, on=True)
    db_mod.set_account_kill_switch(account_id=acct_id, on=False)
    assert db_mod.get_account_kill_switch(acct_id) is False


# ---------------------------------------------------------------------------
# risk.check_all — per-account kill switch enforcement
# ---------------------------------------------------------------------------

def test_account_kill_switch_blocks_order():
    from server.risk import check_all, RiskViolation
    acct_id = _make_account()
    db_mod.set_account_kill_switch(account_id=acct_id, on=True)
    fake_account = {"equity": 10000, "daytrade_count": 0, "last_equity": 10000}
    with pytest.raises(RiskViolation, match="kill switch"):
        check_all("AAPL", "buy", fake_account, day_trade_count=0,
                  notional=500, account_id=acct_id)


def test_account_kill_switch_off_does_not_block_for_kill_switch_reason():
    from server.risk import check_all, RiskViolation
    acct_id = _make_account()
    db_mod.set_account_kill_switch(account_id=acct_id, on=False)
    fake_account = {"equity": 10000, "daytrade_count": 0, "last_equity": 10000}
    try:
        check_all("AAPL", "buy", fake_account, day_trade_count=0,
                  notional=500, account_id=acct_id)
    except RiskViolation as e:
        # Any other risk guard may fire, but not the per-account kill switch
        assert "account" not in str(e).lower() or "kill switch" not in str(e).lower()


def test_global_kill_switch_still_blocks():
    from server.risk import check_all, RiskViolation
    db_mod.set_risk_setting("kill_switch", "true")
    fake_account = {"equity": 10000, "daytrade_count": 0, "last_equity": 10000}
    with pytest.raises(RiskViolation, match="kill switch"):
        check_all("AAPL", "buy", fake_account, day_trade_count=0,
                  notional=500, account_id=None)


# ---------------------------------------------------------------------------
# Performance attribution
# ---------------------------------------------------------------------------

def test_performance_by_strategy_account_returns_list():
    rows = db_mod.performance_by_strategy_account()
    assert isinstance(rows, list)


def test_performance_by_strategy_account_empty_on_fresh_db():
    rows = db_mod.performance_by_strategy_account()
    assert rows == []


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

def test_kill_switch_api_404_for_unknown_account(client):
    r = client.get("/api/broker-accounts/999/kill-switch")
    assert r.status_code == 404


def test_kill_switch_api_get_returns_false_by_default(client):
    r = client.post("/api/broker-accounts", json={
        "label": "Test", "api_key": "k", "api_secret": "s", "account_type": "paper"
    })
    acct_id = r.json()["id"]
    r2 = client.get(f"/api/broker-accounts/{acct_id}/kill-switch")
    assert r2.status_code == 200
    assert r2.json()["kill_switch"] is False


def test_kill_switch_api_post_sets_and_returns_state(client):
    r = client.post("/api/broker-accounts", json={
        "label": "Test2", "api_key": "k", "api_secret": "s", "account_type": "paper"
    })
    acct_id = r.json()["id"]
    r2 = client.post(f"/api/broker-accounts/{acct_id}/kill-switch?on=true")
    assert r2.status_code == 200
    assert r2.json()["kill_switch"] is True
    # Toggle back off
    r3 = client.post(f"/api/broker-accounts/{acct_id}/kill-switch?on=false")
    assert r3.json()["kill_switch"] is False
