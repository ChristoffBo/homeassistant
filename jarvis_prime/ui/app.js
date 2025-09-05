(function(){
  const $  = s => document.querySelector(s);
  const $$ = s => document.querySelectorAll(s);

  // Robust API base
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

  // Tabs
  $$('.tablink').forEach(b=>b.addEventListener('click',()=>{
    $$('.tablink').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
    $$('.tab').forEach(t=>t.classList.remove('active'));
    $('#'+b.dataset.tab).classList.add('active');
  }));

  /* ---------------- Inbox ---------------- */
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
  $('#msg-body').addEventListener('click', async (e)=>{
    const btn = e.target.closest('button[data-act]');
    if(!btn) return;
    const id = btn.dataset.id;
    const act = btn.dataset.act;
    try{
      if(act==='del'){
        if(!confirm('Delete this message?')) return;
        await jfetch(API('api/messages/'+id), {method:'DELETE'});
        toast('Deleted');
      }else if(act==='arch'){
        await jfetch(API(`api/messages/${id}/save`), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({})});
        toast('Toggled archive');
      }
      await loadInbox();
    }catch{ toast('Action failed'); }
  });
  $('#del-all').addEventListener('click', async()=>{
    if(!confirm('Delete ALL messages?')) return;
    const keep = $('#keep-arch')?.checked ? 1 : 0;
    try{
      await jfetch(API(`api/messages?keep_saved=${keep}`), {method:'DELETE'});
      toast('All deleted');
      await loadInbox();
    }catch{ toast('Delete all failed'); }
  });

  // Live updates via SSE with exponential backoff
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

  /* -------------- Personas -------------- */
  async function loadPersonas(){
    try{
      const p = await jfetch(API('api/notify/personas'));
      $('#p-dude').checked  = !!p?.dude;
      $('#p-chick').checked = !!p?.chick;
      $('#p-nerd').checked  = !!p?.nerd;
      $('#p-rager').checked = !!p?.rager;
    }catch{}
  }
  $('#save-personas').addEventListener('click', async()=>{
    try{
      await jfetch(API('api/notify/personas'), {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          dude: $('#p-dude').checked,
          chick: $('#p-chick').checked,
          nerd: $('#p-nerd').checked,
          rager: $('#p-rager').checked
        })
      });
      toast('Personas saved');
    }catch{ toast('Save failed'); }
  });

  /* --------------- Intakes --------------- */
  async function loadChannels(){
    try{
      const c = await jfetch(API('api/notify/channels'));
      $('#smtp-host').value = c?.smtp?.host || '';
      $('#smtp-port').value = c?.smtp?.port || '';
      $('#smtp-user').value = c?.smtp?.user || '';
      $('#smtp-pass').value = c?.smtp?.pass || '';
      $('#smtp-from').value = c?.smtp?.from || '';
      $('#gotify-url').value = c?.gotify?.url || '';
      $('#gotify-token').value = c?.gotify?.token || '';
      $('#ntfy-url').value = c?.ntfy?.url || '';
      $('#ntfy-topic').value = c?.ntfy?.topic || '';
    }catch{}
  }
  $('#save-channels').addEventListener('click', async()=>{
    try{
      await jfetch(API('api/notify/channels'), {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          smtp:{
            host:$('#smtp-host').value, port:$('#smtp-port').value,
            user:$('#smtp-user').value, pass:$('#smtp-pass').value, from:$('#smtp-from').value
          },
          gotify:{ url:$('#gotify-url').value, token:$('#gotify-token').value },
          ntfy:{ url:$('#ntfy-url').value, topic:$('#ntfy-topic').value }
        })
      });
      toast('Intakes saved');
    }catch{ toast('Save failed'); }
  });
  $('#test-email').addEventListener('click', ()=> jfetch(API('api/notify/test/email'),{method:'POST'}).then(()=>toast('Email test sent')).catch(()=>toast('Email test failed')));
  $('#test-gotify').addEventListener('click',()=> jfetch(API('api/notify/test/gotify'),{method:'POST'}).then(()=>toast('Gotify test sent')).catch(()=>toast('Gotify test failed')));
  $('#test-ntfy').addEventListener('click',  ()=> jfetch(API('api/notify/test/ntfy'),  {method:'POST'}).then(()=>toast('ntfy test sent')).catch(()=>toast('ntfy test failed')));

  /* --------------- Settings -------------- */
  async function loadInboxSettings(){
    try{
      const s = await jfetch(API('api/inbox/settings'));
      if(s && typeof s==='object'){
        if(s.retention_days!=null)    $('#retention').value = s.retention_days;
        if(s.default_purge_days!=null)$('#purge-days').value = s.default_purge_days;
        if(s.qh){
          $('#qh-tz').value = s.qh.tz || '';
          $('#qh-start').value = s.qh.start || '';
          $('#qh-end').value = s.qh.end || '';
          $('#qh-allow-critical').checked = !!s.qh.allow_critical;
        }
      }
    }catch{}
  }
  $('#save-retention').addEventListener('click', async()=>{
    try{
      const d = parseInt($('#retention').value||'0',10) || 0;
      await jfetch(API('api/inbox/settings'), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ retention_days:d })});
      toast('Retention saved');
    }catch{ toast('Save failed'); }
  });
  $('#purge').addEventListener('click', async()=>{
    if(!confirm('Run purge now?')) return;
    try{
      const days = parseInt($('#purge-days').value||'0',10) || 0;
      await jfetch(API('api/inbox/purge'), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ days })});
      toast('Purge started');
    }catch{ toast('Purge failed'); }
  });
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

  /* ----------------- LLM ----------------- */
  async function loadLLM(){
    try{
      const s = await jfetch(API('api/llm/settings'));
      $('#llm-model').value   = s?.model   || '';
      $('#llm-ctx').value     = s?.ctx     ?? '';
      $('#llm-timeout').value = s?.timeout ?? '';
    }catch{}
  }
  $('#save-llm').addEventListener('click', async()=>{
    try{
      await jfetch(API('api/llm/settings'), {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          model: $('#llm-model').value,
          ctx: parseInt($('#llm-ctx').value||'0',10) || 0,
          timeout: parseInt($('#llm-timeout').value||'0',10) || 0
        })
      });
      toast('LLM saved');
    }catch{ toast('Save failed'); }
  });

  /* -------------- EnviroGuard ------------- */
  async function loadEnviro(){
    try{
      const e = await jfetch(API('api/llm/enviroguard'));
      $('#env-status').textContent = e?.enabled ? 'Enabled' : 'Disabled';
      $('#env-hot').value  = e?.hot  ?? '';
      $('#env-cold').value = e?.cold ?? '';
      $('#env-hyst').value = e?.hyst ?? '';
    }catch{}
  }
  $('#save-env').addEventListener('click', async()=>{
    try{
      await jfetch(API('api/llm/enviroguard'), {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          hot:  parseFloat($('#env-hot').value||''),
          cold: parseFloat($('#env-cold').value||''),
          hyst: parseFloat($('#env-hyst').value||'')
        })
      });
      toast('EnviroGuard saved');
    }catch{ toast('Save failed'); }
  });

  /* -------- Options (All) dynamic editor -------- */
  function guessWidget(key, type, val){
    const lower = key.toLowerCase();
    if (type.startsWith('int') || type==='float') return `<input type="number" data-key="${key}" value="${val ?? ''}">`;
    if (type==='bool') return `<label class="lbl"><input type="checkbox" data-key="${key}" ${val ? 'checked':''}/> ${key}</label>`;
    // long-ish strings → textarea
    if ((typeof val==='string' && val.length>80) || /_map$|_profiles$|_times$/.test(lower)) {
      return `<textarea data-key="${key}">${val ?? ''}</textarea>`;
    }
    return `<input type="text" data-key="${key}" value="${val ?? ''}">`;
  }
  function renderOptions(options, schema){
    const wrap = $('#opts-wrap');
    wrap.innerHTML = '';
    const groups = {
      core: [], io: [], llm: [], services: [], env: [], misc: []
    };
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

    function section(title, rows){
      return `<fieldset><legend>${title}</legend><div class="grid-auto">${rows.join('')}</div></fieldset>`;
    }
    wrap.innerHTML =
      section('Core', groups.core) +
      section('I/O & Channels', groups.io) +
      section('LLM', groups.llm) +
      section('Services', groups.services) +
      section('Environment / Weather', groups.env) +
      section('Misc', groups.misc);
  }
  async function loadOptionsAll(){
    try{
      const [opts, sch] = await Promise.all([
        jfetch(API('api/options')),
        jfetch(API('api/schema'))
      ]);
      renderOptions(opts, sch);
    }catch(e){
      console.error(e);
      $('#opts-wrap').innerHTML = '<div class="toast">Failed to load options/schema</div>';
    }
  }
  $('#save-options').addEventListener('click', async()=>{
    try{
      // Rebuild object by reading every [data-key]
      const fields = Array.from($('#opts-wrap').querySelectorAll('[data-key]'));
      const payload = {};
      for(const el of fields){
        const key = el.dataset.key;
        if (el.type === 'checkbox') payload[key] = !!el.checked;
        else if (el.tagName === 'TEXTAREA') payload[key] = el.value;
        else if (el.type === 'number') payload[key] = el.value==='' ? '' : (String(el.value).includes('.') ? parseFloat(el.value) : parseInt(el.value,10));
        else payload[key] = el.value;
      }
      await jfetch(API('api/options'), {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
      toast('Options saved');
    }catch(e){ toast('Save failed'); }
  });

  /* ----------------- Boot ---------------- */
  (async function boot(){
    await loadInbox();
    await Promise.all([
      loadPersonas(),
      loadChannels(),
      loadInboxSettings(),
      loadLLM(),
      loadEnviro(),
      loadOptionsAll()
    ]);
  })();
})();