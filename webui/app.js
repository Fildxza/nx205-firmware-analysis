/* FILDZA · NX205 Connectivity & Firmware Studio
   Vanilla-JS client. All values come from the local Python API (/api/*);
   nothing is fabricated in the browser. Where the backend reports nothing, an
   explicit empty / unavailable / pending state is shown. Status vocabulary:
   REAL · UNAVAILABLE · ERROR · PLACEHOLDER. */

"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts) {
  const res = await fetch(path, opts);
  const ct = res.headers.get("content-type") || "";
  return { ok: res.ok, status: res.status,
           data: ct.includes("json") ? await res.json() : await res.text() };
}

const STATUS_WORD = { ok: "REAL", unreachable: "UNAVAILABLE", error: "ERROR" };
function pill(word) {
  const w = String(word || "PENDING").toUpperCase();
  const cls = { REAL: "pill-real", UNAVAILABLE: "pill-unavailable",
    ERROR: "pill-error", PLACEHOLDER: "pill-placeholder" }[w] || "pill-pending";
  return `<span class="pill ${cls}"><span class="d"></span>${esc(w)}</span>`;
}
const engWord = (s) => STATUS_WORD[s] || "ERROR";
const dotCls = (w) => ({ REAL: "dot-real", UNAVAILABLE: "dot-unavailable",
  ERROR: "dot-error" }[w] || "dot-pending");

/* icons */
const ICON = {
  pc: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M8 20h8M12 16v4"/></svg>',
  router: '<svg viewBox="0 0 24 24"><rect x="3" y="12" width="18" height="7" rx="1.5"/><path d="M7 16h.01M11 16h2M12 12V7M12 7l-3-3M12 7l3-3"/></svg>',
  globe: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M6 4l14 8-14 8z"/></svg>',
  target: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/></svg>',
  shield: '<svg viewBox="0 0 24 24"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5L16 9.5"/></svg>',
  clip: '<svg viewBox="0 0 24 24"><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4h6v3H9zM8 11h8M8 15h5"/></svg>',
};

const VIEWS = {
  overview:    ["Studio", "Overview", "A live summary of this diagnostic session, built only from measured data."],
  diagnostics: ["Network", "Network Experience", "Read-only reachability from this PC. Each check is independent."],
  firmware:    ["Firmware", "Firmware Studio", "Offline analysis of the local firmware package. Not a live router operation."],
  evidence:    ["History", "Evidence & History", "A timestamped record of real diagnostic events and manual observations."],
  settings:    ["Configuration", "Settings", "Diagnostic target and preferences for this PC."],
};

const state = { session: null, firmwarePoll: null };

/* ---------- shell ---------- */
function showView(name, { updateHash = true } = {}) {
  if (!VIEWS[name]) name = "overview";
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.add("is-hidden"));
  $(`#view-${name}`).classList.remove("is-hidden");
  $("#viewEyebrow").textContent = VIEWS[name][0];
  $("#viewTitle").textContent = VIEWS[name][1];
  $("#viewSub").textContent = VIEWS[name][2];
  // Deep-link: reflect the open tab in the URL hash (e.g. #firmware) so a
  // bookmark, refresh, or shared link reopens the same view. No server
  // round-trip involved — purely a client-side convenience.
  if (updateHash) {
    history.replaceState(null, "", `#${name}`);
  }
  render(name);
}

