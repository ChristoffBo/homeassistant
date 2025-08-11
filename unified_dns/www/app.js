/* eslint-disable */
const $ = (q) => document.querySelector(q);
const $$ = (q) => Array.from(document.querySelectorAll(q));

async function api(path, method = "GET", body = null) {
  // Relative to ingress base
  const url = path.replace(/^\//, "");
  const res = await fetch(url, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : null,
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  const ct = res.headers.get("content-type") || "";
  if (!ct.includes("application/json")) {
    const txt = await res.text();
    throw new Error(`Expected JSON, got ${ct} (${txt.slice(0,80)}...)`);
  }
  return await res.json();
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
    });
  });
}

let OPTIONS = null;

function toast(msg, cls = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = `toast show ${cls || ""}`;
  setTimeout(() => t.classList.remove("show"), 2500);
}

async function loadOptions() {
  try {
    const js = await api("api/options");
    OPTIONS = js.options || {};
  } catch (e) {
    toast("Load options failed: " + e, "err");
    OPTIONS = { servers: [], cache_builder_list: [] };
  }
  $("#opt-gotify-url").value = OPTIONS.gotify_url || "";
  $("#opt-gotify-token").value = OPTIONS.gotify_token || "";
  $("#opt-cache-global").value = (OPTIONS.cache_builder_list || []).join("\n");
  renderConfigured();
}

function renderConfigured() {
  const tb = $("#tbl-configured tbody");
  tb.innerHTML = "";
  (OPTIONS.servers || []).forEach((s, idx) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${s.name || ""}</td>
      <td>${s.type || ""}</td>
      <td>${s.base_url || ""}</td>
      <td>${s.primary ? "Yes" : "No"}</td>
      <td class="actions">
        <button type="button" class="btn btn-xs" data-edit="${idx}">Edit</button>
        <button type="button" class="btn btn-xs btn-danger" data-del="${idx}">Delete</button>
      </td>
    `;
    tb.appendChild(tr);
  });
  tb.querySelectorAll("[data-edit]").forEach((b) => {
    b.addEventListener("click", () => {
      const i = parseInt(b.dataset.edit, 10);
      const s = OPTIONS.servers[i];
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
    });
  });
  tb.querySelectorAll("[data-del]").forEach((b) => {
    b.addEventListener("click", async () => {
      const i = parseInt(b.dataset.del, 10);
      const copy = (OPTIONS.servers || []).slice();
      copy.splice(i, 1);
      try {
        await saveOptions({ servers: copy });
        toast("Server removed", "ok");
      } catch (e) {
        toast(`Delete failed: ${e}`, "err");
      }
      await loadOptions();
    });
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
  const s = readServerForm();
  if (!s.name) return toast("Display Name is required", "err");
  if (!s.base_url) return toast("Base URL is required", "err");
  const list = (OPTIONS.servers || []).slice();
  const ix = list.findIndex((x) => (x.name || "") === s.name);
  if (ix >= 0) list[ix] = s; else list.push(s);
  try {
    await saveOptions({ servers: list });
    toast("Server saved", "ok");
  } catch (e) {
    return toast(`Save failed: ${e}`, "err");
  }
  await loadOptions();
}

async function saveNotify() {
  try {
    await saveOptions({
      gotify_url: $("#opt-gotify-url").value.trim(),
      gotify_token: $("#opt-gotify-token").value.trim(),
    });
    toast("Notify settings saved", "ok");
  } catch (e) {
    toast(`Save failed: ${e}`, "err");
  }
}

async function saveCacheGlobal() {
  const lines = $("#opt-cache-global").value.split("\n").map((x) => x.trim()).filter(Boolean);
  try {
    await saveOptions({ cache_builder_list: lines });
    toast("Cache list saved", "ok");
  } catch (e) {
    toast(`Save failed: ${e}`, "err");
  }
}

let pollTimer = null;
async function refreshStats() {
  try {
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
        <td>${s.ok ? s.blocked : "-"}</td>
      `;
      tb.appendChild(tr);
    });
  } catch (e) {
    toast(`Stats error: ${e}`, "err");
  }
}

function setAutoRefresh() {
  if (pollTimer) clearInterval(pollTimer);
  const sec = parseInt($("#refresh-every").value, 10);
  pollTimer = setInterval(refreshStats, sec * 1000);
}

async function runSelfCheck() {
  $("#selfcheck-output").textContent = "Running...";
  try {
    const js = await api("api/selfcheck");
    $("#selfcheck-output").textContent = JSON.stringify(js, null, 2);
  } catch (e) {
    $("#selfcheck-output").textContent = String(e);
  }
}

function bindEvents() {
  $("#btn-save-server").addEventListener("click", saveServer);
  $("#btn-clear-form").addEventListener("click", clearServerForm);
  $("#btn-save-notify").addEventListener("click", saveNotify);
  $("#btn-save-cache").addEventListener("click", saveCacheGlobal);
  $("#btn-update-now").addEventListener("click", refreshStats);
  $("#refresh-every").addEventListener("change", setAutoRefresh);
  $("#btn-selfcheck").addEventListener("click", runSelfCheck);
}

document.addEventListener("DOMContentLoaded", async () => {
  bindTabs();
  bindEvents();
  await loadOptions();
  await refreshStats();
  setAutoRefresh();
});