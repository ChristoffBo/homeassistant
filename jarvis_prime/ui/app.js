
/* Jarvis Prime – route auto‑discovery
   Fix for 404s when backend serves different API bases.
   Tries multiple bases and caches the winner in localStorage.
*/
(() => {
  const CANDIDATES = [
    "api",            // expected
    "",               // root: messages at /messages
    "v1/api",
    "api/v1",
    "backend/api",
    "jarvis/api"
  ];

  const els = {
    list: document.getElementById("list"),
    preview: document.getElementById("preview"),
    footer: document.getElementById("footer"),
    q: document.getElementById("q"),
    limit: document.getElementById("limit"),
    btnSearch: document.getElementById("btn-search"),
    btnRefresh: document.getElementById("btn-refresh"),
    btnDeleteAll: document.getElementById("btn-delete-all"),
    retention: document.getElementById("retention"),
    btnSaveRetention: document.getElementById("btn-save-retention"),
    purgeDays: document.getElementById("purge-days"),
    btnPurge: document.getElementById("btn-purge"),
    wakeText: document.getElementById("wake-text"),
    btnWake: document.getElementById("btn-wake"),
  };

  let state = { items: [], selectedId: null, timer: null, sse: null, base: null };

  const baseFromStorage = localStorage.getItem("jarvis_api_base");
  if (baseFromStorage) state.base = baseFromStorage;

  const pageBase = (() => {
    const { pathname } = window.location;
    return pathname.endsWith('/') ? pathname : pathname.replace(/[^/]+$/, '');
  })();
  const apiUrl = (rel) => pageBase + (state.base ? state.base + '/' : '') + rel.replace(/^\/+/, '');

  async function probeBase(b) {
    const url = pageBase + (b ? b + '/' : '') + 'messages?limit=1&_=' + Date.now();
    try {
      const r = await fetch(url, { method: 'GET', cache: 'no-store', credentials: 'same-origin' });
      if (r.status === 200) return true;
      if (r.status === 204) return true;
      // Some servers return [] with 200 JSON, some 404 for unknown route
      return false;
    } catch { return false; }
  }

  async function discover() {
    if (state.base) return state.base;
    for (const cand of CANDIDATES) {
      const ok = await probeBase(cand);
      if (ok) {
        state.base = cand;
        localStorage.setItem("jarvis_api_base", cand);
        toast(`API base: ${cand || "(root)"}`);
        return cand;
      }
    }
    // fallback: assume "api" but continue
    state.base = "api";
    return state.base;
  }

  async function fetchJSON(path, opts = {}) {
    // discover base if needed
    if (!state.base) await discover();
    const bust = `_=${Date.now()}`;
    const sep = path.includes("?") ? "&" : "?";
    const res = await fetch(apiUrl(path + sep + bust), {
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      cache: "no-store",
      ...opts,
    });
    if (!res.ok) {
      // If 404, try to re-discover in case server base changed
      if (res.status === 404) {
        localStorage.removeItem("jarvis_api_base");
        state.base = null;
      }
      const text = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status} ${res.statusText} :: ${text.slice(0,200)}`);
    }
    const ct = res.headers.get("content-type") || "";
    return ct.includes("application/json") ? res.json() : res.text();
  }

  const toast = (msg) => {
    if (!els.footer) return;
    els.footer.textContent = msg;
    els.footer.classList.add("blink");
    setTimeout(() => els.footer.classList.remove("blink"), 400);
  };

  // ---- List / Preview ----
  async function loadMessages() {
    try {
      const p = new URLSearchParams();
      p.set("limit", els.limit?.value || "50");
      if (els.q?.value?.trim()) p.set("q", els.q.value.trim());
      const data = await fetchJSON(`messages?${p.toString()}`);
      const arr = Array.isArray(data?.items) ? data.items : (Array.isArray(data) ? data : []);
      state.items = arr;
      renderList();
      if (state.selectedId && !state.items.find(x => String(x.id) === String(state.selectedId))) {
        state.selectedId = null; renderEmpty();
      }
      toast(`Loaded ${state.items.length} messages`);
    } catch (e) { toast(`Load failed: ${e.message}`); }
  }

  function renderList() {
    els.list.innerHTML = "";
    if (!state.items.length) {
      els.list.innerHTML = `<div class="empty" style="padding:16px;color:var(--muted)">No messages.</div>`;
      return;
    }
    for (const it of state.items) {
      const row = document.createElement("div");
      row.className = "item" + (String(it.id) === String(state.selectedId) ? " active" : "");
      row.dataset.id = it.id;
      const title = document.createElement("div");
      title.innerHTML = `<div class="title">${escapeHtml(it.title || "(No title)")}</div>
        <div class="meta">${formatTs(it.created_at)} · <span class="source">${escapeHtml(it.source || "unknown")}</span></div>`;
      const actions = document.createElement("div");
      actions.className = "row-actions";
      const del = document.createElement("button");
      del.className = "btn danger"; del.textContent = "Delete";
      del.addEventListener("click", (ev) => { ev.stopPropagation(); deleteMessage(it.id); });
      actions.appendChild(del);
      row.appendChild(title);
      row.appendChild(actions);
      row.addEventListener("click", () => openMessage(it.id));
      els.list.appendChild(row);
    }
  }

  function renderEmpty() {
    els.preview.innerHTML = `<div class="empty">
      <h2>Welcome 👋</h2>
      <p>Select a message on the left to preview it here.</p>
      <p class="hint">Shortcuts: <kbd>/</kbd> search, <kbd>r</kbd> refresh, <kbd>w</kbd> wake, <kbd>Del</kbd> delete.</p>
    </div>`;
  }

  async function openMessage(id) {
    state.selectedId = id;
    try {
      const data = await fetchJSON(`messages/${encodeURIComponent(id)}`);
      const m = data || {};
      els.preview.innerHTML = `<div class="detail">
        <h2>${escapeHtml(m.title || "(No title)")}</h2>
        <div class="meta">
          <span class="badge">${escapeHtml(m.source || "unknown")}</span>
          <span class="badge">${m.severity || "info"}</span>
          <span class="badge">${m.read ? "read" : "unread"}</span>
          <span class="badge">${formatTs(m.created_at)}</span>
        </div>
        <div class="body">${escapeHtml(m.body || "")}</div>
        <div class="row-actions">
          <button class="btn danger" id="pv-del">Delete</button>
        </div>
      </div>`;
      document.getElementById("pv-del").addEventListener("click", () => deleteMessage(id));
      markRead(id).catch(()=>{});
      highlightSelected();
    } catch (e) { toast(`Open failed: ${e.message}`); }
  }

  function highlightSelected() {
    [...els.list.querySelectorAll(".item")].forEach(el => el.classList.toggle("active", el.dataset.id === String(state.selectedId)));
  }

  function formatTs(ts) {
    if (!ts || Number(ts) === 0) return "—";
    try { return new Date(ts).toLocaleString(); } catch { return "—"; }
  }

  // ---- Actions ----
  async function deleteMessage(id) {
    if (!confirm("Delete this message?")) return;
    try { await fetchJSON(`messages/${encodeURIComponent(id)}`, { method: "DELETE" }); toast("Deleted"); await loadMessages(); }
    catch (e) { toast(`Delete failed: ${e.message}`); }
  }

  async function deleteAll() {
    if (!confirm("Delete ALL messages? This cannot be undone.")) return;
    try {
      let ok = false;
      try { await fetchJSON(`messages`, { method: "DELETE" }); ok = true; }
      catch (_e) {
        for (const it of state.items) {
          await fetchJSON(`messages/${encodeURIComponent(it.id)}`, { method: "DELETE" });
        }
        ok = true;
      }
      if (ok) { toast("All messages deleted"); state.selectedId = null; await loadMessages(); }
    } catch (e) { toast(`Delete all failed: ${e.message}`); }
  }

  async function purge() {
    const days = parseInt(els.purgeDays.value || "30", 10);
    if (!confirm(`Purge messages older than ${days} day(s)?`)) return;
    try { await fetchJSON(`messages/purge`, { method: "POST", body: JSON.stringify({ days }) }); toast("Purge complete"); await loadMessages(); }
    catch (e) { toast(`Purge failed: ${e.message}`); }
  }

  async function saveRetention() {
    const days = parseInt(els.retention.value || "30", 10);
    try { await fetchJSON(`retention`, { method: "POST", body: JSON.stringify({ days }) }); toast("Retention saved"); }
    catch (e) { toast(`Retention save failed: ${e.message}`); }
  }

  async function markRead(id) { try { await fetchJSON(`messages/${encodeURIComponent(id)}/read`, { method: "POST" }); } catch (e) {} }

  async function sendWake() {
    const text = (els.wakeText?.value || "").trim();
    if (!text) { els.wakeText?.focus(); return; }
    try { await fetchJSON(`wake`, { method: "POST", body: JSON.stringify({ text }) }); toast("Wake sent"); if (els.wakeText) els.wakeText.value = ""; await loadMessages(); }
    catch (e) { toast(`Wake failed: ${e.message}`); }
  }

  // ---- Live updates ----
  function startAuto() { stopAuto(); state.timer = setInterval(loadMessages, 5000); }
  function stopAuto() { if (state.timer) clearInterval(state.timer); state.timer = null; }
  function startSSE() {
    try {
      if (state.sse) state.sse.close();
      const sse = new EventSource(apiUrl((state.base ? state.base + '/' : '') + 'stream'));
      sse.onmessage = () => loadMessages();
      sse.onerror = () => { try { sse.close(); } catch(_e){} state.sse = null; startAuto(); };
      state.sse = sse; toast("Live updates enabled");
      stopAuto();
    } catch (_e) { startAuto(); }
  }

  // ---- Utilities / events ----
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));

  els.btnSearch?.addEventListener("click", loadMessages);
  els.btnRefresh?.addEventListener("click", loadMessages);
  els.btnDeleteAll?.addEventListener("click", deleteAll);
  els.btnSaveRetention?.addEventListener("click", saveRetention);
  els.btnPurge?.addEventListener("click", purge);
  els.btnWake?.addEventListener("click", sendWake);
  els.wakeText?.addEventListener("keydown", (e) => { if (e.key === "Enter") sendWake(); });
  els.q?.addEventListener("keydown", (e) => { if (e.key === "Enter") loadMessages(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/") { e.preventDefault(); els.q?.focus(); }
    else if (e.key?.toLowerCase() === "r") { loadMessages(); }
    else if (e.key?.toLowerCase() === "w") { els.wakeText?.focus(); }
    else if (e.key === "Delete" && state.selectedId) { deleteMessage(state.selectedId); }
  });

  // init
  (async () => {
    renderEmpty();
    await discover();
    await loadMessages();
    startSSE(); // will fall back to polling
  })();
})();
