const fmtUSD = (n) => (n == null || isNaN(n)) ? "—"
  : n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const fmtNum = (n, d = 2) => (n == null || isNaN(n)) ? "—"
  : Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtPct = (n) => (n == null || isNaN(n)) ? "—" : (n >= 0 ? "+" : "") + Number(n).toFixed(2) + "%";
const cls = (n) => n > 0 ? "pos" : n < 0 ? "neg" : "";

let chartPeriod = "1D";

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`${r.status}: ${t}`);
  }
  if (r.status === 204) return null;
  return r.json();
}

async function refreshAccount() {
  const a = await api("/api/account");
  const c = await api("/api/clock");
  document.getElementById("env-line").textContent =
    `${a.account_type.toUpperCase()} • ${a.status.replace("AccountStatus.", "")}`;
  const ms = document.getElementById("market-state");
  ms.textContent = "market: " + (c.is_open ? "OPEN" : "CLOSED");
  ms.classList.remove("text-ok", "text-bad");
  ms.classList.add(c.is_open ? "text-ok" : "text-mute");
  ms.style.color = c.is_open ? "#16c784" : "#7f8aa3";

  const cards = [
    { label: "Equity",        val: fmtUSD(a.equity) },
    { label: "Cash",          val: fmtUSD(a.cash) },
    { label: "Buying Power",  val: fmtUSD(a.buying_power) },
    { label: "Day P&L",       val: fmtUSD(a.day_pl), sub: fmtPct(a.day_pl_pct), tone: a.day_pl },
    { label: "Portfolio",     val: fmtUSD(a.portfolio_value) },
  ];
  document.getElementById("acct-cards").innerHTML = cards.map(c => `
    <div class="card p-4">
      <div class="text-xs mute mb-1">${c.label}</div>
      <div class="text-xl font-semibold ${cls(c.tone ?? 0)}">${c.val}</div>
      ${c.sub ? `<div class="text-xs ${cls(c.tone ?? 0)}">${c.sub}</div>` : ""}
    </div>`).join("");

  document.getElementById("updated").textContent = "updated " + new Date().toLocaleTimeString();
}

async function refreshPositions() {
  const ps = await api("/api/positions");
  const tbody = document.querySelector("#positions-table tbody");
  if (!ps.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="mute text-center py-6">No positions</td></tr>`;
    return;
  }
  tbody.innerHTML = ps.map(p => `
    <tr>
      <td class="font-semibold">${p.symbol}</td>
      <td><span class="tag ${p.side === "long" ? "buy" : "sell"}">${p.side}</span></td>
      <td>${fmtNum(p.qty, 4)}</td>
      <td>${fmtUSD(p.avg_entry_price)}</td>
      <td>${fmtUSD(p.current_price)}</td>
      <td>${fmtUSD(p.market_value)}</td>
      <td class="${cls(p.unrealized_pl)}">${fmtUSD(p.unrealized_pl)}</td>
      <td class="${cls(p.unrealized_plpc)}">${fmtPct(p.unrealized_plpc)}</td>
      <td><button class="btn danger" onclick="closePosition('${p.symbol}')">Close</button></td>
    </tr>`).join("");
}

async function refreshOrders() {
  const os = await api("/api/orders?limit=50");
  const tbody = document.getElementById("orders-body");
  if (!os.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="mute text-center py-6">No orders</td></tr>`;
    return;
  }
  tbody.innerHTML = os.map(o => {
    const t = o.submitted_at ? new Date(o.submitted_at).toLocaleString() : "—";
    const cancelable = ["new", "accepted", "pending_new", "partially_filled"].includes(o.status);
    return `
      <tr>
        <td class="mute">${t}</td>
        <td class="font-semibold">${o.symbol}</td>
        <td><span class="tag ${o.side}">${o.side}</span></td>
        <td>${fmtNum(o.qty, 4)}</td>
        <td>${fmtNum(o.filled_qty, 4)}</td>
        <td>${o.filled_avg_price ? fmtUSD(o.filled_avg_price) : "—"}</td>
        <td class="mute">${o.type}</td>
        <td><span class="tag ${o.status}">${o.status}</span></td>
        <td>${cancelable ? `<button class="btn" onclick="cancelOrder('${o.id}')">Cancel</button>` : ""}</td>
      </tr>`;
  }).join("");
}

