# Task 9 — Walk-forward research, benchmarks, statistical gate (TDD)

Goal: Build the RESEARCH HARNESS (not a data run). Deterministic, no-network,
Decimal-money. Produces PASS/FAIL evidence; never enables a strategy. Files:
server/research.py, server/benchmarks.py, server/statistics.py, tests/*,
+ additive server/db.py persistence, + a read-only server/main.py research endpoint.

## Plan (COMPLETE)
- [x] Read plan Phase 0 + Task 9; design spec §11, §12, §19.10, §19.13
- [x] Inspect Task 6/7/8 code + DB + main; baseline regression green (105 passed)
- [x] RED tests/test_statistics.py (bootstrap CI, concentration, gate, 12 predicates)
- [x] RED tests/test_benchmarks.py (SPY B&H, 60/40, monthly policy, causal exposure-matched)
- [x] RED tests/test_walk_forward.py (fold geometry, embargo/warm-up, cash reset+liquidation,
      frozen params, single holdout eval, persisted attempts, Calmar selection + tie-breaks)
- [x] Ran RED, SAW failures (ImportError: cannot import server.statistics/benchmarks/research)
- [x] GREEN server/statistics.py (moving-block bootstrap, concentration, gate, 12 criteria) — 29
- [x] GREEN server/benchmarks.py (buy-and-hold, 60/40, monthly policy, prior-bar exposure-matched) — 10
- [x] GREEN server/research.py (fold geometry, embargo, grids, selection, freeze-before-holdout) — 24
- [x] Additive server/db.py: research_runs + research_attempts tables + save/list/get fns
- [x] Read-only server/main.py research endpoints (GET list/get persisted research runs)
- [x] GREEN: 3 new suites (63); regression subset (Tasks 1-8) 168 passed; py_compile; import server.main
- [x] Appended lesson; scratch empty; proved test_update_check 6 failures unrelated
      (same 6 fail with only my changes stashed; pre-existing stash@{0} restored untouched)

## Exact fold geometry (spec §19.10, §19.13) — DEFAULT constants = real spec values
STOCK: require 10 complete years. Final holdout = latest 24 complete months.
  Pre-holdout anchored folds: train starts 5 years, +1yr validation window, advance yearly.
  Embargo = 5 sessions. Bootstrap block = 20 sessions. Annualization = 252.
CRYPTO: require 6 complete years. Final holdout = latest 12 complete months.
  Pre-holdout anchored folds: train starts 3 years, +6mo validation window, advance ...
  Embargo = 2 days. Bootstrap block = 14 days. Annualization = 365.
Grids (predeclared): stock breakout [126,252], volume [1.0,1.2,1.4], trail ATR [2.5,3.0,3.5];
  crypto breakout [40,55,70], exit low [15,20,30], trail ATR [3.0,3.5,4.0]. Others fixed.
Selection: max training Calmar s.t. training max drawdown <= 5%; tie -> lower turnover;
  tie -> lexicographic params. Persist EVERY attempt (grid x fold).

## Hard rules (Phase 0 anti-patterns)
- NEVER optimize on the final holdout — it is scored EXACTLY ONCE after params frozen.
- No temporal leakage across fold boundaries; embargo unscored; warm-up produces no orders.
- Every OOS fold begins from CASH; params fixed within a fold; training positions liquidated
  with costs before a validation boundary; open validation positions liquidated at fold end.
- Fold returns chained geometrically (timestamp order) into ONE OOS curve; drawdown on chain.
- Decimal money. Research/reporting infra only — do NOT change live behavior.
- Do NOT enable any strategy as a side effect.
- Inconclusive (CI spans zero) is NOT a pass; wholly negative FAILS.

## Tests use small synthetic datasets with REDUCED fold sizes injected via parameters
(fast + deterministic) but the module DEFAULT constants must equal the real spec values.

## Verification commands
- python -m pytest tests/test_walk_forward.py tests/test_benchmarks.py tests/test_statistics.py -q
- python -m pytest tests/test_walk_forward.py tests/test_benchmarks.py tests/test_statistics.py
  tests/test_portfolio_backtest.py tests/test_backtest_metrics.py tests/test_liquid_stock_trend.py
  tests/test_btc_eth_trend.py tests/test_execution_ledger.py -q
- python -m py_compile server/research.py server/benchmarks.py server/statistics.py server/db.py server/main.py
- python -c "import server.main"
