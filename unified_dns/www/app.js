/* eslint-disable */
const $ = (q, root = document) => root.querySelector(q);
const $$ = (q, root = document) => Array.from(root.querySelectorAll(q));

/* ---------- Utilities ---------- */
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
  if (/^https?:\/\//i.test(path)) return path;                    // absolute
  return new URL(path.replace(/^\//, ""), window.location.href).toString(); // relative to ingress page
}

async function api(path, method = "GET", body = null) {
  const url = buildUrl(path);
  try {
    const res = await fetch(url, {
      method,
      credentials: "same-origin",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : null,
      cache: "no-store",
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status} ${res.statusText} @ ${url} :: ${txt.slice(0,160)}`);
    }
    const ct = res.headers.get("content-type") || "";
    if (!ct.includes("application/json")) {
      const txt = await res.text();
      throw new Error(`Expected JSON, got ${ct} @ ${url}. First: ${txt.slice(0,160)}`);
    }
    return await res.json();
  } catch (err) {
    console.error("FETCH ERROR:", err);
    toast(`Fetch failed: ${err.message}`, "err");
    throw err;
  }
}

/* ---------- Safe element reads ---------- */
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

/* ---------- Tabs ---------- */
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

/* ---------- State ---------- */
let OPTIONS = { servers: [], cache_builder_list: [] };
let pollTimer = null;

/* ---------- Options ---------- */
async function loadOptions() {
  const js = await api("api/options");
  OPTIONS = js.options || OPTIONS;
  setVal("opt-gotify-url", OPTIONS.gotify_url || "");
  setVal("opt-gotify-token", OPTIONS.gotify_token || "");
  setVal("opt-cache-global", (OPTIONS.cache_builder_list || []).join("\n"));
  renderConfigured();
}

function renderConfigured() {
  const table = document.getElementById("tbl-configured");
  if (!table) return; // mobile layout might hide it
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

async function saveOptions(patch) {
  const js = await api("api/options", "POST", patch);
  OPTIONS = js.options || OPTIONS;
}

/* ---------- Forms ---------- */
function readServerForm() {
  return {
    name: val("srv-name").trim(),
    type: val("srv-type") || "technitium",
    base_url: val("srv-base").trim(),
    dns_host: val("srv-dnshost").trim(),
    dns_port: parseInt(val("srv-dnsport", 53), 10) || 53,
    dns_protocol: val("srv-dnsproto") || "udp",
    username: val("srv-user"),
    password: val("srv-pass"),
    token: val("srv-token"),
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

/* ---------- Actions ---------- */
async function saveServer() {
  toast("Saving server…", "ok");
  const s = readServerForm();
  if (!s.name) { toast("Display Name is required", "err"); return; }
  if (!s.base_url) { toast("Base URL is required", "err"); return; }

  const list = (OPTIONS.servers || []).slice();
  const ix = list.findIndex((x) => (x.name || "") === s.name);
  if (ix >= 0) list[ix] = s; else list.push(s);

  await saveOptions({ servers: list });
  toast("Server saved", "ok");
  await loadOptions();
}

async function saveNotify() {
  toast("Saving notify…", "ok");
  await saveOptions({
    gotify_url: val("opt-gotify-url").trim(),
    gotify_token: val("opt-gotify-token").trim(),
  });
  toast("Notify saved", "ok");
}

async function saveCacheGlobal() {
  toast("Saving cache list…", "ok");
  const lines = val("opt-cache-global")
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);
  await saveOptions({ cache_builder_list: lines });
  toast("Cache list saved", "ok");
}

async function refreshStats() {
  const js = await api("api/stats");
  const u = js.unified || { total: 0, blocked: 0, allowed: 0, servers: [] };
  setVal("kpi-total", u.total);
  setVal("kpi-blocked", u.blocked);
  setVal("kpi-allowed", u.allowed);
  const pct = (js.pct_blocked || 0) + "%";
  setText("kpi-pct", pct);

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
function setText(id, v) {
  const el = document.getElementById(id);
  if (el) el.textContent = v;
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
  const js = await api("api/selfcheck");
  if (out) out.textContent = JSON.stringify(js, null, 2);
}

/* ---------- Strong event wiring (works on mobile/ingress) ---------- */
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
      await saveOptions({ servers: copy });
      toast("Server removed", "ok");
      return await loadOptions();
    }
  } catch (err) {
    console.error("Action error:", err);
    toast(String(err), "err");
  }
}

/* ---------- Boot sequence with element wait ---------- */
function waitForElements(ids, timeoutMs = 2500) {
  const start = performance.now();
  return new Promise((resolve) => {
    function check() {
      const missing = ids.filter((id) => document.getElementById(id) == null);
      if (missing.length === 0) return resolve(true);
      if (performance.now() - start > timeoutMs) {
        console.warn("Missing elements after wait:", missing);
        return resolve(false); // continue anyway, code is null-safe
      }
      requestAnimationFrame(check);
    }
    check();
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  try {
    ensureToast();
    bindEvents();
    // Elements we most commonly use; we wait briefly so mobile rendering is ready
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