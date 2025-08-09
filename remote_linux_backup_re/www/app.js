// tiny helper
async function api(path, opts={}) {
  const headers = opts.headers || {};
  if (!headers["Content-Type"] && opts.method && opts.method.toUpperCase()==="POST") {
    headers["Content-Type"] = "application/json";
  }
  const r = await fetch(path, Object.assign({headers}, opts));
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
const $ = (id)=>document.getElementById(id);

// tabs
function setActive(tab){
  ["Backup","Restore","Backups","Mounts","Settings","Help"].forEach(n=>{
    $(`tab${n}`).classList.toggle("active", n===tab);
    $(`view${n}`).classList.toggle("hide", n!==tab);
  });
}
$("tabBackup").onclick = ()=>setActive("Backup");
$("tabRestore").onclick = ()=>setActive("Restore");
$("tabBackups").onclick = ()=>{ setActive("Backups"); refreshBackups().catch(console.error); };
$("tabMounts").onclick = ()=>setActive("Mounts");
$("tabSettings").onclick = ()=>setActive("Settings");
$("tabHelp").onclick = ()=>setActive("Help");

// Options
async function loadOptions(){
  const j = await api("/api/options");
  $("s_gurl").value = j.gotify_url||"";
  $("s_gtoken").value = j.gotify_token||"";
  $("s_gen").value = String(!!j.gotify_enabled);
  $("s_dben").value = String(!!j.dropbox_enabled);
  $("s_dropremote").value = j.dropbox_remote||"dropbox:HA-Backups";
  $("s_uiport").value = j.ui_port||8066;
}
async function saveOptions(){
  const body = {
    gotify_url:$("s_gurl").value.trim(),
    gotify_token:$("s_gtoken").value.trim(),
    gotify_enabled:($("s_gen").value==="true"),
    dropbox_enabled:($("s_dben").value==="true"),
    dropbox_remote:$("s_dropremote").value.trim(),
    ui_port:parseInt($("s_uiport").value||"8066",10)
  };
  const j = await api("/api/options",{method:"POST",body:JSON.stringify(body)});
  $("status_box").value = JSON.stringify(j,null,2);
}
$("btnSaveSettings").onclick = ()=>saveOptions().catch(e=>$("status_box").value=e.message);

$("btnTestGotify").onclick = async ()=>{
  const body = { url:$("s_gurl").value.trim(), token:$("s_gtoken").value.trim(), insecure:true };
  const j = await api("/api/gotify_test",{method:"POST",body:JSON.stringify(body)});
  $("status_box").value = JSON.stringify(j,null,2);
};

// Servers
async function refreshServers(){
  const j = await api("/api/servers");
  const tb = $("serverTable").querySelector("tbody");
  tb.innerHTML = "";
  const selB = $("b_saved"), selR = $("r_saved");
  selB.innerHTML = `<option value="">-- none --</option>`;
  selR.innerHTML = `<option value="">-- none --</option>`;
  (j.servers||[]).forEach(s=>{
    // table
    const tr = document.createElement("tr");
    const hasPwd = (s.password && s.password.length>0) ? "Yes" : "No";
    tr.innerHTML = `<td>${s.name}</td><td>${s.host}</td><td>${s.username}</td><td>${s.port}</td><td>${hasPwd}</td>
      <td><button class="btn inline" data-act="fill">Fill</button>
          <button class="btn inline" data-act="delete">Delete</button></td>`;
    tr.querySelector('[data-act="fill"]').onclick = ()=>{
      $("sv_name").value=s.name; $("sv_host").value=s.host; $("sv_user").value=s.username; $("sv_port").value=s.port;
      $("b_host").value=s.host; $("b_user").value=s.username; $("b_port").value=s.port;
      $("r_host").value=s.host; $("r_user").value=s.username; $("r_port").value=s.port;
    };
    tr.querySelector('[data-act="delete"]').onclick = async ()=>{
      const j2 = await api("/api/server_delete",{method:"POST",body:JSON.stringify({name:s.name})});
      $("status_box").value = JSON.stringify(j2,null,2);
      await refreshServers();
    };
    tb.appendChild(tr);

    // dropdowns
    const optB = document.createElement("option"); optB.value = s.name; optB.textContent = s.name; optB.dataset.server = JSON.stringify(s);
    const optR = document.createElement("option"); optR.value = s.name; optR.textContent = s.name; optR.dataset.server = JSON.stringify(s);
    selB.appendChild(optB); selR.appendChild(optR);
  });

  selB.onchange = ()=>{
    const opt = selB.options[selB.selectedIndex];
    if(opt && opt.dataset.server){
      const s = JSON.parse(opt.dataset.server);
      $("b_host").value=s.host; $("b_user").value=s.username; $("b_port").value=s.port;
    }
  };
  selR.onchange = ()=>{
    const opt = selR.options[selR.selectedIndex];
    if(opt && opt.dataset.server){
      const s = JSON.parse(opt.dataset.server);
      $("r_host").value=s.host; $("r_user").value=s.username; $("r_port").value=s.port;
    }
  };
}
$("btnAddServer").onclick = async ()=>{
  const body = {
    name:$("sv_name").value.trim(),
    host:$("sv_host").value.trim(),
    username:$("sv_user").value.trim(),
    port:parseInt($("sv_port").value||"22",10),
    password:$("sv_pass").value,
    save_password:($("sv_savepwd").value==="true")
  };
  const j = await api("/api/server_add_update",{method:"POST",body:JSON.stringify(body)});
  $("status_box").value = JSON.stringify(j,null,2);
  if(j.ok){ $("sv_pass").value=""; await refreshServers(); }
};

// Mounts
async function refreshMounts(){
  const j = await api("/api/mounts");
  const tb = $("mountTable").querySelector("tbody"); tb.innerHTML="";
  // fill backup store dropdown base
  const storeSel = $("b_store");
  const selVal = storeSel.value;
  storeSel.innerHTML = `<option value="/backup">/backup (local)</option>`;

  (j.mounts||[]).forEach(m=>{
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${m.name||""}</td><td>${m.proto}</td><td>${m.server}</td><td>${m.share}</td><td>${m.mount}</td><td>${m.auto_mount? "Yes":"No"}</td>
      <td>
        <button class="btn inline" data-act="mount">Mount</button>
        <button class="btn inline" data-act="unmount">Unmount</button>
        <button class="btn inline" data-act="delete">Delete</button>
        <button class="btn inline" data-act="fill">Fill form</button>
      </td>`;
    tr.querySelector('[data-act="mount"]').onclick = async ()=>{
      const j2 = await api("/api/mount_now",{method:"POST",body:JSON.stringify(m)});
      $("status_box").value = JSON.stringify(j2,null,2);
      await refreshMounts();
    };
    tr.querySelector('[data-act="unmount"]').onclick = async ()=>{
      const j2 = await api("/api/unmount_now",{method:"POST",body:JSON.stringify({mount:m.mount})});
      $("status_box").value = JSON.stringify(j2,null,2);
      await refreshMounts();
    };
    tr.querySelector('[data-act="delete"]').onclick = async ()=>{
      const j2 = await api("/api/mount_delete",{method:"POST",body:JSON.stringify({name:m.name})});
      $("status_box").value = JSON.stringify(j2,null,2);
      await refreshMounts();
    };
    tr.querySelector('[data-act="fill"]').onclick = ()=>{
      $("m_name").value = m.name||"";
      $("m_proto").value = m.proto||"cifs";
      $("m_server").value = m.server||"";
      $("m_user").value = m.username||"";
      $("m_pass").value = m.password||"";
      $("m_share").value = m.share||"";
      $("m_mount").value = m.mount||"";
      $("m_opts").value = m.options||"";
      $("m_auto").value = String(!!m.auto_mount);
    };
    tb.appendChild(tr);

    // add to backup "Store to" select
    const op = document.createElement("option");
    op.value = m.mount; op.textContent = `${m.name || m.mount} (${m.mount})`;
    storeSel.appendChild(op);
  });
  if (selVal) storeSel.value = selVal;
}
$("btnAddMount").onclick = async ()=>{
  const body = {
    name:$("m_name").value.trim(),
    proto:$("m_proto").value.trim(),
    server:$("m_server").value.trim(),
    username:$("m_user").value,
    password:$("m_pass").value,
    share:$("m_share").value.trim(),
    mount:$("m_mount").value.trim(),
    options:$("m_opts").value.trim(),
    auto_mount:($("m_auto").value==="true")
  };
  const j = await api("/api/mount_add_update",{method:"POST",body:JSON.stringify(body)});
  $("status_box").value = JSON.stringify(j,null,2);
  if(j.ok) refreshMounts();
};
$("btnList").onclick = async ()=>{
  const server = $("m_server").value.trim();
  const proto = $("m_proto").value.trim();
  if(!server){ alert("Enter server first"); return; }
  const j = await api(`/api/mount_list?proto=${encodeURIComponent(proto)}&server=${encodeURIComponent(server)}`);
  $("status_box").value = j.raw || JSON.stringify(j,null,2);
};

// simple browse modal for SMB/NFS
let browse_ctx = { proto:"cifs", server:"", user:"", pass:"", share:"", path:"" };
const openBrowse = ()=>{$("browse_modal").style.display="flex";};
const closeBrowse = ()=>{$("browse_modal").style.display="none";};
function renderBrowse(items){
  $("browse_path").textContent = (browse_ctx.proto==="cifs"
    ? `//${browse_ctx.server}/${browse_ctx.share||""}/${browse_ctx.path||""}`.replace(/\/+/g,"/")
    : `${browse_ctx.server} (NFS exports)`
  );
  const list = $("browse_list"); list.innerHTML="";
  items.forEach(it=>{
    const div = document.createElement("div");
    div.textContent = `${(it.type||"").toUpperCase()}  ${it.name||it.path}`;
    div.onclick = async ()=>{
      if(browse_ctx.proto==="cifs"){
        if(!browse_ctx.share && it.type==="share"){
          $("m_share").value = it.name; closeBrowse(); return;
        }
        if(it.type==="dir"){ browse_ctx.path = browse_ctx.path ? (browse_ctx.path+"/"+it.name) : it.name; await doBrowse(); }
        else if(it.type==="file"){ closeBrowse(); }
      }else{
        if(it.type==="export"){ $("m_share").value = it.path; closeBrowse(); }
      }
    };
    list.appendChild(div);
  });
}
async function doBrowse(){
  const body = { proto:browse_ctx.proto, server:browse_ctx.server, username:browse_ctx.user, password:browse_ctx.pass, share:browse_ctx.share, path:browse_ctx.path };
  const j = await api("/api/mount_browse",{method:"POST",body:JSON.stringify(body)});
  renderBrowse(j.items||[]);
}
$("btnBrowse").onclick = async ()=>{
  browse_ctx = {
    proto:$("m_proto").value.trim(),
    server:$("m_server").value.trim(),
    user:$("m_user").value, pass:$("m_pass").value,
    share:$("m_share").value.trim(), path:""
  };
  if(!browse_ctx.server){ alert("Enter server first"); return; }
  openBrowse(); await doBrowse();
};
$("browse_close").onclick = closeBrowse;
$("browse_up").onclick = async ()=>{
  if(browse_ctx.path){ const parts=browse_ctx.path.split("/"); parts.pop(); browse_ctx.path=parts.join("/"); await doBrowse(); }
  else if(browse_ctx.share){ browse_ctx.share=""; await doBrowse(); }
};

// Estimate / Backup / Restore
$("btnEstimate").onclick = async ()=>{
  const body = {
    method:$("b_method").value, username:$("b_user").value, host:$("b_host").value,
    password:$("b_pass").value, port:parseInt($("b_port").value||"22",10),
    disk:$("b_disk").value, files:$("b_files").value, bwlimit_kbps:parseInt($("b_bw").value||"0",10)
  };
  const j = await api("/api/estimate_backup",{method:"POST",body:JSON.stringify(body)});
  $("status_box").value = JSON.stringify(j,null,2);
};
$("btnBackup").onclick = async ()=>{
  const body = {
    method:$("b_method").value, username:$("b_user").value, host:$("b_host").value,
    password:$("b_pass").value, port:parseInt($("b_port").value||"22",10),
    disk:$("b_disk").value, files:$("b_files").value, store_to:$("b_store").value,
    verify:($("b_verify").value==="true"), excludes:$("b_excludes").value,
    retention_days:parseInt($("b_retention").value||"0",10),
    backup_name:$("b_name").value, bwlimit_kbps:parseInt($("b_bw").value||"0",10),
    cloud_upload:$("b_cloud").value.trim()
  };
  const j = await api("/api/run_backup",{method:"POST",body:JSON.stringify(body)});
  $("status_box").value = JSON.stringify(j,null,2);
  try { await refreshBackups(); } catch(e){}
};
$("btnRestore").onclick = async ()=>{
  const body = {
    method:$("r_method").value, username:$("r_user").value, host:$("r_host").value,
    password:$("r_pass").value, port:parseInt($("r_port").value||"22",10),
    disk:$("r_disk").value, image_path:$("r_img").value,
    local_src:$("r_src").value, remote_dest:$("r_dest").value,
    excludes:$("r_ex").value, bwlimit_kbps:parseInt($("r_bw").value||"0",10)
  };
  const j = await api("/api/run_restore",{method:"POST",body:JSON.stringify(body)});
  $("status_box").value = JSON.stringify(j,null,2);
};
$("btnBrowseImage").onclick = async ()=>{
  // simple helper: list roots and pick file by prompt
  const roots = ["/backup"];
  // ask backend for mounts (to include mounted paths)
  try {
    const j = await api("/api/mounts");
    (j.mounts||[]).forEach(m => roots.push(m.mount));
  } catch {}
  const root = prompt("Browse which root?\n" + roots.join("\n"), roots[0]);
  if(!root) return;
  const res = await api("/api/ls?path="+encodeURIComponent(root));
  const files = (res.items||[]).filter(it=>!it.is_dir).map(it=>it.path);
  const pick = prompt("Pick file (copy/paste path):\n"+files.join("\n"));
  if(pick) $("r_img").value = pick;
};

// Backups list
async function refreshBackups(){
  const data = await api("/api/backups");
  const body = $("backups_tbody"); body.innerHTML="";
  (data.items||[]).sort((a,b)=>b.created-a.created).forEach(x=>{
    const tr=document.createElement("tr");
    const size = (x.size>=0) ? ((x.size/1048576).toFixed(1)+" MB") : "";
    const created = x.created ? (new Date(x.created*1000).toISOString().replace('T',' ').slice(0,19)) : "";
    tr.innerHTML = `<td>${x.path}</td><td>${x.kind||""}</td><td>${x.host||""}</td><td>${size}</td><td>${created}</td><td></td>`;
    const td = tr.lastChild;
    const dl = document.createElement("a"); dl.className="btn inline"; dl.textContent="Download"; dl.href=`/api/download?path=${encodeURIComponent(x.path)}`; dl.target="_blank";
    const del = document.createElement("button"); del.className="btn inline"; del.textContent="Delete";
    del.onclick = async ()=>{ if(confirm(`Delete ${x.path}?`)){ await api("/api/backups/delete",{method:"POST",body:JSON.stringify({path:x.path})}); await refreshBackups(); } };
    td.appendChild(dl); td.appendChild(del);
    body.appendChild(tr);
  });
}
$("btnRefreshBackups").onclick = ()=>refreshBackups().catch(console.error);

// init
(async function init(){
  await loadOptions();
  await refreshMounts();
  await refreshServers();
  // default tab
  setActive("Backup");
})();
