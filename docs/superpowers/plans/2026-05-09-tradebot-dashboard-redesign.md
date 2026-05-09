# TradeBot Dashboard Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all files in `server/static/` with a NEXORA-style dark glassmorphism dashboard — 11 HTML pages, shared CSS, and shared JS — wired to the existing FastAPI backend with no backend changes.

**Architecture:** Plain HTML pages served by FastAPI static routes; one file per page, full-page reload on navigation. `styles.css` defines all design tokens, glassmorphism, glow effects, animations, and critical layout fallbacks. `app.js` holds all API calls, shared utilities, chart helpers, and per-page init functions dispatched via `body[data-page]`. No build step, no npm.

**Tech Stack:** HTML5, Tailwind CSS (Play CDN), ApexCharts (CDN), Vanilla JS ES2020, Google Fonts Inter, FastAPI static files.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `server/static/styles.css` | Rewrite | Design tokens, glassmorphism, glow, animations, critical layout |
| `server/static/app.js` | Rewrite | Utilities, API wrapper, pollers, chart helpers, page init dispatcher |
| `server/static/login.html` | Rewrite | Standalone login page (no sidebar) |
| `server/static/index.html` | Rewrite | Dashboard overview — 4-row layout |
| `server/static/bots.html` | Create | Bots & Strategies with trading controls |
| `server/static/positions.html` | Create | Positions & Orders tables |
| `server/static/performance.html` | Create | Performance Analytics |
| `server/static/balances.html` | Create | Balances & Assets |
| `server/static/logs.html` | Create | Logs & Signals (signals only) |
| `server/static/apikeys.html` | Create | API Keys connection health |
| `server/static/backtesting.html` | Create | Coming Soon placeholder |
| `server/static/risk.html` | Create | Coming Soon placeholder |
| `server/static/settings.html` | Create | Coming Soon placeholder |

---

## Task 1: styles.css — Complete Shared Stylesheet

**Files:**
- Rewrite: `server/static/styles.css`

- [ ] **Step 1: Write styles.css**

```css
/* ── Fonts ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ── Design tokens ── */
:root {
  --bg:        #080D14;
  --card:      rgba(17,24,39,0.82);
  --border:    #1E2D45;
  --sidebar:   #0D1117;
  --blue:      #3B82F6;
  --green:     #10B981;
  --red:       #EF4444;
  --orange:    #F59E0B;
  --purple:    #8B5CF6;
  --indigo:    #6366F1;
  --cyan:      #06B6D4;
  --text:      #E6EBF5;
  --muted:     #64748B;
}

/* ── Reset & base ── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
body {
  font-family: 'Inter', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
  /* CRITICAL LAYOUT FALLBACK — must not be Tailwind-only */
  display: flex;
}
a { text-decoration: none; color: inherit; }
button { cursor: pointer; font-family: inherit; }

/* ── Critical layout fallbacks (also defined via Tailwind utilities) ── */
.sidebar {
  width: 220px;
  flex-shrink: 0;
  position: fixed;
  top: 0; left: 0;
  height: 100vh;
  background: var(--sidebar);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  z-index: 40;
  overflow-y: auto;
}
.main {
  margin-left: 220px;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}
.content { flex: 1; padding: 1.5rem; }

/* Metric grid */
.metric-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 1rem;
}
/* Generic two-column row */
.row-2col { display: grid; gap: 1rem; }
/* Three-column row */
.row-3col { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; }

/* ── Glassmorphism card ── */
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  backdrop-filter: blur(12px);
  padding: 1.25rem;
  transition: box-shadow .2s;
  min-width: 0;
}
.card:hover {
  box-shadow: 0 0 0 1px rgba(59,130,246,.08), 0 8px 32px rgba(0,0,0,.5);
}

/* ── Glow utilities ── */
.glow-green { text-shadow: 0 0 18px rgba(16,185,129,.55), 0 0 36px rgba(16,185,129,.18); }
.glow-red   { text-shadow: 0 0 18px rgba(239,68,68,.55),  0 0 36px rgba(239,68,68,.18);  }
.glow-blue  { text-shadow: 0 0 18px rgba(59,130,246,.55), 0 0 36px rgba(59,130,246,.18); }

/* ── Icon circle ── */
.icon-circle {
  width: 36px; height: 36px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.icon-blue   { background: rgba(59,130,246,.15);  box-shadow: 0 0 12px rgba(59,130,246,.25); }
.icon-green  { background: rgba(16,185,129,.15);  box-shadow: 0 0 12px rgba(16,185,129,.25); }
.icon-cyan   { background: rgba(6,182,212,.15);   box-shadow: 0 0 12px rgba(6,182,212,.25);  }
.icon-purple { background: rgba(139,92,246,.15);  box-shadow: 0 0 12px rgba(139,92,246,.25); }
.icon-orange { background: rgba(245,158,11,.15);  box-shadow: 0 0 12px rgba(245,158,11,.25); }
.icon-indigo { background: rgba(99,102,241,.15);  box-shadow: 0 0 12px rgba(99,102,241,.25); }
.icon-red    { background: rgba(239,68,68,.15);   box-shadow: 0 0 12px rgba(239,68,68,.25);  }

/* ── Badges ── */
.badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px; font-weight: 500;
  white-space: nowrap;
}
.b-enabled  { background: rgba(16,185,129,.15); color: var(--green); box-shadow: 0 0 10px rgba(16,185,129,.15); }
.b-disabled { background: rgba(100,116,139,.12); color: var(--muted); }
.b-error    { background: rgba(239,68,68,.15);   color: var(--red);   box-shadow: 0 0 10px rgba(239,68,68,.15); }
.b-notrun   { background: rgba(245,158,11,.12);  color: var(--orange); }
.b-buy      { background: rgba(16,185,129,.15);  color: var(--green); padding: 1px 6px; border-radius: 4px; }
.b-sell     { background: rgba(239,68,68,.15);   color: var(--red);   padding: 1px 6px; border-radius: 4px; }

/* Pulsing dot (for enabled badge) */
.pdot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--green);
  animation: pdot 1.5s ease-in-out infinite;
}
@keyframes pdot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: .4; transform: scale(.7); }
}

/* ── Skeleton shimmer ── */
.skeleton {
  background: linear-gradient(90deg, var(--border) 25%, rgba(30,45,69,.6) 50%, var(--border) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s ease infinite;
  border-radius: 6px;
  height: 1.2em;
  width: 100%;
}
@keyframes shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }

/* ── Text utilities ── */
.text-muted   { color: var(--muted); }
.text-error   { color: var(--red); }
.text-green   { color: var(--green); }
.text-tabular { font-variant-numeric: tabular-nums; }

/* ── Overflow protection ── */
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }

/* ── Sidebar nav ── */
.logo {
  display: flex; align-items: center; gap: 10px;
  padding: 1.25rem 1rem;
  border-bottom: 1px solid var(--border);
}
.logo-mark {
  width: 32px; height: 32px;
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 0 20px rgba(59,130,246,.35);
}
.logo-text { font-size: 15px; font-weight: 700; letter-spacing: -.3px; }
.nav { flex: 1; padding: .75rem 0; overflow-y: auto; }
.nav-section {
  font-size: 10px; font-weight: 600; letter-spacing: .08em;
  color: var(--muted); text-transform: uppercase;
  padding: .75rem 1rem .25rem;
}
.nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: .5rem 1rem;
  border-left: 3px solid transparent;
  color: var(--muted);
  font-size: 13px; font-weight: 500;
  transition: color .15s, background .15s;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.nav-item svg { flex-shrink: 0; }
.nav-item:hover { color: var(--text); background: rgba(255,255,255,.04); }
.nav-item.active {
  color: var(--blue);
  border-left-color: var(--blue);
  background: linear-gradient(90deg, rgba(59,130,246,.12), transparent);
}
.sidebar-footer { padding: 1rem; border-top: 1px solid var(--border); }
.paper-card {
  background: rgba(59,130,246,.08);
  border: 1px solid rgba(59,130,246,.2);
  border-radius: 10px;
  padding: .75rem;
}
.paper-label { font-size: 11px; color: var(--muted); margin-bottom: 4px; }
.go-live {
  font-size: 12px; font-weight: 600; color: var(--blue);
  display: block; margin-top: 4px;
}

/* ── Header ── */
.page-header {
  position: sticky; top: 0; z-index: 30;
  background: rgba(8,13,20,.9);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  padding: .75rem 1.5rem;
  display: flex; align-items: center; gap: 1rem;
  min-width: 0;
}
.page-header .title-wrap { min-width: 0; }
.page-header .page-title { font-size: 17px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.page-header .page-sub   { font-size: 12px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.search-bar {
  display: flex; align-items: center; gap: 8px;
  background: rgba(30,45,69,.5);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 12px;
  width: 240px; flex-shrink: 0;
  pointer-events: none; opacity: .6;
}
.search-text { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 13px; color: var(--muted); }
.market-chip {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px; font-weight: 500;
  border: 1px solid var(--border);
  white-space: nowrap;
}
.market-chip.open   { color: var(--green); border-color: rgba(16,185,129,.3); background: rgba(16,185,129,.08); }
.market-chip.closed { color: var(--muted); }
.market-chip.unknown { color: var(--orange); border-color: rgba(245,158,11,.3); }
.online-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 6px rgba(16,185,129,.5);
}
.avatar {
  width: 30px; height: 30px; border-radius: 50%;
  background: linear-gradient(135deg, var(--blue), var(--purple));
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; flex-shrink: 0;
}
.plan-badge {
  font-size: 10px; font-weight: 600; padding: 2px 7px;
  border-radius: 4px; background: rgba(59,130,246,.15); color: var(--blue);
  white-space: nowrap;
}
.bell-wrap { position: relative; }
.bell-badge {
  position: absolute; top: -4px; right: -4px;
  background: var(--red); color: #fff;
  font-size: 9px; font-weight: 700;
  width: 14px; height: 14px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
}

/* ── Banner ── */
.banner {
  padding: .6rem 1.25rem;
  font-size: 13px; font-weight: 500;
  display: flex; align-items: center; gap: 8px;
}
.banner-paper { background: rgba(59,130,246,.1); border-bottom: 1px solid rgba(59,130,246,.2); color: var(--blue); }
.banner-kill  { background: rgba(239,68,68,.12);  border-bottom: 1px solid rgba(239,68,68,.25);  color: var(--red); }
.banner-warn  { background: rgba(245,158,11,.1);  border-bottom: 1px solid rgba(245,158,11,.2);  color: var(--orange); }

/* ── Table ── */
.dtable {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
}
.dtable th {
  font-size: 11px; font-weight: 600; color: var(--muted);
  text-transform: uppercase; letter-spacing: .06em;
  padding: .5rem .75rem;
  text-align: left;
  border-bottom: 1px solid var(--border);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.dtable td {
  padding: .6rem .75rem;
  font-size: 13px;
  border-bottom: 1px solid rgba(30,45,69,.5);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.dtable tr:last-child td { border-bottom: none; }
.dtable tr:hover td { background: rgba(59,130,246,.04); }

/* ── System bar ── */
.sys-bar {
  display: flex; flex-wrap: wrap; gap: .75rem;
  padding: .75rem 1.5rem;
  border-top: 1px solid var(--border);
  background: rgba(13,17,23,.6);
  font-size: 12px; color: var(--muted);
}
.sys-item { display: flex; align-items: center; gap: 6px; }
.sys-dot  { width: 6px; height: 6px; border-radius: 50%; background: var(--green); box-shadow: 0 0 6px rgba(16,185,129,.5); }
.sys-dot.off { background: var(--red); box-shadow: 0 0 6px rgba(239,68,68,.4); }

/* ── Range tabs ── */
.range-tabs { display: flex; gap: 2px; }
.range-tab {
  padding: 3px 10px; font-size: 11px; font-weight: 500;
  border-radius: 6px; border: none;
  background: transparent; color: var(--muted);
  cursor: pointer; transition: background .15s, color .15s;
}
.range-tab:hover   { background: rgba(59,130,246,.1); color: var(--blue); }
.range-tab.active  { background: rgba(59,130,246,.15); color: var(--blue); }

/* ── Modal ── */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,.6); backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  z-index: 50;
}
.modal-overlay.hidden { display: none; }
.modal-box {
  background: #0F1623;
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 1.5rem;
  width: 420px; max-width: 90vw;
}
.modal-title { font-size: 16px; font-weight: 700; margin-bottom: .5rem; }
.modal-body  { font-size: 13px; color: var(--muted); line-height: 1.6; margin-bottom: 1.25rem; }
.modal-body strong { color: var(--text); }
.modal-actions { display: flex; gap: .75rem; justify-content: flex-end; }

/* ── Buttons ── */
.btn {
  padding: 7px 16px; border-radius: 8px;
  font-size: 13px; font-weight: 600; border: none;
  cursor: pointer; transition: opacity .15s, box-shadow .15s;
  display: inline-flex; align-items: center; gap: 6px;
  white-space: nowrap;
}
.btn:disabled { opacity: .45; cursor: not-allowed; }
.btn-primary  { background: var(--blue);  color: #fff; }
.btn-danger   { background: var(--red);   color: #fff; }
.btn-ghost    { background: rgba(255,255,255,.07); color: var(--text); }
.btn-sm       { padding: 4px 10px; font-size: 12px; border-radius: 6px; }
.btn:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }

/* ── Result summary panel ── */
.result-panel {
  background: rgba(16,185,129,.08);
  border: 1px solid rgba(16,185,129,.2);
  border-radius: 10px; padding: .75rem 1rem;
  font-size: 12px; margin-top: .75rem;
}
.result-panel.error { background: rgba(239,68,68,.08); border-color: rgba(239,68,68,.2); }

/* ── Chart unavailable fallback ── */
.chart-unavailable {
  display: flex; align-items: center; justify-content: center;
  height: 100%; min-height: 80px;
  color: var(--muted); font-size: 12px;
}

/* ── Empty / error states ── */
.state-empty { text-align: center; padding: 2rem 1rem; color: var(--muted); font-size: 13px; }
.state-error { text-align: center; padding: 1rem; color: var(--red); font-size: 12px; }

/* ── Login page ── */
.login-wrap {
  min-height: 100vh; display: flex;
  align-items: center; justify-content: center;
  background: var(--bg);
}
.login-card { width: 380px; }

/* ── Placeholder page ── */
.placeholder-wrap {
  display: flex; align-items: center; justify-content: center;
  min-height: 300px; flex-direction: column; gap: .75rem;
  color: var(--muted);
}
```

