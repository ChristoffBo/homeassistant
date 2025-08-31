// Jarvis v3.2 — ingress-safe (strip '/ui'), SSE fixed, delete-all & dropdowns
(function(){
  const $ = (s, r=document) => r.querySelector(s);
  const els = {
    list: $('#list'), preview: $('#preview'),
    q: $('#q'), limit: $('#limit'),
    refresh: $('#btn-refresh'), search: $('#btn-search'),
    savedBtn: $('#btn-saved'),
    retention: $('#retention'), saveRetention: $('#btn-save-retention'),
    purgeDays: $('#purge-days'), purge: $('#btn-purge'),
    delAll: $('#btn-delall'), keepFav: $('#keep-fav'),
    footer: $('#footer'), live: $('#live-badge'),
    wakeText: $('#wake-text'), wakeSend: $('#wake-send')
  };

  // Ingress-aware API root: remove trailing '/ui...' from pathname
  function apiRoot(){
    const {origin, pathname} = location;
    const cut = pathname.split('/ui')[0]; // '/ingress-token' or ''
    const base = cut.endsWith('/') ? cut : cut + '/';
    return origin + base; // ends with '/'
  }
  const root = apiRoot();
  const u = (path) => root + path.replace(/^\/+/, '');

  const API = {
    async list(q, limit=50, offset=0, savedOnly=null){
      const url = new URL(u('api/messages'));
      if(q) url.searchParams.set('q', q);
      url.searchParams.set('limit', limit);
      url.searchParams.set('offset', offset);
      if(savedOnly!==null) url.searchParams.set('saved', savedOnly ? '1':'0');
      const r = await fetch(url); if(!r.ok) throw new Error('list'); return (await r.json()).items || [];
    },
    async get(id){ const r=await fetch(u(`api/messages/${id}`)); if(!r.ok) throw new Error('get'); return r.json(); },
    async del(id){ const r=await fetch(u(`api/messages/${id}`),{method:'DELETE'}); if(!r.ok) throw new Error('del'); return r.json(); },
    async setSaved(id,saved){ const r=await fetch(u(`api/messages/${id}/save`),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({saved})}); if(!r.ok) throw new Error('save'); return r.json(); },
    async getSettings(){ const r=await fetch(u('api/inbox/settings')); if(!r.ok) throw new Error('settings'); return r.json(); },
    async setRetention(days){ const r=await fetch(u('api/inbox/settings'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({retention_days:days})}); if(!r.ok) throw new Error('set'); return r.json(); },
    async purge(days){ const r=await fetch(u('api/inbox/purge'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({days})}); if(!r.ok) throw new Error('purge'); return r.json(); },
    async deleteAll(keep){ const r=await fetch(u(`api/messages?keep_saved=${keep?1:0}`),{method:'DELETE'}); if(!r.ok) throw new Error('delall'); return r.json(); },
    async wake(text){ const r=await fetch(u('api/wake'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})}); if(!r.ok) throw new Error('wake'); return r.json(); }
  };

  let state = { items:[], active:null, savedOnly:false };
  const esc = s => String(s||'').replace(/[&<>"']/g, m=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  function fmt(ts){ try{ const v = Number(ts||0); const ms = v > 1e12 ? v : v*1000; return new Date(ms).toLocaleString(); }catch{ return '' } }

  function renderList(items){
    const root = els.list; root.innerHTML='';
    if(!items.length){ root.innerHTML = '<div class="item"><div class="title">No messages</div><div class="meta">—</div></div>'; return; }
    for(const it of items){
      const div = document.createElement('div'); div.className='item'; div.dataset.id=it.id;
      div.innerHTML = `<div><div class="title">${esc(it.title||'(no title)')}</div><div class="meta">${fmt(it.created_at)} • <span class="source">${esc(it.source||'?')}</span>${it.saved?' • ★':''}</div></div><div class="meta">#${it.id}</div>`;
      div.addEventListener('click', ()=> select(it.id));
      root.appendChild(div);
    }
  }

  async function renderPreview(it){
    els.preview.innerHTML='';
    const meta=[];
    if(it.source) meta.push(`<span class="badge">Source: ${esc(it.source)}</span>`);
    if(it.created_at) meta.push(`<span class="badge">${fmt(it.created_at)}</span>`);
    if(it.extras && it.extras.via) meta.push(`<span class="badge">Via: ${esc(it.extras.via)}</span>`);
    const body=(it.body||it.message||'').trim();
    const root=document.createElement('div'); root.className='detail';
    root.innerHTML = `<h2>${esc(it.title||'(no title)')}</h2><div class="meta">${meta.join(' ')}</div><div class="body">${esc(body)}</div>
      <div class="row-actions">
        <button id="a-save" class="btn">${it.saved?'★ Unsave':'☆ Save'}</button>
        <button id="a-copy" class="btn">Copy</button>
        <button id="a-del" class="btn danger">Delete</button>
      </div>`;
    els.preview.appendChild(root);
    root.querySelector('#a-copy').addEventListener('click', ()=>navigator.clipboard.writeText(`${it.title||''}\n\n${body}`));
    root.querySelector('#a-del').addEventListener('click', async()=>{ if(!confirm('Delete this message?'))return; await API.del(it.id); load(); });
    root.querySelector('#a-save').addEventListener('click', async()=>{ const want=!it.saved; await API.setSaved(it.id,want); load(it.id); });
  }

  async function select(id){ state.active=id; [...els.list.querySelectorAll('.item')].forEach(n=>n.classList.toggle('active', n.dataset.id==id)); const it=await API.get(id); renderPreview(it); }
  async function load(selectId=null){ const q=els.q.value.trim(); const lim=parseInt(els.limit.value,10)||50; const items=await API.list(q,lim,0,state.savedOnly); state.items=items; renderList(items); if(selectId && items.find(i=>i.id===selectId)){ select(selectId); } else if(items[0]) select(items[0].id); else els.preview.innerHTML='<div class="empty"><h2>Welcome 👋</h2><p>No messages found.</p></div>'; }
  async function loadSettings(){ try{ const s=await API.getSettings(); if(s && s.retention_days) els.retention.value=String(s.retention_days); els.purgeDays.value=els.retention.value; }catch{} }

  function startLive(){
    try{
      const src = new EventSource(u('api/stream'));
      src.onopen = ()=> { els.live.classList.remove('err'); els.live.classList.add('ok'); };
      src.onerror = ()=> { els.live.classList.remove('ok'); els.live.classList.add('err'); };
      src.onmessage = (e)=>{
        try{
          const data = JSON.parse(e.data||'{}');
          if(['created','deleted','deleted_all','saved','purged'].includes(data.event)){ load(state.active); }
        }catch{}
      };
    }catch{
      setInterval(()=> load(state.active), 5000);
    }
  }

  // events
  els.refresh.addEventListener('click', ()=>load(state.active));
  els.search.addEventListener('click', ()=>load());
  els.limit.addEventListener('change', ()=>load());
  els.q.addEventListener('keydown', e=>{ if(e.key==='Enter') load(); });
  els.savedBtn.addEventListener('click', ()=>{ state.savedOnly=!state.savedOnly; els.savedBtn.textContent='Saved only: '+(state.savedOnly?'ON':'OFF'); load(state.active); });
  els.saveRetention.addEventListener('click', async()=>{ const d=parseInt(els.retention.value,10)||30; await API.setRetention(d); });
  els.purge.addEventListener('click', async()=>{ let v=els.purgeDays.value; if(v==='custom'){ const s=prompt('Days to purge older than?', '30'); if(!s) return; v=s; } const d=parseInt(v,10)||30; if(!confirm(`Purge messages older than ${d} days?`)) return; await API.purge(d); load(); });
  els.delAll.addEventListener('click', async()=>{ if(!confirm('Delete ALL messages?')) return; await API.deleteAll(els.keepFav.checked); load(); });
  els.wakeSend.addEventListener('click', async()=>{ const t=els.wakeText.value.trim(); if(!t) return; try{ await API.wake(t); els.wakeText.value=''; }catch{} });

  loadSettings().then(()=>load());
  startLive();
})();
