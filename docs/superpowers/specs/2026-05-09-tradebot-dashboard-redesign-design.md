# TradeBot Dashboard Redesign — Design Spec
**Date:** 2026-05-09  
**Status:** Approved with Conditions (QA v5 applied 2026-05-09)  
**Verified:** All Phase 1 endpoint fields verified against actual backend code on 2026-05-09.

---

## Overview

Redesign the existing TradeBot admin dashboard (`server/static/`) to match the NEXORA AI Trading visual style — dark glassmorphism cards, neon glow effects, professional sidebar navigation, and ApexCharts-powered charts. No new backend endpoints. No separate frontend framework. The existing FastAPI + alpaca-py backend is untouched; only the static HTML/CSS/JS files are replaced.

**Deployment context:** Personal local desktop use only. The dashboard is served through FastAPI static routes (`uvicorn server.main:app`). Opening HTML files directly via `file://` is not supported — relative `/api/...` calls will fail.

---

## Delivery Phases

### Phase 1 — UI Redesign (this spec)
All pages built and styled. Pages backed by confirmed existing endpoints are fully wired. Pages whose backend endpoints are not yet stable display a "Coming Soon" placeholder card with the page chrome intact.

### Phase 2 — Backend Completion (separate task, post-redesign)
- `backtesting.html` — new FastAPI endpoints required
- `risk.html` — `GET /api/risk` exists but the page is a **Coming Soon placeholder in Phase 1**. No read-only risk summary is implemented. Full settings PATCH UX is deferred to Phase 2.
- `settings.html` — `/api/notifications` needs schema confirmation

**Phase 1 pages (fully wired):** `index.html`, `bots.html`, `positions.html`, `performance.html`, `balances.html`, `logs.html`, `apikeys.html`, `login.html`

**Phase 1 pages (placeholder chrome):** `backtesting.html`, `risk.html`, `settings.html`

---

## Architecture

| Layer | Technology | Notes |
|---|---|---|
| Pages | Plain HTML files | One file per section, served by FastAPI static routes |
| Styling | Tailwind CSS (CDN) | Layout utilities; Play CDN — local prototype use only |
| Charts | ApexCharts (CDN) | Area charts, sparklines, donut, radial bar |
| Icons | Inline SVG | No external icon library; no emoji in UI |
| JavaScript | Vanilla JS (`app.js`) | All API calls use `textContent` for DOM injection; no `innerHTML` for API data |
| Font | Inter (Google Fonts CDN) | Loaded in `<head>` of every page; fallback `system-ui, sans-serif` |
| Backend | FastAPI (unchanged) | Serves `server/static/`; all existing `/api/...` endpoints remain |

### CDN Dependencies (intentionally unpinned — local prototype use)

| Library | CDN | Offline behavior |
|---|---|---|
| Tailwind CSS | `cdn.tailwindcss.com` (Play CDN) | Without Tailwind, visual polish degrades but critical layout must remain usable via `styles.css` fallback rules. The following MUST be defined in `styles.css` (not Tailwind-only): page shell (`body { display:flex }`), sidebar (`width:220px; flex-shrink:0; position:fixed; top:0; left:0; height:100vh`), main content margin (`margin-left:220px`), metric grid (`display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:1rem`), card base (background, border, border-radius, backdrop-filter), table base (`width:100%; table-layout:fixed; border-collapse:collapse`), overflow protection (`min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap` on constrained elements) |
| ApexCharts | `cdn.jsdelivr.net/npm/apexcharts` | Chart containers show "Chart unavailable" text |
| Google Fonts — Inter | `fonts.googleapis.com` | `font-family: system-ui, sans-serif` fallback in CSS |

CDN URLs are not version-pinned. Accepted risk for a personal local tool.

---

## Pages & File Structure

Each sidebar nav item is a separate HTML page. Navigation causes a full page reload (no SPA routing). Login is not in the sidebar.

**Sidebar nav items (10):** Dashboard, Bots & Strategies, Positions & Orders, Performance, Backtesting, Balances, Risk, Logs, API Keys, Settings

