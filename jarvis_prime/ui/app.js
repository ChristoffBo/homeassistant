// Jarvis Prime Inbox UI — Ingress-ready v3 (desktop + Android)
// - Uses base-path-safe URLs so Home Assistant Ingress "just works"
// - Correct API methods/paths (POST settings+purge, delete-all with keep_saved)
// - Uses created_at timestamps, extras JSON, saved/favorite toggle
// - SSE live updates with polling fallback
(function(){
  const $ = (s, r=document) => r.querySelector(s);
  const els = {
    list: $('#list'),
    preview: $('#preview'),
    q: $('#q'),
    limit: $('#limit'),
    refresh: $('#btn-refresh'),
    search: $('#btn-search'),
    retention: $('#retention'),
    saveRetention: $('#btn-save-retention'),
    purgeDays: $('#purge-days'),
    purge: $('#btn-purge'),
    footer: $('#footer'),
    savedOnly: null // inserted later
  };

  // ---- Base-path safe URL builder ----
  const base = document.baseURI;
  const u = (path) => new URL(path.replace(/^\//?, ''), base).toString();

  // ---- API client ----
  const API = {
    async list(q, limit=50, offset=0, savedOnly=null){
      const url = new URL(u('api/messages'));
      if(q) url.searchParams.set('q', q);
      url.searchParams.set('limit', limit);
      url.searchParams.set('offset', offset);
      if(savedOnly!==null) url.searchParams.set('saved', savedOnly ? '1' : '0');
      const r = await fetch(url);
      if(!r.ok) throw new Error('Failed to list messages');
      return (await r.json()).items || [];
    },
    async get(id){
      const r = await fetch(u(`api/messages/${id}`));
      if(!r.ok) throw new Error('Message not found');
      return await r.json();
    },
    async del(id){
      const r = await fetch(u(`api/messages/${id}`), { method:'DELETE' });
      if(!r.ok) throw new Error('Delete failed');
      return await r.json();
    },
    async read(id, read=true){
      const r = await fetch(u(`api/messages/${id}/read`), {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({read})
      });
      if(!r.ok) throw new Error('Read toggle failed');
      return await r.json();
    },
    async setSaved(id, saved=true){
      const r = await fetch(u(`api/messages/${id}/save`), {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({saved})
      });
      if(!r.ok) throw new Error('Save toggle failed');
      return await r.json();
    },
    async getSettings(){
      const r = await fetch(u('api/inbox/settings')); if(!r.ok) throw new Error('settings');
      return await r.json();
    },
    async setRetention(days){
      const r = await fetch(u('api/inbox/settings'), {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({retention_days: days})
      });
      if(!r.ok) throw new Error('save settings'); return await r.json();
    },
    async purge(days){
      const r = await fetch(u('api/inbox/purge'), {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({days})
      });
      if(!r.ok) throw new Error('purge failed'); return await r.json();
    },
    async deleteAll(keepSaved=false){
      const r = await fetch(u(`api/messages?keep_saved=${keepSaved?1:0}`), { method:'DELETE' });
      if(!r.ok) throw new Error('delete all failed'); return await r.json();
    }
  };

  // ---- State ----
  let state = { items:[], activeId:null, savedOnly:false };
  function fmtTime(ts){
    try{
      const d = new Date(((ts||0))*1000);
      return d.toLocaleString();
    }catch(e){ return ''; }
  }
  function escapeHtml(s){ return (s||'').replace(/[&<>\"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[m])); }

  // ---- UI rendering ----
  function renderList(items){
    const root = els.list;
    root.innerHTML = '';
    if(!items.length){
      root.innerHTML = '<div class="item"><div class="title">No messages</div><div class="meta">—</div></div>';
      return;
    }
    for(const it of items){
      const div = document.createElement('div');
      div.className = 'item';
      div.dataset.id = it.id;
      div.innerHTML = `
        <div>
          <div class="title">${escapeHtml(it.title || '(no title)')}</div>
          <div class="meta">${fmtTime(it.created_at)} • <span class="source">${escapeHtml(it.source||'?')}</span>${it.saved?' • ★':''}</div>
        </div>
        <div class="meta">#${it.id}</div>
      `;
      div.addEventListener('click', () => select(it.id));
      root.appendChild(div);
    }
  }

  async function renderPreview(it){
    els.preview.innerHTML = '';
    const meta = [];
    if(it.source) meta.push(`<span class="badge">Source: ${escapeHtml(it.source)}</span>`);
    if(it.priority!=null) meta.push(`<span class="badge">Priority: ${it.priority}</span>`);
    if(it.created_at) meta.push(`<span class="badge">${fmtTime(it.created_at)}</span>`);
    if(it.extras && it.extras.via) meta.push(`<span class="badge">Via: ${escapeHtml(it.extras.via)}</span>`);
    const body = (it.body || it.message || '').trim();

    const root = document.createElement('div');
    root.className = 'detail';
    root.innerHTML = `
      <h2>${escapeHtml(it.title || '(no title)')}</h2>
      <div class="meta">${meta.join(' ')}</div>
      <div class="body">${escapeHtml(body)}</div>
      <div class="row-actions">
        <button id="btn-save" class="btn">${it.saved?'★ Unsave':'☆ Save'}</button>
        <button id="btn-copy" class="btn">Copy</button>
        <button id="btn-delete" class="btn danger">Delete</button>
        <span class="spacer"></span>
        <button id="btn-delete-all" class="btn danger" title="Delete all messages">Delete all</button>
        <label class="retention"><span>Keep favorites</span><input id="keep-fav" type="checkbox" checked/></label>
      </div>
    `;
    els.preview.appendChild(root);

    root.querySelector('#btn-copy').addEventListener('click', () => {
      const text = `${it.title || ''}\n\n${body}`.trim();
      navigator.clipboard.writeText(text).then(()=>toast('Copied'));
    });
    root.querySelector('#btn-delete').addEventListener('click', async () => {
      if(!confirm('Delete this message?')) return;
      await API.del(it.id);
      toast('Deleted');
      load();
    });
    root.querySelector('#btn-save').addEventListener('click', async () => {
      const want = !it.saved;
      await API.setSaved(it.id, want);
      it.saved = want;
      toast(want?'Saved':'Unsaved');
      load(it.id);
    });
    root.querySelector('#btn-delete-all').addEventListener('click', async () => {
      if(!confirm('Delete ALL messages?')) return;
      const keep = root.querySelector('#keep-fav').checked;
      await API.deleteAll(keep);
      toast('All deleted');
      load();
    });
  }

  function toast(msg){
    els.footer.textContent = msg;
    setTimeout(() => els.footer.textContent = '', 1800);
  }

  // ---- Loaders ----
  async function select(id){
    state.activeId = id;
    [...els.list.querySelectorAll('.item')].forEach(el => el.classList.toggle('active', el.dataset.id==id));
    const it = await API.get(id);
    renderPreview(it);
  }

  async function load(selectId=null){
    const q = els.q.value.trim();
    const limit = parseInt(els.limit.value,10)||50;
    const items = await API.list(q, limit, 0, state.savedOnly);
    state.items = items;
    renderList(items);
    if(selectId && items.find(i=>i.id===selectId)){ select(selectId); return; }
    if(items[0]) select(items[0].id);
    else els.preview.innerHTML = '<div class="empty"><h2>Welcome 👋</h2><p>No messages found.</p></div>';
  }

  async function loadSettings(){
    try{
      const s = await API.getSettings();
      if(s && s.retention_days) els.retention.value = s.retention_days;
      els.purgeDays.value = els.retention.value;
    }catch(e){ /* ignore */ }
  }

  // ---- SSE + Poll fallback ----
  function startLive(){
    let pollTimer = null;
    try{
      const src = new EventSource(u('api/stream'));
      src.onmessage = (e)=>{
        try{
          const data = JSON.parse(e.data||'{}');
          const ev = data.event;
          if(ev==='created' || ev==='deleted' || ev==='deleted_all' || ev==='saved' || ev==='purged'){
            // Refresh list; keep current selection if possible
            const id = state.activeId;
            load(id);
          }
        }catch(_){ /* ignore */ }
      };
      src.onerror = ()=>{
        // fallback to polling every 5s
        if(!pollTimer){
          pollTimer = setInterval(()=> load(state.activeId), 5000);
        }
      };
    }catch(e){
      pollTimer = setInterval(()=> load(state.activeId), 5000);
    }
  }

  // ---- Small UI wiring ----
  function addSavedToggle(){
    const toggle = document.createElement('button');
    toggle.className = 'btn';
    toggle.textContent = 'Saved only: OFF';
    toggle.title = 'Show only favorited messages';
    toggle.addEventListener('click', ()=>{
      state.savedOnly = !state.savedOnly;
      toggle.textContent = 'Saved only: ' + (state.savedOnly?'ON':'OFF');
      load(state.activeId);
    });
    // Insert after Search button
    els.search.insertAdjacentElement('afterend', toggle);
    els.savedOnly = toggle;
  }

  // ---- Events ----
  els.refresh.addEventListener('click', ()=>load(state.activeId));
  els.search.addEventListener('click', ()=>load());
  els.limit.addEventListener('change', ()=>load());
  els.q.addEventListener('keydown', e => { if(e.key==='Enter') load(); });

  els.saveRetention.addEventListener('click', async () => {
    const days = parseInt(els.retention.value,10)||30;
    await API.setRetention(days);
    toast('Retention saved');
  });
  els.purge.addEventListener('click', async () => {
    const days = parseInt(els.purgeDays.value,10)||30;
    if(!confirm(`Purge messages older than ${days} days?`)) return;
    const res = await API.purge(days);
    toast(`Purged ${res.purged||res.removed||0} items`);
    load();
  });

  // boot
  addSavedToggle();
  loadSettings().then(()=>load());
  startLive();
})();
