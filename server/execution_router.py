"""Execution router — the single seam that routes EVERY order path through the
execution ledger (Task 4, spec §19.7 complete order-path coverage, §19.8 migration
authority / shadow vs authoritative).

All SIX order paths call this module:
  - automated (engine strategy orders)  → owner = the strategy name
  - manual (POST /api/orders)           → owner = "manual"
  - webhook (POST /api/webhook/signal)  → owner = "webhook"
  - take-profit (engine TP pass)        → owner = the ORIGINAL opening strategy
  - close-position (DELETE /positions/{symbol}) → owner = the selected owner(s)
  - close-all (DELETE /positions)       → owner = the selected owner(s)

Two modes (§19.8), read from app_config key ``execution_ledger_mode``:

  shadow (DEFAULT)
    The ledger RECORDS an observation intent so we can see the order flow, but it
    MUST NOT submit through the new path and MUST NOT mutate legacy positions. The
    LEGACY engine stays authoritative; live behavior is unchanged. `route_order`
    returns ``legacy_authoritative=True`` so the caller runs its existing submit +
    legacy bookkeeping exactly as before.

  authoritative
    The legacy direct-submit path is DISABLED. `route_order` submits ONCE through
    ``ExecutionService`` (persist-before-submit, at-most-once economic submission),
    binds the acknowledgement, and returns ``legacy_authoritative=False``. Strategy
    lots/P&L change ONLY when confirmed fills are ingested by ``poll_account`` — an
    acknowledgement is never a fill, and legacy ``record_open_trade`` /
    ``close_trade_and_record_perf`` on mere acknowledgement no longer run.

Owner tagging and owner-scoped closes are enforced here so no path can bypass them.

Anything unrecognized fails SAFE to shadow: an unknown/blank mode never silently
enables authoritative live submission.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from . import db

_VALID_MODES = ("shadow", "authoritative")


# ── Feature flags (§19.8) ────────────────────────────────────────────────────────

def execution_ledger_mode() -> str:
    """Return 'shadow' (default) or 'authoritative'.

    Any unrecognized/blank value fails SAFE to 'shadow' — an unknown flag must never
    silently enable authoritative live submission."""
    val = (db.get_app_config("execution_ledger_mode", "shadow") or "shadow").strip().lower()
    return val if val in _VALID_MODES else "shadow"


def is_authoritative() -> bool:
    return execution_ledger_mode() == "authoritative"


def automation_quiesced() -> bool:
    """Whether automation is quiesced (paused). Default False — current behavior."""
    val = (db.get_app_config("automation_quiesced", "0") or "0").strip().lower()
    return val in ("1", "true", "yes", "on")


def set_execution_ledger_mode(mode: str) -> None:
    m = (mode or "").strip().lower()
    if m not in _VALID_MODES:
        raise ValueError(f"execution_ledger_mode must be one of {_VALID_MODES}, got {mode!r}")
    db.set_app_config("execution_ledger_mode", m)


def set_automation_quiesced(on: bool) -> None:
    db.set_app_config("automation_quiesced", "1" if on else "0")


# ── Owner-quantity helpers (§4.3, §19.7) ─────────────────────────────────────────

def owned_sellable_qty(strategy: str, account_id: int, symbol: str) -> Decimal:
    """The quantity `strategy` may sell on this account/symbol: its own remaining
    lots minus reserved nonterminal exits. Never another strategy's or the full
    broker position (§4.3)."""
    return db.get_sellable_qty(strategy, account_id, symbol)


def owners_holding_symbol(account_id: int, symbol: str) -> list[str]:
    """Strategies that currently own lots for (account, symbol)."""
    sym = db.canonical_symbol(symbol)
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT DISTINCT strategy FROM position_lots "
            "WHERE account_id=? AND symbol=? AND provenance NOT IN ('external') "
            "AND CAST(remaining_qty AS REAL) > 0",
            (account_id, sym)).fetchall()
    return [r["strategy"] for r in rows]


def owner_symbols(account_id: int, owner: str) -> list[str]:
    """Canonical symbols this owner currently holds open lots for on the account."""
    return sorted(db.get_strategy_positions(owner, account_id).keys())


def _new_cid(owner: str) -> str:
    return f"{owner}-{uuid.uuid4().hex[:16]}"


# ── The routing seam (§19.7, §19.8) ──────────────────────────────────────────────

def record_intent_shadow(*, account_id: int, owner: str, symbol: str, side: str,
                         qty: str | None = None, notional: str | None = None,
                         order_type: str = "market",
                         client_order_id: str | None = None) -> int:
    """Persist an observation intent WITHOUT submitting or mutating any lot (shadow).

    Returns the execution_order id. The intent stays in INTENT_PERSISTED — it is a
    record that the legacy path handled this order, nothing more. It never becomes a
    fill and never creates a lot, so legacy positions are untouched (§19.8)."""
    return db.create_order_intent(
        account_id=account_id, strategy=owner, client_order_id=client_order_id or _new_cid(owner),
        symbol=symbol, side=side, order_type=order_type,
        requested_qty=qty, requested_notional=notional,
    )


def route_order(*, broker, account_id: int, owner: str, symbol: str, side: str,
                qty: str | None = None, notional: str | None = None,
                order_type: str = "market",
                client_order_id: str | None = None) -> dict:
    """Route ONE order through the ledger, honoring the execution_ledger_mode flag.

    Returns a dict:
      { "mode": "shadow"|"authoritative",
        "order_id": <execution_order id>,
        "legacy_authoritative": bool }

    - shadow (default): records an observation intent, does NOT submit through the
      new path, does NOT mutate lots. legacy_authoritative=True → caller runs its
      existing submit + bookkeeping unchanged.
    - authoritative: submits ONCE through ExecutionService and binds the ack.
      legacy_authoritative=False → caller must NOT run the legacy submit or the
      legacy record_open_trade / close_trade_and_record_perf.
    """
    if is_authoritative():
        from .execution_service import ExecutionService
        svc = ExecutionService(broker, account_id=account_id)
        order_id = svc.submit(
            strategy=owner, symbol=symbol, side=side, qty=qty, notional=notional,
            order_type=order_type, client_order_id=client_order_id,
        )
        return {"mode": "authoritative", "order_id": order_id,
                "legacy_authoritative": False}

    order_id = record_intent_shadow(
        account_id=account_id, owner=owner, symbol=symbol, side=side,
        qty=qty, notional=notional, order_type=order_type,
        client_order_id=client_order_id,
    )
    return {"mode": "shadow", "order_id": order_id, "legacy_authoritative": True}


def route_take_profit(*, broker, account_id: int, position: dict,
                      take_profit_pct: float) -> dict | None:
    """Route a take-profit exit for one live broker position through the ledger.

    Sells ONLY the ORIGINAL opening strategy's OWNED quantity (§4.3, §19.7), never
    the full broker position. The owner is resolved from the ledger's owned lots
    (falling back to the legacy open_trades attribution). Returns the route_order
    result, or None when nothing is owned / the gain is below threshold.
    """
    symbol = position["symbol"]
    if position.get("side", "long") != "long":
        return None
    plpc = position.get("unrealized_plpc", 0.0)
    if take_profit_pct <= 0 or plpc < take_profit_pct:
        return None

    # Resolve the owning strategy from owned lots first (authoritative ownership),
    # then fall back to legacy open_trades attribution.
    owners = owners_holding_symbol(account_id, symbol)
    owner = owners[0] if owners else db.get_open_trade_strategy(symbol, account_id)
    if not owner:
        return None

    # Clamp to what THIS owner may actually sell — never the full broker position.
    sellable = owned_sellable_qty(owner, account_id, symbol)
    if sellable <= 0:
        return None

    from .execution_models import decimal_text
    return route_order(
        broker=broker, account_id=account_id, owner=owner, symbol=symbol,
        side="sell", qty=decimal_text(sellable), order_type="market",
    )


def route_owner_close(*, broker, account_id: int, owners: list[str],
                      symbol: str | None = None) -> list[dict]:
    """Close positions for the SELECTED owner(s) only (§19.7).

    - symbol given  → close that owner's owned quantity of that symbol (close-position)
    - symbol None   → close every symbol each owner owns (close-all for owner)

    Each exit sells ONLY the owner's own sellable quantity. Returns one route_order
    result per exit intent created.
    """
    from .execution_models import decimal_text
    results: list[dict] = []
    for owner in owners:
        if symbol is not None:
            targets = [db.canonical_symbol(symbol)]
        else:
            targets = owner_symbols(account_id, owner)
        for sym in targets:
            sellable = owned_sellable_qty(owner, account_id, sym)
            if sellable <= 0:
                continue
            results.append(route_order(
                broker=broker, account_id=account_id, owner=owner, symbol=sym,
                side="sell", qty=decimal_text(sellable), order_type="market",
            ))
    return results


def parse_owners(owner_param: str | None) -> list[str]:
    """Parse the ``owner`` query parameter into a de-duplicated owner list.

    Explicit user closes affect only the selected owner(s); multiple owners are
    allowed only when the request explicitly names them, comma-separated (§19.7).
    Returns [] when nothing is selected (the caller then rejects the request)."""
    if not owner_param:
        return []
    seen: list[str] = []
    for part in owner_param.split(","):
        o = part.strip()
        if o and o not in seen:
            seen.append(o)
    return seen