| File | Page | Phase | Endpoints |
|---|---|---|---|
| `index.html` | Dashboard Overview | 1 — wired | `/api/account`, `/api/clock`, `/api/positions`, `/api/orders`, `/api/portfolio_history`, `/api/performance`, `/api/signals` |
| `bots.html` | Bots & Strategies | 1 — wired | `/api/account`, `/api/clock`, `/api/risk` (GET — kill switch state), `/api/strategies`, `/api/engine` (GET), `/api/engine/run_now` (POST), `PATCH /api/strategies/{name}`, `POST /api/risk/kill_switch` |
| `positions.html` | Positions & Orders | 1 — wired | `/api/positions`, `/api/orders` |
| `performance.html` | Performance Analytics | 1 — wired | `/api/performance`, `/api/signals` |
| `backtesting.html` | Backtesting Studio | 1 — placeholder | New endpoints (Phase 2) |
| `balances.html` | Balances & Assets | 1 — wired | `/api/account`, `/api/positions` |
| `risk.html` | Risk Management | 1 — placeholder | Phase 2 |
| `logs.html` | Logs & Signals | 1 — wired | `/api/signals` only (`/api/logs` does not exist) |
| `apikeys.html` | API Keys | 1 — wired | `/api/account` (connection health only — see Security Rules) |
| `settings.html` | Settings | 1 — placeholder | Phase 2 |
| `login.html` | Login | 1 — wired | `/api/auth/login` (existing, restyled) |
| `styles.css` | Shared styles | — | Glow, glassmorphism, animations, color tokens, critical layout fallbacks |
| `app.js` | Shared JS | — | API fetch calls, page detection, per-page init |

---

## API Contracts (Phase 1 — all verified against backend code 2026-05-09)

### GET /api/account
Auth: `tb_session` cookie required.

| Field | Type | Notes |
|---|---|---|
| `status` | string | Alpaca account status |
| `cash` | float | Available cash |
| `equity` | float | Total account equity |
| `last_equity` | float | Previous close equity |
| `buying_power` | float | |
| `portfolio_value` | float | |
| `day_pl` | float | Day P&L in dollars (backend-computed) |
| `day_pl_pct` | float | Day P&L as decimal (0.05 = 5%) |
| `pattern_day_trader` | bool | |
| `trading_blocked` | bool | |
| `account_type` | string | `"paper"` or `"live"` |

### GET /api/clock
No auth required.

| Field | Type | Notes |
|---|---|---|
| `is_open` | bool | US equities regular market open |
| `next_open` | string | ISO timestamp |
| `next_close` | string | ISO timestamp |
| `timestamp` | string | Current server time ISO |

### GET /api/positions
Auth required. Returns array. Each item:

| Field | Type | Notes |
|---|---|---|
| `symbol` | string | |
| `qty` | float | |
| `side` | string | `"long"` or `"short"` |
| `avg_entry_price` | float | |
| `current_price` | float | |
| `market_value` | float | |
| `unrealized_pl` | float | |
| `unrealized_plpc` | float | As decimal |
| `change_today` | float | Intraday change as decimal |

### GET /api/orders
Auth required. Query params: `status` (default `"all"`, options `"open"`, `"closed"`), `limit` (default 50).
Returns array. Each item:

| Field | Type | Notes |
|---|---|---|
| `id` | string | |
| `symbol` | string | |
| `side` | string | `"buy"` or `"sell"` |
| `qty` | float\|null | |
| `filled_qty` | float | |
| `filled_avg_price` | float\|null | |
| `type` | string | e.g. `"market"` |
| `status` | string | `"filled"`, `"canceled"`, `"pending_new"`, etc. |
| `submitted_at` | string\|null | ISO timestamp |
| `filled_at` | string\|null | ISO timestamp |

**No per-trade realized P&L field.** Recent Trades table P&L column shows `—`.

### GET /api/signals
Auth required. Query param: `limit` (default 100). Returns array. Each item:

| Field | Type | Notes |
|---|---|---|
| `id` | int | |
| `ts` | string | ISO timestamp |
| `strategy` | string | Backend key e.g. `"momentum"` |
| `symbol` | string | |
| `side` | string | `"buy"` or `"sell"` — **not** a win/loss indicator |
| `qty` | float | |
| `reason` | string | |
| `order_id` | string\|null | |
| `status` | string | `"pending"`, `"blocked"`, `"error"`, `"filled"` |

### GET /api/strategies
No auth required. Returns array. Each item:

| Field | Type | Notes |
|---|---|---|
| `name` | string | Backend key e.g. `"momentum"` |
| `label` | string | Display name |
| `description` | string | |
| `enabled` | bool | Whether strategy is active |
| `params` | dict | Current parameter values |