async function refreshSignals() {
  const ss = await api("/api/signals?limit=100");
  const tbody = document.getElementById("signals-body");
  if (!ss.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="mute text-center py-6">No signals yet</td></tr>`;
    return;
  }
  tbody.innerHTML = ss.map(s => `
    <tr>
      <td class="mute">${new Date(s.ts).toLocaleString()}</td>
      <td>${s.strategy}</td>
      <td class="font-semibold">${s.symbol}</td>
      <td>${s.side === "buy" || s.side === "sell" ? `<span class="tag ${s.side}">${s.side}</span>` : s.side}</td>
      <td>${fmtNum(s.qty, 4)}</td>
      <td class="mute" style="max-width:300px;white-space:normal">${escapeHTML(s.reason || "")}</td>
      <td><span class="tag ${s.status || ""}">${s.status || ""}</span></td>
    </tr>`).join("");
}

function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// ── Strategy form rendering ────────────────────────────────────────────────
function renderParamField(key, schema, value) {
  const val = (value !== null && value !== undefined) ? value : "";
  const hint = schema.hint
    ? `<div style="font-size:11px;color:#4a6080;margin-top:3px">${escapeHTML(schema.hint)}</div>` : "";

  if (schema.type === "bool") {
    const chk = (val === true || val === "true") ? "checked" : "";
    return `<label style="display:flex;align-items:flex-start;gap:8px;cursor:pointer;padding:4px 0">
      <input type="checkbox" data-key="${key}" ${chk} style="margin-top:2px;accent-color:#5b8def;flex-shrink:0" />
      <div><div style="font-size:12px;color:#c8d6e8">${escapeHTML(schema.label)}</div>${hint}</div>
    </label>`;
  }
  if (schema.type === "symbols") {
    const sv = Array.isArray(val) ? val.join(", ") : (val || "");
    return `<div style="margin-bottom:10px">
      <label style="font-size:11px;color:#8aa3c0;text-transform:uppercase;letter-spacing:.04em">${escapeHTML(schema.label)}</label>
      <input class="input" style="margin-top:4px" data-key="${key}" data-type="symbols" value="${escapeHTML(sv)}" placeholder="AAPL, MSFT, NVDA" />
      ${hint}
    </div>`;
  }
  const attrs = [
    `data-key="${key}" type="number" step="any"`,
    schema.min !== undefined ? `min="${schema.min}"` : "",
    schema.max !== undefined ? `max="${schema.max}"` : "",
    (val !== "" && val !== null) ? `value="${val}"` : `placeholder="—"`,
  ].join(" ");
  return `<div style="margin-bottom:10px">
    <label style="font-size:11px;color:#8aa3c0;text-transform:uppercase;letter-spacing:.04em">${escapeHTML(schema.label)}</label>
    <input class="input" style="margin-top:4px" ${attrs} />
    ${hint}
  </div>`;
}

async function refreshStrategies() {
  const list = await api("/api/strategies");
  const wrap = document.getElementById("strategies-list");
  wrap.innerHTML = list.map(s => {
    const schema = s.params_schema || [];
    const fields = schema.length
      ? schema.map(f => renderParamField(f.key, f, s.params[f.key])).join("")
      : `<textarea class="input" style="font-family:monospace;font-size:12px;margin-top:6px" rows="5" data-key="__json__">${escapeHTML(JSON.stringify(s.params, null, 2))}</textarea>`;

    return `
    <div style="border:1px solid #243049;border-radius:10px;padding:12px" data-strategy="${s.name}">
      <div style="display:flex;align-items:flex-start;gap:10px">
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;font-weight:600">${escapeHTML(s.label)}</div>
          <div style="font-size:12px;color:#7f8aa3;margin-top:3px;line-height:1.5">${escapeHTML(s.description)}</div>
        </div>
        ${s.auto_trade
          ? `<div class="switch ${s.enabled ? "on" : ""}" onclick="toggleStrategy('${s.name}',${!s.enabled})" style="margin-top:2px;flex-shrink:0"></div>`
          : `<span class="chip mute">manual</span>`}
      </div>
      ${s.auto_trade ? `
      <details style="margin-top:10px">
        <summary style="font-size:12px;color:#7f8aa3;cursor:pointer;user-select:none">⚙ Configure Parameters</summary>
        <div style="margin-top:12px;padding-top:12px;border-top:1px solid #1a2233" data-params-form="${s.name}">
          ${fields}
        </div>
        <button class="btn" style="width:100%;margin-top:8px;font-size:12px" onclick="saveParams('${s.name}')">💾 Save Changes</button>
      </details>` : ""}
    </div>`;
  }).join("");
}

async function refreshEngine() {
  const e = await api("/api/engine");
  const node = document.getElementById("engine-status");
  if (!e.ts) { node.textContent = "engine idle"; return; }
  const t = new Date(e.ts).toLocaleTimeString();
  if (e.error) { node.textContent = `${t} • ${e.error}`; return; }
  const sigs = (e.signals || []).length;
  const ran = (e.ran || []).length;
  node.textContent = `${t} • ran ${ran} strategies, ${sigs} signals`;
}

async function toggleStrategy(name, enabled) {
  await api(`/api/strategies/${name}`, { method: "PATCH", body: JSON.stringify({ enabled }) });
  await refreshStrategies();
}

async function saveParams(name) {
  const form = document.querySelector(`[data-params-form="${name}"]`);
  if (!form) return;
  const jsonTa = form.querySelector('[data-key="__json__"]');
  if (jsonTa) {
    let parsed;
    try { parsed = JSON.parse(jsonTa.value); }
    catch (e) { alert("Invalid JSON: " + e.message); return; }
    await api(`/api/strategies/${name}`, { method: "PATCH", body: JSON.stringify({ params: parsed }) });
    await refreshStrategies(); return;
  }
  const params = {};
  form.querySelectorAll("[data-key]").forEach(el => {
    const key = el.dataset.key;
    if (el.type === "checkbox") {
      params[key] = el.checked;
    } else if (el.dataset.type === "symbols") {
      params[key] = el.value.split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
    } else if (el.type === "number") {
      const v = el.value.trim();
      params[key] = (v === "" || v === "—") ? null : parseFloat(v);
    } else {
      params[key] = el.value;
    }
  });
  await api(`/api/strategies/${name}`, { method: "PATCH", body: JSON.stringify({ params }) });
  await refreshStrategies();
}

// ── Logout ─────────────────────────────────────────────────────────────────
async function doLogout() {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.href = "/login";
}

// ── Notification settings modal ────────────────────────────────────────────
let _notifSettings = {};

async function showNotificationSettings() {
  const s = await api("/api/notifications");
  _notifSettings = s;
  document.getElementById("sw-email").className    = "switch" + (s.email_enabled ? " on" : "");
  document.getElementById("sw-telegram").className = "switch" + (s.telegram_enabled ? " on" : "");
  document.getElementById("n-email-to").value  = s.email_to || "";
  document.getElementById("n-smtp").value      = s.email_smtp || "smtp.gmail.com";
  document.getElementById("n-port").value      = s.email_port || "587";
  document.getElementById("n-user").value      = s.email_user || "";
  document.getElementById("n-pass").value      = s.email_pass || "";
  document.getElementById("n-tg-token").value  = s.telegram_token || "";
  document.getElementById("n-tg-chat").value   = s.telegram_chat_id || "";
  document.getElementById("n-on-trade").checked = s.notify_on_trade;
  document.getElementById("n-on-block").checked = s.notify_on_block;
  document.getElementById("n-daily").checked    = s.notify_daily_summary;
  document.getElementById("notif-modal").style.display = "block";
}

function closeNotifModal() {
  document.getElementById("notif-modal").style.display = "none";
}

function toggleNotifSwitch(field, swId) {
  _notifSettings[field] = !_notifSettings[field];
  document.getElementById(swId).className = "switch" + (_notifSettings[field] ? " on" : "");
}

async function saveNotifSettings() {
  const body = {
    email_enabled:       _notifSettings.email_enabled    || false,
    telegram_enabled:    _notifSettings.telegram_enabled || false,
    email_to:            document.getElementById("n-email-to").value,
    email_smtp:          document.getElementById("n-smtp").value,
    email_port:          parseInt(document.getElementById("n-port").value) || 587,
    email_user:          document.getElementById("n-user").value,
    email_pass:          document.getElementById("n-pass").value,
    telegram_token:      document.getElementById("n-tg-token").value,
    telegram_chat_id:    document.getElementById("n-tg-chat").value,
    notify_on_trade:     document.getElementById("n-on-trade").checked,
    notify_on_block:     document.getElementById("n-on-block").checked,
    notify_daily_summary:document.getElementById("n-daily").checked,
  };
  await api("/api/notifications", { method: "POST", body: JSON.stringify(body) });
  document.getElementById("notif-status").textContent = "✓ Saved";
  setTimeout(() => document.getElementById("notif-status").textContent = "", 2000);
}

async function testNotif(channel) {
  const statusEl = document.getElementById("notif-status");
  statusEl.textContent = "Sending test...";
  statusEl.style.color = "#7f8aa3";
  try {
    const payload = { channel };
    if (channel === "email") {
      payload.email_to   = document.getElementById("n-email-to").value.trim();
      payload.email_smtp = document.getElementById("n-smtp").value.trim() || "smtp.gmail.com";
      payload.email_port = parseInt(document.getElementById("n-port").value) || 587;
      payload.email_user = document.getElementById("n-user").value.trim();
      payload.email_pass = document.getElementById("n-pass").value.trim();
      if (!payload.email_to || !payload.email_user || !payload.email_pass) {
        statusEl.textContent = "Fill in all email fields first.";
        statusEl.style.color = "#f0b90b";
        return;
      }
    } else {
      payload.telegram_token   = document.getElementById("n-tg-token").value.trim();
      payload.telegram_chat_id = document.getElementById("n-tg-chat").value.trim();
      if (!payload.telegram_token || !payload.telegram_chat_id) {
        statusEl.textContent = "Fill in Bot Token and Chat ID first.";
        statusEl.style.color = "#f0b90b";
        return;
      }
    }
    await api("/api/notifications/test", { method: "POST", body: JSON.stringify(payload) });
    statusEl.textContent = channel === "email"
      ? "✓ Email sent! Check your inbox (may take 30 seconds)."
      : "✓ Telegram message sent!";
    statusEl.style.color = "#16c784";
  } catch (e) {
    statusEl.textContent = "Error: " + e.message;
    statusEl.style.color = "#ea3943";
  }
}

// ── Order mode (shares vs USD) ─────────────────────────────────────────────
let _orderMode = "qty";
function setOrderMode(mode) {
  _orderMode = mode;
  document.getElementById("input-qty-wrap").classList.toggle("hidden", mode !== "qty");
  document.getElementById("input-usd-wrap").classList.toggle("hidden", mode !== "usd");
  document.getElementById("mode-qty").classList.toggle("active", mode === "qty");
  document.getElementById("mode-usd").classList.toggle("active", mode === "usd");
}

async function manualOrder(side) {
  const symbol = document.getElementById("m-symbol").value.trim().toUpperCase();
  if (!symbol) { alert("Symbol required"); return; }
  let body = { symbol, side };
  if (_orderMode === "usd") {
    const notional = parseFloat(document.getElementById("m-usd").value);
    if (!notional || notional <= 0) { alert("USD amount required"); return; }
    body.notional = notional;
    if (!confirm(`${side.toUpperCase()} $${notional.toFixed(2)} of ${symbol}?`)) return;
  } else {
    const qty = parseFloat(document.getElementById("m-qty").value);
    if (!qty || qty <= 0) { alert("Qty required"); return; }
    body.qty = qty;
    if (!confirm(`${side.toUpperCase()} ${qty} shares of ${symbol}?`)) return;
  }
  try {
    await api("/api/orders", { method: "POST", body: JSON.stringify(body) });
    await Promise.all([refreshAccount(), refreshOrders(), refreshPositions()]);
  } catch (e) { alert("Order failed: " + e.message); }
}

// ── Risk controls ──────────────────────────────────────────────────────────
let _killActive = false;

async function refreshRisk() {
  try {
    const r = await api("/api/risk");
    _killActive = r.kill_switch;

    // badge
    const badge = document.getElementById("risk-kill-badge");
    badge.innerHTML = r.kill_switch
      ? `<span class="tag error font-semibold">HALTED</span>`
      : `<span class="tag filled">active</span>`;

    // kill button label
    const killBtn = document.getElementById("kill-btn");
    if (killBtn) {
      killBtn.textContent = r.kill_switch ? "🟢 Resume Trading" : "🛑 Kill Switch";
      killBtn.className = r.kill_switch ? "btn success flex-1" : "btn danger flex-1";
    }

    // warnings
    const warnEl = document.getElementById("risk-warnings");
    if (r.warnings && r.warnings.length) {
      warnEl.innerHTML = r.warnings.map(w =>
        `<div class="flex items-center gap-2 p-2 rounded-lg" style="background:#2a1a1a;color:#f0b90b">⚠ ${escapeHTML(w)}</div>`
      ).join("");
    } else {
      warnEl.innerHTML = `<div class="text-xs" style="color:#16c784">✓ All risk checks passing</div>`;
    }

    // PDT status
    const pdtEl = document.getElementById("risk-pdt-status");
    if (pdtEl && r.pdt_applies) {
      pdtEl.textContent = `PDT: ${r.day_trade_count}/${r.max_day_trades} day trades`;
    } else if (pdtEl) {
      pdtEl.textContent = `PDT: exempt (equity ≥ $25k)`;
    }

    // populate inputs once
    if (!document.getElementById("r-max-loss")._loaded) {
      document.getElementById("r-max-loss").value  = r.settings.max_daily_loss_pct;
      document.getElementById("r-max-dt").value    = r.settings.max_day_trades;
      document.getElementById("r-size-mode").value = r.settings.position_size_mode;
      document.getElementById("r-size-pct").value  = r.settings.position_size_pct;
      document.getElementById("r-max-pos").value   = r.settings.max_position_pct;
      document.getElementById("r-max-loss")._loaded = true;
    }
  } catch (e) { console.error("risk:", e); }
}

async function toggleKillSwitch() {
  const on = !_killActive;
  if (on && !confirm("Activate kill switch? This will halt all automated trading immediately.")) return;
  await api("/api/risk/kill_switch", { method: "POST", body: JSON.stringify({ on }) });
  await refreshRisk();
}

async function saveRiskSettings() {
  const fields = {
    max_daily_loss_pct: document.getElementById("r-max-loss").value,
    max_day_trades:     document.getElementById("r-max-dt").value,
    position_size_mode: document.getElementById("r-size-mode").value,
    position_size_pct:  document.getElementById("r-size-pct").value,
    max_position_pct:   document.getElementById("r-max-pos").value,
  };
  try {
    for (const [key, value] of Object.entries(fields)) {
      await api(`/api/risk/${key}`, { method: "PATCH", body: JSON.stringify({ value: String(value) }) });
    }
    await refreshRisk();
  } catch (e) { alert("Save failed: " + e.message); }
}

async function lookupQuote() {
  const symbol = document.getElementById("m-symbol").value.trim().toUpperCase();
  if (!symbol) return;
  try {
    const q = await api(`/api/quote/${symbol}`);
    document.getElementById("m-quote").textContent =
      `${symbol} bid ${fmtUSD(q.bid)} • ask ${fmtUSD(q.ask)}`;
  } catch (e) { document.getElementById("m-quote").textContent = "quote error: " + e.message; }
}

async function cancelOrder(id) {
  if (!confirm("Cancel order?")) return;
  await api(`/api/orders/${id}`, { method: "DELETE" });
  await refreshOrders();
}

async function cancelAllOrders() {
  if (!confirm("Cancel all open orders?")) return;
  await api(`/api/orders`, { method: "DELETE" });
  await refreshOrders();
}

async function closePosition(symbol) {
  if (!confirm(`Close position in ${symbol}?`)) return;
  await api(`/api/positions/${symbol}`, { method: "DELETE" });
  await Promise.all([refreshPositions(), refreshOrders(), refreshAccount()]);
}

async function closeAllPositions() {
  if (!confirm("Close ALL positions?")) return;
  await api(`/api/positions`, { method: "DELETE" });
  await Promise.all([refreshPositions(), refreshOrders(), refreshAccount()]);
}

async function runEngineNow() {
  await api("/api/engine/run_now", { method: "POST" });
  await Promise.all([refreshSignals(), refreshOrders(), refreshPositions(), refreshEngine(), refreshAccount()]);
}

async function refreshChart() {
  try {
    const tf = chartPeriod === "1D" ? "5Min" : "1D";
    const h = await api(`/api/portfolio_history?period=${chartPeriod}&timeframe=${tf}`);
    drawChart(h);
  } catch (e) {
    document.getElementById("equity-chart").innerHTML =
      `<text x="400" y="90" text-anchor="middle" fill="#7f8aa3" font-size="12">chart unavailable</text>`;
  }
}

function drawChart(h) {
  const svg = document.getElementById("equity-chart");
  const eq = (h.equity || []).filter(v => v != null);
  if (eq.length < 2) { svg.innerHTML = ""; return; }
  const W = 800, H = 180, PAD = 6;
  const min = Math.min(...eq), max = Math.max(...eq);
  const span = max - min || 1;
  const stepX = (W - 2 * PAD) / (eq.length - 1);
  const xy = eq.map((v, i) => [PAD + i * stepX, PAD + (H - 2 * PAD) * (1 - (v - min) / span)]);
  const path = "M" + xy.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" L");
  const area = path + ` L${xy[xy.length-1][0]},${H} L${xy[0][0]},${H} Z`;
  const last = eq[eq.length - 1], first = eq[0];
  const up = last >= first;
  const stroke = up ? "#16c784" : "#ea3943";
  const fill = up ? "rgba(22,199,132,0.15)" : "rgba(234,57,67,0.15)";
  svg.innerHTML = `
    <path d="${area}" fill="${fill}" stroke="none"/>
    <path d="${path}" fill="none" stroke="${stroke}" stroke-width="1.5"/>
  `;
}

document.addEventListener("click", (e) => {
  const tab = e.target.closest("[data-tab]");
  if (tab) {
    document.querySelectorAll("[data-tab]").forEach(t => t.classList.toggle("active", t === tab));
    const which = tab.dataset.tab;
    document.getElementById("tab-orders").classList.toggle("hidden", which !== "orders");
    document.getElementById("tab-signals").classList.toggle("hidden", which !== "signals");
    if (which === "signals") refreshSignals();
  }
  const period = e.target.closest("#period-tabs [data-p]");
  if (period) {
    chartPeriod = period.dataset.p;
    document.querySelectorAll("#period-tabs [data-p]").forEach(b => b.classList.toggle("active", b === period));
    refreshChart();
  }
});

// ── Performance analytics ──────────────────────────────────────────────────────

async function refreshPerformance() {
  try {
    const d = await api("/api/performance");

    // Quick-stat strip
    const totalSignals = d.strategy_stats.reduce((a, s) => a + (s.total || 0), 0);
    document.getElementById("pf-total").textContent  = totalSignals;
    document.getElementById("pf-strats").textContent = d.strategy_stats.length;
    document.getElementById("pf-syms").textContent   = d.unique_symbols;
    const uplEl = document.getElementById("pf-upl");
    uplEl.textContent  = fmtUSD(d.total_unrealized_pl);
    uplEl.className    = "text-xl font-semibold " + cls(d.total_unrealized_pl);

    // Per-strategy cards
    const cardsEl = document.getElementById("pf-strategy-cards");
    if (!d.strategy_stats.length) {
      cardsEl.innerHTML = `<div class="mute text-xs text-center py-4">No strategy signals yet — enable a strategy and wait for market hours.</div>`;
    } else {
      cardsEl.innerHTML = d.strategy_stats.map(s => {
        const executed   = Math.max(0, (s.total || 0) - (s.blocked || 0) - (s.errors || 0));
        const pct        = s.total > 0 ? Math.round((executed / s.total) * 100) : 0;
        const lastDate   = s.last_signal ? new Date(s.last_signal).toLocaleDateString() : "—";
        return `
        <div style="background:#1a2233;border-radius:8px;padding:10px">
          <div class="flex items-center justify-between mb-1">
            <span style="font-size:13px;font-weight:600">${escapeHTML(s.strategy)}</span>
            <span class="chip">${s.total} signals</span>
          </div>
          <div class="flex flex-wrap gap-3 text-xs" style="color:#7f8aa3">
            <span class="pos">▲ ${s.buys || 0} buy</span>
            <span class="neg">▼ ${s.sells || 0} sell</span>
            <span>${s.unique_symbols || 0} symbols</span>
            ${s.blocked > 0 ? `<span style="color:#f0b90b">⚠ ${s.blocked} blocked</span>` : ""}
          </div>
          <div style="display:flex;align-items:center;gap:8px;margin-top:8px">
            <div style="flex:1;height:4px;background:#243049;border-radius:2px">
              <div style="height:4px;background:#5b8def;border-radius:2px;width:${pct}%"></div>
            </div>
            <span style="font-size:11px;color:#7f8aa3">${pct}% executed</span>
          </div>
          <div style="font-size:11px;color:#4a6080;margin-top:4px">Last: ${lastDate}</div>
        </div>`;
      }).join("");
    }

    // Top symbols table
    const tbody = document.getElementById("pf-symbols-body");
    if (!d.top_symbols.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="mute text-center py-4">No trades yet</td></tr>`;
    } else {
      tbody.innerHTML = d.top_symbols.map(s => `
        <tr>
          <td class="font-semibold">${escapeHTML(s.symbol)}</td>
          <td>${s.total}</td>
          <td class="pos">${s.buys}</td>
          <td class="neg">${s.sells}</td>
          <td class="mute">${s.strategies}</td>
        </tr>`).join("");
    }

    // 30-day activity bar chart
    drawActivityChart(d.daily_counts);

  } catch (e) { console.error("performance:", e); }
}

