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

## 2026-07-11 - Task 9: fold packing, embargo-as-warmup, freeze pass is an attempt

- Insight: with anchored expanding folds, the embargo does NOT consume extra
  calendar BETWEEN training and validation — it is the first `embargo_periods`
  UNSCORED bars at the START of each validation window (and max-lookback warm-up is
  drawn from the tail preceding validation). Modeling it as a separate gap made the
  reduced fixtures unable to fit two folds. Rule: validation window = [train_end,
  train_end + val_len); the first embargo bars are unscored; scored region begins
  after. This is what §19.13 "Fold boundaries" means by an unscored embargo.
- Mistake: reduced test geometry with min_years=3 + 1yr holdout left only 2
  pre-holdout years, yielding just ONE fold, so the "anchored + advance" assertions
  passed trivially (single-element sets are trivially sorted/unique). Rule: to truly
  exercise multi-fold advancement, size the reduced fixture so pre-holdout spans
  >= train_years + 2 windows (used min_years=4 -> 3 pre-holdout years -> 2 folds)
  and assert the EXACT per-fold train.end indices and non-overlap.
- Mistake: a persistence count asserted grid_n * n_folds training attempts, but the
  pre-holdout FREEZE selection is itself a full grid pass over the whole pre-holdout
  window and MUST be persisted too (§12.12 every attempt visible). Rule: training
  attempts = grid_n * (n_folds + 1); validation = n_folds; holdout = exactly 1.
- Rule: the statistical gate is three-valued. lower>0 PASS; upper<0 FAIL; spanning
  zero (incl. lower==0) is INCONCLUSIVE and is NEVER a pass. C7 (<20 crypto round
  trips) is likewise INCONCLUSIVE, not a pass. evaluate_all_criteria treats any
  non-PASS verdict as failing overall.
- Rule: profit concentration divides each group's positive P&L by TOTAL POSITIVE
  P&L across all trades (losses excluded from both numerator and denominator);
  loss concentration is a SEPARATE ratio over absolute losses. Don't net them.
- Rule: the exposure-matched benchmark must be strictly causal — day-t return uses
  day t-1's recorded exposure; it must never read the same-bar exposure key. Proved
  with a dict subclass that records every key lookup and asserting the last bar's
  own date is never consulted.
- Rule (Task 9 boundary): research/db/main changes are ADDITIVE evidence infra only.
  research_runs/research_attempts persist PASS/FAIL evidence; the API endpoints are
  READ-ONLY (GET). No strategy is enabled and no live state mutated — enabling is a
  separate Task 12 gated cutover.

## 2026-07-11 - Task 11: honest INCONCLUSIVE is the win; force it in code

- Insight: in this environment BOTH sleeves are INCONCLUSIVE and that is the CORRECT
  deliverable. Alpaca creds decrypt to empty (len 0) → no stock data; Binance creds
  raise "crypto not initialised — DB_SECRET_KEY missing or invalid" → no crypto data
  (the documented DB_SECRET_KEY hazard: key-mismatch reads creds as invalid, NOT an
  API outage). Never manufacture a green run to hide missing data.
- Rule: the stock sleeve is bounded to INCONCLUSIVE even WITH creds, because the
  network stock provider passes NO corporate_actions so bars are UNADJUSTED, and the
  §7 universe has in-window splits (AAPL 4:1 2020, NVDA 4:1 2021 + 10:1 2024, AMZN
  20:1 2022, GOOGL 20:1 2022). §19.13: a provider that can't supply point-in-time
  split/dividend bars "cannot produce a passing stock research result."
- Rule: honesty-over-optics must be ENFORCED IN CODE, not just prose. A synthetic /
  data-limited sleeve sets SleeveData.forced_inconclusive=True and the runner
  OVERRIDES the raw statistical gate — even a positive bootstrap lower bound reports
  INCONCLUSIVE. Locked by test_forced_inconclusive_overrides_positive_interval.
- Mistake: first synthetic fixture produced 0 trades (smooth low-drift sine), so the
  "infrastructure demo" proved nothing. Cause 1: breakout needs close > prior-window
  HIGH, but hi = close*1.012 inflated the high so a rising close could never exceed
  it — nothing ever fired. Cause 2: drift too small for a 55/252-day breakout. Rule:
  to make a trend strategy actually trade on synthetic bars, keep the intraday high
  only marginally above close (e.g. *1.0008) and give a decisive drift + long cycle;
  verify closed-trade count > 0 before trusting the demo.
- Rule: a research/evidence script must be READ-ONLY on live state: persist=None,
  open trading.db only mode=ro, never set_execution_ledger_mode / enable a strategy /
  submit an order / cutover. Catch a missing-credential error and record INCONCLUSIVE
  instead of crashing. Verify post-run: mode still shadow, strategies still disabled,
  trading.db unmodified in git.
- Rule (security): decrypted API key/secret must NEVER be interpolated into any
  string, log, or exception — pass them only as positional args to the client. As
  defence-in-depth against a third-party exception echoing request material, redact
  any >=16-char alphanumeric run from any recorded failure reason (_safe_error).
