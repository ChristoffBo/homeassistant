
const $ = (q)=>document.querySelector(q);
const j = async (url, opt={})=>{
  const res = await fetch(url, Object.assign({headers:{'Content-Type':'application/json'}}, opt));
  const ct = res.headers.get('content-type')||'';
  if(ct.includes('application/json')) return await res.json();
  return await res.text();
};
const logInto = (id, t)=>{const el=$(id); el.textContent += (t+'\n'); el.scrollTop=el.scrollHeight;};

// tabs
document.querySelectorAll('nav .tab').forEach(b=>{
  b.addEventListener('click', ()=>{
    document.querySelectorAll('nav .tab').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
    document.querySelectorAll('.tabpane').forEach(p=>p.classList.remove('active'));
    $('#'+b.dataset.tab).classList.add('active');
  });
});

// backup wizard visibility
function syncSshVisibility(){
  const ssh = $('#b_source_type').value === 'ssh' || $('#b_mode').value === 'rsync';
  document.querySelectorAll('.ssh-only').forEach(x=>x.style.display = ssh ? '' : 'none');
}
$('#b_source_type').addEventListener('change', syncSshVisibility);
$('#b_mode').addEventListener('change', syncSshVisibility);
syncSshVisibility();

// ---- Picker modal ----
const Picker = {
  onChoose:null, ctx:{},
  open(title){ $('#picker_title').textContent=title; $('#picker_modal').classList.remove('hidden'); },
  close(){ $('#picker_modal').classList.add('hidden'); $('#picker_list').innerHTML=''; $('#picker_sel').textContent=''; $('#picker_breadcrumbs').textContent=''; this.onChoose=null; this.ctx={}; },
  setPath(p){ this.ctx.path=p; $('#picker_breadcrumbs').textContent=p; },
  setItems(items){ const ul=$('#picker_list'); ul.innerHTML=''; items.forEach(it=>{ const li=document.createElement('li'); li.dataset.name=it.name; li.dataset.dir=it.dir?'1':'0'; li.innerHTML=`<span>${it.dir?'📁':'📄'} ${it.name}</span>${it.dir?'<span class="badge">dir</span>':''}`; li.onclick=()=>{ ul.querySelectorAll('li').forEach(x=>x.classList.remove('sel')); li.classList.add('sel'); $('#picker_sel').textContent=it.name; }; ul.appendChild(li); }); }
};
$('#picker_close').onclick=()=>Picker.close();
$('#picker_choose').onclick=()=>{ const sel=$('#picker_list li.sel'); if(!sel){alert('Select an item'); return;} let p=Picker.ctx.path; if(!p.endsWith('/')) p+='/'; p+= sel.dataset.name; if(Picker.onChoose) Picker.onChoose({name:sel.dataset.name, dir: sel.dataset.dir==='1', path:p}); Picker.close(); };

// browse helpers
async function browseSSH(start='/'){
  const body={host:$('#b_host').value,port:22,username:$('#b_user').value,password:$('#b_pass').value,path:start};
  const r=await j('/api/ssh/listdir',{method:'POST',body:JSON.stringify(body)});
  if(!r.ok){alert('SSH browse failed');return;}
  Picker.open('Browse SSH'); Picker.setPath(start); Picker.setItems(r.items);
  Picker.onChoose=async (sel)=>{
    if(sel.dir){ const r2=await j('/api/ssh/listdir',{method:'POST',body:JSON.stringify({...body,path:sel.path})}); if(r2.ok){ Picker.open('Browse SSH'); Picker.setPath(sel.path); Picker.setItems(r2.items); Picker.onChoose=Picker.onChoose; } }
    else { $('#b_src').value=sel.path; }
  };
}
$('#bw_browse_ssh')?.addEventListener('click', ()=>browseSSH($('#b_src').value||'/'));

async function pickLocal(start='/config', setTargetInput){
  const r=await j('/api/local/listdir?path='+encodeURIComponent(start));
  if(!r.ok){alert('Local browse failed');return;}
  Picker.open('Pick local'); Picker.setPath(start); Picker.setItems(r.items);
  Picker.onChoose=async (sel)=>{
    if(sel.dir){ const r2=await j('/api/local/listdir?path='+encodeURIComponent(sel.path)); if(r2.ok){ Picker.open('Pick local'); Picker.setPath(sel.path); Picker.setItems(r2.items); Picker.onChoose=Picker.onChoose; } }
    else { $(setTargetInput).value = sel.path; }
  };
}
$('#bw_pick_local').addEventListener('click', ()=>pickLocal('/config','#b_src'));
$('#bw_pick_dest_local').addEventListener('click', ()=>pickLocal('/config','#b_dest_path'));

