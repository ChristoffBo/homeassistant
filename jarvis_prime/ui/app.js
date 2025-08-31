
/* Jarvis Prime Inbox Frontend (Ingress-safe)
   - All API calls are RELATIVE (no leading slash) so HA ingress prefix works.
   - Auto-refresh (5s) and optional SSE at "api/stream".
   - Wakeword push, delete one/all, purge, retention.
*/
(() => {
  // Resolve base path for static and API under HA Ingress
  const BASE = (() => {
    // e.g. https://ha.local/api/hassio_ingress/XYZ/ -> keep trailing slash
    const u = new URL(window.location.href);
    return u.pathname.endsWith('/') ? u.pathname : u.pathname + '/';
  })();

  // Helper to join BASE with a relative "api/..." path safely
  const url = (rel) => BASE + rel.replace(/^\/+/, '');

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

  let state = { items: [], selectedId: null, autoTimer: null, sse: null };

  const fetchJSON = async (path, opts = {}) => {
    // Cache-bust to avoid stale ingress caching
    const bust = `_=${Date.now()}`;
    const sep = path.includes('?') ? '&' : '?';
    const res = await fetch(url(path + sep + bust), {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`HTTP ${res.status}: ${text}`);
    }
    const ct = res.headers.get("content-type") || "";
    return ct.includes("application/json") ? res.json() : res.text();
  };

  const toast = (msg) => { els.footer.textContent = msg; els.footer.classList.add("blink"); setTimeout(() => els.footer.classList.remove("blink"), 400); };

  const loadMessages = async () => {
    try {
      const p = new URLSearchParams();
      p.set("limit", els.limit.value || "50");
      if (els.q.value.trim()) p.set("q", els.q.value.trim());
      const data = await fetchJSON(`api/messages?${p.toString()}`);
      state.items = Array.isArray(data.items || data) ? (data.items || data) : [];
      renderList();
      if (state.selectedId && !state.items.find(x => String(x.id) === String(state.selectedId))) {
        state.selectedId = null; renderEmpty();
      }
      toast(`Loaded ${state.items.length} message(s)`);
    } catch (e) { toast(`Load failed: ${e.message}`); }
  };

  const renderList = () => {
    els.list.innerHTML = "";
    if (!state.items.length) {
      els.list.innerHTML = `<div class="empty" style="padding:16px;color:var(--muted)">No messages.</div>`;
      return;
    }
    for (const it of state.items) {
      const row = document.createElement("div");
      row.className = "item" + (String(it.id) === String(state.selectedId) ? " active" : "");
      row.dataset.id = it.id;
      row.innerHTML = `<div><div class="title">${escapeHtml(it.title || "(No title)")}</div>
        <div class="meta">${it.created_at ? new Date(it.created_at).toLocaleString() : ""}${it.source ? ` · ${escapeHtml(it.source)}` : ""}</div></div>
        <div class="row-actions"><button class="btn danger _del">Delete</button></div>`;
      row.addEventListener("click", () => openMessage(it.id));
      row.querySelector("._del").addEventListener("click", (ev) => { ev.stopPropagation(); deleteMessage(it.id); });
      els.list.appendChild(row);
    }
  };

  const renderEmpty = () => {
    els.preview.innerHTML = `<div class="empty"><h2>Welcome 👋</h2><p>Select a message on the left to preview it here.</p><p class="hint">Tip: <kbd>/</kbd> search, <kbd>r</kbd> refresh, <kbd>w</kbd> wake, <kbd>Del</kbd> delete.</p></div>`;
  };

  const openMessage = async (id) => {
    state.selectedId = id;
    try {
      const data = await fetchJSON(`api/messages/${encodeURIComponent(id)}`);
      const m = data || {};
      els.preview.innerHTML = `<div class="detail">
        <h2>${escapeHtml(m.title || "(No title)")}</h2>
        <div class="meta">
          <span class="badge">${m.source ? escapeHtml(m.source) : "unknown"}</span>
          <span class="badge">${m.severity || "info"}</span>
          <span class="badge">${m.read ? "read" : "unread"}</span>
          <span class="badge">${m.created_at ? new Date(m.created_at).toLocaleString() : ""}</span>
        </div>
        <div class="body">${escapeHtml(m.body || "")}</div>
        <div class="row-actions"><button class="btn danger" id="pv-del">Delete</button></div>
      </div>`;
      document.getElementById("pv-del").addEventListener("click", () => deleteMessage(id));
      markRead(id).catch(()=>{});
      highlightSelected();
    } catch (e) { toast(`Open failed: ${e.message}`); }
  };

  const highlightSelected = () => {
    [...els.list.querySelectorAll(".item")].forEach(el => el.classList.toggle("active", el.dataset.id === String(state.selectedId)));
  };

  const deleteMessage = async (id) => {
    if (!confirm("Delete this message?")) return;
    try {
      await fetchJSON(`api/messages/${encodeURIComponent(id)}`, { method: "DELETE" });
      toast("Deleted");
      await loadMessages();
    } catch (e) { toast(`Delete failed: ${e.message}`); }
  };

  const deleteAll = async () => {
    if (!confirm("Delete ALL messages? This cannot be undone.")) return;
    try {
      // Prefer bulk endpoint; fallback loop
      let ok = false;
      try { await fetchJSON(`api/messages`, { method: "DELETE" }); ok = true; }
      catch (_e) {
        for (const it of state.items) { await fetchJSON(`api/messages/${encodeURIComponent(it.id)}`, { method: "DELETE" }); }
        ok = true;
      }
      if (ok) { toast("All messages deleted"); state.selectedId = null; await loadMessages(); }
    } catch (e) { toast(`Delete all failed: ${e.message}`); }
  };

  const purge = async () => {
    const days = parseInt(els.purgeDays.value || "30", 10);
    if (!confirm(`Purge messages older than ${days} day(s)?`)) return;
    try { await fetchJSON(`api/messages/purge`, { method: "POST", body: JSON.stringify({ days }) }); toast("Purge complete"); await loadMessages(); }
    } catch (e) { toast(`Purge failed: ${e.message}`); }
  };

  const saveRetention = async () => {
    const days = parseInt(els.retention.value || "30", 10);
    try { await fetchJSON(`api/retention`, { method: "POST", body: JSON.stringify({ days }) }); toast("Retention saved"); }
    catch (e) { toast(`Retention save failed: ${e.message}`); }
  };

  const markRead = async (id) => { try { await fetchJSON(`api/messages/${encodeURIComponent(id)}/read`, { method: "POST" }); } catch (_e) {} };

  const sendWake = async () => {
    const text = (els.wakeText.value || "").trim();
    if (!text) { els.wakeText.focus(); return; }
    try {
      await fetchJSON(`api/wake`, { method: "POST", body: JSON.stringify({ text }) });
      toast("Wake sent"); els.wakeText.value = ""; await loadMessages();
    } catch (e) { toast(`Wake failed: ${e.message}`); }
  };

  const startSSE = () => {
    try {
      if (state.sse) state.sse.close();
      const sse = new EventSource(url('api/stream'));
      sse.onmessage = () => loadMessages();
      sse.onerror = () => { try { sse.close(); } catch(_e){} state.sse = null; startAutoRefresh(); };
      state.sse = sse; toast("Live updates enabled"); stopAutoRefresh();
    } catch (_e) { startAutoRefresh(); }
  };

  const startAutoRefresh = () => { stopAutoRefresh(); state.autoTimer = setInterval(loadMessages, 5000); };
  const stopAutoRefresh = () => { if (state.autoTimer) clearInterval(state.autoTimer); state.autoTimer = null; };

  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Wire events
  els.btnSearch.addEventListener("click", loadMessages);
  els.btnRefresh.addEventListener("click", loadMessages);
  els.btnDeleteAll.addEventListener("click", deleteAll);
  els.btnSaveRetention.addEventListener("click", saveRetention);
  els.btnPurge.addEventListener("click", purge);
  els.btnWake.addEventListener("click", sendWake);
  els.wakeText.addEventListener("keydown", (e) => { if (e.key === "Enter") sendWake(); });
  els.q.addEventListener("keydown", (e) => { if (e.key === "Enter") loadMessages(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/") { e.preventDefault(); els.q.focus(); }
    else if (e.key.toLowerCase() === "r") { loadMessages(); }
    else if (e.key.toLowerCase() === "w") { els.wakeText.focus(); }
    else if (e.key === "Delete" && state.selectedId) { deleteMessage(state.selectedId); }
  });

  // init
  renderEmpty();
  loadMessages();
  // Try SSE first (will fall back to polling automatically)
  startSSE();
})();
