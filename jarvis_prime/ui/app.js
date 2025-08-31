// Jarvis v4.7 — Ingress '/ui/' root fix + diagnostics
(function(){
  const $ = (s, r=document) => r.querySelector(s);
  const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));

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

  const els = {
    feed: $('#feed'), detail: $('#detail'),
    q: $('#q'), limit: $('#limit'),
    search: $('#btn-search'), refresh: $('#btn-refresh'),
    retention: $('#retention'), saveRetention: $('#btn-save-retention'),
    purgeDays: $('#purge-days'), purge: $('#btn-purge'),
    delAll: $('#btn-delall'), keepArch: $('#keep-arch'),
    live: $('#live-badge'),
    wakeText: $('#wake-text'), wakeSend: $('#wake-send'),
    chips: $$('.chips .chip'),
    railTabs: $$('.tabs .tab'), rail: $('#rail'),
    srcChips: $$('.sources .chip'),
    toast: $('#toast'),
    counts: { all: $('#c-all'), unread: $('#c-unread'), arch: $('#c-arch'), smtp: $('#c-smtp'), gotify: $('#c-gotify'), ui: $('#c-ui') },
    chime: $('#chime'), ding: $('#ding')
  };

  function toast(msg){ const d=document.createElement('div'); d.className='toast'; d.textContent=msg; els.toast.appendChild(d); setTimeout(()=> d.remove(), 3500); }
  const esc = s => String(s||'').replace(/[&<>"']/g, m=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m]));
  const fmt = (ts) => { try { const v=Number(ts||0); const ms = v>1e12 ? v : v*1000; return new Date(ms).toLocaleString(); } catch { return '' } };

  async function jfetch(url, opts){
    const isTemp = /\/api\/messages\/ui-\d+$/.test(String(url));
    try{
      const r = await fetch(url, opts);
      if(!r.ok){
        const t = await r.text().catch(()=>'');
        if(!(isTemp && r.status===404)) throw new Error(r.status+' '+r.statusText+' @ '+url+'\n'+t); else return Promise.reject(new Error('temp-404'));
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
    async wake(text){ return jfetch(u('api/wake'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text: 'Jarvis ' + text})}); }
  };

  const state = { items: [], active: null, tab: 'all', source: '', newestSeen: 0 };

  const byId = new Map();
  function indexItems(items){ byId.clear(); for(const it of items){ byId.set(String(it.id), it); } }
  let lastTop = null, lastCount = 0;


  function counts(items){
    const c = { all:items.length, unread:0, arch:0, smtp:0, gotify:0, ui:0 };
    for(const it of items){
      if(it.saved) c.arch++;
      const src=(it.source||'').toLowerCase(); if(c[src]!=null) c[src]++;
      if(state.newestSeen && it.created_at>state.newestSeen) c.unread++;
    }
    for(const k of Object.keys(c)){ if(els.counts[k]) els.counts[k].textContent = c[k]; }
  }

  function filtered(items){
    let arr = items.slice();
    if(state.tab==='archived') arr = arr.filter(i=>i.saved);
    if(state.tab==='errors') arr = arr.filter(i=>/error|fail|exception/i.test((i.title||'') + ' ' + (i.body||i.message||'')));
    if(state.tab==='unread') arr = arr.filter(i=>state.newestSeen && i.created_at>state.newestSeen);
    if(state.source) arr = arr.filter(i=>(i.source||'').toLowerCase()===state.source);
    return arr;
  }

  function renderFeed(items){
    const list = filtered(items);
    const root = els.feed; root.innerHTML='';
    if(!list.length){ root.innerHTML = '<div class="toast">No messages</div>'; return; }
    for(const it of list){
      const c=document.createElement('div'); c.className='card'; c.dataset.id=it.id;
      const isNew = state.newestSeen && it.created_at>state.newestSeen;
      if(isNew) c.classList.add('new');
      c.innerHTML = `<div><div class="title">${esc(it.title||'(no title)')}</div>
        <div class="meta">${fmt(it.created_at)} • <span class="src">${esc(it.source||'?')}</span>${it.saved?' • Archived':''}</div></div>
        <div class="meta">#${it.id}</div>`;
      c.addEventListener('click', ()=> select(it.id));
      root.appendChild(c);
    }
  }

  async function renderDetail(it){
    els.detail.innerHTML='';
    const w = document.createElement('div'); w.className='wrap';
    const badges = [];
    if(it.source) badges.push(`<span class="badge">Source: ${esc(it.source)}</span>`);
    if(it.created_at) badges.push(`<span class="badge">${fmt(it.created_at)}</span>`);
    w.innerHTML = `<h2>${esc(it.title||'(no title)')}</h2>
      <div class="badges">${badges.join(' ')}</div>
      <div class="body">${esc((it.body||it.message||'').trim())}</div>
      <div class="actions">
        <button id="a-arch" class="btn">${it.saved?'Unarchive':'Archive'}</button>
        <button id="a-copy" class="btn">Copy</button>
        <button id="a-del" class="btn danger">Delete</button>
        <span class="kbd">a</span><span class="kbd">Del</span>
      </div>`;
    els.detail.appendChild(w);
    $('#a-copy').addEventListener('click', ()=>navigator.clipboard.writeText(`${it.title||''}\n\n${it.body||it.message||''}`));
    $('#a-del').addEventListener('click', async()=>{ if(!confirm('Delete this message?')) return; await API.del(it.id); toast('Deleted'); load(); });
    $('#a-arch').addEventListener('click', async()=>{ await API.setArchived(it.id,!it.saved); toast(it.saved?'Unarchived':'Archived'); load(it.id); });
  }

  async function select(id){
    state.active = id;
    if(String(id).startsWith('ui-')){
      const temp = byId.get(String(id));
      if(temp) return renderDetail(temp);
    }
    try{
      const it = await API.get(id);
      renderDetail(it);
    }catch(e){ /* suppress 404 toast here; jfetch already notified */ }
  }

  async function load(selectId=null){
    const items = await API.list($('#q')?.value?.trim()||'', parseInt(els.limit.value,10)||50, 0);
    if(!state.newestSeen && items[0]) state.newestSeen = items[0].created_at || 0;
    const top = items[0]?.id || null; const cnt = items.length;
    state.items = items; indexItems(items);
    counts(items);
    if(top!==lastTop || cnt!==lastCount){ renderFeed(items); lastTop = top; lastCount = cnt; }
    if(selectId && items.find(i=>String(i.id)===String(selectId))) select(selectId);
    else if(!state.active && items[0]) select(items[0].id);
  }

  async function loadSettings(){
    try{ const s=await API.getSettings(); if(s && s.retention_days) els.retention.value=String(s.retention_days); els.purgeDays.value=els.retention.value; }catch(e){}
  }

  function startLive(){
    try{
      const src = new EventSource(u('api/stream'));
      src.onopen = ()=>{ els.live.textContent='LIVE'; els.live.classList.remove('err'); els.live.classList.add('ok'); };
      src.onerror = ()=>{ els.live.textContent='OFFLINE'; els.live.classList.remove('ok'); els.live.classList.add('err'); };
      src.onmessage = (e)=>{
        try{
          const data = JSON.parse(e.data||'{}');
          if(['created','deleted','deleted_all','saved','purged'].includes(data.event)){
            if(els.chime?.checked) try{ els.ding.currentTime=0; els.ding.play(); }catch{}
            load(state.active);
          }
        }catch{}
      };
    }catch(e){ console.warn('SSE failed:', e); }
    setInterval(()=> load(state.active), 2000);
  }

  // Events
  $('#btn-refresh')?.addEventListener('click', ()=> load(state.active));
  $('#btn-search')?.addEventListener('click', ()=> load());
  els.limit?.addEventListener('change', ()=> load());
  $('#q')?.addEventListener('keydown', e=>{ if(e.key==='Enter') load(); });
  $$('.tabs .tab').forEach(t=> t.addEventListener('click', ()=>{
    $$('.tabs .tab').forEach(x=>x.classList.remove('active')); t.classList.add('active');
    state.tab = t.dataset.tab; renderFeed(state.items);
  }));
  els.srcChips.forEach(c=> c.addEventListener('click', ()=>{
    els.srcChips.forEach(x=>x.classList.remove('active'));
    c.classList.add('active'); state.source = c.dataset.src || ''; renderFeed(state.items);
  }));

  $('#btn-save-retention')?.addEventListener('click', async()=>{ const d=parseInt(els.retention.value,10)||30; await API.setRetention(d); toast('Retention saved'); });
  $('#btn-purge')?.addEventListener('click', async()=>{
    let v=els.purgeDays.value; if(v==='custom'){ const s=prompt('Days to purge older than?', '30'); if(!s) return; v=s; }
    const d=parseInt(v,10)||30; if(!confirm(`Purge messages older than ${d} days?`)) return; await API.purge(d); toast('Purge started'); load();
  });
  $('#btn-delall')?.addEventListener('click', async()=>{ if(!confirm('Delete ALL messages?')) return; await API.deleteAll(els.keepArch.checked); toast('All deleted'); load(); });

  // Wake
  $('#wake-send')?.addEventListener('click', async()=>{
    const t = els.wakeText.value.trim(); if(!t) return;
    try{
      await API.wake(t);
      const now = Math.floor(Date.now()/1000);
      const temp = { id:'ui-'+now, title:'Wake', message:t, body:t, source:'ui', created_at: now };
      state.items.unshift(temp); lastTop = null; lastCount = 0; renderFeed(state.items); /* keep selection */
      toast('Wake sent'); els.wakeText.value='';
      setTimeout(()=> load(temp.id), 1200);
    }catch{ /* toast shown in jfetch */ }
  });
  els.chips.forEach(ch => ch.addEventListener('click', ()=>{ const v = ch.getAttribute('data-wake'); els.wakeText.value = v; $('#wake-send').click(); }));

  // Keyboard
  document.addEventListener('keydown', (e)=>{
    if(e.key==='/' && document.activeElement!==$('#q')){ e.preventDefault(); $('#q')?.focus(); }
    if(e.key==='r'){ load(state.active); }
    if(e.key==='a' && state.active){ API.setArchived(state.active, true).then(()=>{ toast('Archived'); load(state.active); }); }
    if(e.key==='Delete' && state.active){ if(confirm('Delete this message?')) API.del(state.active).then(()=>{ toast('Deleted'); load(); }); }
  });

  // Boot
  console.log('[Jarvis UI] BASE =', document.baseURI);
  console.log('[Jarvis UI] ROOT =', ROOT);
  loadSettings().then(()=> load()).catch(()=>{});
  startLive();
})();