async function listMounts(){ return await j('/api/mounts'); }
async function ensureMounted(name){
  const r = await listMounts();
  const m = r.mounts.find(x=>x.name===name);
  if(!m){ throw new Error('Mount not found'); }
  if(m.mounted) return true;
  const r2 = await j('/api/mounts/mount',{method:'POST',body:JSON.stringify({name})});
  return r2.ok;
}
async function browseMount(name, start='/', targetInput='#b_src'){
  try{ await ensureMounted(name); }catch(e){ alert('Mount failed'); return; }
  const r=await j('/api/mounts/listdir',{method:'POST',body:JSON.stringify({name, path:start})});
  if(!r.ok){ alert('Mount browse failed'); return; }
  Picker.open('Browse mount: '+name); Picker.setPath(start); Picker.setItems(r.items);
  Picker.onChoose=async (sel)=>{
    if(sel.dir){ const r2=await j('/api/mounts/listdir',{method:'POST',body:JSON.stringify({name, path:sel.path})}); if(r2.ok){ Picker.open('Browse mount: '+name); Picker.setPath(sel.path); Picker.setItems(r2.items); Picker.onChoose=Picker.onChoose; } }
    else { $(targetInput).value = sel.path; }
  };
}
$('#bw_pick_mount').addEventListener('click', async ()=>{
  const r=await listMounts(); const names=r.mounts.map(m=>m.name);
  if(!names.length){ alert('No mounts saved. Create one first.'); return; }
  Picker.open('Pick mount'); Picker.setPath('(mount)'); Picker.setItems(names.map(n=>({name:n,dir:false})));
  Picker.onChoose=(sel)=>browseMount(sel.name,'/','#b_src');
});
$('#bw_pick_dest_mount').addEventListener('click', async ()=>{
  const r=await listMounts(); const names=r.mounts.map(m=>m.name);
  if(!names.length){ alert('No mounts saved. Create one first.'); return; }
  Picker.open('Pick destination mount'); Picker.setPath('(mount)'); Picker.setItems(names.map(n=>({name:n,dir:false})));
  Picker.onChoose=(sel)=>{ $('#b_dest_mount').value=sel.name; browseMount(sel.name,'/','#b_dest_path'); };
});

// mkdir destination
$('#bw_mkdir_dest').addEventListener('click', async ()=>{
  const mode=$('#b_dest_type').value;
  const base=$('#b_dest_path').value || '/config';
  const folder=prompt('New folder name:');
  if(!folder) return;
  if(mode==='local'){
    const r=await j('/api/local/mkdir',{method:'POST',body:JSON.stringify({path:base,name:folder})});
    logInto('#log_backup','mkdir local: '+JSON.stringify(r));
    if(r.ok) $('#b_dest_path').value = r.path;
  }else{
    const name=$('#b_dest_mount').value.trim();
    if(!name){ alert('Set mount name first'); return; }
    const r=await j('/api/mounts/mkdir',{method:'POST',body:JSON.stringify({name, path:base, folder})});
    logInto('#log_backup','mkdir mount: '+JSON.stringify(r));
    if(r.ok) $('#b_dest_path').value = r.path.replace(/^.*?:/,''); // keep path
  }
});

// estimate
$('#bw_estimate').addEventListener('click', async ()=>{
  const mode = $('#b_source_type').value;
  const path = $('#b_src').value || '/';
  let body = {mode:'local', path};
  if(mode==='ssh') body = {mode:'ssh', path, host:$('#b_host').value, username:$('#b_user').value, password:$('#b_pass').value};
  if(mode==='mount'){ body = {mode:'mount', path, name:$('#b_dest_mount').value || ''}; }
  const r = await j('/api/estimate',{method:'POST',body:JSON.stringify(body)});
  if(r.ok){ $('#bw_estimate_out').textContent = r.bytes+' bytes'; logInto('#log_backup', 'estimate: '+JSON.stringify(r)); }
});

// test ssh
$('#bw_test_ssh')?.addEventListener('click', async ()=>{
  const body = {host:$('#b_host').value, port:22, username:$('#b_user').value, password:$('#b_pass').value};
  const r = await j('/api/ssh/test',{method:'POST',body:JSON.stringify(body)});
  logInto('#log_backup', 'ssh test: '+JSON.stringify(r));
  alert(r.ok ? 'SSH OK' : 'SSH failed');
});

