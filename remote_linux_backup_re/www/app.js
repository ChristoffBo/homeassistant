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

async function loadOptions(){
  const d = await api('/api/options');
  // Settings
  $('s_ui_port').value = d.ui_port ?? 8066;
  $('s_gotify_url').value = d.gotify_url || '';
  $('s_gotify_token').value = d.gotify_token || '';
  $('s_dropbox_enabled').value = String(!!d.dropbox_enabled);
  $('s_dropbox_remote').value = d.dropbox_remote || 'dropbox:HA-Backups';
}
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
async function listBackups(){
  const res = await api('/api/list_backups');
  $('s_status').value = res.map(x => `${x.path}  (${(x.size/1048576).toFixed(1)} MB)`).join('\n');
}

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
    verify:$('b_verify').checked, backup_name:$('b_name').value
  };
  const res = await api('/api/run_backup', {method:'POST', body: JSON.stringify(payload)});
  $('b_result').value = res.out || JSON.stringify(res,null,2);
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
  const res = await api('/api/run_restore', {method:'POST', body: JSON.stringify(payload)});
  $('r_result').value = res.out || JSON.stringify(res,null,2);
}

/* ---------- Explorer ---------- */
let currentPath = "/backup";
function renderCrumbs(path){
  const cont = $('crumbs');
  cont.innerHTML = "";
  const parts = path.split("/").filter(Boolean);
  let acc = path.startsWith("/") ? "/" : "";
  const rootSpan = document.createElement("span");
  rootSpan.textContent = "/";
  rootSpan.onclick = ()=> loadDir("/");
  cont.appendChild(rootSpan);
  parts.forEach(p=>{
    acc = (acc === "/" ? "" : acc) + "/" + p;
    const s = document.createElement("span");
    s.textContent = p;
    s.onclick = ()=> loadDir(acc);
    cont.appendChild(s);
  });
}
async function loadDir(path){
  try{
    const res = await api(`/api/ls?path=${encodeURIComponent(path)}`);
    currentPath = res.path;
    renderCrumbs(currentPath);
    const body = $('explorer_rows');
    body.innerHTML = "";
    res.items.forEach(it=>{
      const tr = document.createElement('tr');
      const name = document.createElement('td'); name.textContent = it.name; tr.appendChild(name);
      const typ = document.createElement('td'); typ.textContent = it.is_dir ? "dir" : "file"; tr.appendChild(typ);
      const size = document.createElement('td'); size.textContent = it.is_dir ? "" : (it.size/1048576).toFixed(1) + " MB"; tr.appendChild(size);
      const act = document.createElement('td');
      if(it.is_dir){
        const btn = document.createElement('button'); btn.className="btn secondary"; btn.textContent="Open";
        btn.onclick = ()=> loadDir(it.path);
        act.appendChild(btn);
      }else{
        const a = document.createElement('a'); a.className="btn"; a.textContent="Download";
        a.href = `/api/download?path=${encodeURIComponent(it.path)}`; a.target="_blank";
        act.appendChild(a);
      }
      tr.appendChild(act);
      body.appendChild(tr);
    });
  }catch(e){
    alert("Error: "+e.message);
  }
}

/* wiring */
function wire(){
  document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => showTab(t.dataset.target)));
  $('btn_save_settings').addEventListener('click', (e)=>{ e.preventDefault(); saveOptions().catch(err=>{$('s_status').value='Error: '+err.message;}); });
  $('btn_list_backups').addEventListener('click', (e)=>{ e.preventDefault(); listBackups().catch(console.error); });
  $('btn_probe').addEventListener('click', (e)=>{ e.preventDefault(); probeHost().catch(console.error); });
  $('btn_install').addEventListener('click', (e)=>{ e.preventDefault(); installTools().catch(console.error); });
  $('btn_estimate').addEventListener('click', (e)=>{ e.preventDefault(); estimateTime().catch(console.error); });
  $('btn_run_backup').addEventListener('click', (e)=>{ e.preventDefault(); runBackup().catch(console.error); });
  $('btn_run_restore').addEventListener('click', (e)=>{ e.preventDefault(); runRestore().catch(console.error); });
  $('jump_backup').addEventListener('click', ()=> loadDir('/backup'));
  $('jump_mnt').addEventListener('click', ()=> loadDir('/mnt'));
  loadOptions().catch(console.error);
  loadDir('/backup').catch(console.error);
}
document.addEventListener('DOMContentLoaded', wire);