function viewFromHash() {
  return (location.hash || "").replace(/^#/, "");
}

async function loadSession() {
  const { data } = await api("/api/session");
  state.session = data;
  $("#deviceName").textContent = data.device || "—";
  $("#deviceHw").textContent = data.hw || "—";
  $("#footVersion").textContent = "v" + (data.version || "—");
  $("#safetyLine").textContent = data.safety || "";
  updateGatewayChip();
}
function updateGatewayChip() {
  const s = state.session || {};
  $("#deviceGw").textContent = (s.settings && s.settings.router) || "not set";
}

function render(name) {
  ({ overview: renderOverview, diagnostics: renderDiagnostics,
     firmware: renderFirmware, evidence: renderEvidence,
     settings: renderSettings }[name])();
}

/* ---------- OVERVIEW ---------- */
async function renderOverview() {
  await loadSession();
  const s = state.session;
  const last = s.last_diagnostics;
  const c = last && last.checks;

  const gwWord = c ? engWord(c.router_icmp.status) : "PENDING";
  const netWord = c ? engWord(c.internet_icmp.status) : "PENDING";
  const gwMeta = c && c.router_icmp.status === "ok"
    ? `<span class="mono">${esc(c.router_icmp.rtt_avg_ms)} ms · ${esc(c.router_icmp.loss_percent)}% loss</span>`
    : (c ? "no reply" : "not measured");
  const netMeta = c && c.internet_icmp.status === "ok"
    ? `<span class="mono">${esc(c.internet_icmp.rtt_avg_ms)} ms · ${esc(c.internet_icmp.loss_percent)}% loss</span>`
    : (c ? "no reply" : "not measured");
  const gw = (s.settings && s.settings.router) || "not set";

  const conn = `
    <div class="conn">
      <div class="node">
        <div class="node-badge">${ICON.pc}</div>
        <div class="node-label">This PC</div>
        <div class="node-meta">diagnostic host</div>
      </div>
      <div class="link ${gwWord === "REAL" ? "ok" : "down"}"><span class="node-dot ${dotCls(gwWord)}"></span></div>
      <div class="node">
        <div class="node-badge">${ICON.router}</div>
        <div class="node-label">Gateway</div>
        <div class="node-meta"><span class="mono">${esc(gw)}</span><br>${gwMeta}</div>
      </div>
      <div class="link ${netWord === "REAL" ? "ok" : "down"}"><span class="node-dot ${dotCls(netWord)}"></span></div>
      <div class="node">
        <div class="node-badge">${ICON.globe}</div>
        <div class="node-label">Internet</div>
        <div class="node-meta">${netMeta}</div>
      </div>
    </div>`;

  // Figures (only real numbers; otherwise an em dash)
  const fig = (val, unit, label) => `<div class="fig">
      <div class="fig-val">${val}${unit ? `<span class="unit">${unit}</span>` : ""}</div>
      <div class="fig-label">${label}</div></div>`;
  const netOk = c && c.internet_icmp.status === "ok";
  const figures = `<div class="figrow">
      ${fig(netOk ? esc(c.internet_icmp.rtt_avg_ms) : "—", netOk ? "ms" : "", "Internet latency")}
      ${fig(netOk ? esc(c.internet_icmp.loss_percent) : "—", netOk ? "%" : "", "Packet loss")}
      ${fig(last ? Object.keys(last.checks).length : 0, "", "Checks completed")}
      ${fig(s.evidence_count || 0, "", "Evidence records")}
    </div>`;

  const sessionKv = `<div class="kvlist">
      <div class="kvrow"><span class="k">Session state</span><span class="v">${pill("REAL")} active</span></div>
      <div class="kvrow"><span class="k">Selected gateway</span><span class="v mono">${esc(gw)}</span></div>
      <div class="kvrow"><span class="k">Internet reachability</span><span class="v">${pill(netWord)}</span></div>
      <div class="kvrow"><span class="k">Last diagnostic run</span><span class="v mono">${esc(last ? last.timestamp : "— not run yet")}</span></div>
      <div class="kvrow"><span class="k">Firmware analysis</span><span class="v">${esc(s.firmware_status)}</span></div>
    </div>`;

  const ev = await api("/api/evidence");
  const recent = (ev.data.rows || []).filter(r => r.event_type === "diagnostics").slice(0, 5);
  const recentHtml = recent.length ? `<div class="timeline">${recent.map(tlItem).join("")}</div>`
    : emptyState(ICON.clip, "No diagnostic events yet",
        "Run the checks in the Network tab to populate this session's history.");

  $("#view-overview").innerHTML = `
    <div class="split">
      <div class="card">
        <div class="card-head"><h2 class="card-title">Connection path</h2>
          <span class="overline">live summary</span></div>
        ${conn}
        <div class="card-pad" style="border-top:1px solid var(--hair)">${figures}</div>
      </div>
      <div class="card card-pad">
        <h2 class="card-title" style="margin-bottom:6px">Session</h2>
        ${sessionKv}
      </div>
    </div>
    <div class="card" style="margin-top:18px">
      <div class="card-head"><h2 class="card-title">Recent real events</h2>
        <span class="overline">diagnostics</span></div>
      <div class="card-pad">${recentHtml}</div>
    </div>`;
}

/* ---------- NETWORK ---------- */
function renderDiagnostics() {
  const s = state.session || {};
  const set = s.settings || {};
  const target = `${set.scheme || "http"}://${set.router || "— set a gateway —"}:${set.port || 80}`;
  $("#view-diagnostics").innerHTML = `
    <div class="card card-pad">
      <div class="btn-row" style="justify-content:space-between">
        <div><span class="overline">target</span>
          <div class="mono" style="margin-top:4px;color:var(--ink-2)">${esc(target)}</div></div>
        <div class="btn-row">
          <button class="btn" id="detectGw">${ICON.target} Detect gateway</button>
          <button class="btn btn-primary" id="runDiag">${ICON.play} Run diagnostics</button>
        </div>
      </div>
      <div id="diagMsg" style="margin-top:12px"></div>
    </div>
    <div id="diagResults" style="margin-top:18px">${diagResultsHTML(s.last_diagnostics)}</div>`;
  $("#runDiag").addEventListener("click", runDiagnostics);
  $("#detectGw").addEventListener("click", detectGateway);
}

function diagResultsHTML(snap) {
  if (!snap) {
    return `<div class="card">${emptyState(ICON.globe, "No diagnostics run yet",
      "Click “Run diagnostics” to probe the current target. Results appear here with full detail.")}</div>`;
  }
  const c = snap.checks, n = (v, u = "") => (v || v === 0) ? `${v}${u}` : "—";
  const rp = c.router_icmp, ip = c.internet_icmp, dns = c.dns,
    tcp = c.router_tcp, http = c.router_http;
  const row = (check, target, lat, loss, code, status, detail) => `<tr>
      <td>${esc(check)}</td><td class="mono">${esc(target)}</td>
      <td class="num">${esc(lat)}</td><td class="num">${esc(loss)}</td>
      <td class="num">${esc(code)}</td><td>${pill(engWord(status))}</td>
      <td class="muted">${esc(detail)}</td></tr>`;
  const rows = [
    row("Router ICMP", rp.host, n(rp.rtt_avg_ms, " ms"), n(rp.loss_percent, "%"), "—",
      rp.status, rp.status === "ok" ? `${rp.received}/${rp.sent} replies` : (rp.detail || "")),
    row("Internet ICMP", ip.host, n(ip.rtt_avg_ms, " ms"), n(ip.loss_percent, "%"), "—",
      ip.status, ip.status === "ok" ? `${ip.received}/${ip.sent} replies` : (ip.detail || "")),
    row("DNS resolution", dns.hostname, "—", "—", "—", dns.status,
      dns.addresses && dns.addresses.length ? dns.addresses.join(", ") : (dns.detail || "no answer")),
    row("Router TCP port", `${tcp.host}:${tcp.port}`, n(tcp.connect_ms, " ms"), "—", "—",
      tcp.status, tcp.status === "ok" ? "port open" : (tcp.detail || "")),
    row("Router HTTP", http.url, n(http.latency_ms, " ms"), "—", n(http.http_code),
      http.status, http.auth_required ? "admin page present, auth required" : (http.detail || "")),
  ].join("");
  return `<div class="card">
      <div class="card-head"><h2 class="card-title">Detailed results</h2>
        <span class="chip mono">snapshot ${esc(snap.timestamp)}</span></div>
      <table class="table"><thead><tr>
        <th>Check</th><th>Target</th><th>Latency</th><th>Loss</th><th>HTTP</th>
        <th>Status</th><th>Detail</th></tr></thead><tbody>${rows}</tbody></table>
      <div class="card-pad" style="border-top:1px solid var(--hair)">
        <div class="note">Each check is independent. A failed ICMP ping does not by
        itself mean the router is offline — a device may block ping yet still serve
        its admin page. An HTTP response confirms only that a web server answered; it
        does not read firmware, SIM, or administrative data from the router.</div>
      </div></div>`;
}

async function runDiagnostics() {
  const btn = $("#runDiag"), msg = $("#diagMsg");
  btn.disabled = true;
  msg.innerHTML = `<span class="loading"><span class="spinner"></span>Running checks…</span>`;
  const set = (state.session && state.session.settings) || {};
  try {
    const { data } = await api("/api/diagnostics", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ router: set.router, port: set.port, scheme: set.scheme }) });
    if (!data.ok) {
      msg.innerHTML = `<span class="msg msg-err">${esc((data.errors || ["failed"]).join("; "))}</span>`;
    } else {
      state.session.last_diagnostics = data.snapshot;
      $("#diagResults").innerHTML = diagResultsHTML(data.snapshot);
      msg.innerHTML = `<span class="msg msg-ok">Completed ${esc(data.snapshot.timestamp)}</span>`;
    }
  } catch (e) {
    msg.innerHTML = `<span class="msg msg-err">Request failed: ${esc(e.message)}</span>`;
  } finally { btn.disabled = false; }
}

