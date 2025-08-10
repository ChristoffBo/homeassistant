// UI persistence
function persistField(id){ const el=$(id); if(!el) return; const key='RLB:'+id; const saved=localStorage.getItem(key); if(saved!==null){ el.value=saved; } el.addEventListener('input',()=>localStorage.setItem(key, el.value)); }
['#b_host','#b_user','#b_label','#b_src','#b_device','#r_host','#r_user','#r_dest_path','#r_device','#c_name','#c_host','#c_port','#c_user','#m_name','#m_host','#m_share','#m_user','#m_export','#m_opts','#s_name','#s_label','#s_src','#s_hour','#s_min','#s_weekday','#s_day'].forEach(persistField);
['#retention_minfree','#retention_keep_last','#retention_max_age','#b_mount_sub','#s_mount_sub'].forEach(persistField);

const $ = (q)=>document.querySelector(q);
const $$ = (q)=>Array.from(document.querySelectorAll(q));

// Tabs
$$('.tabbtn').forEach(btn=>btn.addEventListener('click',()=>{
  $$('.tabbtn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  const t = btn.dataset.tab;
  $$('main > section').forEach(s=>s.classList.add('hidden'));
  $('#'+t).classList.remove('hidden');
  if(t==='backups'){ loadBackups(); loadRetention(); }
  if(t==='connections'){ loadConnections(); }
  if(t==='schedule'){ loadSchedule(); populateScheduleMounts(); loadJobsCfg(); }
  if(t==='restore'){ populateRestoreLists(); }
  if(t==='mounts'){ loadMounts(); }
}));

// Socket for logs + job updates
const socket = io();
socket.on('connect', ()=> log('[socket] connected'));
socket.on('log', d => log(`[${d.kind}] ${d.msg}`));
let LAST_JOB_ID = null;
socket.on('job_update', job => {
  LAST_JOB_ID = job.id;
  if(job.kind.includes('backup')){
    $('#b_progbar').style.width = (job.progress||0)+'%';
    $('#b_progtext').textContent = (job.progress||0)+'%';
  } else {
    $('#r_progbar').style.width = (job.progress||0)+'%';
    $('#r_progtext').textContent = (job.progress||0)+'%';
  }
});

// Logs stream tail as text
(function tail(){
  fetch('/api/logs/tail').then(resp=>{
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    function pump(){
      reader.read().then(({done, value})=>{
        if(done) return setTimeout(tail, 2000);
        const text = dec.decode(value);
        const el = $('#footerlog');
        el.textContent += text;
        el.scrollTop = el.scrollHeight;
        pump();
      });
    }
    pump();
  });
})();

function log(s){ const el=$('#footerlog'); el.textContent += s+"\n"; el.scrollTop = el.scrollHeight; }

// Connections
function loadConnections(){
  fetch('/api/connections').then(r=>r.json()).then(d=>{
    const tb = $('#c_table tbody'); tb.innerHTML='';
    d.connections.forEach(c=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${c.name}</td><td>${c.host}:${c.port||22}</td><td>${c.username}</td><td>${c.has_password? 'saved' : 'ask'}</td>
      <td><button class="danger" data-del="${c.name}">Delete</button></td>`;
      tb.appendChild(tr);
    });
    // Fill selectors
    const fill = (sel)=>{
      sel.innerHTML = '<option value="">-- choose --</option>' + d.connections.map(c=>`<option value="${c.name}">${c.name}</option>`).join('');
    };
    fill($('#b_conn')); fill($('#r_conn')); fill($('#s_conn'));
    tb.querySelectorAll('button[data-del]').forEach(b=>b.addEventListener('click',()=>{
      fetch('/api/connections/delete',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name:b.dataset.del})})
      .then(()=>loadConnections());
    }));
  });
}
$('#c_save').addEventListener('click', ()=>{
  const body = {
    name: $('#c_name').value.trim(),
    host: $('#c_host').value.trim(),
    port: parseInt($('#c_port').value||'22',10),
    username: $('#c_user').value.trim(),
    password: $('#c_pass').value,
    persist_password: true
  };
  fetch('/api/connections/save',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})
  .then(r=>r.json()).then(d=>{
    if(!d.ok){ alert('Save failed: '+(d.error||'unknown')); return; }
    loadConnections();
  });
});
$('#c_test').addEventListener('click', ()=>{
  const body = {
    host: $('#c_host').value.trim(),
    port: parseInt($('#c_port').value||'22',10),
    username: $('#c_user').value.trim(),
    password: $('#c_pass').value,
    path: '/'
  };
  fetch('/api/connections/test',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})
  .then(r=>r.json()).then(d=>{
    alert(d.ok? 'OK: Connection works' : ('Failed: '+d.error));
  });
});

// Backup tab
$('#b_mode').addEventListener('change', ()=>{
  const v = $('#b_mode').value;
  $('#b_src_row').classList.toggle('hidden', v!=='copy');
  $('#b_dev_row').classList.toggle('hidden', v!=='image');
});
$('#b_browse').addEventListener('click', async ()=>{
  const {host,user,pass,conn} = readConnInputs('b_');
  if(!host && !conn){ alert('Choose a connection or enter host.'); return; }
  let start = prompt('Enter a start path (e.g., / or /var/log):','/'); if(!start) return;
  openPicker({connection_name: conn, host, username:user, password:pass}, start, (chosen)=>{ $('#b_src').value = chosen; });
});
$('#b_start').addEventListener('click', ()=>{
  const {host,user,pass,conn} = readConnInputs('b_');
  const label = $('#b_label').value.trim();
  const mode = $('#b_mode').value;
  const bwlimit = parseInt($('#b_bwlimit').value||'0',10);
  if(mode==='copy'){
    const body = {mode, source_path: $('#b_src').value.trim(), label, bwlimit_kbps: bwlimit};
    addConnToBody(body, conn, host, user, pass);
    startJob('/api/backup/start', body);
  } else {
    const body = {mode, device: $('#b_device').value.trim(), label, bwlimit_kbps: bwlimit, encrypt: $('#b_encrypt').value==='1', passphrase: $('#b_passphrase').value};
    addConnToBody(body, conn, host, user, pass);
    if(!confirm('This will read a full disk device. Ensure the device path is correct. Continue?')) return;
    startJob('/api/backup/start', body);
  }
});

// Restore tab
$('#r_mode').addEventListener('change', ()=>{
  const v = $('#r_mode').value;
  $('#r_src_folder_row').classList.toggle('hidden', v!=='rsync');
  $('#r_dest_path_row').classList.toggle('hidden', v!=='rsync');
  $('#r_src_image_row').classList.toggle('hidden', v!=='image');
  $('#r_device_row').classList.toggle('hidden', v!=='image');
  $('#r_passphrase_row').classList.toggle('hidden', v!=='image');
  $('#r_confirm_row').classList.toggle('hidden', v!=='image');
});
function populateRestoreLists(){
  fetch('/api/backups').then(r=>r.json()).then(all=>{
    const folders = new Set();
    const images = [];
    all.forEach(it=>{
      if(it.rel.endsWith('.img.gz')) images.push(it);
      else {
        const p = it.rel.split('/'); p.pop(); // folder
        folders.add(p.join('/'));
      }
    });
    const fsel = $('#r_local_folder');
    fsel.innerHTML = '<option value="">-- choose --</option>' + Array.from(folders).filter(Boolean).map(x=>`<option value="${x}">${x}</option>`).join('');
    const isel = $('#r_local_image');
    isel.innerHTML = '<option value="">-- choose --</option>' + images.map(x=>`<option value="${x.rel}">${x.rel} (${x.size_h})</option>`).join('');
  });
}
$('#r_start').addEventListener('click', ()=>{
  const {host,user,pass,conn} = readConnInputs('r_');
  const mode = $('#r_mode').value;
  if(mode==='rsync'){
    const folder = $('#r_local_folder').value;
    const dest = $('#r_dest_path').value.trim();
    if(!folder || !dest){ alert('Choose a folder and destination path.'); return; }
    const body = {mode:'rsync', local_src: folder, dest_path: dest, dry_run: $('#r_dryrun').value==='1'};
    addConnToBody(body, conn, host, user, pass);
    startJob('/api/restore/start', body);
  } else {
    const image = $('#r_local_image').value;
    const dev = $('#r_device').value.trim();
    if(!image || !dev){ alert('Choose an image and device.'); return; }
    if(!confirm('RESTORE IMAGE: This will overwrite the device on the remote system. Are you 100% sure?')) return;
    const body = {mode:'image', local_src: image, device: dev, passphrase: $('#r_passphrase').value, confirm: $('#r_confirm').value, force: false};
    addConnToBody(body, conn, host, user, pass);
    startJob('/api/restore/start', body);
  }
});

function readConnInputs(prefix){
  return {
    conn: $('#'+prefix+'conn')?.value || '',
    host: $('#'+prefix+'host')?.value.trim() || '',
    user: $('#'+prefix+'user')?.value.trim() || '',
    pass: $('#'+prefix+'pass')?.value || ''
  };
}
function addConnToBody(body, conn, host, user, pass){
  if(conn) body.connection_name = conn;
  else { body.host = host; body.username = user; body.password = pass; }
}

// Remote file browser (SFTP)
async function browseRemote(body){ /* legacy */
  try{
    const r = await fetch('/api/remote/listdir',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    const d = await r.json();
    if(!d.ok){ alert('Browse failed: '+(d.error||'unknown')); return null; }
    let cur = body.path || '/';
    while(true){
      const choice = prompt(
        `Listing: ${cur}\n`+
        d.items.map((it,i)=>`${i+1}. ${it.is_dir? '[D]':'[F]'} ${it.name} ${it.size? '('+it.size+'B)':''}`).join('\n')+
        "\nEnter number to descend into a folder, '..' to go up, '.' to choose this folder, or a full path:",
        "."
      );
      if(choice===null) return null;
      if(choice==='.') return cur;
      if(choice==='..'){ cur = cur.split('/').slice(0,-1).join('/')||'/'; body.path=cur; const r2 = await fetch('/api/remote/listdir',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)}); d = await r2.json(); continue; }
      if(choice.startsWith('/')){ cur = choice; body.path=cur; const r2 = await fetch('/api/remote/listdir',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)}); d = await r2.json(); continue; }
      const idx = parseInt(choice,10)-1;
      if(!isNaN(idx) && d.items[idx] && d.items[idx].is_dir){
        cur = d.items[idx].path;
        body.path = cur;
        const r2 = await fetch('/api/remote/listdir',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
        d = await r2.json();
        if(!d.ok){ alert('Browse failed: '+(d.error||'unknown')); return null; }
        continue;
      }
      alert('Invalid choice');
    }
  }catch(e){ alert('Browse error: '+e); return null; }
}

function startJob(url, body){
  fetch(url,{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})
  .then(r=>r.json()).then(d=>{
    if(!d.ok){ alert('Error: '+(d.error||'unknown')); return; }
    log('Started job '+d.job_id);
  });
}

// Backups list
function loadBackups(){
  fetch('/api/backups').then(r=>r.json()).then(rows=>{
    const tb = $('#b_table tbody'); tb.innerHTML='';
    rows.forEach(r=>{
      const tr = document.createElement('tr');
      const when = new Date(r.mtime*1000).toLocaleString();
      tr.innerHTML = `<td>${r.rel}</td><td>${r.size_h}</td><td>${when}</td>
        <td>
          <a href="/api/backups/download?rel=${encodeURIComponent(r.rel)}" target="_blank"><button class="secondary">Download</button></a>
          <button class="danger" data-del="${r.rel}">Delete</button>
        </td>`;
      tb.appendChild(tr);
    });
    tb.querySelectorAll('button[data-del]').forEach(b=>b.addEventListener('click',()=>{
      if(!confirm('Delete '+b.dataset.del+' ?')) return;
      fetch('/api/backups/delete',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({rel:b.dataset.del})})
      .then(()=>loadBackups());
    }));
  });
}

// Schedule
function loadSchedule(){
  loadConnections();
  fetch('/api/schedule').then(r=>r.json()).then(d=>{
    const tb = $('#s_table tbody'); tb.innerHTML='';
    (d.jobs||[]).forEach(j=>{
      const cron = j.cron||{};
      const cronTxt = cron.type==='daily' ? `Daily @ ${cron.hour}:${String(cron.minute).padStart(2,'0')}` :
                      cron.type==='weekly' ? `Weekly(${cron.weekday}) @ ${cron.hour}:${String(cron.minute).padStart(2,'0')}` :
                      `Monthly(${cron.day}) @ ${cron.hour}:${String(cron.minute).padStart(2,'0')}`;
      const tr=document.createElement('tr');
      tr.innerHTML = `<td>${j.name}</td><td>${j.connection_name}</td><td>${j.mode}</td><td>${j.source_path||j.device||''}</td><td>${cronTxt}</td>`;
      tb.appendChild(tr);
    });
  });
}
$('#s_mode').addEventListener('change', ()=>{
  const v = $('#s_mode').value;
  $('#s_src_row label').textContent = v==='image' ? 'Device (e.g., /dev/sda)' : 'Source path (folder)';
});
$('#s_type').addEventListener('change', ()=>{
  const v = $('#s_type').value;
  $('#s_week_row').classList.toggle('hidden', v!=='weekly');
  $('#s_day_row').classList.toggle('hidden', v!=='monthly');
});
$('#s_add').addEventListener('click', ()=>{
  const job = {
    name: $('#s_name').value.trim(),
    connection_name: $('#s_conn').value,
    mode: $('#s_mode').value,
    label: $('#s_label').value.trim(),
    source_path: $('#s_src').value.trim(),
    mount_name: $('#s_use_mount').value || undefined,
    mount_sub: $('#s_mount_sub').value.trim(),
    device: $('#s_src').value.trim(),
    cron: {
      type: $('#s_type').value,
      hour: parseInt($('#s_hour').value||'3',10),
      minute: parseInt($('#s_min').value||'0',10),
      weekday: parseInt($('#s_weekday').value||'0',10),
      day: parseInt($('#s_day').value||'1',10)
    }
  };
  // Fetch existing, append, save
  fetch('/api/schedule').then(r=>r.json()).then(d=>{
    const jobs = d.jobs||[]; jobs.push(job);
    return fetch('/api/schedule/save',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({jobs})});
  }).then(()=> loadSchedule());
});

// Notifications
$('#n_test').addEventListener('click', ()=>{
  fetch('/api/gotify/test',{method:'POST'}).then(r=>r.json()).then(d=>{
    alert(d.sent? 'Sent' : 'Not configured or failed');
  });
});

// Restore lists initial load
populateRestoreLists();
loadConnections();
loadBackups();

let pickerState = { body:null, cur:'/' };
async function openPicker(body, startPath, onChoose){
  pickerState.body = {...body};
  pickerState.cur = startPath || '/';
  const picker = $('#picker');
  const list = $('#picker_list');
  const ppath = $('#picker_path');
  function renderItems(items){
    list.innerHTML = '';
    items.forEach(it=>{
      if(!it.is_dir) return; // Only dirs selectable
      const row = document.createElement('div');
      row.className = 'picker-item';
      row.innerHTML = `<span>📁 ${it.name}</span><span class="small">${it.path}</span>`;
      row.addEventListener('click', async ()=>{
        pickerState.cur = it.path;
        await refresh();
      });
      list.appendChild(row);
    });
  }
  async function refresh(){
    ppath.textContent = pickerState.cur;
    const r = await fetch('/api/remote/listdir',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({...pickerState.body, path: pickerState.cur})});
    const d = await r.json();
    if(!d.ok){ alert('Browse failed: '+(d.error||'unknown')); return; }
    renderItems(d.items||[]);
  }
  $('#picker_up').onclick = async ()=>{
    const parts = pickerState.cur.split('/').filter(Boolean);
    parts.pop(); pickerState.cur = '/' + parts.join('/');
    await refresh();
  };
  $('#picker_close').onclick = ()=>{ picker.classList.add('hidden'); };
  $('#picker_choose').onclick = ()=>{ onChoose(pickerState.cur); picker.classList.add('hidden'); };
  picker.classList.remove('hidden');
  await refresh();
}

$('#b_src_type').addEventListener('change', ()=>{
  const t = $('#b_src_type').value;
  const isSSH = t==='ssh';
  $('#b_src_row').classList.toggle('hidden', !isSSH);
  $('#b_mount_row').classList.toggle('hidden', isSSH);
  $('#b_dev_row').classList.toggle('hidden', $('#b_mode').value!=='image');
});
// Estimation
$('#b_estimate').addEventListener('click', async ()=>{
  const {host,user,pass,conn} = readConnInputs('b_');
  const path = $('#b_src').value.trim() || '/';
  if(!(host||conn)){ alert('Enter connection or choose saved'); return; }
  let body = {path};
  if(conn) body.connection_name = conn; else { body.host=host; body.username=user; body.password=pass; }
  if(conn){ // need resolved credentials; prompt if not saved
    // backend uses saved password; attempt anyway
  }
  const r = await fetch('/api/estimate/ssh_size',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({host, port:22, username:user, password:pass, path})});
  const d = await r.json();
  if(!d.ok){ alert('Estimate failed: '+(d.error||'unknown')); return; }
  $('#b_estimate_out').textContent = d.bytes ? (Math.round(d.bytes/1024/1024)+' MB') : 'unknown';
});

$('#b_estimate_mount').addEventListener('click', async ()=>{
  const name = $('#b_mount').value; const path = $('#b_mount_sub').value.trim()||'/';
  if(!name){ alert('Choose a mount'); return; }
  const r = await fetch('/api/estimate/mount_size?'+new URLSearchParams({name, path})); const d = await r.json();
  if(!d.ok){ alert('Estimate failed: '+(d.error||'unknown')); return; }
  $('#b_estimate_mount_out').textContent = d.bytes ? (Math.round(d.bytes/1024/1024)+' MB') : 'unknown';
});
// Retention UI
async function loadRetention(){
  const d = await (await fetch('/api/retention')).json();
  $('#retention_dir').value = d.backups_dir;
  $('#retention_free').value = d.free_gb+' GB';
  $('#retention_total').value = d.total_gb+' GB';
  $('#retention_minfree').value = d.config.min_free_gb;
  $('#retention_keep_last').value = d.config.keep_last;
  $('#retention_max_age').value = d.config.max_age_days;
}
$('#retention_save').addEventListener('click', async ()=>{
  const body = {
    min_free_gb: parseFloat($('#retention_minfree').value||'0'),
    keep_last: parseInt($('#retention_keep_last').value||'0',10),
    max_age_days: parseInt($('#retention_max_age').value||'0',10)
  };
  const r = await fetch('/api/retention',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const d = await r.json();
  if(!d.ok){ alert('Save failed'); return; }
  await loadRetention();
});
async function populateScheduleMounts(){
  const d = await (await fetch('/api/mounts')).json();
  const sel = $('#s_use_mount'); sel.innerHTML = '<option value="">-- none --</option>' + (d.mounts||[]).map(m=>`<option value="${m.name}">${m.name}</option>`).join('');
}
$('#b_cancel').addEventListener('click', async ()=>{
  if(!LAST_JOB_ID){ alert('No running job'); return; }
  const r = await fetch('/api/jobs/cancel',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({job_id: LAST_JOB_ID})});
  const d = await r.json();
  if(!d.ok){ alert('Cancel failed: '+(d.error||'unknown')); } else { alert('Canceled'); }
});
async function loadJobsCfg(){
  const d = await (await fetch('/api/jobs/config')).json();
  $('#j_maxc').value = d.max_concurrent;
  $('#j_bw').value = d.default_bwlimit_kbps;
}
$('#j_save').addEventListener('click', async ()=>{
  const body = {max_concurrent: parseInt($('#j_maxc').value||'1',10), default_bwlimit_kbps: parseInt($('#j_bw').value||'0',10)};
  const r = await fetch('/api/jobs/config',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const d = await r.json(); if(!d.ok){ alert('Save failed'); } else { alert('Saved'); }
});
let BACKUPS_CACHE = [];
function renderBackups(){
  const tb = $('#b_table tbody'); tb.innerHTML='';
  const q = ($('#b_search').value||'').toLowerCase().trim();
  const group = $('#b_group').value || '';
  const rows = BACKUPS_CACHE.filter(r=> (group=='' || r.rel.startsWith(group+'/')) && (q=='' || r.rel.toLowerCase().includes(q)));
  rows.forEach(r=>{
    const tr = document.createElement('tr');
    const when = new Date(r.mtime*1000).toLocaleString();
    tr.innerHTML = `<td>${r.rel}</td><td>${r.size_h}</td><td>${when}</td>
      <td>
        <a href="/api/backups/download?rel=${encodeURIComponent(r.rel)}" target="_blank"><button class="secondary">Download</button></a>
        ${r.is_dir ? `<button class="secondary" data-verify="${r.rel}">Verify</button>` : ''}
        <button class="danger" data-del="${r.rel}">Delete</button>
      </td>`;
    tb.appendChild(tr);
  });
  tb.querySelectorAll('button[data-del]').forEach(b=>b.addEventListener('click',()=>{
    if(!confirm('Delete '+b.dataset.del+' ?')) return;
    fetch('/api/backups/delete',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({rel:b.dataset.del})})
    .then(()=>loadBackups());
  }));
  tb.querySelectorAll('button[data-verify]').forEach(b=>b.addEventListener('click', async ()=>{
    const r = await fetch('/api/verify/start',{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({rel: b.dataset.verify})}); const d = await r.json();
    if(!d.ok){ alert('Verify start failed'); } else { alert('Verify started: '+d.job_id); }
  }));
}
$('#b_refresh').addEventListener('click', loadBackups);
$('#b_search').addEventListener('input', renderBackups);
async function loadBackups(){
  const rows = await (await fetch('/api/backups')).json();
  BACKUPS_CACHE = rows;
  // group options
  const groups = new Set();
  rows.forEach(r=>{ const p = r.rel.split('/'); if(p.length>1) groups.add(p[0]); });
  const sel = $('#b_group'); sel.innerHTML = '<option value="">-- all --</option>' + Array.from(groups).sort().map(g=>`<option value="${g}">${g}</option>`).join('');
  renderBackups();
}
$('#b_download_logs').addEventListener('click', ()=>{ window.open('/api/logs/download','_blank'); });
$('#b_export_settings').addEventListener('click', ()=>{ window.open('/api/settings/export','_blank'); });
$('#b_upload').addEventListener('change', async (ev)=>{
  if(!ev.target.files || !ev.target.files[0]) return;
  const fd = new FormData(); fd.append('file', ev.target.files[0]);
  const r = await fetch('/api/backups/upload',{method:'POST', body: fd}); const d = await r.json();
  if(!d.ok){ alert('Upload failed: '+(d.error||'unknown')); return; }
  if(d.rel.ends_with && d.rel.ends_with('.zip')){ /* optional unpack step shown later */ }
  alert('Uploaded to '+d.rel); loadBackups();
});
$('#sys_apt').addEventListener('click', async ()=>{
  if(!confirm('Run apt-get update && upgrade inside the add-on container?')) return;
  const r = await fetch('/api/system/apt_upgrade',{method:'POST'}); const d = await r.json();
  if(!d.ok){ alert('Update failed: '+(d.error||d.step||'unknown')); } else { alert('Update completed.'); }
});
