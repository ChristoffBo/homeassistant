(function () {
  /* ---------------- Helpers ---------------- */
  const $  = (s, r=document) => r.querySelector(s);
  const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));

  // Resolve API root that works in both Ingress and direct-host
  function apiRoot() {
    if (window.JARVIS_API_BASE) {
      let v = String(window.JARVIS_API_BASE);
      return v.endsWith('/') ? v : v + '/';
    }
    try {
      const u = new URL(document.baseURI);
      let p = u.pathname;
      // If UI is at /ui/ or ends with /index.html, trim to the UI root
      if (p.endsWith('/index.html')) p = p.slice(0, -'/index.html'.length);
      if (p.endsWith('/ui/')) p = p.slice(0, -4);
      if (!p.endsWith('/')) p += '/';
      u.pathname = p;
      return u.toString();
    } catch (e) {
      return document.baseURI;
    }
  }
  const ROOT = apiRoot();
  const API  = (path) => new URL(String(path).replace(/^\/+/, ''), ROOT).toString();

  function toast(msg) {
    const d = document.createElement('div');
    d.className = 'toast';
    d.textContent = msg;
    $('#toast')?.appendChild(d);
    setTimeout(() => d.remove(), 3500);
  }

  async function jfetch(url, opts) {
    const r = await fetch(url, opts);
    if (!r.ok) {
      const t = await r.text().catch(() => '');
      throw new Error(`${r.status} ${r.statusText} @ ${url}\n${t}`);
    }
    const ct = r.headers.get('content-type') || '';
    return ct.includes('application/json') ? r.json() : r.text();
  }

  /* ---------------- Tabs ---------------- */
  $$('.tablink').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.tablink').forEach(x => x.classList.remove('active'));
      btn.classList.add('active');
      $$('.tab').forEach(t => t.classList.remove('active'));
      const pane = $('#' + btn.dataset.tab);
      if (pane) pane.classList.add('active');
    });
  });

  /* ---------------- Inbox ---------------- */
  let INBOX_ITEMS = [];
  let SELECTED_ID = null;

  function fmt(ts) {
    try {
      const v = Number(ts || 0);
      const ms = v > 1e12 ? v : v * 1000;
      return new Date(ms).toLocaleString();
    } catch {
      return '';
    }
  }

  function updateCounters(items) {
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
    const today    = items.filter(i => (i.created_at || 0) >= start).length;
    const archived = items.filter(i => i.saved).length;
    const errors   = items.filter(i => /error|fail|exception/i.test(`${i.title||''} ${i.body||i.message||''}`)).length;
    $('#msg-today').textContent = today;
    $('#msg-arch').textContent  = archived;
    $('#msg-err').textContent   = errors;
  }

  function renderPreview(m) {
    if (!m) {
      $('#pv-title').textContent = 'No message selected';
      $('#pv-meta').textContent = '–';
      $('#pv-body').innerHTML = '<p class="muted">Click a message to see its contents here.</p>';
      return;
    }
    $('#pv-title').textContent = m.title || '(no title)';
    const bits = [];
    if (m.source) bits.push(m.source);
    if (m.created_at) bits.push(fmt(m.created_at));
    $('#pv-meta').textContent = bits.join(' • ') || '–';
    const body = (m.body || m.message || '').trim();
    // Avoid HTML injection; keep it simple
    $('#pv-body').textContent = body || '(empty)';
  }

  function selectRowById(id) {
    SELECTED_ID = id;
    $$('#msg-body tr.msg-row').forEach(tr => tr.classList.toggle('selected', tr.dataset.id === String(id)));
    const m = INBOX_ITEMS.find(x => String(x.id) === String(id));
    renderPreview(m);
  }

  async function loadInbox() {
    const tb = $('#msg-body');
    try {
      const data = await jfetch(API('api/messages'));
      const items = data && data.items ? data.items :
                    (Array.isArray(data) ? data : []);
      INBOX_ITEMS = Array.isArray(items) ? items : [];
      tb.innerHTML = '';

      if (!INBOX_ITEMS.length) {
        tb.innerHTML = '<tr><td colspan="4">No messages</td></tr>';
        updateCounters([]);
        renderPreview(null);
        return;
      }

      updateCounters(INBOX_ITEMS);
      for (const m of INBOX_ITEMS) {
        const tr = document.createElement('tr');
        tr.className = 'msg-row';
        tr.dataset.id = m.id;
        tr.innerHTML = `
          <td>${fmt(m.created_at)}</td>
          <td>${m.source || ''}</td>
          <td>${m.title || ''}</td>
          <td>
            <button class="btn" data-id="${m.id}" data-act="arch">${m.saved ? 'Unarchive' : 'Archive'}</button>
            <button class="btn danger" data-id="${m.id}" data-act="del">Delete</button>
          </td>`;
        tb.appendChild(tr);
      }

      const follow = $('#pv-follow')?.checked;
      const still = SELECTED_ID && INBOX_ITEMS.some(x => String(x.id) === String(SELECTED_ID));
      if (still) {
        selectRowById(SELECTED_ID);
      } else if (follow) {
        const last = INBOX_ITEMS[INBOX_ITEMS.length - 1];
        if (last) selectRowById(last.id);
        else renderPreview(null);
      } else {
        renderPreview(null);
      }
    } catch (e) {
      console.error(e);
      tb.innerHTML = '<tr><td colspan="4">Failed to load</td></tr>';
      toast('Inbox load error');
      renderPreview(null);
    }
  }

  // Row clicks and per-message actions
  $('#msg-body').addEventListener('click', (ev) => {
    const btn = ev.target.closest('button[data-act]');
    if (btn) {
      const id  = btn.dataset.id;
      const act = btn.dataset.act;
      (async () => {
        try {
          if (act === 'del') {
            if (!confirm('Delete this message?')) return;
            await jfetch(API('api/messages/' + id), { method: 'DELETE' });
            toast('Deleted');
          } else if (act === 'arch') {
            await jfetch(API(`api/messages/${id}/save`), {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({})
            });
            toast('Toggled archive');
          }
          await loadInbox();
        } catch (e) {
          toast('Action failed');
        }
      })();
      return;
    }
    const tr = ev.target.closest('tr.msg-row');
    if (tr && tr.dataset.id) selectRowById(tr.dataset.id);
  });

  // Delete All (with “keep archived” option)
  $('#del-all').addEventListener('click', async () => {
    if (!confirm('Delete ALL messages?')) return;
    const keep = $('#keep-arch')?.checked ? 1 : 0;
    try {
      await jfetch(API(`api/messages?keep_saved=${keep}`), { method: 'DELETE' });
      toast('All deleted');
      await loadInbox();
    } catch {
      toast('Delete all failed');
    }
  });

  // Live updates with SSE + backoff
  (function startStream() {
    let es = null, backoff = 1000;
    function connect() {
      try { es && es.close(); } catch {}
      es = new EventSource(API('api/stream'));
      es.onopen = () => backoff = 1000;
      es.onerror = () => {
        try { es.close(); } catch {}
        setTimeout(connect, Math.min(backoff, 15000));
        backoff = Math.min(backoff * 2, 15000);
      };
      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data || '{}');
          if (['created', 'deleted', 'deleted_all', 'saved', 'purged'].includes(data.event)) {
            loadInbox().then(() => {
              if (data.event === 'created' && $('#pv-follow')?.checked) {
                if (data.id) selectRowById(data.id);
              }
            });
          }
        } catch {}
      };
    }
    connect();
    // Safety: periodic refresh
    setInterval(loadInbox, 5 * 60 * 1000);
  })();

  /* ---------------- Boot ---------------- */
  loadInbox();
})();
/* ======================================================================= *
 *                     AEGISOPS — UI WIRING (INBOX SAFE)
 * - Purely additive. Does not modify existing Inbox code or globals.
 * - Only attaches behavior if matching Aegis elements are present.
 * - Uses dedicated helpers (aegApi, aegToast) to avoid collisions.
 * ======================================================================= */
