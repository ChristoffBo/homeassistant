(function(){
  const $  = s => document.querySelector(s);
  const $$ = s => document.querySelectorAll(s);

  /* ---------- API helpers ---------- */
  function apiRoot(){
    if (window.JARVIS_API_BASE) return String(window.JARVIS_API_BASE).replace(/\/?$/, '/');
    try{
      const u = new URL(document.baseURI);
      let p = u.pathname;
      if (p.endsWith('/index.html')) p = p.slice(0, -'/index.html'.length);
      if (p.endsWith('/ui/'))      p = p.slice(0, -4);
      if (!p.endsWith('/'))        p += '/';
      u.pathname = p;
      return u.toString();
    }catch{ return document.baseURI; }
  }
  const ROOT = apiRoot();
  const API  = path => new URL(String(path).replace(/^\/+/, ''), ROOT).toString();

  function toast(msg){
    const d=document.createElement('div');
    d.className='toast'; d.textContent=msg;
    $('#toast').appendChild(d);
    setTimeout(()=>d.remove(),3500);
  }
  async function jfetch(url, opts){
    const r = await fetch(url, opts);
    if(!r.ok){
      let t=''; try{ t = await r.text(); }catch{}
      throw new Error(r.status+' '+r.statusText+' @ '+url+'\n'+t);
    }
    const ct = r.headers.get('content-type')||'';
    return ct.includes('application/json') ? r.json() : r.text();
  }

  /* ---------- Tabs ---------- */
  $$('.tablink').forEach(b=>b.addEventListener('click',()=>{
    $$('.tablink').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
    $$('.tab').forEach(t=>t.classList.remove('active'));
    $('#'+b.dataset.tab).classList.add('active');
  }));

  /* =====================================================
   * Inbox with Message Preview
   * ===================================================*/
  function fmt(ts){
    try{
      const v = Number(ts||0);
      const ms = v > 1e12 ? v : v * 1000;
      return new Date(ms).toLocaleString();
    }catch{ return ''; }
  }
  function updateCounters(items){
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()/1000;
    const today    = items.filter(i => (i.created_at||0) >= start).length;
    const archived = items.filter(i => i.saved).length;
    const errors   = items.filter(i => /error|fail|exception/i.test(`${i.title||''} ${i.body||i.message||''}`)).length;
    $('#msg-today').textContent = today;
    $('#msg-arch').textContent  = archived;
    $('#msg-err').textContent   = errors;
  }
  async function loadInbox(){
    const tb = $('#msg-body');
    try{
      const data = await jfetch(API('api/messages'));
      const items = data && data.items ? data.items : (Array.isArray(data) ? data : []);
      tb.innerHTML = '';
      if(!items.length){
        tb.innerHTML = '<tr><td colspan="4">No messages</td></tr>';
        updateCounters([]);
        return;
      }
      updateCounters(items);
      for(const m of items){
        const tr=document.createElement('tr');
        tr.className='clickable';
        tr.dataset.id = m.id;
        tr.innerHTML = `
          <td>${fmt(m.created_at)}</td>
          <td>${m.source||''}</td>
          <td>${m.title||''}</td>
          <td>
            <button class="btn" data-id="${m.id}" data-act="arch">${m.saved?'Unarchive':'Archive'}</button>
            <button class="btn danger" data-id="${m.id}" data-act="del">Delete</button>
          </td>`;
        tb.appendChild(tr);
      }
    }catch(e){
      console.error(e);
      tb.innerHTML = '<tr><td colspan="4">Failed to load</td></tr>';
      toast('Inbox load error');
    }
  }
  // Row click → preview
  $('#msg-body').addEventListener('click', async (e)=>{
    const btn = e.target.closest('button[data-act]');
    if(btn){
      const id = btn.dataset.id, act = btn.dataset.act;
      try{
        if(act==='del'){
          if(!confirm('Delete this message?')) return;
          await jfetch(API('api/messages/'+id), {method:'DELETE'});
          toast('Deleted'); hidePreview();
        }else if(act==='arch'){
          await jfetch(API(`api/messages/${id}/save`), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({})});
          toast('Toggled archive');
        }
        await loadInbox();
      }catch{ toast('Action failed'); }
      return;
    }
    const row = e.target.closest('tr.clickable');
    if(!row) return;
    const id = row.dataset.id;
    try{
      const m = await jfetch(API('api/messages/'+id));
      showPreview(m);
    }catch{
      toast('Preview failed');
    }
  });
  function showPreview(m){
    $('#pv-title').textContent  = m?.title || '(no title)';
    $('#pv-source').textContent = m?.source || '';
    $('#pv-time').textContent   = fmt(m?.created_at);
    const body = String(m?.html || m?.body || m?.message || '');
    const el = $('#pv-body');
    // Safe-ish render: if looks like HTML, render; else text
    if(/<\/?[a-z][\s\S]*>/i.test(body)){
      el.innerHTML = body;
    }else{
      el.textContent = body;
    }
    $('#preview').classList.remove('hidden');
  }
  function hidePreview(){ $('#preview').classList.add('hidden'); $('#pv-body').innerHTML=''; }
  $('#pv-close').addEventListener('click', hidePreview);

  // Delete all
  $('#del-all').addEventListener('click', async()=>{
    if(!confirm('Delete ALL messages?')) return;
    const keep = $('#keep-arch')?.checked ? 1 : 0;
    try{
      await jfetch(API(`api/messages?keep_saved=${keep}`), {method:'DELETE'});
      toast('All deleted');
      hidePreview();
      await loadInbox();
    }catch{ toast('Delete all failed'); }
  });

  // SSE stream
  (function startStream(){
    let es=null, backoff=1000;
    function connect(){
      try{ es && es.close(); }catch{}
      es = new EventSource(API('api/stream'));
      es.onopen = ()=> backoff = 1000;
      es.onerror = ()=>{ try{es.close();}catch{}; setTimeout(connect, Math.min(backoff, 15000)); backoff = Math.min(backoff*2, 15000); };
      es.onmessage = (ev)=>{
        try{
          const data = JSON.parse(ev.data||'{}');
          if(['created','deleted','deleted_all','saved','purged'].includes(data.event)){
            loadInbox();
          }
        }catch{}
      };
    }
    connect();
    setInterval(loadInbox, 300000);
  })();

  /* =====================================================
   * Unified Options wiring
   * ===================================================*/
  let OPTS = null, SCHEMA = null;
  async function refreshOptions(){
    try{
      [OPTS, SCHEMA] = await Promise.all([
        jfetch(API('api/options')),
        jfetch(API('api/schema'))
      ]);
      if (!OPTS) OPTS = {};
      if (!SCHEMA) SCHEMA = {};
      hydrateAllTabs();
    }catch(e){
      console.error(e);
      $('#opts-wrap').innerHTML = '<div class="toast">Failed to load options/schema</div>';
    }
  }
  function setField(el, key){
    const v = OPTS?.[key];
    if(el.type === 'checkbox') el.checked = !!v;
    else if(el.tagName === 'TEXTAREA') el.value = v ?? '';
    else el.value = (v ?? '');
  }
  function collectAndSave(selector, keys){
    return async function(){
      try{
        const payload = {};
        (keys || Array.from(document.querySelectorAll(selector))).forEach(el => {
          const key = el.dataset.opt || el;
          const node = typeof el === 'string' ? document.querySelector(`[data-opt="${el}"]`) : el;
          if (!node) return;
          if (node.type === 'checkbox') payload[key] = !!node.checked;
          else if (node.tagName === 'TEXTAREA') payload[key] = node.value;
          else if (node.type === 'number') payload[key] = node.value==='' ? '' : (String(node.value).includes('.') ? parseFloat(node.value) : parseInt(node.value,10));
          else payload[key] = node.value;
        });
        await jfetch(API('api/options'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
        toast('Saved');
      }catch(e){ toast('Save failed'); }
    }
  }

  /* Personas tab */
  function hydratePersonas(){
    $$('#personas [data-opt]').forEach(el => setField(el, el.dataset.opt));
  }
  $('#save-persona-opts').addEventListener('click', collectAndSave('#personas [data-opt]'));

  /* Intakes tab */
  function hydrateIntakes(){
    $$('#intakes [data-opt]').forEach(el => setField(el, el.dataset.opt));
  }
  $('#save-intakes').addEventListener('click', collectAndSave('#intakes [data-opt]'));

  /* Outputs tab */
  function hydrateOutputs(){
    $$('#outputs [data-opt]').forEach(el => setField(el, el.dataset.opt));
  }
  $('#save-outputs').addEventListener('click', collectAndSave('#outputs [data-opt]'));

  /* Settings tab */
  function hydrateSettings(){
    $$('#settings [data-opt]').forEach(el => setField(el, el.dataset.opt));
  }
  $('#save-settings').addEventListener('click', collectAndSave('#settings [data-opt]'));
  $('#purge').addEventListener('click', async()=>{
    if(!confirm('Run purge now?')) return;
    try{
      const days = parseInt(OPTS?.retention_days||'0',10) || 0;
      await jfetch(API('api/inbox/purge'), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ days })});
      toast('Purge started');
    }catch{ toast('Purge failed'); }
  });
  // Quiet Hours separate endpoints if available (kept from previous build)
  $('#save-quiet').addEventListener('click', async()=>{
    try{
      await jfetch(API('api/notify/quiet'), {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          tz: $('#qh-tz').value,
          start: $('#qh-start').value,
          end: $('#qh-end').value,
          allow_critical: $('#qh-allow-critical').checked
        })
      });
      toast('Quiet hours saved');
    }catch{ toast('Save failed'); }
  });

  /* LLM tab */
  function hydrateLLM(){
    $$('#llm [data-opt]').forEach(el => setField(el, el.dataset.opt));
  }
  $('#save-llm').addEventListener('click', collectAndSave('#llm [data-opt]'));

  /* EnviroGuard tab */
  function hydrateEnv(){ $$('#enviro [data-opt]').forEach(el => setField(el, el.dataset.opt)); }
  $('#save-env').addEventListener('click', collectAndSave('#enviro [data-opt]'));

  /* Options (All) dynamic */
  function guessWidget(key, type, val){
    const lower = key.toLowerCase();
    if (type && (type.startsWith('int') || type==='float')) return `<input type="number" data-key="${key}" value="${val ?? ''}">`;
    if (type==='bool') return `<label class="lbl"><input type="checkbox" data-key="${key}" ${val ? 'checked':''}/> ${key}</label>`;
    if ((typeof val==='string' && val.length>80) || /_map$|_profiles$|_times$/.test(lower)) {
      return `<textarea data-key="${key}">${val ?? ''}</textarea>`;
    }
    return `<input type="text" data-key="${key}" value="${val ?? ''}">`;
  }
  function renderOptions(options, schema){
    const wrap = $('#opts-wrap');
    wrap.innerHTML = '';
    const groups = { core:[], io:[], llm:[], services:[], env:[], misc:[] };
    Object.keys(options||{}).forEach(k=>{
      const t = (schema && schema[k]) ? String(schema[k]) : 'str';
      const v = options[k];
      const row = `<div class="opt-row">${guessWidget(k, t, v)}</div>`;
      if (/^(bot_|jarvis_|beautify_|greeting_|chat_|personality_|active_persona|cache_refresh|heartbeat_)/.test(k)) groups.core.push(row);
      else if (/^(gotify_|ntfy_|push_|ingest_|smtp_|proxy_|webhook_|intake_)/.test(k)) groups.io.push(row);
      else if (/^llm_/.test(k) || /^(tinyllama|llama32_)/.test(k)) groups.llm.push(row);
      else if (/^(radarr_|sonarr_|technitium_|uptimekuma_)/.test(k)) groups.services.push(row);
      else if (/^weather_/.test(k)) groups.env.push(row);
      else groups.misc.push(row);
    });
    function section(title, rows){ return `<fieldset><legend>${title}</legend><div class="grid-auto">${rows.join('')}</div></fieldset>`; }
    wrap.innerHTML = section('Core', groups.core)+section('I/O & Channels', groups.io)+section('LLM', groups.llm)+section('Services', groups.services)+section('Environment / Weather', groups.env)+section('Misc', groups.misc);
  }
  $('#save-options').addEventListener('click', async()=>{
    try{
      const fields = Array.from($('#opts-wrap').querySelectorAll('[data-key]'));
      const payload = {};
      for(const el of fields){
        const key = el.dataset.key;
        if (el.type === 'checkbox') payload[key] = !!el.checked;
        else if (el.tagName === 'TEXTAREA') payload[key] = el.value;
        else if (el.type === 'number') payload[key] = el.value==='' ? '' : (String(el.value).includes('.') ? parseFloat(el.value) : parseInt(el.value,10));
        else payload[key] = el.value;
      }
      await jfetch(API('api/options'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
      toast('Options saved');
      await refreshOptions();
    }catch(e){ toast('Save failed'); }
  });

  function hydrateAllTabs(){
    hydratePersonas();
    hydrateIntakes();
    hydrateOutputs();
    hydrateSettings();
    hydrateLLM();
    hydrateEnv();
    renderOptions(OPTS, SCHEMA);
    // About version (best-effort)
    $('#about-ver').textContent = OPTS?.version || '1.x';
  }

  /* Boot */
  (async function boot(){
    await loadInbox();
    await refreshOptions();
    // About (try /api/version for exact string)
    try{
      const ver = await jfetch(API('api/version'));
      if (typeof ver === 'string') $('#about-ver').textContent = ver;
      else if (ver?.version) $('#about-ver').textContent = ver.version;
    }catch{}
  })();
})();