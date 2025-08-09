/* small helper */
async function api(path, opts={}) {
  const headers = opts.headers || {};
  if (!headers["Content-Type"] && opts.body) headers["Content-Type"] = "application/json";
  const r = await fetch(path, {...opts, headers});
  let text = await r.text();
  let json; try { json = text ? JSON.parse(text) : {}; } catch { json = {ok:false, raw:text}; }
  if (!r.ok) return Promise.resolve(json || {ok:false});
  return json || {ok:true};
}
const $ = s => document.querySelector(s);
const $id = s => document.getElementById(s);

/* tabs */
function showTab(name){
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('is-active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('is-active'));
  $(`#panel-${name}`).classList.add('is-active');
  document.querySelector(`.tab[data-target="${name}"]`).classList.add('is-active');
}
document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>showTab(t.dataset.target)));

/* Show/hide dd/rsync specific fields */
function applyMethodVisibility(prefix){
  const method = $id(`${prefix}_method`).value;
  document.querySelectorAll(`#panel-${prefix} [data-show]`).forEach(el=>{
    el.style.display = (el.getAttribute('data-show')===method) ? '' : 'none';
  });
}
['b','r'].forEach(p=>{
  $id(`${p}_method`)?.addEventListener('change',()=>applyMethodVisibility(p));
  applyMethodVisibility(p);
});

/* Status box helper */
function setStatus(obj) {
  $id('status_box').value = (typeof obj === 'string') ? obj : JSON.stringify(obj,null,2);
}

/* ---------- Settings ---------- */
async function loadOptions(){
  const j = await api('/api/options');
  $id("s_gurl").value = j.gotify_url || "";
  $id("s_gtoken").value = j.gotify_token || "";
  $id("s_gen").value = String(!!j.gotify_enabled);
  $id("s_dben").value = String(!!j.dropbox_enabled);
  $id("s_dropremote").value = j.dropbox_remote || "dropbox:HA-Backups";
  $id("s_uiport").value = j.ui_port || 8066;
}
$id("btnSaveSettings").onclick = async ()=>{
  const body = {
    gotify_url:$id("s_gurl").value.trim(),
    gotify_token:$id("s_gtoken").value.trim(),
    gotify_enabled:($id("s_gen").value==="true"),
    dropbox_enabled:($id("s_dben").value==="true"),
    dropbox_remote:$id("s_dropremote").value.trim(),
    ui_port:parseInt($id("s_uiport").value||"8066",10)
  };
  const j = await api('/api/options',{method:'POST',body:JSON.stringify(body)});
  setStatus(j);
};
$id("btnTestGotify").onclick = async ()=>{
  const body = { url:$id("s_gurl").value.trim(), token:$id("s_gtoken").value.trim(), insecure:true };
  const j = await api('/api/gotify_test',{method:'POST',body:JSON.stringify(body)});
  setStatus(j);
};

