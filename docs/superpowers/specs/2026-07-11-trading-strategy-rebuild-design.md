# TradeBot Strategy and Execution Rebuild Design

Date: 2026-07-11
Status: Approved design; implementation not started

## 1. Objective

Rebuild TradeBot's automated execution, accounting, backtesting, and strategy layer so that stock and crypto strategies can be evaluated with trustworthy, reproducible evidence.

The primary objective is positive net expectancy after realistic costs. Win rate is informational and must not be used as the optimization target.

The target allocation of deployed risk capital is:

- 90% stocks
- 10% crypto

For the first validation cycle, total gross exposure is capped at 50% of combined portfolio equity: 45% stocks, 5% crypto, and at least 50% cash. Thus the deployed risky-asset mix remains 90/10 while cash is reported separately.

The combined portfolio has a hard 5% peak-to-trough drawdown ceiling. Exceeding this ceiling in a final historical holdout or paper-trading validation fails the strategy. This is a risk threshold, not a guarantee that future losses cannot exceed 5%.

## 2. Current-State Problems

### 2.1 Position ownership

The current engine passes every strategy the complete account-level broker position map. A strategy can therefore sell positions opened manually or by another strategy. Current performance attribution is contaminated and cannot be used as clean training or selection data.

### 2.2 Premature fill accounting

Order acknowledgement is treated as execution. Pending, partially filled, rejected, or delayed orders can create phantom lots or incorrect realized P&L. Requested quantity and current quotes are sometimes substituted for confirmed execution quantity and price.

### 2.3 Incomplete ledger

The `signals` and `open_trades` records do not form an idempotent execution ledger. They lack authoritative fill identity, complete fees, order lifecycle, and robust reconciliation against broker holdings.

### 2.4 Invalid strategy comparison

Cross-strategy exits, deleted-account history, orphaned lots, and inconsistent fill information make the existing strategy-level P&L unsuitable for parameter tuning.

### 2.5 Backtesting limitations

The current backtester always fetches Alpaca daily data, does not provide a genuine crypto provider, can overspend cash when simultaneous orders occur, omits important execution constraints, and has no walk-forward or untouched holdout protocol. Existing crypto results are not sufficient evidence for Binance strategies.

### 2.6 Unsafe optimization

The current AI tuner optimizes primarily for win rate using contaminated results. It has no out-of-sample gate and can save parameter values that differ from its rationale because of silent clamping.

## 3. Scope

### 3.1 Included

- Strategy-owned execution orders, fills, lots, and realized P&L
- Broker reconciliation and external/manual-position quarantine
- Additive database migration and compatibility reads
- Separate stock and crypto historical-data contracts
- Portfolio-aware, cost-aware backtesting
- Walk-forward testing and a final untouched holdout
- A liquid-US-stock long-only trend/breakout strategy
- A BTC/ETH spot-only daily trend strategy
- Portfolio allocation and drawdown enforcement
- Deterministic automated tests and paper-trading promotion gates
- Dashboard compatibility for existing trading and performance views

### 3.2 Excluded

- Live-capital deployment
- Short selling, options, futures, margin, or leverage
- Intraday stock trading
- Four-hour crypto trading in the first release
- AI parameter tuning
- Sentiment-based sizing
- Grid trading, averaging down, or pyramiding
- Destructive rewriting of historical production data
- Claims or guarantees of future profitability

## 4. Selected Architecture

The existing dashboard, broker accounts, strategy registry, and service structure remain in place. Execution accounting and backtesting are replaced incrementally behind compatible interfaces.

### 4.1 Order lifecycle

1. The strategy creates an order intent.
2. TradeBot persists the intent before contacting the broker.
3. TradeBot submits the order using an idempotent client order ID.
4. The broker response updates acknowledgement state only.
5. TradeBot polls or ingests authoritative order/fill information.
6. Confirmed fills update strategy lots and P&L in one idempotent transaction.
7. Reconciliation compares the internal ledger with broker positions.

Acknowledged states such as `accepted`, `pending`, `new`, and `open` are not fills.

### 4.2 Domain records

Add the following tables without removing current tables:

#### `execution_orders`

- Internal ID
- Account ID and strategy
- Client and broker order IDs
- Symbol, side, order type
- Requested quantity or notional
- Current broker status
- Submission/update timestamps
- Last error
- Unique account/client-order identity
- Unique account/broker-order identity when available

#### `execution_fills`

- Parent execution-order ID
- Stable broker fill/trade ID
- Filled quantity and price
- Fee and fee currency
- Fill timestamp
- Unique order/fill identity for idempotency

#### `position_lots`

- Account, strategy, and symbol ownership
- Opening fill reference
- Original and remaining quantity
- Unit cost including allocated entry fees
- Open and close timestamps
- Provenance status such as `verified` or `legacy_unverified`

