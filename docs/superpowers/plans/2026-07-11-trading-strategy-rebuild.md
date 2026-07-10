# TradeBot Strategy Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace TradeBot's acknowledgement-based, account-wide strategy accounting with strategy-owned fill accounting; add reproducible stock/crypto portfolio backtesting; implement the approved 45% stock / 5% crypto / 50% cash strategy; validate it; and deploy it to the VPS in paper mode.

**Architecture:** Add an additive decimal-safe execution ledger and a single execution service used by all order paths. Build a deterministic portfolio backtester with explicit historical providers, then add two strategy-pure signal models and a consolidated risk controller. Existing APIs remain compatible through projection functions until the new ledger becomes authoritative behind a feature flag.

**Tech Stack:** Python 3.13, FastAPI, SQLite, APScheduler, Alpaca SDK, ccxt/Binance, Tradier HTTP API, pytest.

---

## Phase 0: Allowed APIs and repository patterns

Use only these existing interfaces until a task explicitly extends them:

- Strategy signal contract: `server/strategies/base.py::Signal`, `Strategy.evaluate`.
- Broker construction: `server/broker_factory.py::get_account_client`.
- Existing normalized order reads: `AccountClient.get_orders`, `BinanceAccountClient.get_orders`, `TradierAccountClient.get_orders`.
- Existing SQLite connection/transaction pattern: `server/db.py::get_conn`, `init_db`.
- Existing deterministic bar fixtures: `tests/test_backtest_engine.py::_make_bars`.
- Existing API test isolation: `tests/conftest.py` and `tests/test_api_backtest.py`.

Anti-pattern guards:

- Never treat `accepted`, `pending`, `new`, or `open` as fills.
- Never infer fill quantity/price from a quote.
- Never allow a strategy to sell account-level quantity.
- Never use SQLite `REAL` as authoritative ledger money/quantity.
- Never silently fall back from a crypto provider to Alpaca.
- Never optimize on the final holdout.
- Never deploy to live accounts.

## Task 1: Decimal execution schema and order state model

**Files:**
- Create: `server/execution_models.py`
- Modify: `server/db.py`
- Create: `tests/test_execution_ledger.py`

- [ ] **Step 1: Write failing schema/model tests**

Create tests proving canonical decimal normalization rejects exponent notation, states distinguish terminal/nonterminal orders, schema initialization is rerunnable, and duplicate fill identity is idempotent.

```python
def test_decimal_text_rejects_exponent():
    with pytest.raises(ValueError):
        decimal_text("1e-8")

def test_execution_schema_is_rerunnable(tmp_db):
    db.init_db()
    db.init_db()
    names = table_names()
    assert {"execution_orders", "execution_fills", "position_lots", "lot_matches"} <= names
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_execution_ledger.py -q`
Expected: import/schema failures because the execution model does not exist.

- [ ] **Step 3: Add domain types**

Implement `OrderState`, `OrderAck`, `Fill`, `decimal_text`, and `parse_decimal` in `server/execution_models.py`. Use `Decimal`, forbid exponent input, normalize negative zero, allow at most 18 fractional digits, and expose `OrderState.is_terminal`.

- [ ] **Step 4: Add additive tables**

Add `execution_orders`, `execution_fills`, `fee_adjustments`, `position_lots`, `lot_matches`, `reconciliation_snapshots`, and `portfolio_risk_state` in `db.init_db()`. Include unique `(account_id, client_order_id)`, unique nullable `(account_id, broker_order_id)`, unique fill identity, canonical-text checks, UTC timestamps, and indexes for account/state and strategy/account/symbol.

- [ ] **Step 5: Implement persistence primitives**

Add `create_order_intent`, `mark_order_submitting`, `bind_order_ack`, `get_execution_order`, `get_order_by_client_id`, and `insert_fill_and_apply_fifo`. The fill transaction uses `BEGIN IMMEDIATE`; duplicate-equal fills return the existing ID, duplicate-conflicting fills raise `LedgerConflict`.

- [ ] **Step 6: Run GREEN and regression subset**

