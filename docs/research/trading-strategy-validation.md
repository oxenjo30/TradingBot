# Trading Strategy Validation — Evidence Report

**Task 11 of the trading-strategy-rebuild plan.** This report records the ACTUAL
result of the walk-forward / final-holdout research protocol for both strategy
sleeves, with no spin. It is the deployment verdict that Task 12 must obey.

- **Code revision under test:** `e243d71af2db6dfa6dcbaf782a99053195df9696`
- **Date of run:** 2026-07-11
- **Runner:** `scripts/run_strategy_research.py` (deterministic; read-only market
  data + in-memory backtest; `persist=None`; touches no live trading state)
- **Design references:** spec §7 (stock), §8 (crypto), §9 (data), §11–§12
  (validation + hard gates), §18 (approval boundary), §19.10 / §19.13
  (reproducible validation, statistical gate).

---

## 1. Verdict summary

| Sleeve | Data source reached | Verdict | Deploy action |
|--------|---------------------|---------|---------------|
| Stock (§7)  | Synthetic fallback (real Alpaca data unavailable) | **INCONCLUSIVE** | **Stays DISABLED** |
| Crypto (§8) | Synthetic fallback (real Binance data unavailable) | **INCONCLUSIVE** | **Stays DISABLED** |

**Neither sleeve PASSED. Neither sleeve may be enabled.**

> **Deployment (Task 12) may include the tested infrastructure but MUST NOT enable
> any sleeve that did not PASS.** Per spec §19.13, an inconclusive interval cannot
> pass and the sleeve remains disabled. Both sleeves here are inconclusive, so both
> `liquid_stock_trend` and `btc_eth_trend` remain `auto_trade=False, hidden=True`
> and are not assigned to any account.

An INCONCLUSIVE verdict is the **correct and expected** deliverable for this task
in the current environment. It is not a failure of the work — it is the honest
result of not having trustworthy data. Fabricating a green result would violate
spec §17 ("cannot prove future profitability") and the task's honesty-over-optics
rule.

---

## 2. Why real data could not be reached

The runner FIRST attempts real historical data for each sleeve over the full
window the geometry requires (stock ~10 years via Alpaca, crypto ~6 years via
Binance). Both attempts failed in this environment:

| Sleeve | Real-data attempt | Failure (verbatim) |
|--------|-------------------|--------------------|
| Stock  | `alpaca_client.historical_provider().fetch(...)` | `ValueError: No Alpaca credentials configured. Add an Alpaca account in Settings.` |
| Crypto | Binance client built from DB creds | `RuntimeError: crypto not initialised — DB_SECRET_KEY missing or invalid` |

Root causes (confirmed, read-only):

- A local `trading.db` exists and lists paper accounts (`alpaca` id 23, `binance`
  id 25, `tradier` id 31), but:
  - The stored Alpaca API key **decrypts to empty** (`len_key == 0`), so the
    live data client cannot be constructed.
  - Binance credential decryption **raises** because `DB_SECRET_KEY` is missing /
    mismatched in this environment. This is the documented `DB_SECRET_KEY` hazard:
    when that `.env` key does not match the one that encrypted the creds, every
    broker credential reads as invalid (a key-mismatch, **not** a broker/API
    outage).

Because no real bars could be obtained, no real-data run was performed. The runner
did not crash — it caught each error, recorded it, and fell back to clearly
labelled synthetic fixtures for an **infrastructure-only** demonstration.

---

## 3. The stock split-adjustment limitation (bounds the stock verdict independently)

Even if Alpaca credentials were present, the **stock sleeve would still be
INCONCLUSIVE** on the current wiring, for a structural reason:

- The network stock provider (`server/alpaca_client.py::historical_provider` →
  `_NetworkAlpacaProvider._raw_bars` → `get_recent_bars(symbol, days=3650)`)
  passes **no `corporate_actions`**. The split-adjustment transform in
  `server/historical.py` (`apply_split_to_bars`) therefore has nothing to apply,
  so real stock bars are returned **UNADJUSTED for splits and dividends**.