#### `lot_matches`

- Closing fill and opening-lot references
- Matched quantity
- Entry and exit price
- Allocated entry/exit costs
- Net realized P&L
- Idempotent closing-fill/lot identity

#### Reconciliation records

Store account/symbol broker quantity, internal quantity, delta, timestamp, and resolution status. A material unexplained delta freezes automated orders for that account until resolved.

Money and quantities must use decimal-safe representations. Floating-point `REAL` values must not be the authoritative ledger representation.

### 4.3 Ownership rules

- Strategies receive only their owned positions for exit decisions.
- A strategy sell is rejected or rounded down if it exceeds that strategy's sellable quantity.
- Lot matching includes account, strategy, and symbol.
- Manual or unattributed broker holdings are classified as `external/manual`.
- Automated strategies cannot sell `external/manual` holdings.
- Take-profit actions operate on individual strategy lots, never the full broker position.
- Historical records without trustworthy fill provenance remain `legacy_unverified` and are excluded from clean validation datasets.

### 4.4 Crash and restart safety

- Persist before submit.
- Use stable client order IDs.
- Make fill ingestion idempotent.
- Reconcile all accounts on startup before enabling new orders.
- Do not mutate owned quantities until confirmed fills are ingested.
- Preserve and surface unmatched fills rather than silently discarding them.

## 5. Broker Contract

Every broker adapter will expose normalized acknowledgement and fill data while preserving current compatibility methods during migration.

Required normalized concepts:

- `OrderAck`: broker/client IDs, requested quantity/notional, status, and submission time
- `Fill`: stable fill ID, order ID, quantity, price, fee, fee currency, and fill time
- Order lookup by broker order ID
- Fill listing by order and reconciliation window

Broker-specific precision, minimum notional, status vocabulary, and pagination must be normalized explicitly. Quotes and requested values are never authoritative substitutes for fills.

## 6. Portfolio Risk Controller

The portfolio controller operates above individual strategies.

### 6.1 Capital allocation

- Deployed risk capital: 90% stocks and 10% crypto
- Initial stock gross exposure: at most 45% of total portfolio equity
- Initial crypto gross exposure: at most 5% of total portfolio equity
- Initial cash: at least 50% of total portfolio equity
- Unused allocation remains cash

The deliberately low initial gross exposure is required to make the 5% drawdown target plausible. Exposure may not be raised merely to improve return during the same validation cycle.

### 6.2 Risk limits

- Hard combined drawdown stop: 5%
- New-entry freeze: 4% drawdown
- Daily portfolio loss limit: 1%
- Weekly portfolio loss limit: 2%
- Combined open risk at initial stops: no more than 1.25% of equity
- Stock risk per new position: 0.25% of total equity
- Crypto risk per new position: 0.10% of total equity
- All sizing rounds downward
- Skip trades when broker minimum size would violate the risk budget

The drawdown baseline is the high-water mark of reconciled combined portfolio equity. Section 19 defines consolidation, cash-flow adjustment, stale-equity handling, and the hard-stop shutdown policy. A hard stop does not assume instantaneous or lossless liquidation.

## 7. Stock Strategy

### 7.1 Universe

Version one uses a fixed, declared liquid universe:

- SPY
- QQQ
- AAPL
- MSFT
- NVDA
- AMZN
- GOOGL
- META

The daily-gainers and most-active scanners are not used. Penny stocks, leveraged/inverse ETFs, OTC securities, and anachronistic historical constituents are excluded.

### 7.2 Regime

New entries are allowed only when:

- SPY daily close is above SMA200; and
- SMA200 is above its value 20 trading sessions earlier.

If SPY closes below SMA200 for two consecutive sessions, existing stock positions generate regime-exit intents for the next session open.

### 7.3 Entry

After a completed daily bar, a symbol qualifies when:

- Close is above the highest adjusted high of the previous 252 trading sessions, excluding the decision bar.
- Close is above SMA100.
- Decision-bar volume is at least 1.2 times the average volume of the previous 20 sessions, excluding the decision bar.
- The symbol has no strategy-owned open position or pending entry.

When more symbols qualify than capacity permits, rank by percentage distance above the prior 252-session high, then by symbol for deterministic tie-breaking. Fill is modeled and submitted at the next eligible session.

### 7.4 Exit

- Initial stop: confirmed entry price minus 2.5 times ATR20 at entry.
- Trailing stop: highest completed closing price since entry minus 3.0 times current ATR20.
- The stop never moves downward.
- Regime failure also exits.
- A completed-bar stop breach produces an exit for the next session open, including adverse opening gaps.
- No universal profit target and no RSI exhaustion exit.