### PATCH /api/strategies/{name}
Auth required. Request body:

| Field | Type | Notes |
|---|---|---|
| `enabled` | bool\|null | Enable or disable the strategy |
| `params` | dict\|null | Parameter overrides (merged with existing) |

Response: `{ name, enabled, params, updated_at }`.

### GET /api/engine
No auth required.

| Field | Type | Notes |
|---|---|---|
| `ts` | string\|null | ISO timestamp of last engine run |
| `ran` | array | `[{ strategy, error?, signals_count? }]` |
| `signals` | array | Signals from last run |
| `error` | string\|null | Engine-level error (e.g. `"kill switch active"`) |
| `risk` | dict\|null | Risk summary from last run |

### POST /api/engine/run_now
Auth required. Same response structure as GET /api/engine.

### POST /api/risk/kill_switch
Auth required. Request body: `{ "on": bool }` (defaults to `true` if omitted).  
Response: `{ "kill_switch": bool }`.

### GET /api/performance
Auth required.

| Field | Type | Notes |
|---|---|---|
| `strategy_stats` | array | `{ strategy, total, buys, sells, blocked, errors, unique_symbols, first_signal, last_signal }` |
| `top_symbols` | array | `{ symbol, total, buys, sells, strategies }` |
| `daily_counts` | array | 30-day history: `{ date, total, buys, sells }` |
| `open_positions` | int | |
| `total_unrealized_pl` | float | Sum of unrealized P&L across all open positions |
| `unique_symbols` | int | |

### GET /api/portfolio_history
Auth required. Query params: `period` (default `"1M"`), `timeframe` (default `"1D"`).  
Returns raw Alpaca portfolio history response:

| Field | Type | Notes |
|---|---|---|
| `timestamp` | array of int | Unix epoch seconds |
| `equity` | array of float | Equity value at each timestamp |
| `profit_loss` | array of float | Absolute P&L at each timestamp |
| `profit_loss_pct` | array of float | Percentage P&L at each timestamp |
| `base_value` | float | Starting equity for the period |
| `timeframe` | string | Timeframe confirmed by Alpaca |

**Range tab → API params mapping:**

| Tab | `period` | `timeframe` | Notes |
|---|---|---|---|
| 1H | `1D` | `5Min` | |
| 24H | `1D` | `1H` | |
| 7D | `1W` | `1D` | |
| 30D | `1M` | `1D` | |
| YTD | `1A` | `1D` | |
| 6Y | `6A` | `1D` | Not labeled "All" — this is a 6-year window, not true account history |

Each tab triggers a fresh API call with the matching params. For new accounts with less than the selected window of history, Alpaca returns whatever data exists — fewer than 2 points shows "Not enough data for this range."

### /api/logs
**Does not exist.** `logs.html` uses `/api/signals` only.

---

## Visual Design System

### Color Tokens

| Token | Hex | Usage |
|---|---|---|
| Background | `#080D14` | Page background |
| Card surface | `rgba(17,24,39,0.82)` | All card backgrounds |
| Card border | `#1E2D45` | Card outlines, table dividers |
| Sidebar | `#0D1117` | Left nav panel |
| Blue accent | `#3B82F6` | Active nav, primary buttons, chart lines |
| Neon green | `#10B981` | Positive P&L, Enabled status, Buy tags |
| Red | `#EF4444` | Negative P&L, Error status, Sell tags, Kill switch |
| Orange | `#F59E0B` | Warning states |
| Purple | `#8B5CF6` | Bot icons, Active bots metric |
| Indigo | `#6366F1` | Open positions metric |
| Cyan | `#06B6D4` | Fill rate metric |
| Text primary | `#E6EBF5` | Main text |
| Text muted | `#64748B` | Labels, secondary info, column headers |

### Glow Effects (applied via `styles.css`)