/* ---------- Mounts ---------- */
let mounts = [];
async function refreshMounts(){
  const j = await api('/api/mounts');
  mounts = j.mounts || j.items || [];
  const tb = $id('mountTable'); tb.innerHTML = '';
  mounts.forEach(m=>{
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${m.name||""}</td><td>${m.proto}</td><td>${m.server}</td><td>${m.share}</td>
      <td>${m.mount}</td><td>${m.auto_mount?'Yes':'No'}</td>
      <td></td>`;
    const td = tr.lastChild;
    const btnM = document.createElement('button'); btnM.className='btn'; btnM.textContent='Mount';
    btnM.onclick = async ()=>{ setStatus(await api('/api/mount_now',{method:'POST',body:JSON.stringify(m)})); refreshMounts(); fillStoreTargets(); };
    const btnU = document.createElement('button'); btnU.className='btn'; btnU.style.marginLeft='6px'; btnU.textContent='Unmount';
    btnU.onclick = async ()=>{ setStatus(await api('/api/unmount_now',{method:'POST',body:JSON.stringify({mount:m.mount})})); refreshMounts(); fillStoreTargets(); };
    const btnD = document.createElement('button'); btnD.className='btn'; btnD.style.marginLeft='6px'; btnD.textContent='Delete';
    btnD.onclick = async ()=>{ setStatus(await api('/api/mount_delete',{method:'POST',body:JSON.stringify({name:m.name})})); refreshMounts(); fillStoreTargets(); };
    const btnF = document.createElement('button'); btnF.className='btn'; btnF.style.marginLeft='6px'; btnF.textContent='Fill form';
    btnF.onclick = ()=>{ $id('m_name').value=m.name||''; $id('m_proto').value=m.proto||'cifs'; $id('m_server').value=m.server||''; 
      $id('m_user').value=m.username||''; $id('m_pass').value=m.password||''; $id('m_share').value=m.share||''; 
      $id('m_mount').value=m.mount||''; $id('m_opts').value=m.options||''; $id('m_auto').value=String(!!m.auto_mount); };
    td.append(btnM,btnU,btnD,btnF);
    tb.appendChild(tr);
  });
  fillStoreTargets();
}
function fillStoreTargets(){
  const sel = $id('b_store'); const current = sel.value;
  sel.innerHTML = '';
  const optLocal = document.createElement('option'); optLocal.value = '/backup'; optLocal.textContent='/backup (local)';
  sel.appendChild(optLocal);
  mounts.forEach(m=>{
    if (m.mounted || m.mount) {
      const o = document.createElement('option'); o.value = m.mount; o.textContent = `${m.name || m.mount} (${m.mount})`;
      sel.appendChild(o);
    }
  });
  if (current) sel.value = current;
}
$id('btnAddMount').onclick = async ()=>{
  const body = {
    name:$id('m_name').value.trim(),
    proto:$id('m_proto').value,
    server:$id('m_server').value.trim(),
    username:$id('m_user').value.trim(),
    password:$id('m_pass').value,
    share:$id('m_share').value.trim(),
    mount:$id('m_mount').value.trim(),
    options:$id('m_opts').value.trim(),
    auto_mount:($id('m_auto').value==='true')
  };
  if (!body.name || !body.server || !body.share) { alert('Name, server, share/export are required.'); return; }
  setStatus(await api('/api/mount_add_update',{method:'POST',body:JSON.stringify(body)}));
  refreshMounts();
};
$id('btnList').onclick = async ()=>{
  const server = $id('m_server').value.trim(); const proto = $id('m_proto').value;
  if (!server) { alert('Enter server first'); return; }
  const r = await api(`/api/mount_list?proto=${encodeURIComponent(proto)}&server=${encodeURIComponent(server)}`);
  // Fill dropdown
  const sel = $id('m_share_select'); sel.innerHTML = '';
  (r.items||[]).filter(it=>it.name && (it.type==='share' || it.type==='export')).forEach(it=>{
    const o=document.createElement('option'); o.value=it.name || it.path; o.textContent=it.name || it.path; sel.appendChild(o);
  });
  // Show JSON in status box too
  setStatus(r);
};
$id('m_share_select').addEventListener('change', ()=>{
  const v = $id('m_share_select').value;
  if (v) $id('m_share').value = v;
});

/* ---------- Browse (SMB/NFS & SSH) ---------- */
const modal = $id('browse_modal');
const browsePath = $id('browse_path');
const browseList = $id('browse_list');
const browseTitle = $id('browse_title');
let browseCtx = null; // {mode:'smb'|'nfs'|'ssh', ...}

function openModal(){ modal.setAttribute('aria-hidden','false'); }
function closeModal(){ modal.setAttribute('aria-hidden','true'); browseList.innerHTML=''; browsePath.textContent=''; browseCtx=null; }
$id('browse_close').onclick = closeModal;

async function doBrowse(){
  if (!browseCtx) return;
  if (browseCtx.mode==='ssh'){
    const payload = { host:browseCtx.host, username:browseCtx.user, password:browseCtx.pass, port:browseCtx.port, path:browseCtx.path||'/' };
    const r = await api('/api/ssh_ls',{method:'POST',body:JSON.stringify(payload)});
    if (!r || r.error || r.ok===false){
      browseList.innerHTML = `<div class="hint">Remote browse not available on this build. Enter paths manually in the field.</div>`;
      return;
    }
    renderList((r.items||[]).map(it=>({name:it.name, type:it.is_dir?'dir':'file'})));
    browsePath.textContent = `${browseCtx.host}:${browseCtx.path||'/'}`;
  } else {
    const body = {
      proto:browseCtx.mode==='smb'?'cifs':'nfs',
      server:browseCtx.server, username:browseCtx.user, password:browseCtx.pass,
      share:browseCtx.share, path:browseCtx.path||''
    };
    const r = await api('/api/mount_browse',{method:'POST',body:JSON.stringify(body)});
    renderList(r.items||[]);
    const prefix = (browseCtx.mode==='smb')
      ? `//${browseCtx.server}/${browseCtx.share||''}/${browseCtx.path||''}`.replace(/\/+/g,'/')
      : `${browseCtx.server} ${browseCtx.share||''} ${browseCtx.path||''}`.trim();
    browsePath.textContent = prefix;
  }
}
function renderList(items){
  browseList.innerHTML='';
  items.forEach(it=>{
    const row = document.createElement('div'); row.className='row';
    const type = document.createElement('div'); type.className='type'; type.textContent = it.type?.toUpperCase() || '';
    const name = document.createElement('div'); name.textContent = it.name || it.path || '';
    row.append(type,name); browseList.appendChild(row);
    row.onclick = async ()=>{
      if (browseCtx.mode==='smb' || browseCtx.mode==='nfs'){
        if(!browseCtx.share && it.type==='share'){ $id('m_share').value = it.name; closeModal(); return; }
        if (it.type==='dir'){ browseCtx.path = (browseCtx.path? `${browseCtx.path}/${it.name}`:it.name); await doBrowse(); }
        if (it.type==='file'){ /* ignore files when mounting */ }
      } else if (browseCtx.mode==='ssh'){
        if (it.type==='dir'){ browseCtx.path = (browseCtx.path? `${browseCtx.path}/${it.name}`:it.name); await doBrowse(); }
      }
    };
  });
}
$id('browse_up').onclick = async ()=>{
  if (!browseCtx) return;
  if (browseCtx.path){
    const parts = browseCtx.path.replace(/\/+$/,'').split('/'); parts.pop();
    browseCtx.path = parts.join('/');
    await doBrowse();
  } else if ((browseCtx.mode==='smb'||browseCtx.mode==='nfs') && browseCtx.share){
    browseCtx.share = ''; await doBrowse();
  }
};
$id('browse_select').onclick = ()=>{
  if (!browseCtx) return;
  if (browseCtx.mode==='ssh'){
    // append selected remote folder to rsync list
    const current = $id('b_files').value.trim();
    const add = (browseCtx.path ? `/${browseCtx.path.replace(/^\/?/,'')}` : '/');
    $id('b_files').value = current ? (current + ',' + add) : add;
    closeModal();
  } else {
    // fill share with subdir if present
    const sub = browseCtx.path ? `${browseCtx.share}/${browseCtx.path}` : browseCtx.share;
    if (sub) $id('m_share').value = sub;
    closeModal();
  }
};
$id('btnBrowse').onclick = async ()=>{
  const proto = $id('m_proto').value; const server=$id('m_server').value.trim();
  if(!server){ alert('Enter server first'); return; }
  browseCtx = { mode:(proto==='cifs'?'smb':'nfs'), server, user:$id('m_user').value, pass:$id('m_pass').value, share:$id('m_share').value.trim(), path:'' };
  browseTitle.textContent = (proto==='cifs'?'Browse SMB':'Browse NFS');
  openModal(); doBrowse();
};
$id('btn_browse_remote').onclick = async (e)=>{
  e.preventDefault();
  const host=$id('b_host').value.trim(); if(!host){ alert('Enter Host/IP first.'); return; }
  browseCtx = { mode:'ssh', host, user:$id('b_user').value.trim()||'root', pass:$id('b_pass').value, port:parseInt($id('b_port').value||'22',10), path:'/' };
  browseTitle.textContent = 'Browse remote (SSH)';
  openModal(); doBrowse();
};

/* Quick pick from backups (for Restore input) */
$id('btn_browse_local').onclick = (e)=>{ e.preventDefault(); showTab('backups'); };

/* Store-to mount/unmount shortcuts */
$id('btn_store_mount').onclick = async (e)=>{
  e.preventDefault();
  const m = mounts.find(x=>x.mount===$id('b_store').value);
  if (!m) { $id('b_store_status').textContent='Not a preset'; return; }
  const r = await api('/api/mount_now',{method:'POST',body:JSON.stringify(m)}); $id('b_store_status').textContent=r.ok?'Mounted':'Failed';
  refreshMounts();
};
$id('btn_store_unmount').onclick = async (e)=>{
  e.preventDefault();
  const path = $id('b_store').value;
  const r = await api('/api/unmount_now',{method:'POST',body:JSON.stringify({mount:path})}); $id('b_store_status').textContent=r.ok?'Unmounted':'Failed';
  refreshMounts();
};

/* ---------- Backups list ---------- */
async function backupsRefresh(){
  const data = await api('/api/backups');
  const body = $id('backups_rows'); body.innerHTML="";
  (data.items||[]).sort((a,b)=> (b.created||0)-(a.created||0)).forEach(x=>{
    const tr=document.createElement('tr');
    const size = (x.size>=1073741824) ? `${(x.size/1073741824).toFixed(1)} GB` :
                 (x.size>=1048576) ? `${(x.size/1048576).toFixed(1)} MB` :
                 (x.size>=1024) ? `${(x.size/1024).toFixed(1)} KB` : (x.size||0)+' B';
    const date = x.created ? new Date(x.created*1000).toISOString().replace('T',' ').slice(0,19) : (x.mtime||'');
    tr.innerHTML = `<td>${x.path}</td><td>${x.kind||x.type||'unknown'}</td><td>${x.location||'Local'}</td><td>${size}</td><td>${date}</td><td></td>`;
    const td = tr.lastChild;
    const dl = document.createElement('a'); dl.className='btn'; dl.textContent='Download'; dl.href=`/api/download?path=${encodeURIComponent(x.path)}`; dl.target="_blank";
    const use = document.createElement('button'); use.className='btn'; use.style.marginLeft='6px'; use.textContent='Use for restore';
    use.onclick = ()=>{ showTab('restore'); $id('r_image').value = x.path; };
    const del = document.createElement('button'); del.className='btn btn--danger'; del.style.marginLeft='6px'; del.textContent='Delete';
    del.onclick = async ()=>{ if(confirm(`Delete ${x.path}?`)){ await api('/api/backups/delete',{method:'POST',body:JSON.stringify({path:x.path})}); backupsRefresh(); }};
    td.append(dl,use,del);
    body.appendChild(tr);
  });
}

/* ---------- Backup/Restore actions ---------- */
$id("btnEstimate").onclick = async ()=>{
  const body = {
    method:$id("b_method").value, username:$id("b_user").value, host:$id("b_host").value,
    password:$id("b_pass").value, port:parseInt($id("b_port").value||"22",10),
    disk:$id("b_disk").value, files:$id("b_files").value, bwlimit_kbps:parseInt($id("b_bw").value||"0",10)
  };
  setStatus(await api("/api/estimate_backup",{method:"POST",body:JSON.stringify(body)}));
};
$id("btnBackup").onclick = async ()=>{
  const body = {
    method:$id("b_method").value, username:$id("b_user").value, host:$id("b_host").value,
    password:$id("b_pass").value, port:parseInt($id("b_port").value||"22",10),
    disk:$id("b_disk").value, files:$id("b_files").value, store_to:$id("b_store").value,
    verify:($id("b_verify").value==="true"), excludes:$id("b_excludes").value,
    retention_days:parseInt($id("b_retention").value||"0",10),
    backup_name:$id("b_name").value, bwlimit_kbps:parseInt($id("b_bw").value||"0",10),
    cloud_upload:$id("b_cloud").value.trim()
  };
  setStatus(await api("/api/run_backup",{method:"POST",body:JSON.stringify(body)}));
  backupsRefresh();
};
$id("btnRestore").onclick = async ()=>{
  if (!confirm("Are you sure you want to restore? This will overwrite data.")) return;
  if (!confirm("Last warning. Proceed with restore?")) return;
  const body = {
    method:$id("r_method").value, username:$id("r_user").value, host:$id("r_host").value,
    password:$id("r_pass").value, port:parseInt($id("r_port").value||"22",10),
    disk:$id("r_disk").value, image_path:$id("r_image").value,
    local_src:$id("r_image").value, remote_dest:$id("r_dest").value,
    excludes:$id("r_ex").value, bwlimit_kbps:parseInt($id("r_bw").value||"0",10)
  };
  setStatus(await api("/api/run_restore",{method:"POST",body:JSON.stringify(body)}));
};

/* ---------- Scheduler ---------- */
async function schRefresh(){
  const r = await api('/api/schedules'); // expected {items:[...]}  (name, cron, method, host, source, store)
  const hint = $id('sch_hint');
  const body = $id('sch_rows'); body.innerHTML='';
  if (!r || r.error || (!r.items && !Array.isArray(r))) {
    hint.textContent = "Scheduler endpoints not found. Backend should implement /api/schedules, /api/schedule_add, /api/schedule_delete.";
    return;
  }
  hint.textContent = "";
  (r.items || r).forEach(j=>{
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${j.name||''}</td><td>${j.cron||''}</td><td>${j.method||''}</td>
      <td>${j.host||''}</td><td>${j.source||''}</td><td>${j.store||''}</td><td></td>`;
    const td = tr.lastChild;
    const btnDel = document.createElement('button'); btnDel.className='btn btn--danger'; btnDel.textContent='Delete';
    btnDel.onclick = async()=>{ await api('/api/schedule_delete',{method:'POST',body:JSON.stringify({name:j.name})}); schRefresh(); };
    const btnRun = document.createElement('button'); btnRun.className='btn'; btnRun.style.marginLeft='6px'; btnRun.textContent='Run now';
    btnRun.onclick = async()=>{ await api('/api/schedule_run_now',{method:'POST',body:JSON.stringify({name:j.name})}); };
    td.append(btnRun,btnDel); body.appendChild(tr);
  });
}
$id('btnSchRefresh').onclick = schRefresh;
$id('btnSchAdd').onclick = async ()=>{
  const body = {
    name:$id('sch_name').value.trim(),
    cron:$id('sch_cron').value.trim(),
    method:$id('sch_method').value,
    host:$id('sch_host').value.trim(),
    username:$id('sch_user').value.trim(),
    port:parseInt($id('sch_port').value||'22',10),
    password:$id('sch_pass').value,
    source:$id('sch_source').value.trim(),
    store:$id('sch_store').value.trim()
  };
  if (!body.name || !body.cron) { alert('Name and CRON are required.'); return; }
  setStatus(await api('/api/schedule_add',{method:'POST',body:JSON.stringify(body)}));
  schRefresh();
};

/* ---------- Init ---------- */
(async function init(){
  await loadOptions();
  await refreshMounts();
  await backupsRefresh();
  applyMethodVisibility('b'); applyMethodVisibility('r');
})();