### 7.5 Sizing and constraints

- Quantity is the floor of `risk_budget / initial_stop_distance`.
- Maximum symbol market value is 10% of total equity.
- Maximum five stock positions.
- Maximum stock gross exposure is 45% of total equity for the first validation cycle.
- No pyramiding.
- Orders cannot exceed available cash or modeled liquidity constraints.

## 8. Crypto Strategy

### 8.1 Universe and timeframe

- BTC/USDT spot
- ETH/USDT spot
- Daily UTC exchange-native completed candles
- No leverage, derivatives, staking return, shorts, or additional assets

Daily bars are mandatory for version one. Four-hour behavior must not be implemented or claimed until the historical and live bar contracts support it consistently.

### 8.2 Entry

After a completed daily candle, enter when:

- Close exceeds the highest high of the previous 55 completed daily candles, excluding the decision candle.
- EMA50 is above EMA200.
- No strategy-owned position or pending entry exists.

Fill occurs at the next completed interval's open under the backtest execution model or through the normal live/paper order lifecycle.

### 8.3 Exit

Generate an exit when any condition occurs:

- Close falls below the lowest low of the previous 20 completed daily candles.
- Close remains below EMA200 for two consecutive completed daily candles.
- The ATR trailing stop is breached.

Initial stop is 3.0 ATR20 below confirmed entry. The trailing stop is the highest completed close since entry minus 3.5 ATR20 and never loosens.

### 8.4 Sizing and constraints

- Risk per new position: 0.10% of total portfolio equity.
- BTC maximum allocation: 3%.
- ETH maximum allocation: 2%.
- Combined crypto market value: at most 5%.
- Maximum two positions.
- Quantity rounds down to exchange precision.
- Skip when minimum notional exceeds the risk or allocation budget.
- No pyramiding or averaging down.

## 9. Historical Data Contract

The backtester receives bars through explicit historical providers rather than global thread-local fallback.

Each request declares:

- Asset class
- Provider
- Symbol
- Start and end timestamps
- Timeframe
- Timezone/calendar
- Adjustment policy
- Point-in-time/as-of policy where supported

Each response includes normalized, sorted bars and provenance metadata. Validation rejects duplicate timestamps, non-finite values, inconsistent OHLC, unsupported coverage, and undeclared gaps.

Stock and crypto providers cannot silently substitute for each other. Backtest runs persist provider, asset class, timeframe, adjustment policy, retrieval time, and a deterministic data fingerprint.

## 10. Backtesting Engine

### 10.1 Temporal integrity

- Strategies see only bars completed at the decision timestamp.
- Orders fill strictly after the signal timestamp.
- Current-bar values are excluded from trailing-window thresholds where specified.
- Future sentinel data must not alter earlier signals.
- Exceptions and missing required data fail the run; they are not converted into zero-signal success.

### 10.2 Execution model

- Next-session/next-bar open fills
- Explicit adverse slippage
- Stock sell regulatory costs where available
- Crypto maker/taker fee assumption, quantity precision, and minimum notional
- Adverse gap execution
- Cash reservation for simultaneous orders
- Deterministic order priority
- Volume participation constraints where data supports them
- Explicit partial-fill/rejection behavior
- Explicit end-of-test liquidation or carry convention, reported in results

Baseline cost assumptions:

- Stocks: 10 basis points one way slippage; stress at 20 basis points
- Crypto: 10 basis points fee plus 5 basis points slippage each way; stress at 20 plus 20 basis points

Actual broker/account fee schedules replace assumptions when authoritative data is available. Temporary zero-fee promotions are not assumed.

### 10.3 Portfolio accounting

- Cash cannot become negative unless an explicitly modeled margin account is introduced; margin is excluded from this design.
- Simultaneous orders reserve cash before fills.
- Portfolio, asset-class, symbol, and open-risk limits are evaluated against the proposed order.
- The authoritative unrounded account identity is `ending cash + ending market value = ending equity`.
- The performance attribution identity is `initial equity + gross realized P&L + gross unrealized P&L + dividend/investment income + external cash flows - entry fees - exit fees - other execution costs = ending equity`.
- Gross realized/unrealized P&L exclude all fees and execution costs in this identity. Net lot P&L is a derived reporting value and must never be substituted into the gross identity or have costs subtracted twice.

### 10.4 Metrics

Report at minimum:

- Net return and CAGR
- Maximum drawdown
- Annualized volatility
- Sharpe, Sortino, and Calmar ratios
- Benchmark return and excess return
- Turnover and total execution costs
- Average and distribution of holding periods
- Gross/net exposure and cash utilization
- Win rate, payoff ratio, and expectancy
- Worst trade, worst gap, and tail-loss measures
- Results by year, walk-forward fold, strategy, and symbol

