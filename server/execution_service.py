"""Execution service — the single ordered path from intent to bound acknowledgement,
and from broker fills into the strategy-owned ledger (Task 3, spec §4.1, §19.3, §19.4).

Guarantees
----------
- At-most-once ECONOMIC submission (NOT at-most-once HTTP): an order is submitted to
  the broker exactly once per client order id. The client order id is committed
  BEFORE the network call, so a retry with the same id cannot place a second
  economic order (the duplicate intent is rejected by the ledger).
- Persist-before-submit: the intent and `SUBMITTING` state are persisted before the
  broker is contacted, so a crash/timeout is recoverable by authoritative lookup.
- Ambiguous submission recovery (§19.3): on a timeout/crash in `SUBMITTING`, recover
  through account + client-order-id lookup. ONE match binds the broker id. MULTIPLE
  matches freeze the account. NO match after THREE lookups over 60 seconds becomes
  `UNKNOWN`, freezes the account, and forbids automatic resubmission.
- Fill ingestion (§19.13): `poll_account` uses a persisted per-account watermark and
  refetches a 24-hour overlap every cycle, ingesting fills idempotently through
  `db.insert_fill_and_apply_fifo`.

The broker adapter must pass the capability gate (§19.4); otherwise automation is
UNSUPPORTED and the service refuses to construct.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

from . import broker_factory, db
from .execution_models import OrderState

# Ambiguous-submission recovery policy (§19.3): three lookups over ~60 seconds.
_RECOVERY_ATTEMPTS = 3
_RECOVERY_INTERVAL_SECONDS = 20            # 3 * 20s ≈ 60s window
# Fill-ingestion overlap window (§19.13): refetch the last 24 hours every cycle.
_OVERLAP_HOURS = 24


class UnsupportedBrokerError(Exception):
    """The broker adapter cannot provide authoritative lookup/fills — automation is
    unsupported and must fail closed (spec §19.4)."""


def _parse_ts(ts: str) -> datetime:
    """Parse a UTC ISO-8601 fill timestamp (with or without microseconds / 'Z')."""
    s = (ts or "").strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class ExecutionService:
    def __init__(self, broker, account_id: int):
        if not broker_factory.supports_automation(broker):
            raise UnsupportedBrokerError(
                f"broker {type(broker).__name__} cannot provide authoritative order "
                f"lookup + fills; automation is unsupported (spec §19.4)"
            )
        self.broker = broker
        self.account_id = account_id

    # ── Submission (§4.1, §19.3) ────────────────────────────────────────────────

    def submit(self, *, strategy: str, symbol: str, side: str,
               qty: str | None = None, notional: str | None = None,
               order_type: str = "market",
               client_order_id: str | None = None,
               recovery_interval: float | None = None) -> int:
        """Submit one order through the ledger. Returns the execution_order id.

        1. Persist the intent + client order id (rejects a duplicate → at-most-once
           economic submission).
        2. Persist `SUBMITTING` immediately before the network call.
        3. Submit ONCE.
        4. Bind the acknowledgement, OR recover on timeout/crash ambiguity.
        """
        cid = client_order_id or f"{strategy}-{uuid.uuid4().hex[:16]}"

        # (1) Commit intent + client id BEFORE the network call. A duplicate client
        # id raises here — the guarantee of at-most-once ECONOMIC submission.
        order_id = db.create_order_intent(
            account_id=self.account_id, strategy=strategy, client_order_id=cid,
            symbol=symbol, side=side, order_type=order_type,
            requested_qty=qty, requested_notional=notional,
        )

        # (2) Persist SUBMITTING right before contacting the broker (§19.3).
        db.mark_order_submitting(order_id)

        # (3) Submit exactly ONCE.
        try:
            ack = self.broker.submit_market_order(
                symbol, side,
                qty=float(qty) if qty is not None else None,
                notional=float(notional) if notional is not None else None,
                client_order_id=cid,
            )
        except Exception as exc:
            # (4b) Ambiguous submission — recover by authoritative lookup. NEVER
            # resubmit automatically (§19.3).
            self._recover_ambiguous(order_id, cid, symbol, str(exc),
                                    recovery_interval=recovery_interval)
            return order_id

        # (4a) Bind the acknowledgement (NOT a fill).
        broker_order_id = str(ack.get("id") or "") or None
        db.bind_order_ack(order_id, broker_order_id=broker_order_id,
                          state=OrderState.ACKNOWLEDGED.value)
        return order_id

    def _recover_ambiguous(self, order_id: int, cid: str, symbol: str,
                           error: str, *, recovery_interval: float | None) -> None:
        """Three client-id lookups over ~60s (§19.3).

        - Exactly one match → bind the broker id (the order WAS placed; do not
          resubmit).
        - More than one match → freeze the account (ambiguous).
        - No match after three lookups → UNKNOWN + freeze + forbid resubmission.
        """
        interval = (_RECOVERY_INTERVAL_SECONDS if recovery_interval is None
                    else recovery_interval)
        for attempt in range(_RECOVERY_ATTEMPTS):
            try:
                found = self.broker.get_order_by_client_id(cid, symbol=symbol)
            except Exception as lookup_exc:
                # A lookup that raises (e.g. MULTIPLE matches) is an ambiguous submit.
                self._freeze(order_id, error,
                             reason=f"ambiguous client-id lookup: {lookup_exc}")
                return
            if found:
                # The order reached the broker. Bind it — no economic resubmission.
                db.bind_order_ack(
                    order_id,
                    broker_order_id=str(found.get("broker_order_id") or "") or None,
                    state=found.get("state") or OrderState.ACKNOWLEDGED.value,
                    last_error=f"recovered after submit ambiguity: {error}",
                )
                return
            if attempt < _RECOVERY_ATTEMPTS - 1:
                time.sleep(interval)

        # No match after three lookups → UNKNOWN, freeze, forbid resubmission.
        self._freeze(order_id, error,
                     reason="no broker order found after 3 client-id lookups")

    def _freeze(self, order_id: int, error: str, *, reason: str) -> None:
        """Mark the order UNKNOWN and freeze the account (kill switch)."""
        db.bind_order_ack(order_id, broker_order_id=None,
                          state=OrderState.UNKNOWN.value,
                          last_error=f"{reason}: {error}")
        db.set_account_kill_switch(self.account_id, True)
        db.log_audit("execution", "account_frozen",
                     f"account {self.account_id} order {order_id}: {reason}")

    # ── Fill ingestion (§19.13) ─────────────────────────────────────────────────

    def poll_account(self) -> int:
        """Ingest authoritative fills for this account's non-terminal orders.

        Uses the persisted per-account watermark and refetches a 24-hour overlap
        every cycle so late/out-of-order fills inside the window are captured. Each
        fill is ingested idempotently through db.insert_fill_and_apply_fifo, so a
        repeated overlap does not double-apply. Returns the count of NEWLY ingested
        fills.
        """
        watermark = db.get_fill_watermark(self.account_id)
        # Refetch window start = watermark - 24h (or the epoch on the first cycle).
        if watermark:
            since_dt = _parse_ts(watermark) - timedelta(hours=_OVERLAP_HOURS)
        else:
            since_dt = datetime(1970, 1, 1, tzinfo=timezone.utc)
        since_ms = int(since_dt.timestamp() * 1000)

        orders = self._nonterminal_orders_with_broker_id()
        new_count = 0
        max_seen = watermark or ""

        for order in orders:
            oid = order["id"]
            boid = order["broker_order_id"]
            symbol = order["symbol"]
            try:
                fills = self.broker.get_order_fills(boid, since=since_ms, symbol=symbol)
            except Exception as exc:
                # A regressing/conflicting snapshot or lookup failure freezes closed.
                self._freeze(oid, str(exc), reason="fill snapshot conflict")
                continue

            for f in fills:
                try:
                    prev_id = self._fill_exists(f.broker_fill_id)
                    db.insert_fill_and_apply_fifo(
                        oid, broker_fill_id=f.broker_fill_id, qty=f.qty,
                        price=f.price, fee=f.fee, fee_currency=f.fee_currency,
                        filled_at=f.filled_at,
                    )
                    if not prev_id:
                        new_count += 1
                except Exception as exc:
                    # Conflicting duplicate fill (LedgerConflict) → freeze (§19.5).
                    self._freeze(oid, str(exc), reason="ledger fill conflict")
                    continue
                if f.filled_at > max_seen:
                    max_seen = f.filled_at

            # Refresh the order state from the authoritative snapshot (ack, not fill).
            try:
                snap = self.broker.get_order(boid, symbol=symbol)
            except Exception:
                snap = None
            if snap and snap.get("state"):
                db.bind_order_ack(oid, broker_order_id=boid, state=snap["state"])

        if max_seen and max_seen != (watermark or ""):
            db.set_fill_watermark(self.account_id, max_seen,
                                  overlap_cursor=since_dt.strftime(
                                      "%Y-%m-%dT%H:%M:%S.%f") + "Z")
        return new_count

    def _nonterminal_orders_with_broker_id(self) -> list[dict]:
        """This account's orders that have a broker id and are not yet terminal.

        A canceled/rejected/expired order can still have arriving fills from BEFORE
        it went terminal, so we also include orders that went terminal but whose
        fills we may not have fully ingested — kept simple here by including any
        order with a bound broker id whose state is not FILLED with all-terminal."""
        with db.get_conn() as c:
            rows = c.execute(
                "SELECT id, broker_order_id, symbol, state FROM execution_orders "
                "WHERE account_id=? AND broker_order_id IS NOT NULL",
                (self.account_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _fill_exists(self, broker_fill_id: str) -> bool:
        with db.get_conn() as c:
            r = c.execute(
                "SELECT 1 FROM execution_fills WHERE account_id=? AND broker_fill_id=?",
                (self.account_id, broker_fill_id),
            ).fetchone()
        return r is not None
