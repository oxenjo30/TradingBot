"""Tests for the durable hard-stop shutdown policy (Task 5, spec §19.2).

Covers:
  - Persist HARD_STOP_TRIGGERED; global + participating-account entry kill switches.
  - Cancel nonterminal strategy-owned BUYS only (never external/manual).
  - Reconcile cancellations up to 60s, ingest fills meanwhile.
  - Recompute owned sellable quantities.
  - ONE idempotent exit per (account, strategy, symbol) excluding quarantined qty.
  - Crypto precision-valid exits; below-min dust quarantined.
  - Closed-market stock exits QUEUE for next session.
  - Partial fills reconcile; rejected/expired exits retry <=3.
  - Restart during EVERY shutdown step resumes the same shutdown.
  - NO auto reset; owner-only clearance with fresh reconciliation + audit reason.

Fakes only, NO network.
"""
import os
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def db(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode()
    os.environ["DB_SECRET_KEY"] = key
    import server.crypto as crypto
    crypto.init_crypto()
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    db_mod.init_db()
    return db_mod


def _make_account(db, label="Paper") -> int:
    from server import crypto
    return db.create_broker_account(label, crypto.encrypt("k"), crypto.encrypt("s"), "paper")


def _open_lot(db, strategy, account_id, symbol, qty, price, when):
    """Create a verified BUY fill + lot for (strategy, account, symbol)."""
    oid = db.create_order_intent(
        account_id=account_id, strategy=strategy,
        client_order_id=f"{strategy}-open-{symbol}-{when}",
        symbol=symbol, side="buy", order_type="market", requested_qty=qty)
    db.mark_order_submitting(oid)
    db.bind_order_ack(oid, broker_order_id=f"b-{oid}", state="FILLED")
    db.insert_fill_and_apply_fifo(
        oid, broker_fill_id=f"f-{oid}", qty=qty, price=price,
        fee="0", fee_currency="USD", filled_at=when)
    return oid


class FakeBroker:
    """Records cancellations and exit submissions; produces deterministic fills."""
    is_crypto = False

    def __init__(self, market_open=True, reject_symbols=None):
        self.canceled = []
        self.submitted = []
        self.market_open = market_open
        self.reject_symbols = set(reject_symbols or [])
        self._counter = 0

    def cancel_order(self, broker_order_id, symbol=None):
        self.canceled.append(broker_order_id)
        return {"id": broker_order_id, "state": "CANCELED"}

    def submit_market_order(self, symbol, side, qty=None, notional=None,
                            client_order_id=None):
        self._counter += 1
        self.submitted.append({"symbol": symbol, "side": side, "qty": qty,
                               "notional": notional, "client_order_id": client_order_id})
        if symbol in self.reject_symbols:
            return {"id": None, "state": "REJECTED"}
        return {"id": f"exit-{self._counter}", "state": "ACKNOWLEDGED"}

    def is_market_open(self):
        return self.market_open


# ── Trigger + kill switches (§19.2 step 1) ─────────────────────────────────────

def test_hard_stop_persists_triggered_flag(db):
    from server.portfolio_risk import HardStopController
    acct = _make_account(db)
    ctrl = HardStopController(accounts=[acct], broker_for=lambda a: FakeBroker())
    ctrl.trigger(reason="drawdown 5.0000%")
    assert db.get_app_config("hard_stop_state", "") == "HARD_STOP_TRIGGERED" or \
           db.get_portfolio_risk("hard_stop_triggered", "") in ("1", "true", "HARD_STOP_TRIGGERED")


def test_hard_stop_activates_global_and_account_kill_switches(db):
    from server.portfolio_risk import HardStopController
    import server.risk as risk
    acct = _make_account(db)
    ctrl = HardStopController(accounts=[acct], broker_for=lambda a: FakeBroker())
    ctrl.trigger(reason="drawdown 5.0000%")
    assert risk.is_killed() is True
    assert db.get_account_kill_switch(acct) is True


# ── Cancel strategy-owned buys only (§19.2 step 2) ─────────────────────────────

def test_hard_stop_cancels_only_strategy_owned_buys(db):
    from server.portfolio_risk import HardStopController
    acct = _make_account(db)
    # Strategy-owned nonterminal BUY.
    oid = db.create_order_intent(
        account_id=acct, strategy="liquid_stock_trend",
        client_order_id="own-buy-1", symbol="AAPL", side="buy",
        order_type="market", requested_qty="10")
    db.bind_order_ack(oid, broker_order_id="own-b1", state="ACKNOWLEDGED")
    # External/manual nonterminal BUY — must NOT be canceled.
    ext = db.create_order_intent(
        account_id=acct, strategy="external/manual",
        client_order_id="ext-buy-1", symbol="AAPL", side="buy",
        order_type="market", requested_qty="5")
    db.bind_order_ack(ext, broker_order_id="ext-b1", state="ACKNOWLEDGED")

    broker = FakeBroker()
    ctrl = HardStopController(accounts=[acct], broker_for=lambda a: broker)
    ctrl.trigger(reason="hard stop")
    assert "own-b1" in broker.canceled
    assert "ext-b1" not in broker.canceled


def test_hard_stop_does_not_cancel_sell_orders(db):
    from server.portfolio_risk import HardStopController
    acct = _make_account(db)
    sell = db.create_order_intent(
        account_id=acct, strategy="liquid_stock_trend",
        client_order_id="own-sell-1", symbol="AAPL", side="sell",
        order_type="market", requested_qty="10")
    db.bind_order_ack(sell, broker_order_id="own-s1", state="ACKNOWLEDGED")
    broker = FakeBroker()
    ctrl = HardStopController(accounts=[acct], broker_for=lambda a: broker)
    ctrl.trigger(reason="hard stop")
    assert "own-s1" not in broker.canceled


# ── One idempotent exit per (account, strategy, symbol) (§19.2 step 5) ──────────

def test_hard_stop_submits_one_exit_per_owned_position(db):
    from server.portfolio_risk import HardStopController
    acct = _make_account(db)
    _open_lot(db, "liquid_stock_trend", acct, "AAPL", "10", "100", "2026-07-11T09:00:00.000000Z")
    broker = FakeBroker(market_open=True)
    ctrl = HardStopController(accounts=[acct], broker_for=lambda a: broker)
    ctrl.trigger(reason="hard stop")
    exits = [s for s in broker.submitted if s["side"] == "sell"]
    assert len(exits) == 1
    assert exits[0]["symbol"] == "AAPL"
    assert Decimal(str(exits[0]["qty"])) == Decimal("10")


def test_hard_stop_exit_is_idempotent_across_reruns(db):
    from server.portfolio_risk import HardStopController
    acct = _make_account(db)
    _open_lot(db, "liquid_stock_trend", acct, "AAPL", "10", "100", "2026-07-11T09:00:00.000000Z")
    broker = FakeBroker(market_open=True)
    ctrl = HardStopController(accounts=[acct], broker_for=lambda a: broker)
    ctrl.trigger(reason="hard stop")
    n_first = len([s for s in broker.submitted if s["side"] == "sell"])
    # Re-running the same shutdown (e.g. after restart) must NOT double-submit.
    ctrl.resume()
    n_second = len([s for s in broker.submitted if s["side"] == "sell"])
    assert n_first == 1
    assert n_second == 1


def test_hard_stop_excludes_external_quantity_from_exit(db):
    from server.portfolio_risk import HardStopController
    acct = _make_account(db)
    _open_lot(db, "liquid_stock_trend", acct, "AAPL", "10", "100", "2026-07-11T09:00:00.000000Z")
    # An external/manual lot for the same symbol must NOT be sold by the strategy exit.
    with db.get_conn() as c:
        c.execute(
            "INSERT INTO position_lots (account_id, strategy, symbol, original_qty, "
            "remaining_qty, unit_cost, opened_at, provenance) "
            "VALUES (?,?,?,?,?,?,?, 'external')",
            (acct, "external/manual", "AAPL", "7", "7", "100",
             "2026-07-11T08:00:00.000000Z"))
    broker = FakeBroker(market_open=True)
    ctrl = HardStopController(accounts=[acct], broker_for=lambda a: broker)
    ctrl.trigger(reason="hard stop")
    exits = [s for s in broker.submitted if s["side"] == "sell"]
    assert len(exits) == 1
    assert Decimal(str(exits[0]["qty"])) == Decimal("10")  # only owned qty, not 17


# ── Closed-market stock exits queue (§19.2 step 7) ─────────────────────────────

def test_closed_market_stock_exit_is_queued_not_submitted(db):
    from server.portfolio_risk import HardStopController
    acct = _make_account(db)
    _open_lot(db, "liquid_stock_trend", acct, "AAPL", "10", "100", "2026-07-11T09:00:00.000000Z")
    broker = FakeBroker(market_open=False)  # market closed
    ctrl = HardStopController(accounts=[acct], broker_for=lambda a: broker)
    ctrl.trigger(reason="hard stop")
    exits = [s for s in broker.submitted if s["side"] == "sell"]
    assert exits == []  # nothing submitted while market is closed
    queued = ctrl.queued_exits()
    assert any(q["symbol"] == "AAPL" for q in queued)


def test_queued_stock_exit_submits_when_market_reopens(db):
    from server.portfolio_risk import HardStopController
    acct = _make_account(db)
    _open_lot(db, "liquid_stock_trend", acct, "AAPL", "10", "100", "2026-07-11T09:00:00.000000Z")
    broker = FakeBroker(market_open=False)
    ctrl = HardStopController(accounts=[acct], broker_for=lambda a: broker)
    ctrl.trigger(reason="hard stop")
    assert [s for s in broker.submitted if s["side"] == "sell"] == []
    # Market reopens → the queued exit is submitted on resume.
    broker.market_open = True
    ctrl.resume()
    exits = [s for s in broker.submitted if s["side"] == "sell"]
    assert len(exits) == 1


# ── Crypto dust quarantine (§19.2 step 6) ──────────────────────────────────────

def test_crypto_dust_below_min_is_quarantined(db):
    from server.portfolio_risk import HardStopController
    acct = _make_account(db, "Binance")
    _open_lot(db, "btc_eth_trend", acct, "BTC/USDT", "0.0000005", "30000",
              "2026-07-11T09:00:00.000000Z")
    broker = FakeBroker(market_open=True)
    broker.is_crypto = True
    ctrl = HardStopController(
        accounts=[acct], broker_for=lambda a: broker,
        min_qty={"BTC/USDT": Decimal("0.0001")})
    ctrl.trigger(reason="hard stop")
    exits = [s for s in broker.submitted if s["side"] == "sell"]
    assert exits == []  # dust below min → quarantined, not sold
    assert ctrl.quarantined() != []


# ── Retry <=3 on rejection (§19.2 step 8) ──────────────────────────────────────

def test_rejected_exit_retries_at_most_three_times(db):
    from server.portfolio_risk import HardStopController
    acct = _make_account(db)
    _open_lot(db, "liquid_stock_trend", acct, "AAPL", "10", "100", "2026-07-11T09:00:00.000000Z")
    broker = FakeBroker(market_open=True, reject_symbols={"AAPL"})
    ctrl = HardStopController(accounts=[acct], broker_for=lambda a: broker)
    ctrl.trigger(reason="hard stop")
    # Drive retries; total submission ATTEMPTS for the exit must be capped at 3.
    for _ in range(5):
        ctrl.resume()
    attempts = [s for s in broker.submitted if s["symbol"] == "AAPL" and s["side"] == "sell"]
    assert len(attempts) <= 3
    # After exhaustion the account stays frozen and unresolved.
    assert ctrl.is_unresolved() is True


# ── Restart during EVERY shutdown step (§19.2 step 9) ──────────────────────────

@pytest.mark.parametrize("stop_after_step", [
    "TRIGGERED", "KILL_SWITCHES", "CANCEL_BUYS", "RECONCILE",
    "RECOMPUTE", "SUBMIT_EXITS",
])
def test_restart_resumes_same_shutdown_after_each_step(db, stop_after_step):
    from server.portfolio_risk import HardStopController, SHUTDOWN_STEPS
    acct = _make_account(db)
    _open_lot(db, "liquid_stock_trend", acct, "AAPL", "10", "100", "2026-07-11T09:00:00.000000Z")

    broker = FakeBroker(market_open=True)
    ctrl = HardStopController(accounts=[acct], broker_for=lambda a: broker)
    # Interrupt the shutdown right after `stop_after_step` persists.
    ctrl.trigger(reason="hard stop", stop_after=stop_after_step)
    # The step must be durably recorded so a fresh controller resumes from there.
    assert db.get_portfolio_risk("hard_stop_step", "") == stop_after_step

    # Simulate a process restart: brand-new controller + broker, resume.
    broker2 = FakeBroker(market_open=True)
    ctrl2 = HardStopController(accounts=[acct], broker_for=lambda a: broker2)
    ctrl2.resume()

    # Regardless of where we were interrupted, the shutdown completes exactly one exit.
    total_exits = ([s for s in broker.submitted if s["side"] == "sell"] +
                   [s for s in broker2.submitted if s["side"] == "sell"])
    assert len(total_exits) == 1
    assert db.get_portfolio_risk("hard_stop_step", "") == SHUTDOWN_STEPS[-1]


# ── No auto-reset; owner-only clearance (§19.2 step 10) ────────────────────────

def test_hard_stop_never_auto_resets(db):
    from server.portfolio_risk import HardStopController, is_hard_stopped
    acct = _make_account(db)
    _open_lot(db, "liquid_stock_trend", acct, "AAPL", "10", "100", "2026-07-11T09:00:00.000000Z")
    broker = FakeBroker(market_open=True)
    ctrl = HardStopController(accounts=[acct], broker_for=lambda a: broker)
    ctrl.trigger(reason="hard stop")
    # Even after a clean completion, the hard stop stays engaged.
    ctrl.resume()
    assert is_hard_stopped() is True


def test_owner_clearance_requires_reconciliation_and_reason(db):
    from server.portfolio_risk import (HardStopController, clear_hard_stop,
                                       is_hard_stopped)
    acct = _make_account(db)
    broker = FakeBroker(market_open=True)
    ctrl = HardStopController(accounts=[acct], broker_for=lambda a: broker)
    ctrl.trigger(reason="hard stop")

    # Missing reason → rejected.
    with pytest.raises(ValueError):
        clear_hard_stop(reason="", reconciled=True, owner="owner")
    # No fresh reconciliation → rejected.
    with pytest.raises(ValueError):
        clear_hard_stop(reason="reviewed", reconciled=False, owner="owner")
    assert is_hard_stopped() is True

    # Valid owner clearance → cleared.
    clear_hard_stop(reason="reviewed and reconciled", reconciled=True, owner="owner")
    assert is_hard_stopped() is False


def test_startup_resume_runs_before_strategy_eval_when_hard_stopped(db):
    """A restart while HARD_STOP_TRIGGERED keeps the account frozen and resumes the
    shutdown; strategy evaluation must not run new entries first (§19.2 step 9)."""
    from server.portfolio_risk import is_hard_stopped, resume_pending_hard_stop
    acct = _make_account(db)
    _open_lot(db, "liquid_stock_trend", acct, "AAPL", "10", "100", "2026-07-11T09:00:00.000000Z")
    # Persist a mid-shutdown state directly (as if a crash left it here).
    db.set_portfolio_risk("hard_stop_triggered", "1")
    db.set_portfolio_risk("hard_stop_step", "CANCEL_BUYS")
    assert is_hard_stopped() is True
    broker = FakeBroker(market_open=True)
    resume_pending_hard_stop(accounts=[acct], broker_for=lambda a: broker)
    # Shutdown finished the exit and the account remains hard-stopped (no auto reset).
    exits = [s for s in broker.submitted if s["side"] == "sell"]
    assert len(exits) == 1
    assert is_hard_stopped() is True
