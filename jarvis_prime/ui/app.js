(function(){
  const $  = s => document.querySelector(s);
  const $$ = s => document.querySelectorAll(s);

  /* ---------- API path helper (STRICTLY RELATIVE) ---------- */
  // If HA ingress rewrites the base path, using a bare "api/..." keeps calls relative.
  // Optional window.JARVIS_API_BASE supported if you ever want to override.
  const API = (path) => {
    const p = String(path || '').replace(/^\/+/, '');
    const base = (typeof window !== 'undefined' && window.JARVIS_API_BASE) ? String(window.JARVIS_API_BASE).replace(/\/+$/,'') + '/' : '';
    return base + p;
  };

  function toast(msg){
    const d=document.createElement('div');
    d.className='toast';
    d.textContent=String(msg||'');
    $('#toast').appendChild(d);
    setTimeout(()=>d.remove(), 4200);
  }

  async function jfetch(url, opts){
    const r = await fetch(url, opts);
    if(!r.ok){
      let t=''; try{ t = await r.text(); }catch{}
      throw new Error(r.status+' '+r.statusText+' @ '+url+'\n'+t);
    }
    const ct=(r.headers.get('content-type')||'').toLowerCase();
    if(ct.includes('application/json')) return r.json();
    return r.text();
  }

  /* ---------- Tabs ---------- */
  $$('.tablink').forEach(b=>{
    b.addEventListener('click', ()=>{
      $$('.tablink').forEach(x=>x.classList.remove('active'));
      b.classList.add('active');
      const id = b.dataset.tab;
      $$('.tab').forEach(t=>t.classList.remove('active'));
      $('#'+id).classList.add('active');
    });
  });

  /* =================== INBOX =================== */
  let INBOX_ITEMS = [];
  let SELECTED_ID = null;

  function tsFmt(v){
    try {
      const n = Number(v||0);
      const ms = n > 1e12 ? n : n*1000;
      return new Date(ms).toLocaleString();
    }catch{return '';}
  }

  function counters(items){
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()/1000;
    $('#msg-today').textContent = items.filter(i => (i.created_at||0) >= start).length;
    $('#msg-arch').textContent  = items.filter(i => i.saved).length;
    $('#msg-err').textContent   = items.filter(i => /error|fail|exception/i.test(`${i.title||''} ${i.body||i.message||''}`)).length;
  }

  function renderPreview(m){
    if(!m){
      $('#pv-title').textContent = 'No message selected';
      $('#pv-meta').textContent  = '–';
      $('#pv-body').textContent  = 'Click a message to see its contents here.';
      return;
    }
    $('#pv-title').textContent = m.title || '(no title)';
    const meta = [];
    if(m.source) meta.push(m.source);
    if(m.created_at) meta.push(tsFmt(m.created_at));
    $('#pv-meta').textContent = meta.join(' • ') || '–';

    const body = (m.body || m.message || '').trim();
    $('#pv-body').textContent = body || '(empty)';
  }

  function selectRowById(id){
    SELECTED_ID = id;
    $$('#msg-body tr').forEach(tr => tr.classList.toggle('selected', String(tr.dataset.id)===String(id)));
    renderPreview(INBOX_ITEMS.find(x=>String(x.id)===String(id)) || null);
  }

  async function loadInbox(){
    const tb = $('#msg-body');
    try{
      const data = await jfetch(API('api/messages'));
      const items = (data && data.items) ? data.items : (Array.isArray(data) ? data : []);
      INBOX_ITEMS = items;
      tb.innerHTML = '';
      if(!items.length){
        tb.innerHTML = '<tr><td colspan="4">No messages</td></tr>';
        counters([]); renderPreview(null);
        return;
      }
      counters(items);
      for(const m of items){
        const tr = document.createElement('tr');
        tr.className = 'msg-row';
        tr.dataset.id = m.id;
        tr.innerHTML = `
          <td>${tsFmt(m.created_at)}</td>
          <td>${m.source||''}</td>
          <td>${m.title||''}</td>
          <td>
            <button class="btn" data-act="arch" data-id="${m.id}">${m.saved?'Unarchive':'Archive'}</button>
            <button class="btn danger" data-act="del" data-id="${m.id}">Delete</button>
          </td>`;
        tb.appendChild(tr);
      }

      // restore selection (follow newest if enabled)
      const follow = $('#pv-follow')?.checked;
      const still = SELECTED_ID && items.some(x=>String(x.id)===String(SELECTED_ID));
      if(still) selectRowById(SELECTED_ID);
      else if(follow) { const last = items[items.length-1]; if(last) selectRowById(last.id); }
      else renderPreview(null);
    }catch(e){
      console.error(e);
      tb.innerHTML = '<tr><td colspan="4">Failed to load</td></tr>';
      toast('Inbox load error');
    }
  }

  $('#msg-body').addEventListener('click', (ev)=>{
    const tr = ev.target.closest('tr.msg-row');
    if(tr?.dataset.id){ selectRowById(tr.dataset.id); return; }
    const b  = ev.target.closest('button[data-act]');
    if(!b) return;
    (async()=>{
      try{
        if(b.dataset.act==='del'){
          if(!confirm('Delete this message?')) return;
          await jfetch(API(`api/messages/${b.dataset.id}`), {method:'DELETE'});
        }else if(b.dataset.act==='arch'){
          await jfetch(API(`api/messages/${b.dataset.id}/save`), {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
        }
        await loadInbox();
      }catch{ toast('Action failed'); }
    })();
  });

  $('#msg-del-all').addEventListener('click', async()=>{
    if(!confirm('Delete ALL messages?')) return;
    const keep = $('#keep-arch')?.checked ? 1 : 0;
    try{
      await jfetch(API(`api/messages?keep_saved=${keep}`), {method:'DELETE'});
      await loadInbox();
      toast('All messages deleted');
    }catch{ toast('Delete all failed'); }
  });

  // SSE live updates (relative URL)
  (function sse(){
    let es=null, backoff=1000;
    function connect(){
      try{ es && es.close(); }catch{}
      es = new EventSource(API('api/stream'));
      es.onopen = ()=> backoff = 1000;
      es.onerror = ()=>{ try{es.close();}catch{}; setTimeout(connect, Math.min(backoff,15000)); backoff=Math.min(backoff*2,15000); };
      es.onmessage = ev=>{
        try{
          const data = JSON.parse(ev.data||'{}');
          if(['created','deleted','deleted_all','saved','purged'].includes(data.event)){
            loadInbox().then(()=>{
              if(data.event==='created' && $('#pv-follow')?.checked && data.id) selectRowById(data.id);
            });
          }
        }catch{}
      };
    }
    connect();
    setInterval(loadInbox, 300000);
  })();

  /* =================== AEGISOPS =================== */

  const AEG = { hosts:[], playbooks:[], schedules:[] };

  // tiny INI parser for one-line hosts
  function parseInventoryIni(txt){
    const rows=[];
    (String(txt||'')).split(/\r?\n/).forEach(line=>{
      const s=line.trim();
      if(!s || s.startsWith('#') || s.startsWith('[')) return;
      const parts=s.split(/\s+/);
      const name=parts.shift();
      if(!name) return;
      const kv=Object.fromEntries(parts.map(p=>{const i=p.indexOf('=');return i>0?[p.slice(0,i),p.slice(i+1)]:[p,true];}));
      rows.push({name, host:kv.ansible_host||'', user:kv.ansible_user||''});
    });
    return rows;
  }
  function buildInventoryIni(rows){
    const lines=['[all]'];
    rows.forEach(r=>{
      if(!r.name) return;
      const host=r.host?` ansible_host=${r.host}`:'';
      const user=r.user?` ansible_user=${r.user}`:'';
      lines.push(`${r.name}${host}${user}`);
    });
    return lines.join('\n')+'\n';
  }

  // API helpers
  async function aeg_list_playbooks(){
    try{
      const res = await jfetch(API('api/aegisops/playbooks'));
      return Array.isArray(res?.items) ? res.items : (Array.isArray(res) ? res : []);
    }catch(e){ toast('Playbook list unavailable'); return []; }
  }
  async function aeg_get_inventory(){
    try{ return String(await jfetch(API('api/aegisops/inventory'))); }
    catch(e){ toast('Inventory not reachable'); return ''; }
  }
  async function aeg_save_inventory(text){
    try{
      await jfetch(API('api/aegisops/inventory'), {method:'POST', headers:{'Content-Type':'text/plain'}, body:String(text||'')});
      toast('Inventory saved');
    }catch(e){ toast('Save failed'); }
  }
  async function aeg_list_schedules(){
    try{
      const res = await jfetch(API('api/aegisops/schedules'));
      return Array.isArray(res) ? res : (Array.isArray(res?.items) ? res.items : []);
    }catch(e){ toast('Schedules not reachable'); return []; }
  }
  async function aeg_save_schedule(sch){
    try{
      await jfetch(API('api/aegisops/schedules'), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(sch)});
      toast('Schedule saved');
    }catch(e){ toast('Save schedule failed'); }
  }
  async function aeg_delete_schedule(id){
    try{ await jfetch(API(`api/aegisops/schedules/${encodeURIComponent(id)}`), {method:'DELETE'}); toast('Schedule deleted'); }
    catch(e){ toast('Delete failed'); }
  }
  async function aeg_runs(){
    try{
      const res = await jfetch(API('api/aegisops/runs?limit=100'));
      return Array.isArray(res) ? res : (Array.isArray(res?.items) ? res.items : []);
    }catch(e){ toast('Runs not reachable'); return []; }
  }
  async function aeg_run_once(playbook, servers, forks){
    try{
      await jfetch(API('api/aegisops/run'), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({playbook, servers, forks})});
      toast('Run triggered');
    }catch(e){ toast('Run failed'); }
  }

  // Playbook Editor API (optional on backend)
  async function pb_load(name){
    try{ return String(await jfetch(API(`api/aegisops/playbook?name=${encodeURIComponent(name)}`))); }
    catch(e){ toast('Load failed (endpoint missing?)'); return ''; }
  }
  async function pb_save(name, text){
    try{
      await jfetch(API(`api/aegisops/playbook?name=${encodeURIComponent(name)}`), {method:'POST', headers:{'Content-Type':'text/plain'}, body:String(text||'')});
      toast('Saved');
    }catch(e){ toast('Save failed'); }
  }
  async function pb_delete(name){
    try{
      await jfetch(API(`api/aegisops/playbook?name=${encodeURIComponent(name)}`), {method:'DELETE'});
      toast('Deleted');
    }catch(e){ toast('Delete failed'); }
  }

  /* ----- RENDERERS ----- */
  function renderHosts(){
    const tb = $('#ag-hosts');
    tb.innerHTML = '';
    if(!AEG.hosts.length){ tb.innerHTML='<tr><td colspan="4">No hosts (use Add Host or Refresh)</td></tr>'; return; }
    AEG.hosts.forEach((h,i)=>{
      const tr=document.createElement('tr');
      tr.innerHTML = `
        <td><input class="ag-host-name" value="${h.name||''}"></td>
        <td><input class="ag-host-host" value="${h.host||''}"></td>
        <td><input class="ag-host-user" value="${h.user||''}"></td>
        <td><button class="btn danger" data-act="del-host" data-idx="${i}">Delete</button></td>`;
      tb.appendChild(tr);
    });
  }
  $('#ag-hosts').addEventListener('click',(e)=>{
    const b=e.target.closest('button[data-act="del-host"]'); if(!b) return;
    const i=parseInt(b.dataset.idx,10); if(isNaN(i)) return;
    AEG.hosts.splice(i,1); renderHosts(); renderServersSelect();
  });
  $('#ag-host-add').addEventListener('click', ()=>{
    AEG.hosts.push({name:'host',host:'127.0.0.1',user:'root'});
    renderHosts(); renderServersSelect();
  });
  $('#ag-host-save').addEventListener('click', ()=>{
    const names=$$('#ag-hosts .ag-host-name');
    const hosts=$$('#ag-hosts .ag-host-host');
    const users=$$('#ag-hosts .ag-host-user');
    const rows=[];
    for(let i=0;i<names.length;i++){
      const name=names[i].value.trim(); if(!name) continue;
      rows.push({name,host:hosts[i].value.trim(),user:users[i].value.trim()});
    }
    AEG.hosts=rows;
    aeg_save_inventory(buildInventoryIni(rows)).then(()=>{ renderHosts(); renderServersSelect(); });
  });
  $('#ag-host-refresh').addEventListener('click', async()=>{
    const txt = await aeg_get_inventory();
    AEG.hosts = parseInventoryIni(txt);
    renderHosts(); renderServersSelect();
  });

  function renderPlaybooks(){
    const fill = (selId)=>{
      const sel=$(selId); sel.innerHTML='';
      if(!AEG.playbooks.length){ sel.innerHTML='<option value="">No playbooks found</option>'; sel.disabled=true; return; }
      AEG.playbooks.forEach(pb=>{ const o=document.createElement('option'); o.value=pb; o.textContent=pb; sel.appendChild(o); });
      sel.disabled=false;
    };
    fill('#ag-pb-select');
    fill('#ag-sch-playbook-select');
    fill('#pb-select');
  }
  $('#ag-pb-refresh').addEventListener('click', async()=>{
    AEG.playbooks = await aeg_list_playbooks();
    renderPlaybooks();
  });
  $('#ag-pb-run').addEventListener('click', ()=>{
    const pb=$('#ag-pb-select').value;
    if(!pb){ toast('Select a playbook'); return; }
    aeg_run_once(pb, AEG.hosts.map(h=>h.name), 1);
  });

  function renderServersSelect(){
    const sel=$('#ag-sch-servers-select');
    sel.innerHTML='';
    if(!AEG.hosts.length){ sel.innerHTML='<option value="">No hosts</option>'; sel.disabled=true; return; }
    AEG.hosts.forEach(h=>{ const o=document.createElement('option'); o.value=h.name; o.textContent=h.name; sel.appendChild(o); });
    sel.disabled=false;
  }

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
          <button class="btn" data-act="edit-sch" data-id="${s.id}">Edit</button>
          <button class="btn danger" data-act="del-sch" data-id="${s.id}">Delete</button>
        </td>`;
      tb.appendChild(tr);
    });
  }
  $('#ag-table').addEventListener('click',(e)=>{
    const b=e.target.closest('button[data-act]'); if(!b) return;
    const id=b.dataset.id, act=b.dataset.act;
    if(act==='del-sch'){
      if(!confirm('Delete schedule '+id+'?')) return;
      aeg_delete_schedule(id).then(loadSchedules);
    }else if(act==='edit-sch'){
      const s=AEG.schedules.find(x=>x.id===id); if(!s) return;
      $('#ag-sch-id').value = s.id||'';
      $('#ag-sch-every').value = s.every||'5m';
      $('#ag-sch-forks').value = s.forks||1;
      $('#ag-notify-success').checked = !!(s.notify?.on_success);
      $('#ag-notify-fail').checked = !!(s.notify?.on_fail ?? true);
      $('#ag-notify-change').checked = !!(s.notify?.only_on_state_change ?? true);
      $('#ag-notify-cooldown').value = s.notify?.cooldown_min ?? 30;
      $('#ag-notify-quiet').value = s.notify?.quiet_hours ?? '';
      $('#ag-notify-key').value = s.notify?.target_key ?? '';
      $('#ag-sch-playbook-select').value = s.playbook || '';
      const sel = $('#ag-sch-servers-select');
      const set = new Set((Array.isArray(s.servers)?s.servers:[]).map(String));
      [...sel.options].forEach(o=> o.selected=set.has(o.value));
      toast('Loaded schedule into editor');
    }
  });

  $('#ag-add').addEventListener('click', ()=>{
    const id = $('#ag-sch-id').value.trim();
    const playbook = $('#ag-sch-playbook-select').value;
    const servers = [...$('#ag-sch-servers-select').selectedOptions].map(o=>o.value);
    if(!id) return toast('Schedule id required');
    if(!playbook) return toast('Pick a playbook');
    if(!servers.length) return toast('Pick at least one server');

    const sch={
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
    aeg_save_schedule(sch).then(loadSchedules);
  });

  async function loadSchedules(){
    AEG.schedules = await aeg_list_schedules();
    renderSchedules();
  }

  // Runs
  async function loadRuns(){
    const tb = $('#ag-runs');
    tb.innerHTML='<tr><td colspan="7">Loading…</td></tr>';
    const rows = await aeg_runs();
    tb.innerHTML='';
    if(!rows.length){ tb.innerHTML='<tr><td colspan="7">No runs</td></tr>'; return; }
    rows.forEach(r=>{
      const tr=document.createElement('tr');
      tr.innerHTML = `
        <td>${r.ts||''}</td>
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
    const [inv, pbs] = await Promise.allSettled([aeg_get_inventory(), aeg_list_playbooks()]);
    if(inv.status==='fulfilled') AEG.hosts = parseInventoryIni(inv.value);
    if(pbs.status==='fulfilled') AEG.playbooks = pbs.value;
    renderHosts(); renderServersSelect(); renderPlaybooks();
  });

  // Editor
  $('#pb-load').addEventListener('click', async()=>{
    const name = $('#pb-select').value || $('#pb-new-name').value.trim();
    if(!name) return toast('Pick or type a filename');
    const txt = await pb_load(name);
    $('#pb-select').value = name;
    $('#pb-new-name').value = name;
    $('#pb-text').value = txt;
  });
  $('#pb-save').addEventListener('click', async()=>{
    let name = $('#pb-select').value || $('#pb-new-name').value.trim();
    if(!name) return toast('Filename required');
    await pb_save(name, $('#pb-text').value);
    // refresh list if new
    AEG.playbooks = await aeg_list_playbooks();
    renderPlaybooks();
    $('#pb-select').value = name;
  });
  $('#pb-delete').addEventListener('click', async()=>{
    const name = $('#pb-select').value;
    if(!name) return toast('Select a playbook to delete');
    if(!confirm(`Delete ${name}?`)) return;
    await pb_delete(name);
    $('#pb-text').value = '';
    $('#pb-new-name').value = '';
    AEG.playbooks = await aeg_list_playbooks();
    renderPlaybooks();
  });

  /* ---------- Boot ---------- */
  (async function boot(){
    // Inbox
    loadInbox();

    // Aegis metadata
    const [inv, pbs] = await Promise.allSettled([aeg_get_inventory(), aeg_list_playbooks()]);
    if(inv.status==='fulfilled') AEG.hosts = parseInventoryIni(inv.value);
    if(pbs.status==='fulfilled') AEG.playbooks = pbs.value;
    renderHosts(); renderServersSelect(); renderPlaybooks();
    loadSchedules();
    loadRuns();
  })();
})();