- [ ] **Step 2: Verify file was written**

```powershell
Get-Item server\static\styles.css | Select-Object Length
```
Expected: file exists, Length > 3000.

- [ ] **Step 3: Commit**

```powershell
git add server/static/styles.css
git commit -m "feat: add shared NEXORA dashboard stylesheet"
```

---

## Task 2: app.js — Core Utilities and Page Dispatcher

**Files:**
- Rewrite: `server/static/app.js`

- [ ] **Step 1: Write app.js (core utilities — no page init functions yet)**

```js
/* ─────────────────────────────────────────
   TradeBot Dashboard — app.js
   All page-specific init functions follow
   the core utilities section.
───────────────────────────────────────── */

// ── AbortController registry ──
const _acs = {};
function _abort(key) {
  if (_acs[key]) { _acs[key].abort(); }
  _acs[key] = new AbortController();
  return _acs[key].signal;
}

// ── API fetch wrapper ──
// Throws on non-2xx. Redirects to login on 401.
async function api(path, opts = {}) {
  const signal = _abort(opts.key || path);
  const res = await fetch(path, { ...opts, signal });
  if (res.status === 401) { location.href = '/static/login.html'; throw new Error('unauthorized'); }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Formatters ──
const fmt = {
  // $1,234.56 (no sign)
  usd(v, fallback = '—') {
    if (v == null || isNaN(v)) return fallback;
    return '$' + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  },
  // +$1,234.56 or -$1,234.56 with sign
  usdSigned(v, fallback = '—') {
    if (v == null || isNaN(v)) return fallback;
    const abs = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (v < 0 ? '-$' : '+$') + abs;
  },
  // +12.34% (from decimal: 0.05 → 5.00%)
  pctDecimal(v, fallback = '—') {
    if (v == null || isNaN(v)) return fallback;
    const p = (v * 100).toFixed(2);
    return (v >= 0 ? '+' : '') + p + '%';
  },
  // +12.34% (already a percentage value)
  pct(v, fallback = '—') {
    if (v == null || isNaN(v)) return fallback;
    return (v >= 0 ? '+' : '') + Number(v).toFixed(1) + '%';
  },
  integer(v, fallback = '0') {
    if (v == null || isNaN(v)) return fallback;
    return String(Math.round(v));
  },
  // "May 9, 10:32 AM"
  time(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  }
};

// ── DOM state helpers ──
function showLoading(el) {
  el.innerHTML = '<div class="skeleton" style="height:1.2em;border-radius:4px;"></div>';
}
function showError(el, msg = 'Failed to load — retrying in 30s') {
  el.innerHTML = '';
  el.textContent = msg;
  el.classList.add('state-error');
}
function showEmpty(el, msg) {
  el.innerHTML = '';
  el.textContent = msg;
  el.classList.add('state-empty');
}
function clearState(el) {
  el.classList.remove('state-error', 'state-empty');
}

// ── Poller ──
// fn: async function that fetches and renders one panel.
//     fn must re-throw on error so poller can manage retry timing.
// intervalMs: normal polling interval.
// On failure: immediately show error (fn's job), pause interval,
//             retry once after 30s, then resume normal interval.
function createPoller(fn, intervalMs) {
  let intervalId = null;
  let retryId = null;
  let isRetrying = false;

  async function tick() {
    if (isRetrying) return;
    try {
      await fn();
    } catch (err) {
      if (err.name === 'AbortError') return;
      isRetrying = true;
      retryId = setTimeout(async () => {
        isRetrying = false;
        retryId = null;
        try { await fn(); } catch (_) { /* retry done, resume polling regardless */ }
      }, 30_000);
    }
  }

  return {
    start() { tick(); intervalId = setInterval(tick, intervalMs); },
    stop()  { clearInterval(intervalId); clearTimeout(retryId); isRetrying = false; }
  };
}

// ── Active nav ──
function setActiveNav() {
  const page = document.body.dataset.page;
  document.querySelectorAll('.nav-item[data-page]').forEach(a => {
    a.classList.toggle('active', a.dataset.page === page);
  });
}

// ── Clock chip ──
async function initClockChip(chipEl) {
  try {
    const clock = await api('/api/clock', { key: 'clock' });
    chipEl.textContent = 'US Equities ' + (clock.is_open ? 'Open' : 'Closed');
    chipEl.className = 'market-chip ' + (clock.is_open ? 'open' : 'closed');
    return clock;
  } catch {
    chipEl.textContent = 'Market status unavailable';
    chipEl.className = 'market-chip unknown';
    return null;
  }
}

// ── Modal helpers ──
let _modalTrigger = null;

function openModal(overlayEl, onConfirm) {
  _modalTrigger = document.activeElement;
  overlayEl.classList.remove('hidden');
  // Focus the cancel button by default so Enter doesn't accidentally confirm
  const cancelBtn = overlayEl.querySelector('[data-action="cancel"]');
  if (cancelBtn) cancelBtn.focus();

  function handleKey(e) {
    if (e.key === 'Escape') { closeModal(overlayEl); cleanup(); }
  }
  function handleClick(e) {
    const action = e.target.closest('[data-action]')?.dataset.action;
    if (action === 'cancel') { closeModal(overlayEl); cleanup(); }
    if (action === 'confirm') { closeModal(overlayEl); cleanup(); onConfirm(); }
  }
  function cleanup() {
    overlayEl.removeEventListener('keydown', handleKey);
    overlayEl.removeEventListener('click', handleClick);
  }
  overlayEl.addEventListener('keydown', handleKey);
  overlayEl.addEventListener('click', handleClick);
  // Focus trap
  overlayEl.addEventListener('keydown', function trap(e) {
    if (e.key !== 'Tab') return;
    const focusable = [...overlayEl.querySelectorAll('button, [tabindex="0"]')];
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
}

function closeModal(overlayEl) {
  overlayEl.classList.add('hidden');
  if (_modalTrigger) { _modalTrigger.focus(); _modalTrigger = null; }
}

// ── ApexCharts helpers ──
// Returns a new ApexCharts instance or null if library unavailable.
function safeMakeChart(el, options) {
  if (typeof ApexCharts === 'undefined') {
    el.innerHTML = '<div class="chart-unavailable">Chart unavailable</div>';
    return null;
  }
  const chart = new ApexCharts(el, options);
  chart.render();
  return chart;
}

function sparkConfig(data) {
  return {
    series: [{ data: data.length ? data : [0] }],
    chart: { type: 'area', height: 46, width: 90, sparkline: { enabled: true } },
    stroke: { curve: 'smooth', width: 1.5, colors: ['#3B82F6'] },
    fill: { type: 'gradient', gradient: { shade: 'dark', opacityFrom: 0.35, opacityTo: 0 } },
    colors: ['#3B82F6'],
    tooltip: { enabled: false }
  };
}

function perfChartConfig(timestamps, equities, baseValue) {
  return {
    series: [{ name: 'Equity', data: timestamps.map((t, i) => ({ x: new Date(t * 1000), y: equities[i] })) }],
    chart: { type: 'area', height: 220, toolbar: { show: false }, background: 'transparent', animations: { enabled: false } },
    stroke: { curve: 'smooth', width: 2, colors: ['#3B82F6'] },
    fill: { type: 'gradient', gradient: { shade: 'dark', opacityFrom: 0.3, opacityTo: 0, stops: [0, 100] } },
    colors: ['#3B82F6'],
    annotations: { yaxis: [{ y: baseValue, borderColor: '#EF4444', strokeDashArray: 4, label: { text: 'Base', style: { color: '#EF4444', background: 'transparent' } } }] },
    xaxis: { type: 'datetime', labels: { style: { colors: '#64748B', fontSize: '11px' } }, axisBorder: { show: false }, axisTicks: { show: false } },
    yaxis: { labels: { style: { colors: '#64748B', fontSize: '11px' }, formatter: v => '$' + (v/1000).toFixed(0) + 'k' } },
    grid: { borderColor: '#1E2D45', strokeDashArray: 3 },
    theme: { mode: 'dark' },
    tooltip: { theme: 'dark', x: { format: 'MMM dd, yyyy' } }
  };
}

function donutConfig(labels, series) {
  return {
    series,
    labels,
    chart: { type: 'donut', height: 155, background: 'transparent' },
    colors: ['#3B82F6', '#10B981', '#8B5CF6', '#F59E0B', '#06B6D4', '#6366F1'],
    dataLabels: { enabled: false },
    legend: { position: 'bottom', labels: { colors: '#64748B' }, fontSize: '11px' },
    plotOptions: { pie: { donut: { size: '62%' } } },
    theme: { mode: 'dark' },
    tooltip: { theme: 'dark' }
  };
}

function radialConfig(pct, label) {
  return {
    series: [Math.min(Math.abs(pct), 100)],
    chart: { type: 'radialBar', height: 160, background: 'transparent' },
    plotOptions: { radialBar: {
      hollow: { size: '65%' },
      dataLabels: {
        name:  { fontSize: '11px', color: '#64748B', offsetY: -6 },
        value: { fontSize: '17px', color: '#E6EBF5', offsetY: 5,
                 formatter: () => (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%' }
      }
    }},
    colors: [pct >= 0 ? '#10B981' : '#EF4444'],
    labels: [label],
    theme: { mode: 'dark' }
  };
}

// ── Page dispatcher ──
const PAGE_INIT = {
  index:       initDashboard,
  bots:        initBots,
  positions:   initPositions,
  performance: initPerformance,
  balances:    initBalances,
  logs:        initLogs,
  apikeys:     initApiKeys,
  // login excluded — uses own inline script
};

document.addEventListener('DOMContentLoaded', () => {
  setActiveNav();
  const page = document.body.dataset.page;
  if (PAGE_INIT[page]) PAGE_INIT[page]();
});

// ─────────────────────────────────────────
// Page init functions are appended in Tasks 4–10
// ─────────────────────────────────────────
```

- [ ] **Step 2: Commit**

```powershell
git add server/static/app.js
git commit -m "feat: add shared app.js utilities, API wrapper, chart helpers, page dispatcher"
```

---

## Task 3: login.html — Standalone Auth Page

**Files:**
- Rewrite: `server/static/login.html`