// start backup
$('#bw_start').addEventListener('click', async ()=>{
  const modeSel = $('#b_mode').value;
  const src = $('#b_src').value || '/';
  const payload = {
    mode: modeSel,
    label: $('#b_label').value || 'backup',
    bwlimit_kbps: parseInt($('#b_bw').value||'0'),
    dry_run: $('#b_dry').value==='1',
    profile: $('#b_profile').value.toLowerCase(),
    dest_type: $('#b_dest_type').value,
    dest_mount_name: $('#b_dest_mount').value,
    dest_path: $('#b_dest_path').value,
    source_path: src,
    host: $('#b_host').value, username: $('#b_user').value, password: $('#b_pass').value,
    mount_name: $('#b_dest_mount').value
  };
  const r = await j('/api/backup/start',{method:'POST',body:JSON.stringify(payload)});
  logInto('#log_backup','start: '+JSON.stringify(r));
  if($('#backups').classList.contains('active')) loadBackups();
});

$('#bw_cancel').addEventListener('click', async ()=>{
  const r = await j('/api/jobs/cancel',{method:'POST'});
  logInto('#log_backup','cancel: '+JSON.stringify(r));
});

// jobs polling
setInterval(async ()=>{
  const r = await j('/api/jobs');
  if(Array.isArray(r) && r.length){
    const j0 = r[0];
    const p = Math.max(0, Math.min(100, j0.progress || 0));
    $('#bw_progress > div').style.width = p+'%';
  }else{
    $('#bw_progress > div').style.width = '0%';
  }
}, 1000);

// ---- Backups tab ----
function fmtBytes(n){ if(!n) return '0'; const u=['B','KB','MB','GB','TB']; let i=0; while(n>=1024&&i<u.length-1){n/=1024;i++;} return n.toFixed(1)+' '+u[i]; }
function fmtWhen(ts){ if(!ts) return ''; const d=new Date(ts*1000); return d.toLocaleString(); }
async function loadBackups(){
  const r=await j('/api/backups');
  const tb=$('#bk_table tbody'); tb.innerHTML='';
  (r.items||[]).forEach(b=>{
    const tr=document.createElement('tr');
    const src=b.source||{};
    const sdesc = src.type==='ssh'?`${src.user}@${src.host}:${src.path||src.device||''}`: src.type==='mount'?`${src.name}:${src.path}`: src.type==='local'?`${src.path}`:'';
    tr.innerHTML = `<td>${b.label}</td><td>${fmtWhen(b.when)}</td><td>${fmtBytes(b.size)}</td><td>${b.mode}</td><td>${sdesc}</td>
      <td class="row">
        <button data-id="${b.id}" class="bk_restore_original">Restore (original)</button>
        <button data-id="${b.id}" class="bk_restore_to secondary">Restore to…</button>
        <a class="secondary" href="/api/backups/download-archive?id=${encodeURIComponent(b.id)}">Download (.tar.gz)</a>
      </td>`;
    tb.appendChild(tr);
  });
  tb.querySelectorAll('.bk_restore_original').forEach(btn=>{
    btn.onclick = async ()=>{
      const id=btn.dataset.id; const pw = prompt('If original is SSH, enter password (leave blank for local/mount):','');
      const payload={id, original:true}; if(pw) payload.password=pw;
      const r=await j('/api/restore/start',{method:'POST',body:JSON.stringify(payload)});
      logInto('#log_backups','restore original: '+JSON.stringify(r));
    };
  });
  tb.querySelectorAll('.bk_restore_to').forEach(btn=>{
    btn.onclick = async ()=>{
      const id=btn.dataset.id;
      // choose destination (local or mount) and path
      const mode = confirm('OK = restore to LOCAL folder (pick next). Cancel = restore to MOUNT.') ? 'local' : 'mount';
      if(mode==='local'){
        pickLocal('/config','#b_dest_path'); // reuse picker
        Picker.onChoose = async (sel)=>{
          if(sel.dir){
            const r2=await j('/api/local/listdir?path='+encodeURIComponent(sel.path)); if(r2.ok){ Picker.open('Pick local'); Picker.setPath(sel.path); Picker.setItems(r2.items); Picker.onChoose=Picker.onChoose; }
          }else{
            const payload={id, original:false, to_mode:'local', to_path: sel.path};
            const r=await j('/api/restore/start',{method:'POST',body:JSON.stringify(payload)});
            logInto('#log_backups','restore to local: '+JSON.stringify(r));
          }
        };
      }else{
        const r=await listMounts(); const names=r.mounts.map(m=>m.name);
        if(!names.length){ alert('No mounts saved.'); return; }
        Picker.open('Pick mount'); Picker.setPath('(mount)'); Picker.setItems(names.map(n=>({name:n,dir:false})));
        Picker.onChoose=(sel)=>{
          browseMount(sel.name,'/','#b_dest_path');
          Picker.onChoose=async (pick)=>{
            if(pick.dir){
              const r2=await j('/api/mounts/listdir',{method:'POST',body:JSON.stringify({name:sel.name, path:pick.path})});
              if(r2.ok){ Picker.open('Browse mount: '+sel.name); Picker.setPath(pick.path); Picker.setItems(r2.items); Picker.onChoose=Picker.onChoose; }
            }else{
              const payload={id, original:false, to_mode:'mount', mount_name: sel.name, to_path: pick.path};
              const r=await j('/api/restore/start',{method:'POST',body:JSON.stringify(payload)});
              logInto('#log_backups','restore to mount: '+JSON.stringify(r));
            }
          };
        };
      }
    };
  });
}
document.querySelector('button[data-tab="backups"]').addEventListener('click', loadBackups);