async function detectGateway() {
  const msg = $("#diagMsg");
  msg.innerHTML = `<span class="loading"><span class="spinner"></span>Detecting gateway…</span>`;
  const { data } = await api("/api/gateway");
  if (data.status === "ok") {
    await loadSession(); renderDiagnostics();
    $("#diagMsg").innerHTML = `<span class="msg msg-ok">Gateway ${esc(data.gateway)} (via ${esc(data.source)})</span>`;
  } else {
    msg.innerHTML = `<span class="msg msg-err">${esc(data.detail || "detection failed")}. Set it manually in Settings.</span>`;
  }
}

/* ---------- FIRMWARE STUDIO ---------- */
function renderFirmware() {
  $("#view-firmware").innerHTML =
    `<div class="card card-pad" id="fwBody"><div class="loading">
       <span class="spinner"></span>Requesting analysis…</div></div>`;
  pollFirmware();
}

async function pollFirmware() {
  const body = $("#fwBody");
  if (!body) return;
  const { data } = await api("/api/firmware");
  if (state.session) state.session.firmware_status = data.status;

  if (data.status === "computing" || data.status === "idle") {
    body.innerHTML = `<div class="loading"><span class="spinner"></span>
      Analysing firmware image — hashing ~141 MB (runs once per session)…</div>`;
    clearTimeout(state.firmwarePoll);
    state.firmwarePoll = setTimeout(pollFirmware, 1200);
    return;
  }
  const host = $("#view-firmware");
  if (data.status === "absent") {
    host.innerHTML = `<div class="card">${emptyState(ICON.clip,
      "Firmware package not found",
      "Place the extracted TP-Link package folder in the project directory, then reopen this tab.")}</div>`;
    return;
  }
  if (data.status === "error") {
    host.innerHTML = `<div class="card card-pad"><span class="msg msg-err">Analysis error: ${esc(data.error || "unknown")}</span></div>`;
    return;
  }
  host.innerHTML = (data.reports || []).map(firmwareCard).join("")
    || `<div class="card">${emptyState(ICON.clip, "No firmware files detected", "")}</div>`;
}

