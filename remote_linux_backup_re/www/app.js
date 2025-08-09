// -------- small helper --------
const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
const id = s => document.getElementById(s);

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (!headers["Content-Type"] && opts.body) headers["Content-Type"] = "application/json";
  const r = await fetch(path, { ...opts, headers });
  if (!r.ok) throw new Error(await r.text());
  const ct = r.headers.get("content-type") || "";
  return ct.includes("application/json") ? r.json() : r.text();
}
function log(msg) {
  const box = id("status_box");
  if (typeof msg === "object") msg = JSON.stringify(msg, null, 2);
  box.value = (box.value ? box.value + "\n" : "") + msg;
  box.scrollTop = box.scrollHeight;
}

// -------- tabs --------
function show(tab) {
  $$(".tab").forEach(b => b.classList.toggle("is-active", b.dataset.tab === tab));
  $$(".panel").forEach(p => p.classList.toggle("is-active", p.id === `panel-${tab}`));
}
$$(".tab").forEach(btn => btn.addEventListener("click", () => show(btn.dataset.tab)));

// -------- options / settings (with Gotify test) --------
async function loadOptions() {
  try {
    const o = await api("/api/options");
    id("s_gurl").value = o.gotify_url || "";
    id("s_gtoken").value = o.gotify_token || "";
    id("s_gen").value = String(!!o.gotify_enabled);
    id("s_dben").value = String(!!o.dropbox_enabled);
    id("s_dropremote").value = o.dropbox_remote || "dropbox:HA-Backups";
    id("s_uiport").value = o.ui_port || 8066;
  } catch (e) {
    log("Load options failed: " + e.message);
  }
}
id("btnSaveSettings").onclick = async () => {
  try {
    const body = {
      gotify_url: id("s_gurl").value.trim(),
      gotify_token: id("s_gtoken").value.trim(),
      gotify_enabled: id("s_gen").value === "true",
      dropbox_enabled: id("s_dben").value === "true",
      dropbox_remote: id("s_dropremote").value.trim(),
      ui_port: parseInt(id("s_uiport").value || "8066", 10),
    };
    const j = await api("/api/options", { method: "POST", body: JSON.stringify(body) });
    log(j);
  } catch (e) { log("Save options error: " + e.message); }
};
id("btnTestGotify").onclick = async () => {
  try {
    const j = await api("/api/gotify_test", { method: "POST", body: JSON.stringify({
      url: id("s_gurl").value.trim(),
      token: id("s_gtoken").value.trim(),
      insecure: true
    })});
    log(j);
  } catch (e) { log("Gotify test error: " + e.message); }
};