Annualization derives from timeframe and calendar: stock sessions and 24/7 crypto are not treated identically. Internal return rates use one documented scale consistently.

## 11. Validation Protocol

### 11.1 Data periods

- Stocks: target at least ten reliable years of adjusted daily data, including stressed regimes such as 2020 and 2022.
- Crypto: use the earliest reliable liquid BTC/ETH daily history available from the selected provider.
- If required coverage or corporate-action quality is unavailable, the limitation is reported and the affected result cannot be labeled proven.

### 11.2 Walk-forward process

- Use chronological anchored walk-forward folds.
- Tune only on data preceding each validation fold.
- Include a purge at least as long as the strategy's maximum lookback.
- Persist every attempted parameter configuration and selection rule.
- Combine non-overlapping out-of-sample folds into one out-of-sample equity curve.
- Evaluate the final untouched holdout once after design and parameter selection are frozen.

Parameter exploration uses coarse, predeclared neighboring values. It must not optimize many indicators simultaneously or select a single lucky result.

### 11.3 Benchmarks

- Stock strategy: SPY buy-and-hold over the identical dates and data policy.
- Crypto strategy: static 60% BTC / 40% ETH buy-and-hold over identical dates.
- Combined policy benchmark: 45% SPY, 3% BTC, 2% ETH, and 50% cash, rebalanced monthly with modeled costs.
- Combined exposure-matched benchmark: the same daily stock/crypto gross exposure as the candidate, invested in SPY and a drifting 60/40 BTC/ETH sleeve; this benchmark is used for value-added claims.
- Existing saved strategy runs remain production baselines but are not called market benchmarks.

## 12. Hard Backtest Acceptance Criteria

The candidate passes historical research only when all applicable criteria pass:

1. Positive net out-of-sample return after baseline costs.
2. Positive net out-of-sample return under stressed costs.
3. Combined maximum drawdown at or below 5% over aggregate out-of-sample results.
4. Combined maximum drawdown at or below 5% in the final untouched holdout.
5. Positive net result in at least 60% of walk-forward folds.
6. At least 100 closed stock trades across the available history.
7. At least 20 crypto round trips; fewer is `inconclusive`, not a pass.
8. No single stock or calendar year supplies more than 35% of total net profit.
9. Neighboring parameter settings remain profitable and retain at least 70% of the selected setting's out-of-sample Calmar ratio; when the selected Calmar is non-positive, the candidate fails.
10. The selected strategy has positive net expectancy.
11. No temporal leakage, data-integrity, strategy-ownership, negative-cash, or ledger-reconciliation failure.
12. Every attempted configuration and failed criterion remains visible in the research output.

Benchmark underperformance does not automatically prove the strategy unsafe, but it must be reported prominently. The strategy cannot be described as adding value unless it improves the approved benchmark on an explicitly selected risk-adjusted measure.

## 13. Paper-Trading Gate

Historical acceptance permits paper trading only.

Paper validation requires:

- At least 90 calendar days
- At least 20 closed round trips across the enabled portfolio; otherwise extend the period
- Combined drawdown below 5%
- Positive net expectancy after observed costs
- Execution costs within the stressed backtest band
- Zero duplicate-order, ownership, fill-idempotency, reconciliation, restart-state, or risk-limit failures
- Daily reconciliation evidence

Failure leaves the strategy disabled. Live deployment requires a separate design, risk review, explicit user approval, and a capital ramp plan.

## 14. Migration and Rollout

### Phase A: Safety and compatibility

- Add deterministic regression tests that reproduce cross-strategy selling and premature-fill accounting.
- Add execution-ledger tables and normalized domain records.
- Keep current dashboards functioning through compatibility readers.
- Implement fill ingestion and reconciliation without enabling new strategies.

### Phase B: Ownership enforcement

- Expose strategy-owned positions.
- Reject cross-strategy sales.
- Quarantine external/manual and legacy-unverified inventory.
- Reconcile all configured paper accounts.

### Phase C: Backtesting foundation

- Add provider contracts, validated requests, provenance, and deterministic execution.
- Add portfolio limits, cost models, metrics, walk-forward folds, and benchmarks.
- Verify stock and crypto fixtures independently.

### Phase D: Strategies

- Add the stock strategy through test-driven development.
- Add the crypto strategy through test-driven development.
- Add portfolio allocation and drawdown controls.

### Phase E: Research report

- Run declared walk-forward experiments.
- Freeze parameters before final holdout.
- Produce full pass/fail evidence, including failed variants.
- Do not enable a strategy that misses any hard criterion.

### Phase F: Paper deployment checkpoint