function firmwareCard(r) {
  if (r.error) {
    return `<div class="card card-pad"><div class="fw-name">${esc(r.filename)}</div>
      <span class="msg msg-err" style="margin-top:8px;display:inline-block">${esc(r.error)}</span></div>`;
  }
  const meta = `<div class="kvlist" style="margin-top:14px">
      <div class="kvrow"><span class="k">File size</span><span class="v">${esc(r.size_human)} <span class="mono muted">(${esc(r.size_bytes)} bytes)</span></span></div>
      <div class="kvrow"><span class="k">Detected format (by signature)</span><span class="v">${esc(r.format)}</span></div>
      <div class="kvrow"><span class="k">Header bytes</span><span class="v mono">${esc(r.header_hex)}</span></div>
      <div class="kvrow"><span class="k">Parsed build / versions</span><span class="v mono">${esc(r.build || "—")} / ${esc(r.versions || "—")}</span></div>
    </div>`;

  const integrity = `<div class="integrity" style="margin-top:14px">
      <div class="seal">${ICON.shield}<span>SHA-256</span></div>
      <div class="hashbox">
        <div class="hash-k">Integrity digest · computed from the local file</div>
        <div class="hash-v">${esc(r.sha256)}</div>
        <div class="hash-sub">MD5 <span class="mono">${esc(r.md5)}</span> &nbsp;·&nbsp; reference check: ${esc((r.integrity_status || "").toUpperCase())}</div>
      </div></div>`;

  let structure = `<p class="muted" style="font-size:12.5px">No embedded structures parsed.</p>`;
  if (r.embedded && r.embedded.length) {
    structure = `<table class="table" style="margin:0 -24px;width:calc(100% + 48px)">
      <thead><tr><th>Embedded structure</th><th>Occurrences</th><th>First offset</th></tr></thead>
      <tbody>${r.embedded.map(h => `<tr><td>${esc(h.name)}</td>
        <td class="num">${esc(h.count)}</td><td class="num">${esc(h.first_offset)}</td></tr>`).join("")}
      </tbody></table>`;
  }
  const findings = `<div class="kvlist">
      <div class="kvrow"><span class="k">Kernel string (heuristic)</span><span class="v mono">${esc(r.kernel_version || "not found")}</span></div>
      <div class="kvrow"><span class="k">Entropy (sampled)</span><span class="v">${esc(r.entropy_bits || "—")} — ${esc(r.entropy_label || "")}</span></div>
      <div class="kvrow"><span class="k">Detection confidence</span><span class="v">${esc(r.confidence)}</span></div>
    </div>`;
  const warns = (r.warnings || []).map(w => `<div class="note" style="margin-top:10px">${esc(w)}</div>`).join("");

  return `<div class="card">
      <div class="card-pad">
        <div class="fw-identity">
          <div><span class="overline">firmware file · offline analysis</span>
            <div class="fw-name" style="margin-top:5px">${esc(r.filename)}</div></div>
          ${pill(r.supported ? "REAL" : "UNAVAILABLE")}
        </div>
        <div class="section-rule">Verified metadata</div>
        ${meta}
        ${integrity}
        <div class="section-rule">Structure findings · heuristic</div>
        ${structure}
        <div style="margin-top:14px">${findings}</div>
        ${warns}
        <div class="note" style="margin-top:14px">This is analysis of a local firmware
          <em>file</em>. It is not a live router firmware feature and performs no
          modification, signing, or flashing. Heuristic findings are indicative, not
          authoritative.</div>
      </div></div>`;
}

