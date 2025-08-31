// Jarvis Prime Inbox UI — API client + renderer (+ wake + auto-refresh + delete-all)
const API = {
  async list(q, limit=50, offset=0){
    const url = new URL('/api/messages', location.origin);
    if(q) url.searchParams.set('q', q);
    url.searchParams.set('limit', limit);
    url.searchParams.set('offset', offset);
    const r = await fetch(url); if(!r.ok) throw new Error('Failed to list messages');
    return (await r.json()).items || [];
  },
  async get(id){
    const r = await fetch(`/api/messages/${id}`);
    if(!r.ok) throw new Error('Message not found');
    return await r.json();
  },
  async del(id){
    const r = await fetch(`/api/messages/${id}`, { method:'DELETE' });
    if(!r.ok) throw new Error('Delete failed');
    return await r.json();
  },
  async read(id, read=true){
    const r = await fetch(`/api/messages/${id}/read`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({read})
    });
    if(!r.ok) throw new Error('Read toggle failed');
    return await r.json();
  },
  async create({title, body, source='ui', priority=5}){
    const r = await fetch('/api/messages', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({title, body, source, priority})
    });
    if(!r.ok) throw new Error('create failed');
    return await r.json();
  },
  async getSettings(){
    const r = await fetch('/api/inbox/settings'); if(!r.ok) throw new Error('settings');
    return await r.json();
  },
  async setRetention(days){
    // backend expects POST
    const r = await fetch('/api/inbox/settings', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({retention_days: days})
    });
    if(!r.ok) throw new Error('save settings'); return await r.json();
  },
  async purge(days){
    // endpoint is /api/inbox/purge
    const r = await fetch('/api/inbox/purge', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({days})
    });
    if(!r.ok) throw new Error('purge failed'); return await r.json();
  }
};

const els = {
  list: document.getElementById('list'),
  preview: document.getElementById('preview'),
  q: document.getElementById('q'),
  limit: document.getElementById('limit'),
  refresh: document.getElementById('btn-refresh'),
  search: document.getElementById('btn-search'),
  retention: document.getElementById('retention'),
  saveRetention: document.getElementById('btn-save-retention'),
  purgeDays: document.getElementById('purge-days'),
  purge: document.getElementById('btn-purge'),
  footer: document.getElementById('footer'),
  wakeText: document.getElementById('wake-text'),
  wakeBtn: document.getElementById('btn-wake'),
  deleteAll: document.getElementById('btn-delete-all'),
};

let state = { items:[], activeId:null, timer:null, latestId:null };

function fmtTime(ts){
  try{
    const d = new Date((ts||0)*1000);
    return d.toLocaleString();
  }catch(e){ return ''; }
}

function renderList(items){
  els.list.innerHTML = '';
  if(!items.length){
    els.list.innerHTML = '<div class="item"><div class="title">No messages</div><div class="meta">—</div></div>';
    return;
  }
  for(const it of items){
    const div = document.createElement('div');
    div.className = 'item';
    div.dataset.id = it.id;
    div.innerHTML = `
      <div>
        <div class="title">${escapeHtml(it.title || '(no title)')}</div>
        <div class="meta">${fmtTime(it.ts)} • <span class="source">${escapeHtml(it.source||'?')}</span></div>
      </div>
      <div class="meta">#${it.id}</div>
    `;
    div.addEventListener('click', () => select(it.id));
    els.list.appendChild(div);
  }
}

function escapeHtml(s){
  return (s||'').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

async function select(id){
  state.activeId = id;
  [...els.list.querySelectorAll('.item')].forEach(el => el.classList.toggle('active', el.dataset.id==id));
  const it = await API.get(id);
  renderPreview(it);
}

function renderPreview(it){
  els.preview.innerHTML = '';
  const meta = [];
  if(it.source) meta.push(`<span class="badge">Source: ${escapeHtml(it.source)}</span>`);
  if(it.priority!=null) meta.push(`<span class="badge">Priority: ${it.priority}</span>`);
  if(it.ts) meta.push(`<span class="badge">${fmtTime(it.ts)}</span>`);
  if(it.meta && it.meta.via) meta.push(`<span class="badge">Via: ${escapeHtml(it.meta.via)}</span>`);
  const body = (it.body || it.message || '').trim();

  const root = document.createElement('div');
  root.className = 'detail';
  root.innerHTML = `
    <h2>${escapeHtml(it.title || '(no title)')}</h2>
    <div class="meta">${meta.join(' ')}</div>
    <div class="body">${escapeHtml(body)}</div>
    <div class="row-actions">
      <button id="btn-copy" class="btn">Copy</button>
      <button id="btn-delete" class="btn danger">Delete</button>
    </div>
  `;
  els.preview.appendChild(root);

  root.querySelector('#btn-copy').addEventListener('click', () => {
    const text = `${it.title || ''}

${body}`.trim();
    navigator.clipboard.writeText(text).then(()=>toast('Copied'));
  });
  root.querySelector('#btn-delete').addEventListener('click', async () => {
    if(!confirm('Delete this message?')) return;
    await API.del(it.id);
    toast('Deleted');
    load();
  });
}

function toast(msg){
  els.footer.textContent = msg;
  setTimeout(() => els.footer.textContent = '', 1800);
}

async function load(){
  const q = els.q.value.trim();
  const limit = parseInt(els.limit.value,10)||50;
  const items = await API.list(q, limit, 0);
  const previousTop = state.items[0]?.id;
  state.items = items;
  renderList(items);
  if(items[0]){
    state.latestId = items[0].id;
    if(!state.activeId) select(items[0].id);
  }
  if(previousTop && items[0] && items[0].id !== previousTop){
    toast('New message received');
  }
}

async function sendWake(){
  const phrase = (els.wakeText.value || 'hey jarvis').trim();
  await API.create({title:'Wake', body: phrase, source:'ui', priority: 9});
  els.wakeText.value='';
  toast('Wake sent');
  load();
}

async function deleteAll(){
  if(!confirm('Delete ALL messages? This cannot be undone.')) return;
  // fetch in batches and delete
  let offset = 0;
  const limit = 200;
  while(true){
    const batch = await API.list('', limit, offset);
    if(!batch.length) break;
    for(const it of batch){
      await API.del(it.id);
    }
    if(batch.length < limit) break;
  }
  toast('All messages deleted');
  load();
}

function startAutoRefresh(){
  clearInterval(state.timer);
  state.timer = setInterval(load, 5000); // 5s polling
}

// Events
els.refresh.addEventListener('click', load);
els.search.addEventListener('click', load);
els.limit.addEventListener('change', load);
els.q.addEventListener('keydown', e => { if(e.key==='Enter') load(); });
window.addEventListener('keydown', e => {
  if(e.key==='r') load();
  if(e.key==='w'){ e.preventDefault(); sendWake(); }
  if(e.key==='/'){ e.preventDefault(); els.q.focus(); }
  if(e.key==='Delete' && state.activeId){ API.del(state.activeId).then(load); }
});
els.saveRetention.addEventListener('click', async () => {
  const days = parseInt(els.retention.value,10)||30;
  await API.setRetention(days);
  toast('Retention saved');
});
els.purge.addEventListener('click', async () => {
  const days = parseInt(els.purgeDays.value,10)||30;
  if(!confirm(`Purge messages older than ${days} days?`)) return;
  const res = await API.purge(days);
  toast(`Purged`);
  load();
});
els.wakeBtn.addEventListener('click', sendWake);
els.deleteAll.addEventListener('click', deleteAll);

// boot
load().then(startAutoRefresh);