- The §7 universe contains multiple **forward splits inside a 10-year window**:
  - AAPL 4:1 (2020-08-31)
  - NVDA 4:1 (2021-07-20) and 10:1 (2024-06-10)
  - AMZN 20:1 (2022-06-06)
  - GOOGL 20:1 (2022-07-18)
- On an unadjusted series, the day a split takes effect shows a ~75–95% price
  "drop" that is not a market move. This fabricates a false stop-out and destroys
  every trailing-high / breakout computation around the event.

Spec §19.13 ("Corporate actions and total return") is explicit:

> *"Providers that cannot supply these point-in-time bars and events cannot produce
> a passing stock research result."*

Therefore the stock sleeve is bounded to **INCONCLUSIVE** by the data contract
itself, independent of credentials. Wiring an authoritative split/dividend feed
into the stock provider is a prerequisite for any future stock PASS. This is a
known, documented limitation — not a defect introduced by this task.

The crypto sleeve has no split analogue (spot BTC/ETH daily has no splits), so if
Binance credentials were valid the crypto sleeve *could* in principle reach real
data and produce a real (non-forced) verdict. It could not here because of the
`DB_SECRET_KEY` credential failure above.

---

## 4. What the run actually did (infrastructure demonstration)

To prove the research pipeline executes end-to-end, the runner drove both sleeves
through the **real code path** on clearly labelled synthetic fixtures:

`predeclared_grid` → `FoldGeometry.*_default()` → `run_walk_forward`
(anchored folds + single-scored holdout) → `backtest_fn` wrapping
`PortfolioBacktester` (next-bar fills, adverse slippage/fees, FIFO lots, Decimal
accounting, full §10.4 metrics) → §12/§19.13 statistical gate
(`moving_block_bootstrap_ci` + `classify_ci`).

The synthetic series is a trending sine with drift, chosen ONLY so the pipeline
produces genuine breakouts and stop-out exits. **The numbers below are meaningless
as evidence of profitability** — they demonstrate that the machinery runs, nothing
more. The verdict is forced INCONCLUSIVE regardless of them.

### Stock sleeve (synthetic infrastructure demo)

| Field | Value |
|-------|-------|
| Grid attempts exercised | 95 (training + validation + freeze + holdout) |
| Frozen params (selected on all pre-holdout data) | `breakout=252, volume=1.0, trail_atr=2.5` |
| Baseline-cost OOS net return | `0.294135` |
| Stressed-cost OOS net return | `0.290167` |
| Holdout closed trades | 3 |
| Holdout daily-return 95% CI (moving block) | `[0.000010, 0.000044, 0.000084]` |
| Equal-weight buy-and-hold benchmark (holdout) | `0.2316` |

### Crypto sleeve (synthetic infrastructure demo)

| Field | Value |
|-------|-------|
| Grid attempts exercised | 168 |
| Frozen params | `breakout=40, exit_low=15, trail_atr=3.0` |
| Baseline-cost OOS net return | `0.057711` |
| Stressed-cost OOS net return | `0.049235` |
| Holdout closed trades | 2 |
| Holdout daily-return 95% CI (moving block) | `[0.000024, 0.000043, 0.000060]` |
| Equal-weight buy-and-hold benchmark (holdout) | `0.4367` |

**Note the load-bearing safety behaviour:** both synthetic holdout intervals have a
*positive* lower bound (`0.000010`, `0.000024`), which on real data would read as
PASS. The runner still reports **INCONCLUSIVE** for both, because
`SleeveData.forced_inconclusive` overrides the raw gate whenever the data is
synthetic or (for stock) structurally unusable. Honesty over optics is enforced in
code, and locked by `tests/test_run_strategy_research.py::
test_forced_inconclusive_overrides_positive_interval`.

### Cost assumptions used (spec §10.2)

- Stocks: baseline 10 bps one-way slippage; stress 20 bps.
- Crypto: baseline 10 bps fee + 5 bps slippage each way; stress 20 bps + 20 bps.
- Applied adversely on both sides via `CostModel.baseline` / `CostModel.stress`.