Run: `pytest tests/test_execution_ledger.py tests/test_db_broker.py tests/test_db_backtest.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

Commit only Task 1 files with hooks disabled to prevent unrelated version bumps.

## Task 2: Strategy-owned lots, reservations, and reconciliation

**Files:**
- Create: `server/reconciliation.py`
- Modify: `server/db.py`
- Modify: `server/engine.py`
- Modify: `server/strategies/crypto_volatility_breakout.py`
- Create: `tests/test_strategy_ownership.py`
- Create: `tests/test_reconciliation.py`

- [ ] **Step 1: Write RED ownership tests**

Test that a Bollinger exit cannot sell an SMA-owned lot, two concurrent exits cannot reserve more than the owned quantity, account IDs isolate entry prices, external quantity is quarantined, and dust tolerance does not freeze an account.

```python
def test_strategy_cannot_sell_another_strategys_lot(ledger):
    ledger.open_lot("sma_cross", 23, "AAPL", "10", "100")
    assert ledger.sellable_qty("bollinger", 23, "AAPL") == Decimal("0")
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_strategy_ownership.py tests/test_reconciliation.py -q`.

- [ ] **Step 3: Implement owned-position reads and reservations**

Add DB functions `get_strategy_positions`, `get_strategy_entry_price(strategy, account_id, symbol)`, `get_sellable_qty`, `reserve_exit_qty`, and `release_exit_reservation`. Selection keys always include strategy, account, and canonical symbol.

- [ ] **Step 4: Implement reconciliation**

Implement `ReconciliationService.compare(account_id, broker_positions, open_orders)` returning VERIFIED, DUST, or FROZEN rows. Unknown broker quantity becomes `external/manual`; tolerance is one broker increment and max($1, minimum notional). Persist stable snapshot IDs.

- [ ] **Step 5: Route strategy evaluation through owned positions**

In `engine.run_tick`, pass `db.get_strategy_positions(strategy, account_id)` to each strategy, while account-level positions remain available only to portfolio exposure checks. Remove cross-strategy close matching. Update volatility-breakout entry lookup to include account ID.

- [ ] **Step 6: Run GREEN and engine regressions**

Run: `pytest tests/test_strategy_ownership.py tests/test_reconciliation.py tests/test_strategy_health.py tests/test_crypto_strategies.py -q`.

- [ ] **Step 7: Commit**

Commit Task 2 files.

## Task 3: Normalized broker acknowledgement and fill recovery

**Files:**
- Modify: `server/alpaca_client.py`
- Modify: `server/binance_client.py`
- Modify: `server/tradier_client.py`
- Modify: `server/broker_factory.py`
- Create: `server/execution_service.py`
- Create: `tests/test_execution_service.py`
- Modify: `tests/test_binance_client.py`

- [ ] **Step 1: Write RED adapter/service tests**

Cover timeout-after-accept recovery by client ID, partial then canceled orders, duplicate cumulative Binance snapshots, unsupported lookup fail-closed, delayed fees, and at-most-once economic submission.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_execution_service.py tests/test_binance_client.py -q`.

- [ ] **Step 3: Extend adapter contract**

Each adapter implements `get_order(order_id)`, `get_order_by_client_id(client_id)`, and `get_order_fills(order_id, since=None)`. Normalize states through `OrderState`. If only aggregate fills exist, emit deterministic monotonic delta fills and reject regressions.

- [ ] **Step 4: Implement execution service**

`ExecutionService.submit()` persists intent, marks SUBMITTING, submits once, binds acknowledgement, and on ambiguity performs three client-ID lookups over 60 seconds before UNKNOWN/freeze. `poll_account()` ingests fills with a persisted watermark and 24-hour overlap.

- [ ] **Step 5: Run GREEN and broker regressions**

Run: `pytest tests/test_execution_service.py tests/test_binance_client.py tests/test_api_broker.py tests/test_db_broker.py -q`.

- [ ] **Step 6: Commit**

Commit Task 3 files.

## Task 4: Route every order path through the execution service

**Files:**
- Modify: `server/engine.py`
- Modify: `server/main.py`
- Modify: `server/db.py`
- Create: `tests/test_order_path_coverage.py`

- [ ] **Step 1: Write RED path-coverage tests**