| Element | CSS rule |
|---|---|
| Positive P&L values | `text-shadow: 0 0 18px rgba(16,185,129,.55), 0 0 36px rgba(16,185,129,.18)` |
| Negative P&L values | `text-shadow: 0 0 18px rgba(239,68,68,.55), 0 0 36px rgba(239,68,68,.18)` |
| Enabled badge | `box-shadow: 0 0 10px rgba(16,185,129,.15)` + pulsing dot animation |
| Error badge | `box-shadow: 0 0 10px rgba(239,68,68,.15)` |
| Card on hover | `box-shadow: 0 0 0 1px rgba(59,130,246,.08), 0 8px 32px rgba(0,0,0,.5)` |
| Active nav item | Blue left border + `background: linear-gradient(90deg, rgba(59,130,246,.12), transparent)` |
| Icon circles | Colored background + matching color `box-shadow` glow |
| Toggle switch (on) | `box-shadow: 0 0 10px rgba(16,185,129,.35)` |
| Logo mark | `box-shadow: 0 0 20px rgba(59,130,246,.35)` |

### Glassmorphism Cards
```css
background: rgba(17, 24, 39, 0.82);
border: 1px solid #1E2D45;
border-radius: 14px;
backdrop-filter: blur(12px);
```

### Typography
- Font family: `Inter` via Google Fonts CDN; fallback `system-ui, sans-serif`
- Numbers: `font-variant-numeric: tabular-nums` on all financial values
- `white-space: nowrap; overflow: hidden; text-overflow: ellipsis` scoped to: nav labels, table cells, metric value labels, compact chips, card titles in fixed-width containers
- Allow text wrapping for: error banners, empty state messages, descriptive text, help text

---

## Shared Layout (every page)

### Sidebar (220px fixed, left)
- Logo mark: gradient blue→purple with glow
- Nav sections: Overview, Analysis, Portfolio, System
- 10 nav items with inline SVG icons (no emoji)
- Active item: blue left border + gradient background
- Bottom card: "Paper Trading Mode" notice with "Go Live →" button

### Header (sticky top)
- Page title + subtitle (left)
- Search bar (center, 240px width) — **decorative placeholder only**; no shortcut badge; styled as inactive input
- Notification bell with red count badge
- Market status chip — labeled **"US Equities"** + open/closed; reads `is_open` from `/api/clock`; if `/api/clock` fails, shows "Market status unavailable" chip (gray); **Enable** and **Run Engine Now** are disabled until clock data loads
- "Paper Mode" badge shown when `account.account_type === "paper"`
- User avatar (gradient) + name + online dot

**No theme toggle.** Dashboard is dark-only.

---

## Dashboard Overview — Section Detail (`index.html`)

### Row 1 — 6 Metric Cards
`grid-template-columns: repeat(6, minmax(0, 1fr))`

Each card: colored icon circle (inline SVG, with glow), label, large value, % change chip, ApexCharts sparkline (90px × 46px) labeled "Signal activity trend" — all sparklines use `performance.daily_counts` (last 7 entries, `total` field). Sparklines are visual decorators only; they do not represent the card's financial metric.

| Card | Icon color | Source | Formula | Glow |
|---|---|---|---|---|
| Total Balance | Blue | `/api/account` | `account.equity` | None |
| Daily P&L | Green/Red | `/api/account` | `account.day_pl` | Green if ≥ 0, Red if < 0 |
| Fill Rate | Cyan | `/api/signals` | `filled / (filled + blocked + error) × 100`; `—` if denominator = 0 | None |
| Active Bots | Purple | `/api/strategies` | count where `enabled === true` | None |
| Unrealized P&L | Orange/Red | `/api/performance` | `performance.total_unrealized_pl` | Green if ≥ 0, Red if < 0 |
| Open Positions | Indigo | `/api/performance` | `performance.open_positions` | None |

**Fallback:** display `—` if endpoint returns an error or field is missing. Never display `undefined`, `NaN`, or raw JS error strings.

**Refresh cadence:** all metric cards refresh every 30 seconds.

### Row 2 — Performance Chart + Bot Status
`grid-template-columns: 3fr 2fr`

**Performance chart:** ApexCharts area chart, 220px tall. Data source: `GET /api/portfolio_history` — use the `timestamp` array (convert Unix epoch to Date objects) and `equity` array. Blue glowing stroke, gradient fill fading to transparent. Dashed red baseline at `base_value`. Time-range tabs (**1H, 24H, 7D, 30D, YTD, 6Y**) each trigger a fresh API call with the matching `period`/`timeframe` params (see API contract table). The tab must be labeled "6Y" — not "All". If fewer than 2 points, show "Not enough data for this range."

**Bot Status panel:** Lists all strategies from `/api/strategies`. Each row: inline SVG colored icon circle, `strategy.label` (truncated with ellipsis), `strategy.description` (truncated), status badge. No P&L per strategy (not available).

