"""Task 3 — normalized broker acknowledgement, fill recovery, and execution service.

RED-first tests (spec §5, §19.3, §19.4). No network calls: brokers are fakes that
record calls and return recorded/sanitized responses.

Covered behaviors (plan Task 3 Step 1):
  - Timeout-after-accept recovery by client id: the order WAS placed; recovery finds
    it via get_order_by_client_id and does NOT double-submit (§19.3).
  - At-most-once ECONOMIC submission under a simulated network timeout + retry: one
    economic order even if the HTTP call is retried.
  - Ambiguous submission with NO broker record after 3 lookups over 60s → UNKNOWN +
    freeze the account + forbid automatic resubmission (§19.3).
  - Multiple client-id matches → freeze the account (§19.3).
  - poll_account ingests fills idempotently using a persisted watermark and a
    24-hour overlap refetch (§19.13 retention).
  - Unsupported adapter (no authoritative lookup) → fail closed (§19.4).

Uses an isolated per-test SQLite DB (same pattern as test_execution_ledger.py).
"""
from __future__ import annotations

from decimal import Decimal

import pytest


# ── DB isolation ────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path, monkeypatch):
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "exec.db")
    db_mod.init_db()
    return db_mod


@pytest.fixture
def acct(db):
    """A real paper broker account row so account-level FKs (kill switch) resolve.

    Production always has a broker_accounts row for the account being traded; the
    account_settings.account_id kill-switch column references it. Tests create one
    and use its id so freezing an account is exercised against the real constraint."""
    return db.create_broker_account(
        label="paper-exec", api_key_enc="k", api_secret_enc="s",
        account_type="paper", broker="binance",
    )


# ── Fake brokers (no network) ───────────────────────────────────────────────────

class FakeBroker:
    """A capability-complete fake adapter.

    Records submit calls and exposes authoritative lookup by broker/client id plus
    fill listing. `fills_by_order` maps broker_order_id -> list of normalized Fill.
    """
    supports_authoritative_lookup = True

    def __init__(self):
        self.submit_calls: list[dict] = []
        self.orders: dict[str, dict] = {}          # broker_order_id -> normalized order
        self.by_client: dict[str, list[dict]] = {} # client_order_id -> [normalized order]
        self.fills_by_order: dict[str, list] = {}
        self.submit_should_timeout = False
        self.submit_side_effect_places_order = False

    # -- submission (compat method used by the service) --
    def submit_market_order(self, symbol, side, qty=None, notional=None, client_order_id=None):
        self.submit_calls.append(dict(symbol=symbol, side=side, qty=qty,
                                      notional=notional, client_order_id=client_order_id))
        if self.submit_should_timeout:
            if self.submit_side_effect_places_order:
                # Order actually reached the exchange before the socket died.
                self._register(client_order_id, symbol, side, qty)
            raise TimeoutError("network timeout after send")
        boid = self._register(client_order_id, symbol, side, qty)
        return {"id": boid, "symbol": symbol, "side": side, "qty": qty, "status": "accepted"}

    def _register(self, client_order_id, symbol, side, qty):
        boid = f"bro-{len(self.orders) + 1}"
        order = {
            "broker_order_id": boid,
            "client_order_id": client_order_id,
            "symbol": symbol,
            "side": side,
            "requested_qty": str(qty) if qty is not None else None,
            "state": "ACKNOWLEDGED",
        }
        self.orders[boid] = order
        self.by_client.setdefault(client_order_id, []).append(order)
        return boid

    # -- normalized lookup (§5, §19.3) --
    def get_order(self, order_id, symbol=None):
        return self.orders.get(order_id)

    def get_order_by_client_id(self, client_id, symbol=None):
        matches = self.by_client.get(client_id, [])
        if not matches:
            return None
        if len(matches) > 1:
            raise MultipleOrdersError(client_id)
        return matches[0]

    def get_order_fills(self, order_id, since=None, symbol=None):
        return list(self.fills_by_order.get(order_id, []))


class MultipleOrdersError(Exception):
    """Raised by an adapter when a client id maps to more than one broker order."""


class UnsupportedBroker:
    """An adapter that CANNOT provide authoritative lookup — automation must fail closed."""
    supports_authoritative_lookup = False

    def submit_market_order(self, *a, **k):
        return {"id": "x", "status": "accepted"}


# ── helpers ─────────────────────────────────────────────────────────────────────

def _fill(bid, oid, qty, price, fee="0", cur="USD", at="2026-06-18T00:00:00.000000Z"):
    from server.execution_models import Fill
    return Fill(broker_fill_id=bid, broker_order_id=oid, qty=qty, price=price,
                fee=fee, fee_currency=cur, filled_at=at)


# ── Happy path submission binds the broker id ───────────────────────────────────

