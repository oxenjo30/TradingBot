"""Execution-ledger domain types (Task 1).

Decimal-safe order/fill primitives for the strategy-owned execution ledger.
See docs/superpowers/specs/2026-07-11-trading-strategy-rebuild-design.md §19.3, §19.5.

Design rules enforced here:
  - Money and quantities are canonical decimal TEXT: no exponent notation, at most
    18 fractional digits, negative zero normalized to "0" (§19.5).
  - Order states distinguish terminal from nonterminal; acknowledgement states
    (accepted/pending/new/open/acknowledged) are NEVER fills (§19.3, plan anti-pattern).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum

MAX_FRACTIONAL_DIGITS = 18


class LedgerConflict(Exception):
    """A duplicate broker fill identity arrived with different economic values.

    Idempotent re-ingestion of an identical fill is fine; a conflicting one (same
    id, different qty/price/fee) means the ledger and broker disagree and the
    account must freeze rather than silently overwrite."""


# ── Order state model (§19.3) ───────────────────────────────────────────────────

class OrderState(str, Enum):
    INTENT_PERSISTED = "INTENT_PERSISTED"
    SUBMITTING       = "SUBMITTING"
    ACKNOWLEDGED     = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED           = "FILLED"
    CANCEL_PENDING   = "CANCEL_PENDING"
    CANCELED         = "CANCELED"
    REJECTED         = "REJECTED"
    EXPIRED          = "EXPIRED"
    UNKNOWN          = "UNKNOWN"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATES


_TERMINAL_STATES = frozenset({
    OrderState.FILLED, OrderState.CANCELED,
    OrderState.REJECTED, OrderState.EXPIRED,
})


# ── Decimal canonical text (§19.5) ──────────────────────────────────────────────

def parse_decimal(value: str | Decimal | int) -> Decimal:
    """Parse to Decimal, rejecting exponent notation and non-finite values."""
    if isinstance(value, Decimal):
        d = value
    else:
        s = str(value).strip()
        if "e" in s.lower():
            raise ValueError(f"exponent notation not allowed: {value!r}")
        try:
            d = Decimal(s)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid decimal: {value!r}") from exc
    if not d.is_finite():
        raise ValueError(f"non-finite decimal: {value!r}")
    return d


def decimal_text(value: str | Decimal | int) -> str:
    """Return canonical decimal text: plain (no exponent), at most 18 fractional
    digits, negative zero normalized to '0', trailing zeros trimmed.

    Raises ValueError on exponent input, non-finite values, or more than 18
    fractional digits."""
    d = parse_decimal(value)

    # Reject excessive precision BEFORE normalization (0.1234...19 digits).
    exponent = d.as_tuple().exponent
    frac_digits = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    if frac_digits > MAX_FRACTIONAL_DIGITS:
        raise ValueError(
            f"too many fractional digits ({frac_digits} > {MAX_FRACTIONAL_DIGITS}): {value!r}"
        )

    # Normalize: drop trailing zeros but keep a plain (non-exponent) string.
    d = d.normalize()
    if d == 0:
        return "0"                       # collapses -0, 0.0, 0E+2, etc.
    # `f` format never uses exponent notation.
    text = format(d, "f")
    # format(...,'f') can still leave trailing zeros for some inputs; trim them.
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


# ── Normalized broker concepts (§5) ─────────────────────────────────────────────

@dataclass(frozen=True)
class OrderAck:
    """Broker acknowledgement — NOT a fill."""
    broker_order_id: str | None
    client_order_id: str
    requested_qty: str | None
    requested_notional: str | None
    state: OrderState
    submitted_at: str


@dataclass(frozen=True)
class Fill:
    """Confirmed execution. `broker_fill_id` is the stable idempotency key."""
    broker_fill_id: str
    broker_order_id: str
    qty: str
    price: str
    fee: str
    fee_currency: str
    filled_at: str