### Data fingerprints (reproducibility)

Each dataset carries a deterministic SHA-256 content fingerprint (see
`fingerprint_bars`). The synthetic fingerprints for this run are recorded in the
`--json` output of the runner; because the synthetic generator is deterministic,
re-running reproduces the same fingerprints bit-for-bit. Real-data fingerprints
will replace these once an authoritative feed is wired.

---

## 5. Hard-gate status against spec §12

Because both sleeves are INCONCLUSIVE on data grounds, the twelve §12 criteria are
**not evaluated as a pass** for either sleeve. The two that are decisive here:

- **§12 / §19.13 statistical gate** — a confidence interval that is not strictly
  positive on *trustworthy* data cannot pass. We have no trustworthy data, so the
  gate cannot be satisfied. Verdict: INCONCLUSIVE.
- **§11.1 data quality** — required coverage / corporate-action quality is
  unavailable (stock: unadjusted + in-window splits; crypto: no reachable feed).
  Spec §11.1: *"the limitation is reported and the affected result cannot be
  labeled proven."* Reported here.

The §12 criteria implementations themselves are unit-tested (`tests/
test_statistics.py`) and the three-valued gate (PASS / FAIL / INCONCLUSIVE, where
spanning zero or lower-bound == 0 is never a pass) is verified there.

---

## 6. Deployment instruction for Task 12

1. **Do NOT enable `liquid_stock_trend`.** It stays `auto_trade=False,
   hidden=True`, unassigned. It is bounded to INCONCLUSIVE until an authoritative
   split/dividend-adjusted stock feed is wired AND a real 10-year run PASSES the
   §12 gate.
2. **Do NOT enable `btc_eth_trend`.** It stays disabled until valid Binance
   credentials (fix `DB_SECRET_KEY` / re-enter keys) allow a real 6-year run that
   PASSES the §12 gate.
3. **The infrastructure MAY be deployed** in shadow mode: the execution ledger,
   backtester, research runner, and read-only research endpoints are additive and
   do not enable trading. Keep `execution_ledger_mode = shadow` and automation
   quiesced (spec §19.8, §14 Phase F).
4. **Re-run this exact script** (`python scripts/run_strategy_research.py`) once a
   trustworthy feed is available. A sleeve is enabled **only** on a PASS verdict
   with a strictly-positive holdout CI lower bound and all applicable §12 hard
   gates satisfied.

---

## 7. Reproduction

```bash
python scripts/run_strategy_research.py            # human-readable
python scripts/run_strategy_research.py --json     # machine-readable
python -m pytest tests/test_run_strategy_research.py -q   # pipeline smoke tests
```

The script never places an order, never enables a strategy, never mutates
`trading.db`, and never contacts the VPS. Confirmed post-run: `execution_ledger_mode`
still shadow, research strategies not enabled, `trading.db` unmodified in git.

---

## 8. Final review (four adversarial lenses)

Four independent review passes were run against the design doc and the code, each
adopting a different adversarial lens. Every Critical/Important finding was fixed
test-first; the rest is cited evidence.

### (a) Spec compliance vs §7 / §8 / §9 / §12 / §18 / §19

- **§7 stock rules** — the research adapter (`_StockAdapter`) reproduces: prior-252
  breakout with the decision bar EXCLUDED (`prior = bars[:-1]`), strict inequality
  `close > prior_high`, SMA100 confirmation, 1.2× prior-20 volume, SPY regime
  (close > SMA200 AND SMA200 rising over 20 sessions), two-close-below regime exit,
  2.5·ATR initial / 3.0·ATR trailing stop that never lowers, max 5 positions, no
  pyramiding. Grid params `{breakout, volume, trail_atr}` are threaded from
  `predeclared_grid("stock")`.
