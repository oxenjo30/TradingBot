/* ─────────────────────────────────────────
   TradeBot Dashboard — app.js
   All page-specific init functions follow
   the core utilities section.
───────────────────────────────────────── */

// ── Broker catalog ──
const BROKER_CATALOG = [
  // Active
  { id: 'alpaca',      name: 'Alpaca',        initials: 'AL', color: '#00C805', bg: 'rgba(0,200,5,.18)',      available: true  },
  // Stocks & Options
  { id: 'ibkr',        name: 'IBKR',          initials: 'IB', color: '#E31837', bg: 'rgba(227,24,55,.15)',    available: false },
  { id: 'schwab',      name: 'Schwab',        initials: 'SC', color: '#00A0DF', bg: 'rgba(0,160,223,.15)',    available: false },
  { id: 'tradier',     name: 'Tradier',       initials: 'TR', color: '#4F8EF7', bg: 'rgba(79,142,247,.15)',   available: true  },
  { id: 'tastytrade',  name: 'Tastytrade',    initials: 'TT', color: '#FF6B35', bg: 'rgba(255,107,53,.15)',   available: false },
  { id: 'robinhood',   name: 'Robinhood',     initials: 'RH', color: '#00B300', bg: 'rgba(0,179,0,.15)',      available: false },
  { id: 'webull',      name: 'Webull',        initials: 'WB', color: '#00A0B0', bg: 'rgba(0,160,176,.15)',    available: false },
  { id: 'fidelity',    name: 'Fidelity',      initials: 'FI', color: '#367C2B', bg: 'rgba(54,124,43,.15)',    available: false },
  { id: 'etrade',      name: 'E*TRADE',       initials: 'ET', color: '#7B2D8B', bg: 'rgba(123,45,139,.15)',   available: false },
  // Crypto
  { id: 'coinbase',    name: 'Coinbase',      initials: 'CB', color: '#1652F0', bg: 'rgba(22,82,240,.15)',    available: false },
  { id: 'kraken',      name: 'Kraken',        initials: 'KR', color: '#5741D9', bg: 'rgba(87,65,217,.15)',    available: false },
  { id: 'binanceus',   name: 'Binance.US',    initials: 'BI', color: '#F0B90B', bg: 'rgba(240,185,11,.15)',   available: false },
  // Forex
  { id: 'oanda',       name: 'OANDA',         initials: 'OA', color: '#FF6600', bg: 'rgba(255,102,0,.15)',    available: false },
  { id: 'forexcom',    name: 'Forex.com',     initials: 'FX', color: '#0052CC', bg: 'rgba(0,82,204,.15)',     available: false },
  { id: 'fxcm',        name: 'FXCM',          initials: 'FC', color: '#1E3A5F', bg: 'rgba(30,58,95,.25)',     available: false },
  { id: 'ig',          name: 'IG Markets',    initials: 'IG', color: '#FF5F00', bg: 'rgba(255,95,0,.15)',     available: false },
  // Futures & Commodities
  { id: 'ninjatrader', name: 'NinjaTrader',   initials: 'NT', color: '#00A9E0', bg: 'rgba(0,169,224,.15)',    available: false },
  { id: 'tradestation',name: 'TradeStation',  initials: 'TS', color: '#D62828', bg: 'rgba(214,40,40,.15)',    available: false },
  { id: 'ampfutures',  name: 'AMP Futures',   initials: 'AF', color: '#2E86AB', bg: 'rgba(46,134,171,.15)',   available: false },
  { id: 'cqg',         name: 'CQG',           initials: 'CQ', color: '#F4A261', bg: 'rgba(244,162,97,.15)',   available: false },
];

function getBrokerMeta(brokerId) {
  return BROKER_CATALOG.find(b => b.id === brokerId) || BROKER_CATALOG[0];
}

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
  if (res.status === 402) { location.href = '/static/license.html'; throw new Error('license required'); }
  if (res.status === 401) { location.href = '/static/login.html'; throw new Error('unauthorized'); }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const d = await res.json(); msg = d.detail || d.message || msg; } catch (_) {}
    throw new Error(msg);
  }
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
        try { await fn(); } catch (_) { /* retry done, resume polling regardless */ }
        isRetrying = false;
        retryId = null;
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