- [ ] **Step 1: Write login.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Login — TradeBot</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body class="login-wrap">
  <div class="card login-card">
    <div class="flex items-center gap-3 mb-6">
      <div class="logo-mark icon-blue" style="width:40px;height:40px;border-radius:10px;">
        <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
          <path d="M11 2L20 7.5V14.5L11 20L2 14.5V7.5L11 2Z" fill="url(#lg1)"/>
          <defs><linearGradient id="lg1" x1="2" y1="2" x2="20" y2="20">
            <stop stop-color="#3B82F6"/><stop offset="1" stop-color="#8B5CF6"/>
          </linearGradient></defs>
        </svg>
      </div>
      <div>
        <div style="font-size:17px;font-weight:700;">TradeBot</div>
        <div class="text-muted" style="font-size:12px;">Admin Dashboard</div>
      </div>
    </div>

    <div id="login-error" class="state-error hidden mb-4" style="text-align:left;padding:.6rem .75rem;background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.25);border-radius:8px;"></div>

    <form id="login-form">
      <div class="mb-4">
        <label class="block text-muted mb-1" style="font-size:12px;font-weight:500;">Username</label>
        <input id="username" type="text" autocomplete="username" required
          class="w-full" style="background:rgba(30,45,69,.5);border:1px solid #1E2D45;border-radius:8px;padding:8px 12px;font-size:14px;color:#E6EBF5;outline:none;">
      </div>
      <div class="mb-6">
        <label class="block text-muted mb-1" style="font-size:12px;font-weight:500;">Password</label>
        <input id="password" type="password" autocomplete="current-password" required
          class="w-full" style="background:rgba(30,45,69,.5);border:1px solid #1E2D45;border-radius:8px;padding:8px 12px;font-size:14px;color:#E6EBF5;outline:none;">
      </div>
      <button type="submit" id="login-btn" class="btn btn-primary w-full" style="justify-content:center;">
        Sign In
      </button>
    </form>
  </div>

  <script>
    document.getElementById('login-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('login-btn');
      const errEl = document.getElementById('login-error');
      const username = document.getElementById('username').value;
      const password = document.getElementById('password').value;

      btn.disabled = true;
      btn.textContent = 'Signing in…';
      errEl.classList.add('hidden');
      errEl.textContent = '';

      try {
        const res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password })
        });
        if (res.ok) {
          location.href = '/static/index.html';
        } else {
          errEl.textContent = 'Invalid username or password.';
          errEl.classList.remove('hidden');
          btn.disabled = false;
          btn.textContent = 'Sign In';
        }
      } catch {
        errEl.textContent = 'Connection error — is the server running?';
        errEl.classList.remove('hidden');
        btn.disabled = false;
        btn.textContent = 'Sign In';
      }
    });
  </script>
</body>
</html>
```

- [ ] **Step 2: Start server and verify login page**

```powershell
uvicorn server.main:app --reload
```

Open `http://localhost:8000/static/login.html`.

Verify:
- Dark background (`#080D14`), centered card with glassmorphism border
- Logo mark visible with blue glow
- Username and password fields render correctly
- Submitting with wrong credentials: error message appears below logo, button re-enables
- Page does not crash, no console errors

- [ ] **Step 3: Commit**

```powershell
git add server/static/login.html
git commit -m "feat: add NEXORA-style login page"
```

---

## Task 4: index.html + initDashboard() — Dashboard Overview

**Files:**
- Rewrite: `server/static/index.html`
- Modify: `server/static/app.js` (append `initDashboard`)

**Sidebar HTML pattern** — used verbatim in every non-login page. Copy this sidebar into every subsequent page task, updating the `<title>` and `data-page` as noted.

- [ ] **Step 1: Write index.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dashboard — TradeBot</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/apexcharts"></script>
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body data-page="index">

<!-- ── Sidebar ── -->
<aside class="sidebar">
  <div class="logo">
    <div class="logo-mark icon-blue">
      <svg width="18" height="18" viewBox="0 0 22 22" fill="none">
        <path d="M11 2L20 7.5V14.5L11 20L2 14.5V7.5L11 2Z" fill="url(#lgs)"/>
        <defs><linearGradient id="lgs" x1="2" y1="2" x2="20" y2="20">
          <stop stop-color="#3B82F6"/><stop offset="1" stop-color="#8B5CF6"/>
        </linearGradient></defs>
      </svg>
    </div>
    <span class="logo-text">TradeBot</span>
  </div>

  <nav class="nav">
    <p class="nav-section">Overview</p>
    <a href="/static/index.html" class="nav-item" data-page="index">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
      Dashboard
    </a>
    <p class="nav-section">Analysis</p>
    <a href="/static/performance.html" class="nav-item" data-page="performance">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
      Performance
    </a>
    <a href="/static/backtesting.html" class="nav-item" data-page="backtesting">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
      Backtesting
    </a>
    <p class="nav-section">Portfolio</p>
    <a href="/static/positions.html" class="nav-item" data-page="positions">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
      Positions & Orders
    </a>
    <a href="/static/balances.html" class="nav-item" data-page="balances">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>
      Balances
    </a>
    <a href="/static/bots.html" class="nav-item" data-page="bots">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="2" height="2"/><rect x="13" y="9" width="2" height="2"/><path d="M9 13a3 3 0 0 0 6 0"/></svg>
      Bots & Strategies
    </a>
    <p class="nav-section">System</p>
    <a href="/static/risk.html" class="nav-item" data-page="risk">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
      Risk
    </a>
    <a href="/static/logs.html" class="nav-item" data-page="logs">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
      Logs & Signals
    </a>
    <a href="/static/apikeys.html" class="nav-item" data-page="apikeys">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
      API Keys
    </a>
    <a href="/static/settings.html" class="nav-item" data-page="settings">
      <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
      Settings
    </a>
  </nav>

  <div class="sidebar-footer">
    <div class="paper-card">
      <p class="paper-label">Paper Trading Mode</p>
      <p style="font-size:12px;color:#E6EBF5;margin-top:2px;">Safe sandbox environment</p>
      <a href="#" class="go-live">Go Live →</a>
    </div>
  </div>
</aside>

<!-- ── Main ── -->
<div class="main">

  <!-- Header -->
  <header class="page-header">
    <div class="title-wrap flex-1 min-w-0">
      <div class="page-title">Dashboard</div>
      <div class="page-sub">Overview of your trading activity</div>
    </div>
    <div class="search-bar">
      <svg width="14" height="14" fill="none" stroke="#64748B" stroke-width="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <span class="search-text">Search…</span>
    </div>
    <div class="bell-wrap">
      <svg width="18" height="18" fill="none" stroke="#64748B" stroke-width="1.8" viewBox="0 0 24 24"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
      <span class="bell-badge">3</span>
    </div>
    <div id="market-chip" class="market-chip">US Equities…</div>
    <span id="paper-badge" class="plan-badge hidden">Paper Mode</span>
    <div class="flex items-center gap-2">
      <div class="avatar">JR</div>
      <div class="hidden md:block">
        <div style="font-size:13px;font-weight:600;">Trader</div>
        <div class="text-muted" style="font-size:11px;">Admin</div>
      </div>
      <div class="online-dot"></div>
    </div>
  </header>

  <!-- Content -->
  <main class="content flex flex-col gap-4">

    <!-- Row 1: 6 Metric Cards -->
    <div class="metric-grid">

      <!-- Total Balance -->
      <div class="card">
        <div class="flex items-center gap-2 mb-2">
          <div class="icon-circle icon-blue">
            <svg width="14" height="14" fill="none" stroke="#3B82F6" stroke-width="2" viewBox="0 0 24 24"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>
          </div>
          <span class="text-muted truncate" style="font-size:12px;">Total Balance</span>
        </div>
        <div id="balance-val" class="text-tabular truncate" style="font-size:20px;font-weight:700;">—</div>
        <div id="balance-sub" class="text-muted truncate" style="font-size:11px;margin-top:2px;">Equity</div>
        <div id="spark-balance" style="margin-top:6px;"></div>
        <div class="text-muted" style="font-size:10px;margin-top:2px;">Signal activity trend</div>
      </div>

      <!-- Daily P&L -->
      <div class="card">
        <div class="flex items-center gap-2 mb-2">
          <div class="icon-circle icon-green">
            <svg width="14" height="14" fill="none" stroke="#10B981" stroke-width="2" viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/></svg>
          </div>
          <span class="text-muted truncate" style="font-size:12px;">Daily P&amp;L</span>
        </div>
        <div id="daypnl-val" class="text-tabular truncate" style="font-size:20px;font-weight:700;">—</div>
        <div id="daypnl-sub" class="text-muted truncate" style="font-size:11px;margin-top:2px;">Today</div>
        <div id="spark-daypnl" style="margin-top:6px;"></div>
        <div class="text-muted" style="font-size:10px;margin-top:2px;">Signal activity trend</div>
      </div>

      <!-- Fill Rate -->
      <div class="card">
        <div class="flex items-center gap-2 mb-2">
          <div class="icon-circle icon-cyan">
            <svg width="14" height="14" fill="none" stroke="#06B6D4" stroke-width="2" viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
          </div>
          <span class="text-muted truncate" style="font-size:12px;">Fill Rate</span>
        </div>
        <div id="fillrate-val" class="text-tabular truncate" style="font-size:20px;font-weight:700;">—</div>
        <div class="text-muted truncate" style="font-size:11px;margin-top:2px;">Signals filled ÷ resolved</div>
        <div id="spark-fillrate" style="margin-top:6px;"></div>
        <div class="text-muted" style="font-size:10px;margin-top:2px;">Signal activity trend</div>
      </div>

      <!-- Active Bots -->
      <div class="card">
        <div class="flex items-center gap-2 mb-2">
          <div class="icon-circle icon-purple">
            <svg width="14" height="14" fill="none" stroke="#8B5CF6" stroke-width="2" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="2" height="2"/><rect x="13" y="9" width="2" height="2"/><path d="M9 13a3 3 0 0 0 6 0"/></svg>
          </div>
          <span class="text-muted truncate" style="font-size:12px;">Active Bots</span>
        </div>
        <div id="bots-val" class="text-tabular truncate" style="font-size:20px;font-weight:700;">—</div>
        <div class="text-muted truncate" style="font-size:11px;margin-top:2px;">Strategies enabled</div>
        <div id="spark-bots" style="margin-top:6px;"></div>
        <div class="text-muted" style="font-size:10px;margin-top:2px;">Signal activity trend</div>
      </div>

      <!-- Unrealized P&L -->
      <div class="card">
        <div class="flex items-center gap-2 mb-2">
          <div class="icon-circle icon-orange">
            <svg width="14" height="14" fill="none" stroke="#F59E0B" stroke-width="2" viewBox="0 0 24 24"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
          </div>
          <span class="text-muted truncate" style="font-size:12px;">Unrealized P&amp;L</span>
        </div>
        <div id="upnl-val" class="text-tabular truncate" style="font-size:20px;font-weight:700;">—</div>
        <div class="text-muted truncate" style="font-size:11px;margin-top:2px;">Open positions</div>
        <div id="spark-upnl" style="margin-top:6px;"></div>
        <div class="text-muted" style="font-size:10px;margin-top:2px;">Signal activity trend</div>
      </div>

      <!-- Open Positions -->
      <div class="card">
        <div class="flex items-center gap-2 mb-2">
          <div class="icon-circle icon-indigo">
            <svg width="14" height="14" fill="none" stroke="#6366F1" stroke-width="2" viewBox="0 0 24 24"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/></svg>
          </div>
          <span class="text-muted truncate" style="font-size:12px;">Open Positions</span>
        </div>
        <div id="openpos-val" class="text-tabular truncate" style="font-size:20px;font-weight:700;">—</div>
        <div class="text-muted truncate" style="font-size:11px;margin-top:2px;">Current holdings</div>
        <div id="spark-openpos" style="margin-top:6px;"></div>
        <div class="text-muted" style="font-size:10px;margin-top:2px;">Signal activity trend</div>
      </div>
    </div>

    <!-- Row 2: Performance Chart + Bot Status -->
    <div class="row-2col" style="grid-template-columns:3fr 2fr;">

      <!-- Performance Chart -->
      <div class="card">
        <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div>
            <div style="font-size:13px;font-weight:600;">Portfolio Performance</div>
            <div id="perf-headline" class="text-tabular glow-green" style="font-size:22px;font-weight:700;margin-top:2px;">—</div>
          </div>
          <div class="range-tabs">
            <button class="range-tab active" data-period="1D" data-timeframe="5Min">1H</button>
            <button class="range-tab" data-period="1D" data-timeframe="1H">24H</button>
            <button class="range-tab" data-period="1W" data-timeframe="1D">7D</button>
            <button class="range-tab" data-period="1M" data-timeframe="1D">30D</button>
            <button class="range-tab" data-period="1A" data-timeframe="1D">YTD</button>
            <button class="range-tab" data-period="6A" data-timeframe="1D">6Y</button>
          </div>
        </div>
        <div id="perf-chart" style="min-height:220px;"></div>
      </div>

      <!-- Bot Status -->
      <div class="card">
        <div style="font-size:13px;font-weight:600;margin-bottom:.75rem;">Bot Status</div>
        <div id="bot-status-list" style="display:flex;flex-direction:column;gap:.5rem;">
          <div class="skeleton" style="height:36px;"></div>
          <div class="skeleton" style="height:36px;"></div>
          <div class="skeleton" style="height:36px;"></div>
        </div>
      </div>
    </div>

    <!-- Row 3: Allocation + P&L Breakdown + Recent Trades -->
    <div class="row-3col">

      <!-- Allocation -->
      <div class="card">
        <div style="font-size:13px;font-weight:600;margin-bottom:.75rem;">Portfolio Allocation</div>
        <div id="alloc-chart" style="min-height:155px;"></div>
        <div id="alloc-empty" class="state-empty hidden">No open positions.</div>
      </div>

      <!-- P&L Breakdown -->
      <div class="card">
        <div style="font-size:13px;font-weight:600;margin-bottom:.5rem;">P&amp;L Breakdown</div>
        <div id="radial-chart" style="min-height:160px;"></div>
        <div style="display:flex;flex-direction:column;gap:.4rem;margin-top:.5rem;">
          <div class="flex justify-between"><span class="text-muted" style="font-size:12px;">Daily P&amp;L</span><span id="pnl-daypnl" class="text-tabular" style="font-size:12px;font-weight:600;">—</span></div>
          <div class="flex justify-between"><span class="text-muted" style="font-size:12px;">Unrealized P&amp;L</span><span id="pnl-upnl" class="text-tabular" style="font-size:12px;font-weight:600;">—</span></div>
          <div class="flex justify-between"><span class="text-muted" style="font-size:12px;">Open Positions</span><span id="pnl-openpos" class="text-tabular" style="font-size:12px;font-weight:600;">—</span></div>
        </div>
      </div>

      <!-- Recent Trades -->
      <div class="card">
        <div style="font-size:13px;font-weight:600;margin-bottom:.75rem;">Recent Trades</div>
        <div id="trades-wrap">
          <table class="dtable">
            <colgroup><col style="width:90px"><col style="width:60px"><col style="width:45px"><col style="width:60px"><col style="width:50px"></colgroup>
            <thead><tr>
              <th>Time</th><th>Symbol</th><th>Side</th><th>Size</th><th>P&amp;L</th>
            </tr></thead>
            <tbody id="trades-body">
              <tr><td colspan="5" class="state-empty">Loading…</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Row 4: System Bar -->
    <div class="sys-bar">
      <div class="sys-item"><div id="sys-exchange-dot" class="sys-dot off"></div><span>Exchange: <span id="sys-exchange">—</span></span></div>
      <div class="sys-item"><div id="sys-api-dot" class="sys-dot off"></div><span>API: <span id="sys-api">—</span></span></div>
      <div class="sys-item"><svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg><span>Server: <span id="sys-time">—</span></span></div>
      <div class="sys-item"><svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-.73-9.27"/></svg><span>Last Engine Run: <span id="sys-lastrun">—</span></span></div>
      <div class="sys-item"><svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg><span>API Response: <span id="sys-latency">—</span></span></div>
    </div>

  </main>