- Back up the production database and configuration.
- Disable AI tuning, sentiment sizing, Classic Patterns, crypto grid, crypto RSI bounce, and other legacy automatic assignments.
- Deploy only after tests, migration dry run, rollback verification, and explicit user approval.
- Enable approved candidates in paper mode only.

## 15. Testing Requirements

Implementation follows test-driven development: each behavior begins with a failing test that is observed failing for the expected reason.

Required automated coverage includes:

- Strategy ownership and cross-strategy sell rejection
- Pending, rejected, partial, duplicate, and delayed fills
- Fill idempotency and crash-window reconciliation
- Manual/external-position quarantine
- Fee allocation and FIFO partial-lot matching
- Multi-account isolation
- Stock and crypto provider separation
- Future-data leakage sentinel
- Weekday stock and 24/7 crypto calendars
- Timezones and daylight-saving transitions
- Missing bars, gaps, splits, dividends, and declared delisting behavior
- Simultaneous orders with insufficient cash
- Precision and minimum-notional rejection
- Drawdown freeze and hard stop
- Restart persistence of entry, ATR, peak, and trailing stop
- Deterministic repeatability and data fingerprints
- Ledger/equity reconciliation
- Walk-forward train/validation/holdout isolation
- Benchmark rate-scale consistency
- Existing dashboard/API compatibility

No network call is permitted in deterministic unit tests. Broker and historical-provider integrations use recorded, sanitized fixtures plus separately marked integration tests.

## 16. Operational Controls

- Existing automated strategies remain unchanged until the production migration checkpoint.
- No destructive database migration is permitted.
- A backup and tested rollback are required before VPS deployment.
- Reconciliation failures, stale data, unsupported status, or malformed fills fail closed.
- Logs and dashboards must distinguish intent, acknowledgement, partial fill, full fill, cancellation, rejection, reconciliation exception, and risk block.
- Strategy health uses net expectancy, drawdown, costs, and sample sufficiency rather than win rate alone.

## 17. Evidence and Limitations

The selected trend and breakout families are research candidates supported by broad momentum evidence, not proof that these exact rules will profit. Repository comments that state historical CAGR are not accepted as evidence.

Passing historical tests demonstrates that the implementation behaved consistently on the tested data under declared assumptions. It cannot prove future profitability, prevent market gaps beyond modeled limits, or guarantee a maximum realized loss. The design prioritizes rejecting unreliable strategies and limiting exposure before any live-capital discussion.

## 18. Implementation Approval Boundary

This document approves the design only. Implementation planning begins only after the user reviews this written specification. Code changes begin only after the implementation plan is written and approved under the repository workflow.

## 19. Review Resolutions and Operational Contracts

This section resolves the independent execution, quantitative, and safety review findings. Where an earlier section is less specific, this section controls.

### 19.1 Consolidated portfolio equity

- Version one accepts explicitly configured paper accounts only; live accounts fail validation.
- Participating account IDs are audited configuration. Adding or removing one requires an owner-authorized high-water-mark reset event.
- Base currency is USD. USD is valued at one. USDT uses a fresh USDT/USD reference; a 1.0 fallback is allowed only within a verified 50-basis-point deviation, otherwise new entries freeze.
- Account snapshots must be at most 120 seconds apart and none older than 180 seconds. Otherwise combined equity is stale, entries freeze, and the high-water mark is not updated.
- Combined equity is the sum of reconciled participating-account equity converted to USD at the snapshot timestamp.
- Deposits, withdrawals, and transfers adjust the high-water mark and daily/weekly baselines by the same signed external flow, preventing cash movement from being treated as P&L.
- Persist high-water mark, daily and weekly baselines, snapshot IDs, conversion rates, and resets. Only an authenticated owner may reset them with an audit reason.
- Day boundaries are 00:00 UTC; weeks begin Monday 00:00 UTC. Use unrounded decimals and compare drawdown to four decimal places.
- Drawdown greater than or equal to 4.0000% freezes entries. Drawdown greater than or equal to 5.0000% invokes the hard stop.

### 19.2 Hard-stop policy

1. Persist `HARD_STOP_TRIGGERED`; activate global and participating-account entry kill switches.
2. Cancel nonterminal strategy-owned buys, never external/manual orders.
3. Reconcile cancellations for up to 60 seconds and ingest fills that arrive meanwhile.
4. Recompute owned sellable quantities.
5. Submit one idempotent exit per account, strategy, and symbol, excluding quarantined quantity.
6. Crypto exits use precision-valid market orders; below-minimum dust is quarantined and reported.
7. Closed-market stock exits queue for the next regular session and are revalidated before submission; no extended-hours assumption is made.
8. Partial fills reconcile normally. Rejected/expired exits retry at most three times, linked to the original event and never exceeding remaining quantity.
9. Unresolved exits, stale state, unknown statuses, or restart keep the account frozen and alert the owner. Startup resumes the same shutdown before strategy evaluation.
10. No automatic reset is permitted. Owner clearance requires fresh reconciliation and an audit reason.

