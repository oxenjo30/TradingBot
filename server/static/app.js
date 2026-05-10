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

      const tdChevron = document.createElement('td');
      tdChevron.style.cssText = 'color:#64748B;font-size:10px;user-select:none;padding-right:0;';
      tdChevron.textContent = '▶';

      const tdIcon = document.createElement('td');
      tdIcon.innerHTML = '<div class="icon-circle icon-purple" style="width:26px;height:26px;"><svg width="11" height="11" fill="none" stroke="#8B5CF6" stroke-width="2" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="2" height="2"/><rect x="13" y="9" width="2" height="2"/><path d="M9 13a3 3 0 0 0 6 0"/></svg></div>';

      const tdName = document.createElement('td');
      const nameDiv = document.createElement('div');
      nameDiv.className = 'truncate';
      nameDiv.style.fontWeight = '500';
      nameDiv.textContent = s.label;
      tdName.appendChild(nameDiv);

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

      tr.append(tdChevron, tdIcon, tdName, tdDesc, tdBadge, tdAction);
      tbody.appendChild(tr);

      // ── expandable sub-row ─────────────────────────────────────────────────
      const subTr = document.createElement('tr');
      subTr.className = 'hidden';
      subTr.style.background = 'rgba(17,24,39,0.4)';
      const subTd = document.createElement('td');
      subTd.colSpan = 6;
      subTd.style.padding = '0 .75rem .75rem 3rem';

      function buildSubTable(currentAccounts) {
        subTd.innerHTML = '';
        const subTable = document.createElement('table');
        subTable.className = 'dtable';
        subTable.style.marginTop = '.5rem';

        const thead = document.createElement('thead');
        thead.innerHTML = '<tr><th>Account</th><th>Type</th><th>Status</th><th style="text-align:right;">Action</th></tr>';
        const stbody = document.createElement('tbody');

        if (!currentAccounts.length) {
          const emptyTr = document.createElement('tr');
          const emptyTd = document.createElement('td');
          emptyTd.colSpan = 4;
          emptyTd.className = 'text-muted';
          emptyTd.style.cssText = 'font-size:12px;padding:.5rem 0;';
          emptyTd.textContent = 'No accounts assigned yet.';
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
        assignTd.style.paddingTop = '.5rem';
        const assignBtn = document.createElement('button');
        assignBtn.className = 'btn btn-ghost btn-sm';
        assignBtn.style.fontSize = '11px';
        assignBtn.textContent = '+ Assign Account';
        assignBtn.addEventListener('click', () => {
          const assignedIds = new Set(stratAccounts.map(a => a.id));
          const available = allAccounts.filter(a => !assignedIds.has(a.id));
          const sel = document.getElementById('assign-account-select');
          sel.innerHTML = '<option value="">Select a broker account…</option>';
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
        tdChevron.textContent = isExpanded ? '▶' : '▼';
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

  async function loadAccounts() {
    const grid = document.getElementById('accounts-grid');
    try {
      const accounts = await api('/api/broker-accounts', { key: 'keys-list' });
      grid.innerHTML = '';
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
    const card = document.createElement('div');
    card.className = 'card';
    card.style.cssText = 'padding:1rem;display:flex;flex-direction:column;gap:.6rem;';

    const header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;';
    const label = document.createElement('div');
    label.style.cssText = 'font-size:14px;font-weight:600;';
    label.textContent = acct.label;
    const typeBadge = document.createElement('span');
    typeBadge.className = 'badge ' + (acct.account_type === 'live' ? 'b-enabled' : 'b-disabled');
    typeBadge.textContent = acct.account_type === 'live' ? 'Live' : 'Paper';
    header.append(label, typeBadge);

    const keyRow = document.createElement('div');
    keyRow.className = 'text-muted';
    keyRow.style.cssText = 'font-size:12px;font-family:monospace;';
    keyRow.textContent = acct.api_key;

    const dateRow = document.createElement('div');
    dateRow.className = 'text-muted';
    dateRow.style.cssText = 'font-size:11px;';
    dateRow.textContent = 'Added ' + new Date(acct.created_at).toLocaleDateString();

    const statusRow = document.createElement('div');
    statusRow.style.cssText = 'font-size:12px;min-height:18px;';

    const actions = document.createElement('div');
    actions.style.cssText = 'display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.25rem;';

    const btnTest = document.createElement('button');
    btnTest.className = 'btn btn-ghost btn-sm';
    btnTest.style.fontSize = '11px';
    btnTest.textContent = 'Test Connection';
    btnTest.addEventListener('click', () => testConnection(acct.id, statusRow));

    const btnEdit = document.createElement('button');
    btnEdit.className = 'btn btn-ghost btn-sm';
    btnEdit.style.fontSize = '11px';
    btnEdit.textContent = 'Edit';
    btnEdit.addEventListener('click', () => openEditModal(acct));

    const btnRotate = document.createElement('button');
    btnRotate.className = 'btn btn-ghost btn-sm';
    btnRotate.style.fontSize = '11px';
    btnRotate.textContent = 'Rotate Keys';
    btnRotate.addEventListener('click', () => openRotateModal(acct.id));

    const btnDel = document.createElement('button');
    btnDel.className = 'btn btn-sm';
    btnDel.style.cssText = 'font-size:11px;color:#EF4444;background:none;border:1px solid #EF444440;';
    btnDel.textContent = 'Delete';
    btnDel.addEventListener('click', () => openDeleteModal(acct));

    actions.append(btnTest, btnEdit, btnRotate, btnDel);
    card.append(header, keyRow, dateRow, statusRow, actions);
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
    document.getElementById('edit-account-type').value = acct.account_type;
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
    } catch { /* non-blocking — warn not shown if fetch fails */ }
    openModal(document.getElementById('modal-delete-account'), async () => {
      await api(`/api/broker-accounts/${acct.id}`, { method: 'DELETE', key: 'del-account' });
      await loadAccounts();
    });
  }

  document.getElementById('btn-add-account').addEventListener('click', () => {
    ['add-label', 'add-api-key', 'add-api-secret'].forEach(id => document.getElementById(id).value = '');
    document.getElementById('add-account-type').value = 'paper';
    document.getElementById('add-error').classList.add('hidden');
    openModal(document.getElementById('modal-add-account'), async () => {
      const label = document.getElementById('add-label').value.trim();
      const apiKey = document.getElementById('add-api-key').value.trim();
      const apiSecret = document.getElementById('add-api-secret').value.trim();
      const accountType = document.getElementById('add-account-type').value;
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
          body: JSON.stringify({ label, api_key: apiKey, api_secret: apiSecret, account_type: accountType }),
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