Assert automated, manual, webhook, take-profit, close-position, and close-all requests create execution intents and never mutate lots before fills. Assert manual closes require an owner selection and take-profit sells only owned quantity.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_order_path_coverage.py -q`.

- [ ] **Step 3: Replace direct broker submissions**

Inject/use `ExecutionService` from all six paths. Keep API response compatibility through order projections. Remove direct `record_open_trade`/`close_trade_and_record_perf` calls from acknowledgements.

- [ ] **Step 4: Add feature flags**

Add `execution_ledger_mode = shadow|authoritative` and `automation_quiesced`. Shadow mode records observations but cannot submit through the new path; authoritative mode disables the legacy submit path.

- [ ] **Step 5: Run GREEN and API regressions**

Run: `pytest tests/test_order_path_coverage.py tests/test_api_broker.py tests/test_api_strategy_accounts.py tests/test_api_backtest.py -q`.

- [ ] **Step 6: Commit**

Commit Task 4 files.

## Task 5: Consolidated portfolio risk and hard stop

**Files:**
- Create: `server/portfolio_risk.py`
- Modify: `server/risk.py`
- Modify: `server/engine.py`
- Modify: `server/db.py`
- Create: `tests/test_portfolio_risk.py`
- Create: `tests/test_hard_stop.py`

- [ ] **Step 1: Write RED risk tests**

Cover synchronized/stale account snapshots, 45/5/50 exposure, external cash-flow adjustment, paired internal transfers, 4% entry freeze, exact 5% hard stop, 1% daily/2% weekly freezes, restart during every shutdown step, closed-market exits, partial/rejected retries, and owner-only clearance.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_portfolio_risk.py tests/test_hard_stop.py -q`.

- [ ] **Step 3: Implement risk state**

Implement `PortfolioSnapshot`, `PortfolioRiskState`, `consolidate_snapshots`, `apply_external_flow`, and `evaluate_limits` using Decimal. Persist baselines/high-water mark and sample every 60 seconds.

- [ ] **Step 4: Implement quantity solver**

Implement bounded monotonic search for the largest broker increment satisfying stop loss plus costs and all exposure/cash/liquidity caps. Reject nonpositive stop distance.

- [ ] **Step 5: Implement durable shutdown**

Persist shutdown steps, cancel buys, reconcile, create owner-specific exits, queue closed-market stock exits, retry three times, resume on restart, and require owner clearance.

- [ ] **Step 6: Run GREEN and risk regressions**

Run: `pytest tests/test_portfolio_risk.py tests/test_hard_stop.py tests/test_per_account_risk.py tests/test_strategy_health.py -q`.

- [ ] **Step 7: Commit**

Commit Task 5 files.

## Task 6: Historical provider contracts and point-in-time data

**Files:**
- Create: `server/historical.py`
- Modify: `server/alpaca_client.py`
- Modify: `server/binance_client.py`
- Modify: `server/strategies/base.py`
- Create: `tests/test_historical_providers.py`

- [ ] **Step 1: Write RED provider tests**

Validate sorted unique finite OHLCV, stock/crypto separation, fingerprints, exact range/timeframe, split transformation, dividend cash event, symbol change, delisting, stale/missing data, and no silent fallback.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_historical_providers.py -q`.

- [ ] **Step 3: Implement contracts**

Add `HistoricalRequest`, `HistoricalDataset`, `CorporateAction`, `HistoricalProvider`, and validation/fingerprint helpers. Alpaca provider is stock-only daily; Binance provider is crypto-only daily UTC.

- [ ] **Step 4: Implement event-aware transformations**

Apply point-in-time splits consistently to OHLCV and position state, credit dividends as cash, preserve instrument IDs across symbol changes, and fail closed on unsupported merger/spinoff data.

- [ ] **Step 5: Run GREEN and adapter regressions**

Run: `pytest tests/test_historical_providers.py tests/test_backtest_alpaca.py tests/test_binance_client.py -q`.

- [ ] **Step 6: Commit**

Commit Task 6 files.

## Task 7: Deterministic portfolio backtester

**Files:**
- Replace internals: `server/backtest.py`
- Create: `server/backtest_models.py`
- Create: `server/backtest_metrics.py`
- Modify: `server/db.py`
- Modify: `server/main.py`
- Create: `tests/test_portfolio_backtest.py`
- Create: `tests/test_backtest_metrics.py`

- [ ] **Step 1: Write RED execution/accounting tests**

Test next-bar fills, future sentinel leakage, gaps, limited cash, simultaneous reservations, deterministic priority, costs, precision/minimum notional, final liquidation, calendar differences, and both accounting identities.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_portfolio_backtest.py tests/test_backtest_metrics.py -q`.