### 19.3 Order state and ambiguous submission

Canonical states are `INTENT_PERSISTED`, `SUBMITTING`, `ACKNOWLEDGED`, `PARTIALLY_FILLED`, `FILLED`, `CANCEL_PENDING`, `CANCELED`, `REJECTED`, `EXPIRED`, and `UNKNOWN`. Terminal states are filled, canceled, rejected, and expired; cancel-after-partial preserves fills and cancels only the remainder.

- Commit intent and client order ID before submission, then persist `SUBMITTING` immediately before the network call.
- A timeout/crash in `SUBMITTING` must recover through account plus client-order-ID lookup before any retry.
- Every automated adapter implements `get_order_by_client_id`; inability to provide authoritative lookup makes automation unsupported.
- One match binds the broker ID. Multiple matches freeze the account. No match after three lookups over 60 seconds becomes `UNKNOWN`, freezes the account, and forbids automatic resubmission.
- The guarantee is at-most-once economic submission, not at-most-once HTTP requests.

### 19.4 Broker capability gate

Before automated enablement, each adapter documents and tests authoritative lookup by broker/client ID, fill source and identity, pagination/overlap, status transitions, partial/cancel-after-partial behavior, fee/correction source, symbol normalization, precision, minimum notional, and retention limits.

When a broker exposes only monotonic cumulative filled quantity and average price, deterministic synthetic fill deltas use `(account_id, broker_order_id, cumulative_filled_qty, snapshot_version)` and explicit fee provenance. Regressing/conflicting snapshots freeze the account. A broker with neither executions nor authoritative monotonic snapshots is unsupported.

### 19.5 Ledger invariants

- Internal integer primary keys; verified executions restrict deletion of referenced accounts.
- Authoritative money/quantity uses canonical decimal text: no exponent, at most 18 decimal places, `Decimal`, ROUND_DOWN for order quantities, and ROUND_HALF_EVEN only for reporting.
- UTC ISO-8601 timestamps include microseconds.
- Orders require account, owner/source, client ID, symbol, side, state, timestamps, valid enums, and exactly one positive requested quantity/notional.
- Fill identity is unique per account/broker. Fills are immutable; late fees append adjustment rows.
- Fill insert, lot creation/matching, fee allocation, P&L, and cumulative order update run in one `BEGIN IMMEDIATE` transaction. Duplicate identity reloads and verifies equality; conflicts freeze the account.
- FIFO attribution orders by opening fill time then lot ID. Entry fees enter unit cost once; audit allocation cannot double-subtract them.
- Sellable quantity is remaining owned lots minus reserved nonterminal exits. Oversized exits round down deterministically; zero is rejected.

### 19.6 Bootstrap and reconciliation

- Quiesce all automation and reconcile nonterminal orders before classification.
- Import as `legacy_verified` only records confirmed by an authoritative terminal broker order with trustworthy account, symbol, quantity, and price.
- Everything else is `legacy_unverified`; uncovered broker quantity is `external/manual`. Unknown always quarantines and ownership is never inferred by age.
- Owner adoption requires evidence, exact account/symbol/quantity/owner, and audit reason; adopted quantity cannot exceed the unexplained reconciled amount.
- Compare settled broker quantity with verified lots and fills; separately report open-order reservations. Use canonical instrument IDs.
- Quantity tolerance is one broker increment; value tolerance is the greater of USD 1 or one minimum notional. Within tolerance is `DUST`; above tolerance freezes.
- Snapshots have stable IDs. Only an authenticated owner resolves, freezes, or unfreezes, with audit logging.

### 19.7 Complete order-path coverage

Automated, manual, webhook, take-profit, close-position, and close-all paths all persist execution intents and ingest authoritative fills. Manual/webhook owners are `manual` and `webhook`. Explicit user closes affect only selected owners unless the authenticated request names multiple owners. Compatibility APIs may project the ledger but cannot bypass it.

### 19.8 Migration authority and rollback

- Migrations are additive, transactional, versioned, rerunnable, and dry-run against a backup copy.
- Phase A is shadow-only: the legacy engine stays authoritative; the ledger observes but cannot submit or mutate legacy positions.
- Cutover disables automation, reconciles pending orders, backs up DB/configuration, classifies inventory, then atomically enables the new execution path. The old submit path fails closed after the switch; there is no dual submission.
- Before the switch, rollback uses the old binary and untouched legacy tables. After new fills, rollback stops automation, archives post-cutover paper records, and restores the pre-cutover DB/configuration backup.
- Golden API/dashboard response fixtures must pass before cutover.