**Status badge labels — derived from backend truth:**

| Badge | Label | Condition |
|---|---|---|
| Green + pulsing dot | **Enabled — Last Run OK** | `enabled: true` + strategy in `engine.ran` without `error` field |
| Red | **Last Run Error** | Strategy in `engine.ran` with `error` field present |
| Orange | **Enabled — Not Run Yet** | `enabled: true` + strategy not in `engine.ran` |
| Gray | **Disabled** | `enabled: false` |

Note: "Paused" is not a backend state and is not used.

### Row 3 — Allocation + P&L Breakdown + Recent Trades
`grid-template-columns: repeat(3, minmax(0, 1fr))`

**Allocation:** ApexCharts donut (155px). `/api/positions` — group by `symbol`, value = `market_value`. Empty: "No open positions."

**P&L Breakdown:** ApexCharts radialBar (160px, hollow 65%, font 17px). Ring = `account.day_pl_pct × 100` (convert decimal to percent). Below:
- Daily P&L: `account.day_pl` (green/red glow)
- Unrealized P&L: `performance.total_unrealized_pl` (green/red glow)
- Open Positions: `performance.open_positions`
- Fallback: `$0.00` if unavailable.

**Recent Trades:** `GET /api/orders?status=closed&limit=25` — filter client-side to `status === "filled"`, sort by `filled_at` descending, show top 5. Columns: Time (`filled_at`), Symbol, Side (Buy/Sell tag), Size (`filled_qty`), P&L (`—`). `table-layout: fixed`. Empty: "No recent trades."

### Row 4 — System Bar
Full-width. Items: Exchange connection (derived from successful `/api/account` response), API status, server time (`clock.timestamp` live), **Last Engine Run** (`engine.ts`), **API Response Time** (fetch duration in ms). Online dots with green glow. `flex-wrap: wrap`.

---

## app.js — Page Detection & Initialization

```html
<body data-page="index">
```

```js
const PAGE_INIT = {
  index: initDashboard,
  bots: initBots,
  positions: initPositions,
  performance: initPerformance,
  balances: initBalances,
  logs: initLogs,
  apikeys: initApiKeys,
  // login is excluded — it uses its own inline form-submit handler, not this pattern
};
document.addEventListener('DOMContentLoaded', () => {
  const page = document.body.dataset.page;
  if (PAGE_INIT[page]) PAGE_INIT[page]();
});
```

No DOM lookups for other pages. ApexCharts instances stored in module-level variables and destroyed (`chart.destroy()`) before re-render.

**login.html** is fully wired to `POST /api/auth/login` but does not participate in the `PAGE_INIT` pattern. It contains its own inline script: form submit → POST → redirect to `index.html` on success, display error message on 401.

---

## Metric Formula Matrix (all fields verified 2026-05-09)

| Metric | Endpoint | Field | Format | Fallback | Refresh |
|---|---|---|---|---|---|
| Total Balance | `/api/account` | `equity` | `$#,##0.00` | `—` | 30s |
| Daily P&L | `/api/account` | `day_pl` | `+$#,##0.00` / `-$#,##0.00` | `—` | 30s |
| Day P&L % (ring) | `/api/account` | `day_pl_pct × 100` | `+##.##%` | `0%` | 30s |
| Unrealized P&L | `/api/performance` | `total_unrealized_pl` | `$#,##0.00` | `$0.00` | 30s |
| Fill Rate | `/api/signals` | `filled / (filled + blocked + error) × 100` | `##.#%` | `—` | 60s |
| Active Bots | `/api/strategies` | count where `enabled === true` | integer | `0` | 30s |
| Open Positions | `/api/performance` | `open_positions` | integer | `0` | 30s |

---

## Error Handling & Retry Model

On any fetch failure:
1. Immediately render the error state for that panel.
2. Schedule a **single retry after 30 seconds**. While the retry is pending, **pause the normal polling interval** for that panel — the retry counts as the next tick. Resume the normal interval only after the retry completes (success or failure).
3. Use `AbortController` per fetch to cancel any in-flight request before starting a new one, preventing stale responses from overwriting newer data.
4. After the retry, resume normal polling regardless of result.
5. 401 → redirect to `login.html`. 500 → panel error state only; do not crash the page.

This ensures the retry and the normal 30-second poll never fire simultaneously for the same panel.

