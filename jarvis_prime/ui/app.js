// Jarvis UI v2 - desktop + Android friendly
(function(){
  const $ = (sel, root=document) => root.querySelector(sel);
  const $$ = (sel, root=document) => Array.from(root.querySelectorAll(sel));

  // Elements
  const msgList = $('#msgList');
  const nowCard = $('#nowCard');
  const favBtn = $('#favBtn');
  const delBtn = $('#delBtn');
  const copyBtn = $('#copyBtn');
  const liveBadge = $('#liveBadge');
  const unreadCount = $('#unreadCount');
  const wakeInput = $('#wakeInput');
  const wakeSend = $('#wakeSend');
  const savedToggle = $('#savedToggle');
  const unreadToggle = $('#unreadToggle');
  const searchBox = $('#searchBox');
  const purgeBtn = $('#purgeBtn');
  const purgeDays = $('#purgeDays');
  const retentionDays = $('#retentionDays');
  const saveRetention = $('#saveRetention');
  const keepFavs = $('#keepFavs');
  const deleteAllBtn = $('#deleteAll');
  const statusText = $('#statusText');

  // State
  let messages = [];
  let filtered = [];
  let selectedId = null;
  let unread = new Set();
  let stream;

  const fmt = (ts) => {
    try{
      const d = new Date(ts || Date.now());
      return d.toLocaleString();
    }catch(e){ return ''}
  };

  function setStatus(t){ statusText.textContent = t; }

  function renderList(){
    msgList.innerHTML = '';
    filtered.forEach(it => {
      const node = $('#msgItemTpl').content.firstElementChild.cloneNode(true);
      node.dataset.id = it.id;
      const star = $('.star', node);
      const ttl = $('.title', node);
      const prev = $('.preview', node);
      const ts = $('.ts', node);

      star.classList.toggle('active', !!it.saved);
      ttl.textContent = it.title || (it.extras && it.extras.source) || 'Message';
      prev.textContent = it.message || '';
      ts.textContent = fmt(it.created_at);

      star.addEventListener('click', async (ev)=>{
        ev.stopPropagation();
        await toggleSave(it);
      });

      node.addEventListener('click', ()=> select(it.id));

      msgList.appendChild(node);
    });
    unreadCount.textContent = String(unread.size);
  }

  function renderNow(it){
    if(!it){
      nowCard.classList.add('empty');
      nowCard.innerHTML = '<div class="empty-text">No messages yet.</div>';
      [favBtn, delBtn, copyBtn].forEach(b=>b.disabled = true);
      return;
    }
    nowCard.classList.remove('empty');
    nowCard.innerHTML = `
      <h2>${escapeHtml(it.title || 'Message')}</h2>
      <div class="subtitle">${fmt(it.created_at)} ${it.extras && it.extras.via ? '· '+escapeHtml(it.extras.via): ''}</div>
      <div class="body">${escapeHtml(it.message || '')}</div>
    `;
    favBtn.disabled = delBtn.disabled = copyBtn.disabled = false;
    favBtn.textContent = it.saved ? '★ Saved' : '☆ Save';
  }

  function escapeHtml(s){return String(s).replace(/[&<>"']/g, m=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m]))}

  function applyFilters(){
    const q = searchBox.value.trim().toLowerCase();
    filtered = messages.filter(m => {
      if(savedToggle.getAttribute('aria-pressed')==='true' && !m.saved) return false;
      if(unreadToggle.getAttribute('aria-pressed')==='true' && !unread.has(m.id)) return false;
      if(q && !(String(m.title||'').toLowerCase().includes(q) || String(m.message||'').toLowerCase().includes(q))) return false;
      return true;
    });
    renderList();
  }

  function upsert(msg, makeUnread=true){
    const i = messages.findIndex(x=>x.id===msg.id);
    if(i>=0) messages[i]=msg; else messages.unshift(msg);
    if(makeUnread) unread.add(msg.id);
    applyFilters();
    if(!selectedId) select(msg.id);
  }

  function select(id){
    selectedId = id;
    const it = messages.find(m=>m.id===id);
    if(it){ unread.delete(id); renderNow(it); applyFilters(); }
  }

  async function fetchMessages(){
    setStatus('Loading…');
    const r = await fetch('/api/messages?limit=200');
    const js = await r.json();
    messages = (js.items||js||[]).map(mapBackend);
    filtered = messages.slice();
    renderList();
    renderNow(messages[0]);
    setStatus('Ready.');
  }

  function mapBackend(o){
    // Normalize different field spellings safely
    return {
      id: o.id || o._id || o.uuid,
      title: o.title || o.topic || '',
      message: o.message || o.text || '',
      created_at: o.created_at || o.ts || o.timestamp || Date.now(),
      saved: !!(o.saved || o.favorite || o.favourite),
      extras: o.extras || o.meta || {}
    };
  }

  async function toggleSave(it){
    const want = !it.saved;
    const r = await fetch(`/api/messages/${encodeURIComponent(it.id)}/save`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ saved: want })
    });
    if(!r.ok){ setStatus('Save failed'); return; }
    it.saved = want;
    if(selectedId===it.id) renderNow(it);
    applyFilters();
  }

  async function delSelected(){
    if(!selectedId) return;
    const id = selectedId;
    if(!confirm('Delete this message?')) return;
    const r = await fetch(`/api/messages/${encodeURIComponent(id)}`, {method:'DELETE'});
    if(r.ok){
      messages = messages.filter(m=>m.id!==id);
      selectedId = null;
      applyFilters();
      renderNow(messages[0]);
    }else setStatus('Delete failed');
  }

  async function deleteAll(){
    if(!confirm('Delete ALL messages?')) return;
    const keep = keepFavs.checked ? 1 : 0;
    const r = await fetch(`/api/messages?keep_saved=${keep}`, {method:'DELETE'});
    if(r.ok){
      messages = [];
      filtered = [];
      selectedId = null;
      renderList(); renderNow(null);
    }else setStatus('Delete all failed');
  }

  async function doPurge(){
    let days = purgeDays.value;
    if(days==='custom'){
      const val = prompt('Purge messages older than how many days?', '30');
      if(!val) return;
      days = parseInt(val,10);
      if(!Number.isFinite(days) || days<=0){ alert('Invalid number'); return; }
    }else{
      days = parseInt(days,10);
    }
    const r = await fetch('/api/inbox/purge', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ days })
    });
    if(r.ok){ setStatus('Purge started'); } else setStatus('Purge failed');
  }

  async function saveRet(){
    const days = parseInt(retentionDays.value,10);
    const r = await fetch('/api/inbox/settings', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ retention_days: days })
    });
    setStatus(r.ok ? 'Retention saved' : 'Retention failed');
  }

  async function sendWake(){
    const text = wakeInput.value.trim();
    if(!text) return;
    const r = await fetch('/api/wake', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ text })
    });
    if(r.ok){
      wakeInput.value='';
      setStatus('Sent');
    }else setStatus('Send failed');
  }

  function startSSE(){
    try{
      if(stream) stream.close();
      stream = new EventSource('/api/stream');
      stream.onopen = ()=> { liveBadge.classList.remove('err'); liveBadge.classList.add('ok'); };
      stream.onerror = ()=> { liveBadge.classList.remove('ok'); liveBadge.classList.add('err'); };
      stream.onmessage = (e)=>{
        try{
          const data = JSON.parse(e.data);
          const msg = mapBackend(data);
          upsert(msg, true);
        }catch(err){ console.error('SSE parse', err); }
      };
    }catch(e){ console.warn('SSE not available', e); }
  }

  // Events
  savedToggle.addEventListener('click', ()=>{
    const p = savedToggle.getAttribute('aria-pressed')==='true' ? 'false':'true';
    savedToggle.setAttribute('aria-pressed', p);
    applyFilters();
  });
  unreadToggle.addEventListener('click', ()=>{
    const p = unreadToggle.getAttribute('aria-pressed')==='true' ? 'false':'true';
    unreadToggle.setAttribute('aria-pressed', p);
    applyFilters();
  });
  searchBox.addEventListener('input', applyFilters);
  purgeBtn.addEventListener('click', doPurge);
  saveRetention.addEventListener('click', saveRet);
  deleteAllBtn.addEventListener('click', deleteAll);
  delBtn.addEventListener('click', delSelected);
  favBtn.addEventListener('click', ()=>{
    const it = messages.find(m=>m.id===selectedId); if(it) toggleSave(it);
  });
  copyBtn.addEventListener('click', async ()=>{
    const it = messages.find(m=>m.id===selectedId);
    if(!it) return;
    try{
      await navigator.clipboard.writeText(it.message||'');
      setStatus('Copied');
    }catch{ setStatus('Copy failed');}
  });
  wakeSend.addEventListener('click', sendWake);
  wakeInput.addEventListener('keydown', (e)=>{ if(e.key==='Enter') sendWake(); });

  // Init
  fetchMessages();
  startSSE();
})();
