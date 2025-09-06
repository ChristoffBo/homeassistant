(function(){
  const $  = s => document.querySelector(s);
  const $$ = s => document.querySelectorAll(s);

  /* ---------- API base (Ingress-safe) ---------- */
  function computeBase(){
    // Prefer window.JARVIS_API_BASE if the backend sets it
    if (window.JARVIS_API_BASE) {
      const b = String(window.JARVIS_API_BASE);
      return b.endsWith('/') ? b : b + '/';
    }
    // Otherwise use document.baseURI and keep the path segment as-is
    try{
      const u = new URL(document.baseURI);
      let p = u.pathname || '/';
      // remove trailing index.html
      if (p.endsWith('/index.html')) p = p.slice(0, -'/index.html'.length);
      if (!p.endsWith('/')) p += '/';
      u.pathname = p;
      return u.toString();
    }catch{
      return './';
    }
  }
  const ROOT = computeBase();

  // Build two variants: absolute & relative; jfetch will try both
  function API(path){
    const rel = String(path).replace(/^\/+/, '');
    let abs;
    try{ abs = new URL(rel, ROOT).toString(); }
    catch{ abs = rel; }
    return [abs, rel];
  }

  function toast(msg){
    const d=document.createElement('div');
    d.className='toast'; d.textContent=msg;
    $('#toast').appendChild(d);
    setTimeout(()=>d.remove(), 3500);
  }

  async function jfetch(urlOrList, opts){
    const variants = Array.isArray(urlOrList) ? urlOrList : [urlOrList];
    let lastErr;
    for (const url of variants){
      try{
        const r = await fetch(url, opts);
        if (!r.ok){ lastErr = new Error(`${r.status} ${r.statusText}`); continue; }
        const ct = (r.headers.get('content-type')||'').toLowerCase();
        return ct.includes('application/json') ? r.json() : r.text();
      }catch(e){ lastErr = e; }
    }
    throw lastErr || new Error('Request failed');
  }

  function openEventSource(path, onmsg, onerr){
    const [abs, rel] = API(path);
    let es = new EventSource(abs);
    es.onmessage = onmsg;
    es.onerror = ()=>{
      try{ es.close(); }catch{}
      // Try relative as fallback
      const es2 = new EventSource(rel);
      es2.onmessage = onmsg;
      es2.onerror = onerr || (()=>{});
    };
    return es;
  }

  /* ---------- Tabs ---------- */
  $$('.tablink').forEach(b=>b.addEventListener('click',()=>{
    $$('.tablink').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
    $$('.tab').forEach(t=>t.classList.remove('active'));
    $('#'+b.dataset.tab).classList.add('active');
  }));

  /* ---------- Inbox ---------- */
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

  let INBOX_ITEMS = [];
  let SELECTED_ID = null;

  function renderPreview(m){
    if(!m){
      $('#pv-title').textContent='No message selected';
      $('#pv-meta').textContent='–';
      $('#pv-body').innerHTML='<span class="muted">Click a message to see its contents here.</span>';
      return;
    }
    $('#pv-title').textContent = m.title || '(no title)';
    const metaBits = [];
    if (m.source) metaBits.push(m.source);
    if (m.created_at) metaBits.push(fmt(m.created_at));
    $('#pv-meta').textContent = metaBits.join(' • ') || '–';
    const body = (m.body || m.message || '').trim();
    $('#pv-body').textContent = body || '(empty)';
  }

  function selectRowById(id){
    SELECTED_ID = id;
    $$('#msg-body tr').forEach(tr=> tr.classList.toggle('selected', tr.dataset.id===String(id)));
    const m = INBOX_ITEMS.find(x=> String(x.id)===String(id));
    renderPreview(m);
  }

  async function loadInbox(){
    const tb = $('#msg-body');
    try{
      const data = await jfetch(API('api/messages'));
      const items = data && data.items ? data.items : (Array.isArray(data) ? data : []);
      INBOX_ITEMS = items;
      tb.innerHTML = '';
      if(!items.length){
        tb.innerHTML = '<tr><td colspan="4">No messages</td></tr>';
        updateCounters([]); renderPreview(null);
        return;
      }
      updateCounters(items);
      for(const m of items){
        const tr=document.createElement('tr');
        tr.className='msg-row';
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

      const follow = $('#pv-follow')?.checked;
      const stillExists = SELECTED_ID && items.some(x=> String(x.id)===String(SELECTED_ID));
      if (stillExists) {
        selectRowById(SELECTED_ID);
      } else if (follow) {
        const last = items[items.length-1];
        if (last) selectRowById(last.id);
        else renderPreview(null);
      } else {
        renderPreview(null);
      }
    }catch(e){
      console.error('[inbox] load failed', e);
      tb.innerHTML = '<tr><td colspan="4">Failed to load</td></tr>';
      renderPreview(null);
      toast('Inbox load error');
    }
  }

  $('#msg-body').addEventListener('click', (e)=>{
    const tr = e.target.closest('tr.msg-row');
    if(tr && tr.dataset.id){
      selectRowById(tr.dataset.id);
      return;
    }
    const btn = e.target.closest('button[data-act]');
    if(!btn) return;
    const id = btn.dataset.id;
    const act = btn.dataset.act;
    (async()=>{
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
    })();
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

  // Live updates (SSE) with fallback to relative path
  (function(){
    openEventSource('api/stream', (ev)=>{
      try{
        const d = JSON.parse(ev.data||'{}');
        if(['created','deleted','deleted_all','saved','purged'].includes(d.event)){
          loadInbox().then(()=>{
            if (d.event==='created' && $('#pv-follow')?.checked && d.id) selectRowById(d.id);
          });
        }
      }catch{}
    }, ()=>{/* ignore */});
  })();

  /* ---------- AEGISOPS ---------- */
  const AEG = { hosts:[], playbooks:[], schedules:[] };

  // minimal INI parser for inventory.ini (one host per line)
  function parseInventoryIni(txt){
    const rows=[];
    (txt||'').split(/\r?\n/).forEach(line=>{
      const s=line.trim();
      if(!s || s.startsWith('#') || s.startsWith('[')) return;
      const parts=s.split(/\s+/);
      const name = parts.shift();
      if(!name) return;
      const kv = Object.fromEntries(parts.map(p=>{
        const i=p.indexOf('=');
        return i>0 ? [p.slice(0,i), p.slice(i+1)] : [p, true];
      }));
      rows.push({ name, host: kv.ansible_host||'', user: kv.ansible_user||'' });
    });
    return rows;
  }
  function buildInventoryIni(rows){
    const lines=['[all]'];
    rows.forEach(r=>{
      if(!r.name) return;
      const host = r.host ? ` ansible_host=${r.host}` : '';
      const user = r.user ? ` ansible_user=${r.user}` : '';
      lines.push(`${r.name}${host}${user}`);
    });
    return lines.join('\n')+'\n';
  }

  // API helpers (backend may not exist yet — soft-fail with toasts)
  const aeg = {
    async listPlaybooks(){ try{
      const res = await jfetch(API('api/aegisops/playbooks'));
      return Array.isArray(res?.items) ? res.items : (Array.isArray(res) ? res : []);
    }catch(e){ toast('Playbook list unavailable'); return []; }},

    async getInventory(){ try{
      const txt = await jfetch(API('api/aegisops/inventory'));
      return String(txt);
    }catch(e){ toast('Inventory not reachable'); return ''; }},

    async saveInventory(text){ try{
      await jfetch(API('api/aegisops/inventory'), {method:'POST', headers:{'Content-Type':'text/plain'}, body:text});
      toast('Inventory saved');
    }catch(e){ toast('Save failed (backend?)'); }},

    async listSchedules(){ try{
      const res = await jfetch(API('api/aegisops/schedules'));
      return Array.isArray(res) ? res : (Array.isArray(res?.items) ? res.items : []);
    }catch(e){ toast('Schedules not reachable'); return []; }},

    async saveSchedule(s){ try{
      await jfetch(API('api/aegisops/schedules'), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(s)});
      toast('Schedule saved');
    }catch(e){ toast('Save schedule failed'); }},

    async deleteSchedule(id){ try{
      await jfetch(API('api/aegisops/schedules/'+encodeURIComponent(id)), {method:'DELETE'});
      toast('Schedule deleted');
    }catch(e){ toast('Delete failed'); }},

    async runs(){ try{
      const res = await jfetch(API('api/aegisops/runs?limit=100'));
      return Array.isArray(res) ? res : (Array.isArray(res?.items) ? res.items : []);
    }catch(e){ toast('Runs not reachable'); return []; }},

    async runOnce(playbook, servers, forks){ try{
      await jfetch(API('api/aegisops/run'), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({playbook, servers, forks})});
      toast('Run triggered');
    }catch(e){ toast('Run failed'); }},

    // Editor endpoints
    async getPlaybook(name){ try{
      return await jfetch(API('api/aegisops/playbook?name='+encodeURIComponent(name)));
    }catch(e){ toast('Load failed'); return ''; }},
    async savePlaybook(name, content){ try{
      await jfetch(API('api/aegisops/playbook'), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name, content})});
      toast('Saved');
    }catch(e){ toast('Save failed'); }},
    async deletePlaybook(name){ try{
      await jfetch(API('api/aegisops/playbook'), {method:'DELETE', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name})});
      toast('Deleted');
    }catch(e){ toast('Delete failed'); }},
  };

  /* ---- Hosts UI ---- */
  function renderHosts(){
    const tb = $('#ag-hosts');
    tb.innerHTML = '';
    if(!AEG.hosts.length){
      tb.innerHTML = '<tr><td colspan="4">No hosts (use Add Host or Refresh)</td></tr>';
      return;
    }
    AEG.hosts.forEach((h,i)=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><input class="ag-host-name" value="${h.name||''}"></td>
        <td><input class="ag-host-host" value="${h.host||''}"></td>
        <td><input class="ag-host-user" value="${h.user||''}"></td>
        <td><button class="btn danger" data-idx="${i}" data-act="del-host">Delete</button></td>`;
      tb.appendChild(tr);
    });
  }

  $('#ag-hosts').addEventListener('click',(e)=>{
    const b = e.target.closest('button[data-act="del-host"]');
    if(!b) return;
    const idx = parseInt(b.dataset.idx,10);
    if(Number.isFinite(idx)){ AEG.hosts.splice(idx,1); renderHosts(); renderServersSelect(); }
  });

  $('#ag-host-add').addEventListener('click',()=>{
    AEG.hosts.push({name:'host',host:'127.0.0.1',user:'root'});
    renderHosts(); renderServersSelect();
  });

  $('#ag-host-save').addEventListener('click',()=>{
    const names = $$('#ag-hosts .ag-host-name');
    const hosts = $$('#ag-hosts .ag-host-host');
    const users = $$('#ag-hosts .ag-host-user');
    const rows=[];
    for(let i=0;i<names.length;i++){
      const name = names[i].value.trim();
      if(!name) continue;
      rows.push({name, host:(hosts[i].value||'').trim(), user:(users[i].value||'').trim()});
    }
    AEG.hosts = rows;
    aeg.saveInventory(buildInventoryIni(AEG.hosts)).then(()=>{ renderHosts(); renderServersSelect(); });
  });

  $('#ag-host-refresh').addEventListener('click', async()=>{
    const txt = await aeg.getInventory();
    AEG.hosts = parseInventoryIni(txt);
    renderHosts(); renderServersSelect();
  });

  /* ---- Playbooks dropdown ---- */
  function renderPlaybooks(){
    const fills = [$('#ag-pb-select'), $('#ag-sch-playbook-select'), $('#pb-select')];
    fills.forEach(sel=>{
      sel.innerHTML='';
      if(!AEG.playbooks.length){
        sel.innerHTML = '<option value="">No playbooks found</option>';
        sel.disabled = true;
      }else{
        sel.disabled = false;
        AEG.playbooks.forEach(pb=>{
          const o=document.createElement('option'); o.value=pb; o.textContent=pb; sel.appendChild(o);
        });
      }
    });
  }

  $('#ag-pb-refresh').addEventListener('click', async()=>{
    AEG.playbooks = await aeg.listPlaybooks();
    renderPlaybooks();
  });

  $('#ag-pb-run').addEventListener('click', ()=>{
    const pb = $('#ag-pb-select').value;
    if(!pb){ toast('Select a playbook'); return; }
    const servers = AEG.hosts.map(h=>h.name);
    aeg.runOnce(pb, servers, 1);
  });

  /* ---- Servers multiselect ---- */
  function renderServersSelect(){
    const sel = $('#ag-sch-servers-select');
    sel.innerHTML='';
    if(!AEG.hosts.length){
      sel.innerHTML='<option value="">No hosts</option>'; sel.disabled=true; return;
    }
    sel.disabled=false;
    AEG.hosts.forEach(h=>{
      const o=document.createElement('option'); o.value=h.name; o.textContent=h.name; sel.appendChild(o);
    });
  }

  /* ---- Schedules ---- */
  function renderSchedules(){
    const tb = $('#ag-table');
    tb.innerHTML='';
    if(!AEG.schedules.length){ tb.innerHTML='<tr><td colspan="5">No schedules</td></tr>'; return; }
    AEG.schedules.forEach(s=>{
      const tr=document.createElement('tr');
      tr.innerHTML = `
        <td>${s.id||''}</td>
        <td>${s.playbook||''}</td>
        <td>${Array.isArray(s.servers)?s.servers.join(', '):s.servers||''}</td>
        <td>${s.every||''}</td>
        <td>
          <button class="btn" data-id="${s.id}" data-act="edit-sch">Edit</button>
          <button class="btn danger" data-id="${s.id}" data-act="del-sch">Delete</button>
        </td>`;
      tb.appendChild(tr);
    });
  }

  $('#ag-table').addEventListener('click', (e)=>{
    const b = e.target.closest('button[data-act]');
    if(!b) return;
    const id=b.dataset.id, act=b.dataset.act;
    if(act==='del-sch'){
      if(!confirm('Delete schedule '+id+'?')) return;
      aeg.deleteSchedule(id).then(loadSchedules);
    }else if(act==='edit-sch'){
      const s = AEG.schedules.find(x=>x.id===id);
      if(!s) return;
      $('#ag-sch-id').value = s.id||'';
      $('#ag-sch-every').value = s.every||'5m';
      $('#ag-sch-forks').value = s.forks||1;
      $('#ag-notify-success').checked = !!(s.notify?.on_success);
      $('#ag-notify-fail').checked    = !!(s.notify?.on_fail ?? true);
      $('#ag-notify-change').checked  = !!(s.notify?.only_on_state_change ?? true);
      $('#ag-notify-cooldown').value  = s.notify?.cooldown_min ?? 30;
      $('#ag-notify-quiet').value     = s.notify?.quiet_hours ?? '';
      $('#ag-notify-key').value       = s.notify?.target_key ?? '';
      $('#ag-sch-playbook-select').value = s.playbook || '';
      const sel = $('#ag-sch-servers-select');
      const set = new Set((Array.isArray(s.servers)?s.servers:[]).map(String));
      [...sel.options].forEach(o=> o.selected = set.has(o.value));
      toast('Loaded schedule into editor');
    }
  });

  $('#ag-add').addEventListener('click', ()=>{
    const id = $('#ag-sch-id').value.trim();
    if(!id){ toast('Schedule id required'); return; }
    const playbook = $('#ag-sch-playbook-select').value;
    if(!playbook){ toast('Pick a playbook'); return; }
    const servers = [...$('#ag-sch-servers-select').selectedOptions].map(o=>o.value);
    if(!servers.length){ toast('Pick at least one server'); return; }

    const sch = {
      id, playbook, servers,
      every: $('#ag-sch-every').value,
      forks: parseInt($('#ag-sch-forks').value||'1',10) || 1,
      notify:{
        on_success: $('#ag-notify-success').checked,
        on_fail: $('#ag-notify-fail').checked,
        only_on_state_change: $('#ag-notify-change').checked,
        cooldown_min: parseInt($('#ag-notify-cooldown').value||'30',10)||30,
        quiet_hours: $('#ag-notify-quiet').value || '',
        target_key: $('#ag-notify-key').value || ''
      }
    };
    aeg.saveSchedule(sch).then(loadSchedules);
  });

  async function loadSchedules(){
    AEG.schedules = await aeg.listSchedules();
    renderSchedules();
  }

  /* ---- Runs ---- */
  async function loadRuns(){
    const tb = $('#ag-runs');
    tb.innerHTML = '<tr><td colspan="7">Loading…</td></tr>';
    const rows = await aeg.runs();
    tb.innerHTML='';
    if(!rows.length){ tb.innerHTML='<tr><td colspan="7">No runs</td></tr>'; return; }
    rows.forEach(r=>{
      const tr=document.createElement('tr');
      tr.innerHTML = `
        <td>${r.ts ? r.ts : ''}</td>
        <td>${r.playbook||''}</td>
        <td>${r.status||''}</td>
        <td>${r.ok_count??''}</td>
        <td>${r.changed_count??''}</td>
        <td>${r.fail_count??''}</td>
        <td>${r.unreachable_count??''}</td>`;
      tb.appendChild(tr);
    });
  }
  $('#ag-refresh').addEventListener('click', loadRuns);
  $('#ag-meta-refresh').addEventListener('click', async()=>{
    const [inv, pbs] = await Promise.allSettled([aeg.getInventory(), aeg.listPlaybooks()]);
    if(inv.status==='fulfilled') AEG.hosts = parseInventoryIni(inv.value); else AEG.hosts=[];
    if(pbs.status==='fulfilled') AEG.playbooks = pbs.value; else AEG.playbooks=[];
    renderHosts(); renderServersSelect(); renderPlaybooks();
  });

  /* ---- Playbook Editor ---- */
  $('#pb-load').addEventListener('click', async()=>{
    const name = $('#pb-select').value;
    if(!name){ toast('Pick a playbook'); return; }
    const txt = await aeg.getPlaybook(name);
    $('#pb-editor').value = String(txt || '');
    $('#pb-new-name').value = name; // default save target to same file
  });

  $('#pb-save').addEventListener('click', async()=>{
    const name = ($('#pb-new-name').value || '').trim();
    if(!name){ toast('Enter a filename'); return; }
    await aeg.savePlaybook(name, $('#pb-editor').value);
    // refresh list
    AEG.playbooks = await aeg.listPlaybooks();
    renderPlaybooks();
    $('#pb-select').value = name;
  });

  $('#pb-delete').addEventListener('click', async()=>{
    const name = $('#pb-select').value || $('#pb-new-name').value;
    if(!name){ toast('Pick a playbook'); return; }
    if(!confirm('Delete '+name+'?')) return;
    await aeg.deletePlaybook(name);
    $('#pb-editor').value = '';
    $('#pb-new-name').value = '';
    AEG.playbooks = await aeg.listPlaybooks();
    renderPlaybooks();
  });

  /* ---------- Boot ---------- */
  (async function boot(){
    // Inbox
    await loadInbox();
    // Aegis metadata
    const [inv, pbs] = await Promise.allSettled([aeg.getInventory(), aeg.listPlaybooks()]);
    if(inv.status==='fulfilled') AEG.hosts = parseInventoryIni(inv.value); else AEG.hosts=[];
    if(pbs.status==='fulfilled') AEG.playbooks = pbs.value; else AEG.playbooks=[];
    renderHosts(); renderServersSelect(); renderPlaybooks();
    loadSchedules();
    loadRuns();
  })();
})();
