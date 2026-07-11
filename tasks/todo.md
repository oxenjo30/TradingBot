# Task 7 — Deterministic portfolio backtester (TDD)

Goal: Replace backtest internals with a deterministic, decimal-safe, portfolio-aware
engine driven by explicit HistoricalDataset providers. Enforce temporal integrity,
next-bar fills, adverse costs, cash reservation (no negative cash), stock/crypto
calendar-aware annualization, and BOTH accounting identities. Preserve the existing
/api/backtest response shape used by the dashboard.

## Plan (COMPLETE)
- [x] Design backtest_models.py + backtest_metrics.py
- [x] Write RED tests/test_portfolio_backtest.py
- [x] Write RED tests/test_backtest_metrics.py
- [x] Run RED, SEE failures (ModuleNotFoundError: server.backtest_models/_metrics)
- [x] Implement server/backtest_metrics.py (pure decimal metrics) — 26 tests
- [x] Implement server/backtest_models.py (portfolio engine) — 23 tests
- [x] Rewire server/backtest.py -> new engine via _LegacyStrategyAdapter,
      keep legacy dict response shape (32 legacy tests still pass)
- [x] Add reproducibility metadata column + persistence to server/db.py
- [x] Validate request bounds at server/main.py (Field gt/ge/le)
- [x] Run GREEN: test_portfolio_backtest + test_backtest_metrics (49 passed)
- [x] Regression: + backtest_engine + api_backtest + db_backtest
      + historical_providers + execution_ledger (137 passed); broad sweep 324 passed
- [x] py_compile touched files; import server.main clean
- [x] Prove test_update_check failures pre-existing/unrelated (same 6 fail with my
      code stashed away; pre-existing stash@{0} restored untouched)
- [x] No scratch files left; appended lesson (test/impl expectation corrections)

## Key invariants
- Decimal for all cash/positions; ROUND_DOWN for order qty.
- Strategy sees only completed bars; fills strictly after signal ts (next-bar open).
- Future sentinel bar must not change earlier signals.
- Cash cannot go negative; simultaneous orders reserve cash before fills.
- account identity: ending_cash + ending_market_value == ending_equity (unrounded)
- attribution identity: initial_equity + gross_realized + gross_unrealized + income
  + external_flows - entry_fees - exit_fees - other_costs == ending_equity
- Gross realized/unrealized EXCLUDE fees. Net lot P&L is derived-only.
- Annualization: stock=252 sessions, crypto=365 days (one documented scale).

## Verification commands
- python -m pytest tests/test_portfolio_backtest.py tests/test_backtest_metrics.py -q
- python -m pytest tests/test_portfolio_backtest.py tests/test_backtest_metrics.py
  tests/test_backtest_engine.py tests/test_api_backtest.py tests/test_db_backtest.py
  tests/test_historical_providers.py tests/test_execution_ledger.py -q