/* ---------- EVIDENCE ---------- */
async function renderEvidence() {
  const { data } = await api("/api/evidence");
  const rows = data.rows || [];
  const body = rows.length
    ? `<div class="timeline">${rows.map(tlItem).join("")}</div>`
    : emptyState(ICON.clip, "No evidence recorded yet",
        "Diagnostic runs and manual observations will be recorded here with real timestamps and source attribution.");

  $("#view-evidence").innerHTML = `
    <div class="card">
      <div class="card-head"><h2 class="card-title">Recorded evidence</h2>
        <div class="btn-row">
          <a class="btn" href="/api/export?format=csv">Export CSV</a>
          <a class="btn" href="/api/export?format=json">Export JSON</a>
        </div></div>
      <div class="card-pad">${body}</div>
      <div class="legend">
        ${pill("REAL")} measured now &nbsp; ${pill("UNAVAILABLE")} no response
        &nbsp; ${pill("ERROR")} could not run &nbsp; ${pill("PLACEHOLDER")} sample, unverified
      </div>
    </div>
    <div class="card card-pad" style="margin-top:18px">
      <h2 class="card-title" style="margin-bottom:14px">Record a manual observation</h2>
      <form id="obsForm">
        <div class="field"><label>Test name</label>
          <input name="test_name" placeholder="e.g. LAN admin page loaded" required></div>
        <div class="field"><label>Result</label>
          <select name="result"><option>pass</option><option>fail</option>
            <option>partial</option><option value="not-tested">not-tested</option></select></div>
        <div class="field"><label>Interface</label>
          <input name="interface" placeholder="e.g. LAN, 2.4GHz Wi-Fi, WAN/5G"></div>
        <div class="field"><label>Detail</label>
          <input name="detail" placeholder="what you observed"></div>
        <div class="btn-row"><button class="btn btn-primary" type="submit">Record observation</button>
          <span id="obsMsg"></span></div>
      </form>
    </div>`;
  $("#obsForm").addEventListener("submit", submitObservation);
}

