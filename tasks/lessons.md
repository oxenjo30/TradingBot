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