</div>

<script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Append initDashboard() to app.js**

```js
// ─────────────────────────────────────────
// initDashboard — index.html
// ─────────────────────────────────────────
async function initDashboard() {
  const chipEl = document.getElementById('market-chip');
  await initClockChip(chipEl);

  // Chart instances (destroyed and recreated on range tab change)
  let perfChart = null;
  let allocChart = null;
  let radialChart = null;
  const sparkCharts = {};

  // ── Fetch account ──
  async function fetchAccount() {
    const t0 = Date.now();
    try {
      const a = await api('/api/account', { key: 'idx-account' });
      const latency = Date.now() - t0;

      const balEl = document.getElementById('balance-val');
      clearState(balEl);
      balEl.textContent = fmt.usd(a.equity);

      const pnlEl = document.getElementById('daypnl-val');
      clearState(pnlEl);
      pnlEl.textContent = fmt.usdSigned(a.day_pl, '—');
      pnlEl.className = 'text-tabular truncate ' + (a.day_pl >= 0 ? 'glow-green' : 'glow-red');
      pnlEl.style.fontSize = '20px';
      pnlEl.style.fontWeight = '700';

      document.getElementById('daypnl-sub').textContent = fmt.pctDecimal(a.day_pl_pct, '');

      // Paper badge
      if (a.account_type === 'paper') {
        document.getElementById('paper-badge').classList.remove('hidden');
      }

      // System bar
      document.getElementById('sys-exchange').textContent = a.status || 'ACTIVE';
      document.getElementById('sys-exchange-dot').classList.remove('off');
      document.getElementById('sys-api').textContent = 'Connected';
      document.getElementById('sys-api-dot').classList.remove('off');
      document.getElementById('sys-latency').textContent = latency + 'ms';

      // P&L breakdown
      const pct = (a.day_pl_pct || 0) * 100;
      document.getElementById('pnl-daypnl').textContent = fmt.usdSigned(a.day_pl, '$0.00');
      document.getElementById('pnl-daypnl').className = 'text-tabular ' + (a.day_pl >= 0 ? 'glow-green' : 'glow-red');

      // Radial chart
      if (radialChart) { radialChart.destroy(); }
      const radEl = document.getElementById('radial-chart');
      radEl.innerHTML = '';
      radialChart = safeMakeChart(radEl, radialConfig(pct, 'Day P&L'));

    } catch (e) {
      if (e.name === 'AbortError') return;
      showError(document.getElementById('balance-val'));
      throw e;
    }
  }

  // ── Fetch performance ──
  async function fetchPerformance() {
    try {
      const p = await api('/api/performance', { key: 'idx-perf' });

      const upnlEl = document.getElementById('upnl-val');
      clearState(upnlEl);
      const upnl = p.total_unrealized_pl || 0;
      upnlEl.textContent = fmt.usdSigned(upnl, '$0.00');
      upnlEl.className = 'text-tabular truncate ' + (upnl >= 0 ? 'glow-green' : 'glow-red');
      upnlEl.style.fontSize = '20px';
      upnlEl.style.fontWeight = '700';

      const opEl = document.getElementById('openpos-val');
      clearState(opEl);
      opEl.textContent = fmt.integer(p.open_positions, '0');

      document.getElementById('pnl-upnl').textContent = fmt.usdSigned(p.total_unrealized_pl, '$0.00');
      document.getElementById('pnl-upnl').className = 'text-tabular ' + (upnl >= 0 ? 'glow-green' : 'glow-red');
      document.getElementById('pnl-openpos').textContent = fmt.integer(p.open_positions, '0');

      // Sparklines (use daily_counts last 7 entries)
      const counts = (p.daily_counts || []).slice(-7).map(d => d.total || 0);
      const sparkIds = ['spark-balance','spark-daypnl','spark-fillrate','spark-bots','spark-upnl','spark-openpos'];
      sparkIds.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        if (sparkCharts[id]) { sparkCharts[id].destroy(); }
        el.innerHTML = '';
        sparkCharts[id] = safeMakeChart(el, sparkConfig(counts));
      });

    } catch (e) {
      if (e.name === 'AbortError') return;
      showError(document.getElementById('upnl-val'));
      throw e;
    }
  }

  // ── Fetch signals → fill rate ──
  async function fetchSignals() {
    try {
      const sigs = await api('/api/signals?limit=200', { key: 'idx-signals' });
      const filled  = sigs.filter(s => s.status === 'filled').length;
      const blocked = sigs.filter(s => s.status === 'blocked').length;
      const error   = sigs.filter(s => s.status === 'error').length;
      const denom   = filled + blocked + error;
      const frEl    = document.getElementById('fillrate-val');
      clearState(frEl);
      frEl.textContent = denom === 0 ? '—' : ((filled / denom) * 100).toFixed(1) + '%';
    } catch (e) {
      if (e.name === 'AbortError') return;
      showError(document.getElementById('fillrate-val'));
      throw e;
    }
  }

  // ── Fetch strategies → active bots ──
  async function fetchStrategies() {
    try {
      const strats = await api('/api/strategies', { key: 'idx-strategies' });
      const botsEl = document.getElementById('bots-val');
      clearState(botsEl);
      botsEl.textContent = strats.filter(s => s.enabled).length;

      // Bot status panel
      const engine = await api('/api/engine', { key: 'idx-engine' });
      const ranMap = {};
      (engine.ran || []).forEach(r => { ranMap[r.strategy] = r; });
      const listEl = document.getElementById('bot-status-list');
      listEl.innerHTML = '';
      strats.forEach(s => {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:8px;min-width:0;';

        // Icon circle
        const ic = document.createElement('div');
        ic.className = 'icon-circle icon-purple';
        ic.style.cssText = 'width:28px;height:28px;flex-shrink:0;';
        ic.innerHTML = '<svg width="12" height="12" fill="none" stroke="#8B5CF6" stroke-width="2" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="2" height="2"/><rect x="13" y="9" width="2" height="2"/><path d="M9 13a3 3 0 0 0 6 0"/></svg>';

        // Name
        const name = document.createElement('div');
        name.style.cssText = 'flex:1;min-width:0;';
        const nameSpan = document.createElement('div');
        nameSpan.className = 'truncate';
        nameSpan.style.fontSize = '12px';
        nameSpan.style.fontWeight = '500';
        nameSpan.textContent = s.label;
        name.appendChild(nameSpan);

        // Badge
        const badge = document.createElement('span');
        let badgeClass, badgeText;
        if (!s.enabled) {
          badgeClass = 'b-disabled'; badgeText = 'Disabled';
        } else if (ranMap[s.name] && ranMap[s.name].error) {
          badgeClass = 'b-error'; badgeText = 'Last Run Error';
        } else if (ranMap[s.name]) {
          badgeClass = 'b-enabled';
          badgeText = '';
        } else {
          badgeClass = 'b-notrun'; badgeText = 'Not Run Yet';
        }
        badge.className = 'badge ' + badgeClass;
        if (badgeClass === 'b-enabled') {
          const dot = document.createElement('span');
          dot.className = 'pdot';
          badge.appendChild(dot);
          const t = document.createElement('span');
          t.textContent = 'Enabled';
          badge.appendChild(t);
        } else {
          badge.textContent = badgeText;
        }

        row.appendChild(ic);
        row.appendChild(name);
        row.appendChild(badge);
        listEl.appendChild(row);
      });

      // System bar - last engine run
      document.getElementById('sys-lastrun').textContent = engine.ts ? fmt.time(engine.ts) : 'Never';

    } catch (e) {
      if (e.name === 'AbortError') return;
      showError(document.getElementById('bots-val'));
      throw e;
    }
  }

  // ── Fetch positions → donut ──
  async function fetchPositions() {
    try {
      const positions = await api('/api/positions', { key: 'idx-positions' });
      const allocEl = document.getElementById('alloc-chart');
      const emptyEl = document.getElementById('alloc-empty');

      if (!positions.length) {
        allocEl.classList.add('hidden');
        emptyEl.classList.remove('hidden');
        return;
      }
      allocEl.classList.remove('hidden');
      emptyEl.classList.add('hidden');
      allocEl.innerHTML = '';
      if (allocChart) { allocChart.destroy(); }
      const labels = positions.map(p => p.symbol);
      const series = positions.map(p => Math.abs(p.market_value));
      allocChart = safeMakeChart(allocEl, donutConfig(labels, series));
    } catch (e) {
      if (e.name === 'AbortError') return;
      showError(document.getElementById('alloc-chart'));
      throw e;
    }
  }

  // ── Fetch orders → recent trades ──
  async function fetchOrders() {
    try {
      const orders = await api('/api/orders?status=closed&limit=25', { key: 'idx-orders' });
      const filled = orders
        .filter(o => o.status === 'filled' && o.filled_at)
        .sort((a, b) => new Date(b.filled_at) - new Date(a.filled_at))
        .slice(0, 5);

      const tbody = document.getElementById('trades-body');
      tbody.innerHTML = '';
      if (!filled.length) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 5;
        td.className = 'state-empty';
        td.textContent = 'No recent trades.';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }
      filled.forEach(o => {
        const tr = document.createElement('tr');
        const cells = [
          fmt.time(o.filled_at),
          o.symbol,
          '', // side tag — set below
          o.filled_qty != null ? o.filled_qty.toFixed(2) : '—',
          '—'
        ];
        cells.forEach((text, i) => {
          const td = document.createElement('td');
          if (i === 2) {
            const tag = document.createElement('span');
            tag.className = 'badge ' + (o.side === 'buy' ? 'b-buy' : 'b-sell');
            tag.textContent = o.side === 'buy' ? 'Buy' : 'Sell';
            td.appendChild(tag);
          } else {
            td.textContent = text;
          }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    } catch (e) {
      if (e.name === 'AbortError') return;
      const tbody = document.getElementById('trades-body');
      tbody.innerHTML = '<tr><td colspan="5" class="state-error">Failed to load trades.</td></tr>';
      throw e;
    }
  }

  // ── Fetch portfolio history → area chart ──
  const RANGE_PARAMS = {
    '1D-5Min': { period: '1D', timeframe: '5Min', label: '1H' },
    '1D-1H':   { period: '1D', timeframe: '1H',   label: '24H' },
    '1W-1D':   { period: '1W', timeframe: '1D',   label: '7D' },
    '1M-1D':   { period: '1M', timeframe: '1D',   label: '30D' },
    '1A-1D':   { period: '1A', timeframe: '1D',   label: 'YTD' },
    '6A-1D':   { period: '6A', timeframe: '1D',   label: '6Y' },
  };

  async function fetchPerfChart(period, timeframe) {
    const chartEl = document.getElementById('perf-chart');
    chartEl.innerHTML = '<div class="skeleton" style="height:220px;border-radius:8px;"></div>';
    try {
      const h = await api(`/api/portfolio_history?period=${period}&timeframe=${timeframe}`, { key: 'idx-ph' });
      const ts = h.timestamp || [];
      const eq = h.equity    || [];
      const base = h.base_value || 0;

      chartEl.innerHTML = '';
      if (ts.length < 2) {
        chartEl.innerHTML = '<div class="state-empty" style="height:220px;display:flex;align-items:center;justify-content:center;">Not enough data for this range.</div>';
        return;
      }
      if (perfChart) { perfChart.destroy(); }
      perfChart = safeMakeChart(chartEl, perfChartConfig(ts, eq, base));

      // Headline P&L
      const last = eq[eq.length - 1] || 0;
      const change = last - base;
      const headEl = document.getElementById('perf-headline');
      headEl.textContent = fmt.usdSigned(change, '—');
      headEl.className = 'text-tabular glow-' + (change >= 0 ? 'green' : 'red');

    } catch (e) {
      if (e.name === 'AbortError') return;
      chartEl.innerHTML = '<div class="state-error" style="height:220px;display:flex;align-items:center;justify-content:center;">Failed to load chart.</div>';
      throw e;
    }
  }

  // ── Range tab wiring ──
  document.querySelectorAll('.range-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.range-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      fetchPerfChart(btn.dataset.period, btn.dataset.timeframe);
    });
  });

  // ── Server time ticker ──
  async function fetchClock() {
    try {
      const c = await api('/api/clock', { key: 'idx-clock2' });
      document.getElementById('sys-time').textContent = new Date(c.timestamp).toLocaleTimeString();
    } catch { /* non-critical */ }
  }

  // ── Start everything ──
  fetchPerfChart('1D', '5Min'); // default tab: 1H

  createPoller(fetchAccount,    30_000).start();
  createPoller(fetchPerformance,30_000).start();
  createPoller(fetchSignals,    60_000).start();
  createPoller(fetchStrategies, 30_000).start();
  createPoller(fetchPositions,  30_000).start();
  createPoller(fetchOrders,     30_000).start();
  createPoller(fetchClock,      10_000).start();
}
```