function tlItem(r) {
  return `<div class="tl-item">
      <div class="tl-when">${esc(r.timestamp)}</div>
      <div class="tl-body">
        <div class="tl-head"><span class="tl-test">${esc(r.test_name)}</span>${pill(r.status)}</div>
        <div class="tl-target">${esc(r.event_type)} · ${esc(r.target)}</div>
        ${r.result ? `<div class="tl-detail">${esc(r.result)}</div>` : ""}
        ${r.detail ? `<div class="tl-detail muted">${esc(r.detail)}</div>` : ""}
        <div class="tl-src">source: ${esc(r.source || "—")}</div>
      </div></div>`;
}

async function submitObservation(e) {
  e.preventDefault();
  const f = e.target, msg = $("#obsMsg");
  const { data } = await api("/api/observation", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ test_name: f.test_name.value, result: f.result.value,
      interface: f.interface.value || "unspecified", detail: f.detail.value }) });
  if (data.ok) renderEvidence();
  else msg.innerHTML = `<span class="msg msg-err">${esc(data.message)}</span>`;
}

/* ---------- SETTINGS ---------- */
function renderSettings() {
  const set = (state.session && state.session.settings) || {};
  $("#view-settings").innerHTML = `
    <div class="card card-pad">
      <h2 class="card-title" style="margin-bottom:16px">Diagnostic target</h2>
      <form id="setForm">
        <div class="field"><label>Router gateway / target IP or host</label>
          <input name="router" value="${esc(set.router || "")}" placeholder="auto-detect or e.g. 192.168.1.1">
          <div class="hint">Not assumed to be 192.168.1.1 — use Detect or type the real gateway.</div></div>
        <div class="field"><label>TCP / HTTP port</label>
          <input name="port" type="number" min="1" max="65535" value="${esc(set.port || 80)}"></div>
        <div class="field"><label>Scheme</label>
          <select name="scheme"><option value="http"${set.scheme !== "https" ? " selected" : ""}>http</option>
            <option value="https"${set.scheme === "https" ? " selected" : ""}>https</option></select></div>
        <div class="btn-row"><button class="btn btn-primary" type="submit">Save settings</button>
          <button class="btn" type="button" id="setDetect">${ICON.target} Detect gateway</button>
          <span id="setMsg"></span></div>
      </form>
      <div class="note" style="margin-top:18px">Diagnostic preferences for this PC only.
        The app never stores router passwords, cookies, SIM credentials, or other secrets,
        and never changes any setting on the physical router.</div>
    </div>`;
  $("#setForm").addEventListener("submit", saveSettings);
  $("#setDetect").addEventListener("click", async () => {
    const { data } = await api("/api/gateway");
    if (data.status === "ok") { $("#setForm").router.value = data.gateway;
      $("#setMsg").innerHTML = `<span class="msg msg-ok">Detected ${esc(data.gateway)}</span>`; }
    else $("#setMsg").innerHTML = `<span class="msg msg-err">${esc(data.detail || "detection failed")}</span>`;
  });
}

async function saveSettings(e) {
  e.preventDefault();
  const f = e.target, msg = $("#setMsg");
  const { data } = await api("/api/settings", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ router: f.router.value, port: Number(f.port.value),
      scheme: f.scheme.value }) });
  if (data.ok) { state.session.settings = data.settings; updateGatewayChip();
    msg.innerHTML = `<span class="msg msg-ok">Saved.</span>`; }
  else msg.innerHTML = `<span class="msg msg-err">${esc((data.errors || []).join("; "))}</span>`;
}

/* ---------- helpers ---------- */
function emptyState(icon, title, sub) {
  return `<div class="empty"><div class="em-mark">${icon}</div>
      <div class="em-title">${esc(title)}</div>
      ${sub ? `<div class="em-sub">${esc(sub)}</div>` : ""}</div>`;
}

/* ---------- init ---------- */
$("#nav").addEventListener("click", (e) => {
  const t = e.target.closest(".tab");
  if (t) showView(t.dataset.view);
});
window.addEventListener("hashchange", () => showView(viewFromHash(), { updateHash: false }));
(async function init() {
  await loadSession();
  api("/api/firmware").catch(() => {});   // kick off one-time firmware hash
  showView(viewFromHash() || "overview");
})();
