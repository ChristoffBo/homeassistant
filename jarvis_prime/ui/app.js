/* Jarvis Prime Inbox — JP7
   - API base read from <meta name="jarvis-api-base"> (default 'api'); override with ?base=…
   - SSE live updates (api/stream) + 5s polling fallback
   - Wake, Delete one/All, Purge quick buttons, Retention, Save/Unsave
   - Follow-new toggle -> auto-open latest message on arrival
*/
(() => {
  const META = document.querySelector('meta[name="jarvis-api-base"]');
  let BASE = new URLSearchParams(location.search).get('base');
  if (!BASE) BASE = (META?.content ?? 'api');
  const api = (p) => `${BASE ? BASE + '/' : ''}${p.replace(/^\/+/, '')}`;

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
    btnFollow: document.getElementById("btn-follow"),
    btnFilterSaved: document.getElementById("btn-filter-saved"),
    wakeText: document.getElementById("wake-text"),
    btnWake: document.getElementById("btn-wake"),
  };

  let state = {
    items: [],
    selectedId: null,
    follow: true,
    savedOnly: false,
    sse: null,
    timer: null,
  };

  const toast = (msg) => {
    if (!els.footer) return;
    els.footer.textContent = msg;
    els.footer.classList.add("blink");
    setTimeout(() => els.footer.classList.remove("blink"), 400);
  };

  function fmt(ts) {
    if (!ts || Number(ts) === 0) return "—";
    const d = new Date(Number(ts) * 1000);
    return d.toLocaleString();
  }

  async function jget(path) {
    const u = `${api(path)}${path.includes('?') ? '&' : '?'}_=${Date.now()}`;
    const r = await fetch(u, { credentials: "same-origin", cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`);
    const ct = r.headers.get("content-type") || "";
    return ct.includes("json") ? r.json() : r.text();
  }
  async function jsend(path, method="POST", body) {
    const r = await fetch(api(path), {
      method, credentials: "same-origin", cache: "no-store",
      headers: { "content-type": "application/json" },
      body: body ? JSON.stringify(body) : undefined
    });
    if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`);
    return r.json().catch(()=> ({}));
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
      row.innerHTML = `
        <div>
          <div class="title">${escapeHtml(it.title || "(No title)")}</div>
          <div class="meta">
            <span class="badge">${escapeHtml(it.source || "unknown")}</span>
            <span class="badge">${it.read ? "read" : "unread"}</span>
            <span class="badge">${fmt(it.created_at)}</span>
          </div>
        </div>
        <div class="badges">
          <button data-save="${it.id}" class="btn${it.saved ? ' primary' : ''} small">${it.saved ? 'Saved' : 'Save'}</button>
          <button data-del="${it.id}" class="btn danger small">Del</button>
        </div>`;
      row.addEventListener("click", (e) => {
        if (e.target.closest("button")) return;
        openMessage(it.id);
      });
      row.querySelector(`[data-del="${it.id}"]`).addEventListener("click", (ev) => { ev.stopPropagation(); deleteMessage(it.id); });
      row.querySelector(`[data-save="${it.id}"]`).addEventListener("click", async (ev) => {
        ev.stopPropagation();
        try {
          await jsend(`messages/${it.id}/save`, "POST", { saved: it.saved ? 0 : 1 });
          loadMessages({autoOpen:false});
        } catch(e){ toast(`Save failed: ${e.message}`) }
      });
      els.list.appendChild(row);
    }
  }

  async function loadMessages({autoOpen=true} = {}) {
    try {
      const p = new URLSearchParams();
      p.set("limit", els.limit?.value || "50");
      if (els.q?.value?.trim()) p.set("q", els.q.value.trim());
      if (state.savedOnly) p.set("saved", "1");
      const data = await jget(`messages?${p.toString()}`);
      const arr = Array.isArray(data?.items) ? data.items : (Array.isArray(data) ? data : []);
      state.items = arr;
      renderList();
      if (autoOpen) {
        if (state.follow && state.items.length) openMessage(state.items[0].id);
        else if (state.selectedId && state.items.find(x => String(x.id) === String(state.selectedId))) openMessage(state.selectedId);
      }
      toast(`Loaded ${state.items.length} messages`);
    } catch (e) { toast(`Load failed: ${e.message}`); }
  }

  async function openMessage(id) {
    state.selectedId = id;
    try {
      const m = await jget(`messages/${encodeURIComponent(id)}`);
      els.preview.innerHTML = `<div class="detail">
        <h2>${escapeHtml(m.title || "(No title)")}</h2>
        <div class="meta">
          <span class="badge">${escapeHtml(m.source || "unknown")}</span>
          <span class="badge">${m.read ? "read" : "unread"}</span>
          <span class="badge">${fmt(m.created_at)}</span>
        </div>
        <div class="body">${escapeHtml(m.body || "")}</div>
        <div class="row-actions">
          <button class="btn" id="pv-save">${m.saved ? 'Unsave' : 'Save'}</button>
          <button class="btn danger" id="pv-del">Delete</button>
        </div>
      </div>`;
      document.getElementById("pv-del").addEventListener("click", () => deleteMessage(id));
      document.getElementById("pv-save").addEventListener("click", async () => {
        try { await jsend(`messages/${id}/save`, "POST", { saved: m.saved ? 0 : 1 }); loadMessages({autoOpen:false}); }
        catch(e){ toast(`Save failed: ${e.message}`); }
      });
      markRead(id).catch(()=>{});
      highlightSelected();
    } catch (e) { toast(`Open failed: ${e.message}`); }
  }

  function highlightSelected() {
    [...els.list.querySelectorAll(".item")].forEach(el => el.classList.toggle("active", el.dataset.id === String(state.selectedId)));
  }

  async function deleteMessage(id) {
    if (!confirm("Delete this message?")) return;
    try { await jsend(`messages/${encodeURIComponent(id)}`, "DELETE"); toast("Deleted"); await loadMessages({autoOpen:false}); }
    catch (e) { toast(`Delete failed: ${e.message}`); }
  }

  async function deleteAll() {
    if (!confirm("Delete ALL messages? This cannot be undone.")) return;
    try { await jsend(`messages`, "DELETE"); toast("All messages deleted"); state.selectedId = null; await loadMessages(); }
    catch (e) { toast(`Delete all failed: ${e.message}`); }
  }

  async function purgeDays(days) {
    if (!confirm(`Purge messages older than ${days} day(s)?`)) return;
    try { await jsend(`inbox/purge`, "POST", { days }); toast(`Purged > ${days}d`); await loadMessages(); }
    catch (e) { toast(`Purge failed: ${e.message}`); }
  }

  async function saveRetention() {
    const days = parseInt(els.retention.value || "30", 10);
    try { await jsend(`inbox/settings`, "POST", { retention_days: days }); toast("Retention saved"); }
    catch (e) { toast(`Retention save failed: ${e.message}`); }
  }

  async function markRead(id) { try { await jsend(`messages/${encodeURIComponent(id)}/read`, "POST", { read: true }); } catch (e) {} }

  async function sendWake() {
    const text = (els.wakeText?.value || "").trim();
    if (!text) { els.wakeText?.focus(); return; }
    try { await jsend(`wake`, "POST", { text }); toast("Wake sent"); els.wakeText.value = ""; }
    catch (e) { toast(`Wake failed: ${e.message}`); }
  }

  // ---- Live updates ----
  function startAuto() { stopAuto(); state.timer = setInterval(() => loadMessages({autoOpen:true}), 5000); }
  function stopAuto() { if (state.timer) clearInterval(state.timer); state.timer = null; }
  function startSSE() {
    try {
      const es = new EventSource(api('stream'));
      es.onopen = () => { stopAuto(); toast("Live updates enabled"); };
      es.onmessage = () => loadMessages({autoOpen:true});
      es.onerror = () => { try { es.close(); } catch(_e){} startAuto(); };
      state.sse = es;
    } catch(_e) { startAuto(); }
  }

  // ---- events & init ----
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));

  els.btnSearch?.addEventListener("click", () => loadMessages());
  els.btnRefresh?.addEventListener("click", () => loadMessages());
  els.btnDeleteAll?.addEventListener("click", deleteAll);
  els.btnSaveRetention?.addEventListener("click", saveRetention);
  els.btnFollow?.addEventListener("click", () => { state.follow = !state.follow; els.btnFollow.classList.toggle("primary", state.follow); });
  els.btnFilterSaved?.addEventListener("click", () => { state.savedOnly = !state.savedOnly; els.btnFilterSaved.classList.toggle("primary", state.savedOnly); loadMessages(); });
  els.wakeText?.addEventListener("keydown", (e) => { if (e.key === "Enter") sendWake(); });
  els.btnWake?.addEventListener("click", sendWake);
  document.querySelectorAll(".purge-group .btn").forEach(b => {
    b.addEventListener("click", () => purgeDays(parseInt(b.dataset.days, 10)));
  });
  els.q?.addEventListener("keydown", (e) => { if (e.key === "Enter") loadMessages(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/") { e.preventDefault(); els.q?.focus(); }
    else if (e.key?.toLowerCase() === "r") { loadMessages(); }
    else if (e.key?.toLowerCase() === "w") { els.wakeText?.focus(); }
    else if (e.key === "Delete" && state.selectedId) { deleteMessage(state.selectedId); }
  });

  (async () => {
    els.btnFollow.classList.add("primary");
    await loadMessages();
    startSSE(); // will fall back to polling
  })();
})();