// ── Mobile sidebar toggle ──
function initMobileSidebar() {
  const sidebar = document.querySelector('.sidebar');
  if (!sidebar) return;

  const header = document.querySelector('.page-header');
  if (!header) return;

  const burger = document.createElement('button');
  burger.className = 'hamburger-btn';
  burger.setAttribute('aria-label', 'Toggle menu');
  burger.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
  </svg>`;
  header.insertBefore(burger, header.firstChild);

  const backdrop = document.createElement('div');
  backdrop.className = 'sidebar-backdrop';
  document.body.appendChild(backdrop);

  function openSidebar()  { sidebar.classList.add('mobile-open'); backdrop.classList.add('visible'); document.body.style.overflow = 'hidden'; }
  function closeSidebar() { sidebar.classList.remove('mobile-open'); backdrop.classList.remove('visible'); document.body.style.overflow = ''; }

  burger.addEventListener('click', () => sidebar.classList.contains('mobile-open') ? closeSidebar() : openSidebar());
  backdrop.addEventListener('click', closeSidebar);

  sidebar.querySelectorAll('.nav-item').forEach(link => {
    link.addEventListener('click', () => { if (window.innerWidth < 768) closeSidebar(); });
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
  const trap = function(e) {
    if (e.key !== 'Tab') return;
    const focusable = [...overlayEl.querySelectorAll('button, [tabindex="0"]')];
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  function cleanup() {
    overlayEl.removeEventListener('keydown', handleKey);
    overlayEl.removeEventListener('click', handleClick);
    overlayEl.removeEventListener('keydown', trap);
  }
  overlayEl.addEventListener('keydown', handleKey);
  overlayEl.addEventListener('click', handleClick);
  overlayEl.addEventListener('keydown', trap);
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
  const isLight = _chartTheme() === 'light';
  const labelClr = isLight ? '#64748B' : '#94A3B8';
  const gridClr  = isLight ? '#E2E8F0' : '#1E2D45';
  return {
    series: [{ name: 'Equity', data: timestamps.map((t, i) => ({ x: new Date(t * 1000), y: equities[i] })) }],
    chart: { type: 'area', height: 220, toolbar: { show: false }, background: 'transparent', animations: { enabled: false } },
    dataLabels: { enabled: false },
    stroke: { curve: 'smooth', width: 2, colors: ['#3B82F6'] },
    fill: { type: 'gradient', gradient: { shade: 'dark', opacityFrom: 0.3, opacityTo: 0, stops: [0, 100] } },
    colors: ['#3B82F6'],
    annotations: { yaxis: [{ y: baseValue, borderColor: '#EF4444', strokeDashArray: 4, label: { text: 'Base', style: { color: '#EF4444', background: 'transparent' } } }] },
    xaxis: { type: 'datetime', labels: { style: { colors: labelClr, fontSize: '11px' } }, axisBorder: { show: false }, axisTicks: { show: false } },
    yaxis: { labels: { style: { colors: labelClr, fontSize: '11px' }, formatter: v => '$' + (v/1000).toFixed(0) + 'k' } },
    grid: { borderColor: gridClr, strokeDashArray: 3 },
    theme: { mode: _chartTheme() },
    tooltip: { theme: _chartTheme(), x: { format: 'HH:mm MMM dd' } }
  };
}

function donutConfig(labels, series) {
  const isLight = _chartTheme() === 'light';
  const labelClr = isLight ? '#64748B' : '#94A3B8';
  return {
    series,
    labels,
    chart: { type: 'donut', height: 155, background: 'transparent' },
    colors: ['#3B82F6', '#10B981', '#8B5CF6', '#F59E0B', '#06B6D4', '#6366F1'],
    dataLabels: { enabled: false },
    legend: { position: 'bottom', labels: { colors: labelClr }, fontSize: '11px' },
    plotOptions: { pie: { donut: { size: '62%' } } },
    theme: { mode: _chartTheme() },
    tooltip: { theme: _chartTheme() }
  };
}

function radialConfig(pct, label) {
  const isLight = _chartTheme() === 'light';
  return {
    series: [Math.min(Math.abs(pct), 100)],
    chart: { type: 'radialBar', height: 160, background: 'transparent' },
    plotOptions: { radialBar: {
      hollow: { size: '65%' },
      dataLabels: {
        name:  { fontSize: '11px', color: isLight ? '#64748B' : '#94A3B8', offsetY: -6 },
        value: { fontSize: '17px', color: isLight ? '#0F172A' : '#E6EBF5', offsetY: 5,
                 formatter: () => (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%' }
      }
    }},
    colors: [pct >= 0 ? '#10B981' : '#EF4444'],
    labels: [label],
    theme: { mode: _chartTheme() }
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
  risk:        initRisk,
  settings:    initSettings,
  backtesting: initBacktesting,
  // login excluded — uses own inline script
};

// ── Watchlist — single flat list with live price rows ──
let _wlSymbols = [];   // string[]
let _wlId      = null; // id of the auto-managed single watchlist
const WL_NAME  = '__default__';

async function _wlLoad() {
  try {
    const lists = await api('/api/watchlists', { key: 'wl-list' });
    let wl = lists[0];
    if (!wl) {
      wl = await api('/api/watchlists', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: WL_NAME }),
      });
    }
    _wlId      = wl.id;
    _wlSymbols = wl.symbols || [];
  } catch { _wlId = null; _wlSymbols = []; }
  _wlRenderRows();
  if (_wlSymbols.length) _wlRefreshPrices();
}

async function _wlRefreshPrices() {
  if (!_wlSymbols.length) return;
  try {
    const res = await fetch(`/api/quotes/snapshot?symbols=${_wlSymbols.map(encodeURIComponent).join(',')}`);
    if (!res.ok) return;
    const snaps = await res.json();
    snaps.forEach(s => {
      const row = document.getElementById(`wl-row-${s.symbol}`);
      if (!row) return;
      const priceEl  = row.querySelector('.wl-price');
      const changeEl = row.querySelector('.wl-change');
      if (priceEl && s.price != null)
        priceEl.textContent = '$' + s.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      if (changeEl && s.change_pct != null) {
        const up = s.change_pct >= 0;
        changeEl.textContent = (up ? '+' : '') + s.change_pct.toFixed(2) + '%';
        changeEl.style.color = up ? '#10B981' : '#EF4444';
      }
    });
  } catch { /* prices non-critical */ }
}

function _wlRenderRows() {
  const rowsEl  = document.getElementById('wl-rows');
  const emptyEl = document.getElementById('wl-empty');
  const countEl = document.getElementById('wl-count');
  if (!rowsEl) return;
  if (countEl) countEl.textContent = _wlSymbols.length ? `${_wlSymbols.length} symbol${_wlSymbols.length > 1 ? 's' : ''}` : '';
  if (!_wlSymbols.length) {
    rowsEl.innerHTML = '';
    if (emptyEl) emptyEl.style.display = '';
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';
  rowsEl.innerHTML = _wlSymbols.map((sym, i) => `
    <div id="wl-row-${sym}" style="display:flex;align-items:center;padding:.55rem 0;
      ${i < _wlSymbols.length - 1 ? 'border-bottom:1px solid var(--border);' : ''}">
      <span style="font-size:13px;font-weight:700;color:var(--text);min-width:72px;letter-spacing:.02em;">${escHtml(sym)}</span>
      <span class="wl-change" style="font-size:12px;font-weight:600;min-width:64px;color:var(--muted);">—</span>
      <span class="wl-price text-tabular" style="font-size:13px;font-weight:600;flex:1;text-align:right;color:var(--text);">—</span>
      <button onclick="window._wlRemove('${escHtml(sym)}')"
        style="background:none;border:none;cursor:pointer;color:var(--muted);padding:0 0 0 12px;
        display:flex;align-items:center;transition:color .15s;"
        onmouseover="this.style.color='#EF4444'" onmouseout="this.style.color=''"
        title="Remove ${escHtml(sym)}">
        <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/>
        </svg>
      </button>
    </div>`).join('');
}

window._wlRemove = async function(sym) {
  if (!_wlId) return;
  try {
    await api(`/api/watchlists/${_wlId}/symbols/${encodeURIComponent(sym)}`, { method: 'DELETE' });
    await _wlLoad();
  } catch { alert('Failed to remove symbol.'); }
};

// ── Account mode badge (sidebar card reflects live vs paper) ──
async function initAccountModeBadge() {
  const card = document.getElementById('mode-card');
  if (!card) return;
  try {
    const accounts = await api('/api/broker-accounts', { key: 'broker-accounts-badge' });
    const liveAccounts = (accounts || []).filter(a => a.account_type === 'live');
    const label = card.querySelector('.paper-label');
    const sub   = label ? label.nextElementSibling : null;
    const link  = card.querySelector('.go-live');
    if (liveAccounts.length > 0) {
      card.classList.add('live-card');
      if (label) label.textContent = 'Live Trading Active';
      if (sub) {
        sub.textContent = liveAccounts.length === 1
          ? liveAccounts[0].label || 'Live account connected'
          : `${liveAccounts.length} live accounts connected`;
      }
      if (link) { link.textContent = 'Manage Accounts →'; link.href = '/static/apikeys.html'; }
    } else {
      if (link) link.href = '/static/apikeys.html';
    }
  } catch { /* silently keep default paper state */ }
}

// ── Global search overlay ────────────────────────────────────────────
const SEARCH_PAGES = [
  { label: 'Dashboard',          desc: 'Overview & metrics',                        url: '/static/index.html',       keywords: ['dash','home','index','overview'],                icon: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>' },
  { label: 'Positions & Orders', desc: 'Open holdings, order history & manual trade',url: '/static/positions.html',  keywords: ['pos','order','hold','trade','manual','buy','sell'],icon: '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>' },
  { label: 'Balances',           desc: 'Account cash and equity',                   url: '/static/balances.html',   keywords: ['bal','cash','fund','equity','money'],            icon: '<rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/>' },
  { label: 'Performance',        desc: 'P&L, signals & strategy analytics',         url: '/static/performance.html',keywords: ['perf','pnl','profit','analytics'],               icon: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>' },
  { label: 'Bots & Strategies',  desc: 'Assign strategies to broker accounts',      url: '/static/bots.html',       keywords: ['bot','strat','strategy','algo'],                 icon: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="2" height="2"/><rect x="13" y="9" width="2" height="2"/><path d="M9 13a3 3 0 0 0 6 0"/>' },
  { label: 'Risk',               desc: 'Guards, kill switch & limits',              url: '/static/risk.html',       keywords: ['risk','guard','kill','limit','loss'],            icon: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>' },
  { label: 'Logs & Signals',     desc: 'Strategy signal feed',                      url: '/static/logs.html',       keywords: ['log','sig','signal','history','feed'],           icon: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/>' },
  { label: 'Backtesting',        desc: 'Test strategies on historical data',        url: '/static/backtesting.html',keywords: ['back','test','backtest','hist','simul'],         icon: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>' },
  { label: 'Broker Accounts',    desc: 'API keys & account management',             url: '/static/apikeys.html',    keywords: ['key','api','broker','acc','account','cred'],    icon: '<path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>' },
  { label: 'Settings',           desc: 'Notifications & preferences',               url: '/static/settings.html',   keywords: ['set','conf','setting','notif','email','telegram'],icon: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>' },
  { label: 'User Guide',         desc: 'Help & documentation',                      url: '/static/help.html',       keywords: ['help','guide','doc','faq'],                     icon: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>' },
];

function _buildSearchOverlay() {
  if (document.getElementById('search-overlay')) return document.getElementById('search-overlay');
  const el = document.createElement('div');
  el.id = 'search-overlay';
  el.className = 'hidden';
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-label', 'Search');
  el.innerHTML = `
    <div id="search-overlay-box">
      <div id="search-input-wrap">
        <svg width="16" height="16" fill="none" stroke="#64748B" stroke-width="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <input id="search-input" type="text" placeholder="Search pages or type a symbol&hellip;" autocomplete="off" spellcheck="false">
        <div id="search-close-btn" title="Esc">ESC</div>
      </div>
      <div id="search-results"></div>
      <div id="search-hint">
        <span><span class="search-kbd">&uarr;</span> <span class="search-kbd">&darr;</span> navigate</span>
        <span><span class="search-kbd">Enter</span> open</span>
        <span><span class="search-kbd">Esc</span> close</span>
      </div>
    </div>`;
  document.body.appendChild(el);

  const input   = el.querySelector('#search-input');
  const results = el.querySelector('#search-results');
  let focusIdx  = -1;

  function close() { el.classList.add('hidden'); input.value = ''; render(''); }
  function open()  { el.classList.remove('hidden'); input.focus(); render(''); }

  function render(q) {
    const t = q.trim().toLowerCase();
    const matches = t
      ? SEARCH_PAGES.filter(p =>
          p.label.toLowerCase().includes(t) ||
          p.desc.toLowerCase().includes(t) ||
          p.keywords.some(k => k.startsWith(t))
        )
      : SEARCH_PAGES;
    focusIdx = -1;
    results.innerHTML = matches.map((p, i) => `
      <a class="search-result-item" href="${p.url}" data-idx="${i}">
        <div class="search-result-icon">
          <svg width="14" height="14" fill="none" stroke="#60A5FA" stroke-width="1.8" viewBox="0 0 24 24">${p.icon}</svg>
        </div>
        <div>
          <div class="search-result-label">${p.label}</div>
          <div class="search-result-desc">${p.desc}</div>
        </div>
      </a>`).join('');
    if (!t && /^[A-Z]{1,5}$/.test(q.trim().toUpperCase()) && q.trim()) {
      results.innerHTML += `<a class="search-result-item" href="/static/positions.html">
        <div class="search-result-icon"><svg width="14" height="14" fill="none" stroke="#10B981" stroke-width="1.8" viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/></svg></div>
        <div><div class="search-result-label">View ${q.trim().toUpperCase()} on Positions</div><div class="search-result-desc">Go to Positions &amp; Orders page</div></div>
      </a>`;
    }
  }

  input.addEventListener('input', e => render(e.target.value));

  input.addEventListener('keydown', e => {
    const items = results.querySelectorAll('.search-result-item');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      focusIdx = Math.min(focusIdx + 1, items.length - 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      focusIdx = Math.max(focusIdx - 1, 0);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const focused = results.querySelector('.focused');
      if (focused) { location.href = focused.href; return; }
      if (/^[A-Z]{1,5}$/i.test(input.value.trim())) { location.href = '/static/positions.html'; return; }
      const first = results.querySelector('.search-result-item');
      if (first) location.href = first.href;
    } else if (e.key === 'Escape') {
      close(); return;
    }
    items.forEach((item, i) => item.classList.toggle('focused', i === focusIdx));
    if (focusIdx >= 0 && items[focusIdx]) items[focusIdx].scrollIntoView({ block: 'nearest' });
  });

  el.addEventListener('click', e => { if (e.target === el) close(); });
  el.querySelector('#search-close-btn').addEventListener('click', close);

  // Global shortcut: Ctrl+K
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); open(); }
  });

  el._open = open;
  return el;
}

function initGlobalSearch() {
  const bar = document.getElementById('global-search-bar');
  if (!bar) return;
  const overlay = _buildSearchOverlay();
  bar.addEventListener('click', () => overlay._open());
}

// ── Bell / notification indicator ───────────────────────────────────
function initBellIndicator() {
  const bell = document.getElementById('bell-btn');
  const badge = document.getElementById('bell-badge');
  if (!bell) return;
  bell.addEventListener('click', () => { location.href = '/static/logs.html'; });
  // Poll for unread signals
  async function checkUnread() {
    try {
      const signals = await api('/api/signals?limit=5', { key: 'bell-check' });
      if (badge && signals && signals.length > 0) badge.classList.remove('hidden');
    } catch {}
  }
  checkUnread();
  setInterval(checkUnread, 60_000);
}

document.addEventListener('DOMContentLoaded', () => {
  setActiveNav();
  initAccountModeBadge();
  initGlobalSearch();
  initBellIndicator();
  initMobileSidebar();
  const page = document.body.dataset.page;
  if (PAGE_INIT[page]) PAGE_INIT[page]();
});

// ─────────────────────────────────────────
// Page init functions are appended in Tasks 4–10
// ─────────────────────────────────────────

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
      pnlEl.className = 'text-tabular truncate ' + (a.day_pl >= 0 ? 'text-green glow-green' : 'text-red glow-red');
      pnlEl.style.fontSize = '20px';
      pnlEl.style.fontWeight = '700';

      document.getElementById('daypnl-sub').textContent = fmt.pctDecimal(a.day_pl_pct, '');

      if (a.account_type === 'paper') {
        document.getElementById('paper-badge').classList.remove('hidden');
      }

      document.getElementById('sys-exchange').textContent = a.status || 'ACTIVE';
      document.getElementById('sys-exchange-dot').classList.remove('off');
      document.getElementById('sys-api').textContent = 'Connected';
      document.getElementById('sys-api-dot').classList.remove('off');
      document.getElementById('sys-latency').textContent = latency + 'ms';

      const pct = (a.day_pl_pct || 0) * 100;
      document.getElementById('pnl-daypnl').textContent = fmt.usdSigned(a.day_pl, '$0.00');
      document.getElementById('pnl-daypnl').className = 'text-tabular ' + (a.day_pl >= 0 ? 'text-green glow-green' : 'text-red glow-red');

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
      upnlEl.className = 'text-tabular truncate ' + (upnl >= 0 ? 'text-green glow-green' : 'text-red glow-red');
      upnlEl.style.fontSize = '20px';
      upnlEl.style.fontWeight = '700';

      const opEl = document.getElementById('openpos-val');
      clearState(opEl);
      opEl.textContent = fmt.integer(p.open_positions, '0');

      document.getElementById('pnl-upnl').textContent = fmt.usdSigned(p.total_unrealized_pl, '$0.00');
      document.getElementById('pnl-upnl').className = 'text-tabular ' + (upnl >= 0 ? 'text-green glow-green' : 'text-red glow-red');
      document.getElementById('pnl-openpos').textContent = fmt.integer(p.open_positions, '0');

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

  // ── Fetch strategies → active bots + bot status panel ──
  async function fetchStrategies() {
    try {
      const [strats, engine] = await Promise.all([
        api('/api/strategies', { key: 'idx-strategies' }),
        api('/api/engine',     { key: 'idx-engine' }),
      ]);
      const botsEl = document.getElementById('bots-val');
      clearState(botsEl);
      botsEl.textContent = strats.filter(s => s.enabled).length;

      const ranMap = {};
      (engine.ran || []).forEach(r => { ranMap[r.strategy] = r; });
      const listEl = document.getElementById('bot-status-list');
      listEl.innerHTML = '';
      strats.forEach(s => {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:8px;min-width:0;';

        const ic = document.createElement('div');
        ic.className = 'icon-circle icon-purple';
        ic.style.cssText = 'width:28px;height:28px;flex-shrink:0;';
        ic.innerHTML = '<svg width="12" height="12" fill="none" stroke="#8B5CF6" stroke-width="2" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="2" height="2"/><rect x="13" y="9" width="2" height="2"/><path d="M9 13a3 3 0 0 0 6 0"/></svg>';

        const name = document.createElement('div');
        name.style.cssText = 'flex:1;min-width:0;';
        const nameSpan = document.createElement('div');
        nameSpan.className = 'truncate';
        nameSpan.style.fontSize = '12px';
        nameSpan.style.fontWeight = '500';
        nameSpan.textContent = s.label;
        name.appendChild(nameSpan);

        const badge = document.createElement('span');
        const ranEntry = ranMap[s.name];
        let badgeClass, badgeText;
        if (!s.enabled) {
          badgeClass = 'b-disabled'; badgeText = 'Disabled';
        } else if (ranEntry && ranEntry.error) {
          badgeClass = 'b-error'; badgeText = 'Error';
        } else if (ranEntry && !ranEntry.skipped) {
          badgeClass = 'b-enabled'; badgeText = '';  // ran this cycle → Running
        } else if (ranEntry && ranEntry.skipped === 'market_closed') {
          badgeClass = 'b-notrun'; badgeText = 'Mkt Closed';
        } else if (ranEntry && ranEntry.skipped === 'window') {
          badgeClass = 'b-notrun'; badgeText = 'Off Hours';
        } else if (ranEntry && ranEntry.skipped === 'no_accounts') {
          badgeClass = 'b-disabled'; badgeText = 'No Accounts';
        } else {
          badgeClass = 'b-notrun'; badgeText = 'Idle'; // engine hasn't run yet
        }
        badge.className = 'badge ' + badgeClass;
        if (badgeClass === 'b-enabled') {
          const dot = document.createElement('span');
          dot.className = 'pdot';
          badge.appendChild(dot);
          const t = document.createElement('span');
          t.textContent = 'Running';
          badge.appendChild(t);
        } else {
          badge.textContent = badgeText;
        }

        row.appendChild(ic);
        row.appendChild(name);
        row.appendChild(badge);
        listEl.appendChild(row);
      });

      document.getElementById('sys-lastrun').textContent = engine.ts ? fmt.time(engine.ts) : 'Never';

    } catch (e) {
      if (e.name === 'AbortError') return;
      showError(document.getElementById('bots-val'));
      throw e;
    }
  }

  // ── Fetch positions → portfolio heat map ──
  async function fetchPositions() {
    try {
      const positions = await api('/api/positions', { key: 'idx-positions' });
      const gridEl  = document.getElementById('heatmap-grid');
      const emptyEl = document.getElementById('heatmap-empty');

      if (!positions.length) {
        gridEl.style.display  = 'none';
        emptyEl.classList.remove('hidden');
        return;
      }
      gridEl.style.display = 'grid';
      emptyEl.classList.add('hidden');

      const totalMv = positions.reduce((s, p) => s + Math.abs(p.market_value || 0), 0) || 1;
      const maxPct  = Math.max(...positions.map(p => Math.abs(p.unrealized_plpc || 0))) || 1;

      gridEl.innerHTML = positions
        .sort((a, b) => Math.abs(b.market_value) - Math.abs(a.market_value))
        .map(p => {
          const mv      = Math.abs(p.market_value || 0);
          const plPct   = p.unrealized_plpc || 0;
          const isGain  = plPct >= 0;
          const intensity = Math.min(1, Math.abs(plPct) / maxPct);
          const alpha   = 0.12 + intensity * 0.55;
          const bg      = isGain
            ? `rgba(16,185,129,${alpha.toFixed(2)})`
            : `rgba(239,68,68,${alpha.toFixed(2)})`;
          const border  = isGain ? 'rgba(16,185,129,.35)' : 'rgba(239,68,68,.35)';
          const pnlSign = isGain ? '+' : '';
          const sizePct = Math.round((mv / totalMv) * 100);
          return `<div style="background:${bg};border:1px solid ${border};border-radius:8px;
                    padding:.5rem .4rem;text-align:center;cursor:default;
                    min-height:${Math.max(54, 40 + sizePct)}px;display:flex;flex-direction:column;
                    align-items:center;justify-content:center;gap:2px;"
                    title="${p.symbol} — MV: $${Math.round(mv).toLocaleString()} | P&L: ${pnlSign}${plPct.toFixed(2)}%">
            <div style="font-size:11px;font-weight:700;color:var(--text);letter-spacing:.03em;">${p.symbol}</div>
            <div style="font-size:10px;color:${isGain ? 'var(--green)' : 'var(--red)'};font-weight:600;">${pnlSign}${plPct.toFixed(1)}%</div>
            <div style="font-size:9px;color:var(--muted);">$${Math.round(mv).toLocaleString()}</div>
          </div>`;
        }).join('');
    } catch (e) {
      if (e.name === 'AbortError') return;
      showError(document.getElementById('heatmap-grid'));
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
          '',
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

  // ── Portfolio history chart ──
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

  // ── Watchlist wiring ──
  (function initWatchlistPanel() {
    const addInp  = document.getElementById('wl-add-input');
    const addBtn  = document.getElementById('wl-add-btn');
    const sugEl   = document.getElementById('wl-suggestions');
    if (!addInp) return;

    // ── Autocomplete ──
    let _sugDebounce = null;
    let _sugSelected = -1;
    let _sugItems = [];

    function _hideSug() { sugEl.style.display = 'none'; _sugSelected = -1; }

    function _renderSug(results) {
      _sugItems = results;
      if (!results.length) { _hideSug(); return; }
      sugEl.innerHTML = results.map((r, i) => `
        <div data-i="${i}" class="wl-sug-item" style="display:flex;align-items:center;gap:8px;padding:7px 12px;cursor:pointer;
          border-bottom:1px solid var(--border);transition:background .1s;"
          onmouseover="this.style.background='rgba(99,102,241,.1)'"
          onmouseout="this.style.background=''"
          onmousedown="window._wlPickSug(${i})">
          <span style="font-size:12px;font-weight:700;color:var(--text);min-width:52px;">${escHtml(r.symbol)}</span>
          <span style="font-size:11px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escHtml(r.name)}</span>
          ${r.tradable ? '' : '<span style="font-size:10px;color:#F59E0B;margin-left:auto;flex-shrink:0;">not tradable</span>'}
        </div>`).join('');
      sugEl.style.display = 'block';
    }

    window._wlPickSug = function(i) {
      const r = _sugItems[i];
      if (!r) return;
      addInp.value = r.symbol;
      _hideSug();
      _doAdd();
    };

    addInp.addEventListener('input', () => {
      clearTimeout(_sugDebounce);
      const q = addInp.value.trim();
      if (q.length < 1) { _hideSug(); return; }
      _sugDebounce = setTimeout(async () => {
        try {
          const res = await fetch(`/api/assets/search?q=${encodeURIComponent(q)}`);
          if (res.ok) _renderSug(await res.json());
        } catch { _hideSug(); }
      }, 180);
    });

    addInp.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        _sugSelected = Math.min(_sugSelected + 1, _sugItems.length - 1);
        _highlightSug();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        _sugSelected = Math.max(_sugSelected - 1, -1);
        _highlightSug();
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (_sugSelected >= 0 && _sugItems[_sugSelected]) {
          addInp.value = _sugItems[_sugSelected].symbol;
          _hideSug();
        }
        _doAdd();
      } else if (e.key === 'Escape') {
        _hideSug();
      }
    });

    function _highlightSug() {
      sugEl.querySelectorAll('[data-i]').forEach(el => {
        el.style.background = Number(el.dataset.i) === _sugSelected ? 'rgba(99,102,241,.2)' : '';
      });
    }

    document.addEventListener('click', e => {
      if (!addInp.contains(e.target) && !sugEl.contains(e.target)) _hideSug();
    });

    // ── Add symbol ──
    async function _doAdd() {
      const sym = addInp.value.trim().toUpperCase();
      if (!sym || !_wlId) return;
      if (_wlSymbols.includes(sym)) { addInp.value = ''; _hideSug(); return; }
      addBtn.disabled = true;
      try {
        await api(`/api/watchlists/${_wlId}/symbols`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol: sym }),
        });
        addInp.value = '';
        addInp.focus();
        _hideSug();
        await _wlLoad();
      } catch { alert('Could not add symbol.'); }
      finally { addBtn.disabled = false; }
    }

    addBtn.addEventListener('click', _doAdd);

    _wlLoad();
    setInterval(() => { if (_wlSymbols.length) _wlRefreshPrices(); }, 30_000);
  })();

  // ── Start pollers ──
  fetchPerfChart('1D', '5Min');

  createPoller(fetchAccount,    30_000).start();
  createPoller(fetchPerformance,30_000).start();
  createPoller(fetchSignals,    60_000).start();
  createPoller(fetchStrategies, 30_000).start();
  createPoller(fetchPositions,  30_000).start();
  createPoller(fetchOrders,     30_000).start();
  createPoller(fetchClock,      10_000).start();
}

// ─────────────────────────────────────────
// ── Logout ──────────────────────────────────────────────────────────────────
// ── Theme toggle ─────────────────────────────────────────────────────────────
(function initTheme() {
  const saved = localStorage.getItem('tb_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);

  // Inject toggle button into every sidebar footer, after the logout button
  document.addEventListener('DOMContentLoaded', () => {
    const footer = document.querySelector('.sidebar-footer');
    if (!footer) return;

    const btn = document.createElement('button');
    btn.className = 'theme-toggle-btn';
    btn.id = 'theme-toggle';
    _updateThemeBtn(btn, saved);
    btn.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme') || 'dark';
      const next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('tb_theme', next);
      _updateThemeBtn(btn, next);
    });
    footer.appendChild(btn);
  });
})();

function _chartTheme() {
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}

function _updateThemeBtn(btn, theme) {
  if (theme === 'light') {
    btn.innerHTML = `<svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg> Dark Mode`;
  } else {
    btn.innerHTML = `<svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg> Light Mode`;
  }
}

async function doLogout() {
  try { await fetch('/api/auth/logout', { method: 'POST' }); } catch {}
  window.location.href = '/static/login.html';
}

// ── Strategy icons ───────────────────────────────────────────────────────────
function stratIcon(name, active) {
  const c = active ? '#a78bfa' : '#64748b';
  const icons = {
    momentum:  `<polyline points="23 6 13.5 15.5 8.5 10.5 1 18" stroke="${c}"/><polyline points="17 6 23 6 23 12" stroke="${c}"/>`,
    sma_cross: `<line x1="18" y1="20" x2="18" y2="10" stroke="${c}"/><line x1="12" y1="20" x2="12" y2="4" stroke="${c}"/><line x1="6" y1="20" x2="6" y2="14" stroke="${c}"/>`,
    rsi_mr:    `<circle cx="12" cy="12" r="10" stroke="${c}"/><path d="M8 14s1.5 2 4 2 4-2 4-2" stroke="${c}"/><line x1="9" y1="9" x2="9.01" y2="9" stroke="${c}" stroke-width="3"/><line x1="15" y1="9" x2="15.01" y2="9" stroke="${c}" stroke-width="3"/>`,
    bollinger: `<rect x="3" y="5" width="18" height="14" rx="1" stroke="${c}"/><path d="M8 12h8" stroke="${c}"/><path d="M12 8v8" stroke="${c}"/>`,
    breakout_52w: `<polyline points="22 12 18 12 15 21 9 3 6 12 2 12" stroke="${c}"/>`,
    macd_volume:  `<path d="M3 3v18h18" stroke="${c}"/><path d="M7 16l4-8 4 5 3-3" stroke="${c}"/>`,
    golden_cross: `<circle cx="12" cy="12" r="5" stroke="${c}"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4" stroke="${c}"/>`,
  };
  const path = icons[name] || `<circle cx="12" cy="12" r="8" stroke="${c}"/>`;
  return `<svg width="14" height="14" fill="none" stroke-width="1.8" viewBox="0 0 24 24">${path}</svg>`;
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function toggleExplanation(signalId, btnEl) {
  const parentTr = btnEl.closest('tr');
  const existing = parentTr.nextElementSibling;
  if (existing && existing.classList.contains('explanation-row') && existing.dataset.signalId === String(signalId)) {
    existing.remove();
    return;
  }
  btnEl.disabled = true;
  btnEl.textContent = 'Loading…';
  let text;
  try {
    const data = await api(`/api/signals/${signalId}/explanation`);
    text = (data.explanation) ? escHtml(data.explanation) : 'No AI explanation available for this trade.';
  } catch (e) {
    text = 'Failed to load explanation.';
  }
  btnEl.disabled = false;
  btnEl.textContent = 'Explain';
  const expTr = document.createElement('tr');
  expTr.className = 'explanation-row';
  expTr.dataset.signalId = String(signalId);
  expTr.innerHTML = `<td colspan="8"><div class="explanation-text">${text}</div></td>`;
  parentTr.insertAdjacentElement('afterend', expTr);
}

