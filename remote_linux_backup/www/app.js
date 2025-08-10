
// Helpers
const $ = (sel, el=document) => el.querySelector(sel);
const $$ = (sel, el=document) => Array.from(el.querySelectorAll(sel));
const on = (el, ev, cb) => el && el.addEventListener(ev, cb);
async function fetchJSON(url, opts={}){
  const headers = Object.assign({'Content-Type': 'application/json'}, opts.headers||{});
  const res = await fetch(url, Object.assign({}, opts, {headers}));
  const data = await res.json().catch(()=>({}));
  return data;
}
function logLine(t){ const el = $('#log'); if (!el) return; el.textContent += (t + '\n'); el.scrollTop = el.scrollHeight; }

// Tabs
function showTab(id){
  $$('.tab-panel').forEach(p => p.classList.remove('active'));
  $$('.tab-btn').forEach(b => b.classList.remove('active'));
  const panel = document.getElementById(id);
  const btn = $$(`.tab-btn[data-tab="${id}"]`)[0];
  if(panel) panel.classList.add('active');
  if(btn) btn.classList.add('active');
  localStorage.setItem('rlb_active_tab', id);
  window.scrollTo({top:0, behavior:'smooth'});
}
on(document, 'DOMContentLoaded', () => {
  $$('#tabs .tab-btn').forEach(btn => on(btn, 'click', () => showTab(btn.dataset.tab)));
  const saved = localStorage.getItem('rlb_active_tab'); if (saved && $('#'+saved)) showTab(saved);
});

// Progress polling fallback (no Socket.IO)
setInterval(async () => {
  try {
    const jobs = await fetchJSON('/api/jobs');
    const running = Array.isArray(jobs) && jobs.find(j => j.status === 'running');
    if (running){
      const p = $('#b_progress');
      const pct = Math.max(0, Math.min(100, running.progress||0));
      if (p) p.value = pct; const pctEl = $('#b_progress_pct'); if (pctEl) pctEl.textContent = pct + '%';
    }
  } catch(e){}
}, 1500);

// Backup: populate connections & mounts
async function refreshConnections(){
  const d = await fetchJSON('/api/connections');
  const sel = $('#b_conn'); if (!sel) return;
  sel.innerHTML = '<option value="">-- none --</option>';
  (d.connections||[]).forEach(c => {
    const o = document.createElement('option');
    o.value = c.name; o.textContent = `${c.name} (saved)`;
    o.dataset.host = c.host; o.dataset.port = c.port; o.dataset.username = c.username; o.dataset.password = c.password||'';
    sel.appendChild(o);
  });
}
async function refreshMounts(){
  const d = await fetchJSON('/api/mounts');
  const sel = $('#dest_mount'); if (!sel) return;
  sel.innerHTML = '<option value="">-- select mount --</option>';
  (d.mounts||[]).forEach(m => {
    const o = document.createElement('option');
    const badge = m.mounted ? 'mounted' : (m.last_error ? 'error' : 'not mounted');
    o.value = m.name; o.textContent = `${m.name} (${badge})`;
    sel.appendChild(o);
  });
  // render mounts table with badges and "Use in Destination"
  const tbody = $('#m_table tbody');
  if (tbody){
    tbody.innerHTML = '';
    (d.mounts||[]).forEach(m => {
      const tr = document.createElement('tr');
      const st = m.mounted ? '<span class="badge ok">mounted</span>' : (m.last_error ? `<span class="badge err" title="${m.last_error}">error</span>` : '<span class="badge warn">not mounted</span>');
      tr.innerHTML = `<td>${m.name}</td><td>${m.type}</td><td>${m.host}</td><td>${m.share}</td><td>${st}</td><td>${m.mountpoint||'-'}</td><td>${m.last_error||''}</td>
      <td>
        <button class="small" data-act="use" data-name="${m.name}">Use in Destination</button>
        <button class="small" data-act="mount" data-name="${m.name}">Mount</button>
        <button class="small" data-act="unmount" data-name="${m.name}">Unmount</button>
        <button class="small danger" data-act="delete" data-name="${m.name}">Delete</button>
      </td>`;
      tbody.appendChild(tr);
    });
  }
}

