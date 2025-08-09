async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (!headers["Content-Type"] && opts.method && opts.method.toUpperCase() === "POST") {
    headers["Content-Type"] = "application/json";
  }
  const r = await fetch(path, { ...opts, headers });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
const $ = (s) => document.querySelector(s);
function showTab(id) {
  document.querySelectorAll(".panel").forEach(p => p.classList.remove("is-active"));
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("is-active"));
  $(`#panel-${id}`).classList.add("is-active");
  document.querySelector(`.tab[data-target="${id}"]`).classList.add("is-active");
}

// Tabs
document.querySelectorAll(".tab").forEach(t => {
  t.addEventListener("click", () => showTab(t.dataset.target));
});

// ------------ Settings ------------
async function loadOptions() {
  const j = await api("/api/options");
  $("#s_gotify_url").value = j.gotify_url || "";
  $("#s_gotify_token").value = j.gotify_token || "";
  $("#s_gotify_enabled").value = String(!!j.gotify_enabled);
  $("#s_dropbox_enabled").value = String(!!j.dropbox_enabled);
  $("#s_dropbox_remote").value = j.dropbox_remote || "dropbox:HA-Backups";
  $("#s_ui_port").value = j.ui_port || 8066;
}
async function saveOptions() {
  const body = {
    gotify_url: $("#s_gotify_url").value.trim(),
    gotify_token: $("#s_gotify_token").value.trim(),
    gotify_enabled: $("#s_gotify_enabled").value === "true",
    dropbox_enabled: $("#s_dropbox_enabled").value === "true",
    dropbox_remote: $("#s_dropbox_remote").value.trim(),
    ui_port: parseInt($("#s_ui_port").value || "8066", 10),
  };
  const j = await api("/api/options", { method: "POST", body: JSON.stringify(body) });
  $("#s_status").textContent = JSON.stringify(j, null, 2);
}
$("#btn_save_settings").onclick = saveOptions;
$("#btn_test_gotify").onclick = async () => {
  const body = {
    url: $("#s_gotify_url").value.trim(),
    token: $("#s_gotify_token").value.trim(),
    enabled: $("#s_gotify_enabled").value === "true",
    insecure: false
  };
  const j = await api("/api/gotify_test", { method: "POST", body: JSON.stringify(body) });
  $("#s_status").textContent = JSON.stringify(j, null, 2);
};

// ------------ Mounts ------------
async function refreshMounts() {
  const j = await api("/api/mounts");
  const tb = $("#mount_rows"); tb.innerHTML = "";
  (j.mounts || []).forEach(m => {
    const tr = document.createElement("tr");
    const stat = m.mounted ? "🟢 mounted" : "🔴 not mounted";
    tr.innerHTML = `<td>${m.name||""}</td><td>${m.proto}</td><td>${m.server}</td><td>${m.share}</td><td>${m.mount}</td><td>${m.auto_mount?"yes":"no"}</td><td>${stat}</td><td></td>`;
    const actions = tr.lastChild;

    const bMount = document.createElement("button"); bMount.className="btn"; bMount.textContent="Mount";
    bMount.onclick = async()=>{ const r=await api("/api/mount_now",{method:"POST",body:JSON.stringify(m)}); await refreshMounts(); alert(r.ok?"Mounted":"Failed"); };
    actions.appendChild(bMount);

    const bUm = document.createElement("button"); bUm.className="btn"; bUm.style.marginLeft="6px"; bUm.textContent="Unmount";
    bUm.onclick = async()=>{ const r=await api("/api/unmount_now",{method:"POST",body:JSON.stringify({mount:m.mount})}); await refreshMounts(); alert(r.ok?"Unmounted":"Failed"); };
    actions.appendChild(bUm);

    const bDel = document.createElement("button"); bDel.className="btn btn--danger"; bDel.style.marginLeft="6px"; bDel.textContent="Delete";
    bDel.onclick = async()=>{ if(!confirm(`Delete preset "${m.name||m.mount}"?`)) return; const r=await api("/api/mount_delete",{method:"POST",body:JSON.stringify({name:m.name})}); await refreshMounts(); };
    actions.appendChild(bDel);

    tr.onclick = ()=>{ // fill form
      $("#m_name").value = m.name||"";
      $("#m_proto").value = m.proto||"cifs";
      $("#m_server").value = m.server||"";
      $("#m_user").value = m.username||"";
      $("#m_pass").value = m.password||"";
      $("#m_share").value = m.share||"";
      $("#m_mount").value = m.mount||"";
      $("#m_opts").value = m.options||"";
      $("#m_auto").value = String(!!m.auto_mount);
    };

    tb.appendChild(tr);
  });
}

async function listShares() {
  const server = $("#m_server").value.trim();
  const proto = $("#m_proto").value.trim();
  const username = $("#m_user").value.trim();
  const password = $("#m_pass").value;
  if (!server) { alert("Enter server/host first."); return; }
  const r = await api(`/api/mount_list?proto=${encodeURIComponent(proto)}&server=${encodeURIComponent(server)}&username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`);
  const sel = $("#m_share_select"); sel.innerHTML = "";
  if (!r.ok && r.error) { alert(r.error); return; }
  (r.items||[]).forEach(it => {
    const o = document.createElement("option");
    o.value = it.name || it.path || "";
    o.textContent = it.name || it.path || "";
    sel.appendChild(o);
  });
  if (sel.options.length) sel.selectedIndex = 0;
}
$("#btn_list_shares").onclick = (e)=>{ e.preventDefault(); listShares().catch(console.error); };

$("#btn_use_selected").onclick = (e)=>{
  e.preventDefault();
  const sel = $("#m_share_select");
  if (sel.value) $("#m_share").value = sel.value;
};

