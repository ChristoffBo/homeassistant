/* Jarvis Prime Inbox Frontend
   - Auto-refresh (5s) with SSE fallback if available
   - Wakeword push
   - Delete one / Delete all
   - Purge and retention save
   - Keyboard shortcuts: / focus search, r refresh, w wake, Del delete
*/
(() => {
  const API = ""; // same-origin, served behind Ingress
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

  let state = {
    items: [],
    selectedId: null,
    autoTimer: null,
    sse: null,
  };

  const fetchJSON = async (path, opts = {}) => {
    const res = await fetch(API + path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`);
    }
    const ct = res.headers.get("content-type") || "";
    return ct.includes("application/json") ? res.json() : res.text();
  };

  const toast = (msg) => {
    els.footer.textContent = msg;
    els.footer.classList.add("blink");
    setTimeout(() => els.footer.classList.remove("blink"), 400);
  };

  // Load messages list
  const loadMessages = async () => {
    try {
      const params = new URLSearchParams();
      params.set("limit", els.limit.value || "50");
      if (els.q.value.trim()) params.set("q", els.q.value.trim());
      const data = await fetchJSON(`/api/messages?${params.toString()}`);
      // Expect array: [{id, title, body, source, created_at, read, ...}]
      state.items = Array.isArray(data.items || data) ? (data.items || data) : [];
      renderList();
      // If selected message no longer exists, clear preview
      if (state.selectedId && !state.items.find(x => x.id === state.selectedId)) {
        state.selectedId = null;
        renderEmpty();
      }
      toast(`Loaded ${state.items.length} messages`);
    } catch (e) {
      toast(`Load failed: ${e.message}`);
    }
  };

  const renderList = () => {
    els.list.innerHTML = "";
    if (!state.items.length) {
      const d = document.createElement("div");
      d.className = "empty";
      d.style.padding = "16px";
      d.style.color = "var(--muted)";
      d.textContent = "No messages.";
      els.list.appendChild(d);
      return;
    }
    for (const it of state.items) {
      const row = document.createElement("div");
      row.className = "item" + (it.id === state.selectedId ? " active" : "");
      row.dataset.id = it.id;
      const left = document.createElement("div");
      const title = document.createElement("div");
      title.className = "title";
      title.textContent = it.title || "(No title)";
      const meta = document.createElement("div");
      meta.className = "meta";
      const ts = it.created_at || it.ts || it.time || "";
      meta.textContent = (ts ? new Date(ts).toLocaleString() : "") + (it.source ? ` · ${it.source}` : "");
      left.appendChild(title);
      left.appendChild(meta);

      const right = document.createElement("div");
      right.className = "row-actions";
      const del = document.createElement("button");
      del.className = "btn danger";
      del.textContent = "Delete";
      del.addEventListener("click", (ev) => {
        ev.stopPropagation();
        deleteMessage(it.id);
      });
      right.appendChild(del);

      row.appendChild(left);
      row.appendChild(right);

      row.addEventListener("click", () => openMessage(it.id));
      els.list.appendChild(row);
    }
  };

  const renderEmpty = () => {
    els.preview.innerHTML = `
      <div class="empty">
        <h2>Welcome 👋</h2>
        <p>Select a message on the left to preview it here.</p>
        <p class="hint">Tip: <kbd>/</kbd> search, <kbd>r</kbd> refresh, <kbd>w</kbd> wake, <kbd>Del</kbd> delete.</p>
      </div>`;
  };

  const openMessage = async (id) => {
    state.selectedId = id;
    const it = state.items.find(x => x.id === id);
    if (!it) return;
    try {
      const data = await fetchJSON(`/api/messages/${encodeURIComponent(id)}`);
      const m = data || it;
      els.preview.innerHTML = `
        <div class="detail">
          <h2>${escapeHtml(m.title || "(No title)")}</h2>
          <div class="meta">
            <span class="badge">${m.source ? escapeHtml(m.source) : "unknown"}</span>
            <span class="badge">${m.severity || "info"}</span>
            <span class="badge">${m.read ? "read" : "unread"}</span>
            <span class="badge">${m.created_at ? new Date(m.created_at).toLocaleString() : ""}</span>
          </div>
          <div class="body">${escapeHtml(m.body || "")}</div>
          <div class="row-actions">
            <button class="btn danger" id="pv-del">Delete</button>
          </div>
        </div>`;
      document.getElementById("pv-del").addEventListener("click", () => deleteMessage(id));
      markRead(id).catch(()=>{});
      highlightSelected();
    } catch (e) {
      toast(`Open failed: ${e.message}`);
    }
  };

  const highlightSelected = () => {
    [...els.list.querySelectorAll(".item")].forEach(el => {
      el.classList.toggle("active", el.dataset.id === String(state.selectedId));
    });
  };

  const deleteMessage = async (id) => {
    if (!confirm("Delete this message?")) return;
    try {
      await fetchJSON(`/api/messages/${encodeURIComponent(id)}`, { method: "DELETE" });
      toast("Deleted");
      await loadMessages();
    } catch (e) {
      toast(`Delete failed: ${e.message}`);
    }
  };

  const deleteAll = async () => {
    if (!confirm("Delete ALL messages? This cannot be undone.")) return;
    try {
      // Support either bulk endpoint or loop fallback
      let ok = false;
      try {
        await fetchJSON(`/api/messages`, { method: "DELETE" });
        ok = true;
      } catch (e) {
        // fallback: delete individually
        for (const it of state.items) {
          await fetchJSON(`/api/messages/${encodeURIComponent(it.id)}`, { method: "DELETE" });
        }
        ok = true;
      }
      if (ok) {
        toast("All messages deleted");
        state.selectedId = null;
        await loadMessages();
      }
    } catch (e) {
      toast(`Delete all failed: ${e.message}`);
    }
  };

  const purge = async () => {
    const days = parseInt(els.purgeDays.value || "30", 10);
    if (!confirm(`Purge messages older than ${days} day(s)?`)) return;
    try {
      await fetchJSON(`/api/messages/purge`, { method: "POST", body: JSON.stringify({ days }) });
      toast("Purge complete");
      await loadMessages();
    } catch (e) {
      toast(`Purge failed: ${e.message}`);
    }
  };

  const saveRetention = async () => {
    const days = parseInt(els.retention.value || "30", 10);
    try {
      await fetchJSON(`/api/retention`, { method: "POST", body: JSON.stringify({ days }) });
      toast("Retention saved");
    } catch (e) {
      toast(`Retention save failed: ${e.message}`);
    }
  };

  const markRead = async (id) => {
    try {
      await fetchJSON(`/api/messages/${encodeURIComponent(id)}/read`, { method: "POST" });
    } catch (_e) {}
  };

  const sendWake = async () => {
    const text = (els.wakeText.value || "").trim();
    if (!text) {
      els.wakeText.focus();
      return;
    }
    try {
      await fetchJSON(`/api/wake`, { method: "POST", body: JSON.stringify({ text }) });
      toast("Wake sent");
      els.wakeText.value = "";
      // Prefer to reload to show any bot response quickly
      await loadMessages();
    } catch (e) {
      toast(`Wake failed: ${e.message}`);
    }
  };

  // SSE live updates if backend exposes /api/stream
  const startSSE = () => {
    try {
      if (state.sse) state.sse.close();
      const sse = new EventSource(`/api/stream`);
      sse.onmessage = (evt) => {
        // Any event means "reload list"
        loadMessages();
      };
      sse.onerror = () => {
        // fall back to polling
        sse.close();
        state.sse = null;
        startAutoRefresh();
      };
      state.sse = sse;
      toast("Live updates enabled");
      // If SSE is working, stop polling
      stopAutoRefresh();
    } catch (_e) {
      startAutoRefresh();
    }
  };

  const startAutoRefresh = () => {
    stopAutoRefresh();
    state.autoTimer = setInterval(loadMessages, 5000);
  };
  const stopAutoRefresh = () => {
    if (state.autoTimer) clearInterval(state.autoTimer);
    state.autoTimer = null;
  };

  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);

  // Events
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
  startSSE(); // tries SSE then falls back to 5s polling
})();
