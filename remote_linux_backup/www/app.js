const $=s=>document.querySelector(s);const $$=s=>Array.from(document.querySelectorAll(s));
function activateTab(id){$$('.panel').forEach(p=>p.classList.add('hidden'));$('#'+id).classList.remove('hidden');$$('.tab-btn').forEach(a=>a.classList.toggle('active', a.getAttribute('href')==='#'+id));localStorage.setItem('rlb_tab',id)}
window.addEventListener('DOMContentLoaded',()=>{const saved=localStorage.getItem('rlb_tab')||'backup'; if(location.hash){activateTab(location.hash.slice(1))} else {activateTab(saved)} });
window.addEventListener('hashchange',()=>activateTab(location.hash.slice(1)));

async function j(url,opts={}){const res=await fetch(url,{headers:{'Content-Type':'application/json'}, ...opts}); return res.json();}
function logInto(id, t){const el=$(id); if(!el) return; el.textContent += (t+'\n'); el.scrollTop=el.scrollHeight;}

// Backup actions + logs
$('#btn_test_ssh').addEventListener('click', async ()=>{
  const body={host:$('#b_host').value, port:22, username:$('#b_user').value, password:$('#b_pass').value};
  const r=await j('/api/ssh/test',{method:'POST',body:JSON.stringify(body)}); logInto('#log_backup', JSON.stringify(r));
});
$('#btn_start').addEventListener('click', async ()=>{
  const body={
    mode: $('#b_mode').value,
    label: $('#b_label').value || 'backup',
    dest_type: $('#b_dest_type').value,
    dest_mount_name: $('#b_dest_mount').value,
    bwlimit_kbps: parseInt($('#b_bw').value||'0',10),
    dry_run: $('#b_dry').value==='1',
    verify: $('#b_verify').value==='1',
    profile: ($('#b_profile').value||'').toLowerCase(),
    host: $('#b_host').value, username: $('#b_user').value, password: $('#b_pass').value,
    source_path: $('#b_src').value, mount_name: $('#b_dest_mount').value, device: $('#b_src').value
  };
  const r=await j('/api/backup/start',{method:'POST',body:JSON.stringify(body)});
  logInto('#log_backup', 'start: '+JSON.stringify(r));
});
$('#btn_cancel').addEventListener('click', async ()=>{const r=await j('/api/jobs/cancel',{method:'POST'}); logInto('#log_backup', JSON.stringify(r))});

async function pollJob(){try{const arr=await j('/api/jobs'); const cur=arr[0]; if(!cur){$('#b_pct').textContent='0%'; $('#b_progress').value=0; return} $('#b_pct').textContent=(cur.progress||0)+'%'; $('#b_progress').value=cur.progress||0; if(cur.log&&cur.log.length){logInto('#log_backup', cur.log[cur.log.length-1])}}catch(e){}}
setInterval(pollJob,1500);

// Connections logs
$('#c_save').addEventListener('click', async ()=>{
  const body={name:$('#c_name').value, host:$('#c_host').value, port:parseInt($('#c_port').value||'22',10), username:$('#c_user').value, password:$('#c_pass').value};
  const r=await j('/api/connections/save',{method:'POST',body:JSON.stringify(body)}); logInto('#log_connections', 'save '+JSON.stringify(r));
});
$('#c_test').addEventListener('click', async ()=>{
  const body={host:$('#c_host').value, port:parseInt($('#c_port').value||'22',10), username:$('#c_user').value, password:$('#c_pass').value};
  const r=await j('/api/ssh/test',{method:'POST',body:JSON.stringify(body)}); logInto('#log_connections','test '+JSON.stringify(r));
});

// Mounts logs
async function refreshMounts(){const d=await j('/api/mounts'); const tb=$('#m_table tbody'); tb.innerHTML=''; (d.mounts||[]).forEach(m=>{const tr=document.createElement('tr'); tr.innerHTML=`<td>${m.name}</td><td>${m.type}</td><td>${m.host}</td><td>${m.share||''}</td><td>${m.mounted?'mounted':'not mounted'}</td><td>${m.mountpoint||''}</td>`; tb.appendChild(tr)});}
$('#m_save').addEventListener('click', async ()=>{
  const body={name:$('#m_name').value, type:$('#m_type').value, host:$('#m_host').value, share:$('#m_share').value, username:$('#m_user').value, password:$('#m_pass').value, options:$('#m_opts').value, auto_retry:$('#m_retry').value};
  const r=await j('/api/mounts/save',{method:'POST',body:JSON.stringify(body)}); logInto('#log_mounts', 'save '+JSON.stringify(r)); refreshMounts();
});
$('#m_mount').addEventListener('click', async ()=>{
  const r=await j('/api/mounts/mount',{method:'POST',body:JSON.stringify({name:$('#m_name').value})}); logInto('#log_mounts', 'mount '+JSON.stringify(r)); refreshMounts();
});
$('#m_unmount').addEventListener('click', async ()=>{
  const r=await j('/api/mounts/unmount',{method:'POST',body:JSON.stringify({name:$('#m_name').value})}); logInto('#log_mounts', 'unmount '+JSON.stringify(r)); refreshMounts();
});
$('#m_test').addEventListener('click', async ()=>{
  const body={type:$('#m_type').value, host:$('#m_host').value, username:$('#m_user').value, password:$('#m_pass').value};
  const r=await j('/api/mounts/test',{method:'POST',body:JSON.stringify(body)}); logInto('#log_mounts', 'test '+JSON.stringify(r));
});