### 19.9 Pre-trade risk sizing

- Use the adverse side of a quote no older than 30 seconds: ask for buys, bid for sells. Estimated entry adds configured adverse slippage.
- Compute the initial stop from the completed decision bar and estimated entry.
- Quantity is the minimum risk-, sleeve-, symbol-, cash-, and liquidity-capped quantity, rounded down.
- Risk quantity is `(risk_budget - estimated round-trip costs) / stop_distance`; a non-positive numerator skips.
- Recompute after actual VWAP/costs. If modeled open risk exceeds budget by over 10%, create an idempotent reduction. Gap risk can exceed budget and remains unguaranteed.

### 19.10 Reproducible validation

- Stocks require ten complete years. The final holdout is the latest 24 complete months. Pre-holdout anchored folds start with five training years and add one-year validation windows, advancing yearly.
- Crypto requires six complete years. The final holdout is the latest 12 complete months. Pre-holdout anchored folds start with three training years and add six-month validation windows.
- Purge by the maximum lookback; warm indicators before scoring. Refit only from preceding training data.
- Contiguous OOS folds carry cash/positions; gaps liquidate with costs and are disclosed. The final holdout starts from cash using parameters frozen on all pre-holdout data.
- Predeclared grids: stock breakout `[126,252]`, volume `[1.0,1.2,1.4]`, trail ATR `[2.5,3.0,3.5]`; crypto breakout `[40,55,70]`, exit low `[15,20,30]`, trail ATR `[3.0,3.5,4.0]`. Other parameters stay fixed.
- Select training Calmar subject to training drawdown at or below 5%, then lower turnover, then lexicographic parameters. Persist every attempt.
- Report moving-block-bootstrap 95% intervals for daily net return and expectancy using 20-session stock and 14-day crypto blocks. Wholly negative fails; spanning zero is statistically inconclusive.
- Paper promotion requires both 90 days and 20 closed round trips and extends until both pass.
- Profit concentration divides by total positive P&L contribution before losses; loss concentration is reported separately.

### 19.11 Data, benchmarks, and compatibility

- The current fixed stock list provides conditional evidence only, not broad-market evidence.
- One point-in-time corporate-action policy must consistently cover OHLC, volume, shares, ATR, fills, lots, dividends, symbol changes, and delistings. Future-known back-adjustment at decision time is prohibited unless labeled retrospective and kept on one transformed scale.
- Crypto benchmark begins when BTC and ETH are both reliable and rebalances monthly to 60/40 inside the 5% sleeve with costs. Earlier BTC-only history is separate.
- Tail metrics are worst daily return, 95% historical expected shortfall, and worst next-open gap loss.
- Compatibility inventory fixes every endpoint, field/type/decimal format, pagination rule, status mapping, and historical meaning before golden fixtures are recorded.

### 19.12 Scheduling and outages

- Run only after a provider marks a bar final. Stocks target next regular session market-on-open if supported; fallback submits after open and records latency/slippage. Crypto submits after the UTC boundary and never claims the exact opening print.
- A delay over five minutes from the intended window cancels/skips the order.
- Historical data older than one expected interval plus five minutes and broker data older than 180 seconds are stale.
- Rate limits use bounded exponential backoff with jitter for three attempts. Partial pagination invalidates the snapshot.
- Circuit breakers are account scoped. Recovery requires a complete fresh snapshot and successful reconciliation; transitions alert and audit.

### 19.13 Final review resolutions

#### Risk sizing equation

For each broker quantity increment, choose the largest rounded-down quantity `q` satisfying all constraints:

`q * (estimated_entry - initial_stop) + entry_cost(q) + estimated_exit_cost(q) <= risk_budget`

and the sleeve, symbol, cash, liquidity, and combined-open-risk caps. Costs include spread/slippage, broker fees, and sell-side regulatory costs. Solve monotonically by bounded binary search over broker increments; fee-tier discontinuities are evaluated by the adapter cost function. Stop risk is measured from estimated adverse entry to the stop. Sell proceeds do not reduce pre-trade risk; estimated exit costs increase it.

Fail closed before sizing when `estimated_entry - initial_stop <= 0`; the entry is skipped and the stop is not silently recomputed.

#### Fold boundaries

- Training trades are liquidated with costs before a validation boundary; no training position enters validation.
- There is a five-session stock/two-day crypto unscored embargo between parameter selection and validation. The maximum-lookback history before validation is available only as indicator warm-up and produces no orders or scored returns.
- Every OOS validation fold begins from cash. Parameters remain fixed for the fold. Fold returns are chained geometrically in timestamp order into the aggregate OOS curve; drawdown is calculated on that chained curve, and fold resets are disclosed.
- Any open validation position is liquidated with costs at fold end. This removes entry-version ambiguity when parameters change.

