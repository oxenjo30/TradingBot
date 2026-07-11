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

## 2026-07-11 - Task 8: pure signal models, decision-bar exclusion, SMA-slope fixtures

- Rule: "excluding the decision bar/candle" means the trailing-window thresholds
  (prior-252 high, prior-20 avg volume, prior-55 high, prior-20 low) compute over
  bars[:-1] and compare against bars[-1]. The decision bar is the last completed
  bar in the oldest-first list. Never let the current bar contaminate its own
  breakout/volume/low window (look-ahead guard).
- Rule: entries use STRICT inequality (close > prior-window high). A close equal to
  the prior high is NOT a breakout; test both the equal (no-entry) and just-above
  (entry) control cases.
- Mistake: a "flat SMA200 slope" regime fixture nudged only the final close up, but
  that single high bar entered the recent-200 window and lifted SMA200(now) above
  SMA200(20-ago), so the slope read as rising. Cause: SMA200(now)=closes[-200:] and
  SMA200(offset20)=closes[-220:-20] overlap on the middle; a bump in the overlap
  affects both, a bump only in the now-tail affects only now. Rule: to force an
  EQUAL SMA slope, place one identical bump in the now-only region and one in the
  offset-only region so each 200-window contains exactly one bump.
- Mistake: an "ATR trailing-stop breach" exit test crashed price so hard that the
  prior-20-low exit fired first (exit conditions are OR'd, first match wins) and the
  reason string didn't mention "stop". Rule: to isolate ONE exit condition, build a
  fixture where the others are provably quiet (close above prior-20 low, EMA200
  unavailable or above close) so only the intended rule triggers.
- Rule: research-candidate strategies register in REGISTRY but set auto_trade=False
  and hidden=True. Startup seeds registry strategies into the `strategies` table with
  enabled=False and never auto-populates `strategy_accounts`, so "registered but
  disabled/unassigned by default" needs no extra guard beyond those class flags.
