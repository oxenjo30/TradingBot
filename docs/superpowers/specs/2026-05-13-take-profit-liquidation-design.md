# Take-Profit & Manual Liquidation — Design Spec

**Date:** 2026-05-13  
**Status:** Approved

---

## Goal

Two independent features shipped together:

1. **Global take-profit** — engine auto-sells any position whose unrealized gain reaches a user-configured % threshold.
2. **Manual liquidation** — user can close a single position or all positions from the Positions page UI.

---

## Feature 1: Global Take-Profit

### Risk Setting

- New field: `take_profit_pct` (float, default `0.0`)
- Stored in the existing `risk_settings` DB table via `db.set_risk_setting()` / `db.get_risk_settings()`
- `0` means disabled — no take-profit checks run
- Valid range: `0–1000` (supports crypto multi-bagger scenarios)

### Engine Tick — second pass

After the existing strategy signal loop in `engine.py:run_tick()`, add a take-profit pass per account:

```
for each account in client_cache:
    take_profit_pct = risk_settings["take_profit_pct"]
    if take_profit_pct <= 0: skip
    positions = acct_client.get_positions()
    for each position p:
        if p["unrealized_plpc"] >= take_profit_pct:
            submit market sell, qty = p["qty"]
            log to signals table: strategy="take_profit", status="filled"
            remove from local position cache
```

- Skips `risk.check_all()` — exits are never blocked by risk guards
- Skips global kill switch check — take-profit exits are always allowed
- Per-account kill switch (`db.get_account_kill_switch`) is also skipped — same reasoning
- Logs each exit to `signals` table with `strategy="take_profit"`, `reason="take profit {pct}%"`, `status="filled"`
- No notification sent — log entry only

### Risk Page UI

New `.ri` sub-card added to the **Risk Limits** `rg3` grid (becomes a 4th card, or wraps to a second row — CSS grid handles it):

- Icon: green trending-up SVG, `ri-icon-green` colour class
- Label: "Take Profit"  
- Description: "Auto-sell any position when unrealized gain reaches this %. Set to 0 to disable."
- Input: `id="inp-take-profit"`, type number, step 0.5, min 0, max 1000
- Suffix: `%`
- Save button: `data-key="take_profit_pct"`, `data-source="inp-take-profit"` — reuses existing `.risk-save-btn` handler

**Styling:** Uses only CSS variables (`var(--card)`, `var(--border)`, `var(--text)`, `var(--muted)`) and the existing `.ri`, `.ri-field`, `.ri-suffix`, `.btn-risksave` classes. The existing `[data-theme="light"]` overrides in `styles.css` already cover all these classes — no new CSS needed.

---

## Feature 2: Manual Liquidation

### Backend

Both endpoints already exist and are correct — no changes needed:

- `DELETE /api/positions/{symbol}?account_id=` — close one position
- `DELETE /api/positions?account_id=` — close all positions

### Positions Page UI

#### Per-row Close button

- Add 8th column header: empty `<th>` (no label)
- Each position row gets a `<td>` with a small close button:
  - Class: `btn-close-pos`
  - Content: `×` (times symbol)
  - On click: confirm dialog → "Close {SYMBOL}? This will submit a market sell for the full position." → on confirm: `DELETE /api/positions/{symbol}?account_id=` → refresh table
- Button hidden (opacity 0, shown on row hover) for a clean default appearance

#### Close All button

- Added to positions page header, right of the account selector
- Label: "Close All"
- Class: `btn btn-danger`, small (`font-size: 11px`, compact padding)
- On click: confirm dialog → "Close ALL open positions? This cannot be undone." → on confirm: `DELETE /api/positions?account_id=` → refresh table
- Hidden (`display:none`) when positions table is empty; shown when at least one position exists

#### Confirm flow

Reuses the existing `openModal()` utility already in `app.js` — no new modal HTML needed.

#### Styling

- `.btn-close-pos`: small, `color: var(--red)`, transparent background, border on hover — uses CSS variables, works in both themes
- `btn-danger` class already exists in `styles.css`

---

## Files Changed

| File | Change |
|------|--------|
| `server/db.py` | Add `take_profit_pct` to default risk settings |
| `server/engine.py` | Add take-profit pass after strategy loop |
| `server/static/risk.html` | Add take-profit `.ri` card in Risk Limits grid |
| `server/static/app.js` | Load/save `take_profit_pct` in `initRisk()`; add close buttons + Close All to positions page |
| `server/static/styles.css` | Add `.btn-close-pos` style (CSS-variable-based) |

---

## What's Explicitly Out of Scope

- Per-strategy take-profit overrides
- Stop-loss (separate feature)
- Notifications on take-profit exit
- Take-profit for limit orders (market sell only)
- Editing take-profit target per open position
