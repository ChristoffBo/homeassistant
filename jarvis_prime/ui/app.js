(function () {
  /* ---------------- Helpers ---------------- */
  const $  = (s, r=document) => r.querySelector(s);
  const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));

  // Resolve API root that works in both Ingress and direct-host
  function apiRoot() {
    if (window.JARVIS_API_BASE) {
      let v = String(window.JARVIS_API_BASE);
      return v.endsWith('/') ? v : v + '/';
    }
    try {
      const u = new URL(document.baseURI);
      let p = u.pathname;
      // If UI is at /ui/ or ends with /index.html, trim to the UI root
      if (p.endsWith('/index.html')) p = p.slice(0, -'/index.html'.length);
      if (p.endsWith('/ui/')) p = p.slice(0, -4);
      if (!p.endsWith('/')) p += '/';
      u.pathname = p;
      return u.toString();
    } catch (e) {
      return document.baseURI;
    }
  }
  const ROOT = apiRoot();
  const API  = (path) => new URL(String(path).replace(/^\/+/, ''), ROOT).toString();

  function toast(msg) {
    const d = document.createElement('div');
    d.className = 'toast';
    d.textContent = msg;
    $('#toast')?.appendChild(d);
    setTimeout(() => d.remove(), 3500);
  }

  async function jfetch(url, opts) {
    const r = await fetch(url, opts);
    if (!r.ok) {
      const t = await r.text().catch(() => '');
      throw new Error(`${r.status} ${r.statusText} @ ${url}\n${t}`);
    }
    const ct = r.headers.get('content-type') || '';
    return ct.includes('application/json') ? r.json() : r.text();
  }

  /* ---------------- Tabs ---------------- */
  $$('.tablink').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.tablink').forEach(x => x.classList.remove('active'));
      btn.classList.add('active');
      $$('.tab').forEach(t => t.classList.remove('active'));
      const pane = $('#' + btn.dataset.tab);
      if (pane) pane.classList.add('active');
    });
  });

  /* ---------------- Inbox ---------------- */
  let INBOX_ITEMS = [];
  let SELECTED_ID = null;

  function fmt(ts) {
    try {
      const v = Number(ts || 0);
      const ms = v > 1e12 ? v : v * 1000;
      return new Date(ms).toLocaleString();
    } catch {
      return '';
    }
  }

  function updateCounters(items) {
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
    const today    = items.filter(i => (i.created_at || 0) >= start).length;
    const archived = items.filter(i => i.saved).length;
    const errors   = items.filter(i => /error|fail|exception/i.test(`${i.title||''} ${i.body||i.message||''}`)).length;
    $('#msg-today').textContent = today;
    $('#msg-arch').textContent  = archived;
    $('#msg-err').textContent   = errors;
  }

  function renderPreview(m) {
    if (!m) {
      $('#pv-title').textContent = 'No message selected';
      $('#pv-meta').textContent = '–';
      $('#pv-body').innerHTML = '<p class="muted">Click a message to see its contents here.</p>';
      return;
    }
    $('#pv-title').textContent = m.title || '(no title)';
    const bits = [];
    if (m.source) bits.push(m.source);
    if (m.created_at) bits.push(fmt(m.created_at));
    $('#pv-meta').textContent = bits.join(' • ') || '–';
    const body = (m.body || m.message || '').trim();
    // Avoid HTML injection; keep it simple
    $('#pv-body').textContent = body || '(empty)';
  }

  function selectRowById(id) {
    SELECTED_ID = id;
    $$('#msg-body tr.msg-row').forEach(tr => tr.classList.toggle('selected', tr.dataset.id === String(id)));
    const m = INBOX_ITEMS.find(x => String(x.id) === String(id));
    renderPreview(m);
  }

  async function loadInbox() {
    const tb = $('#msg-body');
    try {
      const data = await jfetch(API('api/messages'));
      const items = data && data.items ? data.items :
                    (Array.isArray(data) ? data : []);
      INBOX_ITEMS = Array.isArray(items) ? items : [];
      tb.innerHTML = '';

      if (!INBOX_ITEMS.length) {
        tb.innerHTML = '<tr><td colspan="4">No messages</td></tr>';
        updateCounters([]);
        renderPreview(null);
        return;
      }

      updateCounters(INBOX_ITEMS);
      for (const m of INBOX_ITEMS) {
        const tr = document.createElement('tr');
        tr.className = 'msg-row';
        tr.dataset.id = m.id;
        tr.innerHTML = `
          <td>${fmt(m.created_at)}</td>
          <td>${m.source || ''}</td>
          <td>${m.title || ''}</td>
          <td>
            <button class="btn" data-id="${m.id}" data-act="arch">${m.saved ? 'Unarchive' : 'Archive'}</button>
            <button class="btn danger" data-id="${m.id}" data-act="del">Delete</button>
          </td>`;
        tb.appendChild(tr);
      }

      const follow = $('#pv-follow')?.checked;
      const still = SELECTED_ID && INBOX_ITEMS.some(x => String(x.id) === String(SELECTED_ID));
      if (still) {
        selectRowById(SELECTED_ID);
      } else if (follow) {
        const last = INBOX_ITEMS[INBOX_ITEMS.length - 1];
        if (last) selectRowById(last.id);
        else renderPreview(null);
      } else {
        renderPreview(null);
      }
    } catch (e) {
      console.error(e);
      tb.innerHTML = '<tr><td colspan="4">Failed to load</td></tr>';
      toast('Inbox load error');
      renderPreview(null);
    }
  }

  // Row clicks and per-message actions
  $('#msg-body').addEventListener('click', (ev) => {
    const btn = ev.target.closest('button[data-act]');
    if (btn) {
      const id  = btn.dataset.id;
      const act = btn.dataset.act;
      (async () => {
        try {
          if (act === 'del') {
            if (!confirm('Delete this message?')) return;
            await jfetch(API('api/messages/' + id), { method: 'DELETE' });
            toast('Deleted');
          } else if (act === 'arch') {
            await jfetch(API(`api/messages/${id}/save`), {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({})
            });
            toast('Toggled archive');
          }
          await loadInbox();
        } catch (e) {
          toast('Action failed');
        }
      })();
      return;
    }
    const tr = ev.target.closest('tr.msg-row');
    if (tr && tr.dataset.id) selectRowById(tr.dataset.id);
  });

  // Delete All (with “keep archived” option)
  $('#del-all').addEventListener('click', async () => {
    if (!confirm('Delete ALL messages?')) return;
    const keep = $('#keep-arch')?.checked ? 1 : 0;
    try {
      await jfetch(API(`api/messages?keep_saved=${keep}`), { method: 'DELETE' });
      toast('All deleted');
      await loadInbox();
    } catch {
      toast('Delete all failed');
    }
  });

  // Live updates with SSE + backoff
  (function startStream() {
    let es = null, backoff = 1000;
    function connect() {
      try { es && es.close(); } catch {}
      es = new EventSource(API('api/stream'));
      es.onopen = () => backoff = 1000;
      es.onerror = () => {
        try { es.close(); } catch {}
        setTimeout(connect, Math.min(backoff, 15000));
        backoff = Math.min(backoff * 2, 15000);
      };
      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data || '{}');
          if (['created', 'deleted', 'deleted_all', 'saved', 'purged'].includes(data.event)) {
            loadInbox().then(() => {
              if (data.event === 'created' && $('#pv-follow')?.checked) {
                if (data.id) selectRowById(data.id);
              }
            });
          }
        } catch {}
      };
    }
    connect();
    // Safety: periodic refresh
    setInterval(loadInbox, 5 * 60 * 1000);
  })();

  /* ---------------- Boot ---------------- */
  loadInbox();
})();
