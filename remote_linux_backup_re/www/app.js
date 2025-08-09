async function api(path, opts={}) {
  const headers = opts.headers || {};
  if (!headers["Content-Type"] && opts.method && opts.method.toUpperCase() === "POST") {
    headers["Content-Type"] = "application/json";
  }
  const r = await fetch(path, Object.assign({headers}, opts));
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
function $(id){ return document.getElementById(id); }
function showTab(id){
  document.querySelectorAll('.card').forEach(c => c.style.display = 'none');
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  $(id).style.display = 'block';
  document.querySelector(`.tab[data-target="${id}"]`).classList.add('active');
}

/* ---- Global state ---- */
let mounts = [];
let servers = [];

/* ---- Helper UI fillers ---- */
function fillTargets(){
  const sel = $('b_store');
  const current = sel.value;
  sel.innerHTML = '';
  const opt1 = document.createElement('option'); opt1.value = '/backup'; opt1.textContent = '/backup (local)'; sel.appendChild(opt1);
  mounts.filter(m=>m.mounted).forEach(m=>{
    const o = document.createElement('option'); o.value = m.mount; o.textContent = `${m.name || m.mount} (${m.mount})`;
    sel.appendChild(o);
  });
  if (current) sel.value = current;
  $('b_store_status').textContent = (mounts.find(x=>x.mount===sel.value)?.mounted ? 'Mounted' : '—');
}

function fillServersDropdowns(){
  function put(selectId){
    const sel = $(selectId);
    const current = sel.value;
    sel.innerHTML = '';
    const blank = document.createElement('option'); blank.value = ''; blank.textContent = '— choose —';
    sel.appendChild(blank);
    servers.forEach(s=>{
      const o = document.createElement('option');
      o.value = JSON.stringify(s);
      o.textContent = `${s.name || s.host} (${s.username}@${s.host}:${s.port})`;
      sel.appendChild(o);
    });
    if (current) sel.value = current;
  }
  put('b_server'); put('r_server');
}

function applyServer(selectId, prefix){
  const sel = $(selectId);
  if (!sel.value) return;
  const s = JSON.parse(sel.value);
  $(prefix+'_host').value = s.host || '';
  $(prefix+'_user').value = s.username || 'root';
  $(prefix+'_port').value = s.port || 22;
  if (s.save_password && s.password) $(prefix+'_pass').value = s.password;
}

/* ---- Options ---- */
async function loadOptions(){
  const d = await api('/api/options');
  $('s_ui_port').value = d.ui_port ?? 8066;
  $('s_gotify_url').value = d.gotify_url || '';
  $('s_gotify_token').value = d.gotify_token || '';
  $('s_dropbox_enabled').value = String(!!d.dropbox_enabled);
  $('s_dropbox_remote').value = d.dropbox_remote || 'dropbox:HA-Backups';
  $('dropbox_hint').textContent = d.rclone_config_exists ? 'rclone config found at /config/rclone.conf' : 'No /config/rclone.conf found. Run "rclone config" and ensure the file is at /config/rclone.conf.';
}

/* ---- Mounts ---- */
async function refreshMounts(){
  const res = await api('/api/mounts');
  mounts = res.items || [];
  $('mounts_json_hidden').value = JSON.stringify(mounts, null, 2);

  // table
  const body = $('mount_rows'); body.innerHTML = '';
  mounts.forEach((m, idx)=>{
    const tr = document.createElement('tr');
    const status = m.mounted ? '🟢 mounted' : '🔴 not mounted';
    tr.innerHTML = `<td>${m.name||''}</td><td>${m.proto}</td><td>${m.server}/${m.share}</td><td>${m.mount}</td><td>${m.auto_mount?'yes':'no'}</td><td>${status}</td><td></td>`;
    const td = tr.lastChild;

    // Mount
    const mBtn = document.createElement('button'); mBtn.className='btn'; mBtn.textContent='Mount';
    mBtn.onclick = async()=>{ await api('/api/mounts/mount',{method:'POST',body:JSON.stringify({entry:m})}); await refreshMounts(); fillTargets(); };
    td.appendChild(mBtn);

    // Unmount
    const uBtn = document.createElement('button'); uBtn.className='btn secondary'; uBtn.style.marginLeft='6px'; uBtn.textContent='Unmount';
    uBtn.onclick = async()=>{ await api('/api/mounts/unmount',{method:'POST',body:JSON.stringify({mount:m.mount})}); await refreshMounts(); fillTargets(); };
    td.appendChild(uBtn);

    // Delete
    const dBtn = document.createElement('button'); dBtn.className='btn warn'; dBtn.style.marginLeft='6px'; dBtn.textContent='Delete';
    dBtn.onclick = async()=> {
      if (!confirm(`Delete mount preset "${m.name||m.mount}"?`)) return;
      mounts.splice(idx,1);
      await api('/api/mounts', {method:'POST', body: JSON.stringify({mounts})});
      await refreshMounts(); fillTargets();
    };
    td.appendChild(dBtn);

    // Quick-fill form on row click
    tr.style.cursor='pointer';
    tr.onclick = () => {
      $('m_name').value = m.name || '';
      $('m_proto').value = m.proto || 'cifs';
      $('m_server').value = m.server || '';
      $('m_share').value = m.share || '';
      $('m_user').value = m.username || '';
      $('m_pass').value = m.password || '';
      $('m_mount').value = m.mount || '';
      $('m_opts').value = m.options || '';
      $('m_auto').checked = !!m.auto_mount;
    };

    body.appendChild(tr);
  });

  fillTargets();
}

function formMount() {
  const name = $('m_name').value.trim();
  const mount = ($('m_mount').value.trim()) || (name ? `/mnt/${name}` : '');
  return {
    name,
    proto: $('m_proto').value,
    server: $('m_server').value.trim(),
    share: $('m_share').value.trim(),
    mount,
    username: $('m_user').value.trim(),
    password: $('m_pass').value,
    options: $('m_opts').value.trim(),
    auto_mount: $('m_auto').checked
  };
}

async function saveMounts(){
  await api('/api/mounts', {method:'POST', body: JSON.stringify({mounts})});
}

/* ---- Servers ---- */
async function refreshServers(){
  const res = await api('/api/servers');
  servers = res.items || [];
  fillServersDropdowns();

  const body = $('servers_rows'); body.innerHTML = '';
  servers.forEach((s, idx)=>{
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${s.name||''}</td><td>${s.host}</td><td>${s.username}</td><td>${s.port}</td><td>${s.save_password?'yes':'no'}</td><td></td>`;
    const td = tr.lastChild;

    // Use → copies to Backup form
    const useBtn = document.createElement('button'); useBtn.className='btn'; useBtn.textContent='Use';
    useBtn.onclick = ()=>{
      $('b_server').value = JSON.stringify(s);
      applyServer('b_server','b');
      showTab('tab-backup');
    };
    td.appendChild(useBtn);

    // Edit → fills Servers form (reuse Backup inputs)
    const editBtn = document.createElement('button'); editBtn.className='btn secondary'; editBtn.style.marginLeft='6px'; editBtn.textContent='Edit';
    editBtn.onclick = ()=>{
      $('b_name').value = s.name || '';
      $('b_host').value = s.host; $('b_user').value = s.username; $('b_port').value = s.port;
      if (s.save_password && s.password) $('b_pass').value = s.password;
      showTab('tab-backup');
    };
    td.appendChild(editBtn);

    // Delete
    const delBtn = document.createElement('button'); delBtn.className='btn warn'; delBtn.style.marginLeft='6px'; delBtn.textContent='Delete';
    delBtn.onclick = async()=>{
      if (!confirm(`Delete server preset "${s.name||s.host}"?`)) return;
      servers.splice(idx,1);
      await api('/api/servers', {method:'POST', body: JSON.stringify({servers})});
      await refreshServers();
    };
    td.appendChild(delBtn);

    body.appendChild(tr);
  });
}

$('btn_add_server_from_backup')?.addEventListener('click', async e=>{
  e.preventDefault();
  const name = $('b_name').value.trim() || $('b_host').value.trim();
  if (!name) { alert('Set a Backup name or Host first.'); return; }
  const s = { name, host:$('b_host').value.trim(), username:$('b_user').value.trim()||'root', port:parseInt($('b_port').value||'22',10), save_password: !!$('b_save_pw').checked, password: $('b_save_pw').checked ? $('b_pass').value : '' };
  const i = servers.findIndex(x=>x.host===s.host && x.username===s.username && x.port===s.port);
  if (i>=0) servers[i] = {...servers[i], ...s}; else servers.push(s);
  await api('/api/servers', {method:'POST', body: JSON.stringify({servers})});
  await refreshServers();
});

/* ---- Settings ---- */
async function saveOptions(){
  const payload = {
    gotify_url: $('s_gotify_url').value.trim(),
    gotify_token: $('s_gotify_token').value.trim(),
    dropbox_enabled: $('s_dropbox_enabled').value === 'true',
    dropbox_remote: $('s_dropbox_remote').value.trim()
  };
  const res = await api('/api/options', {method:'POST', body: JSON.stringify(payload)});
  $('s_status').value = res.ok ? 'Saved settings.\n' + JSON.stringify(res.config, null, 2) : 'Failed to save.';
}
async function testGotify(){ const r = await api('/api/gotify_test', {method:'POST', body:'{}'}); $('s_status').value = r.ok ? 'Gotify test sent (if configured).' : 'Gotify test failed.'; }
async function testDropbox(){ const r = await api('/api/dropbox_test', {method:'POST', body:'{}'}); $('s_status').value = JSON.stringify(r, null, 2); }

/* ---- Backup/Restore actions ---- */
async function probeHost(){
  const payload = { host:$('b_host').value, username:$('b_user').value, password:$('b_pass').value, port:parseInt($('b_port').value||'22',10) };
  const res = await api('/api/probe_host', {method:'POST', body: JSON.stringify(payload)});
  $('b_result').value = res.out || JSON.stringify(res,null,2);
}
async function installTools(){
  const payload = { host:$('b_host').value, username:$('b_user').value, password:$('b_pass').value, port:parseInt($('b_port').value||'22',10) };
  const res = await api('/api/install_tools', {method:'POST', body: JSON.stringify(payload)});
  $('b_result').value = res.out || JSON.stringify(res,null,2);
}
async function estimateTime(){
  const payload = {
    method:$('b_method').value, username:$('b_user').value, host:$('b_host').value, password:$('b_pass').value,
    port:parseInt($('b_port').value||'22',10), disk:$('b_disk').value, files:'/etc', bwlimit_kbps:parseInt($('b_bw').value||'0',10)
  };
  const res = await api('/api/estimate_backup', {method:'POST', body: JSON.stringify(payload)});
  $('b_result').value = JSON.stringify(res, null, 2);
}
async function runBackup(){
  const payload = {
    method:$('b_method').value, username:$('b_user').value, host:$('b_host').value, password:$('b_pass').value,
    port:parseInt($('b_port').value||'22',10),
    disk:$('b_disk').value, store_to:$('b_store').value, cloud_upload:$('b_cloud').value,
    excludes:$('b_excl').value, bwlimit_kbps:parseInt($('b_bw').value||'0',10),
    retention_days:parseInt($('b_ret').value||'0',10),
    verify:$('b_verify').checked, backup_name:$('b_name').value,
    remember_server:true, save_password:$('b_save_pw').checked
  };
  const res = await api('/api/run_backup', {method:'POST', body: JSON.stringify(payload)});
  $('b_result').value = res.out || JSON.stringify(res,null,2);
  await backupsRefresh(); await refreshServers();
}
async function runRestore(){
  const method = $('r_method').value;
  const payload = {
    method, username:$('r_user').value, host:$('r_host').value, password:$('r_pass').value,
    port:parseInt($('r_port').value||'22',10),
    image_path:$('r_image').value, disk:$('r_disk').value,
    local_src:$('r_local_src').value, remote_dest:$('r_remote_dest').value,
    excludes:$('r_excl').value, bwlimit_kbps:parseInt($('r_bw').value||'0',10)
  };
  const res = await api('/api/run_restore', {method:'POST', body: JSON.stringify(res ? res : payload)});
  $('r_result').value = res.out || JSON.stringify(res,null,2);
}

/* ---- Backups & Explorer ---- */
function fmtDate(ts){ const d=new Date(ts*1000); return d.toISOString().replace('T',' ').slice(0,19); }
async function backupsRefresh(){
  const data = await api('/api/backups');
  const body = $('backups_rows'); body.innerHTML="";
  data.items.sort((a,b)=>b.created-a.created).forEach(x=>{
    const tr=document.createElement('tr');
    tr.innerHTML = `<td>${x.path}</td><td>${x.kind}</td><td>${x.host||""}</td><td>${(x.size/1048576).toFixed(1)} MB</td><td>${fmtDate(x.created)}</td><td></td>`;
    const td = tr.lastChild;
    const dl = document.createElement('a'); dl.className="btn"; dl.textContent="Download"; dl.href=`/api/download?path=${encodeURIComponent(x.path)}`; dl.target="_blank";
    const del = document.createElement('button'); del.className="btn warn"; del.textContent="Delete";
    del.onclick = async ()=>{ if(confirm(`Delete ${x.path}?`)){ await api('/api/backups/delete',{method:'POST',body:JSON.stringify({path:x.path})}); await backupsRefresh(); }};
    td.appendChild(dl); td.appendChild(document.createTextNode(" ")); td.appendChild(del);
    body.appendChild(tr);
  });
}

async function browseImage(){
  let roots = ['/backup']; mounts.filter(m=>m.mounted).forEach(m=>roots.push(m.mount));
  const root = prompt("Browse which root?\n" + roots.join("\n"), roots[0]);
  if(!root) return;
  const res = await api('/api/ls?path='+encodeURIComponent(root));
  const files = res.items.filter(it=>!it.is_dir).map(it=>it.path);
  const pick = prompt("Pick file (copy/paste path):\n"+files.join("\n"));
  if(pick) $('r_image').value = pick;
}

/* ---- Wire up ---- */
function wire(){
  document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => showTab(t.dataset.target)));

  // Settings
  $('btn_save_settings').addEventListener('click', (e)=>{ e.preventDefault(); saveOptions().catch(err=>{$('s_status').value='Error: '+err.message;}); });
  $('btn_test_gotify').addEventListener('click', (e)=>{ e.preventDefault(); testGotify().catch(err=>{$('s_status').value='Error: '+err.message;}); });
  $('btn_test_dropbox').addEventListener('click', (e)=>{ e.preventDefault(); testDropbox().catch(err=>{$('s_status').value='Error: '+err.message;}); });

  // Backup
  $('btn_probe').addEventListener('click', (e)=>{ e.preventDefault(); probeHost().catch(console.error); });
  $('btn_install').addEventListener('click', (e)=>{ e.preventDefault(); installTools().catch(console.error); });
  $('btn_estimate').addEventListener('click', (e)=>{ e.preventDefault(); estimateTime().catch(console.error); });
  $('btn_run_backup').addEventListener('click', (e)=>{ e.preventDefault(); runBackup().catch(console.error); });
  $('b_server').addEventListener('change', ()=>applyServer('b_server','b'));

  // Store-to quick actions
  $('btn_store_mount').addEventListener('click', async e => {
    e.preventDefault();
    const m = mounts.find(x => x.mount === $('b_store').value);
    if (!m) { $('b_store_status').textContent = 'Not a preset; nothing to mount.'; return; }
    const r = await api('/api/mounts/mount', {method:'POST', body: JSON.stringify({entry:m})});
    $('b_store_status').textContent = r.ok ? 'Mounted' : ('Failed: ' + r.out);
    await refreshMounts(); fillTargets();
  });
  $('btn_store_unmount').addEventListener('click', async e => {
    e.preventDefault();
    const path = $('b_store').value;
    const r = await api('/api/mounts/unmount', {method:'POST', body: JSON.stringify({mount:path})});
    $('b_store_status').textContent = r.ok ? 'Unmounted' : ('Failed: ' + r.out);
    await refreshMounts(); fillTargets();
  });

  // Restore
  $('btn_run_restore').addEventListener('click', (e)=>{ e.preventDefault(); runRestore().catch(console.error); });
  $('r_server').addEventListener('change', ()=>applyServer('r_server','r'));
  $('btn_browse_image').addEventListener('click', (e)=>{ e.preventDefault(); browseImage().catch(console.error); });

  // Mounts form
  $('btn_add_mount').addEventListener('click', async (e) => {
    e.preventDefault();
    const m = formMount();
    if (!m.name || !m.proto || !m.server || !m.share) { alert('Name, protocol, server, share are required.'); return; }
    const i = mounts.findIndex(x => (x.name && x.name===m.name) || x.mount===m.mount);
    if (i >= 0) mounts[i] = {...mounts[i], ...m}; else mounts.push(m);
    await api('/api/mounts', {method:'POST', body: JSON.stringify({mounts})});
    await refreshMounts(); fillTargets();
    $('b_store').value = m.mount;
  });
  $('btn_save_mounts').addEventListener('click', async (e)=>{ e.preventDefault(); await api('/api/mounts', {method:'POST', body: JSON.stringify({mounts})}); await refreshMounts(); });

  $('btn_refresh_mounts').addEventListener('click', (e)=>{ e.preventDefault(); refreshMounts().catch(console.error); });

  // Servers
  $('btn_refresh_servers').addEventListener('click', (e)=>{ e.preventDefault(); refreshServers().catch(console.error); });
  $('btn_add_server_from_backup').addEventListener('click', async e=>{
    e.preventDefault();
    const name = $('b_name').value.trim() || $('b_host').value.trim();
    if (!name) { alert('Set a Backup name or Host first.'); return; }
    const s = { name, host:$('b_host').value.trim(), username:$('b_user').value.trim()||'root', port:parseInt($('b_port').value||'22',10), save_password: !!$('b_save_pw').checked, password: $('b_save_pw').checked ? $('b_pass').value : '' };
    const i = servers.findIndex(x=>x.host===s.host && x.username===s.username && x.port===s.port);
    if (i>=0) servers[i] = {...servers[i], ...s}; else servers.push(s);
    await api('/api/servers', {method:'POST', body: JSON.stringify({servers})});
    await refreshServers();
  });

  // Initial load
  Promise.all([loadOptions(), refreshMounts(), refreshServers(), backupsRefresh()]).then(()=>{
    fillTargets(); fillServersDropdowns();
  });
}
document.addEventListener('DOMContentLoaded', wire);
