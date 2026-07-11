# Task 6 — Historical provider contracts and point-in-time data (TDD)

Goal: Add explicit stock/crypto historical providers with normalized datasets,
validation, deterministic fingerprint, and point-in-time corporate-action
transformations. Backtest/research infra only — live engine untouched.

## Plan (COMPLETE)
- [x] Read plan Task 6, spec §9/§10.1/§19.11, existing adapters & fixtures
- [x] Write failing tests in tests/test_historical_providers.py (RED)
- [x] Run RED, SEE failures (ModuleNotFoundError: server.historical)
- [x] Implement server/historical.py contracts + validation + fingerprint
- [x] Implement AlpacaHistoricalProvider (stock-only daily) — no fallback
- [x] Implement BinanceHistoricalProvider (crypto-only daily UTC) — no fallback
- [x] Implement event-aware transforms (splits, dividends-as-cash, symbol change,
      merger/spinoff fail-closed, delisting)
- [x] Add thin provider hooks to alpaca_client.py / binance_client.py / strategies/base.py
      WITHOUT changing live behavior
- [x] Run GREEN: tests/test_historical_providers.py (45 passed)
- [x] Regression: historical + backtest_alpaca + binance_client + execution_service
      + execution_ledger (107 passed)
- [x] py_compile all touched files; import server.main clean
- [x] Prove test_update_check failures are pre-existing/unrelated (stashed only my
      changes; same 6 failures with my code absent; pre-existing stash@{0} untouched)
- [x] No scratch files created; no correction needed so no lessons entry

## Verification commands
- python -m pytest tests/test_historical_providers.py -q
- python -m pytest tests/test_historical_providers.py tests/test_backtest_alpaca.py tests/test_binance_client.py tests/test_execution_service.py tests/test_execution_ledger.py -q
- python -m py_compile <touched files>; python -c "import server.main"
