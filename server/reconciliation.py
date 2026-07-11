"""Broker reconciliation and external/manual quarantine (Task 2, spec §19.6).

`ReconciliationService.compare` compares settled broker holdings against verified
internal lots per canonical (account, symbol) and classifies each row:

  - VERIFIED  — broker and internal agree (delta 0 after accounting for open orders).
  - DUST      — nonzero delta but within tolerance (one broker increment AND the
                greater of $1 or one minimum notional in value).
  - FROZEN    — delta exceeds tolerance, OR broker holds quantity with no matching
                internal lots. Unmatched broker quantity is classified
                `external/manual`; automated strategies can never sell it.

Open orders are reported as reservations, NOT as missing inventory: an open sell
order reduces the settled broker quantity while the internal lot still exists, so
`settled + open_sell - open_buy` is compared against internal quantity.

Snapshots are persisted with stable ids (reconciliation_snapshots).

Pure/decimal, no network. Broker positions/increments/notionals/prices are passed
in by the caller (the execution/reconciliation layer that talks to the broker).
"""
from __future__ import annotations

from decimal import Decimal

from . import db
from .execution_models import decimal_text, parse_decimal

# Value tolerance floor is the greater of USD 1 or one minimum notional (§19.6).
_MIN_VALUE_TOLERANCE = Decimal("1")
# Default broker quantity increment when the caller does not specify one.
_DEFAULT_INCREMENT = Decimal("0.000001")


class ReconciliationService:
    def compare(self, account_id: int, broker_positions: dict[str, str],
                open_orders: list[dict] | None = None, *,
                increments: dict[str, str] | None = None,
                min_notionals: dict[str, str] | None = None,
                prices: dict[str, str] | None = None) -> list[dict]:
        """Reconcile one account. Returns one classified row per canonical symbol
        seen on either side, each persisted to reconciliation_snapshots.

        broker_positions : {symbol: settled_qty_text}
        open_orders      : [{symbol, side ('buy'|'sell'), qty}]  (reservations)
        increments       : {symbol: broker_qty_increment_text}
        min_notionals    : {symbol: minimum_notional_text}
        prices           : {symbol: reference_price_text}  (for value tolerance)
        """
        open_orders = open_orders or []
        increments = {db.canonical_symbol(k): v for k, v in (increments or {}).items()}
        min_notionals = {db.canonical_symbol(k): v for k, v in (min_notionals or {}).items()}
        prices = {db.canonical_symbol(k): v for k, v in (prices or {}).items()}

        internal = db.get_account_verified_qty(account_id)  # canonical → text

        # Settled broker quantity by canonical symbol.
        broker: dict[str, Decimal] = {}
        for sym, qty in broker_positions.items():
            broker[db.canonical_symbol(sym)] = parse_decimal(qty)

        # Net open-order reservations by canonical symbol: an open sell holds
        # internal quantity that has left the settled broker balance; an open buy
        # is quantity not yet reflected internally.
        open_sell: dict[str, Decimal] = {}
        open_buy: dict[str, Decimal] = {}
        for o in open_orders:
            sym = db.canonical_symbol(o["symbol"])
            side = (o.get("side") or "").lower()
            q = parse_decimal(o.get("qty", "0"))
            if side == "sell":
                open_sell[sym] = open_sell.get(sym, Decimal("0")) + q
            elif side == "buy":
                open_buy[sym] = open_buy.get(sym, Decimal("0")) + q

        symbols = set(internal) | set(broker) | set(open_sell) | set(open_buy)

        rows: list[dict] = []
        for sym in sorted(symbols):
            internal_qty = Decimal(internal.get(sym, "0"))
            settled = broker.get(sym, Decimal("0"))
            # Effective broker-held quantity attributable to us:
            #   settled + quantity tied up in open sells - quantity from open buys.
            effective = settled + open_sell.get(sym, Decimal("0")) - open_buy.get(sym, Decimal("0"))
            delta = effective - internal_qty

            increment = Decimal(str(increments.get(sym, _DEFAULT_INCREMENT)))
            qty_tol = increment
            price = prices.get(sym)
            min_notional = Decimal(str(min_notionals.get(sym, "0")))
            value_tol = max(_MIN_VALUE_TOLERANCE, min_notional)

            classification = "internal"
            if internal_qty == 0 and effective > 0:
                # Broker holds quantity we have no verified lots for → quarantine.
                classification = "external/manual"
                status = "FROZEN"
            elif delta == 0:
                status = "VERIFIED"
            else:
                abs_delta = delta.copy_abs()
                within_qty = abs_delta <= qty_tol
                within_value = True
                if price is not None:
                    delta_value = abs_delta * parse_decimal(price)
                    within_value = delta_value <= value_tol
                if within_qty and within_value:
                    status = "DUST"
                else:
                    status = "FROZEN"

            snapshot_id = db.insert_reconciliation_snapshot(
                account_id, sym,
                broker_qty=decimal_text(effective),
                internal_qty=decimal_text(internal_qty),
                delta=decimal_text(delta),
                status=status,
            )
            rows.append({
                "snapshot_id": snapshot_id,
                "account_id": account_id,
                "symbol": sym,
                "broker_qty": decimal_text(effective),
                "settled_qty": decimal_text(settled),
                "internal_qty": decimal_text(internal_qty),
                "delta": decimal_text(delta),
                "status": status,
                "classification": classification,
            })
        return rows

    @staticmethod
    def is_frozen(rows: list[dict]) -> bool:
        """True if ANY reconciled row froze — the account must not auto-trade."""
        return any(r["status"] == "FROZEN" for r in rows)
