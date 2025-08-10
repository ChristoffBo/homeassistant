(function () {
  'use strict';

  const $ = (sel, ctx=document) => ctx.querySelector(sel);
  const $$ = (sel, ctx=document) => Array.from(ctx.querySelectorAll(sel));
  const statusLine = $("#statusLine");

  // ---------------- Tabs ----------------
  function setActiveTab(name) {
    $$(".tab[data-tab]").forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    $$(".panel").forEach(p => p.classList.toggle('active', p.id === `panel-${name}`));
    window.localStorage.setItem('rlb.tab', name);
  }
  function initTabs(){
    $$(".tab[data-tab]").forEach(btn => btn.addEventListener('click', () => setActiveTab(btn.dataset.tab)));
    const last = window.localStorage.getItem('rlb.tab') || 'backup';
    setActiveTab(last);
  }

  // ---------------- HTTP helpers ----------------
  async function jget(url){
    const r = await fetch(url);
    if(!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return await r.json();
  }
  async function jpost(url, body){
    const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body||{})});
    if(!r.ok){
      const t = await r.text().catch(()=>'');
      throw new Error(`${r.status} ${r.statusText} ${t}`);
    }
    return await r.json().catch(()=>({ok:true}));
  }
  function toast(msg){ statusLine.textContent = msg; }

  // ---------------- Picker ----------------
  const picker = {
    modal: $("#pickerModal"),
    title: $("#pickerTitle"),
    pathEl: $("#pickerPath"),
    list: $("#pickerList"),
    btnUp: $("#pickerUp"),
    btnChoose: $("#pickerChoose"),
    path: "/",
    mode: "local", // local | ssh | mount
    extra: {}, // host,user,mount
    selected: null,
    open({mode, title, start, extra}){
      this.mode = mode; this.title.textContent = title;
      this.path = start || "/"; this.extra = extra||{};
      this.selected = null;
      this.modal.classList.add("open");
      this.refresh();
    },
    close(){ this.modal.classList.remove("open"); this.list.innerHTML=""; },
    async refresh(){
      this.pathEl.textContent = this.path;
      this.list.innerHTML = "";
      try{
        let items = [];
        if(this.mode === 'local'){
          const data = await jget(`/api/local/listdir?path=${encodeURIComponent(this.path)}`);
          items = data.items||data;
        }else if(this.mode === 'ssh'){
          const qs = new URLSearchParams({path:this.path, host:this.extra.host||"", user:this.extra.user||""});
          const data = await jget(`/api/ssh/listdir?${qs.toString()}`);
          items = data.items||data;
        }else if(this.mode === 'mount'){
          const qs = new URLSearchParams({path:this.path, mount:this.extra.mount||""});
          const data = await jget(`/api/mounts/listdir?${qs.toString()}`);
          items = data.items||data;
        }
        // normalize: [{name,type:'dir'|'file'}]
        items.forEach(it => {
          const li = document.createElement('li');
          li.innerHTML = `<span>${it.type==='dir'?'📁':'📄'}</span><span>${it.name}</span><span class="pill">${it.type||''}</span>`;
          li.addEventListener('click', () => {
            if(it.type === 'dir'){
              this.path = this.path.replace(/\/$/,'') + '/' + it.name;
              this.refresh();
            }else{
              this.selected = this.path.replace(/\/$/,'') + '/' + it.name;
              $$(".list li", this.list).forEach(n=>n.classList.remove('active'));
              li.classList.add('active');
            }
          });
          this.list.appendChild(li);
        });
      }catch(e){
        const li=document.createElement('li'); li.textContent = `Error: ${e.message}`; this.list.appendChild(li);
      }
    }
  };
  $("#pickerClose").addEventListener('click', ()=>picker.close());
  picker.btnUp.addEventListener('click', ()=>{
    const p = picker.path.replace(/\/+$/,'').split('/'); p.pop();
    picker.path = p.length ? p.join('/') : '/'; picker.refresh();
  });

  // ---------------- Backup page ----------------
  $("#btnBrowseSSH").addEventListener('click', ()=>{
    picker.open({mode:'ssh', title:'Browse SSH', start:$("#srcPath").value || '/', extra:{host:$("#srcHost").value, user:$("#srcUser").value}});
    picker.btnChoose.onclick = ()=>{ $("#srcPath").value = picker.selected || picker.path; picker.close(); };
  });
  $("#btnPickLocal").addEventListener('click', ()=>{
    picker.open({mode:'local', title:'Pick local', start:$("#srcPath").value || '/'});
    picker.btnChoose.onclick = ()=>{ $("#srcPath").value = picker.selected || picker.path; picker.close(); };
  });
  $("#btnPickFromMount").addEventListener('click', ()=>{
    const m = $("#dstMount").value || '';
    picker.open({mode:'mount', title:`Pick from mount (${m||'default'})`, start:$("#srcPath").value || '/', extra:{mount:m}});
    picker.btnChoose.onclick = ()=>{ $("#srcPath").value = picker.selected || picker.path; picker.close(); };
  });
  $("#btnTestSSH").addEventListener('click', async ()=>{
    try{
      const qs = new URLSearchParams({host:$("#srcHost").value, user:$("#srcUser").value});
      const r = await jget(`/api/ssh/test?${qs}`);
      toast(r.ok ? "SSH OK" : "SSH failed");
    }catch(e){ toast(`SSH error: ${e.message}`); }
  });

  // Destination pickers
  $("#btnDstPickLocal").addEventListener('click', ()=>{
    picker.open({mode:'local', title:'Pick local destination', start:$("#dstFolder").value || '/'});
    picker.btnChoose.onclick = ()=>{ $("#dstFolder").value = picker.selected || picker.path; picker.close(); };
  });
  $("#btnDstPickFromMount").addEventListener('click', ()=>{
    const m = $("#dstMount").value || '';
    picker.open({mode:'mount', title:`Pick from mount (${m||'default'})`, start:$("#dstFolder").value || '/', extra:{mount:m}});
    picker.btnChoose.onclick = ()=>{ $("#dstFolder").value = picker.selected || picker.path; picker.close(); };
  });
  $("#btnDstCreate").addEventListener('click', async ()=>{
    try{
      await jpost('/api/local/mkdir', {path: $("#dstFolder").value});
      toast("Folder created (or already exists)");
    }catch(e){ toast(`Create folder failed: ${e.message}`); }
  });

  // Start / Cancel
  $("#btnStart").addEventListener('click', async ()=>{
    const payload = {
      src_type: $("#srcType").value,
      src_host: $("#srcHost").value,
      src_user: $("#srcUser").value,
      src_pass: $("#srcPass").value,
      src_path: $("#srcPath").value,
      dst_type: $("#dstType").value,
      dst_mount: $("#dstMount").value,
      dst_folder: $("#dstFolder").value,
      mode: $("#mode").value,
      label: $("#label").value,
      bw: parseInt($("#bw").value||"0",10),
      dry: $("#dryRun").value === 'yes'
    };
    try{
      const r = await jpost('/api/backup/start', payload);
      toast(r.message || "Job started");
    }catch(e){ toast(`Start failed: ${e.message}`); }
  });
  $("#btnCancel").addEventListener('click', async ()=>{
    try{ await jpost('/api/backup/cancel', {}); toast("Cancel requested"); }catch(e){ toast(`Cancel failed: ${e.message}`); }
  });
  $("#btnEstimate").addEventListener('click', async ()=>{
    try{
      const r = await jpost('/api/backup/estimate', {src_type:$("#srcType").value, src_host:$("#srcHost").value, src_user:$("#srcUser").value, src_path:$("#srcPath").value});
      toast(`Estimated: ${r.size||'?'}`);
    }catch(e){ toast(`Estimate failed: ${e.message}`); }
  });

  // ---------------- Backups list ----------------
  async function loadBackups(){
    try{
      const data = await jget('/api/backups');
      const tb = $("#tblBackups tbody"); tb.innerHTML="";
      (data.items||data||[]).forEach(b => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${b.label||b.name||''}</td><td>${b.when||''}</td><td>${b.size||''}</td><td>${b.mode||''}</td><td>${b.source||''}</td>
          <td class="toolbar">
            <button class="btn" data-act="restore-orig">Restore (original)</button>
            <button class="btn" data-act="restore-to">Restore to…</button>
            <a class="btn" href="/api/backups/download?name=${encodeURIComponent(b.id||b.name||'')}" target="_blank">Download</a>
            <button class="btn danger" data-act="delete">Delete</button>
          </td>`;
        tr.querySelector('[data-act="restore-orig"]').addEventListener('click', async ()=>{
          try{ await jpost('/api/restore/start', {backup:b.id||b.name, mode:'original'}); toast('Restore started'); }catch(e){ toast(`Restore failed: ${e.message}`); }
        });
        tr.querySelector('[data-act="restore-to"]').addEventListener('click', async ()=>{
          picker.open({mode:'local', title:'Pick restore destination', start:'/'});
          picker.btnChoose.onclick = async ()=>{
            try{ await jpost('/api/restore/start', {backup:b.id||b.name, mode:'to', dest:picker.selected||picker.path}); toast('Restore started'); picker.close(); }catch(e){ toast(`Restore failed: ${e.message}`); }
          };
        });
        tr.querySelector('[data-act="delete"]').addEventListener('click', async ()=>{
          if(!confirm('Delete this backup?')) return;
          try{ await jpost('/api/backups/delete',{name:b.id||b.name}); loadBackups(); }catch(e){ toast(`Delete failed: ${e.message}`); }
        });
        tb.appendChild(tr);
      });
    }catch(e){ toast(`Load backups failed: ${e.message}`); }
  }

  // ---------------- Mounts ----------------
  async function loadMounts(){
    try{
      const data = await jget('/api/mounts');
      const tb = $("#tblMounts tbody"); tb.innerHTML="";
      const dstSel = $("#dstMount"); dstSel.innerHTML = '<option value="">—</option>';
      (data.items||data).forEach(m => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${m.name||''}</td><td>${m.type||''}</td><td>${m.host||''}</td><td>${m.share||m.export||''}</td>
        <td>${m.status||''}</td><td>${m.mountpoint||''}</td>
        <td class="toolbar">
          <button class="btn" data-a="use-dst">Use as destination</button>
          <button class="btn" data-a="use-src">Use as source</button>
          <button class="btn" data-a="mount">Mount</button>
          <button class="btn" data-a="unmount">Unmount</button>
          <button class="btn danger" data-a="delete">Delete</button>
        </td>`;
        tr.querySelector('[data-a="use-dst"]').onclick = ()=>{ $("#dstType").value = 'mount'; $("#dstMount").value = m.name; toast(`Destination set: ${m.name}`); };
        tr.querySelector('[data-a="use-src"]').onclick = ()=>{ $("#srcType").value = 'mount'; $("#srcPath").value = m.mountpoint || '/'; toast(`Source set: ${m.name}`); };
        tr.querySelector('[data-a="mount"]').onclick = async ()=>{ try{ await jpost('/api/mounts/mount',{name:m.name}); loadMounts(); }catch(e){ toast(e.message); } };
        tr.querySelector('[data-a="unmount"]').onclick = async ()=>{ try{ await jpost('/api/mounts/unmount',{name:m.name}); loadMounts(); }catch(e){ toast(e.message); } };
        tr.querySelector('[data-a="delete"]').onclick = async ()=>{ if(confirm('Delete mount?')){ try{ await jpost('/api/mounts/delete',{name:m.name}); loadMounts(); }catch(e){ toast(e.message);} } };
        tb.appendChild(tr);
        // dropdown option
        const opt = document.createElement('option'); opt.value = m.name; opt.textContent = m.name; dstSel.appendChild(opt);
      });
    }catch(e){ toast(`Load mounts failed: ${e.message}`); }
  }
  $("#btnMountRefresh").addEventListener('click', loadMounts);
  $("#btnBrowseMounted").addEventListener('click', ()=>{
    const m = $("#dstMount").value || '';
    picker.open({mode:'mount', title:'Browse mounted', start:'/', extra:{mount:m}});
    picker.btnChoose.onclick = ()=> picker.close();
  });

  // ---------------- Schedule ----------------
  async function loadSchedule(){
    try{
      const data = await jget('/api/schedules');
      $("#schedMax").value = data.max||1;
      $("#schedBw").value = data.bw||0;
      const tb = $("#tblSchedules tbody"); tb.innerHTML="";
      (data.items||data.jobs||[]).forEach(j => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${j.name||''}</td><td>${j.when||''}</td><td class="toolbar">
          <button class="btn danger">Delete</button></td>`;
        tr.querySelector('button').onclick = async ()=>{ if(confirm('Delete schedule?')){ try{ await jpost('/api/schedules/delete',{name:j.name}); loadSchedule(); }catch(e){ toast(e.message);} } };
        tb.appendChild(tr);
      });
    }catch(e){ /* ignore if not implemented */ }
  }
  $("#btnSchedSave").addEventListener('click', async ()=>{
    try{ await jpost('/api/schedules/save',{max:parseInt($("#schedMax").value,10)||1,bw:parseInt($("#schedBw").value,10)||0}); toast('Saved'); }catch(e){ toast(e.message); }
  });

  // ---------------- Alerts (Gotify) ----------------
  async function loadAlerts(){
    try{
      const r = await jget('/api/notify/get'); // {url, token, on, fields:{}}
      $("#gotifyUrl").value = r.url||""; $("#gotifyToken").value = r.token||""; $("#gotifyOn").value = (r.on?'1':'0');
      $("#gf_time").checked = !!(r.fields?.time ?? true);
      $("#gf_size").checked = !!(r.fields?.size ?? true);
      $("#gf_name").checked = !!(r.fields?.name ?? true);
      $("#gf_duration").checked = !!(r.fields?.duration ?? true);
      $("#gf_status").checked = !!(r.fields?.status ?? true);
    }catch(e){ /* optional */ }
  }
  $("#btnGotifySave").addEventListener('click', async ()=>{
    try{
      await jpost('/api/notify/save', {
        url: $("#gotifyUrl").value, token: $("#gotifyToken").value, on: $("#gotifyOn").value==='1',
        fields: {time:$("#gf_time").checked, size:$("#gf_size").checked, name:$("#gf_name").checked, duration:$("#gf_duration").checked, status:$("#gf_status").checked}
      }); toast('Saved');
    }catch(e){ toast(e.message); }
  });
  $("#btnGotifyTest").addEventListener('click', async ()=>{
    try{ await jpost('/api/notify/test', {}); toast('Sent'); }catch(e){ toast(e.message); }
  });

  // ---------------- Jobs polling ----------------
  async function poll(){
    try{
      const r = await jget('/api/jobs');
      const p = Math.min(100, Math.max(0, r.progress || 0));
      $("#progressBar").style.width = p + "%";
      if(r.state){ toast(`${r.state}${r.message?': '+r.message:''}`); }
    }catch(e){ /* ignore */ }
    setTimeout(poll, 2000);
  }

  // Init
  initTabs();
  loadMounts();
  loadBackups();
  loadSchedule();
  loadAlerts();
  poll();
})();