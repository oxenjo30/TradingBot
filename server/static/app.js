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