---

## State Rules (per panel)

| State | Behavior |
|---|---|
| Loading | Skeleton shimmer (pulsing gray bar, same dimensions as content) |
| Populated | Render normally |
| Empty | Centered muted text: e.g., "No positions", "No recent trades", "Not enough data" |
| Error | Muted red text: "Failed to load — retrying in 30s" |

Charts: if ApexCharts library fails to load, show "Chart unavailable" in the container.

---

## Security Rules

- **All API-provided text is injected via `textContent`.** `innerHTML` is allowed only for inline SVG icons hardcoded in JS.
- **API Keys page:** shows connection status (successful `/api/account` response = connected), `account_type` (paper/live), and last successful fetch timestamp. No API key or secret is displayed.
- **Unauthenticated endpoints** (`/api/clock`, `/api/strategies`, `/api/engine`) are acceptable for local personal use. Explicitly accepted as a local-only risk.
- **No `eval`, no dynamic `<script>` injection, no `document.write`.**
- **401** → redirect to `login.html`. **500** → panel error state only.

---

## Trading Controls — bots.html

All control actions require `tb_session` auth cookie. The page fetches `/api/account` on load to determine paper/live mode.

### Controls and Endpoint Mapping

| Action | Endpoint | Request body | Notes |
|---|---|---|---|
| Enable strategy | `PATCH /api/strategies/{name}` | `{"enabled": true}` | |
| Disable strategy | `PATCH /api/strategies/{name}` | `{"enabled": false}` | |
| Run Engine Now | `POST /api/engine/run_now` | none | Triggers one full engine tick; may generate and place orders |
| Kill Switch ON | `POST /api/risk/kill_switch` | `{"on": true}` | Blocks all future engine ticks |
| Kill Switch OFF | `POST /api/risk/kill_switch` | `{"on": false}` | Re-enables engine — requires confirmation |

**Button labels:** "Enable" / "Disable" (not Start/Stop — matches actual backend state).

### Kill Switch — State Source of Truth

**On page load:** read initial kill switch state from `GET /api/risk` → `risk.kill_switch` (bool). This is the authoritative source — it always reflects the current persisted value, regardless of whether the engine has ever run. `GET /api/engine` is **not** used for kill switch state on page load because `engine.risk` may be `null` if the engine has never ticked.

While `GET /api/risk` is in flight, kill switch state is **Unknown**. During Unknown state:
- **Run Engine Now** is disabled. Tooltip: "Checking kill switch status…"
- Kill Switch ON/OFF buttons render as disabled.
- No red banner is shown yet.

If `GET /api/risk` fails, keep state as Unknown and show an inline error: "Could not load risk status."

**After `POST /api/risk/kill_switch`:** the UI must immediately update from the POST response `{ kill_switch: bool }` — do not wait for a `/api/risk` or `/api/engine` refresh. After applying the POST response, optionally refresh `/api/engine` in the background to sync the full engine state.

When `kill_switch === true`:
- Show a persistent, non-dismissible **red banner** at the top of `bots.html`: "Kill Switch Active — engine ticks are blocked."
- **Run Engine Now** button is disabled. Tooltip: "Kill switch is active."
- **Kill Switch OFF** button is shown as primary action; Kill Switch ON is hidden.
- Banner, button states, and ON/OFF visibility update immediately from the POST response — not on next poll.

When `kill_switch === false`:
- No red banner.
- **Kill Switch ON** button visible.

### Run Engine Now — Safety Rules

**Disabled when any of the following is true:**
- `/api/clock` has not yet loaded (clock data pending)
- `clock.is_open === false` (market is closed)
- `engine.risk.kill_switch === true` (kill switch is active)

**Confirmation modal content:**
- Title: "Run Engine Now"
- Mode line: "Account mode: **Paper Trading**" or "Account mode: **Live Trading**" (from `account.account_type`)
- Warning: "This will run one full engine tick. Enabled strategies may generate and place orders."
- Buttons: Cancel | Run Now

**After `POST /api/engine/run_now` completes:**
- Display a result summary panel (inline, below the button, not a modal):
  - Strategies evaluated: count from `engine.ran`
  - Signals generated: `engine.signals.length`
  - Strategy errors: list of `{ strategy, error }` from `engine.ran` where `error` is present
  - Engine-level error (if any): `engine.error`