def test_submit_persists_intent_marks_submitting_and_binds_ack(db, acct):
    from server.execution_service import ExecutionService
    broker = FakeBroker()
    svc = ExecutionService(broker, account_id=acct)
    order_id = svc.submit(strategy="liquid_stock_trend", symbol="AAPL", side="buy",
                          qty="10", client_order_id="cid-happy")
    row = db.get_execution_order(order_id)
    assert row is not None
    assert row["broker_order_id"] == "bro-1"          # ack bound
    assert row["state"] == "ACKNOWLEDGED"
    assert len(broker.submit_calls) == 1              # submitted exactly once
    assert broker.submit_calls[0]["client_order_id"] == "cid-happy"


def test_submit_is_atmost_once_economic_no_double_submit_on_duplicate_cid(db, acct):
    """A second submit() with the same client id must not place a second economic order."""
    from server.execution_service import ExecutionService
    broker = FakeBroker()
    svc = ExecutionService(broker, account_id=acct)
    svc.submit(strategy="s", symbol="AAPL", side="buy", qty="10", client_order_id="cid-dup")
    with pytest.raises(Exception):
        svc.submit(strategy="s", symbol="AAPL", side="buy", qty="10", client_order_id="cid-dup")
    assert len(broker.submit_calls) == 1              # only the first reached the broker


# ── Timeout-after-accept recovery by client id (§19.3) ──────────────────────────

def test_timeout_after_accept_recovers_by_client_id_without_double_submit(db, acct):
    """The order WAS placed but the ack timed out. Recovery finds it by client id and
    binds the broker id — it does NOT submit again (at-most-once economic)."""
    from server.execution_service import ExecutionService
    broker = FakeBroker()
    broker.submit_should_timeout = True
    broker.submit_side_effect_places_order = True     # order reached exchange
    svc = ExecutionService(broker, account_id=acct)

    order_id = svc.submit(strategy="s", symbol="AAPL", side="buy", qty="10",
                          client_order_id="cid-timeout")
    row = db.get_execution_order(order_id)
    # Recovery found the placed order and bound it; account NOT frozen.
    assert row["broker_order_id"] == "bro-1"
    assert row["state"] == "ACKNOWLEDGED"
    assert len(broker.submit_calls) == 1              # never resubmitted economically
    assert db.get_account_kill_switch(acct) is False


def test_timeout_with_no_broker_record_freezes_after_three_lookups(db, acct):
    """Timeout AND the order never reached the broker. After 3 client-id lookups over
    60s finding nothing, declare UNKNOWN, freeze the account, forbid resubmission."""
    from server.execution_service import ExecutionService
    broker = FakeBroker()
    broker.submit_should_timeout = True
    broker.submit_side_effect_places_order = False    # order never placed
    svc = ExecutionService(broker, account_id=acct)

    lookups = {"n": 0}
    orig = broker.get_order_by_client_id
    def counting(cid, symbol=None):
        lookups["n"] += 1
        return orig(cid, symbol)
    broker.get_order_by_client_id = counting

    order_id = svc.submit(strategy="s", symbol="AAPL", side="buy", qty="10",
                          client_order_id="cid-lost", recovery_interval=0)
    row = db.get_execution_order(order_id)
    assert row["state"] == "UNKNOWN"
    assert lookups["n"] == 3                            # exactly three lookups
    assert db.get_account_kill_switch(acct) is True    # account frozen
    assert len(broker.submit_calls) == 1               # no automatic resubmission


def test_multiple_client_id_matches_freezes_account(db, acct):
    """More than one broker order for a client id is ambiguous → freeze (§19.3)."""
    from server.execution_service import ExecutionService
    broker = FakeBroker()
    broker.submit_should_timeout = True
    # Pre-seed two orders under the same client id so recovery lookup is ambiguous.
    broker._register("cid-multi", "AAPL", "buy", "10")
    broker._register("cid-multi", "AAPL", "buy", "10")
    svc = ExecutionService(broker, account_id=acct)

    order_id = svc.submit(strategy="s", symbol="AAPL", side="buy", qty="10",
                          client_order_id="cid-multi", recovery_interval=0)
    row = db.get_execution_order(order_id)
    assert row["state"] == "UNKNOWN"
    assert db.get_account_kill_switch(acct) is True


# ── Unsupported adapter fails closed (§19.4) ────────────────────────────────────

def test_unsupported_adapter_fails_closed(db):
    from server.execution_service import ExecutionService, UnsupportedBrokerError
    with pytest.raises(UnsupportedBrokerError):
        ExecutionService(UnsupportedBroker(), account_id=7)


# ── poll_account: watermark + 24h overlap + idempotent ingestion ────────────────