// initBots — bots.html
// ─────────────────────────────────────────
async function initBots() {
  const chipEl = document.getElementById('market-chip');
  let clock = await initClockChip(chipEl);
  const marketOpen = clock ? clock.is_open : null;

  let killSwitchState = null;
  let currentAccount  = null;

  // ── Kill switch UI ─────────────────────────────────────────────────────────
  function applyKillSwitchUI(on) {
    killSwitchState = on;
    document.getElementById('banner-kill').classList.toggle('hidden', !on);
    const btn = document.getElementById('btn-ks');
    if (btn) {
      btn.textContent = on ? 'Kill Switch OFF' : 'Kill Switch ON';
      btn.className   = 'btn ' + (on ? 'btn-ghost' : 'btn-danger');
      btn.classList.remove('hidden');
    }
    updateRunBtnState();
  }

  function updateRunBtnState() {
    const btn = document.getElementById('btn-run-now');
    if (!btn) return;
    if (killSwitchState === null) {
      btn.disabled = true;
      btn.title = 'Checking kill switch status…';
    } else if (killSwitchState === true) {
      btn.disabled = true;
      btn.title = 'Kill switch is active.';
    } else {
      btn.disabled = false;
      btn.title = marketOpen ? '' : 'Market is closed — engine will run but skip trading.';
    }
  }

  // ── Initial data load ──────────────────────────────────────────────────────
  async function loadData() {
    let accounts, strats, engineStatus, risk;
    try {
      [accounts, strats, engineStatus, risk] = await Promise.all([
        api('/api/broker-accounts', { key: 'bots-accounts' }),
        api('/api/strategies',      { key: 'bots-strats'   }),
        api('/api/engine',          { key: 'bots-engine'   }),
        api('/api/risk',            { key: 'bots-risk'     }),
      ]);
    } catch { return; }

    applyKillSwitchUI(risk.kill_switch);

    const hasPaper = accounts.some(a => a.account_type === 'paper');
    document.getElementById('banner-paper').classList.toggle('hidden', !hasPaper);
    document.getElementById('paper-badge')?.classList.toggle('hidden', !hasPaper);

    const enabledCount = strats.filter(s => s.enabled).length;
    document.getElementById('engine-meta').textContent =
      `${enabledCount} of ${strats.length} strategies globally enabled · ` +
      `Last run: ${engineStatus.ts ? fmt.time(engineStatus.ts) : 'Never'}`;

    renderAccountPanel(accounts);

    if (accounts.length > 0) {
      await selectAccount(accounts[0]);
    } else {
      document.getElementById('panel-title').textContent = 'No broker accounts';
      document.getElementById('panel-meta').textContent = '';
      document.getElementById('assigned-list').innerHTML =
        '<div class="empty-state"><div class="empty-state-icon">&#x1F511;</div>' +
        '<div class="empty-state-title">No accounts connected</div>' +
        '<div class="empty-state-desc">Add a broker account to start enabling strategies.</div></div>';
    }
  }

  // ── Left panel ─────────────────────────────────────────────────────────────
  function renderAccountPanel(accounts) {
    const list = document.getElementById('acct-list');
    list.innerHTML = '';
    accounts.forEach(acct => {
      const item = document.createElement('div');
      item.className = 'acct-item' + (currentAccount?.id === acct.id ? ' active' : '');
      item.dataset.acctId = acct.id;
      item.onclick = () => selectAccount(acct);

      const dot = document.createElement('div');
      dot.className = 'acct-dot';
      dot.style.background = acct.account_type === 'live' ? '#f59e0b' : '#3b82f6';

      const lbl = document.createElement('div');
      lbl.className = 'acct-item-label';
      lbl.innerHTML = `<div class="acct-item-name">${escHtml(acct.label)}</div>` +
        `<div class="acct-item-type">${acct.account_type === 'live' ? 'Live trading' : 'Paper trading'}</div>`;

      const badge = document.createElement('span');
      badge.className = 'badge ' + (acct.account_type === 'live' ? 'b-live' : 'b-paper');
      badge.textContent = acct.account_type;

      item.append(dot, lbl, badge);
      list.appendChild(item);
    });
  }

  // ── Right panel ────────────────────────────────────────────────────────────
  async function selectAccount(acct) {
    currentAccount = acct;
    document.querySelectorAll('.acct-item').forEach(el => {
      el.classList.toggle('active', el.dataset.acctId == acct.id);
    });

    document.getElementById('panel-title').textContent =
      `${acct.label} — ${acct.account_type === 'live' ? 'Live' : 'Paper'}`;
    document.getElementById('panel-meta').textContent = 'Loading…';

    let acctStrats;
    try {
      acctStrats = await api(`/api/broker-accounts/${acct.id}/strategies`,
        { key: `bots-acct-strats-${acct.id}` });
    } catch {
      document.getElementById('panel-meta').textContent = 'Failed to load';
      return;
    }
    renderStratPanel(acct, acctStrats);
  }

  function renderStratPanel(acct, acctStrats) {
    const enabledCount = acctStrats.filter(s => s.enabled).length;
    document.getElementById('panel-meta').textContent =
      `${enabledCount} of ${acctStrats.length} strategies enabled`;

    const aList = document.getElementById('assigned-list');
    aList.innerHTML = '';
    if (acctStrats.length === 0) {
      aList.innerHTML = '<div style="padding:.85rem 1.25rem;font-size:12px;color:#64748B;font-style:italic;">No strategies available.</div>';
    } else {
      acctStrats.forEach(s => aList.appendChild(buildStratRow(acct, s)));
    }
  }

  function buildStratRow(acct, s) {
    const wrap = document.createElement('div');

    // ── Main row ──
    const row = document.createElement('div');
    row.className = 'strat-row';

    const icon = document.createElement('div');
    icon.className = 'strat-icon ' + (s.enabled ? 'si-active' : 'si-inactive');
    icon.innerHTML = stratIcon(s.name, s.enabled);

    const info = document.createElement('div');
    info.className = 'strat-info';
    const hasWindow = s.active_start && s.active_end;
    const schedLabel = hasWindow
      ? `<span style="color:#3B82F6;font-size:10px;margin-left:.4rem;">&#x23F0; ${s.active_start}–${s.active_end} ET</span>`
      : '';
    info.innerHTML = `<div class="strat-name">${escHtml(s.label)}${schedLabel}</div>` +
      `<div class="strat-desc">${escHtml(s.description)}</div>`;

    const actions = document.createElement('div');
    actions.className = 'strat-actions';

    const statusBadge = document.createElement('span');
    if (s.enabled) {
      statusBadge.className = 'badge b-enabled';
      statusBadge.innerHTML = '<span class="pdot"></span> Running';
    } else {
      statusBadge.className = 'badge b-paused';
      statusBadge.textContent = 'Paused';
    }

    // Configure button (params)
    const cfgBtn = document.createElement('button');
    cfgBtn.className = 'btn-remove';
    cfgBtn.title = 'Configure parameters';
    cfgBtn.innerHTML = `<svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`;
    cfgBtn.onclick = () => openConfigureModal(s);

    // Schedule expand button
    const schedBtn = document.createElement('button');
    schedBtn.className = 'btn-remove';
    schedBtn.title = 'Set active hours';
    schedBtn.innerHTML = `<svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`;

    const toggle = document.createElement('div');
    toggle.className = 'strat-toggle' + (s.enabled ? ' on' : '');
    toggle.title = s.enabled ? 'Disable on this account' : 'Enable on this account';
    toggle.onclick = async () => {
      toggle.classList.add('disabled');
      try {
        await api(`/api/strategies/${s.name}/accounts/${acct.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: !s.enabled }),
          key: `bots-toggle-${s.name}-${acct.id}`,
        });
        await selectAccount(acct);
      } catch { toggle.classList.remove('disabled'); }
    };

    actions.append(statusBadge, cfgBtn, schedBtn, toggle);
    row.append(icon, info, actions);

    // ── Schedule sub-row (hidden by default) ──
    const schedRow = document.createElement('div');
    schedRow.style.cssText = 'display:none;padding:.5rem 1.25rem .65rem 3.5rem;border-bottom:1px solid var(--border);background:rgba(15,23,42,.5);';
    schedRow.innerHTML = `
      <div style="display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;">
        <span style="font-size:11px;color:#64748B;white-space:nowrap;">Active hours (ET):</span>
        <input type="time" class="input" id="sched-start-${s.name}" value="${s.active_start || ''}"
          style="width:120px;padding:.25rem .5rem;font-size:12px;height:28px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;color-scheme:dark;">
        <span style="font-size:11px;color:#64748B;">to</span>
        <input type="time" class="input" id="sched-end-${s.name}" value="${s.active_end || ''}"
          style="width:120px;padding:.25rem .5rem;font-size:12px;height:28px;background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:6px;color-scheme:dark;">
        <button class="btn btn-primary" id="sched-save-${s.name}"
          style="font-size:11px;padding:.25rem .65rem;height:28px;">Save</button>
        <button class="btn btn-ghost" id="sched-clear-${s.name}"
          style="font-size:11px;padding:.25rem .65rem;height:28px;">Clear</button>
        <span id="sched-msg-${s.name}" style="font-size:11px;color:#10B981;display:none;">Saved</span>
      </div>`;

    schedBtn.onclick = () => {
      const visible = schedRow.style.display !== 'none';
      schedRow.style.display = visible ? 'none' : 'block';
    };

    const saveSchedule = async (start, end) => {
      const msgEl = document.getElementById(`sched-msg-${s.name}`);
      try {
        await api(`/api/strategies/${s.name}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ active_start: start, active_end: end }),
          key: `sched-${s.name}`,
        });
        // Update inline label
        const newLabel = (start && end)
          ? `<span style="color:#3B82F6;font-size:10px;margin-left:.4rem;">&#x23F0; ${start}–${end} ET</span>`
          : '';
        info.querySelector('.strat-name').innerHTML = `${escHtml(s.label)}${newLabel}`;
        s.active_start = start || null;
        s.active_end   = end   || null;
        if (msgEl) { msgEl.style.display = 'inline'; setTimeout(() => { msgEl.style.display = 'none'; }, 2000); }
      } catch {
        if (msgEl) { msgEl.style.color = '#EF4444'; msgEl.textContent = 'Failed'; msgEl.style.display = 'inline';
          setTimeout(() => { msgEl.style.display = 'none'; msgEl.style.color = '#10B981'; msgEl.textContent = 'Saved'; }, 2500); }
      }
    };

    // Wire save/clear after DOM is appended (buttons exist in schedRow)
    setTimeout(() => {
      document.getElementById(`sched-save-${s.name}`)?.addEventListener('click', () => {
        const start = document.getElementById(`sched-start-${s.name}`)?.value;
        const end   = document.getElementById(`sched-end-${s.name}`)?.value;
        if (!start || !end) {
          const msgEl = document.getElementById(`sched-msg-${s.name}`);
          if (msgEl) { msgEl.style.color = '#F59E0B'; msgEl.textContent = 'Enter both start and end times'; msgEl.style.display = 'inline'; setTimeout(() => { msgEl.style.display = 'none'; msgEl.style.color = '#10B981'; msgEl.textContent = 'Saved'; }, 2500); }
          return;
        }
        saveSchedule(start, end);
      });
      document.getElementById(`sched-clear-${s.name}`)?.addEventListener('click', () => {
        document.getElementById(`sched-start-${s.name}`).value = '';
        document.getElementById(`sched-end-${s.name}`).value   = '';
        saveSchedule('', '');
      });
    }, 0);

    wrap.append(row, schedRow);
    return wrap;
  }

  // ── Configure Strategy modal ───────────────────────────────────────────────
  function openConfigureModal(s) {
    const modal   = document.getElementById('modal-configure');
    const titleEl = document.getElementById('cfg-modal-title');
    const bodyEl  = document.getElementById('cfg-modal-body');
    const msgEl   = document.getElementById('cfg-modal-msg');

    titleEl.textContent = `Configure: ${s.label}`;
    msgEl.textContent = '';
    bodyEl.innerHTML = '';

    const schema = s.params_schema || [];
    const params = s.params || {};

    if (!schema.length) {
      bodyEl.innerHTML = '<div style="font-size:13px;color:var(--muted);">This strategy has no configurable parameters.</div>';
    }

    // Track bool toggle state separately
    const boolState = {};

    schema.forEach(field => {
      const wrap = document.createElement('div');
      wrap.className = 'cfg-field';
      const val = params[field.key] !== undefined ? params[field.key] : '';

      if (field.type === 'bool') {
        boolState[field.key] = !!val;
        wrap.innerHTML = `
          <div class="cfg-toggle-row">
            <div class="cfg-toggle-text">
              <div class="cfg-label">${escHtml(field.label)}</div>
              ${field.hint ? `<div class="cfg-hint">${escHtml(field.hint)}</div>` : ''}
            </div>
            <div class="cfg-bool-toggle${val ? ' on' : ''}" data-key="${escHtml(field.key)}"></div>
          </div>`;
        wrap.querySelector('.cfg-bool-toggle').onclick = function() {
          boolState[field.key] = !boolState[field.key];
          this.classList.toggle('on', boolState[field.key]);
        };

      } else if (field.type === 'symbols') {
        const displayVal = Array.isArray(val) ? val.join(', ') : (val || '');
        wrap.innerHTML = `
          <div class="cfg-label">${escHtml(field.label)}</div>
          ${field.hint ? `<div class="cfg-hint">${escHtml(field.hint)}</div>` : ''}
          <input class="cfg-input" data-key="${escHtml(field.key)}" data-type="symbols"
            type="text" value="${escHtml(displayVal)}" placeholder="e.g. BTC, ETH, SOL">`;

      } else if (field.type === 'number') {
        const minAttr = field.min !== undefined ? `min="${field.min}"` : '';
        const maxAttr = field.max !== undefined ? `max="${field.max}"` : '';
        const stepAttr = Number.isInteger(field.min) && Number.isInteger(field.max) ? 'step="1"' : 'step="any"';
        wrap.innerHTML = `
          <div class="cfg-label">${escHtml(field.label)}</div>
          ${field.hint ? `<div class="cfg-hint">${escHtml(field.hint)}</div>` : ''}
          <input class="cfg-input" data-key="${escHtml(field.key)}" data-type="number"
            type="number" value="${val !== null && val !== undefined ? val : ''}" ${minAttr} ${maxAttr} ${stepAttr}>`;
      }

      bodyEl.appendChild(wrap);
    });

    modal.classList.remove('hidden');

    document.getElementById('cfg-cancel').onclick = () => modal.classList.add('hidden');
    modal.onclick = e => { if (e.target === modal) modal.classList.add('hidden'); };

    document.getElementById('cfg-save').onclick = async () => {
      const updated = {};
      schema.forEach(field => {
        if (field.type === 'bool') {
          updated[field.key] = boolState[field.key];
        } else {
          const input = bodyEl.querySelector(`[data-key="${field.key}"]`);
          if (!input) return;
          if (field.type === 'symbols') {
            updated[field.key] = input.value.split(',').map(x => x.trim().toUpperCase()).filter(Boolean);
          } else if (field.type === 'number') {
            const n = parseFloat(input.value);
            updated[field.key] = isNaN(n) ? null : n;
          }
        }
      });

      msgEl.style.color = '#64748B';
      msgEl.textContent = 'Saving…';
      try {
        await api(`/api/strategies/${s.name}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ params: updated }),
          key: `cfg-save-${s.name}`,
        });
        Object.assign(s.params, updated);
        msgEl.style.color = '#10B981';
        msgEl.textContent = 'Saved successfully.';
        setTimeout(() => modal.classList.add('hidden'), 900);
      } catch {
        msgEl.style.color = '#EF4444';
        msgEl.textContent = 'Save failed. Please try again.';
      }
    };
  }

  // ── Engine controls ────────────────────────────────────────────────────────
  document.getElementById('btn-run-now').addEventListener('click', () => {
    openModal(document.getElementById('modal-run'), runEngine);
  });

  document.getElementById('btn-ks').addEventListener('click', () => {
    const on = killSwitchState;
    openModal(
      document.getElementById(on ? 'modal-ks-off' : 'modal-ks-on'),
      () => setKillSwitch(!on)
    );
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
      resultEl.innerHTML = '';
      const lines = [
        'Strategies evaluated: ' + (result.ran?.length || 0),
        'Signals generated: '    + (result.signals?.length || 0),
      ];
      if (result.error) lines.push('Engine error: ' + result.error);
      errors.forEach(e => lines.push('Error in ' + e.strategy + ': ' + e.error));
      lines.forEach(line => {
        const p = document.createElement('div'); p.textContent = line; resultEl.appendChild(p);
      });
      resultEl.classList.remove('hidden');
      setTimeout(() => resultEl.classList.add('hidden'), 10_000);

      const engineStatus = await api('/api/engine', { key: 'bots-engine-post' });
      const strats = await api('/api/strategies', { key: 'bots-strats-post' });
      const enabledCount = strats.filter(s => s.enabled).length;
      document.getElementById('engine-meta').textContent =
        `${enabledCount} of ${strats.length} strategies globally enabled · ` +
        `Last run: ${engineStatus.ts ? fmt.time(engineStatus.ts) : 'Never'}`;
    } catch {
      resultEl.className = 'result-panel error';
      resultEl.textContent = 'Action failed — check logs.';
      resultEl.classList.remove('hidden');
    } finally {
      btn.innerHTML = '<svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg> Run Now';
      updateRunBtnState();
    }
  }

  async function setKillSwitch(on) {
    try {
      const res = await api('/api/risk/kill_switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ on }),
        key: 'bots-ks',
      });
      applyKillSwitchUI(res.kill_switch);
    } catch {}
  }

  updateRunBtnState();
  await loadData();
}


// ─────────────────────────────────────────
// initPositions — positions.html
// ─────────────────────────────────────────
async function initPositions() {
  initClockChip(document.getElementById('market-chip'));

  // Account selector for positions/orders
  let posAccountId = null;
  let moAccountId  = null;

  async function buildAccountSelectors() {
    try {
      const accounts = await api('/api/broker-accounts', { key: 'pos-acct-list' });
      if (!accounts || accounts.length < 2) return;

      function makeSelect(wrapId, onChange) {
        const wrap = document.getElementById(wrapId);
        if (!wrap) return;
        const sel = document.createElement('select');
        sel.className = 'acct-sel';
        const all = document.createElement('option');
        all.value = ''; all.textContent = 'All accounts';
        sel.appendChild(all);
        accounts.forEach(a => {
          const opt = document.createElement('option');
          opt.value = a.id; opt.textContent = a.label || `Account ${a.id}`;
          sel.appendChild(opt);
        });
        sel.addEventListener('change', () => onChange(sel.value ? parseInt(sel.value) : null));
        wrap.appendChild(sel);
      }

      makeSelect('pos-account-wrap', id => { posAccountId = id; fetchPositions(); fetchOrders(); });
      makeSelect('mo-account-wrap',  id => { moAccountId  = id; });
    } catch {}
  }
  buildAccountSelectors();

  document.getElementById('btn-close-all')?.addEventListener('click', closeAll);

  async function closePosition(symbol) {
    if (!confirm(`Close position in ${symbol}? This will submit a market sell order.`)) return;
    const qs = posAccountId ? `?account_id=${posAccountId}` : '';
    try {
      await api(`/api/positions/${encodeURIComponent(symbol)}${qs}`, { method: 'DELETE' });
      fetchPositions();
    } catch (e) {
      alert(`Failed to close ${symbol}: ${e.message || e}`);
    }
  }

  async function closeAll() {
    if (!confirm('Close ALL open positions? This will submit market sell orders for every open position.')) return;
    const qs = posAccountId ? `?account_id=${posAccountId}` : '';
    try {
      await api(`/api/positions${qs}`, { method: 'DELETE' });
      fetchPositions();
    } catch (e) {
      alert(`Failed to close all positions: ${e.message || e}`);
    }
  }

  async function fetchPositions() {
    const tbody = document.getElementById('pos-body');
    const closeAllBtn = document.getElementById('btn-close-all');
    const qs = posAccountId ? `?account_id=${posAccountId}` : '';
    try {
      const positions = await api(`/api/positions${qs}`, { key: 'pos-positions' });
      tbody.innerHTML = '';
      if (!positions.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="state-empty">No open positions.</td></tr>';
        if (closeAllBtn) closeAllBtn.classList.add('hidden');
        return;
      }
      if (closeAllBtn) closeAllBtn.classList.remove('hidden');
      positions.forEach(p => {
        const tr = document.createElement('tr');
        const pnl = parseFloat(p.unrealized_pl) || 0;
        const vals = [
          p.symbol,
          p.side,
          (parseFloat(p.qty) || 0).toFixed(4).replace(/\.?0+$/, ''),
          fmt.usd(p.avg_entry_price),
          fmt.usd(p.current_price),
          fmt.usd(p.market_value),
          '', // pnl — handled below
          '', // close button — handled below
        ];
        vals.forEach((v, i) => {
          const td = document.createElement('td');
          if (i === 6) {
            td.textContent = fmt.usdSigned(pnl, '—');
            td.className = 'text-tabular ' + (pnl >= 0 ? 'text-green glow-green' : 'text-red glow-red');
          } else if (i === 7) {
            const btn = document.createElement('button');
            btn.className = 'btn-close-pos';
            btn.title = `Close ${p.symbol}`;
            btn.textContent = '×';
            btn.addEventListener('click', () => closePosition(p.symbol));
            td.appendChild(btn);
          } else { td.textContent = v; }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    } catch (e) {
      if (e.name === 'AbortError') return;
      tbody.innerHTML = '<tr><td colspan="8" class="state-error">Failed to load — retrying in 30s</td></tr>';
    }
  }

  let currentStatus = 'all';
  async function fetchOrders() {
    const tbody = document.getElementById('orders-body');
    const qs = posAccountId ? `&account_id=${posAccountId}` : '';
    try {
      const orders = await api(`/api/orders?status=${currentStatus}&limit=50${qs}`, { key: 'pos-orders' });
      tbody.innerHTML = '';
      if (!orders.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="state-empty">No orders.</td></tr>';
        return;
      }
      orders.forEach(o => {
        const tr = document.createElement('tr');
        const fields = [fmt.time(o.submitted_at), o.symbol, '', (o.qty || o.filled_qty || 0), o.status, fmt.time(o.filled_at)];
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
      tbody.innerHTML = '<tr><td colspan="6" class="state-error">Failed to load &mdash; retrying in 30s</td></tr>';
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

  // Positions CSV export
  const exportPosBtn = document.getElementById('export-positions-btn');
  if (exportPosBtn) {
    exportPosBtn.addEventListener('click', () => {
      const qs = posAccountId ? `?account_id=${posAccountId}` : '';
      const a = document.createElement('a');
      a.href = `/api/export/positions${qs}`;
      a.download = 'tradebot_positions.csv';
      a.click();
    });
  }

  // ── Manual order ticket ──────────────────────────────────────────────
  let moSide = 'buy';
  let moMidPrice = 0;

  const buyBtn          = document.getElementById('mo-buy-btn');
  const sellBtn         = document.getElementById('mo-sell-btn');
  const submitBtn       = document.getElementById('mo-submit');
  const modeQtyBtn      = document.getElementById('mo-mode-qty');
  const modeNotionalBtn = document.getElementById('mo-mode-notional');
  const qtyLabel        = document.getElementById('mo-qty-label');
  const symInput        = document.getElementById('mo-sym-input');
  const qtyInput        = document.getElementById('mo-qty-input');
  const priceInput      = document.getElementById('mo-price-input');
  const priceWrap       = document.getElementById('mo-price-wrap');
  const resultEl        = document.getElementById('mo-result');
  const estTotal        = document.getElementById('mo-est-total');
  const quoteDisplay    = document.getElementById('mo-quote-display');

  function updateEstTotal() {
    if (!estTotal) return;
    const qty = parseFloat(qtyInput?.value) || 0;
    if (!qty || !moMidPrice || !modeIsQty) { estTotal.textContent = ''; return; }
    const limitVal = parseFloat(priceInput?.value) || moMidPrice;
    const est = qty * limitVal;
    estTotal.textContent = '≈ $' + est.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function setMoSide(side) {
    moSide = side;
    const isBuy = side === 'buy';
    buyBtn?.classList.toggle('mot-tab-active', isBuy);
    sellBtn?.classList.toggle('mot-tab-active', !isBuy);
    if (submitBtn) {
      submitBtn.classList.toggle('mot-submit-buy',  isBuy);
      submitBtn.classList.toggle('mot-submit-sell', !isBuy);
      const _sym = symInput?.value.trim().toUpperCase() || '';
      const _sl  = _sym ? ' ' + _sym : '';
      submitBtn.innerHTML = isBuy
        ? '<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg> Buy' + _sl
        : '<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg> Sell' + _sl;
    }
  }

  buyBtn?.addEventListener('click',  () => setMoSide('buy'));
  sellBtn?.addEventListener('click', () => setMoSide('sell'));

  let modeIsQty = true;
  function setMoMode(isQty) {
    modeIsQty = isQty;
    modeQtyBtn?.classList.toggle('mot-toggle-active', isQty);
    modeNotionalBtn?.classList.toggle('mot-toggle-active', !isQty);
    if (isQty) {
      if (qtyLabel) qtyLabel.textContent = 'Shares';
      if (qtyInput) { qtyInput.placeholder = '0'; qtyInput.step = 'any'; }
      if (priceWrap) priceWrap.style.display = '';
    } else {
      if (qtyLabel) qtyLabel.textContent = 'USD Value';
      if (qtyInput) { qtyInput.placeholder = '0.00'; qtyInput.step = '0.01'; }
      if (priceWrap) priceWrap.style.display = 'none';
      if (priceInput) priceInput.value = '';
    }
    updateEstTotal();
  }
  modeQtyBtn?.addEventListener('click',      () => setMoMode(true));
  modeNotionalBtn?.addEventListener('click', () => setMoMode(false));

  let quoteTimer = null;

  async function fetchQuote(sym) {
    if (!quoteDisplay || !sym) return;
    quoteDisplay.textContent = 'Fetching price…';
    moMidPrice = 0;
    try {
      const res = await fetch('/api/quote/' + encodeURIComponent(sym));
      if (!res.ok) throw new Error('not found');
      const q = await res.json();
      const bid = parseFloat(q.bid) || 0;
      const ask = parseFloat(q.ask) || 0;
      const mid = bid && ask ? (bid + ask) / 2 : bid || ask;
      if (!mid) { quoteDisplay.textContent = 'No quote available'; return; }
      moMidPrice = mid;
      quoteDisplay.textContent = 'Bid $' + bid.toFixed(2) + ' · Ask $' + ask.toFixed(2) + ' · Mid $' + mid.toFixed(2);
      if (priceInput && !priceInput.value) priceInput.value = mid.toFixed(2);
      updateEstTotal();
      setMoSide(moSide); // refresh button label with symbol
    } catch {
      quoteDisplay.textContent = 'Symbol not found';
      quoteDisplay.style.background = 'rgba(239,68,68,.1)';
      quoteDisplay.style.borderColor = 'rgba(239,68,68,.3)';
      quoteDisplay.style.color = '#DC2626';
      moMidPrice = 0;
    }
  }

  qtyInput?.addEventListener('input', updateEstTotal);
  priceInput?.addEventListener('input', updateEstTotal);

  symInput?.addEventListener('input', () => {
    symInput.value = symInput.value.toUpperCase();
    clearTimeout(quoteTimer);
    if (priceInput) priceInput.value = '';
    if (quoteDisplay) {
      quoteDisplay.textContent = '';
      quoteDisplay.style.background = '';
      quoteDisplay.style.borderColor = '';
      quoteDisplay.style.color = '';
    }
    moMidPrice = 0;
    updateEstTotal();
    setMoSide(moSide); // refresh button label as symbol changes
    const sym = symInput.value.trim();
    if (sym.length >= 1) quoteTimer = setTimeout(() => fetchQuote(sym), 600);
  });

  submitBtn?.addEventListener('click', () => {
    const sym      = symInput?.value.trim().toUpperCase();
    const rawVal   = qtyInput?.value.trim();
    const rawPrice = priceInput?.value.trim();
    if (!sym || !rawVal) { resultEl.textContent = 'Enter a symbol and amount.'; resultEl.className = 'mo-result err'; return; }

    const qty        = modeIsQty ? parseFloat(rawVal) : null;
    const notional   = !modeIsQty ? parseFloat(rawVal) : null;
    const limitPrice = modeIsQty && rawPrice ? parseFloat(rawPrice) : null;
    const unitLabel  = modeIsQty ? 'shares' : 'USD';
    const sideLabel  = moSide === 'buy' ? 'BUY' : 'SELL';
    const priceLabel = limitPrice ? ` @ $${limitPrice.toFixed(2)} limit` : ' at market price';

    const bodyEl  = document.getElementById('modal-mo-body');
    const titleEl = document.getElementById('modal-mo-title');
    const confBtn = document.getElementById('modal-mo-confirm-btn');
    if (bodyEl) bodyEl.textContent = `${sideLabel} ${rawVal} ${unitLabel} of ${sym}${priceLabel}.`;
    if (titleEl) titleEl.textContent = `Confirm ${sideLabel} Order`;
    if (confBtn) {
      confBtn.style.background = moSide === 'buy' ? 'var(--green)' : 'var(--red)';
      confBtn.textContent = moSide === 'buy' ? 'Buy Now' : 'Sell Now';
    }

    openModal(document.getElementById('modal-mo-confirm'), async () => {
      submitBtn.disabled = true;
      resultEl.textContent = 'Submitting&hellip;';
      resultEl.className = 'mo-result';
      try {
        const body = { symbol: sym, side: moSide, account_id: moAccountId ?? null };
        if (qty)         body.qty         = qty;
        if (notional)    body.notional    = notional;
        if (limitPrice)  body.limit_price = limitPrice;
        const res = await api('/api/orders', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
        resultEl.textContent = `✓ Order placed: ${(res.id || '').slice(0,8) || 'OK'}`;
        resultEl.className = 'mo-result ok';
        setTimeout(() => fetchOrders(), 1000);
      } catch (err) {
        resultEl.textContent = `✕ ${err.message}`;
        resultEl.className = 'mo-result err';
      } finally {
        submitBtn.disabled = false;
      }
    });
  });

  createPoller(fetchPositions, 30_000).start();
  createPoller(fetchOrders,    30_000).start();
}

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
        // Status badge
        const statusTd = document.createElement('td');
        statusTd.innerHTML = s.enabled
          ? '<span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600;color:#10B981;"><span style="width:6px;height:6px;border-radius:50%;background:#10B981;display:inline-block;"></span>Active</span>'
          : '<span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600;color:#64748B;"><span style="width:6px;height:6px;border-radius:50%;background:#64748B;display:inline-block;"></span>Disabled</span>';
        tr.appendChild(statusTd);
        [s.strategy, s.total, s.buys, s.sells, s.blocked].forEach(v => {
          const td = document.createElement('td');
          td.textContent = v ?? '0';
          tr.appendChild(td);
        });
        statsTbody.appendChild(tr);
      });
      if (!p.strategy_stats?.length) {
        statsTbody.innerHTML = '<tr><td colspan="6" class="state-empty">No data.</td></tr>';
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
      const chartEl = document.getElementById('daily-chart');
      if (!daily.length) {
        chartEl.innerHTML = '<div class="state-empty" style="height:200px;display:flex;align-items:center;justify-content:center;">No signal activity yet.</div>';
      } else {
        chartEl.innerHTML = '';
        if (dailyChart) dailyChart.destroy();
        const _isLight = _chartTheme() === 'light';
        const _labelClr = _isLight ? '#64748B' : '#94A3B8';
        const _gridClr  = _isLight ? '#E2E8F0' : '#1E2D45';
        const _legClr   = _isLight ? '#0F172A' : '#E6EBF5';
        dailyChart = safeMakeChart(chartEl, {
          series: [
            { name: 'Buys',  data: daily.map(d => ({ x: d.date, y: d.buys  })) },
            { name: 'Sells', data: daily.map(d => ({ x: d.date, y: d.sells })) },
            { name: 'Blocked', data: daily.map(d => ({ x: d.date, y: d.blocked || 0 })) },
          ],
          chart: { type: 'bar', height: 200, toolbar: { show: false }, background: 'transparent', stacked: true },
          colors: ['#10B981', '#EF4444', '#F59E0B'],
          xaxis: { type: 'category', labels: { style: { colors: _labelClr, fontSize: '11px' } }, axisBorder: { show: false } },
          yaxis: { labels: { style: { colors: _labelClr, fontSize: '11px' } }, min: 0, forceNiceScale: true },
          grid: { borderColor: _gridClr, strokeDashArray: 3 },
          legend: { labels: { colors: _legClr } },
          theme: { mode: _chartTheme() },
          tooltip: { theme: _chartTheme() }
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

  async function fetchAttribution() {
    const tbody = document.getElementById('attribution-body');
    if (!tbody) return;
    try {
      const rows = await api('/api/performance/by-account', { key: 'perf-attr' });
      tbody.innerHTML = '';
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="state-empty">No attribution data.</td></tr>'; return;
      }
      rows.forEach(r => {
        const tr = document.createElement('tr');
        [r.strategy, r.account_name || r.account_id || '—', r.total, r.executed, r.blocked].forEach(v => {
          const td = document.createElement('td'); td.textContent = v ?? '0'; tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    } catch (e) {
      if (e.name === 'AbortError') return;
      tbody.innerHTML = '<tr><td colspan="5" class="state-error">Failed to load</td></tr>';
    }
  }

  createPoller(fetchPerformance, 60_000).start();
  createPoller(fetchSignals,     30_000).start();
  createPoller(fetchAttribution, 60_000).start();
  initStrategyHealth();
}

// ── Strategy Health card (performance.html) ───────────────────────────────
async function initStrategyHealth() {
  const tbody  = document.getElementById('sh-tbody');
  const badges = document.getElementById('sh-summary-badges');
  if (!tbody) return;

  let data;
  try {
    data = await api('/api/strategy-health');
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="6" class="state-empty">Failed to load health data.</td></tr>';
    return;
  }

  if (!data || !data.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="state-empty">No strategies registered.</td></tr>';
    return;
  }

  const onTrackCount  = data.filter(d => d.drift_status === 'green' || d.drift_status === 'yellow').length;
  const driftingCount = data.filter(d => d.drift_status === 'red').length;
  if (badges) {
    badges.innerHTML = `
      <span style="font-size:11px;color:var(--muted);">${onTrackCount} on track</span>
      ${driftingCount > 0
        ? `<span class="sh-badge-count">${driftingCount} drifting</span>`
        : `<span class="sh-badge-count sh-badge-ok">All clear</span>`}
    `;
  }

  const pct = v => v != null ? (v * 100).toFixed(1) + '%' : '—';
  const ret = v => v != null ? (v >= 0 ? '+' : '') + v.toFixed(2) + '%' : '—';
  const ago = d => {
    if (!d) return 'Never';
    const diff = Math.floor((Date.now() - new Date(d)) / 3600000);
    if (diff < 1)  return '< 1h ago';
    if (diff < 24) return diff + 'h ago';
    return Math.floor(diff / 24) + 'd ago';
  };
  const statusColor = s => ({ green: 'var(--green)', yellow: 'var(--orange)', red: 'var(--red)' }[s] || 'var(--muted)');

  const pillMap = {
    green:        `<span class="health-pill health-green"><span class="health-dot health-dot-green"></span>On Track</span>`,
    yellow:       `<span class="health-pill health-yellow"><span class="health-dot health-dot-yellow"></span>Watching</span>`,
    red:          `<span class="health-pill health-red"><span class="health-dot health-dot-red"></span>Drifting</span>`,
    no_data:      `<span class="health-pill health-none"><span class="health-dot health-dot-none"></span>Need More Data</span>`,
    no_benchmark: `<span class="health-pill health-none"><span class="health-dot health-dot-none"></span>No Benchmark</span>`,
  };

  let rowParts   = [];
  let detailParts = [];

  data.forEach((d, rowIndex) => {
    const rowId    = `sh-detail-${rowIndex}`;
    const btnId    = `sh-exp-${rowIndex}`;
    const hasBench = d.drift_status !== 'no_benchmark';
    const hasData  = d.drift_status !== 'no_data' && d.drift_status !== 'no_benchmark';
    const color    = statusColor(d.drift_status);

    let wrDelta = '';
    if (hasData && d.benchmark_win_rate != null) {
      const pp  = ((d.live_win_rate - d.benchmark_win_rate) * 100).toFixed(1);
      const cls = pp >= 0 ? 'delta-up' : 'delta-down';
      wrDelta = `<span class="delta-chip ${cls}">${pp >= 0 ? '+' : ''}${pp}pp</span>`;
    }
    let arDelta = '';
    if (hasData && d.benchmark_avg_return_pct != null) {
      const diff = d.live_avg_return_pct - d.benchmark_avg_return_pct;
      const cls  = diff >= 0 ? 'delta-up' : 'delta-down';
      arDelta = `<span class="delta-chip ${cls}">${diff >= 0 ? '+' : ''}${diff.toFixed(2)}%</span>`;
    }

    const benchSub  = hasBench ? `Benchmark: ${d.benchmark_run_name || 'Set'}` : 'No benchmark set';
    const clickable = hasBench ? `style="cursor:pointer;" onclick="shToggle('${rowId}','${btnId}')"` : '';
    const expandBtn = hasBench
      ? `<button class="sh-expand-btn" id="${btnId}" tabindex="-1">
           <svg width="10" height="10" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>
         </button>` : '';

    rowParts.push(`
      <tr ${clickable}>
        <td>${expandBtn}</td>
        <td>
          <div style="font-weight:600;font-size:13px;${!hasBench ? 'color:var(--muted);' : ''}">${d.strategy}</div>
          <div style="font-size:11px;color:#475569;margin-top:1px;">${benchSub}</div>
        </td>
        <td>
          ${hasData ? `<div class="metric-pair">
            <span class="metric-live" style="color:${color};">${pct(d.live_win_rate)}</span>
            <span class="metric-bench">
              <span class="metric-bench-label">BT</span>${pct(d.benchmark_win_rate)}${wrDelta}
            </span>
          </div>` : `<span style="font-size:13px;color:#475569;">—</span>`}
        </td>
        <td>
          ${hasData ? `<div class="metric-pair">
            <span class="metric-live" style="color:${color};">${ret(d.live_avg_return_pct)}</span>
            <span class="metric-bench">
              <span class="metric-bench-label">BT</span>${ret(d.benchmark_avg_return_pct)}${arDelta}
            </span>
          </div>` : `<span style="font-size:13px;color:#475569;">—</span>`}
        </td>
        <td>
          <div style="font-size:13px;font-weight:500;">${d.live_trades} trades</div>
          <div style="font-size:11px;color:#475569;">Last: ${ago(d.last_trade_at)}</div>
        </td>
        <td>${pillMap[d.drift_status] || ''}</td>
      </tr>`);

    if (hasBench) {
      const period = (d.benchmark_start_date && d.benchmark_end_date)
        ? `${d.benchmark_start_date} – ${d.benchmark_end_date}` : '—';
      detailParts.push(`
        <tr class="sh-detail-row" id="${rowId}">
          <td colspan="6" class="sh-detail-cell">
            <div class="sh-detail-inner">
              <div class="sh-detail-item"><span class="sh-detail-label">Benchmark Run</span><span class="sh-detail-val">${d.benchmark_run_name || '—'}</span></div>
              <div class="sh-detail-item"><span class="sh-detail-label">Backtest Period</span><span class="sh-detail-val">${period}</span></div>
              <div class="sh-detail-item"><span class="sh-detail-label">Backtest Win Rate</span><span class="sh-detail-val">${pct(d.benchmark_win_rate)}</span></div>
              <div class="sh-detail-item"><span class="sh-detail-label">Backtest Avg Return</span><span class="sh-detail-val">${ret(d.benchmark_avg_return_pct)} / trade</span></div>
              <div class="sh-detail-item"><span class="sh-detail-label">Backtest Total Trades</span><span class="sh-detail-val">${d.benchmark_total_trades ?? '—'} trades</span></div>
              ${d.drift_status === 'no_data' ? `<div class="sh-detail-item"><span class="sh-detail-label">Live Trades</span><span class="sh-detail-val" style="color:var(--muted);">${d.live_trades} of 10 needed</span></div>` : ''}
              <div class="sh-detail-item" style="margin-left:auto;align-self:center;">
                <a href="/static/backtesting.html?run=${d.benchmark_run_id}" class="btn btn-ghost btn-sm" style="font-size:11px;">
                  <svg width="11" height="11" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                  View Backtest
                </a>
              </div>
            </div>
          </td>
        </tr>`);
    } else {
      detailParts.push(null);
    }
  });

  // Interleave: each data row followed by its detail row (if any)
  let combined = '';
  data.forEach((d, i) => {
    combined += rowParts[i];
    if (detailParts[i]) combined += detailParts[i];
  });
  tbody.innerHTML = combined;
}

function shToggle(detailId, btnId) {
  const row = document.getElementById(detailId);
  const btn = document.getElementById(btnId);
  if (!row || !btn) return;
  const isOpen = row.classList.contains('open');
  row.classList.toggle('open', !isOpen);
  btn.classList.toggle('expanded', !isOpen);
  const poly = btn.querySelector('polyline');
  if (poly) poly.setAttribute('points', isOpen ? '6 9 12 15 18 9' : '18 15 12 9 6 15');
}

// ─────────────────────────────────────────
// initRisk — risk.html
// ─────────────────────────────────────────
async function initRisk() {
  initClockChip(document.getElementById('market-chip'));

  let killState = false;

  function showToast(msg = 'Saved', isError = false) {
    const t = document.getElementById('risk-toast');
    t.textContent = msg;
    t.style.background = isError ? '#EF4444' : '#10B981';
    t.classList.remove('hidden');
    setTimeout(() => t.classList.add('hidden'), 2500);
  }

  async function loadRisk() {
    try {
      const r = await api('/api/risk', { key: 'risk-load' });
      killState = r.kill_switch;
      applyKS(killState);

      document.getElementById('inp-max-loss').value = r.max_daily_loss_pct;
      document.getElementById('inp-max-dt').value   = r.max_day_trades;
      document.getElementById('inp-max-pos').value  = r.max_position_pct;
      document.getElementById('inp-size-pct').value = r.position_size_pct;

      // New inputs
      const s = r.settings || {};
      document.getElementById('inp-consec').value      = s.consecutive_loss_limit  ?? 0;
      document.getElementById('inp-weekly-loss').value = s.weekly_loss_limit_pct   ?? 0;
      document.getElementById('inp-max-orders').value  = s.max_orders_per_day      ?? 0;
      document.getElementById('inp-max-open').value    = s.max_open_positions      ?? 10;
      document.getElementById('inp-sym-exp').value     = s.max_symbol_exposure_pct ?? 0;
      document.getElementById('inp-take-profit').value = s.take_profit_pct         ?? 0;
      if (s.trading_hours_start) document.getElementById('inp-hours-start').value = s.trading_hours_start;
      if (s.trading_hours_end)   document.getElementById('inp-hours-end').value   = s.trading_hours_end;

      // Status labels
      const consecEl = document.getElementById('consec-current');
      if (consecEl) {
        const lim = s.consecutive_loss_limit || 0;
        consecEl.textContent = lim > 0
          ? `Current count: ${r.consecutive_losses ?? 0} / ${lim}`
          : 'Disabled (set to 0)';
      }
      const weeklyEl = document.getElementById('weekly-current');
      if (weeklyEl) {
        const wl = s.weekly_loss_limit_pct || 0;
        weeklyEl.textContent = wl > 0
          ? `Week P&L: ${(r.week_pl_pct ?? 0).toFixed(2)}% (limit: -${wl}%)`
          : 'Disabled (set to 0)';
      }
      const ordEl = document.getElementById('orders-current');
      if (ordEl) {
        const mo = s.max_orders_per_day || 0;
        ordEl.textContent = mo > 0
          ? `Today: ${r.orders_today ?? 0} / ${mo} orders`
          : 'Disabled (set to 0)';
      }
      const hoursEl = document.getElementById('hours-status');
      if (hoursEl) {
        hoursEl.textContent = s.trading_hours_start && s.trading_hours_end
          ? `Active: ${s.trading_hours_start} – ${s.trading_hours_end} ET`
          : 'Disabled — all market hours allowed.';
      }

      // Blacklist
      if (r.blacklist) renderBlacklist(r.blacklist);

      setSizingMode(r.position_size_mode);
      applyLiveStatus(r);
    } catch { /* silent */ }
  }

  function applyLiveStatus(r) {
    // Day P&L
    const plEl  = document.getElementById('risk-live-pl');
    const barEl = document.getElementById('risk-pl-bar');
    const pl    = r.day_pl_pct ?? 0;
    const plPct = pl.toFixed(2) + '%';
    plEl.textContent = (pl >= 0 ? '+' : '') + plPct;
    plEl.style.color  = pl >= 0 ? 'var(--green)' : (r.daily_loss_ok ? 'var(--orange)' : 'var(--red)');
    const limitPct   = Math.abs(r.max_daily_loss_pct);
    const barWidth   = Math.min(100, (Math.abs(pl) / limitPct) * 100);
    barEl.style.width = barWidth + '%';
    barEl.style.background = pl >= 0 ? 'var(--green)' : (r.daily_loss_ok ? 'var(--orange)' : 'var(--red)');

    // Day trades
    const dtEl  = document.getElementById('risk-live-dt');
    const dtSub = document.getElementById('risk-pdt-label');
    dtEl.textContent = `${r.day_trade_count} / ${r.max_day_trades}`;
    dtEl.style.color  = r.pdt_ok ? 'var(--text)' : 'var(--orange)';
    dtSub.textContent = r.pdt_applies ? 'PDT rule applies (< $25k)' : 'PDT rule not applicable';

    // Loss limit
    const llEl  = document.getElementById('risk-live-limit');
    const llSub = document.getElementById('risk-limit-label');
    llEl.textContent  = '-' + Math.abs(r.max_daily_loss_pct) + '%';
    llEl.style.color  = r.daily_loss_ok ? 'var(--muted)' : 'var(--red)';
    llSub.textContent = r.daily_loss_ok ? 'Limit not reached' : 'Limit breached';
    llSub.style.color = r.daily_loss_ok ? '' : 'var(--red)';

    // Engine status
    const esEl  = document.getElementById('risk-engine-status');
    const esSub = document.getElementById('risk-engine-sub');
    if (r.kill_switch) {
      esEl.textContent  = 'Halted';
      esEl.style.color  = 'var(--red)';
      esSub.textContent = 'Kill switch active';
    } else if (!r.daily_loss_ok || !r.pdt_ok || r.weekly_loss_ok === false
               || r.orders_today_ok === false || r.consecutive_ok === false) {
      esEl.textContent  = 'Blocked';
      esEl.style.color  = 'var(--orange)';
      esSub.textContent = 'Risk limit reached';
    } else {
      esEl.textContent  = 'Running';
      esEl.style.color  = 'var(--green)';
      esSub.textContent = 'All guards clear';
    }

    // Warnings
    const warnEl = document.getElementById('risk-warnings');
    if (r.warnings && r.warnings.length) {
      warnEl.innerHTML = r.warnings.map(w => `
        <div class="risk-warning-item">
          <svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          ${w}
        </div>`).join('');
      warnEl.classList.remove('hidden');
      warnEl.style.display = 'flex';
    } else {
      warnEl.classList.add('hidden');
    }
  }

  function applyKS(on) {
    killState = on;
    const card = document.getElementById('ks-card');
    const badge = document.getElementById('ks-badge');
    const btn = document.getElementById('btn-ks');
    if (on) {
      card.style.borderColor = 'rgba(239,68,68,.6)';
      card.style.background = 'rgba(239,68,68,.07)';
      badge.className = 'ks-badge2 ks-badge-on';
      badge.innerHTML = '<span style="width:6px;height:6px;border-radius:50%;background:#EF4444;box-shadow:0 0 6px rgba(239,68,68,.6);display:inline-block;"></span>ACTIVE';
      btn.innerHTML = '<svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg> Deactivate';
      btn.className = 'btn btn-ghost';
    } else {
      card.style.borderColor = 'rgba(239,68,68,.25)';
      card.style.background = '';
      badge.className = 'ks-badge2 ks-badge-off';
      badge.innerHTML = '<span style="width:6px;height:6px;border-radius:50%;background:#475569;display:inline-block;"></span>OFF';
      btn.innerHTML = '<svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg> Activate';
      btn.className = 'btn btn-danger';
    }
  }

  document.getElementById('btn-ks').addEventListener('click', async () => {
    const newState = !killState;
    try {
      await api('/api/risk/kill_switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ on: newState }),
        key: 'risk-ks',
      });
      applyKS(newState);
      showToast(newState ? 'Kill switch activated' : 'Kill switch deactivated');
    } catch { showToast('Failed to update', true); }
  });

  // Save buttons
  document.querySelectorAll('.risk-save-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const key = btn.dataset.key;
      const val = document.getElementById(btn.dataset.source).value;
      if (val === '' || val === null) return;
      btn.disabled = true;
      try {
        await api(`/api/risk/${key}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value: String(val) }),
          key: `risk-save-${key}`,
        });
        showToast('Saved');
      } catch { showToast('Failed to save', true); }
      finally { btn.disabled = false; }
    });
  });

  // Position sizing mode toggle
  function setSizingMode(mode) {
    document.getElementById('sizing-fixed').classList.toggle('active', mode === 'fixed');
    document.getElementById('sizing-pct').classList.toggle('active',  mode === 'pct');
    document.getElementById('pct-sizing-row').classList.toggle('hidden', mode !== 'pct');
  }

  ['sizing-fixed', 'sizing-pct'].forEach(id => {
    document.getElementById(id).addEventListener('click', async () => {
      const mode = document.getElementById(id).dataset.mode;
      setSizingMode(mode);
      try {
        await api('/api/risk/position_size_mode', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value: mode }),
          key: 'risk-mode',
        });
        showToast('Saved');
      } catch { showToast('Failed to save', true); }
    });
  });

  // ── New inputs: load from settings ──────────────────────────────────────
  // (done inside loadRisk → applyLiveStatus uses r.settings)

  // ── Circuit breaker save buttons handled by generic .risk-save-btn ──────

  // ── Reset consecutive losses ─────────────────────────────────────────────
  document.getElementById('btn-reset-losses')?.addEventListener('click', async () => {
    try {
      await api('/api/risk/reset_losses', { method: 'POST', key: 'risk-reset-losses' });
      document.getElementById('consec-current').textContent = 'Counter reset to 0.';
      showToast('Consecutive counter reset');
    } catch { showToast('Reset failed', true); }
  });

  // ── Trading hours save / clear ────────────────────────────────────────────
  document.getElementById('btn-save-hours')?.addEventListener('click', async () => {
    const s = document.getElementById('inp-hours-start').value.trim();
    const e = document.getElementById('inp-hours-end').value.trim();
    if (!s || !e) { showToast('Enter both start and end times', true); return; }
    try {
      await Promise.all([
        api('/api/risk/trading_hours_start', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value: s }), key: 'rh-start' }),
        api('/api/risk/trading_hours_end',   { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value: e }), key: 'rh-end'   }),
      ]);
      document.getElementById('hours-status').textContent = `Active: ${s} – ${e} ET`;
      showToast('Trading hours saved');
    } catch { showToast('Failed to save hours', true); }
  });

  document.getElementById('btn-clear-hours')?.addEventListener('click', async () => {
    try {
      await Promise.all([
        api('/api/risk/trading_hours_start', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value: '' }), key: 'rh-start' }),
        api('/api/risk/trading_hours_end',   { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value: '' }), key: 'rh-end'   }),
      ]);
      document.getElementById('inp-hours-start').value = '';
      document.getElementById('inp-hours-end').value   = '';
      document.getElementById('hours-status').textContent = 'Disabled — all market hours allowed.';
      showToast('Trading hours cleared');
    } catch { showToast('Failed to clear', true); }
  });

  // ── Blacklist CRUD ────────────────────────────────────────────────────────
  function renderBlacklist(symbols) {
    const wrap  = document.getElementById('blacklist-chips');
    const empty = document.getElementById('blacklist-empty');
    wrap.querySelectorAll('.ntl-chip2').forEach(c => c.remove());
    if (!symbols || symbols.length === 0) {
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');
    symbols.forEach(sym => {
      const chip = document.createElement('span');
      chip.className = 'ntl-chip2';
      chip.innerHTML = `${sym}<button title="Remove" aria-label="Remove ${sym}">
        <svg width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>`;
      chip.querySelector('button').addEventListener('click', async () => {
        try {
          const d = await api(`/api/risk/blacklist/${sym}`, { method: 'DELETE', key: 'bl-del' });
          renderBlacklist(d.symbols);
        } catch { showToast('Remove failed', true); }
      });
      wrap.appendChild(chip);
    });
  }

  document.getElementById('btn-blacklist-add')?.addEventListener('click', async () => {
    const inp = document.getElementById('inp-blacklist-add');
    const sym = inp.value.trim().toUpperCase();
    if (!sym) return;
    try {
      const d = await api('/api/risk/blacklist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: sym }),
        key: 'bl-add',
      });
      renderBlacklist(d.symbols);
      inp.value = '';
    } catch { showToast('Add failed', true); }
  });

  document.getElementById('inp-blacklist-add')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('btn-blacklist-add').click();
  });

  // ── Per-account kill switches ────────────────────────────────────────────
  async function loadAccountKillSwitches() {
    const container = document.getElementById('acct-ks-list');
    if (!container) return;
    try {
      const accounts = await api('/api/broker-accounts', { key: 'risk-accts' });
      if (!accounts.length) {
        container.innerHTML = '<div class="state-empty">No broker accounts configured.</div>'; return;
      }
      container.innerHTML = '';
      await Promise.all(accounts.map(async acct => {
        let ksOn = false;
        try {
          const ks = await api(`/api/broker-accounts/${acct.id}/kill-switch`, { key: `ks-${acct.id}` });
          ksOn = !!ks.kill_switch;
        } catch {}
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:.5rem 0;border-bottom:1px solid var(--border);';
        row.dataset.acctId = acct.id;
        const meta = getBrokerMeta(acct.broker);
        row.innerHTML = `
          <div style="display:flex;align-items:center;gap:.5rem;">
            <span class="acct-initials" style="background:${meta.bg};color:${meta.color};border-radius:6px;padding:2px 6px;font-size:11px;font-weight:700;">${meta.initials}</span>
            <span style="font-size:13px;">${acct.label || acct.broker}</span>
            <span class="badge ${ksOn ? 'b-error' : 'b-enabled'}" id="acct-ks-badge-${acct.id}">${ksOn ? 'HALTED' : 'Running'}</span>
          </div>
          <button class="btn ${ksOn ? 'btn-ghost' : 'btn-danger'}" style="font-size:11px;padding:.25rem .6rem;" id="acct-ks-btn-${acct.id}"
            data-acct="${acct.id}" data-on="${ksOn ? '1' : '0'}">
            ${ksOn ? 'Resume' : 'Stop'}
          </button>`;
        container.appendChild(row);

        row.querySelector('button').addEventListener('click', async (ev) => {
          const btn = ev.currentTarget;
          const id  = btn.dataset.acct;
          const cur = btn.dataset.on === '1';
          const next = !cur;
          btn.disabled = true;
          try {
            await api(`/api/broker-accounts/${id}/kill-switch?on=${next}`, { method: 'POST', key: `ks-toggle-${id}` });
            btn.dataset.on = next ? '1' : '0';
            btn.textContent = next ? 'Resume' : 'Stop';
            btn.className = `btn ${next ? 'btn-ghost' : 'btn-danger'}`;
            btn.style.cssText = 'font-size:11px;padding:.25rem .6rem;';
            const badge = document.getElementById(`acct-ks-badge-${id}`);
            if (badge) { badge.className = `badge ${next ? 'b-error' : 'b-enabled'}`; badge.textContent = next ? 'HALTED' : 'Running'; }
            showToast(next ? `Account ${id} halted` : `Account ${id} resumed`);
          } catch { showToast('Failed to update', true); }
          finally { btn.disabled = false; }
        });
      }));
    } catch (e) {
      if (e.name === 'AbortError') return;
      container.innerHTML = '<div class="state-error">Failed to load accounts</div>';
    }
  }

  await loadRisk();
  loadAccountKillSwitches();
}