(function (){
  // ---------- tiny helpers ----------
  const $  = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);

  // toast: reuses a global toast if you already have one; otherwise minimal fallback
  function aegToast(msg){
    if (typeof window.toast === 'function') return window.toast(msg);
    try {
      const wrap = document.getElementById('toast') || (() => {
        const d = document.createElement('div'); d.id = 'toast';
        d.style.position='fixed'; d.style.right='12px'; d.style.bottom='12px'; d.style.zIndex='99999';
        document.body.appendChild(d); return d;
      })();
      const div = document.createElement('div');
      div.textContent = msg;
      div.style.marginTop = '6px';
      div.style.padding = '8px 12px';
      div.style.borderRadius = '8px';
      div.style.background = 'rgba(30,40,60,.95)';
      div.style.color = '#d7e3ff';
      div.style.fontSize = '12px';
      wrap.appendChild(div);
      setTimeout(()=> div.remove(), 3500);
    } catch {}
  }

  // Compute API root (does not interfere with your Inbox’ own logic)
  function computeApiBase(){
    if (window.JARVIS_API_BASE) return String(window.JARVIS_API_BASE).replace(/\/?$/, '/');
    try{
      const u = new URL(document.baseURI);
      let p = u.pathname;
      if (p.endsWith('/index.html')) p = p.slice(0, -'/index.html'.length);
      if (p.endsWith('/ui/'))       p = p.slice(0, -4);
      if (!p.endsWith('/'))         p += '/';
      u.pathname = p;
      return u.toString();
    } catch { return '/'; }
  }
  const AEGIS_ROOT = computeApiBase();
  const aegApi = (path) => new URL(String(path).replace(/^\/+/, ''), AEGIS_ROOT).toString();

  async function jfetch(url, opts){
    const r = await fetch(url, opts);
    if (!r.ok) {
      let t=''; try{ t = await r.text(); }catch{}
      throw new Error(`[${r.status}] ${r.statusText} @ ${url}\n${t}`);
    }
    const ct = r.headers.get('content-type')||'';
    return ct.includes('application/json') ? r.json() : r.text();
  }

  // ---------------- Shared Aegis state ----------------
  const AEG = { hosts: [], playbooks: [], schedules: [] };

  // ---------------- Inventory helpers ----------------
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
      rows.push({ name, host: kv.ansible_host || '', user: kv.ansible_user || '' });
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

  // ---------------- Backend API wrappers ----------------
  async function aeg_list_playbooks(){
    try{
      const res = await jfetch(aegApi('api/aegisops/playbooks'));
      return Array.isArray(res?.items) ? res.items : (Array.isArray(res) ? res : []);
    }catch(e){ aegToast('Playbook list unavailable'); return []; }
  }
  async function aeg_get_inventory(){
    try{ return String(await jfetch(aegApi('api/aegisops/inventory'))); }
    catch(e){ aegToast('Inventory not reachable'); return ''; }
  }
  async function aeg_save_inventory(text){
    try{
      await jfetch(aegApi('api/aegisops/inventory'), { method:'POST', headers:{'Content-Type':'text/plain'}, body:text });
      aegToast('Inventory saved');
    }catch(e){ aegToast('Save failed'); }
  }
  async function aeg_list_schedules(){
    try{
      const res = await jfetch(aegApi('api/aegisops/schedules'));
      return Array.isArray(res) ? res : (Array.isArray(res?.items) ? res.items : []);
    }catch(e){ aegToast('Schedules not reachable'); return []; }
  }
  async function aeg_save_schedule(sch){
    try{
      await jfetch(aegApi('api/aegisops/schedules'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(sch) });
      aegToast('Schedule saved');
    }catch(e){ aegToast('Save schedule failed'); }
  }
  async function aeg_delete_schedule(id){
    try{
      await jfetch(aegApi('api/aegisops/schedules/'+encodeURIComponent(id)), { method:'DELETE' });
      aegToast('Schedule deleted');
    }catch(e){ aegToast('Delete failed'); }
  }
  async function aeg_runs(){
    try{
      const res = await jfetch(aegApi('api/aegisops/runs?limit=100'));
      return Array.isArray(res) ? res : (Array.isArray(res?.items) ? res.items : []);
    }catch(e){ aegToast('Runs not reachable'); return []; }
  }
  async function aeg_run_once(playbook, servers, forks){
    try{
      await jfetch(aegApi('api/aegisops/run'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({playbook, servers, forks}) });
      aegToast('Run triggered');
    }catch(e){ aegToast('Run failed'); }
  }

  // ---------- HOSTS TAB ----------
  const hostsBody = $('#ag-hosts');
  if (hostsBody){
    function renderHosts(){
      hostsBody.innerHTML = '';
      if(!AEG.hosts.length){
        hostsBody.innerHTML = '<tr><td colspan="4">No hosts (use Add Host or Refresh)</td></tr>';
        return;
      }
      AEG.hosts.forEach((h,i)=>{
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><input class="ag-host-name" value="${h.name||''}"></td>
          <td><input class="ag-host-host" value="${h.host||''}"></td>
          <td><input class="ag-host-user" value="${h.user||''}"></td>
          <td><button class="btn danger" data-idx="${i}" data-act="del-host">Delete</button></td>`;
        hostsBody.appendChild(tr);
      });
    }
    hostsBody.addEventListener('click',(e)=>{
      const b = e.target.closest('button[data-act="del-host"]');
      if(!b) return;
      const idx = parseInt(b.dataset.idx,10);
      if(isNaN(idx)) return;
      AEG.hosts.splice(idx,1);
      renderHosts(); renderServersSelect();
    });
    $('#ag-host-add')?.addEventListener('click', ()=>{
      AEG.hosts.push({name:'host',host:'127.0.0.1',user:'root'});
      renderHosts(); renderServersSelect();
    });
    $('#ag-host-save')?.addEventListener('click', ()=>{
      const names = $$('#ag-hosts .ag-host-name');
      const hosts = $$('#ag-hosts .ag-host-host');
      const users = $$('#ag-hosts .ag-host-user');
      const rows=[];
      for(let i=0;i<names.length;i++){
        const name = names[i].value.trim();
        if(!name) continue;
        rows.push({name, host: (hosts[i].value||'').trim(), user:(users[i].value||'').trim()});
      }
      AEG.hosts = rows;
      aeg_save_inventory(buildInventoryIni(AEG.hosts)).then(()=>{ renderHosts(); renderServersSelect(); });
    });
    $('#ag-host-refresh')?.addEventListener('click', async()=>{
      const txt = await aeg_get_inventory();
      AEG.hosts = parseInventoryIni(txt);
      renderHosts(); renderServersSelect();
    });
  }

  // ---------- PLAYBOOKS TAB ----------
  const pbSelect = $('#ag-pb-select');
  function renderPlaybooks(){
    if(!pbSelect) return;
    const s1 = pbSelect;
    const s2 = $('#ag-sch-playbook-select');
    function fill(sel){
      sel.innerHTML='';
      if(!AEG.playbooks.length){
        const o=document.createElement('option'); o.textContent='No playbooks found'; o.value=''; sel.appendChild(o); sel.disabled=true; return;
      }
      sel.disabled=false;
      AEG.playbooks.forEach(pb=>{
        const o=document.createElement('option'); o.value=pb; o.textContent=pb; sel.appendChild(o);
      });
    }
    fill(s1);
    if(s2) fill(s2);
  }
  if (pbSelect){
    $('#ag-pb-refresh')?.addEventListener('click', async()=>{
      AEG.playbooks = await aeg_list_playbooks();
      renderPlaybooks();
    });
    $('#ag-pb-run')?.addEventListener('click', ()=>{
      const pb = $('#ag-pb-select').value;
      if(!pb){ aegToast('Select a playbook'); return; }
      const servers = AEG.hosts.map(h=>h.name);
      aeg_run_once(pb, servers, 1);
    });
  }

  // ---------- SCHEDULES TAB ----------
  const schTable = $('#ag-table');
  function renderServersSelect(){
    const sel = $('#ag-sch-servers-select');
    if(!sel) return;
    sel.innerHTML='';
    if(!AEG.hosts.length){
      const o=document.createElement('option'); o.value=''; o.textContent='No hosts'; sel.appendChild(o); sel.disabled=true; return;
    }
    sel.disabled=false;
    AEG.hosts.forEach(h=>{
      const o=document.createElement('option'); o.value=h.name; o.textContent=h.name; sel.appendChild(o);
    });
  }
  function renderSchedules(){
    if(!schTable) return;
    const tb = schTable;
    tb.innerHTML='';
    if(!AEG.schedules.length){
      tb.innerHTML = '<tr><td colspan="5">No schedules</td></tr>';
      return;
    }
    AEG.schedules.forEach(s=>{
      const tr = document.createElement('tr');
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
  if (schTable){
    schTable.addEventListener('click',(e)=>{
      const b = e.target.closest('button[data-act]');
      if(!b) return;
      const id = b.dataset.id;
      const act= b.dataset.act;
      if(act==='del-sch'){
        if(!confirm('Delete schedule '+id+'?')) return;
        aeg_delete_schedule(id).then(loadSchedules);
      } else if(act==='edit-sch'){
        const s = AEG.schedules.find(x=>x.id===id); if(!s) return;
        $('#ag-sch-id').value   = s.id || '';
        $('#ag-sch-every').value= s.every || '5m';
        $('#ag-sch-forks').value= s.forks || 1;
        $('#ag-notify-success').checked = !!(s.notify?.on_success);
        $('#ag-notify-fail').checked    = !!(s.notify?.on_fail ?? true);
        $('#ag-notify-change').checked  = !!(s.notify?.only_on_state_change ?? true);
        $('#ag-notify-cooldown').value  = s.notify?.cooldown_min ?? 30;
        $('#ag-notify-quiet').value     = s.notify?.quiet_hours ?? '';
        $('#ag-notify-key').value       = s.notify?.target_key ?? '';
        const pbSel = $('#ag-sch-playbook-select'); if (pbSel) pbSel.value = s.playbook || '';
        const srvSel = $('#ag-sch-servers-select'); if (srvSel){
          const set = new Set((Array.isArray(s.servers)?s.servers:[]).map(String));
          [...srvSel.options].forEach(o=> o.selected = set.has(o.value));
        }
        aegToast('Loaded schedule into editor');
      }
    });
    $('#ag-add')?.addEventListener('click', ()=>{
      const id = $('#ag-sch-id').value.trim();
      if(!id){ aegToast('Schedule id required'); return; }
      const playbook = $('#ag-sch-playbook-select').value;
      if(!playbook){ aegToast('Pick a playbook'); return; }
      const servers = [...$('#ag-sch-servers-select').selectedOptions].map(o=>o.value);
      if(!servers.length){ aegToast('Pick at least one server'); return; }
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
      aeg_save_schedule(sch).then(loadSchedules);
    });
    $('#ag-rescan')?.addEventListener('click', async()=>{
      const [inv, pbs] = await Promise.all([aeg_get_inventory(), aeg_list_playbooks()]);
      AEG.hosts     = parseInventoryIni(inv);
      AEG.playbooks = pbs;
      renderHosts?.(); renderServersSelect(); renderPlaybooks();
      aegToast('Hosts & playbooks refreshed');
    });
  }

  async function loadSchedules(){
    AEG.schedules = await aeg_list_schedules();
    renderSchedules();
  }

  // ---------- RUNS / LOGS TAB ----------
  const runsBody = $('#ag-runs');
  async function renderRuns(){
    if(!runsBody) return;
    runsBody.innerHTML = '<tr><td colspan="7">Loading…</td></tr>';
    const rows = await aeg_runs();
    runsBody.innerHTML='';
    if(!rows.length){ runsBody.innerHTML='<tr><td colspan="7">No runs</td></tr>'; return; }
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
      runsBody.appendChild(tr);
    });
  }
  if (runsBody){
    $('#ag-refresh')?.addEventListener('click', renderRuns);
    $('#ag-meta-refresh')?.addEventListener('click', async()=>{
      const [inv, pbs] = await Promise.all([aeg_get_inventory(), aeg_list_playbooks()]);
      AEG.hosts     = parseInventoryIni(inv);
      AEG.playbooks = pbs;
      renderHosts?.(); renderServersSelect(); renderPlaybooks();
      aegToast('Metadata refreshed');
    });
  }

  // ---------- PLAYBOOK EDITOR (optional tab) ----------
  const peList  = $('#pe-list');
  const peArea  = $('#pe-area');
  if (peList && peArea){
    async function peRefreshList(){
      AEG.playbooks = await aeg_list_playbooks();
      peList.innerHTML='';
      if(!AEG.playbooks.length){ peList.innerHTML='<option value="">No playbooks</option>'; return; }
      AEG.playbooks.forEach(n=>{
        const o = document.createElement('option'); o.value=n; o.textContent=n; peList.appendChild(o);
      });
    }
    async function peOpen(name){
      if(!name){ peArea.value=''; return; }
      try{
        const txt = await jfetch(aegApi('api/aegisops/playbook?name='+encodeURIComponent(name)));
        peArea.value = String(txt||'');
      }catch{ aegToast('Open failed'); }
    }
    async function peSave(name, body){
      try{
        await jfetch(aegApi('api/aegisops/playbook'), {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({name, body})
        });
        aegToast('Playbook saved');
        await peRefreshList();
        peList.value = name;
      }catch{ aegToast('Save failed'); }
    }
    async function peDelete(name){
      if(!name) return;
      try{
        await jfetch(aegApi('api/aegisops/playbook?name='+encodeURIComponent(name)), {method:'DELETE'});
        aegToast('Playbook deleted');
        await peRefreshList();
        peArea.value=''; peList.value='';
      }catch{ aegToast('Delete failed'); }
    }

    $('#pe-open')?.addEventListener('click', ()=> peOpen(peList.value));
    $('#pe-save')?.addEventListener('click', ()=>{
      const name = ($('#pe-new-name')?.value || peList.value || '').trim();
      if(!name){ aegToast('Name required'); return; }
      peSave(name, peArea.value||'');
    });
    $('#pe-delete')?.addEventListener('click', ()=>{
      const name = peList.value;
      if(!name){ aegToast('Pick a playbook first'); return; }
      if(confirm(`Delete "${name}"?`)) peDelete(name);
    });
    peRefreshList(); // initial fill
  }

  // ---------- Initial meta bootstrap (non-destructive) ----------
  (async function bootAegis(){
    // pull inventory + playbooks if any relevant tab exists
    if ($('#ag-hosts') || $('#ag-pb-select') || $('#ag-sch-playbook-select') || $('#ag-sch-servers-select')){
      const [inv, pbs] = await Promise.allSettled([aeg_get_inventory(), aeg_list_playbooks()]);
      if(inv.status==='fulfilled') AEG.hosts = parseInventoryIni(inv.value);
      if(pbs.status==='fulfilled') AEG.playbooks = pbs.value;
      try { /* hosts table may not exist on current tab */ } finally {
        // render if present
        if ($('#ag-hosts')) {
          // re-render with whatever is already wired
          const event = new Event('ag-hosts-render'); // no-op, but keeps symmetry if you listen later
        }
        renderServersSelect();
        renderPlaybooks();
      }
    }
    if ($('#ag-table'))      loadSchedules();
    if ($('#ag-runs'))       renderRuns();
  })();
})();