$("#btn_mount_selected").onclick = async (e)=>{
  e.preventDefault();
  const sel = $("#m_share_select");
  if (!sel.value) { alert("No share selected."); return; }
  $("#m_share").value = sel.value;
  // attempt mount immediately (without needing to save preset)
  const payload = {
    name: $("#m_name").value.trim() || sel.value,
    proto: $("#m_proto").value.trim(),
    server: $("#m_server").value.trim(),
    username: $("#m_user").value.trim(),
    password: $("#m_pass").value,
    share: $("#m_share").value.trim(),
    mount: $("#m_mount").value.trim() || `/mnt/${($("#m_name").value.trim()||sel.value)}`,
    options: $("#m_opts").value.trim(),
    auto_mount: $("#m_auto").value==="true"
  };
  const r = await api("/api/mount_now",{method:"POST",body:JSON.stringify(payload)});
  alert(r.ok ? "Mounted." : ("Mount failed:\n" + (r.err||r.out||"")));
  await refreshMounts();
};

$("#btn_add_mount").onclick = async (e)=>{
  e.preventDefault();
  const payload = {
    name: $("#m_name").value.trim(),
    proto: $("#m_proto").value.trim(),
    server: $("#m_server").value.trim(),
    username: $("#m_user").value.trim(),
    password: $("#m_pass").value,
    share: $("#m_share").value.trim(),
    mount: $("#m_mount").value.trim(),
    options: $("#m_opts").value.trim(),
    auto_mount: $("#m_auto").value==="true"
  };
  if (!payload.name || !payload.server || !payload.share) { alert("Name, server and share are required."); return; }
  const r = await api("/api/mount_add_update",{method:"POST",body:JSON.stringify(payload)});
  if (r.ok) { await refreshMounts(); alert("Saved."); } else { alert("Save failed."); }
};

// ------------ Backups list ------------
function fmtSize(n){ if(n<1024) return n+" B"; const u=["KB","MB","GB","TB"]; let i=-1; do{ n/=1024; i++; }while(n>=1024 && i<u.length-1); return n.toFixed(1)+" "+u[i]; }
function fmtDate(ts){ const d=new Date(ts*1000); return d.toISOString().replace("T"," ").slice(0,19); }

async function refreshBackups() {
  const j = await api("/api/backups");
  const tb = $("#backups_rows"); tb.innerHTML = "";
  (j.items||[]).sort((a,b)=>b.created-a.created).forEach(x=>{
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${x.path}</td><td>${x.kind}</td><td>${x.location||"Local"}</td><td>${fmtSize(x.size)}</td><td>${fmtDate(x.created)}</td><td></td>`;
    const td = tr.lastChild;
    const dl = document.createElement("a"); dl.className="btn"; dl.textContent="Download"; dl.href=`/api/download?path=${encodeURIComponent(x.path)}`; dl.target="_blank";
    td.appendChild(dl);

    const rs = document.createElement("button"); rs.className="btn btn--danger"; rs.style.marginLeft="6px"; rs.textContent="Restore";
    rs.onclick = async ()=>{
      if (!confirm("Restore selected image/files?\nThis can overwrite data.")) return;
      if (!confirm("FINAL WARNING: This may DESTROY data on the destination. Continue?")) return;
      // Fill restore panel and switch there, user presses Restore button afterwards (safer)
      $("#r_image").value = x.path;
      showTab("restore");
    };
    td.appendChild(rs);

    tb.appendChild(tr);
  });
}

// ------------ Backup / Restore stubs tied to your existing endpoints ------------
$("#btn_estimate").onclick = async ()=>{
  const payload = {
    method: $("#b_method").value, username: $("#b_user").value, host: $("#b_host").value,
    password: $("#b_pass").value, port: parseInt($("#b_port").value||"22",10),
    disk: $("#b_disk").value
  };
  let j = {};
  try { j = await api("/api/estimate_backup",{method:"POST",body:JSON.stringify(payload)}); }
  catch(e){ j = {ok:false,error:String(e)}; }
  $("#status_box").textContent = JSON.stringify(j,null,2);
};

$("#btn_run_backup").onclick = async ()=>{
  const payload = {
    method: $("#b_method").value, username: $("#b_user").value, host: $("#b_host").value,
    password: $("#b_pass").value, port: parseInt($("#b_port").value||"22",10),
    disk: $("#b_disk").value, store_to: $("#b_store").value,
    verify: ($("#b_verify").value==="true"), backup_name: $("#b_name").value
  };
  let j = {};
  try { j = await api("/api/run_backup",{method:"POST",body:JSON.stringify(payload)}); }
  catch(e){ j = {ok:false,error:String(e)}; }
  $("#status_box").textContent = JSON.stringify(j,null,2);
  await refreshBackups();
};

$("#btn_run_restore").onclick = async ()=>{
  if (!confirm("Restore will overwrite data. Continue?")) return;
  if (!confirm("FINAL WARNING: This may DESTROY data on the destination. Are you absolutely sure?")) return;
  const payload = {
    method: $("#r_method").value, username: $("#r_user").value, host: $("#r_host").value,
    password: $("#r_pass").value, port: parseInt($("#r_port").value||"22",10),
    image_path: $("#r_image").value, disk: $("#r_disk").value
  };
  let j = {};
  try { j = await api("/api/run_restore",{method:"POST",body:JSON.stringify(payload)}); }
  catch(e){ j = {ok:false,error:String(e)}; }
  $("#restore_box").textContent = JSON.stringify(j,null,2);
};

// ------------ init ------------
(async function init(){
  await loadOptions();
  await refreshMounts();
  await refreshBackups();
})();
