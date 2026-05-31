import pytest
import sqlite3
from pathlib import Path


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    db_mod.init_db()
    return db_mod


def test_add_issued_license(tmp_db):
    tmp_db.add_issued_license("order_001", "buyer@test.com", "KEY-ABC")
    rows = tmp_db.list_issued_licenses()
    assert len(rows) == 1
    assert rows[0]["order_id"] == "order_001"
    assert rows[0]["buyer_email"] == "buyer@test.com"
    assert rows[0]["license_key"] == "KEY-ABC"
    assert rows[0]["revoked"] == 0


def test_duplicate_order_id_ignored(tmp_db):
    tmp_db.add_issued_license("order_001", "buyer@test.com", "KEY-ABC")
    tmp_db.add_issued_license("order_001", "buyer@test.com", "KEY-ABC")  # duplicate
    assert len(tmp_db.list_issued_licenses()) == 1


def test_revoke_license(tmp_db):
    tmp_db.add_issued_license("order_002", "buyer2@test.com", "KEY-DEF")
    row = tmp_db.list_issued_licenses()[0]
    tmp_db.revoke_issued_license(row["id"])
    updated = tmp_db.list_issued_licenses()[0]
    assert updated["revoked"] == 1


def test_list_issued_licenses_search(tmp_db):
    tmp_db.add_issued_license("order_003", "alice@test.com", "KEY-GHI")
    tmp_db.add_issued_license("order_004", "bob@test.com", "KEY-JKL")
    results = tmp_db.list_issued_licenses(search="alice")
    assert len(results) == 1
    assert results[0]["buyer_email"] == "alice@test.com"


def test_get_issued_license_by_id(tmp_db):
    tmp_db.add_issued_license("order_005", "carol@test.com", "KEY-MNO")
    row = tmp_db.list_issued_licenses()[0]
    fetched = tmp_db.get_issued_license(row["id"])
    assert fetched["buyer_email"] == "carol@test.com"


def test_update_resent_at(tmp_db):
    tmp_db.add_issued_license("order_006", "dave@test.com", "KEY-PQR")
    row = tmp_db.list_issued_licenses()[0]
    tmp_db.update_resent_at(row["id"])
    updated = tmp_db.get_issued_license(row["id"])
    assert updated["resent_at"] is not None
