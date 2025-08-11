/* eslint-disable */
const $ = (q, root = document) => root.querySelector(q);
const $$ = (q, root = document) => Array.from(root.querySelectorAll(q));

function ensureToast() {
  let t = $("#toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "toast";
    t.className = "toast";
    document.body.appendChild(t);
  }
  return t;
}
function toast(msg, cls = "") {
  const t = ensureToast();
  t.textContent = msg;
  t.className = `toast show ${cls || ""}`;
  setTimeout(() => t.classList.remove("show"), 2500);
}

function buildUrl(path) {
  if (/^https?:\/\//i.test(path)) return path;
  return new URL(path.replace(/^\//, ""), window.location.href).toString();
}

async function api(path, method = "GET", body = null) {
  const url = buildUrl(path);
  try {
    const res = await fetch(url, {
      method,
      mode: "cors",
      credentials: "omit",
      headers: body ? { "Content-Type": "application/json", "Accept":"application/json" } : { "Accept":"application/json" },
      body: body ? JSON.stringify(body) : null,
      cache: "no-store",
    });
    let data = null, txt = "";
    try { data = await res.clone().json(); } catch { try { txt = await res.text(); } catch {} }
    if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText} :: ${(txt||"").slice(0,160)}`);
    if (data == null) {
      if (txt && txt.trim().startsWith("{")) { try { data = JSON.parse(txt); } catch {} }
      if (data == null) data = {};
    }
    return data;
  } catch (err) {
    console.error("FETCH ERROR:", err);
    toast(`Fetch failed: ${err.message}`, "err");
    throw err;
  }
}

function val(id, def = "") {
  const el = document.getElementById(id);
  if (!el) return def;
  if ("checked" in el) return el.checked;
  return (el.value ?? def);
}
function setVal(id, v) {
  const el = document.getElementById(id);
  if (!el) return;
  if ("checked" in el) el.checked = !!v;
  else el.value = v ?? "";
}
function setText(id, v) {
  const el = document.getElementById(id);
  if (el) el.textContent = v;
}

function bindTabs() {
  $$(".tab-link").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      $$(".tab-link").forEach((x) => x.classList.remove("active"));
      a.classList.add("active");
      const tab = a.dataset.tab;
      if (!tab) return;
      $$(".tab").forEach((s) => s.classList.remove("active"));
      const target = document.getElementById(tab);
      if (target) target.classList.add("active");
    }, { passive: false });
  });
}

let OPTIONS = { servers: [], cache_builder_list: [] };
let pollTimer = null;

async function loadOptions() {
  const js = await api("u/options");
  OPTIONS = js.options || OPTIONS;
  setVal("opt-gotify-url", OPTIONS.gotify_url || "");
  setVal("opt-gotify-token", OPTIONS.gotify_token || "");
  setVal("opt-cache-global", (OPTIONS.cache_builder_list || []).join("\n"));
  renderConfigured();
}

function renderConfigured() {
  const table = document.getElementById("tbl-configured");
  if (!table) return;
  const tb = $("tbody", table);
  if (!tb) return;
  tb.innerHTML = "";
  (OPTIONS.servers || []).forEach((s, idx) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${s.name || ""}</td>
      <td>${s.type || ""}</td>
      <td>${s.base_url || ""}</td>
      <td>${s.primary ? "Yes" : "No"}</td>
      <td class="actions">
        <button type="button" class="btn btn-xs" data-action="edit" data-idx="${idx}">Edit</button>
        <button type="button" class="btn btn-xs btn-danger" data-action="del" data-idx="${idx}">Delete</button>
      </td>`;
    tb.appendChild(tr);
  });
}

async function saveOptionsPatch(patch) {
  const js = await api("u/options", "POST", patch);
  if (js && js.options) OPTIONS = js.options;
}

function readServerForm() {
  const s = (x) => (String(val(x) ?? "")).trim();
  const n = (x, d = 53) => {
    const v = parseInt(val(x, d), 10);
    return Number.isFinite(v) ? v : d;
  };
  return {
    name: s("srv-name"),
    type: s("srv-type") || "technitium",
    base_url: s("srv-base"),
    dns_host: s("srv-dnshost"),
    dns_port: n("srv-dnsport", 53),
    dns_protocol: s("srv-dnsproto") || "udp",
    username: s("srv-user"),
    password: s("srv-pass"),
    token: s("srv-token"),
    verify_tls: !!val("srv-verify", true),
    primary: !!val("srv-primary", false),
    cache_builder_override: false,
    cache_builder_list: [],
  };
}
function clearServerForm() {
  setVal("srv-name", "");
  setVal("srv-type", "technitium");
  setVal("srv-base", "");
  setVal("srv-dnshost", "");
  setVal("srv-dnsport", 53);
  setVal("srv-dnsproto", "udp");
  setVal("srv-user", "");
  setVal("srv-pass", "");
  setVal("srv-token", "");
  setVal("srv-verify", true);
  setVal("srv-primary", false);
}

async function saveServer() {
  toast("Saving server…", "ok");
  const s = readServerForm();
  if (!s.name) { toast("Display Name is required", "err"); return; }
  if (!s.base_url) { toast("Base URL is required", "err"); return; }
  const list = (OPTIONS.servers || []).slice();
  const ix = list.findIndex((x) => (x.name || "") === s.name);
  if (ix >= 0) list[ix] = s; else list.push(s);
  await saveOptionsPatch({ servers: list });
  toast("Server saved", "ok");
  await loadOptions();
}

async function saveNotify() {
  toast("Saving notify…", "ok");
  await saveOptionsPatch({
    gotify_url: (String(val("opt-gotify-url") ?? "")).trim(),
    gotify_token: (String(val("opt-gotify-token") ?? "")).trim(),
  });
  toast("Notify saved", "ok");
}

async function saveCacheGlobal() {
  toast("Saving cache list…", "ok");
  const lines = (String(val("opt-cache-global") ?? ""))
    .split("\n").map((x) => x.trim()).filter(Boolean);
  await saveOptionsPatch({ cache_builder_list: lines });
  toast("Cache list saved", "ok");
}

async function refreshStats() {
  const js = await api("u/stats");
  const u = js.unified || { total: 0, blocked: 0, allowed: 0, servers: [] };
  setText("kpi-total", String(u.total));
  setText("kpi-blocked", String(u.blocked));
  setText("kpi-allowed", String(u.allowed));
  setText("kpi-pct", ((js.pct_blocked || 0) + "%"));
  let busiest = "n/a", best = -1;
  (u.servers || []).forEach((s) => { if (s.ok && s.total > best) { best = s.total; busiest = s.name || s.type; } });
  setText("kpi-busiest", busiest);

  const table = document.getElementById("tbl-servers");
  if (table) {
    const tb = $("tbody", table);
    if (tb) {
      tb.innerHTML = "";
      (u.servers || []).forEach((s) => {
        const tr = document.createElement("tr");
        const status = s.ok ? "OK" : "ERR: " + (s.error || "");
        tr.innerHTML = `
          <td>${s.name || ""}</td>
          <td>${s.type || ""}</td>
          <td>${status}</td>
          <td>${s.ok ? s.total : "-"}</td>
          <td>${s.ok ? s.allowed : "-"}</td>
          <td>${s.ok ? s.blocked : "-"}</td>`;
        tb.appendChild(tr);
      });
    }
  }
}

function setAutoRefresh() {
  if (pollTimer) clearInterval(pollTimer);
  const sel = document.getElementById("refresh-every");
  if (!sel) return;
  const sec = parseInt(sel.value || "5", 10);
  pollTimer = setInterval(refreshStats, sec * 1000);
}

async function runSelfCheck() {
  const out = document.getElementById("selfcheck-output");
  if (out) out.textContent = "Running…";
  const js = await api("u/selfcheck");
  if (out) out.textContent = JSON.stringify(js, null, 2);
}

function bindEvents() {
  document.body.addEventListener("click", onAction, { passive: false });
  document.body.addEventListener("touchend", onAction, { passive: false });
  bindTabs();
  const sel = document.getElementById("refresh-every");
  if (sel) sel.addEventListener("change", () => setAutoRefresh(), { passive: true });
}

async function onAction(e) {
  const btn = e.target.closest("button");
  if (!btn) return;
  e.preventDefault();
  const id = btn.id;
  const act = btn.dataset.action;
  try {
    if (id === "btn-save-server") return await saveServer();
    if (id === "btn-clear-form") return void clearServerForm();
    if (id === "btn-save-notify") return await saveNotify();
    if (id === "btn-save-cache") return await saveCacheGlobal();
    if (id === "btn-update-now") return await refreshStats();
    if (id === "btn-selfcheck") return await runSelfCheck();
    if (act === "edit") {
      const i = parseInt(btn.dataset.idx, 10);
      const s = (OPTIONS.servers || [])[i] || {};
      setVal("srv-name", s.name || "");
      setVal("srv-type", s.type || "technitium");
      setVal("srv-base", s.base_url || "");
      setVal("srv-dnshost", s.dns_host || "");
      setVal("srv-dnsport", s.dns_port || 53);
      setVal("srv-dnsproto", s.dns_protocol || "udp");
      setVal("srv-user", s.username || "");
      setVal("srv-pass", s.password || "");
      setVal("srv-token", s.token || "");
      setVal("srv-verify", !!s.verify_tls);
      setVal("srv-primary", !!s.primary);
      toast("Loaded into form", "ok");
      return;
    }
    if (act === "del") {
      const i = parseInt(btn.dataset.idx, 10);
      const copy = (OPTIONS.servers || []).slice();
      copy.splice(i, 1);
      await saveOptionsPatch({ servers: copy });
      toast("Server removed", "ok");
      return await loadOptions();
    }
  } catch (err) {
    console.error("Action error:", err);
    toast(String(err), "err");
  }
}

function waitForElements(ids, timeoutMs = 2500) {
  const start = performance.now();
  return new Promise((resolve) => {
    function check() {
      const missing = ids.filter((id) => document.getElementById(id) == null);
      if (missing.length === 0) return resolve(true);
      if (performance.now() - start > timeoutMs) return resolve(false);
      requestAnimationFrame(check);
    }
    check();
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  try {
    ensureToast();
    bindEvents();
    await waitForElements([
      "srv-name","srv-type","srv-base","srv-dnsproto","srv-dnsport",
      "opt-cache-global","opt-gotify-url","opt-gotify-token"
    ]);
    await loadOptions();
    await refreshStats();
    setAutoRefresh();
  } catch (e) {
    console.error("Boot error:", e);
    toast("UI failed to start (see console)", "err");
  }
});