// ─────────────────────────────────────────
// initBalances — balances.html
// ─────────────────────────────────────────
async function initBalances() {
  initClockChip(document.getElementById('market-chip'));

  let balAccountId = null;

  // Build account selector (only shown when >1 account exists)
  try {
    const accounts = await api('/api/broker-accounts', { key: 'bal-acct-list' });
    if (accounts && accounts.length >= 2) {
      const wrap = document.getElementById('bal-account-wrap');
      if (wrap) {
        const sel = document.createElement('select');
        sel.className = 'acct-sel';
        const all = document.createElement('option');
        all.value = ''; all.textContent = 'All accounts';
        sel.appendChild(all);
        accounts.forEach(a => {
          const opt = document.createElement('option');
          opt.value = a.id; opt.textContent = a.label || `Account ${a.id}`;
          sel.appendChild(opt);
        });
        sel.addEventListener('change', () => {
          balAccountId = sel.value ? parseInt(sel.value) : null;
          fetchAccount();
          fetchHoldings();
        });
        wrap.appendChild(sel);
      }
    }
  } catch {}

  async function fetchAccount() {
    const qs = balAccountId ? `?account_id=${balAccountId}` : '';
    try {
      const a = await api(`/api/account${qs}`, { key: 'bal-account' });
      document.getElementById('bal-equity').textContent = fmt.usd(a.equity);
      document.getElementById('bal-cash').textContent   = fmt.usd(a.cash);
      document.getElementById('bal-bp').textContent     = fmt.usd(a.buying_power);
      document.getElementById('bal-pv').textContent     = fmt.usd(a.portfolio_value);
      if (a.account_type === 'paper') {
        document.getElementById('paper-badge')?.classList.remove('hidden');
      }
    } catch (e) {
      if (e.name === 'AbortError') return;
      ['bal-equity','bal-cash','bal-bp','bal-pv','bal-upnl'].forEach(id => {
        document.getElementById(id).textContent = '—';
      });
      throw e;
    }
  }

  async function fetchHoldings() {
    const tbody = document.getElementById('holdings-body');
    const qs = balAccountId ? `?account_id=${balAccountId}` : '';
    try {
      const positions = await api(`/api/positions${qs}`, { key: 'bal-positions' });
      tbody.innerHTML = '';
      if (!positions.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="state-empty">No open holdings.</td></tr>';
        const upnlEl = document.getElementById('bal-upnl');
        if (upnlEl) { upnlEl.textContent = '—'; upnlEl.className = 'text-tabular'; }
        const upnlSub = document.getElementById('bal-upnl-sub');
        if (upnlSub) upnlSub.textContent = '';
        return;
      }
      let totalPnl = 0;
      positions.forEach(p => {
        const tr = document.createElement('tr');
        const pnl = p.unrealized_pl || 0;
        totalPnl += pnl;
        const fields = [p.symbol, (p.qty||0).toFixed(2), fmt.usd(p.avg_entry_price), fmt.usd(p.current_price), fmt.usd(p.market_value), ''];
        fields.forEach((v, i) => {
          const td = document.createElement('td');
          if (i === 5) {
            td.textContent = fmt.usdSigned(pnl, '—');
            td.className = 'text-tabular ' + (pnl >= 0 ? 'text-green glow-green' : 'text-red glow-red');
          } else { td.textContent = v; }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      const upnlEl  = document.getElementById('bal-upnl');
      const upnlSub = document.getElementById('bal-upnl-sub');
      if (upnlEl) {
        upnlEl.textContent = fmt.usdSigned(totalPnl, '—');
        upnlEl.className = 'text-tabular ' + (totalPnl >= 0 ? 'text-green glow-green' : 'text-red glow-red');
        upnlEl.style.fontSize = '22px';
        upnlEl.style.fontWeight = '700';
      }
      if (upnlSub) {
        upnlSub.textContent = positions.length ? (totalPnl >= 0 ? 'Open gain' : 'Open loss') : '';
        upnlSub.style.color = totalPnl >= 0 ? 'var(--green)' : 'var(--red)';
      }
    } catch (e) {
      if (e.name === 'AbortError') return;
      tbody.innerHTML = '<tr><td colspan="6" class="state-error">Failed to load — retrying in 30s</td></tr>';
      throw e;
    }
  }

  createPoller(fetchAccount,  30_000).start();
  createPoller(fetchHoldings, 30_000).start();
}

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
        tbody.innerHTML = '<tr><td colspan="8" class="state-empty">No signals.</td></tr>';
        return;
      }
      const statusCls = { filled: 'b-enabled', blocked: 'b-notrun', error: 'b-error', pending: 'b-disabled' };
      filtered.slice(0, 100).forEach(s => {
        const tr = document.createElement('tr');
        const fields = [fmt.time(s.ts), s.strategy, s.symbol, '', (s.qty||0).toFixed(2), s.reason, '', ''];
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
          } else if (i === 7) {
            const btn = document.createElement('button');
            btn.className = 'btn-explain';
            btn.textContent = 'Explain';
            btn.onclick = function() { toggleExplanation(s.id, this); };
            td.appendChild(btn);
          } else { td.textContent = v; }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    } catch (e) {
      if (e.name === 'AbortError') return;
      tbody.innerHTML = '<tr><td colspan="8" class="state-error">Failed to load — retrying in 30s</td></tr>';
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

  document.getElementById('export-trades-btn')?.addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = '/api/export/trades?limit=5000';
    a.download = 'tradebot_trades.csv';
    a.click();
  });

  async function fetchAudit() {
    const tbody = document.getElementById('audit-body');
    if (!tbody) return;
    try {
      const rows = await api('/api/audit?limit=200', { key: 'logs-audit' });
      tbody.innerHTML = '';
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="state-empty">No audit entries yet.</td></tr>';
        return;
      }
      const catCls = {
        risk:       'b-notrun',
        kill_switch:'b-error',
        strategy:   'b-buy',
        account:    'b-sell',
        position:   'b-disabled',
      };
      rows.forEach(r => {
        const tr = document.createElement('tr');
        [fmt.time(r.ts), '', r.action, r.detail].forEach((v, i) => {
          const td = document.createElement('td');
          if (i === 1) {
            const badge = document.createElement('span');
            badge.className = 'badge ' + (catCls[r.category] || 'b-disabled');
            badge.textContent = r.category;
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
      tbody.innerHTML = '<tr><td colspan="4" class="state-error">Failed to load — retrying</td></tr>';
    }
  }

  createPoller(fetchSignals, 30_000).start();
  createPoller(fetchAudit,   60_000).start();
}

// initApiKeys — apikeys.html
// ─────────────────────────────────────────
async function initApiKeys() {
  initClockChip(document.getElementById('market-chip'));

  // ── Type selector helpers ─────────────────────────────────────────
  function updateKeyPlaceholders(type, prefix) {
    const isPaper = type === 'paper';

    // API key placeholder
    const keyEl = document.getElementById(`${prefix}-api-key`);
    if (keyEl) keyEl.placeholder = isPaper ? 'PK… paper key' : 'AK… live key';

    // Coloured banner
    const banner = document.getElementById(`${prefix}-creds-banner`);
    const bannerText = document.getElementById(`${prefix}-creds-banner-text`);
    if (banner) {
      banner.className = 'acct-creds-banner ' + (isPaper ? 'acct-creds-banner-paper' : 'acct-creds-banner-live');
    }
    if (bannerText) {
      bannerText.innerHTML = isPaper
        ? 'Paper API keys start with <strong>PK</strong> &mdash; get them from alpaca.markets &rarr; Paper Trading'
        : 'Live API keys start with <strong>AK</strong> &mdash; get them from alpaca.markets &rarr; Live Trading';
    }

    // Header band colour
    const band = document.getElementById(`${prefix}-modal-band`);
    if (band) band.className = 'acct-modal-band ' + (isPaper ? 'acct-band-paper' : 'acct-band-live');

    // Badge in band
    const badge = document.getElementById(`${prefix}-type-badge`);
    if (badge) {
      badge.className = 'acct-type-badge ' + (isPaper ? 'acct-badge-paper' : 'acct-badge-live');
      badge.textContent = isPaper ? 'Paper' : 'Live';
    }
  }

  function wireTypeSelector(selectorId, hiddenId, keyPrefix) {
    const sel = document.getElementById(selectorId);
    if (!sel) return;
    const hidden = document.getElementById(hiddenId);
    sel.querySelectorAll('[data-val]').forEach(opt => {
      opt.addEventListener('click', () => {
        sel.querySelectorAll('[data-val]').forEach(o => o.classList.remove('active'));
        opt.classList.add('active');
        hidden.value = opt.dataset.val;
        if (keyPrefix) updateKeyPlaceholders(opt.dataset.val, keyPrefix);
      });
    });
  }

  function setTypeSelector(selectorId, hiddenId, val, keyPrefix) {
    const sel = document.getElementById(selectorId);
    if (!sel) return;
    const hidden = document.getElementById(hiddenId);
    if (hidden) hidden.value = val;
    sel.querySelectorAll('[data-val]').forEach(o => {
      o.classList.toggle('active', o.dataset.val === val);
    });
    if (keyPrefix) updateKeyPlaceholders(val, keyPrefix);
  }

  wireTypeSelector('add-type-selector', 'add-account-type', 'add');
  wireTypeSelector('edit-type-selector', 'edit-account-type', 'edit');

  // ── Account cards ─────────────────────────────────────────────────
  async function loadAccounts() {
    const grid = document.getElementById('accounts-grid');
    try {
      const accounts = await api('/api/broker-accounts', { key: 'keys-list' });
      grid.innerHTML = '';
      if (!accounts.length) {
        grid.innerHTML = '<div class="state-empty">No broker accounts yet. Click <strong>Add Account</strong> to connect your first broker.</div>';
        return;
      }
      accounts.forEach(acct => grid.appendChild(buildCard(acct)));
    } catch {
      grid.innerHTML = '<div class="state-error">Failed to load accounts.</div>';
    }
  }

  function buildCard(acct) {
    const broker = getBrokerMeta(acct.broker || 'alpaca');
    const isLive = acct.account_type === 'live';

    const wrap = document.createElement('div');
    wrap.style.cssText = 'display:flex;flex-direction:column;gap:0;';

    const card = document.createElement('div');
    card.className = 'broker-card';
    card.style.cssText = `border-left:3px solid ${isLive ? '#EF4444' : '#3B82F6'};`;

    // Header row
    const hdr = document.createElement('div');
    hdr.className = 'broker-card-top';

    // Broker logo
    const logo = document.createElement('div');
    logo.style.cssText = `width:44px;height:44px;border-radius:12px;background:${broker.bg};color:${broker.color};display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:700;letter-spacing:-.5px;flex-shrink:0;`;
    logo.textContent = broker.initials;

    // Name + label
    const info = document.createElement('div');
    info.style.cssText = 'flex:1;min-width:0;';
    const brokerNameEl = document.createElement('div');
    brokerNameEl.style.cssText = 'font-size:15px;font-weight:700;line-height:1.2;color:#E6EBF5;';
    brokerNameEl.textContent = broker.name;
    const acctLabelEl = document.createElement('div');
    acctLabelEl.style.cssText = 'font-size:12px;color:#94A3B8;margin-top:3px;';
    acctLabelEl.textContent = acct.label;
    info.append(brokerNameEl, acctLabelEl);

    // Type badge
    const badges = document.createElement('div');
    badges.style.cssText = 'display:flex;flex-direction:column;align-items:flex-end;gap:5px;';
    const typeBadge = document.createElement('span');
    typeBadge.style.cssText = `display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:20px;font-size:11px;font-weight:600;${
      isLive
        ? 'background:rgba(239,68,68,.15);color:#EF4444;border:1px solid rgba(239,68,68,.25);'
        : 'background:rgba(59,130,246,.12);color:#60A5FA;border:1px solid rgba(59,130,246,.2);'
    }`;
    if (isLive) {
      const dot = document.createElement('span');
      dot.style.cssText = 'width:6px;height:6px;border-radius:50%;background:#EF4444;animation:pulse 2s infinite;';
      typeBadge.appendChild(dot);
    }
    typeBadge.appendChild(document.createTextNode(isLive ? 'Live' : 'Paper'));
    badges.appendChild(typeBadge);
    hdr.append(logo, info, badges);

    // API key chip
    const keyChip = document.createElement('div');
    keyChip.className = 'broker-key-chip';
    const keyLabel = document.createElement('span');
    keyLabel.className = 'broker-key-label';
    keyLabel.textContent = 'API KEY';
    const keyVal = document.createElement('span');
    keyVal.className = 'broker-key-val';
    keyVal.textContent = acct.api_key || '••••••••';
    keyChip.append(keyLabel, keyVal);

    // Status row
    const statusRow = document.createElement('div');
    statusRow.style.cssText = 'display:flex;align-items:center;justify-content:space-between;min-height:18px;margin-top:2px;';
    const dateEl = document.createElement('span');
    dateEl.style.cssText = 'font-size:11px;color:#475569;';
    dateEl.textContent = acct.created_at ? 'Added ' + new Date(acct.created_at).toLocaleDateString('en-US', { month:'short', day:'numeric', year:'numeric' }) : '';
    const statusEl = document.createElement('span');
    statusEl.style.cssText = 'font-size:11px;font-weight:500;';
    statusRow.append(dateEl, statusEl);

    // Divider
    const div = document.createElement('div');
    div.style.cssText = 'border-top:1px solid rgba(30,45,69,.8);margin:.5rem 0 .25rem;';

    // Actions
    const actions = document.createElement('div');
    actions.style.cssText = 'display:flex;gap:.4rem;align-items:center;flex-wrap:wrap;';

    const mkBtn = (svgPath, label, extraStyle) => {
      const b = document.createElement('button');
      b.className = 'btn btn-sm btn-ghost';
      b.style.cssText = 'font-size:11px;' + (extraStyle || '');
      b.innerHTML = `<svg width="11" height="11" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">${svgPath}</svg> ${label}`;
      return b;
    };

    const btnTest = mkBtn('<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>', 'Test');
    const btnEdit = mkBtn('<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>', 'Edit');
    const btnDel  = mkBtn('<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/>', 'Delete', 'color:#EF4444;border-color:rgba(239,68,68,.25);margin-left:auto;');

    btnTest.addEventListener('click', () => testConnection(acct.id, statusEl));
    btnEdit.addEventListener('click', () => openEditModal(acct));
    btnDel.addEventListener('click',  () => openDeleteModal(acct));

    actions.append(btnTest, btnEdit, btnDel);
    card.append(hdr, keyChip, statusRow, div, actions);
    wrap.appendChild(card);
    return wrap;
  }

  async function testConnection(accountId, statusEl) {
    statusEl.textContent = 'Testing…';
    statusEl.style.color = '#94A3B8';
    try {
      const result = await api(`/api/broker-accounts/${accountId}/status`, { key: `test-${accountId}` });
      statusEl.style.color = '#10B981';
      statusEl.textContent = `✓ ${result.account_type} · equity ${fmt.usd(result.equity)}`;
    } catch {
      statusEl.style.color = '#EF4444';
      statusEl.textContent = '✗ Connection failed';
    }
  }

  function openEditModal(acct) {
    const broker = getBrokerMeta(acct.broker || 'alpaca');
    const nameEl = document.getElementById('edit-modal-broker-name');
    if (nameEl) nameEl.textContent = `${broker.name} · ${acct.label}`;
    document.getElementById('edit-account-id').value = acct.id;
    document.getElementById('edit-label').value = acct.label;
    const keyEl = document.getElementById('edit-api-key');
    const secEl = document.getElementById('edit-api-secret');
    if (keyEl) keyEl.value = '';
    if (secEl) secEl.value = '';
    setTypeSelector('edit-type-selector', 'edit-account-type', acct.account_type, 'edit');
    document.getElementById('edit-error').classList.add('hidden');

    openModal(document.getElementById('modal-edit-account'), async () => {
      const label       = document.getElementById('edit-label').value.trim();
      const accountType = document.getElementById('edit-account-type').value;
      const newKey      = (document.getElementById('edit-api-key')?.value || '').trim();
      const newSecret   = (document.getElementById('edit-api-secret')?.value || '').trim();
      const errEl       = document.getElementById('edit-error');
      if (!label) { errEl.textContent = 'Label is required.'; errEl.classList.remove('hidden'); return; }

      try {
        // Save label + type
        await api(`/api/broker-accounts/${acct.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ label, account_type: accountType }),
          key: 'edit-account',
        });
        // Rotate keys only if new ones were provided
        if (newKey && newSecret) {
          await api(`/api/broker-accounts/${acct.id}/credentials`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: newKey, api_secret: newSecret }),
            key: 'rotate-account',
          });
        }
        await loadAccounts();
      } catch (e) {
        errEl.textContent = 'Save failed: ' + (e.message || 'server error');
        errEl.classList.remove('hidden');
        throw e;
      }
    });
  }

  async function openDeleteModal(acct) {
    document.getElementById('delete-account-id').value = acct.id;
    document.getElementById('delete-account-name').textContent = acct.label;
    const warnEl = document.getElementById('delete-assignments-warn');
    warnEl.classList.add('hidden');
    try {
      const { strategies } = await api(`/api/broker-accounts/${acct.id}/assignments`, { key: `assign-${acct.id}` });
      if (strategies.length) {
        warnEl.textContent = `Will remove ${strategies.length} strategy assignment(s): ${strategies.join(', ')}`;
        warnEl.classList.remove('hidden');
      }
    } catch {}
    openModal(document.getElementById('modal-delete-account'), async () => {
      await api(`/api/broker-accounts/${acct.id}`, { method: 'DELETE', key: 'del-account' });
      await loadAccounts();
    });
  }

  // ── Broker picker (Add Account 2-step) ───────────────────────────
  const BP_SECTIONS = [
    { label: 'Stocks & Options',      ids: ['alpaca','ibkr','schwab','tradier','tastytrade','robinhood','webull','fidelity','etrade'] },
    { label: 'Crypto',                ids: ['coinbase','kraken','binanceus'] },
    { label: 'Forex',                 ids: ['oanda','forexcom','fxcm','ig'] },
    { label: 'Futures & Commodities', ids: ['ninjatrader','tradestation','ampfutures','cqg'] },
  ];

  function buildBrokerPicker() {
    const tabBar = document.getElementById('bp-tabs');
    const grid   = document.getElementById('broker-picker-grid');
    tabBar.innerHTML = '';
    grid.innerHTML   = '';
    let activeIdx = 0;

    function renderTab(idx) {
      activeIdx = idx;
      tabBar.querySelectorAll('.bp-tab').forEach((t, i) =>
        t.classList.toggle('bp-tab-active', i === idx)
      );
      grid.innerHTML = '';
      BP_SECTIONS[idx].ids.forEach(id => {
        const b = getBrokerMeta(id);
        const card = document.createElement('div');
        card.className = 'broker-pick-card' + (b.available ? '' : ' broker-pick-soon');
        card.dataset.broker = b.id;
        const logo = document.createElement('div');
        logo.className = 'broker-pick-logo';
        logo.style.cssText = `background:${b.bg};color:${b.color};`;
        logo.textContent = b.initials;
        const name = document.createElement('div');
        name.className = 'broker-pick-name';
        name.textContent = b.name;
        const badge = document.createElement('span');
        badge.className = 'badge ' + (b.available ? 'b-enabled' : 'b-disabled');
        badge.style.fontSize = '10px';
        badge.textContent = b.available ? 'Active' : 'Coming Soon';
        card.append(logo, name, badge);
        grid.appendChild(card);
      });
    }

    BP_SECTIONS.forEach((sec, i) => {
      const btn = document.createElement('button');
      btn.className = 'bp-tab' + (i === 0 ? ' bp-tab-active' : '');
      btn.textContent = sec.label;
      btn.addEventListener('click', () => renderTab(i));
      tabBar.appendChild(btn);
    });
    renderTab(0);
  }

  document.getElementById('add-step-back').addEventListener('click', () => {
    document.getElementById('add-step-1').classList.remove('hidden');
    document.getElementById('add-step-2').classList.add('hidden');
  });

  document.getElementById('broker-picker-grid').addEventListener('click', (e) => {
    const card = e.target.closest('.broker-pick-card:not(.broker-pick-soon)');
    if (!card) return;
    const b = getBrokerMeta(card.dataset.broker);
    document.getElementById('add-broker').value = b.id;
    document.getElementById('add-broker-title').textContent = `Add ${b.name} Account`;
    const iconWrap = document.getElementById('add-broker-icon-wrap');
    iconWrap.style.cssText = `width:36px;height:36px;border-radius:10px;background:${b.bg};color:${b.color};display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;flex-shrink:0;letter-spacing:-.5px;`;
    iconWrap.textContent = b.initials;
    document.getElementById('add-step-1').classList.add('hidden');
    document.getElementById('add-step-2').classList.remove('hidden');
  });

  document.getElementById('btn-add-account').addEventListener('click', () => {
    document.getElementById('add-step-1').classList.remove('hidden');
    document.getElementById('add-step-2').classList.add('hidden');
    ['add-label','add-api-key','add-api-secret'].forEach(id => {
      const el = document.getElementById(id); if (el) el.value = '';
    });
    setTypeSelector('add-type-selector', 'add-account-type', 'paper', 'add');
    document.getElementById('add-error').classList.add('hidden');
    buildBrokerPicker();
    openModal(document.getElementById('modal-add-account'), async () => {
      const label       = document.getElementById('add-label').value.trim();
      const apiKey      = document.getElementById('add-api-key').value.trim();
      const apiSecret   = document.getElementById('add-api-secret').value.trim();
      const accountType = document.getElementById('add-account-type').value;
      const broker      = document.getElementById('add-broker').value || 'alpaca';
      const errEl       = document.getElementById('add-error');
      if (!label || !apiKey || !apiSecret) {
        errEl.textContent = 'All fields are required.';
        errEl.classList.remove('hidden');
        return;
      }
      try {
        await api('/api/broker-accounts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ label, api_key: apiKey, api_secret: apiSecret, account_type: accountType, broker }),
          key: 'add-account',
        });
        await loadAccounts();
      } catch (e) {
        errEl.textContent = 'Add failed: ' + (e.message || 'unknown error');
        errEl.classList.remove('hidden');
        throw e;
      }
    });
  });

  await loadAccounts();
}

// ─────────────────────────────────────────
// initSettings — settings.html
// ─────────────────────────────────────────
async function initSettings() {
  // License status
  try {
    const lic = await fetch('/api/license/status').then(r => r.json());
    const statusEl = document.getElementById('lic-status');
    const daysEl   = document.getElementById('lic-days');
    const deactBtn = document.getElementById('lic-deactivate-btn');
    if (statusEl) {
      statusEl.textContent = lic.valid ? 'Active' : 'Inactive';
      statusEl.style.color = lic.valid ? 'var(--green)' : 'var(--red)';
    }
    if (daysEl) daysEl.textContent = lic.valid ? lic.days_remaining + ' days' : '—';
    if (deactBtn && lic.valid) {
      deactBtn.style.display = 'block';
      deactBtn.onclick = async () => {
        if (!confirm('Deactivate license? The dashboard will become inaccessible.')) return;
        await fetch('/api/license', { method: 'DELETE' });
        location.href = '/static/license.html';
      };
    }
  } catch {}

  // ── element refs ──
  const emailEnabled   = document.getElementById('email-enabled');
  const emailFields    = document.getElementById('email-fields');
  const emailTo        = document.getElementById('email-to');
  const emailSmtp      = document.getElementById('email-smtp');
  const emailPort      = document.getElementById('email-port');
  const emailUser      = document.getElementById('email-user');
  const emailPass      = document.getElementById('email-pass');
  const emailTestMsg   = document.getElementById('email-test-msg');

  const tgEnabled      = document.getElementById('telegram-enabled');
  const tgFields       = document.getElementById('telegram-fields');
  const tgToken        = document.getElementById('telegram-token');
  const tgChatId       = document.getElementById('telegram-chat-id');
  const tgTestMsg      = document.getElementById('telegram-test-msg');

  const notifyTrade    = document.getElementById('notify-on-trade');
  const notifyBlock    = document.getElementById('notify-on-block');
  const notifyDaily    = document.getElementById('notify-daily-summary');

  const saveBtn        = document.getElementById('btn-save-settings');
  const saveMsg        = document.getElementById('settings-save-msg');
  const testEmailBtn   = document.getElementById('btn-test-email');
  const testTgBtn      = document.getElementById('btn-test-telegram');

  // ── helpers ──
  function showMsg(el, text, type) {
    el.textContent = text;
    el.className = 'field-msg ' + type;
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 5000);
  }

  function syncEmailFields() {
    emailFields.classList.toggle('hidden', !emailEnabled.checked);
  }
  function syncTgFields() {
    tgFields.classList.toggle('hidden', !tgEnabled.checked);
  }

  emailEnabled.addEventListener('change', syncEmailFields);
  tgEnabled.addEventListener('change', syncTgFields);

  // ── load current settings ──
  try {
    const data = await fetch('/api/notifications').then(r => r.json());
    emailEnabled.checked  = !!data.email_enabled;
    emailTo.value         = data.email_to        || '';
    emailSmtp.value       = data.email_smtp       || 'smtp.gmail.com';
    emailPort.value       = data.email_port       || 587;
    emailUser.value       = data.email_user       || '';
    emailPass.value       = data.email_pass       || '';

    tgEnabled.checked     = !!data.telegram_enabled;
    tgToken.value         = data.telegram_token   || '';
    tgChatId.value        = data.telegram_chat_id || '';

    notifyTrade.checked   = !!data.notify_on_trade;
    notifyBlock.checked   = !!data.notify_on_block;
    notifyDaily.checked   = !!data.notify_daily_summary;

    // Slack
    const slackEn  = document.getElementById('slack-enabled');
    const slackUrl = document.getElementById('slack-webhook-url');
    if (slackEn)  slackEn.checked  = !!data.slack_enabled;
    if (slackUrl) slackUrl.value   = data.slack_webhook_url || '';

    // Discord
    const discordEn  = document.getElementById('discord-enabled');
    const discordUrl = document.getElementById('discord-webhook-url');
    if (discordEn)  discordEn.checked  = !!data.discord_enabled;
    if (discordUrl) discordUrl.value   = data.discord_webhook_url || '';

    syncEmailFields();
    syncTgFields();
  } catch (e) {
    console.error('Failed to load notification settings', e);
  }

  // ── save ──
  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
    try {
      await fetch('/api/notifications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email_enabled:      emailEnabled.checked,
          email_to:           emailTo.value.trim(),
          email_smtp:         emailSmtp.value.trim(),
          email_port:         parseInt(emailPort.value) || 587,
          email_user:         emailUser.value.trim(),
          email_pass:         emailPass.value,
          telegram_enabled:   tgEnabled.checked,
          telegram_token:     tgToken.value.trim(),
          telegram_chat_id:   tgChatId.value.trim(),
          notify_on_trade:    notifyTrade.checked,
          notify_on_block:    notifyBlock.checked,
          notify_daily_summary: notifyDaily.checked,
          slack_enabled:      document.getElementById('slack-enabled')?.checked   || false,
          slack_webhook_url:  document.getElementById('slack-webhook-url')?.value.trim() || '',
          discord_enabled:    document.getElementById('discord-enabled')?.checked  || false,
          discord_webhook_url: document.getElementById('discord-webhook-url')?.value.trim() || '',
        }),
      });
      showMsg(saveMsg, 'Settings saved.', 'ok');
    } catch (e) {
      showMsg(saveMsg, 'Failed to save: ' + e.message, 'err');
    } finally {
      saveBtn.disabled = false;
      saveBtn.innerHTML = '<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg> Save Settings';
    }
  });

  // ── test email ──
  testEmailBtn.addEventListener('click', async () => {
    testEmailBtn.disabled = true;
    testEmailBtn.textContent = 'Sending...';
    try {
      await fetch('/api/notifications/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel:    'email',
          email_to:   emailTo.value.trim(),
          email_smtp: emailSmtp.value.trim(),
          email_port: parseInt(emailPort.value) || 587,
          email_user: emailUser.value.trim(),
          email_pass: emailPass.value,
        }),
      });
      showMsg(emailTestMsg, 'Test email sent! Check your inbox.', 'ok');
    } catch (e) {
      showMsg(emailTestMsg, 'Send failed: ' + e.message, 'err');
    } finally {
      testEmailBtn.disabled = false;
      testEmailBtn.innerHTML = '<svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="22 2 11 13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> Send Test';
    }
  });

  // ── test telegram ──
  testTgBtn.addEventListener('click', async () => {
    testTgBtn.disabled = true;
    testTgBtn.textContent = 'Sending...';
    try {
      const res = await fetch('/api/notifications/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel:          'telegram',
          telegram_token:   tgToken.value.trim(),
          telegram_chat_id: tgChatId.value.trim(),
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || res.statusText);
      }
      showMsg(tgTestMsg, 'Telegram message sent! Check your chat.', 'ok');
    } catch (e) {
      showMsg(tgTestMsg, 'Send failed: ' + e.message, 'err');
    } finally {
      testTgBtn.disabled = false;
      testTgBtn.innerHTML = '<svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="22 2 11 13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> Send Test';
    }
  });

  // ── TradingView Webhook ──────────────────────────────────────────────────
  async function loadWebhook() {
    try {
      const data = await api('/api/webhook/token', { key: 'wh-load' });
      const urlEl   = document.getElementById('webhook-url');
      const tokenEl = document.getElementById('webhook-token');
      if (urlEl)   urlEl.value   = data.url   || '';
      if (tokenEl) tokenEl.value = data.token  || '';
    } catch {}
  }

  document.getElementById('copy-webhook-url')?.addEventListener('click', () => {
    const el = document.getElementById('webhook-url');
    if (!el) return;
    navigator.clipboard.writeText(el.value).then(() => showMsg(saveMsg, 'URL copied!', 'ok'));
  });

  document.getElementById('copy-webhook-token')?.addEventListener('click', () => {
    const el = document.getElementById('webhook-token');
    if (!el) return;
    navigator.clipboard.writeText(el.value).then(() => showMsg(saveMsg, 'Token copied!', 'ok'));
  });

  document.getElementById('rotate-webhook-token')?.addEventListener('click', async () => {
    if (!confirm('Rotate token? Your existing TradingView alerts will need updating.')) return;
    try {
      const data = await api('/api/webhook/token/rotate', { method: 'POST', key: 'wh-rotate' });
      const tokenEl = document.getElementById('webhook-token');
      if (tokenEl) tokenEl.value = data.token || '';
      showMsg(saveMsg, 'Token rotated — update your TradingView alerts.', 'ok');
    } catch (e) {
      showMsg(saveMsg, 'Rotate failed: ' + e.message, 'err');
    }
  });

  loadWebhook();

  // ── Price Alerts ─────────────────────────────────────────────────────────
  async function loadAlerts() {
    const tbody = document.getElementById('alerts-body');
    if (!tbody) return;
    try {
      const alerts = await api('/api/alerts', { key: 'alerts-load' });
      tbody.innerHTML = '';
      if (!alerts.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="state-empty">No alerts set.</td></tr>'; return;
      }
      alerts.forEach(a => {
        const tr = document.createElement('tr');
        const dirLabel = a.direction === 'above' ? '≥' : '≤';
        const statusCls = a.triggered ? 'b-disabled' : 'b-enabled';
        const statusLabel = a.triggered ? 'Triggered' : 'Active';
        tr.innerHTML = `
          <td>${a.symbol}</td>
          <td>${dirLabel} $${Number(a.target_price).toFixed(2)}</td>
          <td><span class="badge ${statusCls}">${statusLabel}</span></td>
          <td>${a.note || '—'}</td>
          <td><button class="btn btn-ghost" style="font-size:11px;padding:.2rem .5rem;"
            onclick="window._deleteAlert(${a.id})">Remove</button></td>`;
        tbody.appendChild(tr);
      });
    } catch (e) {
      if (e.name === 'AbortError') return;
      const tbody2 = document.getElementById('alerts-body');
      if (tbody2) tbody2.innerHTML = '<tr><td colspan="5" class="state-error">Failed to load</td></tr>';
    }
  }

  window._deleteAlert = async (id) => {
    try {
      await fetch(`/api/alerts/${id}`, { method: 'DELETE' });
      loadAlerts();
    } catch { showMsg(saveMsg, 'Delete failed', 'err'); }
  };

  document.getElementById('add-alert-btn')?.addEventListener('click', () => {
    document.getElementById('add-alert-form')?.classList.remove('hidden');
  });

  document.getElementById('cancel-alert-btn')?.addEventListener('click', () => {
    document.getElementById('add-alert-form')?.classList.add('hidden');
  });

  document.getElementById('save-alert-btn')?.addEventListener('click', async () => {
    const sym  = document.getElementById('alert-symbol')?.value.trim().toUpperCase();
    const dir  = document.getElementById('alert-direction')?.value;
    const price = parseFloat(document.getElementById('alert-price')?.value);
    const note = document.getElementById('alert-note')?.value.trim();
    if (!sym || !dir || isNaN(price)) { showMsg(saveMsg, 'Fill in symbol, direction, and price.', 'err'); return; }
    try {
      await api('/api/alerts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: sym, direction: dir, target_price: price, note }),
        key: 'alert-add',
      });
      document.getElementById('add-alert-form')?.classList.add('hidden');
      document.getElementById('alert-symbol').value = '';
      document.getElementById('alert-price').value  = '';
      document.getElementById('alert-note').value   = '';
      showMsg(saveMsg, 'Alert created.', 'ok');
      loadAlerts();
    } catch (e) { showMsg(saveMsg, 'Failed: ' + e.message, 'err'); }
  });

  loadAlerts();
}

// ─────────────────────────────────────────
// initBacktesting — backtesting.html
// ─────────────────────────────────────────

let _btCurrentRunId = null;
let _btEquityChart  = null;
let _btStrategies   = [];

async function initBacktesting() {
  // Populate strategy dropdown from /api/strategies
  try {
    _btStrategies = await api('/api/strategies');
    const sel = document.getElementById('bt-strategy');
    sel.innerHTML = _btStrategies
      .filter(s => !s.hidden)
      .map(s => `<option value="${s.name}">${s.label}</option>`)
      .join('');
    sel.addEventListener('change', () => renderAdvancedParams(sel.value));
    renderAdvancedParams(sel.value);
  } catch (e) {
    console.error('initBacktesting: failed to load strategies', e);
  }

  // Default date range: last 365 days
  const today    = new Date().toISOString().slice(0, 10);
  const yearAgo  = new Date(Date.now() - 365 * 86400_000).toISOString().slice(0, 10);
  document.getElementById('bt-end').value   = today;
  document.getElementById('bt-start').value = yearAgo;

  // Symbol field: uppercase and clean on blur
  const symField = document.getElementById('bt-symbols');
  symField?.addEventListener('blur', () => {
    const cleaned = symField.value
      .split(',')
      .map(s => s.trim().toUpperCase())
      .filter(Boolean)
      .join(', ');
    if (cleaned) symField.value = cleaned;
  });

  // Load history
  try {
    const runs = await api('/api/backtest/runs');
    renderHistory(runs);
  } catch (e) {
    console.error('initBacktesting: failed to load history', e);
  }

  // Auto-load a run if ?run=<id> is present (used by "View Backtest" links from Strategy Health)
  const urlRun = new URLSearchParams(window.location.search).get('run');
  if (urlRun) {
    try { await loadRun(parseInt(urlRun, 10)); } catch (_) {}
  }
}

function renderAdvancedParams(stratName) {
  const grid = document.getElementById('bt-params-grid');
  const adv  = document.getElementById('bt-advanced');
  if (!grid || !adv) return;
  const strat = _btStrategies.find(s => s.name === stratName);
  const skipKeys = new Set(['symbols', 'use_scanner', 'scanner_min_price', 'scanner_max_price',
    'scanner_top_actives', 'scanner_top_gainers', 'notional', 'qty']);
  const schema = (strat?.params_schema || []).filter(p => !skipKeys.has(p.key) && (p.type === 'number' || p.type === 'bool'));
  if (!schema.length) {
    adv.style.display = 'none';
    grid.innerHTML = '';
    return;
  }
  adv.style.display = '';
  const defaults = strat?.default_params || {};
  grid.innerHTML = schema.map(p => {
    if (p.type === 'bool') {
      const checked = defaults[p.key] ? 'checked' : '';
      return `<div class="form-group" style="display:flex;flex-direction:column;justify-content:flex-end;">
        <label class="form-label" title="${p.hint || ''}">${p.label}</label>
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer;padding:.45rem 0;">
          <input type="checkbox" id="bt-param-${p.key}" ${checked} style="width:16px;height:16px;accent-color:#3B82F6;">
          <span style="font-size:12px;color:#94A3B8;">Enabled</span>
        </label>
      </div>`;
    }
    const val = defaults[p.key] ?? '';
    const min = p.min != null ? `min="${p.min}"` : '';
    const max = p.max != null ? `max="${p.max}"` : '';
    return `<div class="form-group">
      <label class="form-label" title="${p.hint || ''}">${p.label}</label>
      <input id="bt-param-${p.key}" type="number" class="input-field" value="${val}" ${min} ${max} step="any">
    </div>`;
  }).join('');
}

function collectAdvancedParams() {
  const grid = document.getElementById('bt-params-grid');
  if (!grid) return {};
  const params = {};
  grid.querySelectorAll('[id^="bt-param-"]').forEach(el => {
    const key = el.id.replace('bt-param-', '');
    if (el.type === 'checkbox') {
      params[key] = el.checked;
    } else if (el.value.trim() !== '') {
      const n = parseFloat(el.value);
      if (!isNaN(n)) params[key] = n;
    }
  });
  return params;
}

let _btLastData = null;

async function runBacktest() {
  const btn      = document.getElementById('bt-run-btn');
  const errEl    = document.getElementById('bt-error');
  const statusEl = document.getElementById('bt-status');
  errEl.classList.add('hidden');

  const rawSymbols = document.getElementById('bt-symbols').value;
  const symbols = rawSymbols.split(',').map(s => s.trim()).filter(Boolean);

  if (!symbols.length) {
    errEl.textContent = 'Enter at least one symbol.';
    errEl.classList.remove('hidden');
    return;
  }

  const body = {
    strategy:          document.getElementById('bt-strategy').value,
    symbols,
    start_date:        document.getElementById('bt-start').value,
    end_date:          document.getElementById('bt-end').value,
    initial_capital:   parseFloat(document.getElementById('bt-capital').value),
    position_size_pct: parseFloat(document.getElementById('bt-possize').value),
    commission_pct:    parseFloat(document.getElementById('bt-commission').value),
    slippage_pct:      parseFloat(document.getElementById('bt-slippage').value),
    strategy_params:   collectAdvancedParams(),
  };

  btn.disabled = true;
  btn.innerHTML = '<svg style="width:14px;height:14px;animation:spin 1s linear infinite;margin-right:6px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>Running&hellip;';
  if (statusEl) { statusEl.textContent = `Fetching ${symbols.length} symbol${symbols.length > 1 ? 's' : ''}…`; statusEl.style.display = 'inline'; }

  try {
    const res = await fetch('/api/backtest', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    });
    if (res.status === 401) { location.href = '/static/login.html'; return; }
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    _btLastData = data;
    renderResults(data);
    try { renderHistory(await api('/api/backtest/runs')); } catch (_) { /* non-fatal */ }
  } catch (e) {
    errEl.textContent = e.message;
    errEl.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Run Backtest';
    if (statusEl) statusEl.style.display = 'none';
  }
}

function renderResults(data) {
  _btLastData     = data;
  _btCurrentRunId = data.id;
  document.getElementById('bt-results').classList.remove('hidden');

  // Stat pills
  const retEl = document.getElementById('bt-stat-return');
  retEl.textContent = fmt.pct(data.total_return_pct);
  retEl.style.color = (data.total_return_pct >= 0) ? 'var(--green)' : 'var(--red)';

  document.getElementById('bt-stat-drawdown').textContent = fmt.pct(data.max_drawdown_pct);
  document.getElementById('bt-stat-winrate').textContent  = fmt.pct(data.win_rate_pct);
  document.getElementById('bt-stat-sharpe').textContent   =
    data.sharpe_ratio != null ? Number(data.sharpe_ratio).toFixed(2) : '—';
  document.getElementById('bt-stat-trades').textContent   = data.total_trades ?? '—';

  // Equity curve chart
  if (_btEquityChart) { _btEquityChart.destroy(); _btEquityChart = null; }
  const chartDates  = (data.equity_curve || []).map(p => p.date);
  const chartValues = (data.equity_curve || []).map(p => p.equity);

  const _btIsLight = _chartTheme() === 'light';
  const _btLabelClr = _btIsLight ? '#64748B' : '#94A3B8';
  const _btGridClr  = _btIsLight ? '#E2E8F0' : 'rgba(30,45,69,.6)';
  _btEquityChart = new ApexCharts(document.getElementById('bt-chart'), {
    chart:  { type: 'area', height: 280, background: 'transparent',
              toolbar: { show: false }, animations: { enabled: false },
              sparkline: { enabled: false } },
    series: [{ name: 'Equity', data: chartValues }],
    xaxis:  { categories: chartDates,
              labels: { style: { colors: _btLabelClr, fontSize: '11px' },
                        rotate: -30, hideOverlappingLabels: true },
              axisBorder: { show: false }, axisTicks: { show: false } },
    yaxis:  { labels: { style: { colors: _btLabelClr, fontSize: '11px' },
                        formatter: v => '$' + Math.round(v).toLocaleString() } },
    fill:   { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.3, opacityTo: 0.02 } },
    stroke: { width: 2, curve: 'smooth' },
    colors: ['#3B82F6'],
    grid:   { borderColor: _btGridClr, strokeDashArray: 3 },
    tooltip: { theme: _chartTheme(), y: { formatter: v => '$' + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) } },
    theme:  { mode: _chartTheme() },
    dataLabels: { enabled: false },
  });
  _btEquityChart.render();

  // Reset name input
  document.getElementById('bt-run-name').value = data.name || '';

  // Per-symbol breakdown
  const breakdownCard = document.getElementById('bt-breakdown-card');
  const breakdownBody = document.getElementById('bt-breakdown-body');
  const breakdown = data.symbol_breakdown || [];
  if (breakdown.length > 1 && breakdownCard && breakdownBody) {
    breakdownCard.style.display = '';
    breakdownBody.innerHTML = breakdown.map(b => {
      const pnlColor = b.total_pnl >= 0 ? 'var(--green)' : 'var(--red)';
      const pnlSign  = b.total_pnl >= 0 ? '+' : '';
      return `<tr>
        <td style="font-weight:600;">${escHtml(b.symbol)}</td>
        <td>${b.trades}</td>
        <td>${b.wins}</td>
        <td>${Number(b.win_rate_pct).toFixed(1)}%</td>
        <td style="color:${pnlColor};">${pnlSign}${fmt.usd(Math.abs(b.total_pnl))}</td>
      </tr>`;
    }).join('');
  } else if (breakdownCard) {
    breakdownCard.style.display = 'none';
  }

  // Trades table
  const tbody = document.getElementById('bt-trades-body');
  const trades = data.trades || [];
  if (trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="state-empty">No closed trades.</td></tr>';
  } else {
    tbody.innerHTML = trades.map(t => {
      const pnlColor = t.pnl >= 0 ? 'var(--green)' : 'var(--red)';
      const pnlSign  = t.pnl >= 0 ? '+' : '';
      return `<tr>
        <td>${t.date}</td>
        <td>${escHtml(t.symbol)}</td>
        <td><span class="badge b-${t.side === 'buy' ? 'buy' : 'sell'}">${t.side.toUpperCase()}</span></td>
        <td>${t.qty}</td>
        <td>${fmt.usd(t.price)}</td>
        <td style="color:${pnlColor};">${pnlSign}${fmt.usd(Math.abs(t.pnl))}</td>
      </tr>`;
    }).join('');
  }
}

function renderHistory(runs) {
  const el = document.getElementById('bt-history-list');
  if (!runs || runs.length === 0) {
    el.innerHTML = '<div class="state-empty">No saved runs yet.</div>';
    return;
  }
  el.innerHTML = runs.map(r => {
    const syms      = Array.isArray(r.symbols) ? r.symbols.join(', ') : r.symbols;
    const label     = r.name || fmt.time(r.created_at);
    const retColor  = r.total_return_pct >= 0 ? 'var(--green)' : 'var(--red)';
    const dateRange = (r.start_date && r.end_date)
      ? ` &middot; ${r.start_date} &rarr; ${r.end_date}` : '';
    const isBench   = !!r.is_benchmark;
    const benchBtn  = `
      <button class="bench-star-btn${isBench ? ' is-bench' : ''}"
              onclick="setBenchmark(${r.id}, this)"
              title="${isBench ? 'Current benchmark for this strategy' : 'Set as benchmark'}">
        <svg width="11" height="11" fill="${isBench ? 'currentColor' : 'none'}"
             stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
        </svg>
        ${isBench ? 'Benchmark' : 'Set Benchmark'}
      </button>`;
    return `<div style="display:flex;align-items:center;gap:10px;padding:.55rem 0;border-bottom:1px solid rgba(30,45,69,.7);">
      <div style="flex:1;min-width:0;">
        <div style="font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${label}</div>
        <div class="text-muted" style="font-size:11px;">${r.strategy} &middot; ${syms}${dateRange}</div>
      </div>
      <div style="font-size:13px;color:${retColor};min-width:52px;text-align:right;">${fmt.pct(r.total_return_pct)}</div>
      <div style="font-size:12px;color:#EF4444;min-width:52px;text-align:right;">${fmt.pct(r.max_drawdown_pct)}</div>
      <div style="font-size:12px;color:var(--muted);min-width:42px;text-align:right;">${fmt.pct(r.win_rate_pct)}</div>
      ${benchBtn}
      <button class="btn btn-sm btn-ghost" onclick="loadRun(${r.id})">Load</button>
      <button class="btn btn-sm btn-ghost" style="color:#EF4444;" onclick="deleteRun(${r.id})">Delete</button>
    </div>`;
  }).join('');
}

async function setBenchmark(runId, btn) {
  try {
    await api(`/api/backtest/runs/${runId}/set-benchmark`, { method: 'POST' });
    renderHistory(await api('/api/backtest/runs'));
  } catch (e) {
    console.error('setBenchmark error', e);
  }
}

async function loadRun(id) {
  try {
    const data = await api(`/api/backtest/runs/${id}`);
    renderResults(data);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (e) {
    console.error('loadRun error', e);
  }
}

async function deleteRun(id) {
  try {
    const res = await fetch(`/api/backtest/runs/${id}`, { method: 'DELETE' });
    if (!res.ok) return;
    if (_btCurrentRunId === id) {
      document.getElementById('bt-results').classList.add('hidden');
      _btCurrentRunId = null;
    }
    renderHistory(await api('/api/backtest/runs'));
  } catch (e) {
    console.error('deleteRun error', e);
  }
}

async function renameRun() {
  if (!_btCurrentRunId) return;
  const name = document.getElementById('bt-run-name').value.trim();
  if (!name) return;
  try {
    await api(`/api/backtest/runs/${_btCurrentRunId}`, {
      method:  'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ name }),
    });
    renderHistory(await api('/api/backtest/runs'));
  } catch (e) {
    console.error('renameRun error', e);
  }
}

function exportBtCsv() {
  if (!_btLastData?.trades?.length) return;
  const rows = [['Date', 'Symbol', 'Side', 'Shares', 'Fill Price', 'P&L']];
  _btLastData.trades.forEach(t => {
    rows.push([t.date, t.symbol, t.side, t.qty, t.price, t.pnl]);
  });
  const csv = rows.map(r => r.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  const label = (_btLastData.name || _btLastData.strategy || 'backtest').replace(/\s+/g, '_');
  a.download = `tradebot_${label}_trades.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}