- [ ] **Step 3: Implement event loop and fill model**

Use explicit providers, unrounded Decimal cash/positions, later-bar fills, adverse slippage, fees, min notionals, and deterministic order ordering. Exceptions invalidate the run.

- [ ] **Step 4: Implement metrics**

Add return, CAGR, drawdown, annualized volatility, Sharpe, Sortino, Calmar, turnover, exposure, costs, expectancy, payoff, holding periods, worst daily return, 95% expected shortfall, and gap loss with timeframe-derived annualization.

- [ ] **Step 5: Persist reproducibility metadata**

Persist params, provider, timeframe, adjustment/event policy, data fingerprint, cost model, code revision, execution model, and end convention. Validate request bounds at the API.

- [ ] **Step 6: Run GREEN and legacy API regressions**

Run: `pytest tests/test_portfolio_backtest.py tests/test_backtest_metrics.py tests/test_backtest_engine.py tests/test_api_backtest.py tests/test_db_backtest.py -q`.

- [ ] **Step 7: Commit**

Commit Task 7 files.

## Task 8: Approved stock and crypto signal models

**Files:**
- Create: `server/strategies/liquid_stock_trend.py`
- Create: `server/strategies/btc_eth_trend.py`
- Modify: `server/strategies/__init__.py`
- Create: `tests/test_liquid_stock_trend.py`
- Create: `tests/test_btc_eth_trend.py`

- [ ] **Step 1: Write RED stock tests**

Cover rising SPY SMA200 regime, prior-252-high exclusion of current bar, SMA100/volume confirmation, deterministic ranking, ATR initial/trailing stop, two-close regime exit, no pyramiding, and persisted peak/stop state.

- [ ] **Step 2: Write RED crypto tests**

Cover BTC/ETH-only universe, prior-55-high entry, EMA50/200 regime, prior-20-low and two-close regime exits, ATR stops, precision, and 3%/2% caps.

- [ ] **Step 3: Run RED**

Run: `pytest tests/test_liquid_stock_trend.py tests/test_btc_eth_trend.py -q`.

- [ ] **Step 4: Implement minimal pure models**

Implement completed-bar signal generation with no network/global state. Persist entry ATR, peak close, stop, and rule version with owned lots/strategy state. Register both strategies.

- [ ] **Step 5: Run GREEN and all strategy regressions**

Run: `pytest tests/test_liquid_stock_trend.py tests/test_btc_eth_trend.py tests/test_crypto_strategies.py tests/test_ema_confluence.py tests/test_classic_patterns.py -q`.

- [ ] **Step 6: Commit**

Commit Task 8 files.

## Task 9: Walk-forward research, benchmarks, and statistical gate

**Files:**
- Create: `server/research.py`
- Create: `server/benchmarks.py`
- Create: `server/statistics.py`
- Modify: `server/db.py`
- Modify: `server/main.py`
- Create: `tests/test_walk_forward.py`
- Create: `tests/test_benchmarks.py`
- Create: `tests/test_statistics.py`

- [ ] **Step 1: Write RED research tests**

Test exact stock/crypto fold geometry, embargo/warm-up, cash reset/liquidation, frozen params, final-holdout single evaluation, persisted attempts, Calmar selection/ties, causal exposure benchmark, monthly policy benchmark, moving-block bootstrap, concentration, and inconclusive failure.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_walk_forward.py tests/test_benchmarks.py tests/test_statistics.py -q`.

- [ ] **Step 3: Implement orchestration**

Implement predeclared parameter grids and folds from spec Section 19.13. Persist every run. Freeze final params before holdout.

- [ ] **Step 4: Implement benchmarks and gate**

Implement 45% SPY/3% BTC/2% ETH/50% cash policy benchmark and prior-bar exposure-matched benchmark. Require all hard gates and positive lower confidence bounds per aggregate/sleeve/strategy.

- [ ] **Step 5: Run GREEN**

Run: `pytest tests/test_walk_forward.py tests/test_benchmarks.py tests/test_statistics.py -q`.

- [ ] **Step 6: Commit**

Commit Task 9 files.

## Task 10: Migration, compatibility, and operational controls

**Files:**
- Create: `server/migration.py`
- Modify: `server/main.py`
- Modify: `server/static/app.js`
- Create: `tests/test_execution_migration.py`
- Create: `tests/test_api_compatibility.py`

- [ ] **Step 1: Write RED migration/compatibility tests**

Use a copied legacy DB fixture. Prove rerunnable shadow migration, unknown quarantine, no row loss, golden API response compatibility, atomic authority switch, old-path fail closed, retention-gap freeze, and forward-recovery rollback.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_execution_migration.py tests/test_api_compatibility.py -q`.

