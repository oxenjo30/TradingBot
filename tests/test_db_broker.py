"""DB-layer tests for broker_accounts and strategy_accounts CRUD."""
import pytest
import server.db as db_mod


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    db_mod.init_db()


def _enc(s: str) -> str:
    from server import crypto
    return crypto.encrypt(s)


# ── broker_accounts CRUD ───────────────────────────────────────────────────────

def test_create_and_get_account():
    acct_id = db_mod.create_broker_account("Test", _enc("key123"), _enc("secret456"), "paper")
    assert isinstance(acct_id, int)
    row = db_mod.get_broker_account(acct_id)
    assert row["label"] == "Test"
    assert row["account_type"] == "paper"
    assert "api_secret" not in row  # never returned by get_broker_account


def test_get_account_not_found():
    assert db_mod.get_broker_account(9999) is None


def test_list_accounts():
    db_mod.create_broker_account("Alpha", _enc("k1"), _enc("s1"), "paper")
    db_mod.create_broker_account("Beta", _enc("k2"), _enc("s2"), "live")
    labels = [r["label"] for r in db_mod.get_broker_accounts()]
    assert "Alpha" in labels
    assert "Beta" in labels


def test_update_label():
    acct_id = db_mod.create_broker_account("Old", _enc("k"), _enc("s"), "paper")
    db_mod.update_broker_account(acct_id, label="New")
    assert db_mod.get_broker_account(acct_id)["label"] == "New"


def test_update_account_type():
    acct_id = db_mod.create_broker_account("Acct", _enc("k"), _enc("s"), "paper")
    db_mod.update_broker_account(acct_id, account_type="live")
    assert db_mod.get_broker_account(acct_id)["account_type"] == "live"


def test_update_no_fields_raises():
    acct_id = db_mod.create_broker_account("Acct", _enc("k"), _enc("s"), "paper")
    with pytest.raises(ValueError, match="at least one"):
        db_mod.update_broker_account(acct_id)


def test_rotate_credentials():
    from server import crypto
    acct_id = db_mod.create_broker_account("Acct", _enc("oldkey"), _enc("oldsec"), "paper")
    db_mod.update_broker_credentials(acct_id, _enc("newkey"), _enc("newsec"))
    import sqlite3
    conn = sqlite3.connect(db_mod.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT api_key, api_secret FROM broker_accounts WHERE id=?", (acct_id,)).fetchone()
    conn.close()
    assert crypto.decrypt(row["api_key"]) == "newkey"
    assert crypto.decrypt(row["api_secret"]) == "newsec"


def test_delete_account():
    acct_id = db_mod.create_broker_account("ToDelete", _enc("k"), _enc("s"), "paper")
    db_mod.delete_broker_account(acct_id)
    assert db_mod.get_broker_account(acct_id) is None


def test_delete_cascades_to_strategy_accounts():
    acct_id = db_mod.create_broker_account("Cascade", _enc("k"), _enc("s"), "paper")
    db_mod.upsert_strategy("momentum", enabled=False, params={})
    db_mod.assign_strategy_account("momentum", acct_id, enabled=True)
    assert len(db_mod.get_strategy_account_list("momentum")) == 1
    db_mod.delete_broker_account(acct_id)
    assert db_mod.get_strategy_account_list("momentum") == []


# ── strategy_accounts CRUD ─────────────────────────────────────────────────────

def test_assign_and_list():
    acct_id = db_mod.create_broker_account("Acct", _enc("k"), _enc("s"), "paper")
    db_mod.upsert_strategy("momentum", enabled=False, params={})
    inserted = db_mod.assign_strategy_account("momentum", acct_id, enabled=True)
    assert inserted is True
    rows = db_mod.get_strategy_account_list("momentum")
    assert any(r["id"] == acct_id for r in rows)


def test_assign_idempotent():
    acct_id = db_mod.create_broker_account("Acct", _enc("k"), _enc("s"), "paper")
    db_mod.upsert_strategy("momentum", enabled=False, params={})
    assert db_mod.assign_strategy_account("momentum", acct_id, True) is True
    assert db_mod.assign_strategy_account("momentum", acct_id, True) is False


def test_update_enabled_flag():
    acct_id = db_mod.create_broker_account("Acct", _enc("k"), _enc("s"), "paper")
    db_mod.upsert_strategy("momentum", enabled=False, params={})
    db_mod.assign_strategy_account("momentum", acct_id, enabled=True)
    updated = db_mod.update_strategy_account_enabled("momentum", acct_id, enabled=False)
    assert updated is True
    row = db_mod.get_strategy_account_list("momentum")[0]
    assert row["enabled"] == 0


def test_update_enabled_not_found():
    assert db_mod.update_strategy_account_enabled("momentum", 9999, False) is False


def test_unassign():
    acct_id = db_mod.create_broker_account("Acct", _enc("k"), _enc("s"), "paper")
    db_mod.upsert_strategy("momentum", enabled=False, params={})
    db_mod.assign_strategy_account("momentum", acct_id, enabled=True)
    db_mod.unassign_strategy_account("momentum", acct_id)
    assert db_mod.get_strategy_account_list("momentum") == []


def test_get_strategy_accounts_excludes_disabled():
    acct_id = db_mod.create_broker_account("Acct", _enc("k"), _enc("s"), "paper")
    db_mod.upsert_strategy("momentum", enabled=False, params={})
    db_mod.assign_strategy_account("momentum", acct_id, enabled=False)
    assert db_mod.get_strategy_accounts("momentum") == []


def test_get_broker_account_assignments():
    acct_id = db_mod.create_broker_account("Acct", _enc("k"), _enc("s"), "paper")
    db_mod.upsert_strategy("momentum", enabled=False, params={})
    db_mod.assign_strategy_account("momentum", acct_id, enabled=True)
    assignments = db_mod.get_broker_account_assignments(acct_id)
    assert "momentum" in assignments