#### Corporate actions and total return

- Stock decisions and executions use point-in-time split-adjusted OHLCV supplied as of the bar timestamp: pre-split prices divide and pre-split volumes multiply only from the split effective date onward in the provider's event-aware view.
- Strategy shares, entry cost, peaks, ATR state, and stops are transformed by the same split ratio on the effective date without creating P&L.
- Cash dividends are not back-adjusted into prices. They are credited to cash on the payable date when the position was entitled on the ex-date. Benchmarks use identical dividend cash treatment.
- Symbol changes preserve the instrument ID and lot ownership. Mergers/spinoffs require explicit provider events; unsupported events freeze that instrument and make the affected validation segment ineligible.
- A delisting uses the authoritative delisting cash consideration. If none exists, the position is valued at the last executable price through the final tradable session and then at zero, with the limitation reported.
- Providers that cannot supply these point-in-time bars and events cannot produce a passing stock research result.

#### Cash-flow matching

Internal transfers carry a stable transfer ID and paired source/destination legs. They net to zero at portfolio level only after both legs match amount/currency within tolerance. An unmatched leg freezes high-water-mark advancement and new entries until paired or owner-classified as an external flow.

#### Statistical gate

An inconclusive confidence interval cannot pass. For the aggregate OOS curve, final holdout, and each enabled sleeve, the lower bound of the moving-block-bootstrap 95% interval for daily net return must be greater than zero. Each enabled strategy's closed-trade expectancy interval must also have a lower bound greater than zero. Otherwise that sleeve remains disabled. Results are labeled exploratory because the predeclared grid still constitutes multiple testing; no broader claim is allowed.

#### Benchmark mechanics

- Policy benchmark trades at the next eligible open after a month-end signal, uses the same costs and corporate-action cash treatment, and holds cash at zero yield for conservative simplicity.
- Exposure-matched benchmark uses the candidate's prior completed-bar sleeve exposure, applies it to SPY and the drifting BTC/ETH 60/40 sleeve at the next eligible open, and never reads same-bar realized exposure. It pays identical modeled costs.
- The crypto policy benchmark rebalances monthly; between rebalances weights drift. Before common BTC/ETH history it is reported separately and not joined.
- The fixed current stock list is explicitly conditional, overlap-biased research. SPY/QQQ and constituent overlap are reported. Results must not be generalized to broad liquid-US-stock selection.

#### Paper sample by sleeve

Each enabled stock and crypto strategy independently requires 90 days, at least 20 closed round trips, observed restart/reconciliation evidence, and a positive expectancy confidence interval. A sleeve that lacks its own sample is inconclusive and stays disabled even when the combined portfolio passes.

#### Rollback and retention

- Post-cutover rollback is forward recovery, not blind database restoration. Stop automation, cancel/reconcile all orders, archive the new ledger, restore the compatible binary/schema, import every post-backup broker order/fill and classify current inventory, then keep all submission fail-closed until authoritative reconciliation passes. If complete reconstruction is impossible, remain frozen for owner-supervised manual recovery.
- Persist a per-account fill ingestion watermark and overlap cursor. Automated support requires authoritative history covering at least seven days, while TradeBot polls at least every 60 seconds and refetches a 24-hour overlap on every cycle/startup. If downtime or the watermark predates available retention, freeze and require broker-statement/manual recovery.

#### Risk monitor and loss limits

- Sample every participating account at least every 60 seconds. Consolidate one atomic snapshot only when all component snapshots meet Section 19.1 freshness. Trigger evaluation completes within 15 seconds of a valid snapshot.
- Daily and weekly loss use combined reconciled equity, including realized and unrealized P&L and costs, relative to cash-flow-adjusted baselines. At `<= -1.0000%` daily or `<= -2.0000%` weekly, freeze new entries but continue protective exits. Only an authenticated owner may clear after the next boundary and fresh reconciliation; the 5% hard stop remains independently controlling.
- One stale participating account freezes all portfolio entries and high-water-mark updates. Healthy accounts may continue idempotent protective/risk-reduction exits; no healthy account may open new risk until combined state recovers.
- The five-minute scheduling cancellation applies to entries only. Hard-stop, reconciliation, and risk-reduction exits are durable until terminal resolution or owner intervention.

#### Additional cutover tests

Deployment is blocked unless deterministic tests cover atomic global/account kill-switch ordering; interruption/restart after every shutdown step; retry exhaustion and owner clearance; stale multi-account consolidation; cash-flow-adjusted daily/weekly resets; internal-transfer pairing; pre/post-cutover rollback with broker-side fills; retention-gap freeze; and fail-closed old/new authority switching.
