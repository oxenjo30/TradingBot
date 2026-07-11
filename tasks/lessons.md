# Lessons

## 2026-07-11 - Task 4: route order paths, default must stay shadow

- Mistake risk: routing order paths could silently change LIVE paper-trading behavior.
- Cause: the bot runs live; a default that submits through the new ledger, or that
  mutates lots on acknowledgement, would be a real regression.
- Rule: gate every new order path behind `execution_ledger_mode` (default 'shadow',
  unknown values fail SAFE to shadow). In shadow, only RECORD an observation intent
  and let the legacy path stay authoritative; never submit through the ledger or
  create lots. Only in 'authoritative' mode disable legacy submit and move
  record_open_trade/close_trade_and_record_perf behind confirmed-fill ingestion.
- Rule: take-profit and owner closes sell ONLY the owning strategy's sellable qty
  (db.get_sellable_qty), never the full broker position.

## 2026-07-11 - Task 7: Decimal metrics vs pytest.approx; default end-convention

- Mistake 1: asserted `Decimal_metric == pytest.approx(float)`; pytest.approx does
  `expected - actual` and cannot subtract Decimal from float → TypeError.
  Rule: when a metric returns Decimal, cast with `float(metric)` before comparing
  to pytest.approx, or compare Decimal-to-Decimal exactly.
- Mistake 2: a temporal-integrity test asserted `trades == []` for a buy-only run,
  but the default EndConvention is LIQUIDATE, which closes the open position at the
  final bar and thus produces one trade. Rule: to isolate the entry-fill datum in a
  buy-only scenario, run with EndConvention.CARRY so nothing is force-closed; only
  assert trades==[] when the run genuinely leaves no closed round trip.
- Rule: the backtest accounting identities balance ONLY if gross realized/unrealized
  P&L are computed from the MID (pre-slippage) price and every fee/slippage drag is
  accumulated separately as entry_fees / exit_fees / other_costs. Never subtract
  costs into the gross numbers, and never reconstruct gross from the post-slippage
  fill price — store the gross mid entry on the lot and derive from it.