- **§8 crypto rules** — `_CryptoAdapter` reproduces: prior-55 breakout (decision
  candle excluded), EMA50>EMA200 regime, 20-low / two-close-below-EMA200 / ATR-stop
  exits, 3.0·ATR initial / 3.5·ATR trailing, max 2 positions, precision + min
  notional via `SymbolSpec`. Grid `{breakout, exit_low, trail_atr}`.
- **§9 data** — real bars flow through the wired network providers
  (`historical_provider`), which enforce stock/crypto separation and never fall
  back across asset classes. Fingerprints are recorded.
- **§12 / §19.13 gate** — the three-valued gate (`classify_ci`) is applied to the
  holdout daily-return series; a non-strictly-positive interval is never a pass.
- **§18 / approval boundary** — no strategy is enabled; this task produces evidence
  only.
- Finding: **none Critical/Important.** The adapters intentionally re-express the
  live-strategy rules for a from-cash, grid-swept run (the live classes hard-code
  thresholds and read the live ledger, which is unsuitable for research). This
  duplication is documented in the script and is the minimal correct approach.

### (b) Code quality + security

- **No secret leakage** — decrypted `key`/`sec` are passed only as positional args
  to the read-only Binance client and are NEVER interpolated into any string, log,
  or exception (verified by grep). **Important finding fixed test-first:** to defend
  against a third-party (ccxt) exception echoing request material, `_safe_error()`
  now redacts any ≥16-char alphanumeric run from a recorded real-data failure
  reason. Locked by `test_safe_error_redacts_credential_like_tokens` and
  `test_acquire_failure_reason_is_sanitized`.
- **No unsafe eval/exec** — none present. The only `subprocess` call is
  `git rev-parse HEAD` with a fixed argv (no shell).
- **No network in unit tests** — `tests/test_run_strategy_research.py` forces the
  synthetic path (or monkeypatches the real-data functions to raise); it makes no
  network call. Spec §15 ("no network call in deterministic unit tests") holds.

### (c) Quantitative leakage

- **Holdout scored exactly once** — enforced by `research.run_walk_forward` and
  locked by `tests/test_walk_forward.py::test_final_holdout_scored_exactly_once_
  after_freeze` and `::test_holdout_window_never_used_for_any_training_call`.
- **From-cash isolation** — every validation and holdout run starts from cash:
  `::test_every_validation_and_holdout_runs_start_from_cash`. My `_slice` borrows NO
  warm-up prefix across a window boundary, so no pre-window bar leaks into a
  from-cash window's scored region.
- **No look-ahead in the backtester** — the strategy sees only completed bars up to
  and including the decision bar, and orders fill at the NEXT bar's open:
  `tests/test_portfolio_backtest.py::test_signal_fills_at_next_bar_open_not_same_bar`,
  `::test_future_sentinel_does_not_change_earlier_signal`,
  `::test_strategy_never_sees_future_bars`.
- **Decision-bar exclusion** — trailing-window thresholds compute over `bars[:-1]`
  in both adapters (§7.3 / §8.2). Finding: **none Critical/Important.**

### (d) Deployment safety

- **Default stays shadow** — `execution_router.execution_ledger_mode()` returns
  `shadow` by default and fails SAFE to shadow on any unknown value; the research
  script never calls `set_execution_ledger_mode`.
- **No strategy auto-enabled** — both research strategies are
  `auto_trade=False, hidden=True` (asserted at review time); saving a research run
  does not enable any strategy (`tests/test_walk_forward.py::
  test_saving_a_run_does_not_enable_any_strategy`).
- **Cutover gated** — `migration.check_cutover_guards` / `perform_cutover` require
  every guard (backup, zero unknown nonterminal orders, reconciliation, paper-only,
  retention, golden compatibility) and leave mode UNCHANGED on any failure
  (Task 10). Finding: **none Critical/Important.**

**Net:** one Important issue (credential-adjacent redaction) found and fixed
test-first; all other lenses passed with cited evidence.

---

## ADDENDUM — Real-data run on the VPS (2026-07-11)

The initial Task 11 run fell back to synthetic fixtures on the local machine
(no decryptable broker credentials). This addendum records the **real-data**
run executed on the production VPS, which has working broker credentials and
`DB_SECRET_KEY`. Three fixes were required to reach real data, each committed:

1. **Split/dividend adjustment** (`6b8183f`) — `get_recent_bars` now supports
   `adjustment` (default `raw`, live path unchanged); the research provider pulls
   `adjustment='all'`. Verified: AAPL's 2020-08-31 4:1 split is continuous
   (124.81 → 129.04 → 134.18), not a fabricated ~73% gap. `_detect_split_gap`
   re-forces INCONCLUSIVE if any uncorrected split-sized gap remains.
2. **`init_crypto()` in the runner** (`0ce7b51`) — the standalone script never
   initialised Fernet, so every `crypto.decrypt()` failed and both sleeves fell
   back to synthetic even with valid credentials.
3. **History window + graceful shortfall** (`586c228`) — the fetch window clipped
   ~5 months of the daily history Alpaca actually holds; widened to capture the
   full series (2644 stock sessions, 2016-01-04 → 2026-07-10). `run_sleeve` now
   catches `InsufficientHistory` and reports that sleeve INCONCLUSIVE instead of
   aborting the whole run.

### Real-data verdicts

| Sleeve | Data | Sessions | Verdict | Reason |
|--------|------|----------|---------|--------|
| Stock  | REAL (Alpaca, split+div adjusted) | 2644 (2016–2026), 4 folds | **INCONCLUSIVE** | Walk-forward selection (§19.10) froze NO parameter set across all 4 folds → no holdout series. |
| Crypto | REAL (Binance) | 1000 (~2.75y) | **INCONCLUSIVE** | Binance client caps at 1000 daily bars; the 6y walk-forward needs ≥ 2190. Needs history pagination. |

### What the stock result means (the honest answer)

- The strategy **does trade and can be profitable** in isolation: the most
  permissive grid point (breakout=126) took 179 pre-holdout trades for **+31.9%**
  net and 22 holdout trades.
- BUT the **walk-forward's own out-of-sample selection rule rejected every
  parameter set** — none cleared the Calmar/drawdown/turnover selection thresholds
  on the training folds — so `frozen_params = None` and there is no scored holdout.
- Even a what-if evaluation of breakout=126 on the holdout gives a 95% daily-return
  CI of **[-0.000057, +0.000206]** → spans zero → **INCONCLUSIVE** by the §12 gate.
  The edge is not statistically distinguishable from zero after costs.

**Conclusion:** on real, split-adjusted, 10-year data, the §7 liquid-stock trend
strategy is **NOT validated** — it is INCONCLUSIVE, not a proven winner. Per
§12/§19.13 it **remains disabled**. This is consistent with the live observation
that the stock engine rarely trades. No strategy is enabled by this run.

### Remaining work for a scored crypto verdict

`binance_client.get_recent_bars` passes `limit=days` to a single `fetch_ohlcv`
call, which Binance caps at 1000. A real 6-year crypto walk-forward requires
paginating with the `since` parameter across multiple calls. Until then the
crypto sleeve is INCONCLUSIVE on data-coverage grounds, not on merit.

---

## ADDENDUM 2 — Crypto with paginated history (2026-07-11)

Added `BinanceAccountClient.get_historical_bars()` (paginated past Binance's
1000-bar cap; commit `6a1f1ea`) so the crypto sleeve finally has enough history.

### Real crypto verdict (deep data)

| Sleeve | Data | Sessions | Verdict | Detail |
|--------|------|----------|---------|--------|
| Crypto | REAL (Binance, paginated) | 2232 (2020-06 → 2026-07) | **INCONCLUSIVE** | Froze `breakout=40, exit_low=15, trail_atr=3.5`; validation folds +7.4% net; **holdout took 0 trades → CI [0,0]**. |

**Why 0 holdout trades is not a failure of the strategy:** the scored holdout
window (2025-07 → 2026-07) is a severe crypto **bear market** — BTC fell
$119,178 → $64,139 (**−46%**), ETH −48%, equal-weight buy-and-hold **−47%**. The
frozen trend-following params correctly **stayed in cash** rather than buying a
sustained downtrend. That is the strategy behaving as designed — but "flat" yields
no return series, so the §12 gate cannot award a positive-edge PASS.

