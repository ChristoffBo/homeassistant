/* Jarvis Prime Inbox — rebuilt on your original working structure (JP5)
   - Ingress-safe (no leading slashes)
   - Auto-discover API base and cache it
   - SSE live updates (multiple stream path candidates) + 5s polling fallback
   - Wakeword send, delete one/all (with fallback), purge, retention, mark read
   - Instant preview for first item when list loads
*/
(() => {
  // Resolve the page base (works in HA ingress and plain web)
  const pageBase = (() => {
    const { pathname } = window.location;
    return pathname.endsWith('/') ? pathname : pathname.replace(/[^/]+$/, '');
  })();

  // Candidate API bases and stream endpoints to probe
  const BASES = ["api", "", "v1/api", "api/v1", "backend/api", "jarvis/api"];
  const STREAMS = ["stream", "api/stream", "messages/stream"];

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

  let state = { items: [], selectedId: null, timer: null, sse: null, base: localStorage.getItem("jarvis_api_base") || null };

  const urlJoin = (base, rel) => {
    const left = base.endsWith('/') ? base : base + '/';
    return left + rel.replace(/^\/+/, '');
  };
  const apiUrl = (rel) => urlJoin(pageBase + (state.base ? state.base + '/' : ''), rel);

  async function probeBase(b) {
    const u = urlJoin(pageBase + (b ? b + '/' : ''), "messages?limit=1&_=" + Date.now());
    try {
      const r = await fetch(u, { method: 'GET', credentials: 'same-origin', cache: 'no-store' });
      return r.ok;
    } catch { return false; }
  }
  async function discoverBase() {
    if (state.base) return state.base;
    for (const cand of BASES) {
      if (await probeBase(cand)) {
        state.base = cand;
        localStorage.setItem("jarvis_api_base", cand);
        toast(`API base: ${cand || "(root)"}`);
        return cand;
      }
    }
    // fallback default
    state.base = "api";
    return state.base;
  }

  async function fetchJSON(path, opts = {}) {
    if (!state.base) await discoverBase();
    const bust = `_=${Date.now()}`;
    const sep = path.includes("?") ? "&" : "?";
    const res = await fetch(apiUrl(path + sep + bust), {
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      cache: "no-store",
      ...opts,
    });
    if (!res.ok) {
      if (res.status === 404) {
        // Base probably wrong (e.g., rebuilt container). Re-discover next call.
        localStorage.removeItem("jarvis_api_base");
        state.base = null;
      }
      const text = await res.text().catch(()=> "");
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
  async function loadMessages({autoOpen=true} = {}) {
    try {
      const p = new URLSearchParams();
      p.set("limit", els.limit?.value || "50");
      if (els.q?.value?.trim()) p.set("q", els.q.value.trim());
      const data = await fetchJSON(`messages?${p.toString()}`);
      const arr = Array.isArray(data?.items) ? data.items : (Array.isArray(data) ? data : []);
      state.items = arr;
      renderList();
      if (autoOpen && state.items.length && !state.selectedId) {
        openMessage(state.items[0].id);
      } else if (state.selectedId && state.items.find(x => String(x.id) === String(state.selectedId))) {
        // Refresh preview silently to reflect possible updates
        openMessage(state.selectedId);
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
    try { await fetchJSON(`messages/${encodeURIComponent(id)}`, { method: "DELETE" }); toast("Deleted"); await loadMessages({autoOpen:false}); }
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

  async function markRead(id) { try { await fetchJSON(`messages/${encodeURIComponent(id)}/read`, { method: "POST" }); } catch (_e) {} }

  async function sendWake() {
    const text = (els.wakeText?.value || "").trim();
    if (!text) { els.wakeText?.focus(); return; }
    try { await fetchJSON(`wake`, { method: "POST", body: JSON.stringify({ text }) }); toast("Wake sent"); if (els.wakeText) els.wakeText.value = ""; await loadMessages(); }
    catch (e) { toast(`Wake failed: ${e.message}`); }
  }

  // ---- Live updates ----
  function startAuto() { stopAuto(); state.timer = setInterval(() => loadMessages({autoOpen:false}), 5000); }
  function stopAuto() { if (state.timer) clearInterval(state.timer); state.timer = null; }
  async function startSSE() {
    // probe multiple stream endpoints
    try {
      const base = pageBase + (state.base ? state.base + '/' : '');
      for (const s of STREAMS) {
        try {
          const es = new EventSource(urlJoin(base, s));
          es.onmessage = () => loadMessages({autoOpen:false});
          es.onerror = () => { try { es.close(); } catch(_e){} };
          // if we get first open, use this and stop polling
          es.onopen = () => { stopAuto(); toast("Live updates enabled"); };
          state.sse = es; return;
        } catch (_e) { /* try next */ }
      }
    } catch (_e) { /* ignore */ }
    // fallback to polling
    startAuto();
  }

  // ---- Utilities / events ----
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));

  els.btnSearch?.addEventListener("click", () => loadMessages());
  els.btnRefresh?.addEventListener("click", () => loadMessages());
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
    await discoverBase();
    await loadMessages();
    await startSSE();
  })();
})();