// Backups list + logs
async function refreshBackups(){const d=await j('/api/backups'); const tb=$('#bk_table tbody'); tb.innerHTML=''; (d.items||[]).forEach(x=>{const tr=document.createElement('tr'); tr.innerHTML=`<td>${x.label}</td><td>${(x.size/1048576).toFixed(1)} MB</td><td>${x.location}</td><td><a href="/api/backups/download?id=${encodeURIComponent(x.id)}">Download</a></td>`; tb.appendChild(tr)});}
$('#btn_upload').addEventListener('click', async ()=>{
  const fi=$('#upload_input'); if(!fi.files.length){alert('Pick a file'); return;}
  const fd=new FormData(); fd.append('file', fi.files[0]); const res=await fetch('/api/upload',{method:'POST', body:fd}); const d=await res.json(); logInto('#log_backups','upload '+JSON.stringify(d)); refreshBackups();
});

// Schedules logs
async function refreshSchedules(){const d=await j('/api/schedules'); const tb=$('#sch_table tbody'); tb.innerHTML=''; (d.schedules||[]).forEach(s=>{const tr=document.createElement('tr'); tr.innerHTML=`<td>${s.name||''}</td><td>${s.frequency}</td><td>${s.time}</td><td>${s.next_run||''}</td><td>${s.enabled?'Yes':'No'}</td>`; tb.appendChild(tr)});}
$('#sch_save').addEventListener('click', async ()=>{
  const body={name:$('#sch_name').value, frequency:$('#sch_freq').value, time:$('#sch_time').value, day:$('#sch_day').value, enabled:$('#sch_enabled').value==='1', template:{
    mode: $('#sch_mode').value, host: $('#sch_host').value, username: $('#sch_user').value, password: $('#sch_pass').value,
    source_path: $('#sch_src').value, mount_name: $('#sch_mount').value, dest_type: $('#sch_dest_type').value, dest_mount_name: $('#sch_dest_mount').value,
    label: $('#sch_label').value, bwlimit_kbps: parseInt($('#sch_bw').value||'0',10)
  }};
  const r=await j('/api/schedules/save',{method:'POST',body:JSON.stringify(body)}); logInto('#log_schedule', 'save '+JSON.stringify(r)); refreshSchedules();
});

// Notifications logs
async function loadNotify(){
  const d=await j('/api/notify/config');
  if(d.enabled) $('#n_enabled').value='1'; else $('#n_enabled').value='0';
  $('#n_url').value=d.url||''; $('#n_token').value=d.token||''; $('#n_priority').value=d.priority||5;
  const inc=d.include||{}; $('#inc_date').checked=!!inc.date; $('#inc_size').checked=!!inc.size; $('#inc_dur').checked=!!inc.duration; $('#inc_fail').checked=!!inc.failure;
}
$('#n_save').addEventListener('click', async ()=>{
  const body={enabled: $('#n_enabled').value==='1', url: $('#n_url').value, token: $('#n_token').value, priority: parseInt($('#n_priority').value||'5',10),
  include:{date:$('#inc_date').checked,size:$('#inc_size').checked,duration:$('#inc_dur').checked,failure:$('#inc_fail').checked}};
  const r=await j('/api/notify/config',{method:'POST',body:JSON.stringify(body)}); logInto('#log_notifications','save '+JSON.stringify(r));
});
$('#n_test').addEventListener('click', async ()=>{
  const r=await j('/api/notify/test',{method:'POST'}); logInto('#log_notifications','test '+JSON.stringify(r));
});

// Health
async function refreshHealth(){const d=await j('/api/health'); $('#health_info').textContent = JSON.stringify(d, null, 2);}

// Restore logs
async function loadRestoreBackups(){const d=await j('/api/backups'); const sel=$('#r_backup'); sel.innerHTML=''; (d.items||[]).forEach(x=>{const o=document.createElement('option'); o.value=x.id; o.textContent=x.label; sel.appendChild(o)});}
$('#r_start').addEventListener('click', async ()=>{
  const body={from_id: $('#r_backup').value, to_mode: $('#r_mode').value, to_path: $('#r_path').value, bwlimit_kbps: parseInt($('#r_bw').value||'0',10),
  host: $('#r_host').value, username: $('#r_user').value, password: $('#r_pass').value};
  const r=await j('/api/restore/start',{method:'POST',body:JSON.stringify(body)}); logInto('#log_restore', JSON.stringify(r));
});

