
const $=s=>document.querySelector(s);const $$=s=>Array.from(document.querySelectorAll(s));
function activateTab(id){$$('.panel').forEach(p=>p.classList.add('hidden'));$('#'+id).classList.remove('hidden');$$('.tab-btn').forEach(a=>a.classList.toggle('active', a.getAttribute('href')==='#'+id));localStorage.setItem('rlb_tab',id)}
window.addEventListener('DOMContentLoaded',()=>{const saved=localStorage.getItem('rlb_tab')||'backup'; if(location.hash){activateTab(location.hash.slice(1))} else {activateTab(saved)} });
window.addEventListener('hashchange',()=>activateTab(location.hash.slice(1)));

async function j(url,opts={}){const res=await fetch(url,{headers:{'Content-Type':'application/json'}, ...opts}); return res.json();}
function log(t){const el=$('#log'); if(el){el.textContent += (t+'\n'); el.scrollTop=el.scrollHeight}}

async function refreshMounts(){const d=await j('/api/mounts'); const tb=$('#m_table tbody'); tb.innerHTML=''; (d.mounts||[]).forEach(m=>{const tr=document.createElement('tr'); tr.innerHTML=`<td>${m.name}</td><td>${m.type}</td><td>${m.host}</td><td>${m.share||''}</td><td>${m.mounted?'mounted':'not mounted'}</td><td>${m.mountpoint||''}</td>`; tb.appendChild(tr)});}
async function refreshBackups(){const d=await j('/api/backups'); const tb=$('#bk_table tbody'); tb.innerHTML=''; (d.items||[]).forEach(x=>{const tr=document.createElement('tr'); tr.innerHTML=`<td>${x.label}</td><td>${(x.size/1048576).toFixed(1)} MB</td><td>${x.location}</td><td><a href="/api/backups/download?id=${encodeURIComponent(x.id)}">Download</a></td>`; tb.appendChild(tr)});}

async function pollJob(){try{const arr=await j('/api/jobs'); const cur=arr[0]; if(!cur){$('#b_pct').textContent='0%'; $('#b_progress').value=0; return} $('#b_pct').textContent=(cur.progress||0)+'%'; $('#b_progress').value=cur.progress||0; if(cur.log&&cur.log.length){log(cur.log[cur.log.length-1])}}catch(e){}}
setInterval(pollJob,1500);

// Buttons
$('#btn_test_ssh').addEventListener('click', async ()=>{
  const body={host:$('#b_host').value, port:22, username:$('#b_user').value, password:$('#b_pass').value};
  const r=await j('/api/ssh/test',{method:'POST',body:JSON.stringify(body)}); log(JSON.stringify(r));
});
$('#btn_start').addEventListener('click', async ()=>{
  const body={
    mode: $('#b_mode').value,
    label: $('#b_label').value || 'backup',
    dest_type: $('#b_dest_type').value,
    dest_mount_name: $('#b_dest_mount').value || $('#b_dest_mount').value,
    bwlimit_kbps: parseInt($('#b_bw').value||'0',10),
    host: $('#b_host').value, username: $('#b_user').value, password: $('#b_pass').value,
    source_path: $('#b_src').value, mount_name: $('#b_dest_mount').value || $('#b_dest_mount').value,
    device: $('#b_src').value
  };
  const r=await j('/api/backup/start',{method:'POST',body:JSON.stringify(body)});
  log('start: '+JSON.stringify(r));
});
$('#btn_cancel').addEventListener('click', async ()=>{const r=await j('/api/jobs/cancel',{method:'POST'}); log(JSON.stringify(r))});

// Connections
$('#c_save').addEventListener('click', async ()=>{
  const body={name:$('#c_name').value, host:$('#c_host').value, port:parseInt($('#c_port').value||'22',10), username:$('#c_user').value, password:$('#c_pass').value};
  const r=await j('/api/connections/save',{method:'POST',body:JSON.stringify(body)}); log('conn save '+JSON.stringify(r));
});
$('#c_test').addEventListener('click', async ()=>{
  const body={host:$('#c_host').value, port:parseInt($('#c_port').value||'22',10), username:$('#c_user').value, password:$('#c_pass').value};
  const r=await j('/api/ssh/test',{method:'POST',body:JSON.stringify(body)}); log('ssh test '+JSON.stringify(r));
});

// Mounts
$('#m_save').addEventListener('click', async ()=>{
  const body={name:$('#m_name').value, type:$('#m_type').value, host:$('#m_host').value, share:$('#m_share').value, username:$('#m_user').value, password:$('#m_pass').value, options:$('#m_opts').value, auto_retry:$('#m_retry').value};
  const r=await j('/api/mounts/save',{method:'POST',body:JSON.stringify(body)}); log('mount save '+JSON.stringify(r)); refreshMounts();
});
$('#m_mount').addEventListener('click', async ()=>{
  const r=await j('/api/mounts/mount',{method:'POST',body:JSON.stringify({name:$('#m_name').value})}); log('mount '+JSON.stringify(r)); refreshMounts();
});
$('#m_unmount').addEventListener('click', async ()=>{
  const r=await j('/api/mounts/unmount',{method:'POST',body:JSON.stringify({name:$('#m_name').value})}); log('unmount '+JSON.stringify(r)); refreshMounts();
});
$('#m_test').addEventListener('click', async ()=>{
  const body={type:$('#m_type').value, host:$('#m_host').value, username:$('#m_user').value, password:$('#m_pass').value};
  const r=await j('/api/mounts/test',{method:'POST',body:JSON.stringify(body)}); log('mount test '+JSON.stringify(r));
});

// Notifications
$('#n_save').addEventListener('click', async ()=>{
  const body={url:$('#n_url').value, token:$('#n_token').value, priority:parseInt($('#n_priority').value||'5',10)};
  const r=await j('/api/notify/config',{method:'POST',body:JSON.stringify(body)}); log('notify save '+JSON.stringify(r));
});
$('#n_test').addEventListener('click', async ()=>{
  const r=await j('/api/notify/test',{method:'POST'}); log('notify test '+JSON.stringify(r));
});
$('#sys_update').addEventListener('click', async ()=>{
  const r=await j('/api/system/apt_upgrade',{method:'POST'}); $('#sys_log').textContent=(r.output||JSON.stringify(r));
});

// Initial loads
refreshMounts(); refreshBackups();