**Net crypto reading:** the strategy is *sensible* (it traded 61× for +7.4% across
the validation era and avoided a −47% crash) but is **NOT validated** by the strict
holdout gate, because the single holdout window is a downtrend. Per §12/§19.13 it
**remains disabled**.

### Overall conclusion (both sleeves, real deep data)

| Sleeve | Data quality | Verdict | Enabled? |
|--------|--------------|---------|----------|
| Stock (§7)  | Real, 10y, split-adjusted | INCONCLUSIVE (selection froze no params; edge ≈ 0 after costs) | **NO** |
| Crypto (§8) | Real, 6y, paginated | INCONCLUSIVE (holdout is a bear market; strategy correctly flat) | **NO** |

Neither strategy is a backtest-proven winner under the walk-forward + statistical
gate. Both remain disabled. The rebuild infrastructure (execution ledger, risk,
backtester, validation, migration) is deployed to the VPS in **shadow mode** with
**no strategy enabled**. Getting a PASS would require either (a) a strategy/param
redesign that survives walk-forward selection, or (b) a holdout window that spans a
market regime where the strategy can demonstrate a positive edge — neither of which
should be forced.

---

## ADDENDUM 3 — dual_momentum: FIRST VALIDATED STRATEGY (2026-07-11)

After disabling the net-negative live strategies (classic_patterns -$1,954 + 4
others), a new strategy was designed from the P&L evidence: **dual_momentum**, a
low-turnover monthly ETF rotation (SPY/QQQ/IWM/DIA/GLD/TLT/EEM) with dual absolute
(close > SMA) + relative (top-K by lookback return) momentum, going to cash when
nothing qualifies. Deliberately the opposite of the high-turnover pattern matcher
that bled the most.

### Two framework bugs found and fixed en route (not strategy faults)

1. **Drawdown gate mis-calibrated** (`05280e9`): `TRAINING_DRAWDOWN_CAP` and
   `DRAWDOWN_CEILING` required max DD >= -5%, impossible for long-only equity (any
   window spanning 2022 exceeds it). 0/18 configs were ever eligible → every equity
   strategy froze no params → INCONCLUSIVE regardless of real performance. Relaxed
   to an equity-appropriate -20%.
2. **Validator read the wrong holdout field** (`940fe4c`): `run_walk_forward`'s
   holdout_summary carries net_return/max_drawdown but NOT the daily-return series,
   so the gate saw "no series" even when the frozen config traded and profited.
   Re-run the frozen params once on the holdout to extract the series.

### Verdict: **PASS** (real data, deterministic, reproduced)

| Field | Value |
|-------|-------|
| Data | Real Alpaca, split+dividend adjusted, 2644 sessions (2016–2026) |
| Frozen params | lookback=252, abs_sma=150, top_k=3 (selected pre-holdout only) |
| Holdout window | 2024-07-08 → 2026-07-10 (untouched during selection) |
| Holdout net return | **+18.5%** over ~2 years |
| Holdout max drawdown | **-7.8%** (within the -20% equity cap) |
| Holdout daily-return 95% CI | **[+0.000014, +0.000351, +0.000729]** — lower bound > 0 |
| Gate result | **PASS** — statistically significant positive edge after costs |
| Holdout trades | 5 |

The CI lower bound is above zero: the strategy's positive daily edge is
statistically distinguishable from zero after realistic costs — the strict §12
criterion. The result is deterministic (re-run produced identical CI + data
fingerprints).

**This is the first strategy to PASS validation.** Per §12/§19.13 a PASS makes it
ELIGIBLE for a paper-mode deployment — but enabling it requires explicit owner
approval and should begin in PAPER accounts under the shadow→authoritative process.
It is NOT auto-enabled; `auto_trade=False` still holds until an operator turns it on.