// Picker Modal
let picker = {mode:'local', path:'/', mount:'', context:'Local', onChoose:null, ssh:{host:'',user:'',pass:''}};
const pm = id=>document.getElementById(id);
function showPicker(show){pm('picker_modal').classList.toggle('hidden', !show);}
async function loadMountNames(){const d=await j('/api/mounts'); const sel=pm('picker_mount'); sel.innerHTML=''; (d.mounts||[]).forEach(m=>{const o=document.createElement('option'); o.value=m.name; o.textContent=m.name; sel.appendChild(o)})}
async function listDir(){
  const tbody = pm('picker_table').querySelector('tbody'); tbody.innerHTML='';
  let items = [];
  if(picker.mode==='local'){ const d=await j('/api/local/listdir?path='+encodeURIComponent(picker.path||'/')); items=d.items||[]; }
  else if(picker.mode==='ssh'){ const body={host:picker.ssh.host, port:22, username:picker.ssh.user, password:picker.ssh.pass, path:picker.path||'/'}; const d=await j('/api/ssh/listdir',{method:'POST',body:JSON.stringify(body)}); items=d.items||[]; }
  else if(picker.mode==='mount'){ const body={name:picker.mount, path:picker.path||'/'}; const d=await j('/api/mounts/listdir',{method:'POST',body:JSON.stringify(body)}); items=d.items||[]; }
  items.forEach(it=>{const tr=document.createElement('tr'); tr.innerHTML=`<td>${it.name}</td><td>${it.dir?'Dir':'File'}</td><td>${it.size||''}</td>`; tr.addEventListener('click',()=>{ if(it.dir){ picker.path=(picker.path.replace(/\/$/,'')+'/'+it.name).replace(/\/+/g,'/'); pm('picker_path').value=picker.path; listDir(); } }); tbody.appendChild(tr);});
  pm('picker_context').value=picker.context; pm('picker_path').value=picker.path; pm('picker_mount').value=picker.mount||'';
}
pm('picker_close').addEventListener('click', ()=>showPicker(false));
pm('picker_up').addEventListener('click', ()=>{ let p=picker.path||'/'; p=p.replace(/\/+$/,''); p=p.substring(0,p.lastIndexOf('/'))||'/'; picker.path=p; pm('picker_path').value=p; listDir(); });
pm('picker_choose').addEventListener('click', ()=>{ if(picker.onChoose){ picker.onChoose(picker.path) } showPicker(false); });
pm('picker_mount').addEventListener('change', ()=>{ picker.mount=pm('picker_mount').value; picker.path='/'; listDir(); });

async function openPicker(mode, onChoose){
  picker.mode=mode; picker.onChoose=onChoose; picker.path='/';
  if(mode==='local'){ picker.context='Local filesystem'; await listDir(); showPicker(true); }
  else if(mode==='ssh'){ picker.context='SSH browse'; picker.ssh={host:$('#b_host').value,user:$('#b_user').value,pass:$('#b_pass').value}; await listDir(); showPicker(true); }
  else if(mode==='mount'){ picker.context='Mount browse'; await loadMountNames(); picker.mount=pm('picker_mount').value; await listDir(); showPicker(true); }
}
$('#btn_browse_local').addEventListener('click', ()=>openPicker('local', p=>{$('#b_src').value=p}));
$('#btn_browse_ssh').addEventListener('click', ()=>openPicker('ssh', p=>{$('#b_src').value=p}));
$('#btn_browse_mount').addEventListener('click', ()=>openPicker('mount', p=>{$('#b_src').value=p}));

// Estimate
$('#btn_estimate').addEventListener('click', async ()=>{
  let body={mode:'local', path:$('#b_src').value}; const st=$('#b_src_type').value;
  if(st==='SSH (remote)'){ body={mode:'ssh', path:$('#b_src').value, host:$('#b_host').value, username:$('#b_user').value, password:$('#b_pass').value}; }
  else if(st==='Mount (SMB/NFS)'){ body={mode:'mount', name:$('#b_dest_mount').value, path:$('#b_src').value}; }
  const d=await j('/api/estimate',{method:'POST',body:JSON.stringify(body)}); logInto('#log_backup', 'estimate '+JSON.stringify(d)); alert('Estimated size: '+(d.bytes? (d.bytes/1048576).toFixed(1)+' MB' : 'unknown'));
});

// Wizard clickable badges
$$('.wizard .step').forEach(el=>el.addEventListener('click',()=>{$$('.wizard .step').forEach(s=>s.classList.remove('active')); el.classList.add('active'); window.scrollTo({top:document.querySelector('#backup').offsetTop,behavior:'smooth'});}));

// Initial loads
refreshMounts(); refreshBackups(); refreshSchedules(); loadNotify(); refreshHealth(); loadRestoreBackups();
