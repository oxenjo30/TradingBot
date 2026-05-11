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
  { id: 'tradier',     name: 'Tradier',       initials: 'TR', color: '#4F8EF7', bg: 'rgba(79,142,247,.15)',   available: false },
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
  return {
    series: [{ name: 'Equity', data: timestamps.map((t, i) => ({ x: new Date(t * 1000), y: equities[i] })) }],
    chart: { type: 'area', height: 220, toolbar: { show: false }, background: 'transparent', animations: { enabled: false } },
    dataLabels: { enabled: false },
    stroke: { curve: 'smooth', width: 2, colors: ['#3B82F6'] },
    fill: { type: 'gradient', gradient: { shade: 'dark', opacityFrom: 0.3, opacityTo: 0, stops: [0, 100] } },
    colors: ['#3B82F6'],
    annotations: { yaxis: [{ y: baseValue, borderColor: '#EF4444', strokeDashArray: 4, label: { text: 'Base', style: { color: '#EF4444', background: 'transparent' } } }] },
    xaxis: { type: 'datetime', labels: { style: { colors: '#64748B', fontSize: '11px' } }, axisBorder: { show: false }, axisTicks: { show: false } },
    yaxis: { labels: { style: { colors: '#64748B', fontSize: '11px' }, formatter: v => '$' + (v/1000).toFixed(0) + 'k' } },
    grid: { borderColor: '#1E2D45', strokeDashArray: 3 },
    theme: { mode: 'dark' },
    tooltip: { theme: 'dark', x: { format: 'HH:mm MMM dd' } }
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
  risk:        initRisk,
  settings:    initSettings,
  backtesting: initBacktesting,
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
      document.getElementById('pnl-daypnl').className = 'text-tabular ' + (a.day_pl >= 0 ? 'glow-green' : 'glow-red');

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
      const strats = await api('/api/strategies', { key: 'idx-strategies' });
      const botsEl = document.getElementById('bots-val');
      clearState(botsEl);
      botsEl.textContent = strats.filter(s => s.enabled).length;

      const engine = await api('/api/engine', { key: 'idx-engine' });
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

      document.getElementById('sys-lastrun').textContent = engine.ts ? fmt.time(engine.ts) : 'Never';

    } catch (e) {
      if (e.name === 'AbortError') return;
      showError(document.getElementById('bots-val'));
      throw e;
    }
  }

  // ── Fetch positions → allocation donut ──
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
// initBots — bots.html
// ─────────────────────────────────────────
async function initBots() {
  const chipEl = document.getElementById('market-chip');
  let clock = await initClockChip(chipEl);
  const marketOpen = clock ? clock.is_open : null;

  let account = null;
  let killSwitchState = null; // null=unknown, true/false=known

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

  async function fetchStrategies() {
    const [strats, engineStatus, allAccounts] = await Promise.all([
      api('/api/strategies',      { key: 'bots-strats' }),
      api('/api/engine',          { key: 'bots-engine' }),
      api('/api/broker-accounts', { key: 'bots-all-accts' }),
    ]);

    const ranMap = {};
    (engineStatus.ran || []).forEach(r => { ranMap[r.strategy] = r; });

    const enabled = strats.filter(s => s.enabled).length;
    document.getElementById('engine-status-txt').textContent =
      `${enabled} of ${strats.length} strategies enabled · Last run: ${engineStatus.ts ? fmt.time(engineStatus.ts) : 'Never'}`;

    const tbody = document.getElementById('strat-body');
    tbody.innerHTML = '';

    for (const s of strats) {
      let stratAccounts = [];
      try {
        stratAccounts = await api(`/api/strategies/${s.name}/accounts`, { key: `sa-${s.name}` });
      } catch { /* no assignments yet — empty array is fine */ }

      // ── main strategy row ──────────────────────────────────────────────────
      const tr = document.createElement('tr');
      tr.style.cursor = 'pointer';
      tr.dataset.expanded = 'false';

      const tdLeft = document.createElement('td');
      tdLeft.style.cssText = 'white-space:nowrap;';
      const leftWrap = document.createElement('div');
      leftWrap.style.cssText = 'display:flex;align-items:center;gap:8px;';
      const chevronEl = document.createElement('span');
      chevronEl.style.cssText = 'color:#64748B;font-size:10px;user-select:none;display:inline-block;transition:transform .2s;flex-shrink:0;';
      chevronEl.textContent = '▶';
      const iconEl = document.createElement('div');
      iconEl.className = 'icon-circle icon-purple';
      iconEl.style.cssText = 'width:24px;height:24px;flex-shrink:0;';
      iconEl.innerHTML = '<svg width="11" height="11" fill="none" stroke="#8B5CF6" stroke-width="2" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="2" height="2"/><rect x="13" y="9" width="2" height="2"/><path d="M9 13a3 3 0 0 0 6 0"/></svg>';
      leftWrap.append(chevronEl, iconEl);
      tdLeft.appendChild(leftWrap);

      const tdName = document.createElement('td');
      const nameWrap = document.createElement('div');
      nameWrap.style.cssText = 'display:flex;align-items:center;gap:6px;min-width:0;';
      const nameDiv = document.createElement('div');
      nameDiv.className = 'truncate';
      nameDiv.style.fontWeight = '500';
      nameDiv.textContent = s.label;
      const countPill = document.createElement('span');
      countPill.className = 'acct-pill';
      countPill.textContent = stratAccounts.length ? `${stratAccounts.length} acct${stratAccounts.length !== 1 ? 's' : ''}` : 'no accts';
      if (!stratAccounts.length) countPill.classList.add('acct-pill-empty');
      nameWrap.append(nameDiv, countPill);
      tdName.appendChild(nameWrap);

      const tdDesc = document.createElement('td');
      tdDesc.className = 'text-muted truncate';
      tdDesc.textContent = s.description;

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
        badge.appendChild(document.createTextNode('Enabled'));
      } else {
        badge.textContent = bt;
      }
      tdBadge.appendChild(badge);

      const tdAction = document.createElement('td');
      tdAction.style.textAlign = 'right';
      const toggleBtn = document.createElement('button');
      toggleBtn.className = 'btn btn-sm ' + (s.enabled ? 'btn-ghost' : 'btn-primary');
      toggleBtn.textContent = s.enabled ? 'Disable' : 'Enable';
      toggleBtn.addEventListener('click', (e) => { e.stopPropagation(); confirmToggle(s, !s.enabled, toggleBtn); });
      tdAction.appendChild(toggleBtn);

      tr.append(tdLeft, tdName, tdDesc, tdBadge, tdAction);
      tbody.appendChild(tr);

      // ── expandable sub-row ─────────────────────────────────────────────────
      const subTr = document.createElement('tr');
      subTr.className = 'hidden';
      subTr.style.background = 'rgba(17,24,39,0.4)';
      const subTd = document.createElement('td');
      subTd.colSpan = 5;
      subTd.style.cssText = 'padding:0 .75rem .75rem 2.5rem;border-left:2px solid rgba(139,92,246,.3);';

      function buildSubTable(currentAccounts) {
        subTd.innerHTML = '';
        // update the count pill on the parent row
        countPill.textContent = currentAccounts.length ? `${currentAccounts.length} acct${currentAccounts.length !== 1 ? 's' : ''}` : 'no accts';
        countPill.classList.toggle('acct-pill-empty', !currentAccounts.length);

        const panelHeader = document.createElement('div');
        panelHeader.style.cssText = 'font-size:11px;font-weight:600;color:#64748B;text-transform:uppercase;letter-spacing:.06em;padding:.6rem 0 .2rem;';
        panelHeader.textContent = 'Broker Accounts';
        const panelSub = document.createElement('div');
        panelSub.style.cssText = 'font-size:11px;color:#64748B;padding-bottom:.5rem;';
        panelSub.textContent = 'This strategy can run on multiple accounts simultaneously. Each account is toggled independently below.';
        subTd.append(panelHeader, panelSub);

        const subTable = document.createElement('table');
        subTable.className = 'dtable';

        const thead = document.createElement('thead');
        thead.innerHTML = '<tr><th>Account</th><th>Type</th><th>Status</th><th style="text-align:right;">Action</th></tr>';
        const stbody = document.createElement('tbody');

        if (!currentAccounts.length) {
          const emptyTr = document.createElement('tr');
          const emptyTd = document.createElement('td');
          emptyTd.colSpan = 4;
          emptyTd.style.cssText = 'padding:.75rem 0;text-align:center;';
          emptyTd.innerHTML = '<span style="font-size:12px;color:#64748B;">No broker accounts assigned — click <strong style="color:#E6EBF5;">+ Assign Account</strong> below to link one.</span>';
          emptyTr.appendChild(emptyTd);
          stbody.appendChild(emptyTr);
        }

        currentAccounts.forEach(acct => {
          const atr = document.createElement('tr');

          const tdLbl = document.createElement('td');
          tdLbl.textContent = acct.label;

          const tdType = document.createElement('td');
          tdType.innerHTML = `<span class="badge ${acct.account_type === 'live' ? 'b-enabled' : 'b-disabled'}">${acct.account_type}</span>`;

          const tdSt = document.createElement('td');
          const enBadge = document.createElement('span');
          enBadge.className = 'badge ' + (acct.enabled ? 'b-enabled' : 'b-disabled');
          if (acct.enabled) {
            const dot = document.createElement('span'); dot.className = 'pdot'; enBadge.appendChild(dot);
            enBadge.appendChild(document.createTextNode('Enabled'));
          } else {
            enBadge.textContent = 'Disabled';
          }
          tdSt.appendChild(enBadge);

          const tdAct = document.createElement('td');
          tdAct.style.textAlign = 'right';

          const perToggleBtn = document.createElement('button');
          perToggleBtn.className = 'btn btn-sm btn-ghost';
          perToggleBtn.style.fontSize = '11px';
          perToggleBtn.textContent = acct.enabled ? 'Disable' : 'Enable';
          perToggleBtn.addEventListener('click', async () => {
            perToggleBtn.disabled = true;
            try {
              await api(`/api/strategies/${s.name}/accounts/${acct.id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: !acct.enabled }),
                key: `sa-toggle-${s.name}-${acct.id}`,
              });
              stratAccounts = await api(`/api/strategies/${s.name}/accounts`, { key: `sa-${s.name}` });
              buildSubTable(stratAccounts);
            } catch { perToggleBtn.disabled = false; }
          });

          const removeBtn = document.createElement('button');
          removeBtn.className = 'btn btn-sm';
          removeBtn.style.cssText = 'font-size:11px;color:#EF4444;background:none;border:none;margin-left:.25rem;';
          removeBtn.textContent = '×';
          removeBtn.title = 'Unassign account';
          removeBtn.addEventListener('click', () => {
            const descEl = document.getElementById('unassign-desc');
            descEl.innerHTML = '';
            descEl.appendChild(document.createTextNode('Remove '));
            const strong = document.createElement('strong'); strong.textContent = acct.label;
            descEl.appendChild(strong);
            descEl.appendChild(document.createTextNode(` from ${s.label}?`));
            openModal(document.getElementById('modal-unassign'), async () => {
              await api(`/api/strategies/${s.name}/accounts/${acct.id}`, {
                method: 'DELETE', key: `sa-del-${s.name}-${acct.id}`,
              });
              stratAccounts = await api(`/api/strategies/${s.name}/accounts`, { key: `sa-${s.name}` });
              buildSubTable(stratAccounts);
            });
          });

          tdAct.append(perToggleBtn, removeBtn);
          atr.append(tdLbl, tdType, tdSt, tdAct);
          stbody.appendChild(atr);
        });

        // ── Assign Account button ────────────────────────────────────────────
        const assignTr = document.createElement('tr');
        const assignTd = document.createElement('td');
        assignTd.colSpan = 4;
        assignTd.style.cssText = 'padding-top:.6rem;border-bottom:none;';
        const assignBtn = document.createElement('button');
        assignBtn.className = 'btn btn-sm';
        assignBtn.style.cssText = 'font-size:11px;background:rgba(139,92,246,.15);color:#A78BFA;border:1px solid rgba(139,92,246,.25);';
        assignBtn.textContent = '+ Assign Account';
        assignBtn.addEventListener('click', () => {
          const assignedIds = new Set(stratAccounts.map(a => a.id));
          const available = allAccounts.filter(a => !assignedIds.has(a.id));
          const sel = document.getElementById('assign-account-select');
          sel.innerHTML = available.length
            ? '<option value="">Select a broker account…</option>'
            : '<option value="">No available accounts — add one in API Keys</option>';
          available.forEach(a => {
            const opt = document.createElement('option');
            opt.value = a.id;
            opt.textContent = `${a.label} (${a.account_type})`;
            sel.appendChild(opt);
          });
          document.getElementById('assign-strategy-name').textContent = s.label;
          document.getElementById('assign-error').classList.add('hidden');
          openModal(document.getElementById('modal-assign-account'), async () => {
            const acctId = parseInt(sel.value);
            const errEl = document.getElementById('assign-error');
            if (!acctId) { errEl.textContent = 'Please select an account.'; errEl.classList.remove('hidden'); return; }
            try {
              await api(`/api/strategies/${s.name}/accounts`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ account_id: acctId, enabled: true }),
                key: `sa-assign-${s.name}`,
              });
              stratAccounts = await api(`/api/strategies/${s.name}/accounts`, { key: `sa-${s.name}` });
              buildSubTable(stratAccounts);
            } catch {
              errEl.textContent = 'Assign failed.';
              errEl.classList.remove('hidden');
            }
          });
        });
        assignTd.appendChild(assignBtn);
        assignTr.appendChild(assignTd);
        stbody.appendChild(assignTr);

        subTable.append(thead, stbody);
        subTd.appendChild(subTable);
      }

      buildSubTable(stratAccounts);
      subTr.appendChild(subTd);
      tbody.appendChild(subTr);

      tr.addEventListener('click', () => {
        const isExpanded = tr.dataset.expanded === 'true';
        tr.dataset.expanded = isExpanded ? 'false' : 'true';
        chevronEl.style.transform = isExpanded ? '' : 'rotate(90deg)';
        subTr.classList.toggle('hidden', isExpanded);
      });
    }
  }

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
        await fetchStrategies();
      } catch {
        triggerBtn.disabled = false;
        triggerBtn.textContent = enable ? 'Enable' : 'Disable';
        triggerBtn.closest('td').textContent = 'Action failed — check logs.';
      }
    });
  }

  document.getElementById('btn-run-now').addEventListener('click', () => {
    const modeText = account?.account_type === 'paper' ? 'Paper Trading' : 'Live Trading';
    const modeEl = document.getElementById('modal-run-mode');
    modeEl.innerHTML = '';
    modeEl.appendChild(document.createTextNode('Account mode: '));
    const strong = document.createElement('strong');
    strong.textContent = modeText;
    modeEl.appendChild(strong);
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
      resultEl.innerHTML = '';

      const lines = [
        'Strategies evaluated: ' + (result.ran?.length || 0),
        'Signals generated: ' + (result.signals?.length || 0),
      ];
      if (result.error) lines.push('Engine error: ' + result.error);
      errors.forEach(e => lines.push('Error in ' + e.strategy + ': ' + e.error));

      lines.forEach(line => {
        const p = document.createElement('div');
        p.textContent = line;
        resultEl.appendChild(p);
      });
      resultEl.classList.remove('hidden');
      setTimeout(() => resultEl.classList.add('hidden'), 10_000);
      await fetchStrategies();
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

  async function setKillSwitch(on) {
    try {
      const res = await api('/api/risk/kill_switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ on }),
        key: 'bots-ks'
      });
      applyKillSwitchUI(res.kill_switch);
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

  await fetchAccount();
  await fetchRiskState();
  createPoller(fetchStrategies, 30_000).start();
}

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
      badge.className = 'badge b-error';
      badge.textContent = 'ACTIVE';
      btn.textContent = 'Deactivate Kill Switch';
      btn.className = 'btn btn-ghost';
    } else {
      card.style.borderColor = 'rgba(239,68,68,.25)';
      card.style.background = '';
      badge.className = 'badge b-disabled';
      badge.textContent = 'OFF';
      btn.textContent = 'Activate Kill Switch';
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
      if (!val) return;
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
    wrap.querySelectorAll('.blacklist-chip').forEach(c => c.remove());
    if (!symbols || symbols.length === 0) {
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');
    symbols.forEach(sym => {
      const chip = document.createElement('span');
      chip.className = 'blacklist-chip';
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

  await loadRisk();
}

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

// ─────────────────────────────────────────
// initApiKeys — apikeys.html
// ─────────────────────────────────────────
async function initApiKeys() {
  initClockChip(document.getElementById('market-chip'));
  let currentMode = 'paper';

  // ── Trading Mode ──────────────────────────────────────────────────────────
  async function loadMode() {
    try {
      const risk = await api('/api/risk', { key: 'apikeys-risk' });
      currentMode = risk.trading_mode || 'paper';
    } catch { currentMode = 'paper'; }
    applyMode(currentMode, false);
  }

  function applyMode(mode, updateNote = true) {
    currentMode = mode;
    document.getElementById('mode-check-paper').classList.toggle('hidden', mode !== 'paper');
    document.getElementById('mode-check-live').classList.toggle('hidden',  mode !== 'live');
    document.getElementById('mode-opt-paper').classList.toggle('mode-opt-active', mode === 'paper');
    document.getElementById('mode-opt-live').classList.toggle('mode-opt-active',  mode === 'live');
    if (updateNote) {
      const note = document.getElementById('accounts-mode-note');
      note.textContent = mode === 'paper'
        ? 'Showing all accounts · Paper accounts are active'
        : 'Showing all accounts · Live accounts are active';
    }
  }

  document.getElementById('mode-selector').addEventListener('click', async (e) => {
    const opt = e.target.closest('.mode-option');
    if (!opt) return;
    const newMode = opt.dataset.mode;
    if (newMode === currentMode) return;

    if (newMode === 'live') {
      openModal(document.getElementById('modal-live-confirm'), async () => {
        await saveMode(newMode);
      });
    } else {
      await saveMode(newMode);
    }
  });

  async function saveMode(mode) {
    try {
      await api('/api/risk/trading_mode', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: mode }),
        key: 'mode-save',
      });
      applyMode(mode);
      await loadAccounts();
    } catch { /* no-op */ }
  }

  // ── Type selector helper ──────────────────────────────────────────────────
  function wireTypeSelector(selectorId, hiddenId) {
    const sel = document.getElementById(selectorId);
    const hidden = document.getElementById(hiddenId);
    sel.querySelectorAll('.type-opt').forEach(opt => {
      opt.addEventListener('click', () => {
        sel.querySelectorAll('.type-opt').forEach(o => o.classList.remove('active'));
        opt.classList.add('active');
        hidden.value = opt.dataset.val;
      });
    });
  }

  function setTypeSelector(selectorId, hiddenId, val) {
    const sel = document.getElementById(selectorId);
    const hidden = document.getElementById(hiddenId);
    hidden.value = val;
    sel.querySelectorAll('.type-opt').forEach(o => {
      o.classList.toggle('active', o.dataset.val === val);
    });
  }

  wireTypeSelector('add-type-selector', 'add-account-type');
  wireTypeSelector('edit-type-selector', 'edit-account-type');

  // ── Account cards ─────────────────────────────────────────────────────────
  async function loadAccounts() {
    const grid = document.getElementById('accounts-grid');
    const note = document.getElementById('accounts-mode-note');
    try {
      const accounts = await api('/api/broker-accounts', { key: 'keys-list' });
      grid.innerHTML = '';
      note.textContent = currentMode === 'paper'
        ? 'Showing all accounts · Paper accounts are active'
        : 'Showing all accounts · Live accounts are active';

      if (!accounts.length) {
        const empty = document.createElement('div');
        empty.className = 'state-empty';
        empty.textContent = 'No broker accounts yet. Add one to get started.';
        grid.appendChild(empty);
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
    const isActive = acct.account_type === currentMode;

    const card = document.createElement('div');
    card.className = 'broker-card' + (isActive ? '' : ' broker-card-dim');

    // ── Header ───────────────────────────────────────────────────────────────
    const cardTop = document.createElement('div');
    cardTop.className = 'broker-card-top';

    const logoEl = document.createElement('div');
    logoEl.style.cssText = `width:42px;height:42px;border-radius:10px;background:${broker.bg};color:${broker.color};display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;letter-spacing:-.5px;flex-shrink:0;`;
    logoEl.textContent = broker.initials;

    const brokerInfo = document.createElement('div');
    brokerInfo.style.cssText = 'flex:1;min-width:0;';
    const brokerNameEl = document.createElement('div');
    brokerNameEl.style.cssText = 'font-size:15px;font-weight:700;line-height:1.2;';
    brokerNameEl.textContent = broker.name;
    const acctLabelEl = document.createElement('div');
    acctLabelEl.className = 'text-muted';
    acctLabelEl.style.cssText = 'font-size:12px;margin-top:2px;';
    acctLabelEl.textContent = acct.label;
    brokerInfo.append(brokerNameEl, acctLabelEl);

    const rightBadges = document.createElement('div');
    rightBadges.style.cssText = 'display:flex;flex-direction:column;align-items:flex-end;gap:4px;';

    const typeBadge = document.createElement('span');
    typeBadge.className = 'badge ' + (isLive ? 'b-enabled' : 'b-disabled');
    if (isLive) {
      const dot = document.createElement('span'); dot.className = 'pdot'; typeBadge.appendChild(dot);
      typeBadge.appendChild(document.createTextNode('Live'));
    } else {
      typeBadge.textContent = 'Paper';
    }

    const activeBadge = document.createElement('span');
    activeBadge.className = 'badge ' + (isActive ? 'b-enabled' : 'b-disabled');
    activeBadge.style.fontSize = '10px';
    activeBadge.textContent = isActive ? 'Active Mode' : 'Inactive';

    rightBadges.append(typeBadge, activeBadge);
    cardTop.append(logoEl, brokerInfo, rightBadges);

    // ── Key chip ─────────────────────────────────────────────────────────────
    const keyChip = document.createElement('div');
    keyChip.className = 'broker-key-chip';
    const keyLabel = document.createElement('span');
    keyLabel.className = 'broker-key-label';
    keyLabel.textContent = 'API KEY';
    const keyVal = document.createElement('span');
    keyVal.className = 'broker-key-val';
    keyVal.textContent = acct.api_key;
    keyChip.append(keyLabel, keyVal);

    // ── Meta row ─────────────────────────────────────────────────────────────
    const metaRow = document.createElement('div');
    metaRow.style.cssText = 'display:flex;align-items:center;justify-content:space-between;min-height:20px;';
    const dateEl = document.createElement('span');
    dateEl.className = 'text-muted';
    dateEl.style.fontSize = '11px';
    dateEl.textContent = 'Added ' + new Date(acct.created_at).toLocaleDateString('en-US', { month:'short', day:'numeric', year:'numeric' });
    const statusEl = document.createElement('span');
    statusEl.style.cssText = 'font-size:11px;font-weight:500;';
    metaRow.append(dateEl, statusEl);

    // ── Divider ──────────────────────────────────────────────────────────────
    const divider = document.createElement('div');
    divider.style.cssText = 'border-top:1px solid rgba(30,45,69,.8);';

    // ── Actions ──────────────────────────────────────────────────────────────
    const actions = document.createElement('div');
    actions.style.cssText = 'display:flex;gap:.4rem;align-items:center;flex-wrap:wrap;';

    const mkBtn = (iconPath, label, cls) => {
      const b = document.createElement('button');
      b.className = 'btn btn-sm ' + (cls || 'btn-ghost');
      b.style.fontSize = '11px';
      b.innerHTML = `<svg width="11" height="11" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">${iconPath}</svg>${label}`;
      return b;
    };

    const btnTest   = mkBtn('<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>', ' Test');
    const btnEdit   = mkBtn('<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>', ' Edit');
    const btnRotate = mkBtn('<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>', ' Rotate Keys');
    const btnDel    = mkBtn('<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/>', ' Delete', '');
    btnDel.style.cssText = 'font-size:11px;color:#EF4444;background:none;border:1px solid rgba(239,68,68,.25);margin-left:auto;';

    btnTest.addEventListener('click',   () => testConnection(acct.id, statusEl));
    btnEdit.addEventListener('click',   () => openEditModal(acct));
    btnRotate.addEventListener('click', () => openRotateModal(acct.id));
    btnDel.addEventListener('click',    () => openDeleteModal(acct));

    actions.append(btnTest, btnEdit, btnRotate, btnDel);
    card.append(cardTop, keyChip, metaRow, divider, actions);
    return card;
  }

  async function testConnection(accountId, statusEl) {
    statusEl.textContent = 'Testing…';
    statusEl.style.color = '';
    try {
      const result = await api(`/api/broker-accounts/${accountId}/status`, { key: `test-${accountId}` });
      statusEl.style.color = '#22C55E';
      statusEl.textContent = `✓ Connected · ${result.account_type} · equity ${fmt.usd(result.equity)}`;
    } catch {
      statusEl.style.color = '#EF4444';
      statusEl.textContent = '✗ Connection failed';
    }
  }

  function openEditModal(acct) {
    document.getElementById('edit-account-id').value = acct.id;
    document.getElementById('edit-label').value = acct.label;
    setTypeSelector('edit-type-selector', 'edit-account-type', acct.account_type);
    document.getElementById('edit-error').classList.add('hidden');
    openModal(document.getElementById('modal-edit-account'), async () => {
      const label = document.getElementById('edit-label').value.trim();
      const accountType = document.getElementById('edit-account-type').value;
      const errEl = document.getElementById('edit-error');
      if (!label) { errEl.textContent = 'Label is required.'; errEl.classList.remove('hidden'); return; }
      try {
        await api(`/api/broker-accounts/${acct.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ label, account_type: accountType }),
          key: 'edit-account',
        });
        await loadAccounts();
      } catch (e) {
        errEl.textContent = 'Save failed.';
        errEl.classList.remove('hidden');
        throw e;
      }
    });
  }

  function openRotateModal(accountId) {
    document.getElementById('rotate-account-id').value = accountId;
    document.getElementById('rotate-api-key').value = '';
    document.getElementById('rotate-api-secret').value = '';
    document.getElementById('rotate-error').classList.add('hidden');
    openModal(document.getElementById('modal-rotate'), async () => {
      const apiKey = document.getElementById('rotate-api-key').value.trim();
      const apiSecret = document.getElementById('rotate-api-secret').value.trim();
      const errEl = document.getElementById('rotate-error');
      if (!apiKey || !apiSecret) { errEl.textContent = 'Both fields required.'; errEl.classList.remove('hidden'); return; }
      try {
        await api(`/api/broker-accounts/${accountId}/credentials`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ api_key: apiKey, api_secret: apiSecret }),
          key: 'rotate-account',
        });
        await loadAccounts();
      } catch (e) {
        errEl.textContent = 'Rotate failed.';
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
    } catch { /* non-blocking */ }
    openModal(document.getElementById('modal-delete-account'), async () => {
      await api(`/api/broker-accounts/${acct.id}`, { method: 'DELETE', key: 'del-account' });
      await loadAccounts();
    });
  }

  // Build broker picker with tabs (Step 1)
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

  // Step back button
  document.getElementById('add-step-back').addEventListener('click', () => {
    document.getElementById('add-step-1').classList.remove('hidden');
    document.getElementById('add-step-2').classList.add('hidden');
  });

  // Broker picker click (step 1 → step 2)
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
    // Reset to step 1
    document.getElementById('add-step-1').classList.remove('hidden');
    document.getElementById('add-step-2').classList.add('hidden');
    ['add-label', 'add-api-key', 'add-api-secret'].forEach(id => document.getElementById(id).value = '');
    setTypeSelector('add-type-selector', 'add-account-type', 'paper');
    document.getElementById('add-error').classList.add('hidden');
    buildBrokerPicker();
    openModal(document.getElementById('modal-add-account'), async () => {
      const label = document.getElementById('add-label').value.trim();
      const apiKey = document.getElementById('add-api-key').value.trim();
      const apiSecret = document.getElementById('add-api-secret').value.trim();
      const accountType = document.getElementById('add-account-type').value;
      const broker = document.getElementById('add-broker').value || 'alpaca';
      const errEl = document.getElementById('add-error');
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

  await loadMode();
  await loadAccounts();
}

// ─────────────────────────────────────────
// initSettings — settings.html
// ─────────────────────────────────────────
async function initSettings() {
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
}

// ─────────────────────────────────────────
// initBacktesting — backtesting.html
// ─────────────────────────────────────────

let _btCurrentRunId = null;
let _btEquityChart  = null;

async function initBacktesting() {
  // Populate strategy dropdown from /api/strategies
  try {
    const strats = await api('/api/strategies');
    const sel = document.getElementById('bt-strategy');
    sel.innerHTML = strats
      .filter(s => !s.hidden)
      .map(s => `<option value="${s.name}">${s.label}</option>`)
      .join('');
  } catch (e) {
    console.error('initBacktesting: failed to load strategies', e);
  }

  // Default date range: last 365 days
  const today    = new Date().toISOString().slice(0, 10);
  const yearAgo  = new Date(Date.now() - 365 * 86400_000).toISOString().slice(0, 10);
  document.getElementById('bt-end').value   = today;
  document.getElementById('bt-start').value = yearAgo;

  // Load history
  try {
    const runs = await api('/api/backtest/runs');
    renderHistory(runs);
  } catch (e) {
    console.error('initBacktesting: failed to load history', e);
  }
}

async function runBacktest() {
  const btn   = document.getElementById('bt-run-btn');
  const errEl = document.getElementById('bt-error');
  errEl.classList.add('hidden');

  const rawSymbols = document.getElementById('bt-symbols').value;
  const symbols = rawSymbols.split(',').map(s => s.trim()).filter(Boolean);

  const body = {
    strategy:          document.getElementById('bt-strategy').value,
    symbols,
    start_date:        document.getElementById('bt-start').value,
    end_date:          document.getElementById('bt-end').value,
    initial_capital:   parseFloat(document.getElementById('bt-capital').value),
    position_size_pct: parseFloat(document.getElementById('bt-possize').value),
    commission_pct:    parseFloat(document.getElementById('bt-commission').value),
    slippage_pct:      parseFloat(document.getElementById('bt-slippage').value),
  };

  btn.disabled = true;
  btn.innerHTML = '<svg style="width:14px;height:14px;animation:spin 1s linear infinite;margin-right:6px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>Running&hellip;';

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
    renderResults(data);
    try { renderHistory(await api('/api/backtest/runs')); } catch (_) { /* non-fatal */ }
  } catch (e) {
    errEl.textContent = e.message;
    errEl.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Run Backtest';
  }
}

function renderResults(data) {
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

  _btEquityChart = new ApexCharts(document.getElementById('bt-chart'), {
    chart:  { type: 'area', height: 280, background: 'transparent',
              toolbar: { show: false }, animations: { enabled: false },
              sparkline: { enabled: false } },
    series: [{ name: 'Equity', data: chartValues }],
    xaxis:  { categories: chartDates,
              labels: { style: { colors: '#64748B', fontSize: '11px' },
                        rotate: -30, hideOverlappingLabels: true },
              axisBorder: { show: false }, axisTicks: { show: false } },
    yaxis:  { labels: { style: { colors: '#64748B', fontSize: '11px' },
                        formatter: v => '$' + Math.round(v).toLocaleString() } },
    fill:   { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.3, opacityTo: 0.02 } },
    stroke: { width: 2, curve: 'smooth' },
    colors: ['#3B82F6'],
    grid:   { borderColor: 'rgba(30,45,69,.6)', strokeDashArray: 3 },
    tooltip: { theme: 'dark', y: { formatter: v => '$' + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) } },
    theme:  { mode: 'dark' },
    dataLabels: { enabled: false },
  });
  _btEquityChart.render();

  // Reset name input
  document.getElementById('bt-run-name').value = data.name || '';

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
        <td>${t.symbol}</td>
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
    const syms  = Array.isArray(r.symbols) ? r.symbols.join(', ') : r.symbols;
    const label = r.name || fmt.time(r.created_at);
    const retColor = r.total_return_pct >= 0 ? 'var(--green)' : 'var(--red)';
    return `<div style="display:flex;align-items:center;gap:10px;padding:.55rem 0;border-bottom:1px solid rgba(30,45,69,.7);">
      <div style="flex:1;min-width:0;">
        <div style="font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${label}</div>
        <div class="text-muted" style="font-size:11px;">${r.strategy} &middot; ${syms}</div>
      </div>
      <div style="font-size:13px;color:${retColor};min-width:52px;text-align:right;">${fmt.pct(r.total_return_pct)}</div>
      <div style="font-size:12px;color:#EF4444;min-width:52px;text-align:right;">${fmt.pct(r.max_drawdown_pct)}</div>
      <div style="font-size:12px;color:var(--muted);min-width:42px;text-align:right;">${fmt.pct(r.win_rate_pct)}</div>
      <button class="btn btn-sm btn-ghost" onclick="loadRun(${r.id})">Load</button>
      <button class="btn btn-sm btn-ghost" style="color:#EF4444;" onclick="deleteRun(${r.id})">Delete</button>
    </div>`;
  }).join('');
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
