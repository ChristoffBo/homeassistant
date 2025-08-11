/* eslint-disable */
const $ = (q) => document.querySelector(q);
const $$ = (q) => Array.from(document.querySelectorAll(q));

function resolvePath(p) {
  if (/^https?:\/\//i.test(p)) return p;
  const loc = window.location.pathname;
  const m = loc.match(/^\/api\/hassio_ingress\/[^/]+/);
  const base = m ? m[0] : loc.replace(/\/[^/]*$/, "");
  return `${base}/${p.replace(/^\//, "")}`;
}

async function api(path, method = "GET", body = null) {
  const url = resolvePath(path);
  const res = await fetch(url, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : null,
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} @ ${url}`);
  const ct = res.headers.get("content-type") || "";
  if (!ct.includes("application/json")) {
    const txt = await res.text();
    throw new Error(`Expected JSON, got ${ct}. First: ${txt.slice(0,120)}`);
  }
  return await res.json();
}

function toast(msg, cls = "") {
  const t = $("#toast");
  if (!t) return alert(msg);
  t.textContent = msg;
  t.className = `toast show ${cls || ""}`;
  setTimeout(() => t.classList.remove("show"), 2500);
}

function bindTabs() {
  $$(".tab-link").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      $$(".tab-link").forEach((x) => x.classList.remove("active"));
      a.classList.add("active");
      const tab = a.dataset.tab;
      $$(".tab").forEach((s) => s.classList.remove("active"));
      $("#" + tab).classList.add("active");
    }, { passive: false });
  });
}

let OPTIONS = null;

async function loadOptions() {
  const js = await api("api/options");
  OPTIONS = js.options || { servers: [], cache_builder_list: [] };
  $("#opt-gotify-url").value = OPTIONS.gotify_url || "";
  $("#opt-gotify-token").value = OPTIONS.gotify_token || "";
  $("#opt-cache-global").value = (OPTIONS.cache_builder_list || []).join("\n");
  renderConfigured();
}

function renderConfigured() {
  const tb = $("#tbl-configured tbody");
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

function readServerForm() {
  return {
    name: $("#srv-name").value.trim(),
    type: $("#srv-type").value,
    base_url: $("#srv-base").value.trim(),
    dns_host: $("#srv-dnshost").value.trim(),
    dns_port: parseInt($("#srv-dnsport").value, 10) || 53,
    dns_protocol: $("#srv-dnsproto").value,
    username: $("#srv-user").value,
    password: $("#srv-pass").value,
    token: $("#srv-token").value,
    verify_tls: $("#srv-verify").checked,
    primary: $("#srv-primary").checked,
    cache_builder_override: false,
    cache_builder_list: [],
  };
}

function clearServerForm() {
  $("#srv-name").value = "";
  $("#srv-type").value = "technitium";
  $("#srv-base").value = "";
  $("#srv-dnshost").value = "";
  $("#srv-dnsport").value = 53;
  $("#srv-dnsproto").value = "udp";
  $("#srv-user").value = "";
  $("#srv-pass").value = "";
  $("#srv-token").value = "";
  $("#srv-verify").checked = true;
  $("#srv-primary").checked = false;
}

async function saveServer() {
  // immediate feedback so you know the click worked
  toast("Saving server...", "ok");
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
  toast("Saving notify...", "ok");
  await saveOptions({
    gotify_url: $("#opt-gotify-url").value.trim(),
    gotify_token: $("#opt-gotify-token").value.trim(),
  });
  toast("Notify saved", "ok");
}

async function saveCacheGlobal() {
  toast("Saving cache list...", "ok");
  const lines = $("#opt-cache-global").value.split("\n").map((x) => x.trim()).filter(Boolean);
  await saveOptions({ cache_builder_list: lines });
  toast("Cache list saved", "ok");
}

async function refreshStats() {
  const js = await api("api/stats");
  const u = js.unified || { total: 0, blocked: 0, allowed: 0, servers: [] };
  $("#kpi-total").textContent = u.total;
  $("#kpi-blocked").textContent = u.blocked;
  $("#kpi-allowed").textContent = u.allowed;
  $("#kpi-pct").textContent = (js.pct_blocked || 0) + "%";
  let busiest = "n/a", best = -1;
  (u.servers || []).forEach((s) => { if (s.ok && s.total > best) { best = s.total; busiest = s.name || s.type; } });
  $("#kpi-busiest").textContent = busiest;

  const tb = $("#tbl-servers tbody");
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

let pollTimer = null;
function setAutoRefresh() {
  if (pollTimer) clearInterval(pollTimer);
  const sec = parseInt($("#refresh-every").value, 10);
  pollTimer = setInterval(refreshStats, sec * 1000);
}

async function runSelfCheck() {
  $("#selfcheck-output").textContent = "Running...";
  const js = await api("api/selfcheck");
  $("#selfcheck-output").textContent = JSON.stringify(js, null, 2);
}

// --------- STRONG event wiring: delegation + touch + click
function bindEvents() {
  // Delegation: works even if elements are re-rendered
  document.body.addEventListener("click", onAction, { passive: false });
  document.body.addEventListener("touchend", onAction, { passive: false });

  // Tabs still get direct listeners
  bindTabs();
}

async function onAction(e) {
  const btn = e.target.closest("button");
  if (!btn) return;

  // prevent form submissions doing full navigations
  e.preventDefault();

  const id = btn.id;
  const act = btn.dataset.action;

  try {
    if (id === "btn-save-server")      return await saveServer();
    if (id === "btn-clear-form")       return void clearServerForm();
    if (id === "btn-save-notify")      return await saveNotify();
    if (id === "btn-save-cache")       return await saveCacheGlobal();
    if (id === "btn-update-now")       return await refreshStats();
    if (id === "btn-selfcheck")        return await runSelfCheck();

    if (act === "edit") {
      const i = parseInt(btn.dataset.idx, 10);
      const s = (OPTIONS.servers || [])[i] || {};
      $("#srv-name").value = s.name || "";
      $("#srv-type").value = s.type || "technitium";
      $("#srv-base").value = s.base_url || "";
      $("#srv-dnshost").value = s.dns_host || "";
      $("#srv-dnsport").value = s.dns_port || 53;
      $("#srv-dnsproto").value = s.dns_protocol || "udp";
      $("#srv-user").value = s.username || "";
      $("#srv-pass").value = s.password || "";
      $("#srv-token").value = s.token || "";
      $("#srv-verify").checked = !!s.verify_tls;
      $("#srv-primary").checked = !!s.primary;
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

document.addEventListener("DOMContentLoaded", async () => {
  try {
    bindEvents();
    await loadOptions();
    await refreshStats();
    setAutoRefresh();
  } catch (e) {
    console.error("Boot error:", e);
    toast("UI failed to start (see console)", "err");
  }
});