- [ ] **Step 3: Verify Dashboard in browser**

With server running, open `http://localhost:8000/static/index.html`.

Verify:
- Sidebar renders: 10 nav items, "Dashboard" is highlighted with blue left border and gradient
- Header shows page title, decorative search bar (no ⌘K), market chip, avatar
- 6 metric cards render with skeleton shimmer then populate values
- All sparklines render or show gracefully (no JS errors)
- Performance chart area renders with range tabs (1H active by default)
- Bot Status panel shows strategy list with correct badges
- Allocation donut renders (or "No open positions" if empty)
- P&L radial ring renders
- Recent Trades table shows filled orders or "No recent trades"
- System bar shows exchange status, server time ticking, last engine run
- No `undefined`, `NaN`, or raw error strings visible anywhere

- [ ] **Step 4: Commit**

```powershell
git add server/static/index.html server/static/app.js
git commit -m "feat: add dashboard overview page with all metric cards, charts, and pollers"
```

---

## Task 5: bots.html + initBots() — Bots & Strategies

**Files:**
- Create: `server/static/bots.html`
- Modify: `server/static/app.js` (append initBots)

- [ ] **Step 1: Write bots.html**

Copy the full sidebar + header HTML from Task 4 (index.html). Change:
- `<title>Bots & Strategies — TradeBot</title>`
- `<body data-page="bots">`
- Header page-title: `Bots & Strategies` / subtitle: `Manage and monitor your trading strategies`

Replace the `<main class="content">` body with:

```html
<!-- Paper Mode banner (hidden by default, shown by JS) -->
<div id="banner-paper" class="banner banner-paper hidden">
  <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
  Paper Trading Mode — orders are simulated, no real money at risk.
</div>
<!-- Kill Switch banner (hidden by default, shown by JS) -->
<div id="banner-kill" class="banner banner-kill hidden">
  <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
  Kill Switch Active — engine ticks are blocked. No strategies will run.
</div>

<main class="content flex flex-col gap-4">

  <!-- Top action bar -->
  <div class="card flex items-center justify-between flex-wrap gap-3">
    <div>
      <div style="font-size:14px;font-weight:600;">Engine Controls</div>
      <div id="engine-status-txt" class="text-muted" style="font-size:12px;margin-top:2px;">Loading status…</div>
    </div>
    <div class="flex items-center gap-2 flex-wrap">
      <button id="btn-run-now" class="btn btn-primary" disabled title="Checking status…">
        <svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        Run Engine Now
      </button>
      <button id="btn-ks-on"  class="btn btn-danger hidden">Kill Switch ON</button>
      <button id="btn-ks-off" class="btn btn-ghost hidden">Kill Switch OFF</button>
    </div>
  </div>

  <!-- Run Now result panel (hidden by default) -->
  <div id="run-result" class="result-panel hidden"></div>

  <!-- Strategies list -->
  <div class="card">
    <div style="font-size:14px;font-weight:600;margin-bottom:1rem;">Strategies</div>
    <div id="risk-error" class="state-error hidden mb-3">Could not load risk status.</div>
    <table class="dtable">
      <colgroup>
        <col style="width:36px">
        <col style="width:30%">
        <col>
        <col style="width:140px">
        <col style="width:90px">
      </colgroup>
      <thead><tr>
        <th></th><th>Strategy</th><th>Description</th><th>Status</th><th style="text-align:right;">Action</th>
      </tr></thead>
      <tbody id="strat-body">
        <tr><td colspan="5" class="state-empty">Loading strategies…</td></tr>
      </tbody>
    </table>
  </div>

</main>

<!-- ── Modals ── -->

<!-- Enable/Disable confirm -->
<div id="modal-toggle" class="modal-overlay hidden" role="dialog" aria-modal="true" aria-labelledby="modal-toggle-title">
  <div class="modal-box">
    <div id="modal-toggle-title" class="modal-title">Confirm Action</div>
    <div id="modal-toggle-body" class="modal-body"></div>
    <div class="modal-actions">
      <button class="btn btn-ghost" data-action="cancel">Cancel</button>
      <button id="modal-toggle-confirm" class="btn btn-primary" data-action="confirm">Confirm</button>
    </div>
  </div>
</div>

<!-- Run Engine Now confirm -->
<div id="modal-run" class="modal-overlay hidden" role="dialog" aria-modal="true" aria-labelledby="modal-run-title">
  <div class="modal-box">
    <div id="modal-run-title" class="modal-title">Run Engine Now</div>
    <div class="modal-body">
      <div id="modal-run-mode" style="margin-bottom:.5rem;font-size:13px;"></div>
      This will run one full engine tick. Enabled strategies may <strong>generate and place orders</strong>.
    </div>
    <div class="modal-actions">
      <button class="btn btn-ghost" data-action="cancel">Cancel</button>
      <button class="btn btn-primary" data-action="confirm">Run Now</button>
    </div>
  </div>
</div>

<!-- Kill Switch ON confirm -->
<div id="modal-ks-on" class="modal-overlay hidden" role="dialog" aria-modal="true" aria-labelledby="modal-kson-title">
  <div class="modal-box">
    <div id="modal-kson-title" class="modal-title" style="color:#EF4444;">Activate Kill Switch</div>
    <div class="modal-body">This will <strong>block ALL engine ticks</strong>. No strategies will run until the kill switch is turned off.</div>
    <div class="modal-actions">
      <button class="btn btn-ghost" data-action="cancel">Cancel</button>
      <button class="btn btn-danger" data-action="confirm">Activate Kill Switch</button>
    </div>
  </div>
</div>

<!-- Kill Switch OFF confirm -->
<div id="modal-ks-off" class="modal-overlay hidden" role="dialog" aria-modal="true" aria-labelledby="modal-ksoff-title">
  <div class="modal-box">
    <div id="modal-ksoff-title" class="modal-title">Deactivate Kill Switch</div>
    <div class="modal-body">This will <strong>re-enable future engine execution</strong>. Strategies will run on the next scheduled tick.</div>
    <div class="modal-actions">
      <button class="btn btn-ghost" data-action="cancel">Cancel</button>
      <button class="btn btn-primary" data-action="confirm">Deactivate</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Append initBots() to app.js**

```js
// ─────────────────────────────────────────
// initBots — bots.html
// ─────────────────────────────────────────
async function initBots() {
  const chipEl = document.getElementById('market-chip');
  let clock = await initClockChip(chipEl);
  const marketOpen = clock ? clock.is_open : null; // null = unknown

  let account = null;
  let killSwitchState = null; // null = unknown, true/false = known

  // ── Apply kill switch UI ──
  function applyKillSwitchUI(on) {
    killSwitchState = on;
    document.getElementById('banner-kill').classList.toggle('hidden', !on);
    document.getElementById('btn-ks-on').classList.toggle('hidden', on);
    document.getElementById('btn-ks-off').classList.toggle('hidden', !on);
    updateRunBtnState();
  }

  function updateRunBtnState() {
    const btn = document.getElementById('btn-run-now');
    if (killSwitchState === null) {
      btn.disabled = true;
      btn.title = 'Checking kill switch status…';
    } else if (killSwitchState === true) {
      btn.disabled = true;
      btn.title = 'Kill switch is active.';
    } else if (marketOpen === null) {
      btn.disabled = true;
      btn.title = 'Market status unavailable.';
    } else if (!marketOpen) {
      btn.disabled = true;
      btn.title = 'Market is closed.';
    } else {
      btn.disabled = false;
      btn.title = '';
    }
  }

  // ── Load account ──
  async function fetchAccount() {
    try {
      account = await api('/api/account', { key: 'bots-account' });
      if (account.account_type === 'paper') {
        document.getElementById('banner-paper').classList.remove('hidden');
        document.getElementById('paper-badge')?.classList.remove('hidden');
      }
    } catch {
      document.getElementById('banner-paper').textContent = 'Trading mode unknown — Enable and Run Engine Now are disabled.';
      document.getElementById('banner-paper').classList.remove('hidden');
      document.getElementById('btn-run-now').disabled = true;
    }
  }

  // ── Load kill switch state (authoritative source: GET /api/risk) ──
  async function fetchRiskState() {
    try {
      const risk = await api('/api/risk', { key: 'bots-risk' });
      applyKillSwitchUI(risk.kill_switch);
      document.getElementById('risk-error').classList.add('hidden');
    } catch {
      document.getElementById('risk-error').classList.remove('hidden');
      killSwitchState = null;
      updateRunBtnState();
    }
  }

  // ── Load strategies + engine ──
  async function fetchStrategies() {
    const [strats, engine] = await Promise.all([
      api('/api/strategies', { key: 'bots-strats' }),
      api('/api/engine',     { key: 'bots-engine' })
    ]);

    const ranMap = {};
    (engine.ran || []).forEach(r => { ranMap[r.strategy] = r; });

    const enabled = strats.filter(s => s.enabled).length;
    document.getElementById('engine-status-txt').textContent =
      `${enabled} of ${strats.length} strategies enabled · Last run: ${engine.ts ? fmt.time(engine.ts) : 'Never'}`;

    const tbody = document.getElementById('strat-body');
    tbody.innerHTML = '';

    strats.forEach(s => {
      const tr = document.createElement('tr');

      // Icon
      const tdIcon = document.createElement('td');
      tdIcon.innerHTML = '<div class="icon-circle icon-purple" style="width:26px;height:26px;"><svg width="11" height="11" fill="none" stroke="#8B5CF6" stroke-width="2" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="2" height="2"/><rect x="13" y="9" width="2" height="2"/><path d="M9 13a3 3 0 0 0 6 0"/></svg></div>';

      // Name
      const tdName = document.createElement('td');
      const nameDiv = document.createElement('div');
      nameDiv.className = 'truncate';
      nameDiv.style.fontWeight = '500';
      nameDiv.textContent = s.label;
      tdName.appendChild(nameDiv);

      // Description
      const tdDesc = document.createElement('td');
      tdDesc.className = 'text-muted truncate';
      tdDesc.textContent = s.description;

      // Badge
      const tdBadge = document.createElement('td');
      const badge = document.createElement('span');
      let bc, bt;
      if (!s.enabled) { bc = 'b-disabled'; bt = 'Disabled'; }
      else if (ranMap[s.name]?.error) { bc = 'b-error'; bt = 'Last Run Error'; }
      else if (ranMap[s.name]) { bc = 'b-enabled'; }
      else { bc = 'b-notrun'; bt = 'Not Run Yet'; }
      badge.className = 'badge ' + bc;
      if (bc === 'b-enabled') {
        const dot = document.createElement('span'); dot.className = 'pdot'; badge.appendChild(dot);
        const t = document.createElement('span'); t.textContent = 'Enabled'; badge.appendChild(t);
      } else {
        badge.textContent = bt;
      }
      tdBadge.appendChild(badge);

      // Action button
      const tdAction = document.createElement('td');
      tdAction.style.textAlign = 'right';
      const btn = document.createElement('button');
      btn.className = 'btn btn-sm ' + (s.enabled ? 'btn-ghost' : 'btn-primary');
      btn.textContent = s.enabled ? 'Disable' : 'Enable';
      btn.addEventListener('click', () => confirmToggle(s, !s.enabled, btn));
      tdAction.appendChild(btn);

      tr.append(tdIcon, tdName, tdDesc, tdBadge, tdAction);
      tbody.appendChild(tr);
    });
  }

  // ── Toggle strategy enable/disable ──
  function confirmToggle(strategy, enable, triggerBtn) {
    const overlay = document.getElementById('modal-toggle');
    document.getElementById('modal-toggle-title').textContent =
      (enable ? 'Enable' : 'Disable') + ' Strategy';
    const body = document.getElementById('modal-toggle-body');
    body.innerHTML = '';
    const txt = document.createTextNode(
      'Are you sure you want to ' + (enable ? 'enable' : 'disable') + ' '
    );
    const strong = document.createElement('strong');
    strong.textContent = strategy.label;
    body.appendChild(txt);
    body.appendChild(strong);
    body.appendChild(document.createTextNode('?'));

    openModal(overlay, async () => {
      triggerBtn.disabled = true;
      triggerBtn.textContent = '…';
      try {
        await api(`/api/strategies/${strategy.name}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: enable }),
          key: 'bots-toggle-' + strategy.name
        });
        await fetchStrategies(); // refresh list
      } catch {
        triggerBtn.disabled = false;
        triggerBtn.textContent = enable ? 'Enable' : 'Disable';
        showError(triggerBtn.closest('td'), 'Action failed — check logs.');
      }
    });
  }

  // ── Run Engine Now ──
  document.getElementById('btn-run-now').addEventListener('click', () => {
    const modeText = account?.account_type === 'paper' ? 'Paper Trading' : 'Live Trading';
    document.getElementById('modal-run-mode').innerHTML =
      'Account mode: <strong>' + modeText + '</strong>';
    openModal(document.getElementById('modal-run'), runEngine);
  });

  async function runEngine() {
    const btn = document.getElementById('btn-run-now');
    const resultEl = document.getElementById('run-result');
    btn.disabled = true;
    btn.innerHTML = '<span class="pdot"></span> Running…';
    resultEl.classList.add('hidden');

    try {
      const result = await api('/api/engine/run_now', { method: 'POST', key: 'bots-run' });
      const errors = (result.ran || []).filter(r => r.error);
      resultEl.className = 'result-panel' + (errors.length || result.error ? ' error' : '');

      const lines = [
        'Strategies evaluated: ' + (result.ran?.length || 0),
        'Signals generated: ' + (result.signals?.length || 0),
      ];
      if (result.error) lines.push('Engine error: ' + result.error);
      errors.forEach(e => lines.push('Error in ' + e.strategy + ': ' + e.error));

      resultEl.innerHTML = '';
      lines.forEach(line => {
        const p = document.createElement('div');
        p.textContent = line;
        resultEl.appendChild(p);
      });
      resultEl.classList.remove('hidden');

      setTimeout(() => resultEl.classList.add('hidden'), 10_000);
      await fetchStrategies(); // refresh badges
    } catch {
      resultEl.className = 'result-panel error';
      resultEl.innerHTML = '';
      resultEl.textContent = 'Action failed — check logs.';
      resultEl.classList.remove('hidden');
    } finally {
      btn.innerHTML = '<svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg> Run Engine Now';
      updateRunBtnState();
    }
  }

  // ── Kill Switch ──
  async function setKillSwitch(on) {
    try {
      const res = await api('/api/risk/kill_switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ on }),
        key: 'bots-ks'
      });
      applyKillSwitchUI(res.kill_switch); // update immediately from POST response
      // Background refresh engine state
      api('/api/engine', { key: 'bots-engine-bg' }).then(() => {}).catch(() => {});
    } catch {
      alert('Kill switch action failed. Check logs.');
    }
  }

  document.getElementById('btn-ks-on').addEventListener('click', () => {
    openModal(document.getElementById('modal-ks-on'), () => setKillSwitch(true));
  });
  document.getElementById('btn-ks-off').addEventListener('click', () => {
    openModal(document.getElementById('modal-ks-off'), () => setKillSwitch(false));
  });

  // ── Start ──
  await fetchAccount();
  await fetchRiskState();
  createPoller(fetchStrategies, 30_000).start();
}
```

- [ ] **Step 3: Verify bots.html in browser**

Open `http://localhost:8000/static/bots.html`.

Verify:
- Paper Trading banner shown (if paper account)
- Kill switch state loads from `/api/risk` — red banner + Run Engine Now disabled if kill switch is ON
- Run Engine Now disabled when market is closed
- Clicking Run Engine Now shows modal with paper/live mode label; clicking Run Now posts to engine and shows result summary
- Enable/Disable buttons show confirmation modal; after confirm, strategy badge updates
- Kill Switch ON/OFF buttons show correct confirmation modals; UI updates immediately from POST response (no page reload)
- Error state: manually disconnect server → "Could not load risk status" message appears

- [ ] **Step 4: Commit**

```powershell
git add server/static/bots.html server/static/app.js
git commit -m "feat: add bots & strategies page with trading controls, kill switch, and modals"
```

---

## Task 6: positions.html + initPositions()

**Files:**
- Create: `server/static/positions.html`
- Modify: `server/static/app.js` (append initPositions)

- [ ] **Step 1: Write positions.html**

Copy sidebar + header from Task 4. Change title to `Positions & Orders — TradeBot`, `data-page="positions"`, header title `Positions & Orders` / subtitle `Open holdings and order history`.

Main content:

```html
<main class="content flex flex-col gap-4">

  <div class="card">
    <div style="font-size:14px;font-weight:600;margin-bottom:1rem;">Open Positions</div>
    <div id="positions-wrap">
      <table class="dtable">
        <colgroup><col style="width:70px"><col style="width:50px"><col><col><col><col><col style="width:90px"></colgroup>
        <thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Avg Entry</th><th>Price</th><th>Market Value</th><th>Unrealized P&amp;L</th></tr></thead>
        <tbody id="pos-body"><tr><td colspan="7" class="state-empty">Loading…</td></tr></tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <div class="flex items-center justify-between mb-3">
      <div style="font-size:14px;font-weight:600;">Orders</div>
      <div class="flex gap-2">
        <button class="range-tab active" data-status="all">All</button>
        <button class="range-tab" data-status="open">Open</button>
        <button class="range-tab" data-status="closed">Closed</button>
      </div>
    </div>
    <div id="orders-wrap">
      <table class="dtable">
        <colgroup><col style="width:90px"><col style="width:70px"><col style="width:50px"><col><col><col style="width:90px"></colgroup>
        <thead><tr><th>Submitted</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Status</th><th>Filled At</th></tr></thead>
        <tbody id="orders-body"><tr><td colspan="6" class="state-empty">Loading…</td></tr></tbody>
      </table>
    </div>
  </div>

</main>
```

- [ ] **Step 2: Append initPositions() to app.js**

```js
// ─────────────────────────────────────────
// initPositions — positions.html
// ─────────────────────────────────────────
async function initPositions() {
  initClockChip(document.getElementById('market-chip'));

  async function fetchPositions() {
    const tbody = document.getElementById('pos-body');
    try {
      const positions = await api('/api/positions', { key: 'pos-positions' });
      tbody.innerHTML = '';
      if (!positions.length) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 7; td.className = 'state-empty'; td.textContent = 'No open positions.';
        tr.appendChild(td); tbody.appendChild(tr); return;
      }
      positions.forEach(p => {
        const tr = document.createElement('tr');
        const pnl = p.unrealized_pl || 0;
        const vals = [
          p.symbol,
          p.side,
          (p.qty || 0).toFixed(2),
          fmt.usd(p.avg_entry_price),
          fmt.usd(p.current_price),
          fmt.usd(p.market_value),
          '' // P&L with glow — set below
        ];
        vals.forEach((v, i) => {
          const td = document.createElement('td');
          if (i === 6) {
            td.textContent = fmt.usdSigned(pnl, '—');
            td.className = 'text-tabular ' + (pnl >= 0 ? 'glow-green' : 'glow-red');
          } else {
            td.textContent = v;
          }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    } catch (e) {
      if (e.name === 'AbortError') return;
      tbody.innerHTML = '<tr><td colspan="7" class="state-error">Failed to load — retrying in 30s</td></tr>';
      throw e;
    }
  }

  let currentStatus = 'all';
  async function fetchOrders() {
    const tbody = document.getElementById('orders-body');
    try {
      const orders = await api(`/api/orders?status=${currentStatus}&limit=50`, { key: 'pos-orders' });
      tbody.innerHTML = '';
      if (!orders.length) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 6; td.className = 'state-empty'; td.textContent = 'No orders.';
        tr.appendChild(td); tbody.appendChild(tr); return;
      }
      orders.forEach(o => {
        const tr = document.createElement('tr');
        const fields = [fmt.time(o.submitted_at), o.symbol, '', (o.qty || o.filled_qty || 0).toFixed(2), o.status, fmt.time(o.filled_at)];
        fields.forEach((v, i) => {
          const td = document.createElement('td');
          if (i === 2) {
            const tag = document.createElement('span');
            tag.className = 'badge ' + (o.side === 'buy' ? 'b-buy' : 'b-sell');
            tag.textContent = o.side === 'buy' ? 'Buy' : 'Sell';
            td.appendChild(tag);
          } else { td.textContent = v; }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    } catch (e) {
      if (e.name === 'AbortError') return;
      tbody.innerHTML = '<tr><td colspan="6" class="state-error">Failed to load — retrying in 30s</td></tr>';
      throw e;
    }
  }

  document.querySelectorAll('[data-status]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-status]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentStatus = btn.dataset.status;
      fetchOrders();
    });
  });

  createPoller(fetchPositions, 30_000).start();
  createPoller(fetchOrders,    30_000).start();
}
```

- [ ] **Step 3: Verify in browser**

Open `http://localhost:8000/static/positions.html`. Confirm positions table populates (or shows "No open positions"), orders table loads with filter tabs working (All/Open/Closed). P&L column shows green/red glow.

- [ ] **Step 4: Commit**

```powershell
git add server/static/positions.html server/static/app.js
git commit -m "feat: add positions & orders page"
```

---

## Task 7: performance.html + initPerformance()

**Files:**
- Create: `server/static/performance.html`
- Modify: `server/static/app.js` (append initPerformance)

- [ ] **Step 1: Write performance.html**

Copy sidebar + header. Title: `Performance Analytics — TradeBot`, `data-page="performance"`, header title `Performance` / subtitle `Signal and strategy analytics`.

Main content:

```html
<main class="content flex flex-col gap-4">

  <div class="row-2col" style="grid-template-columns:1fr 1fr;">

    <!-- Strategy Stats -->
    <div class="card">
      <div style="font-size:14px;font-weight:600;margin-bottom:.75rem;">Strategy Statistics</div>
      <table class="dtable">
        <colgroup><col><col style="width:50px"><col style="width:50px"><col style="width:50px"><col style="width:60px"></colgroup>
        <thead><tr><th>Strategy</th><th>Total</th><th>Buys</th><th>Sells</th><th>Blocked</th></tr></thead>
        <tbody id="strat-stats-body"><tr><td colspan="5" class="state-empty">Loading…</td></tr></tbody>
      </table>
    </div>

    <!-- Top Symbols -->
    <div class="card">
      <div style="font-size:14px;font-weight:600;margin-bottom:.75rem;">Top Symbols</div>
      <table class="dtable">
        <colgroup><col style="width:70px"><col style="width:60px"><col style="width:60px"><col style="width:60px"></colgroup>
        <thead><tr><th>Symbol</th><th>Total</th><th>Buys</th><th>Sells</th></tr></thead>
        <tbody id="topsym-body"><tr><td colspan="4" class="state-empty">Loading…</td></tr></tbody>
      </table>
    </div>
  </div>

  <!-- Daily signal counts chart -->
  <div class="card">
    <div style="font-size:14px;font-weight:600;margin-bottom:.75rem;">Daily Signal Activity (30 days)</div>
    <div id="daily-chart" style="min-height:200px;"></div>
  </div>

  <!-- Recent signals -->
  <div class="card">
    <div style="font-size:14px;font-weight:600;margin-bottom:.75rem;">Recent Signals</div>
    <table class="dtable">
      <colgroup><col style="width:90px"><col style="width:80px"><col style="width:70px"><col style="width:50px"><col><col style="width:70px"></colgroup>
      <thead><tr><th>Time</th><th>Strategy</th><th>Symbol</th><th>Side</th><th>Reason</th><th>Status</th></tr></thead>
      <tbody id="signals-body"><tr><td colspan="6" class="state-empty">Loading…</td></tr></tbody>
    </table>
  </div>

</main>
```

- [ ] **Step 2: Append initPerformance() to app.js**

```js
// ─────────────────────────────────────────
// initPerformance — performance.html
// ─────────────────────────────────────────
async function initPerformance() {
  initClockChip(document.getElementById('market-chip'));
  let dailyChart = null;

  async function fetchPerformance() {
    try {
      const p = await api('/api/performance', { key: 'perf-data' });

      // Strategy stats table
      const statsTbody = document.getElementById('strat-stats-body');
      statsTbody.innerHTML = '';
      (p.strategy_stats || []).forEach(s => {
        const tr = document.createElement('tr');
        [s.strategy, s.total, s.buys, s.sells, s.blocked].forEach(v => {
          const td = document.createElement('td');
          td.textContent = v ?? '0';
          tr.appendChild(td);
        });
        statsTbody.appendChild(tr);
      });
      if (!p.strategy_stats?.length) {
        statsTbody.innerHTML = '<tr><td colspan="5" class="state-empty">No data.</td></tr>';
      }

      // Top symbols table
      const symTbody = document.getElementById('topsym-body');
      symTbody.innerHTML = '';
      (p.top_symbols || []).slice(0, 10).forEach(s => {
        const tr = document.createElement('tr');
        [s.symbol, s.total, s.buys, s.sells].forEach(v => {
          const td = document.createElement('td'); td.textContent = v ?? '0'; tr.appendChild(td);
        });
        symTbody.appendChild(tr);
      });
      if (!p.top_symbols?.length) {
        symTbody.innerHTML = '<tr><td colspan="4" class="state-empty">No data.</td></tr>';
      }

      // Daily chart
      const daily = p.daily_counts || [];
      if (daily.length >= 2) {
        const chartEl = document.getElementById('daily-chart');
        chartEl.innerHTML = '';
        if (dailyChart) dailyChart.destroy();
        dailyChart = safeMakeChart(chartEl, {
          series: [
            { name: 'Total', data: daily.map(d => ({ x: d.date, y: d.total })) },
            { name: 'Buys',  data: daily.map(d => ({ x: d.date, y: d.buys  })) },
            { name: 'Sells', data: daily.map(d => ({ x: d.date, y: d.sells })) },
          ],
          chart: { type: 'bar', height: 200, toolbar: { show: false }, background: 'transparent', stacked: false },
          colors: ['#3B82F6', '#10B981', '#EF4444'],
          xaxis: { type: 'category', labels: { style: { colors: '#64748B', fontSize: '11px' } }, axisBorder: { show: false } },
          yaxis: { labels: { style: { colors: '#64748B', fontSize: '11px' } } },
          grid: { borderColor: '#1E2D45', strokeDashArray: 3 },
          legend: { labels: { colors: '#E6EBF5' } },
          theme: { mode: 'dark' },
          tooltip: { theme: 'dark' }
        });
      }

    } catch (e) {
      if (e.name === 'AbortError') return;
      throw e;
    }
  }

  async function fetchSignals() {
    const tbody = document.getElementById('signals-body');
    try {
      const sigs = await api('/api/signals?limit=50', { key: 'perf-signals' });
      tbody.innerHTML = '';
      if (!sigs.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="state-empty">No signals.</td></tr>'; return;
      }
      sigs.slice(0, 50).forEach(s => {
        const tr = document.createElement('tr');
        const statusCls = { filled: 'b-enabled', blocked: 'b-notrun', error: 'b-error', pending: 'b-disabled' }[s.status] || 'b-disabled';
        const fields = [fmt.time(s.ts), s.strategy, s.symbol, '', s.reason, ''];
        fields.forEach((v, i) => {
          const td = document.createElement('td');
          if (i === 3) {
            const tag = document.createElement('span');
            tag.className = 'badge ' + (s.side === 'buy' ? 'b-buy' : 'b-sell');
            tag.textContent = s.side === 'buy' ? 'Buy' : 'Sell';
            td.appendChild(tag);
          } else if (i === 5) {
            const badge = document.createElement('span');
            badge.className = 'badge ' + statusCls;
            badge.textContent = s.status;
            td.appendChild(badge);
          } else {
            td.textContent = v;
          }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    } catch (e) {
      if (e.name === 'AbortError') return;
      tbody.innerHTML = '<tr><td colspan="6" class="state-error">Failed to load — retrying in 30s</td></tr>';
      throw e;
    }
  }

  createPoller(fetchPerformance, 60_000).start();
  createPoller(fetchSignals,     30_000).start();
}
```

- [ ] **Step 3: Verify in browser**

Open `http://localhost:8000/static/performance.html`. Confirm strategy stats and top symbols tables populate, daily bar chart renders, signals table loads with status badges.

- [ ] **Step 4: Commit**

```powershell
git add server/static/performance.html server/static/app.js
git commit -m "feat: add performance analytics page"
```

---

## Task 8: balances.html + initBalances()

**Files:**
- Create: `server/static/balances.html`
- Modify: `server/static/app.js` (append initBalances)

- [ ] **Step 1: Write balances.html**

Copy sidebar + header. Title: `Balances — TradeBot`, `data-page="balances"`, header title `Balances & Assets` / subtitle `Account cash and position values`.

Main content:

```html
<main class="content flex flex-col gap-4">

  <!-- Account summary cards -->
  <div class="row-2col" style="grid-template-columns:repeat(4,minmax(0,1fr));">
    <div class="card"><div class="text-muted mb-1" style="font-size:12px;">Equity</div><div id="bal-equity" class="text-tabular" style="font-size:22px;font-weight:700;">—</div></div>
    <div class="card"><div class="text-muted mb-1" style="font-size:12px;">Cash</div><div id="bal-cash" class="text-tabular" style="font-size:22px;font-weight:700;">—</div></div>
    <div class="card"><div class="text-muted mb-1" style="font-size:12px;">Buying Power</div><div id="bal-bp" class="text-tabular" style="font-size:22px;font-weight:700;">—</div></div>
    <div class="card"><div class="text-muted mb-1" style="font-size:12px;">Portfolio Value</div><div id="bal-pv" class="text-tabular" style="font-size:22px;font-weight:700;">—</div></div>
  </div>

  <!-- Positions value table -->
  <div class="card">
    <div style="font-size:14px;font-weight:600;margin-bottom:.75rem;">Holdings</div>
    <table class="dtable">
      <colgroup><col style="width:80px"><col style="width:60px"><col><col><col><col style="width:100px"></colgroup>
      <thead><tr><th>Symbol</th><th>Qty</th><th>Avg Entry</th><th>Current Price</th><th>Market Value</th><th>Unrealized P&amp;L</th></tr></thead>
      <tbody id="holdings-body"><tr><td colspan="6" class="state-empty">Loading…</td></tr></tbody>
    </table>
  </div>

</main>
```

- [ ] **Step 2: Append initBalances() to app.js**

```js
// ─────────────────────────────────────────
// initBalances — balances.html
// ─────────────────────────────────────────
async function initBalances() {
  initClockChip(document.getElementById('market-chip'));

  async function fetchAccount() {
    try {
      const a = await api('/api/account', { key: 'bal-account' });
      document.getElementById('bal-equity').textContent = fmt.usd(a.equity);
      document.getElementById('bal-cash').textContent   = fmt.usd(a.cash);
      document.getElementById('bal-bp').textContent     = fmt.usd(a.buying_power);
      document.getElementById('bal-pv').textContent     = fmt.usd(a.portfolio_value);
      if (a.account_type === 'paper') {
        document.getElementById('paper-badge')?.classList.remove('hidden');
      }
    } catch (e) {
      if (e.name === 'AbortError') return;
      ['bal-equity','bal-cash','bal-bp','bal-pv'].forEach(id => {
        document.getElementById(id).textContent = '—';
      });
      throw e;
    }
  }

  async function fetchHoldings() {
    const tbody = document.getElementById('holdings-body');
    try {
      const positions = await api('/api/positions', { key: 'bal-positions' });
      tbody.innerHTML = '';
      if (!positions.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="state-empty">No open holdings.</td></tr>';
        return;
      }
      positions.forEach(p => {
        const tr = document.createElement('tr');
        const pnl = p.unrealized_pl || 0;
        const fields = [p.symbol, (p.qty||0).toFixed(2), fmt.usd(p.avg_entry_price), fmt.usd(p.current_price), fmt.usd(p.market_value), ''];
        fields.forEach((v, i) => {
          const td = document.createElement('td');
          if (i === 5) {
            td.textContent = fmt.usdSigned(pnl, '—');
            td.className = 'text-tabular ' + (pnl >= 0 ? 'glow-green' : 'glow-red');
          } else { td.textContent = v; }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    } catch (e) {
      if (e.name === 'AbortError') return;
      tbody.innerHTML = '<tr><td colspan="6" class="state-error">Failed to load — retrying in 30s</td></tr>';
      throw e;
    }
  }

  createPoller(fetchAccount,  30_000).start();
  createPoller(fetchHoldings, 30_000).start();
}
```

- [ ] **Step 3: Verify in browser**

Open `http://localhost:8000/static/balances.html`. Confirm 4 account summary values populate, holdings table shows positions with correct P&L glow.

- [ ] **Step 4: Commit**

```powershell
git add server/static/balances.html server/static/app.js
git commit -m "feat: add balances & assets page"
```

---

## Task 9: logs.html + initLogs()

**Files:**
- Create: `server/static/logs.html`
- Modify: `server/static/app.js` (append initLogs)

- [ ] **Step 1: Write logs.html**

Copy sidebar + header. Title: `Logs & Signals — TradeBot`, `data-page="logs"`, header title `Logs & Signals` / subtitle `Signal feed from all strategies`.

Main content:

```html
<main class="content flex flex-col gap-4">

  <div class="card">
    <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
      <div style="font-size:14px;font-weight:600;">Signal Feed</div>
      <div class="flex gap-2 flex-wrap">
        <button class="range-tab active" data-filter="all">All</button>
        <button class="range-tab" data-filter="filled">Filled</button>
        <button class="range-tab" data-filter="blocked">Blocked</button>
        <button class="range-tab" data-filter="error">Error</button>
      </div>
    </div>
    <table class="dtable">
      <colgroup><col style="width:90px"><col style="width:90px"><col style="width:70px"><col style="width:50px"><col style="width:60px"><col><col style="width:70px"></colgroup>
      <thead><tr><th>Time</th><th>Strategy</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Reason</th><th>Status</th></tr></thead>
      <tbody id="logs-body"><tr><td colspan="7" class="state-empty">Loading…</td></tr></tbody>
    </table>
  </div>

</main>
```

- [ ] **Step 2: Append initLogs() to app.js**

```js
// ─────────────────────────────────────────
// initLogs — logs.html
// ─────────────────────────────────────────
async function initLogs() {
  initClockChip(document.getElementById('market-chip'));
  let currentFilter = 'all';

  async function fetchSignals() {
    const tbody = document.getElementById('logs-body');
    try {
      const sigs = await api('/api/signals?limit=200', { key: 'logs-signals' });
      const filtered = currentFilter === 'all' ? sigs : sigs.filter(s => s.status === currentFilter);
      tbody.innerHTML = '';
      if (!filtered.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="state-empty">No signals.</td></tr>';
        return;
      }
      const statusCls = { filled: 'b-enabled', blocked: 'b-notrun', error: 'b-error', pending: 'b-disabled' };
      filtered.slice(0, 100).forEach(s => {
        const tr = document.createElement('tr');
        const fields = [fmt.time(s.ts), s.strategy, s.symbol, '', (s.qty||0).toFixed(2), s.reason, ''];
        fields.forEach((v, i) => {
          const td = document.createElement('td');
          if (i === 3) {
            const tag = document.createElement('span');
            tag.className = 'badge ' + (s.side === 'buy' ? 'b-buy' : 'b-sell');
            tag.textContent = s.side === 'buy' ? 'Buy' : 'Sell';
            td.appendChild(tag);
          } else if (i === 6) {
            const badge = document.createElement('span');
            badge.className = 'badge ' + (statusCls[s.status] || 'b-disabled');
            badge.textContent = s.status;
            td.appendChild(badge);
          } else { td.textContent = v; }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    } catch (e) {
      if (e.name === 'AbortError') return;
      tbody.innerHTML = '<tr><td colspan="7" class="state-error">Failed to load — retrying in 30s</td></tr>';
      throw e;
    }
  }

  document.querySelectorAll('[data-filter]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-filter]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentFilter = btn.dataset.filter;
      fetchSignals();
    });
  });

  createPoller(fetchSignals, 30_000).start();
}
```

- [ ] **Step 3: Verify in browser**

Open `http://localhost:8000/static/logs.html`. Signal feed populates with filter tabs (All/Filled/Blocked/Error) working correctly.

- [ ] **Step 4: Commit**

```powershell
git add server/static/logs.html server/static/app.js
git commit -m "feat: add logs & signals page"
```

---

## Task 10: apikeys.html + initApiKeys()

**Files:**
- Create: `server/static/apikeys.html`
- Modify: `server/static/app.js` (append initApiKeys)

- [ ] **Step 1: Write apikeys.html**

Copy sidebar + header. Title: `API Keys — TradeBot`, `data-page="apikeys"`, header title `API Keys` / subtitle `Connection health and account mode`.

Main content:

```html
<main class="content flex flex-col gap-4">

  <div class="card" style="max-width:600px;">
    <div style="font-size:14px;font-weight:600;margin-bottom:1rem;">Alpaca Connection Status</div>

    <div class="flex flex-col gap-3">
      <div class="flex items-center justify-between">
        <span class="text-muted" style="font-size:13px;">Connection</span>
        <span id="conn-status" class="badge b-disabled">Checking…</span>
      </div>
      <div class="flex items-center justify-between">
        <span class="text-muted" style="font-size:13px;">Account Mode</span>
        <span id="conn-mode" class="text-tabular" style="font-size:13px;font-weight:600;">—</span>
      </div>
      <div class="flex items-center justify-between">
        <span class="text-muted" style="font-size:13px;">Account Status</span>
        <span id="conn-acct-status" class="text-tabular" style="font-size:13px;">—</span>
      </div>
      <div class="flex items-center justify-between">
        <span class="text-muted" style="font-size:13px;">Last Successful Fetch</span>
        <span id="conn-last-fetch" class="text-muted" style="font-size:13px;">—</span>
      </div>
      <div class="flex items-center justify-between">
        <span class="text-muted" style="font-size:13px;">Trading Blocked</span>
        <span id="conn-blocked" style="font-size:13px;">—</span>
      </div>
    </div>

    <div style="margin-top:1.5rem;padding-top:1rem;border-top:1px solid #1E2D45;">
      <p class="text-muted" style="font-size:12px;">API key and secret are stored server-side only and are never sent to the browser.</p>
    </div>
  </div>

</main>
```

- [ ] **Step 2: Append initApiKeys() to app.js**

```js
// ─────────────────────────────────────────
// initApiKeys — apikeys.html
// ─────────────────────────────────────────
async function initApiKeys() {
  initClockChip(document.getElementById('market-chip'));

  async function fetchConnection() {
    const statusEl  = document.getElementById('conn-status');
    const modeEl    = document.getElementById('conn-mode');
    const acctEl    = document.getElementById('conn-acct-status');
    const fetchEl   = document.getElementById('conn-last-fetch');
    const blockedEl = document.getElementById('conn-blocked');

    try {
      const a = await api('/api/account', { key: 'keys-account' });

      statusEl.className = 'badge b-enabled';
      statusEl.innerHTML = '<span class="pdot"></span><span>Connected</span>';

      modeEl.textContent = a.account_type === 'paper' ? 'Paper Trading' : 'Live Trading';
      modeEl.className = 'text-tabular ' + (a.account_type === 'paper' ? 'text-muted' : 'glow-green');

      acctEl.textContent = a.status || '—';
      fetchEl.textContent = new Date().toLocaleTimeString();
      blockedEl.textContent = a.trading_blocked ? 'Yes' : 'No';
      blockedEl.className = a.trading_blocked ? 'glow-red' : 'text-green';

      if (a.account_type === 'paper') {
        document.getElementById('paper-badge')?.classList.remove('hidden');
      }

    } catch (e) {
      if (e.name === 'AbortError') return;
      statusEl.className = 'badge b-error';
      statusEl.textContent = 'Disconnected';
      modeEl.textContent = '—';
      acctEl.textContent = '—';
      blockedEl.textContent = '—';
      throw e;
    }
  }

  createPoller(fetchConnection, 30_000).start();
}
```

- [ ] **Step 3: Verify in browser**

Open `http://localhost:8000/static/apikeys.html`. Connection status shows "Connected" with pulsing dot, account mode (Paper/Live), account status, last fetch time. No API key or secret values shown anywhere.

- [ ] **Step 4: Commit**

```powershell
git add server/static/apikeys.html server/static/app.js
git commit -m "feat: add API keys connection health page"
```

---

## Task 11: Placeholder Pages

**Files:**
- Create: `server/static/backtesting.html`
- Create: `server/static/risk.html`
- Create: `server/static/settings.html`

- [ ] **Step 1: Write backtesting.html**

Copy sidebar + header. Title: `Backtesting — TradeBot`, `data-page="backtesting"`, header title `Backtesting Studio` / subtitle `Strategy back-testing (Phase 2)`.

Main content:

```html
<main class="content">
  <div class="card">
    <div class="placeholder-wrap">
      <svg width="40" height="40" fill="none" stroke="#64748B" stroke-width="1.5" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
      <div style="font-size:15px;font-weight:600;">Backtesting Studio</div>
      <div class="text-muted" style="font-size:13px;text-align:center;max-width:340px;">Backend endpoints for backtesting are planned for Phase 2. This page will be enabled once the endpoints are available.</div>
    </div>
  </div>
</main>
```

- [ ] **Step 2: Write risk.html**

Copy sidebar + header. Title: `Risk Management — TradeBot`, `data-page="risk"`, header title `Risk Management` / subtitle `Risk controls (Phase 2)`.

Main content:

```html
<main class="content">
  <div class="card">
    <div class="placeholder-wrap">
      <svg width="40" height="40" fill="none" stroke="#64748B" stroke-width="1.5" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
      <div style="font-size:15px;font-weight:600;">Risk Management</div>
      <div class="text-muted" style="font-size:13px;text-align:center;max-width:340px;">Full risk settings UI is planned for Phase 2. Kill Switch controls are available on the Bots &amp; Strategies page.</div>
    </div>
  </div>
</main>
```

- [ ] **Step 3: Write settings.html**

Copy sidebar + header. Title: `Settings — TradeBot`, `data-page="settings"`, header title `Settings` / subtitle `Notifications and preferences (Phase 2)`.

Main content:

```html
<main class="content">
  <div class="card">
    <div class="placeholder-wrap">
      <svg width="40" height="40" fill="none" stroke="#64748B" stroke-width="1.5" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
      <div style="font-size:15px;font-weight:600;">Settings</div>
      <div class="text-muted" style="font-size:13px;text-align:center;max-width:340px;">Notification settings and preferences are planned for Phase 2.</div>
    </div>
  </div>
</main>
```

- [ ] **Step 4: Verify all three in browser**

Open each placeholder:
- `http://localhost:8000/static/backtesting.html`
- `http://localhost:8000/static/risk.html`
- `http://localhost:8000/static/settings.html`

Confirm: sidebar renders, active nav item highlights correctly, "Coming Soon" card shows with appropriate icon and message.

- [ ] **Step 5: Commit**

```powershell
git add server/static/backtesting.html server/static/risk.html server/static/settings.html
git commit -m "feat: add placeholder pages for backtesting, risk, and settings"
```

---

## Task 12: Final Integration Smoke Check

- [ ] **Step 1: Start the server**

```powershell
uvicorn server.main:app --reload
```

- [ ] **Step 2: Navigate every page via sidebar links**

Starting from `http://localhost:8000/static/login.html`:

| Page | URL | Check |
|---|---|---|
| Login | `/static/login.html` | Card renders; wrong credentials shows error |
| Dashboard | `/static/index.html` | All 4 rows render; metric cards populate; charts render; system bar active |
| Bots | `/static/bots.html` | Strategies list loads; kill switch state correct; Run Engine Now gated |
| Positions | `/static/positions.html` | Positions and orders tables load |
| Performance | `/static/performance.html` | Strategy stats, chart, signals load |
| Balances | `/static/balances.html` | Account values and holdings load |
| Logs | `/static/logs.html` | Signal feed loads with filter tabs |
| API Keys | `/static/apikeys.html` | Connected status shows; no secret data |
| Backtesting | `/static/backtesting.html` | Placeholder card |
| Risk | `/static/risk.html` | Placeholder card |
| Settings | `/static/settings.html` | Placeholder card |

- [ ] **Step 3: Check for JS errors**

Open browser DevTools → Console. There should be zero uncaught exceptions on any page. `AbortError` exceptions from cancelled fetches are expected and should be swallowed silently (they will appear as logged warnings, not uncaught errors, because the poller checks `err.name === 'AbortError'`).

- [ ] **Step 4: Check text injection safety**

In DevTools console on any page, run:
```js
document.querySelectorAll('[id]').forEach(el => {
  if (el.innerHTML.includes('<script')) console.warn('Possible XSS in', el.id);
});
```
Expected: no warnings.

- [ ] **Step 5: Verify sidebar active state on all pages**

On each page, confirm exactly one `.nav-item.active` exists and it matches the current page.

- [ ] **Step 6: Final commit**

```powershell
git add .
git commit -m "feat: complete NEXORA dashboard redesign — all 11 pages, styles, and shared JS"
```

---

## Spec Coverage Self-Check

| Spec requirement | Task |
|---|---|
| Glassmorphism card, glow effects, color tokens | Task 1 |
| Critical CSS layout fallbacks in styles.css | Task 1 |
| Tailwind CDN + ApexCharts CDN + Inter font | Tasks 3–11 (`<head>`) |
| `data-page` dispatcher + `setActiveNav()` | Task 2 |
| `createPoller` with retry/pause-interval logic | Task 2 |
| `api()` wrapper with AbortController, 401 redirect | Task 2 |
| `textContent` for all API data (no innerHTML) | Tasks 2, 4–10 |
| `login.html` own inline script, excluded from PAGE_INIT | Task 3 |
| 6 metric cards with correct formulas and fallbacks | Task 4 |
| Sparklines labeled "Signal activity trend" | Task 4 |
| Performance chart with 1H/24H/7D/30D/YTD/6Y tabs | Task 4 |
| Bot Status badges: Enabled/Disabled/Last Run OK/Error/Not Run Yet | Tasks 4, 5 |
| Allocation donut from positions market_value | Task 4 |
| P&L radialBar from day_pl_pct | Task 4 |
| Recent Trades: filled orders only, P&L = "—" | Task 4 |
| System bar: Last Engine Run, API Response Time | Task 4 |
| Kill switch state from GET /api/risk (not engine) | Task 5 |
| Unknown state disables Run Engine Now | Task 5 |
| Kill Switch UI updates immediately from POST response | Task 5 |
| Red banner when kill switch active | Task 5 |
| Run Engine Now confirmation modal with paper/live mode | Task 5 |
| Run Engine Now result summary, auto-dismiss 10s | Task 5 |
| Kill Switch ON/OFF both require confirmation | Task 5 |
| Enable/Disable strategy via PATCH /api/strategies/{name} | Task 5 |
| Paper Trading Mode banner | Tasks 4, 5, 8, 10 |
| Modal: focus trap, Escape=cancel, aria-modal, focus return | Task 2, 5 |
| Market chip labeled "US Equities" | Tasks 3–11 |
| Search bar: decorative, no ⌘K badge | Tasks 3–11 |
| No theme toggle | Tasks 3–11 |
| Backtesting/Risk/Settings as Coming Soon placeholders | Task 11 |
| /api/logs does not exist; logs.html uses /api/signals | Task 9 |
| API Keys: connection health only, no secret | Task 10 |
| 30s retry pauses polling interval | Task 2 (createPoller) |