def test_poll_account_ingests_fills_and_advances_watermark(db, acct):
    from server.execution_service import ExecutionService
    broker = FakeBroker()
    svc = ExecutionService(broker, account_id=acct)
    oid = svc.submit(strategy="s", symbol="AAPL", side="buy", qty="10",
                     client_order_id="cid-poll")
    boid = db.get_execution_order(oid)["broker_order_id"]
    broker.fills_by_order[boid] = [
        _fill("f-1", boid, "10", "100.00", fee="0.05",
              at="2026-06-18T15:00:00.000000Z"),
    ]
    ingested = svc.poll_account()
    assert ingested == 1
    # lot exists for the strategy
    assert db.get_sellable_qty("s", acct, "AAPL") == Decimal("10")
    # watermark advanced to the latest fill time
    wm = db.get_fill_watermark(acct)
    assert wm is not None and wm >= "2026-06-18T15:00:00.000000Z"


def test_poll_account_is_idempotent_across_cycles(db, acct):
    from server.execution_service import ExecutionService
    broker = FakeBroker()
    svc = ExecutionService(broker, account_id=acct)
    oid = svc.submit(strategy="s", symbol="AAPL", side="buy", qty="10",
                     client_order_id="cid-poll2")
    boid = db.get_execution_order(oid)["broker_order_id"]
    broker.fills_by_order[boid] = [
        _fill("f-1", boid, "10", "100.00", at="2026-06-18T15:00:00.000000Z"),
    ]
    svc.poll_account()
    # Second cycle re-fetches the 24h overlap — the same fill must NOT double-apply.
    again = svc.poll_account()
    assert again == 0
    assert db.get_sellable_qty("s", acct, "AAPL") == Decimal("10")


def test_poll_account_refetches_24h_overlap(db, acct):
    """Even after the watermark advances, the next cycle refetches a 24h overlap so a
    late-arriving fill inside that window is captured (§19.13)."""
    from server.execution_service import ExecutionService
    broker = FakeBroker()
    svc = ExecutionService(broker, account_id=acct)
    oid = svc.submit(strategy="s", symbol="AAPL", side="buy", qty="10",
                     client_order_id="cid-poll3")
    boid = db.get_execution_order(oid)["broker_order_id"]
    broker.fills_by_order[boid] = [
        _fill("f-1", boid, "6", "100.00", at="2026-06-18T15:00:00.000000Z"),
    ]
    svc.poll_account()
    # A late fill arrives with an EARLIER timestamp than the watermark but within 24h.
    broker.fills_by_order[boid].append(
        _fill("f-2", boid, "4", "100.00", at="2026-06-18T14:30:00.000000Z"))
    n = svc.poll_account()
    assert n == 1
    assert db.get_sellable_qty("s", acct, "AAPL") == Decimal("10")


# ── Partial fill then canceled preserves fills (§19.3) ──────────────────────────

def test_partial_fill_then_cancel_preserves_fills(db, acct):
    """cancel-after-partial preserves the partial fill and cancels only the remainder."""
    from server.execution_service import ExecutionService
    broker = FakeBroker()
    svc = ExecutionService(broker, account_id=acct)
    oid = svc.submit(strategy="s", symbol="AAPL", side="buy", qty="10",
                     client_order_id="cid-partial")
    boid = db.get_execution_order(oid)["broker_order_id"]
    # 6 of 10 fill, then the order is canceled.
    broker.fills_by_order[boid] = [
        _fill("f-1", boid, "6", "100.00", at="2026-06-18T15:00:00.000000Z"),
    ]
    svc.poll_account()
    broker.orders[boid]["state"] = "CANCELED"
    svc.poll_account()
    # The 6 filled remain owned; the 4 canceled remainder is simply not there.
    assert db.get_sellable_qty("s", acct, "AAPL") == Decimal("6")
    row = db.get_execution_order(oid)
    assert row["state"] == "CANCELED"


# ── Delayed fee append, not overwrite (§19.5) ───────────────────────────────────

def test_delayed_fee_appends_adjustment_not_overwrite(db, acct):
    """A late fee correction appends a fee_adjustment row; the original fill is immutable."""
    from server.execution_service import ExecutionService
    broker = FakeBroker()
    svc = ExecutionService(broker, account_id=acct)
    oid = svc.submit(strategy="s", symbol="AAPL", side="buy", qty="10",
                     client_order_id="cid-fee")
    boid = db.get_execution_order(oid)["broker_order_id"]
    broker.fills_by_order[boid] = [
        _fill("f-1", boid, "10", "100.00", fee="0.05",
              at="2026-06-18T15:00:00.000000Z"),
    ]
    svc.poll_account()
    # A late fee correction arrives for the SAME fill (append, don't rewrite).
    db.append_fee_adjustment(account_id=acct, broker_fill_id="f-1", fee="0.02",
                             fee_currency="USD", reason="late maker rebate reversal")
    total = db.get_fill_total_fee(account_id=acct, broker_fill_id="f-1")
    assert total == Decimal("0.07")
    # original fill fee unchanged
    with db.get_conn() as c:
        row = c.execute("SELECT fee FROM execution_fills WHERE broker_fill_id='f-1'").fetchone()
    assert Decimal(row["fee"]) == Decimal("0.05")