- Panel auto-dismisses after 10 seconds or on next user action.

### Enable / Disable / Kill Switch — Safety Behaviors

- Persistent **"Paper Trading Mode"** banner when `account.account_type === "paper"`. Not dismissible.
- If `/api/account` fails: banner shows "Trading mode unknown"; **Enable and Run Engine Now** are disabled until account loads.
- **Enable** button: disabled when `clock.is_open === false`. Tooltip: "Market is closed."
- If `/api/clock` fails: Enable and Run Engine Now default to disabled; chip shows "Market status unavailable."
- **Disable** always enabled (safety control).
- **Kill Switch ON:** requires confirmation — "This will block ALL engine ticks. Confirm?"
- **Kill Switch OFF:** requires confirmation — "This will re-enable future engine execution. Confirm?"
- While any action is in flight: button disabled + spinner. On error: button re-enables + "Action failed — check logs."

### Modal Accessibility (minimum, non-WCAG)
- `role="dialog"`, `aria-modal="true"`, `aria-labelledby` pointing to modal title element
- Focus trap inside modal while open
- Escape key = Cancel (closes modal, no action taken)
- Enter key = confirms only when the Confirm button has focus
- On close: focus returns to the button that opened the modal
- Visible focus ring on all buttons and links

---

## Overflow & Text Rules

- All grid children have `min-width: 0`
- Nowrap + ellipsis scoped to: nav labels, table cells, metric value labels, compact chips, card titles in fixed-width containers
- Tables use `table-layout: fixed`
- System bar uses `flex-wrap: wrap`
- Search bar wrapped in `<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;">`
- Error banners, empty state messages, and descriptive text allow wrapping

---

## Viewport

**Minimum supported:** 1440 × 900 at 100% browser zoom, Chrome or Edge (latest stable). No mobile support.

---

## Strategies (existing backend — display names)

| Display name | Backend key | Initial `enabled` state |
|---|---|---|
| Momentum | `momentum` | true |
| RSI Mean Reversion | `rsi_mr` | true |
| Golden Cross | `golden_cross` | true |
| Bollinger Bands | `bollinger_bands` | true |
| MACD | `macd_v` | false |
| Breakout | `breakout` | false |
| SMA Crossover | `sma_cr` | false |
| Manual | `manual` | false |

Bot Status rows use **colored inline SVG icon circles** — no emoji.

---

## Verification Reference

All Phase 1 endpoint schemas were verified by reading actual backend source files on 2026-05-09. Verification is by code inspection, not live API response capture.

| Backend file | Endpoints verified |
|---|---|
| `server/main.py` | `/api/account`, `/api/clock`, `/api/positions`, `/api/orders`, `/api/signals`, `/api/strategies`, `PATCH /api/strategies/{name}`, `/api/engine` (GET), `/api/engine/run_now` (POST), `/api/performance`, `/api/portfolio_history`, `/api/risk/kill_switch` (POST) |
| `server/risk.py` | `risk.status_summary()` response shape, `set_kill_switch()`, `is_killed()` |
| `server/engine.py` | Engine tick kill-switch check, `_last_run` structure (`ts`, `ran`, `signals`, `error`, `risk`) |
| `server/alpaca_client.py` | `get_portfolio_history()` — confirmed raw Alpaca response passthrough |

**Fields marked as assumptions (not verified from live response):**
- Alpaca portfolio history response shape (`timestamp`, `equity`, `profit_loss`, `profit_loss_pct`, `base_value`, `timeframe`) — based on Alpaca API documentation, not a captured backend response.
- `/api/portfolio_history` `period="6A"` and `period="1A"` support — Alpaca documents these but they have not been tested against the paper account.

---

## Out of Scope

- Marketplace, billing, multi-user auth
- Backtesting backend endpoints (Phase 2)
- Risk settings PATCH UI and notification settings (Phase 2)
- React, Node.js, npm, or any build tooling
- Mobile responsive design
- Light theme
- Per-trade realized P&L (requires backend enhancement)
- `/api/logs` raw log streaming (endpoint does not exist)
- WCAG accessibility audit, CSP headers, SRI hashes — accepted constraints for personal local tool
- Production CDN hardening (version pinning, vendoring)
- True server uptime (no health/uptime endpoint exists; System Bar shows "Last Engine Run" instead)
- Exchange latency (System Bar shows "API Response Time" — frontend fetch duration only)