// -------- mounts --------
let mounts = [];
async function refreshMounts() {
  try {
    const j = await api("/api/mounts");
    mounts = j.mounts || j.items || [];
    // table
    const tb = id("mountTable").querySelector("tbody");
    tb.innerHTML = "";
    mounts.forEach(m => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${m.name || ""}</td>
        <td>${m.proto}</td>
        <td>${m.server}</td>
        <td>${m.share}</td>
        <td>${m.mount}</td>
        <td>${m.auto_mount ? "Yes" : "No"}</td>
        <td class="row-actions"></td>`;
      const cell = tr.querySelector(".row-actions");
      const mk = (txt, fn, cls="btn") => { const b=document.createElement("button"); b.className=cls; b.textContent=txt; b.onclick=fn; return b; };
      cell.appendChild(mk("Mount", async ()=>{ log(await api("/api/mount_now",{method:"POST",body:JSON.stringify(m)})); await refreshMounts(); fillStoreTo(); }));
      cell.appendChild(mk("Unmount", async ()=>{ log(await api("/api/unmount_now",{method:"POST",body:JSON.stringify({mount:m.mount})})); await refreshMounts(); fillStoreTo(); }, "btn"));
      cell.appendChild(mk("Delete", async ()=>{ if(!confirm("Delete preset?")) return; log(await api("/api/mount_delete",{method:"POST",body:JSON.stringify({name:m.name})})); await refreshMounts(); }, "btn danger"));
      tr.onclick = () => { // fill form
        id("m_name").value=m.name||""; id("m_proto").value=m.proto; id("m_server").value=m.server;
        id("m_user").value=m.username||""; id("m_pass").value=m.password||"";
        id("m_share").value=m.share||""; id("m_mount").value=m.mount||"";
        id("m_opts").value=m.options||""; id("m_auto").value=String(!!m.auto_mount);
      };
      tb.appendChild(tr);
    });
    fillStoreTo();
  } catch (e) { log("Load mounts failed: " + e.message); }
}
function fillStoreTo() {
  const sel = id("b_store");
  const keep = sel.value;
  sel.innerHTML = "";
  const optLocal = document.createElement("option");
  optLocal.value = "/backup"; optLocal.textContent = "/backup (local)";
  sel.appendChild(optLocal);
  mounts.filter(m => m.mounted || true).forEach(m => {
    const o = document.createElement("option");
    o.value = m.mount; o.textContent = `${m.name || m.mount} (${m.mount})`;
    sel.appendChild(o);
  });
  if (keep) sel.value = keep;
}
id("btnAddMount").onclick = async () => {
  try {
    const body = {
      name: id("m_name").value.trim(),
      proto: id("m_proto").value,
      server: id("m_server").value.trim(),
      username: id("m_user").value,
      password: id("m_pass").value,
      share: id("m_share").value.trim(),
      mount: id("m_mount").value.trim(),
      options: id("m_opts").value.trim(),
      auto_mount: id("m_auto").value === "true",
    };
    if(!body.name || !body.server || !body.share) return alert("Name, server, share/export are required.");
    const j = await api("/api/mount_add_update", { method:"POST", body: JSON.stringify(body) });
    log(j); await refreshMounts();
  } catch (e) { log("Add/update mount error: " + e.message); }
};

// Shares/exports -> dropdown
id("btnList").onclick = async () => {
  try {
    const server = id("m_server").value.trim();
    const proto = id("m_proto").value;
    if (!server) return alert("Enter server/host first");
    const res = await api(`/api/mount_list?proto=${encodeURIComponent(proto)}&server=${encodeURIComponent(server)}`);
    const items = res.items || [];
    const sel = id("m_share_list");
    sel.innerHTML = "";
    const blank = document.createElement("option"); blank.value = ""; blank.textContent = "— select —"; sel.appendChild(blank);
    items.forEach(it => {
      const o = document.createElement("option");
      o.value = (proto==="cifs") ? it.name : it.path;
      o.textContent = (proto==="cifs") ? it.name : it.path;
      sel.appendChild(o);
    });
    sel.onchange = () => { if (sel.value) id("m_share").value = sel.value; };
    // also dump to status for visibility
    log(res);
  } catch (e) { log("List shares error: " + e.message); }
};

// Browse modal (same endpoints you already had)
const modal = id("browse_modal");
let browse_ctx = { proto:"cifs", server:"", user:"", pass:"", share:"", path:"" };
function openModal(){ modal.style.display="flex"; }
function closeModal(){ modal.style.display="none"; }
id("browse_close").onclick = closeModal;
id("btnBrowse").onclick = async ()=>{
  browse_ctx = {
    proto: id("m_proto").value.trim(),
    server: id("m_server").value.trim(),
    user: id("m_user").value,
    pass: id("m_pass").value,
    share: id("m_share").value.trim(),
    path: ""
  };
  if(!browse_ctx.server) return alert("Enter server first");
  openModal(); await doBrowse();
};
id("browse_up").onclick = async ()=>{
  if (browse_ctx.path) {
    const p = browse_ctx.path.split("/"); p.pop(); browse_ctx.path = p.join("/");
    await doBrowse();
  } else if (browse_ctx.share) {
    browse_ctx.share = ""; await doBrowse();
  }
};
async function doBrowse(){
  id("browse_path").textContent = browse_ctx.proto==="cifs"
      ? `//${browse_ctx.server}/${browse_ctx.share||""}/${browse_ctx.path||""}`.replace(/\/+/g,"/")
      : `${browse_ctx.server} (NFS)`;
  const r = await api("/api/mount_browse", { method:"POST", body: JSON.stringify(browse_ctx) });
  const list = id("browse_list"); list.innerHTML = "";
  (r.items||[]).forEach(it=>{
    const div = document.createElement("div");
    div.textContent = `${(it.type||"").toUpperCase()}  ${it.name || it.path}`;
    div.onclick = async ()=>{
      if(browse_ctx.proto==="cifs"){
        if(!browse_ctx.share && it.type==="share"){ id("m_share").value = it.name; closeModal(); return; }
        if(it.type==="dir"){ browse_ctx.path = browse_ctx.path ? `${browse_ctx.path}/${it.name}` : it.name; await doBrowse(); }
        if(it.type==="file"){ closeModal(); }
      }else{ // NFS
        if(it.type==="export"){ id("m_share").value = it.path; closeModal(); }
      }
    };
    list.appendChild(div);
  });
}

// -------- Backups table with double-confirm Restore --------
async function refreshBackups() {
  try {
    const j = await api("/api/backups");
    const items = (j.items||[]).sort((a,b)=> (b.created||0) - (a.created||0));
    const tb = id("backupsTable").querySelector("tbody");
    tb.innerHTML = "";
    items.forEach(x=>{
      const tr = document.createElement("tr");
      const size = (x.size && x.size > 0) ? human(x.size) : "";
      const date = x.created ? new Date(x.created*1000).toISOString().replace("T"," ").slice(0,19) : "";
      tr.innerHTML = `
        <td>${x.path}</td>
        <td>${x.kind || "unknown"}</td>
        <td>${x.location || "Local"}</td>
        <td>${size}</td>
        <td>${date}</td>
        <td class="row-actions"></td>`;
      const cell = tr.querySelector(".row-actions");
      const dl = document.createElement("a");
      dl.className = "btn"; dl.textContent = "Download";
      dl.href = `/api/download?path=${encodeURIComponent(x.path)}`; dl.target = "_blank";
      const rs = document.createElement("button");
      rs.className = "btn danger"; rs.textContent = "Restore";
      rs.onclick = async ()=>{
        if (!confirm(`Are you sure you want to restore from:\n${x.path}?`)) return;
        if (!confirm("FINAL WARNING: This will overwrite data at the destination. Continue?")) return;
        // Infer method from extension
        const method = x.path.endsWith(".img") || x.path.endsWith(".img.gz") ? "dd" : "rsync";
        const payload = (method==="dd")
          ? { method, username:id("r_user").value, host:id("r_host").value, password:id("r_pass").value,
              port:parseInt(id("r_port").value||"22",10), image_path:x.path, disk:id("r_disk").value }
          : { method, username:id("r_user").value, host:id("r_host").value, password:id("r_pass").value,
              port:parseInt(id("r_port").value||"22",10), local_src:x.path, remote_dest:id("r_dest").value };
        const out = await api("/api/run_restore",{method:"POST",body:JSON.stringify(payload)});
        log(out);
        alert("Restore started. Check Status/Output for progress.");
      };
      cell.appendChild(dl); cell.appendChild(document.createTextNode(" ")); cell.appendChild(rs);
      tb.appendChild(tr);
    });
  } catch (e) { log("Backups fetch failed: " + e.message); }
}
function human(bytes){
  const u=['B','KB','MB','GB','TB']; let i=0; let n=bytes;
  while(n>=1024 && i<u.length-1){ n/=1024; i++; }
  return `${n.toFixed(n>=100||i===0?0:1)} ${u[i]}`;
}

// -------- Backup / Restore actions (from forms) --------
id("btnEstimate").onclick = async ()=>{
  try{
    const body = {
      method:id("b_method").value, username:id("b_user").value, host:id("b_host").value,
      password:id("b_pass").value, port:parseInt(id("b_port").value||"22",10),
      disk:id("b_disk").value, files:id("b_files").value, bwlimit_kbps:parseInt(id("b_bw").value||"0",10)
    };
    log(await api("/api/estimate_backup",{method:"POST",body:JSON.stringify(body)}));
  }catch(e){ log("Estimate error: "+e.message); }
};
id("btnBackup").onclick = async ()=>{
  try{
    const body = {
      method:id("b_method").value, username:id("b_user").value, host:id("b_host").value,
      password:id("b_pass").value, port:parseInt(id("b_port").value||"22",10),
      disk:id("b_disk").value, files:id("b_files").value, store_to:id("b_store").value,
      verify:id("b_verify").value==="true", excludes:id("b_excludes").value,
      retention_days:parseInt(id("b_retention").value||"0",10),
      backup_name:id("b_name").value, bwlimit_kbps:parseInt(id("b_bw").value||"0",10),
      cloud_upload:id("b_cloud").value.trim()
    };
    log(await api("/api/run_backup",{method:"POST",body:JSON.stringify(body)}));
    await refreshBackups();
  }catch(e){ log("Backup error: "+e.message); }
};
id("btnRestore").onclick = async ()=>{
  try{
    if(!confirm("Are you sure?")) return;
    if(!confirm("FINAL WARNING: This will overwrite data at the destination.")) return;
    const body = {
      method:id("r_method").value, username:id("r_user").value, host:id("r_host").value,
      password:id("r_pass").value, port:parseInt(id("r_port").value||"22",10),
      disk:id("r_disk").value, image_path:id("r_src").value,
      local_src:id("r_src").value, remote_dest:id("r_dest").value,
      excludes:id("r_ex").value, bwlimit_kbps:parseInt(id("r_bw").value||"0",10)
    };
    log(await api("/api/run_restore",{method:"POST",body:JSON.stringify(body)}));
  }catch(e){ log("Restore error: "+e.message); }
};

// -------- init --------
(async function init(){
  await loadOptions();
  await refreshMounts();
  await refreshBackups();
  fillStoreTo();
})();