// Backup pickers
function openPicker(kind, opts){
  const modal = $('#picker-modal'); const tbody = $('#picker-table tbody'); const pathEl = $('#picker-path');
  let cwd = opts.startPath || '/'; let lastItems = [];
  async function load(p){
    cwd = p || '/'; pathEl.textContent = cwd; tbody.innerHTML='';
    let resp={ok:false,items:[]};
    try{
      if (kind==='ssh'){
        resp = await fetchJSON('/api/ssh/listdir',{method:'POST',body:JSON.stringify({host:opts.host, port:opts.port||22, username:opts.username, password:opts.password, path:cwd})});
      } else if (kind==='local'){
        resp = await fetchJSON('/api/local/listdir?path='+encodeURIComponent(cwd));
      } else if (kind==='mount'){
        resp = await fetchJSON('/api/mounts/listdir',{method:'POST',body:JSON.stringify({name:opts.name, path:cwd})});
      }
    }catch(e){}
    if(!resp.ok){ alert('Browse failed: '+(resp.error||'')); return; }
    lastItems = resp.items||[];
    const up = document.createElement('tr'); up.innerHTML='<td>..</td><td>dir</td><td></td>'; up.dataset.up='1'; tbody.appendChild(up);
    lastItems.forEach(it=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${it.name}</td><td>${it.dir?'dir':'file'}</td><td>${it.dir?'':(it.size||'')}</td>`;
      tr.dataset.name=it.name; tr.dataset.dir = it.dir?'1':'0'; tbody.appendChild(tr);
    });
  }
  function parentOf(p){ const x = p.replace(/\/+$/,'').split('/'); x.pop(); return x.join('/')||'/'; }
  on(tbody,'click', ev => {
    const tr = ev.target.closest('tr'); if(!tr) return;
    if (tr.dataset.up==='1'){ load(parentOf(cwd)); return; }
    if (tr.dataset.dir==='1'){ const np = (cwd==='/'? '' : cwd) + '/' + tr.dataset.name; load(np.replace(/\/+/g,'/')); }
  });
  $('#picker-up').onclick = ()=> load(parentOf(cwd));
  $('#picker-select').onclick = ()=>{ modal.classList.add('hidden'); opts.onSelect && opts.onSelect(cwd); };
  $('#picker-close').onclick = ()=> modal.classList.add('hidden');
  modal.classList.remove('hidden'); load(cwd);
}

// Event wiring
on(document,'DOMContentLoaded', () => {
  // Tabs already set
  // Explain step lights
  function updateExplain(){
    const srcType = $('#b_src_type').value;
    const mode = $('#b_mode').value;
    const destType = $('#dest_type').value;
    $('#step-source').classList.toggle('active', !!srcType);
    $('#step-mode').classList.toggle('active', !!mode);
    $('#step-destination').classList.toggle('active', !!destType);
  }
  ['b_src_type','b_mode','dest_type'].forEach(id => on($('#'+id),'change', updateExplain)); updateExplain();

  // Bandwidth slider sync
  const num = $('#b_bwlimit'); const rng = $('#b_bw_slider');
  if (num && rng){ const clamp = v=>Math.max(0,Math.min(200, v)); on(rng,'input',()=>{num.value=clamp(rng.value)}); on(num,'input',()=>{rng.value=clamp(num.value||0)}); }

  // Connections dropdown and Use button
  refreshConnections();
  on($('#b_conn_use'),'click', ()=>{
    const sel = $('#b_conn'); const opt = sel && sel.options[sel.selectedIndex];
    if (!opt || !opt.dataset.host){ alert('Select a saved connection first.'); return; }
    $('#b_host').value = opt.dataset.host || '';
    $('#b_user').value = opt.dataset.username || '';
    $('#b_pass').value = opt.dataset.password || '';
  });

  // Mounts
  refreshMounts();

  // Backup buttons
  on($('#b_browse'),'click', ()=>{
    openPicker('ssh', {host:$('#b_host').value, username:$('#b_user').value, password:$('#b_pass').value, startPath: $('#b_src').value || '/', onSelect:(p)=>$('#b_src').value=p});
  });
  on($('#b_pick_local'),'click', ()=> openPicker('local',{startPath:'/config', onSelect:(p)=>$('#b_src').value=p}));
  on($('#b_pick_mount'),'click', ()=>{
    const name = prompt('Enter saved mount name'); if(!name) return;
    openPicker('mount', {name, startPath:'/', onSelect:(p)=>$('#b_src').value=p});
  });
  on($('#b_test'),'click', async ()=>{
    const r = await fetchJSON('/api/ssh/test',{method:'POST', body: JSON.stringify({host:$('#b_host').value, port:22, username:$('#b_user').value, password:$('#b_pass').value})});
    alert(r.ok ? 'SSH connection OK' : ('SSH failed: '+(r.error||'')));
  });
  on($('#b_estimate'),'click', async ()=>{
    const mode = $('#b_mode').value;
    if (mode==='rsync'){
      const r = await fetchJSON('/api/estimate/ssh_size',{method:'POST',body:JSON.stringify({host:$('#b_host').value, port:22, username:$('#b_user').value, password:$('#b_pass').value, path:$('#b_src').value||'/'})});
      alert(r.ok ? ('Estimated '+ r.bytes +' bytes') : ('Failed: '+(r.error||'')));
    } else if (mode==='copy_mount'){
      const name = prompt('Mount name to estimate?'); if(!name) return;
      const r = await fetchJSON('/api/estimate/mount_size?name='+encodeURIComponent(name)+'&path='+encodeURIComponent($('#b_src').value||'/'));
      alert(r.ok ? ('Estimated '+ r.bytes +' bytes') : ('Failed: '+(r.error||'')));
    } else {
      const r = await fetchJSON('/api/estimate/local_size?path='+encodeURIComponent($('#b_src').value||'/config'));
      alert(r.ok ? ('Estimated '+ r.bytes +' bytes') : ('Failed: '+(r.error||'')));
    }
  });
  on($('#b_start'),'click', async ()=>{
    const bwKB = Math.round((parseFloat($('#b_bwlimit').value)||0)*1024);
    const body = {mode: $('#b_mode').value, label: $('#b_label').value.trim(), bwlimit_kbps: bwKB, dest_type: $('#dest_type').value, dest_mount_name: $('#dest_mount').value, dest_subdir: $('#dest_subdir').value.trim()};
    const mode = body.mode;
    if (mode==='rsync'){ Object.assign(body, {host:$('#b_host').value, port:22, username:$('#b_user').value, password:$('#b_pass').value, source_path: $('#b_src').value||'/'}); }
    if (mode==='copy_local'){ Object.assign(body, {source_path: $('#b_src').value||'/config'}); }
    if (mode==='copy_mount'){ const name = prompt('Enter saved mount name to read from'); if(!name){alert('Mount name required'); return;} Object.assign(body, {mount_name:name, source_path: $('#b_src').value||'/'}); }
    if (mode==='image'){ Object.assign(body, {host:$('#b_host').value, port:22, username:$('#b_user').value, password:$('#b_pass').value, device: $('#b_src').value||'/dev/sda'}); }
    const r = await fetchJSON('/api/backup/start',{method:'POST', body: JSON.stringify(body)});
    if (!r.ok){ alert('Start failed: '+(r.error||'')); return; }
    logLine('Job started: '+ r.job_id);
  });
  on($('#b_cancel'),'click', async ()=>{
    await fetchJSON('/api/jobs/cancel', {method:'POST'}).catch(()=>{});
  });

  // Connections tab
  async function loadConnTable(){
    const d = await fetchJSON('/api/connections');
    const tbody = $('#c_table tbody'); tbody.innerHTML='';
    (d.connections||[]).forEach(c => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${c.name}</td><td>${c.host}</td><td>${c.port}</td><td>${c.username}</td>
      <td><button class="small" data-name="${c.name}" data-act="del">Delete</button></td>`;
      tbody.appendChild(tr);
    });
  }
  on($('#c_save'),'click', async ()=>{
    const body = {name:$('#c_name').value.trim(), host:$('#c_host').value.trim(), port:parseInt($('#c_port').value||'22',10), username:$('#c_user').value.trim(), password:$('#c_pass').value};
    await fetchJSON('/api/connections/save',{method:'POST', body: JSON.stringify(body)});
    await refreshConnections(); await loadConnTable();
  });
  on($('#c_refresh'),'click', ()=>{ refreshConnections(); loadConnTable(); });
  on($('#c_test'),'click', async ()=>{
    const r = await fetchJSON('/api/ssh/test',{method:'POST', body: JSON.stringify({host:$('#c_host').value, port:parseInt($('#c_port').value||'22',10), username:$('#c_user').value, password:$('#c_pass').value})});
    alert(r.ok ? 'SSH OK' : ('SSH failed: '+(r.error||'')));
  });
  on($('#c_table'),'click', async (ev)=>{
    const b = ev.target.closest('button[data-act="del"]'); if(!b) return;
    await fetchJSON('/api/connections/delete',{method:'POST', body: JSON.stringify({name:b.dataset.name})});
    await refreshConnections(); await loadConnTable();
  });
  loadConnTable();

  // Mounts tab
  let foundShares = [];
  on($('#m_connect'),'click', async ()=>{
    const type = $('#m_type').value; const host = $('#m_host').value.trim();
    if (!host) return alert('Enter host first');
    if (type==='smb'){
      const r = await fetchJSON('/api/smb/shares',{method:'POST', body: JSON.stringify({host, username:$('#m_user').value, password:$('#m_pass').value})});
      if (!r.ok) return alert('SMB query failed: ' + (r.error||''));
      foundShares = r.shares||[];
      alert(foundShares.length? ('Shares: '+foundShares.join(', ')) : 'No shares found');
    } else {
      const r = await fetchJSON('/api/nfs/exports',{method:'POST', body: JSON.stringify({host})});
      if (!r.ok) return alert('NFS query failed: ' + (r.error||''));
      foundShares = r.exports||[]; alert(foundShares.length? ('Exports: '+foundShares.join(', ')) : 'No exports found');
    }
  });
  on($('#m_pick_share'),'click', ()=>{
    if (!foundShares.length) return alert('Click Connect first'); const s = prompt('Choose:
' + foundShares.join('\n')); if (s) $('#m_share').value = s;
  });
  on($('#m_test'),'click', async ()=>{
    const type = $('#m_type').value, host=$('#m_host').value.trim(), share=$('#m_share').value.trim();
    const body = {type, host, share, username:$('#m_user').value, password:$('#m_pass').value, options:$('#m_opts').value};
    const r = await fetchJSON('/api/mounts/test', {method:'POST', body: JSON.stringify(body)});
    alert(r.ok ? 'Access OK' : ('Test failed: '+(r.error||'')));
  });
  on($('#m_save'),'click', async ()=>{
    const body = {name:$('#m_name').value.trim(), type:$('#m_type').value, host:$('#m_host').value.trim(), share:$('#m_share').value.trim(), username:$('#m_user').value, password:$('#m_pass').value, options:$('#m_opts').value, auto_retry: $('#m_retry').value==='1'};
    await fetchJSON('/api/mounts/save',{method:'POST', body: JSON.stringify(body)});
    await refreshMounts();
  });
  on($('#m_refresh'),'click', ()=> refreshMounts());
  on($('#m_table'),'click', async (ev)=>{
    const b = ev.target.closest('button'); if (!b) return;
    const name = b.dataset.name;
    if (b.dataset.act==='use'){ $('#dest_type').value='mount'; await refreshMounts(); $('#dest_mount').value=name; showTab('tab-backup'); }
    if (b.dataset.act==='mount'){ await fetchJSON('/api/mounts/mount',{method:'POST', body: JSON.stringify({name})}); await refreshMounts(); }
    if (b.dataset.act==='unmount'){ await fetchJSON('/api/mounts/unmount',{method:'POST', body: JSON.stringify({name})}); await refreshMounts(); }
    if (b.dataset.act==='delete'){ await fetchJSON('/api/mounts/delete',{method:'POST', body: JSON.stringify({name})}); await refreshMounts(); }
  });

  // Backups list (placeholder; relies on server existing API)
  async function loadBackups(){
    try{
      const d = await fetchJSON('/api/backups');
      const tbody = $('#bk_table tbody'); tbody.innerHTML='';
      (d.items||[]).forEach(bk => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${bk.label||''}</td><td>${bk.date||''}</td><td>${bk.type||''}</td><td>${bk.size||''}</td><td>${bk.location||''}</td>
          <td><button class="small" data-id="${bk.id}" data-act="dl">Download</button>
          <button class="small" data-id="${bk.id}" data-act="del">Delete</button>
          <button class="small" data-id="${bk.id}" data-act="rerun">Re-run</button></td>`;
        tbody.appendChild(tr);
      });
    }catch(e){}
  }
  on($('#bk_table'),'click', async (ev)=>{
    const b = ev.target.closest('button'); if(!b) return;
    if (b.dataset.act==='rerun'){ await fetchJSON('/api/jobs/rerun',{method:'POST', body: JSON.stringify({id:b.dataset.id})}); }
    if (b.dataset.act==='del'){ await fetchJSON('/api/backups/delete',{method:'POST', body: JSON.stringify({id:b.dataset.id})}); await loadBackups(); }
    if (b.dataset.act==='dl'){ window.location = '/api/backups/download?id='+encodeURIComponent(b.dataset.id); }
  });
  loadBackups();

  // Schedule
  async function loadSched(){
    const d = await fetchJSON('/api/schedules');
    const tbody = $('#sch_table tbody'); tbody.innerHTML='';
    (d.schedules||[]).forEach(e => {
      const nr = e.next_run ? new Date(e.next_run*1000).toLocaleString() : '-';
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${e.name||''}</td><td>${e.freq||''}</td><td>${e.time||''}</td><td>${nr}</td><td><code>${(e.template&&e.template.mode)||''}</code></td><td>${e.enabled?'Yes':'No'}</td>
      <td><button class="small" data-run="${e.id}">Run now</button> <button class="small danger" data-del="${e.id}">Delete</button></td>`;
      tbody.appendChild(tr);
    });
  }
  on($('#sch_add'),'click', async ()=>{
    const e = {
      name: $('#sch_name').value.trim(), freq: $('#sch_freq').value, time: $('#sch_time').value.trim(),
      dow: $('#sch_freq').value==='weekly'? parseInt($('#sch_day').value||'0',10):null,
      dom: $('#sch_freq').value==='monthly'? parseInt($('#sch_day').value||'1',10):null,
      enabled: $('#sch_enabled').value==='1',
      template: {
        mode: $('#sch_mode').value, label: $('#sch_label').value.trim(), bwlimit_kbps: parseInt($('#sch_bw').value||'0',10),
        host: $('#sch_host').value.trim(), port: parseInt($('#sch_port').value||'22',10), username: $('#sch_user').value.trim(), password: $('#sch_pass').value,
        source_path: $('#sch_src').value.trim(), device: $('#sch_src').value.trim(), mount_name: $('#sch_mount').value.trim(),
        dest_type: $('#sch_dest_type').value, dest_mount_name: $('#sch_dest_mount').value.trim(), dest_subdir: $('#sch_dest_subdir').value.trim()
      }
    };
    const r = await fetchJSON('/api/schedules', {method:'POST', body: JSON.stringify(e)});
    if (!r.ok){ alert('Save failed'); return; }
    loadSched();
  });
  on($('#sch_table'),'click', async (ev)=>{
    const b = ev.target.closest('button'); if(!b) return;
    if (b.dataset.run){ await fetchJSON('/api/schedules/run_now', {method:'POST', body: JSON.stringify({id:b.dataset.run})}); }
    if (b.dataset.del){ await fetchJSON('/api/schedules/delete', {method:'POST', body: JSON.stringify({id:b.dataset.del})}); }
    loadSched();
  });
  loadSched();

  // Notifications
  async function loadN(){
    const d = await fetchJSON('/api/notify/config');
    $('#n_enabled').value = d.enabled ? '1':'0';
    $('#n_url').value = d.url||'';
    $('#n_token').value = d.token||'';
    $('#n_priority').value = d.priority||5;
  }
  on($('#n_save'),'click', async ()=>{
    const body = {enabled: $('#n_enabled').value==='1', url: $('#n_url').value.trim(), token: $('#n_token').value.trim(), priority: parseInt($('#n_priority').value||'5',10)};
    await fetchJSON('/api/notify/config', {method:'POST', body: JSON.stringify(body)});
    alert('Saved.');
  });
  on($('#n_test'),'click', async ()=>{
    const r = await fetchJSON('/api/notify/test', {method:'POST'});
    alert(r.ok ? 'Sent' : ('Failed: '+(r.info||'')));
  });
  on($('#sys_apt'),'click', async ()=>{
    $('#sys_log').textContent = 'Running apt update/upgrade...'; const r = await fetchJSON('/api/system/apt_upgrade', {method:'POST'});
    $('#sys_log').textContent = r.ok ? r.output : ('Failed: ' + (r.error||'') + '\n' + (r.output||''));
  });
  loadN();
});