function drawActivityChart(daily) {
  const svg = document.getElementById("pf-activity-chart");
  if (!daily || !daily.length) {
    svg.innerHTML = `<text x="200" y="42" text-anchor="middle" fill="#4a6080" font-size="11">No activity in the last 30 days</text>`;
    return;
  }
  const W = 400, H = 80, PADX = 4, PADY = 14;
  const maxVal = Math.max(...daily.map(d => d.total), 1);
  const n = daily.length;
  const barW = Math.max(2, Math.floor((W - PADX * 2) / n) - 1);
  const step  = (W - PADX * 2) / n;

  const bars = daily.map((d, i) => {
    const barH = ((d.total / maxVal) * (H - PADY - PADX));
    const x = PADX + i * step + (step - barW) / 2;
    const y = H - PADY - barH;
    const showLabel = n <= 15 || (i % Math.ceil(n / 7) === 0);
    const label = d.date ? d.date.slice(5) : "";
    return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW}" height="${Math.max(barH, 1).toFixed(1)}"
              fill="#5b8def" rx="2" opacity=".85"/>
            ${showLabel ? `<text x="${(x + barW / 2).toFixed(1)}" y="${H - 2}" text-anchor="middle"
              fill="#4a6080" font-size="8">${label}</text>` : ""}`;
  }).join("");

  svg.innerHTML = bars;
}

async function refreshScanner() {
  try {
    const d = await api("/api/scanner");
    const fmt = (arr, type) => arr.slice(0, 10).map(s => {
      const price = s.price != null ? fmtUSD(s.price) : "";
      const pct   = s.percent_change != null
        ? `<span class="${s.percent_change >= 0 ? 'pos' : 'neg'}">${s.percent_change >= 0 ? "+" : ""}${Number(s.percent_change).toFixed(1)}%</span>` : "";
      const vol   = s.volume != null
        ? `<span class="mute">${(s.volume / 1e6).toFixed(1)}M</span>` : "";
      return `<div class="flex items-center justify-between text-xs py-1 border-b border-line">
        <span class="font-semibold">${s.symbol}</span>
        <span class="flex gap-2 items-center">${price} ${pct} ${vol}</span>
      </div>`;
    }).join("") || `<div class="mute text-xs">—</div>`;

    document.getElementById("scanner-actives").innerHTML = fmt(d.actives, "actives");
    document.getElementById("scanner-gainers").innerHTML = fmt(d.gainers, "gainers");
    document.getElementById("scanner-losers").innerHTML  = fmt(d.losers,  "losers");
    if (d.cached_at) {
      document.getElementById("scanner-updated").textContent =
        "updated " + new Date(d.cached_at * 1000).toLocaleTimeString();
    }
  } catch (e) { console.error("scanner:", e); }
}

async function refreshAll() {
  try {
    await Promise.all([
      refreshAccount(),
      refreshPositions(),
      refreshOrders(),
      refreshStrategies(),
      refreshSignals(),
      refreshEngine(),
      refreshRisk(),
    ]);
  } catch (e) { console.error(e); }
}

refreshAll();
refreshChart();
refreshScanner();
refreshRisk();
refreshPerformance();
setInterval(refreshAll, 5000);
setInterval(refreshRisk, 10000);
setInterval(refreshChart, 60000);
setInterval(refreshScanner, 60000);
setInterval(refreshPerformance, 30000);