// ---- Mounts tab ----
async function refreshMounts(){
  const r = await j('/api/mounts');
  const tb = $('#m_table tbody'); tb.innerHTML='';
  r.mounts.forEach(m=>{
    const tr=document.createElement('tr');
    tr.innerHTML = `<td>${m.name}</td><td>${m.type}</td><td>${m.host||''}</td><td>${m.share||''}</td>
      <td>${m.mounted?'<span class="badge ok">mounted</span>':'<span class="badge err">not mounted</span>'}${m.last_error?` <span class="badge err">${m.last_error}</span>`:''}</td>
      <td>${m.mountpoint||''}</td>`;
    tr.onclick=()=>{ $('#m_name').value=m.name; $('#m_type').value=m.type; $('#m_host').value=m.host||''; $('#m_share').value=m.share||''; $('#m_user').value=m.username||''; $('#m_pass').value=m.password||''; $('#m_options').value=m.options||''; $('#m_retry').value=m.auto_retry?'1':'0'; };
    tb.appendChild(tr);
  });
}
$('#m_refresh').addEventListener('click', refreshMounts);
refreshMounts();
setInterval(refreshMounts, 5000);

$('#m_save').addEventListener('click', async ()=>{
  const body={name:$('#m_name').value.trim(), type:$('#m_type').value, host:$('#m_host').value.trim(), share:$('#m_share').value.trim(),
    username:$('#m_user').value, password:$('#m_pass').value, options:$('#m_options').value, auto_retry:$('#m_retry').value};
  const r=await j('/api/mounts/save',{method:'POST',body:JSON.stringify(body)});
  logInto('#log_mounts','save: '+JSON.stringify(r)); refreshMounts();
});
$('#m_mount').addEventListener('click', async ()=>{ const r=await j('/api/mounts/mount',{method:'POST',body:JSON.stringify({name:$('#m_name').value})}); logInto('#log_mounts','mount: '+JSON.stringify(r)); refreshMounts(); });
$('#m_unmount').addEventListener('click', async ()=>{ const r=await j('/api/mounts/unmount',{method:'POST',body:JSON.stringify({name:$('#m_name').value})}); logInto('#log_mounts','unmount: '+JSON.stringify(r)); refreshMounts(); });
$('#m_test').addEventListener('click', async ()=>{
  const body={type:$('#m_type').value, host:$('#m_host').value, username:$('#m_user').value, password:$('#m_pass').value};
  const r=await j('/api/mounts/test',{method:'POST',body:JSON.stringify(body)});
  logInto('#log_mounts','test: '+JSON.stringify(r));
  alert(r.ok ? 'Server OK' : 'Server connection failed (see log)');
});
$('#m_pick_share').addEventListener('click', async ()=>{
  const body={type:$('#m_type').value, host:$('#m_host').value.trim(), username:$('#m_user').value, password:$('#m_pass').value};
  const r=await j('/api/mounts/test',{method:'POST',body:JSON.stringify(body)});
  const items=(r.shares||r.exports||[]).map(x=>({name:x, dir:false}));
  if(!items.length){ alert('No shares/exports found'); return; }
  Picker.open('Pick share/export'); Picker.setPath(body.host); Picker.setItems(items);
  Picker.onChoose=(sel)=>{ $('#m_share').value=sel.name; };
});
$('#m_browse').addEventListener('click', async ()=>{
  const name=$('#m_name').value.trim(); if(!name){ alert('Enter Name, Save, then Mount first.'); return; }
  browseMount(name,'/');
});

// health
async function refreshHealth(){
  const r = await j('/api/health');
  $('#health_json').textContent = JSON.stringify(r, null, 2);
}
refreshHealth();
setInterval(refreshHealth, 8000);
