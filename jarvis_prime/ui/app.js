// Jarvis Prime — Notify (Outlook/ntfy layout), SSE, ingress-safe
(function(){
  const $ = (s, r=document) => r.querySelector(s);
  const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));

  // Ingress-safe API root
  function apiRoot() {
    let b = document.baseURI;
    try {
      const url = new URL(b);
      let p = url.pathname;
      if (p.endsWith('/ui/')) p = p.slice(0, -4); // strip 'ui/'
      if (!p.endsWith('/')) p += '/';
      url.pathname = p;
      return url.toString();
    } catch { return b; }
  }
  const ROOT = apiRoot();
  const u = (path) => new URL(path.replace(/^\/+/, ''), ROOT).toString();

  // Elements
  const els = {
    feed: $('#feed'), detail: $('#detail'),
    q: $('#q'), search: $('#btn-search'), refresh: $('#btn-refresh'),
    keepArch: $('#keep-arch'), railDelAll: $('#rail-delall'),
    railTabs: $$('.tab[data-tab]'), srcChips: $$('.chip.src'),
    listCount: $('#c-all'),
    // Compose
    fab: $('#fab'), compose: $('#compose'), composeClose: $('#compose-close'),
    wakeText: $('#wake-text'), wakeSend: $('#wake-send'),
    chime: $('#chime'), ding: $('#ding'),
    // Settings drawer
    settingsBtn: $('#btn-settings'), drawer: $('#drawer'), drawerClose: $('#drawer-close'),
    dtabs: $$('.dtab'),
    // Retention/Purge in drawer
    retention: $('#retention'), saveRetention: $('#btn-save-retention'),
    purgeDays: $('#purge-days'), purge: $('#btn-purge'),
    // Toast
    toast: $('#toast'),
    // Mobile back
    back: $('#btn-back')
  };

  function toast(msg){
    const d=document.createElement('div');
    d.className='toast'; d.textContent=msg;
    els.toast.appendChild(d);
    setTimeout(()=> d.remove(), 3200);
  }
  const esc = s => String(s||'').replace(/[&<>"']/g, m=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m]));
  const fmt = (ts) => {
    try { const v=Number(ts||0); const ms = v>1e12 ? v : v*1000; return new Date(ms).toLocaleString(); }
    catch { return '' }
  };

  async function jfetch(url, opts){
    const isTemp = /\/api\/messages\/ui-\d+$/.test(String(url));
    try{
      const r = await fetch(url, opts);
      if(!r.ok){
        const t = await r.text().catch(()=> '');
        if(!(isTemp && r.status===404)) throw new Error(r.status+' '+r.statusText+' @ '+url+'\n'+t);
        else return Promise.reject(new Error('temp-404'));
      }
      const ct = r.headers.get('content-type')||'';
      return ct.includes('application/json') ? r.json() : r.text();
    }catch(e){
      console.error('Request failed:', e);
      toast('HTTP error: ' + e.message);
      throw e;
    }
  }

  const API = {
    async list(q, limit=50, offset=0){
      const url = new URL(u('api/messages'));
      if(q) url.searchParams.set('q', q);
      url.searchParams.set('limit', limit);
      url.searchParams.set('offset', offset);
      const data = await jfetch(url.toString());
      return (data && data.items) ? data.items : (Array.isArray(data)?data:[]);
    },
    async get(id){ return jfetch(u('api/messages/'+id)); },
    async del(id){ return jfetch(u('api/messages/'+id), {method:'DELETE'}); },
    async setArchived(id,val){ return jfetch(u(`api/messages/${id}/save`),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({saved:val})}); },
    async getSettings(){ return jfetch(u('api/inbox/settings')); },
    async setRetention(days){ return jfetch(u('api/inbox/settings'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({retention_days:days})}); },
    async purge(days){ return jfetch(u('api/inbox/purge'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({days})}); },
    async deleteAll(keep){ return jfetch(u(`api/messages?keep_saved=${keep?1:0}`),{method:'DELETE'}); },
    async wake(text){ return jfetch(u('api/wake'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text: 'Jarvis ' + text})}); },

    // Optional notify/settings endpoints (safe if 404)
    async saveChannels(payload){ return jfetch(u('api/notify/channels'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) }); },
    async test(kind){ return jfetch(u(`api/notify/test/${kind}`), { method:'POST' }); },
    async saveRouting(payload){ return jfetch(u('api/notify/routing'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) }); },
    async saveQuiet(payload){ return jfetch(u('api/notify/quiet'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) }); },
    async savePersonas(payload){ return jfetch(u('api/notify/personas'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) }); }
  };

  const state = { items: [], active: null, tab: 'all', source: '', newestSeen: 0 };

  function renderFeed(items){
    const list = items
      .filter(i => state.tab==='archived' ? i.saved :
                   state.tab==='errors' ? /error|fail|exception/i.test((i.title||'') + ' ' + (i.body||i.message||'')) :
                   state.tab==='unread' ? (state.newestSeen && i.created_at>state.newestSeen) : true)
      .filter(i => state.source ? (String(i.source||'').toLowerCase()===state.source) : true);

    const root = els.feed; root.innerHTML='';
    if(!list.length){
      root.innerHTML = '<div class="toast">No messages</div>';
      if(els.listCount) els.listCount.textContent = String(items.length||0);
      return;
    }
    if(els.listCount) els.listCount.textContent = String(items.length);

    for(const it of list){
      const row = document.createElement('div');
      const isNew = state.newestSeen && it.created_at>state.newestSeen;
      row.className = 'row' + (isNew ? ' unread' : '');
      row.dataset.id = it.id;

      const title = esc(it.title || '(no title)');
      const time = fmt(it.created_at);
      const src  = esc(it.source || '?');
      const snippet = esc((it.body||it.message||'').replace(/\s+/g,' ').slice(0,90));

      row.innerHTML = `
        <div class="dot"></div>
        <div class="title">${title}<span class="src"> • ${src}</span><span class="snippet"> — ${snippet}</span></div>
        <div class="meta">${time}</div>`;
      row.addEventListener('click', ()=> select(it.id));
      root.appendChild(row);
    }
  }

  async function renderDetail(it){
    els.detail.innerHTML='';
    const w = document.createElement('div'); w.className='wrap';
    const badges = [];
    if(it.source) badges.push(`<span class="badge">Source: ${esc(it.source)}</span>`);
    if(it.created_at) badges.push(`<span class="badge">${fmt(it.created_at)}</span>`);
    w.innerHTML = `
      <h2>${esc(it.title||'(no title)')}</h2>
      <div class="badges">${badges.join(' ')}</div>
      <div class="body">${esc((it.body||it.message||'').trim())}</div>
      <div class="actions">
        <button id="a-arch" class="btn">${it.saved?'Unarchive':'Archive'}</button>
        <button id="a-copy" class="btn">Copy</button>
        <button id="a-del" class="btn danger">Delete</button>
      </div>`;
    els.detail.appendChild(w);

    $('#a-copy').addEventListener('click', ()=> navigator.clipboard.writeText(`${it.title||''}\n\n${it.body||it.message||''}`));
    $('#a-del').addEventListener('click', async()=>{ if(!confirm('Delete this message?')) return; await API.del(it.id); toast('Deleted'); load(); });
    $('#a-arch').addEventListener('click', async()=>{ await API.setArchived(it.id,!it.saved); toast(it.saved?'Unarchived':'Archived'); load(it.id); });
  }

  // --- Mobile flow: list-first, then detail ---
  const isMobile = () => window.matchMedia('(max-width:1100px)').matches;
  els.back?.addEventListener('click', ()=> { document.body.classList.remove('mobile-detail'); });

  // Always start in LIST on mobile (prevents landing in detail due to auto-select)
  window.addEventListener('pageshow', () => {
    if (isMobile()) document.body.classList.remove('mobile-detail');
  });

  async function select(id){
    state.active = id;
    if(String(id).startsWith('ui-')){
      const temp = state.items.find(x=> String(x.id)===String(id));
      if(temp){
        renderDetail(temp);
        if(isMobile()) document.body.classList.add('mobile-detail');
        return;
      }
    }
    try{
      const it = await API.get(id);
      renderDetail(it);
      if(isMobile()) document.body.classList.add('mobile-detail');
    }catch{}
  }

  async function load(selectId=null){
    const items = await API.list($('#q')?.value?.trim()||'', 100, 0);
    if(!state.newestSeen && items[0]) state.newestSeen = items[0].created_at || 0;
    state.items = items;
    renderFeed(items);
    // On desktop, auto-select first message; on mobile stay in list until user taps
    if(!isMobile()){
      if(selectId && items.find(i=>String(i.id)===String(selectId))) select(selectId);
      else if(!state.active && items[0]) select(items[0].id);
    }
  }

  function startLive(){
    let backoff = 1000;
    function connect(){
      const es = new EventSource(u('api/stream'));
      let opened=false;
      es.onopen = ()=>{ opened=true; backoff=1000; };
      es.onerror = ()=>{ try{es.close();}catch{}; if(opened) toast('Connection lost. Reconnecting…'); setTimeout(connect, Math.min(backoff,10000)); backoff=Math.min(backoff*2,10000); };
      es.onmessage = (e)=>{
        try{
          const data = JSON.parse(e.data||'{}');
          if(['created','deleted','deleted_all','saved','purged'].includes(data.event)){
            if(els.chime?.checked) try{ els.ding.currentTime=0; els.ding.play(); }catch{}
            load(state.active);
          }
        }catch{}
      };
    }
    connect();
    setInterval(()=> load(state.active), 300000);
  }

  // Filters
  els.railTabs.forEach(t=> t.addEventListener('click', ()=>{
    els.railTabs.forEach(x=>x.classList.remove('active')); t.classList.add('active');
    state.tab = t.dataset.tab; renderFeed(state.items);
  }));
  els.srcChips.forEach(c=> c.addEventListener('click', ()=>{
    els.srcChips.forEach(x=>x.classList.remove('active'));
    c.classList.add('active'); state.source = (c.dataset.src||'').toLowerCase(); renderFeed(state.items);
  }));

  // Actions & search
  els.search?.addEventListener('click', ()=> load());
  els.refresh?.addEventListener('click', ()=> load(state.active));
  $('#q')?.addEventListener('keydown', e=>{ if(e.key==='Enter') load(); });

  // Delete all
  els.railDelAll?.addEventListener('click', async()=>{
    if(!confirm('Delete ALL messages?')) return;
    await API.deleteAll(els.keepArch.checked);
    toast('All deleted'); load();
  });

  // Compose
  els.fab?.addEventListener('click', ()=> els.compose.classList.add('open'));
  els.composeClose?.addEventListener('click', ()=> els.compose.classList.remove('open'));
  els.wakeSend?.addEventListener('click', async()=>{
    const t = els.wakeText.value.trim(); if(!t) return;
    try{
      await API.wake(t);
      const now = Math.floor(Date.now()/1000);
      state.items.unshift({ id:'ui-'+now, title:'Wake', message:t, body:t, source:'ui', created_at: now });
      renderFeed(state.items);
      toast('Wake sent'); els.wakeText.value=''; els.compose.classList.remove('open');
      setTimeout(()=> load(state.items[0]?.id), 1000);
    }catch{}
  });

  // Settings drawer
  els.settingsBtn?.addEventListener('click', ()=> els.drawer.classList.add('open'));
  els.drawerClose?.addEventListener('click', ()=> els.drawer.classList.remove('open'));
  els.dtabs.forEach(b=> b.addEventListener('click', ()=>{
    els.dtabs.forEach(x=>x.classList.remove('active')); b.classList.add('active');
    $$('.pane').forEach(p=> p.classList.remove('show'));
    $(`.pane[data-pane="${b.dataset.pane}"]`)?.classList.add('show');
  }));

  // Retention/Purge
  els.saveRetention?.addEventListener('click', async()=>{
    const d = parseInt(els.retention.value,10)||30;
    await API.setRetention(d); toast('Retention saved');
  });
  els.purge?.addEventListener('click', async()=>{
    let v = els.purgeDays.value; if(v==='custom'){ const s=prompt('Days to purge older than?', '30'); if(!s) return; v=s; }
    const d = parseInt(v,10)||30;
    if(!confirm(`Purge messages older than ${d} days?`)) return;
    await API.purge(d); toast('Purge started'); load();
  });

  // Channel tests (optional)
  $('#test-email')?.addEventListener('click', ()=> API.test('email').then(()=>toast('Email test sent')).catch(()=>toast('Email test failed')));
  $('#test-gotify')?.addEventListener('click', ()=> API.test('gotify').then(()=>toast('Gotify test sent')).catch(()=>toast('Gotify test failed')));
  $('#test-ntfy')?.addEventListener('click', ()=> API.test('ntfy').then(()=>toast('ntfy test sent')).catch(()=>toast('ntfy test failed')));

  $('#save-channels')?.addEventListener('click', async()=>{
    const payload = {
      smtp:{ host:$('#smtp-host').value, port:$('#smtp-port').value, tls:$('#smtp-tls').checked, user:$('#smtp-user').value, pass:$('#smtp-pass').value, from:$('#smtp-from').value },
      gotify:{ url:$('#gotify-url').value, token:$('#gotify-token').value, priority:$('#gotify-priority').value, click:$('#gotify-click').value },
      ntfy:{ url:$('#ntfy-url').value, topic:$('#ntfy-topic').value, tags:$('#ntfy-tags').value, priority:$('#ntfy-priority').value }
    };
    try{ await API.saveChannels(payload); toast('Channels saved'); }catch{ toast('Save failed'); }
  });

  $('#save-routing')?.addEventListener('click', async()=>{
    try{ await API.saveRouting({}); toast('Routing saved'); }catch{ toast('Save failed'); }
  });

  $('#save-quiet')?.addEventListener('click', async()=>{
    try{
      await API.saveQuiet({ tz: $('#qh-tz').value, start: $('#qh-start').value, end: $('#qh-end').value, allow_critical: $('#qh-allow-critical').checked });
      toast('Quiet hours saved');
    }catch{ toast('Save failed'); }
  });

  $('#save-personas')?.addEventListener('click', async()=>{
    try{
      await API.savePersonas({ dude: $('#p-dude').checked, chick: $('#p-chick').checked, nerd: $('#p-nerd').checked, rager: $('#p-rager').checked });
      toast('Personas saved');
    }catch{ toast('Save failed'); }
  });

  // Keyboard niceties
  document.addEventListener('keydown', (e)=>{
    if(e.key==='/' && document.activeElement!==$('#q')){ e.preventDefault(); $('#q')?.focus(); }
    if(e.key==='r'){ load(state.active); }
    if(e.key==='Delete' && state.active){
      if(confirm('Delete this message?'))
        API.del(state.active).then(()=>{ toast('Deleted'); load(); });
    }
    if(e.key==='a' && state.active){
      API.setArchived(state.active, true).then(()=>{ toast('Archived'); load(state.active); });
    }
  });

  // Boot
  (async()=>{
    try{
      const s=await API.getSettings();
      if(s && s.retention_days){
        els.retention.value=String(s.retention_days);
        els.purgeDays.value=els.retention.value;
      }
    }catch{}
  })()
  .then(()=> load())
  .catch(()=>{});
  startLive();
})();