- [ ] **Step 3: Implement shadow migration and projections**

Add schema versioning, dry-run report, bootstrap classification, compatibility projections, audit events, and owner resolution endpoints. Do not auto-adopt legacy inventory.

- [ ] **Step 4: Implement cutover guards**

Require backup marker, zero unknown nonterminal orders, reconciliation pass, paper accounts only, retention capability pass, and golden compatibility pass before authoritative mode.

- [ ] **Step 5: Run GREEN and full API suite**

Run: `pytest tests/test_execution_migration.py tests/test_api_compatibility.py tests/test_api_broker.py tests/test_api_strategy_accounts.py tests/test_api_backtest.py -q`.

- [ ] **Step 6: Commit**

Commit Task 10 files.

## Task 11: Full verification and research evidence

**Files:**
- Create: `docs/research/trading-strategy-validation.md`

- [ ] **Step 1: Run complete tests**

Run: `pytest -q`
Expected: zero failures.

- [ ] **Step 2: Run static/import checks**

Run: `python -m compileall -q server tests` and import `server.main` in a clean process. Expected: exit 0.

- [ ] **Step 3: Run deterministic research**

Run the stock and crypto walk-forward/holdout command against approved provider data. Save data fingerprints, code revision, all parameter attempts, costs, benchmarks, and pass/fail criteria.

- [ ] **Step 4: Write evidence report**

Record actual results without hiding failures. If any hard gate fails, keep that sleeve disabled and report it as failed/inconclusive; deployment may include the tested infrastructure but not enable the failed strategy.

- [ ] **Step 5: Run multi-agent final review**

Dispatch independent reviewers for spec compliance, code quality/security, quantitative leakage, and deployment safety. Fix every Critical/Important finding test-first and re-review.

- [ ] **Step 6: Commit**

Commit the verified research report and review-driven fixes.

## Task 12: VPS paper deployment and post-deploy verification

**Files:**
- Modify if required: `deploy.sh`, `tradebot.service`, operational docs

- [ ] **Step 1: Create production backup**

On VPS, stop only for the bounded cutover window; copy `/opt/tradebot/trading.db`, `.env`, and service definition to a timestamped backup. Verify checksums and available disk space.

- [ ] **Step 2: Deploy code without enabling strategies**

Deploy the verified revision, install only declared dependencies, run migration dry-run against a DB copy, then run the additive migration. Keep `execution_ledger_mode=shadow`, automation quiesced, AI tuner/sentiment/legacy strategies disabled.

- [ ] **Step 3: Start and verify service**

Run service status, health endpoint, dashboard/API smoke tests, log/error scan, schema version check, account reconciliation in read-only/shadow mode, and paper-account guard.

- [ ] **Step 4: Run VPS regression smoke suite**

Run targeted non-network unit tests plus compile/import checks on deployed files. Confirm no live account can enter authoritative automation.

- [ ] **Step 5: Enable only passing paper strategy sleeves**

If and only if the research gate passed for a sleeve and reconciliation is clean, enable that sleeve in paper mode under 45% stock / 5% crypto caps. Otherwise leave it disabled while deploying the infrastructure.

- [ ] **Step 6: Verify first scheduler cycles**

Observe at least two complete scheduler cycles, confirm no duplicate intents, no cross-owner exits, fresh consolidated snapshots, correct kill-switch state, and clean logs.

- [ ] **Step 7: Record deployment evidence**

Document deployed revision, backup paths/checksums, migration mode, enabled/disabled sleeves, health results, and rollback command set.
