# Bots & Strategies Page Redesign — Design Spec

**Date:** 2026-05-11

---

## Problem

The current Bots & Strategies page uses a strategy-first table with expandable rows. To see which accounts run a strategy the user must expand each row. The mental model is backwards for most use cases — users think "which strategies are running on my account?" not "which accounts run this strategy?"

## Goal

Redesign the page with an account-first two-panel layout: select an account on the left, see all its strategies on the right. Per-account toggles are the primary control.

---

## Layout

Two-panel grid (`220px` left | `1fr` right), vertically aligned to the top.

### Engine Bar (full-width, above panels)

```
[ Engine ]  3 of 6 strategies enabled · Last run: 2:45 PM · Next: 3:00 PM
            [ ▶ Run Now ]  [ ⚡ Kill Switch ]
```

- Kill switch banner (red strip) appears above the bar when active.
- Paper trading banner appears above the bar when account is paper.

### Left Panel — Broker Accounts

- Title: "Broker Accounts" (section label style)
- Each account row: dot color (blue=paper, yellow=live), name, type sub-label, badge (paper/live)
- Active account highlighted with blue left border + subtle blue background
- Footer: `+ Add Account` ghost button (links to Broker Accounts page)
- Panel is `position: sticky; top: 1rem`

### Right Panel — Strategy List

Header shows: `{Account Name} — {Paper|Live}` + meta count (`3 of 7 strategies assigned`)

Two sections:

**Assigned to this account**
- Each row: strategy icon, name, description, status badge (Running / Paused), per-account toggle, `Remove` button
- Toggle ON = strategy enabled on this account (green, Running badge)
- Toggle OFF = strategy disabled on this account (grey, Paused badge)
- `Remove` unassigns the strategy from this account (disables it)

**Not assigned to this account**
- Each row: strategy icon, name, description (dimmed, opacity 0.55), `+ Assign` button
- Clicking `+ Assign` immediately assigns and enables the strategy for the selected account, moves the row to the Assigned section

---

## Data Flow

### On page load

1. Parallel: `GET /api/broker-accounts` + `GET /api/strategies` + `GET /api/engine` + `GET /api/risk`
2. Render left panel with all accounts; select the first account
3. Load the selected account's strategy assignments (see below)
4. Apply kill switch / paper banner state

### On account select

Call: `GET /api/broker-accounts/{id}/strategies` (new endpoint, see Backend section)

Returns all 7 strategies with per-account assignment and enabled status. Renders right panel.

### Assign

`POST /api/strategies/{name}/accounts` with `{ account_id, enabled: true }`

On success: re-render right panel (move row to Assigned, toggle ON).

### Remove

`DELETE /api/strategies/{name}/accounts/{account_id}`

On success: re-render right panel (move row to Unassigned).

### Toggle

`PATCH /api/strategies/{name}/accounts/{account_id}` with `{ enabled: true|false }`

On success: update row status badge and toggle state.

### Run Engine Now

`POST /api/engine/run_now` — show result panel briefly, refresh engine bar meta.

### Kill Switch

`POST /api/risk/kill_switch` `{ on: true|false }` — show/hide banner, update button style.

---

## Backend Changes

### New endpoint

`GET /api/broker-accounts/{account_id}/strategies`

Returns all strategies enriched with per-account data:

```json
[
  {
    "name": "momentum",
    "label": "Momentum Breakout",
    "description": "Buys stocks with strong upward momentum confirmed by volume",
    "global_enabled": true,
    "assigned": true,
    "enabled": true
  },
  {
    "name": "sma_cross",
    "label": "SMA Crossover",
    "description": "50-day vs 200-day simple moving average",
    "global_enabled": true,
    "assigned": false,
    "enabled": false
  }
]
```

Implementation: join `strategy_accounts` with the strategy registry. One SQL query.

New `db.py` function: `get_account_strategies(account_id: int) -> list[dict]`

```sql
SELECT
  sa.strategy_name,
  sa.enabled AS per_account_enabled
FROM strategy_accounts sa
WHERE sa.account_id = ?
```

Then merge with `strategies.REGISTRY` metadata to include all strategies (assigned or not).

### No changes to existing endpoints

All assign / unassign / toggle / kill_switch / engine endpoints remain as-is.

---

## Frontend Changes

### bots.html

Replace the current content area (strategy table + modals) with:

- Kill switch banner (already present, keep)
- Paper mode banner (already present, keep)
- Engine bar card (keep, minor cleanup)
- `<div class="two-panel">` containing left panel + right panel
- Remove: strategy table, expandable sub-rows, assign-account modal, unassign modal, toggle modal

### app.js — `initBots()` rewrite

Replace current `fetchStrategies()` and its DOM-building logic with:

- `renderAccountPanel(accounts)` — builds left panel
- `selectAccount(account)` — fetches `/api/broker-accounts/{id}/strategies`, calls `renderStratPanel(account, strategies)`
- `renderStratPanel(account, strategies)` — builds right panel with two sections
- `assignStrategy(name, accountId)` — POST + re-render
- `removeStrategy(name, accountId)` — DELETE + re-render
- `toggleStrategy(name, accountId, enabled)` — PATCH + re-render row in-place

No modals needed for assign/remove — actions are instant and reversible.
Keep existing modals for: Run Engine Now confirm, Kill Switch ON/OFF confirm.

---

## Visual Style

Follows `mockup-bots-b.html` exactly:
- `--card: #131c2e`, `--border: #1e2d45`, `--blue: #3b82f6`, `--green: #16c784`
- 220px left panel, sticky
- Section labels: `10px uppercase muted` with subtle background
- Strategy icons: `30px` rounded square, purple tint for active, grey for inactive
- Status badge: `b-enabled` (green, pulsing dot) or `b-paused` (grey)
- Toggle: 36×20px pill, green when on

---

## Files Changed

| File | Change |
|---|---|
| `server/db.py` | Add `get_account_strategies(account_id)` |
| `server/main.py` | Add `GET /api/broker-accounts/{id}/strategies` endpoint |
| `server/static/bots.html` | Replace content area with two-panel layout |
| `server/static/app.js` | Rewrite `initBots()` |

---

## Out of Scope

- Global enable/disable toggle for a strategy (still accessible via current API but not exposed in new UI — the per-account toggle is the primary control)
- Strategy configuration / parameter editing
- Any other pages
