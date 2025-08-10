
const $=(q)=>document.querySelector(q);
const j=async(u,o={})=>{const r=await fetch(u,Object.assign({headers:{'Content-Type':'application/json'}},o)); const ct=r.headers.get('content-type')||''; return ct.includes('application/json')?await r.json():await r.text();};
const logInto=(id,t)=>{const el=$(id); el.textContent+=(t+'\n'); el.scrollTop=el.scrollHeight;};

// tabs
document.querySelectorAll('nav .tab').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('nav .tab').forEach(x=>x.classList.remove('active')); b.classList.add('active');
  document.querySelectorAll('.tabpane').forEach(p=>p.classList.remove('active')); $('#'+b.dataset.tab).classList.add('active');
  if(b.dataset.tab==='backups') loadBackups();
  if(b.dataset.tab==='mounts') refreshMounts();
  if(b.dataset.tab==='alerts') loadNotify();
  if(b.dataset.tab==='schedule') loadSchedules();
}));

function sshVisible(){ const ssh=$('#b_source_type').value==='ssh'||$('#b_mode').value==='rsync'; document.querySelectorAll('.ssh-only').forEach(x=>x.style.display=ssh?'':'none'); }
$('#b_source_type').addEventListener('change',sshVisible); $('#b_mode').addEventListener('change',sshVisible); sshVisible();

// Picker modal
const Picker={onChoose:null, ctx:{}, open(t){$('#picker_title').textContent=t; $('#picker_modal').classList.remove('hidden');}, close(){ $('#picker_modal').classList.add('hidden'); $('#picker_list').innerHTML=''; $('#picker_sel').textContent=''; $('#picker_breadcrumbs').textContent=''; this.onChoose=null; this.ctx={}; }, setPath(p){ this.ctx.path=p; $('#picker_breadcrumbs').textContent=p; }, setItems(items){ const ul=$('#picker_list'); ul.innerHTML=''; items.forEach(it=>{ const li=document.createElement('li'); li.dataset.name=it.name; li.dataset.dir=it.dir?'1':'0'; li.innerHTML=`<span>${it.dir?'📁':'📄'} ${it.name}</span>${it.dir?'<span class="badge">dir</span>':''}`; li.onclick=()=>{ ul.querySelectorAll('li').forEach(x=>x.classList.remove('sel')); li.classList.add('sel'); $('#picker_sel').textContent=it.name; }; ul.appendChild(li); }); }};
$('#picker_close').onclick=()=>Picker.close();
$('#picker_choose').onclick=()=>{ const sel=$('#picker_list li.sel'); if(!sel){alert('Select an item'); return;} let p=Picker.ctx.path; if(!p.endsWith('/')) p+='/'; p+=sel.dataset.name; if(Picker.onChoose) Picker.onChoose({name:sel.dataset.name,dir:sel.dataset.dir==='1',path:p}); Picker.close(); };

// browsers
async function browseSSH(start='/'){ const body={host:$('#b_host').value,port:22,username:$('#b_user').value,password:$('#b_pass').value,path:start};
  const r=await j('/api/ssh/listdir',{method:'POST',body:JSON.stringify(body)}); if(!r.ok){alert('SSH browse failed'); return;}
  Picker.open('Browse SSH'); Picker.setPath(start); Picker.setItems(r.items);
  Picker.onChoose=async(sel)=>{ if(sel.dir){ const r2=await j('/api/ssh/listdir',{method:'POST',body:JSON.stringify({...body,path:sel.path})}); if(r2.ok){ Picker.open('Browse SSH'); Picker.setPath(sel.path); Picker.setItems(r2.items); Picker.onChoose=Picker.onChoose; } } else { $('#b_src').value=sel.path; } };
}
$('#bw_browse_ssh')?.addEventListener('click',()=>browseSSH($('#b_src').value||'/'));

async function pickLocal(start='/config', target){ const r=await j('/api/local/listdir?path='+encodeURIComponent(start)); if(!r.ok){alert('Local browse failed'); return;}
  Picker.open('Pick local'); Picker.setPath(start); Picker.setItems(r.items);
  Picker.onChoose=async(sel)=>{ if(sel.dir){ const r2=await j('/api/local/listdir?path='+encodeURIComponent(sel.path)); if(r2.ok){ Picker.open('Pick local'); Picker.setPath(sel.path); Picker.setItems(r2.items); Picker.onChoose=Picker.onChoose; } } else { $(target).value=sel.path; } };
}
$('#bw_pick_local').addEventListener('click',()=>pickLocal('/config','#b_src')); $('#bw_pick_dest_local').addEventListener('click',()=>pickLocal('/config','#b_dest_path'));

async function listMounts(){ return await j('/api/mounts'); }
async function ensureMounted(name){ const r=await j('/api/mounts/mount',{method:'POST',body:JSON.stringify({name})}); return r.ok; }
async function browseMount(name, start='/', target='#b_src'){ const ok=await ensureMounted(name); if(!ok){ alert('Mount failed'); return; }
  const r=await j('/api/mounts/listdir',{method:'POST',body:JSON.stringify({name, path:start})}); if(!r.ok){ alert('Mount browse failed'); return; }
  Picker.open('Browse mount: '+name); Picker.setPath(start); Picker.setItems(r.items);
  Picker.onChoose=async(sel)=>{ if(sel.dir){ const r2=await j('/api/mounts/listdir',{method:'POST',body:JSON.stringify({name, path:sel.path})}); if(r2.ok){ Picker.open('Browse mount: '+name); Picker.setPath(sel.path); Picker.setItems(r2.items); Picker.onChoose=Picker.onChoose; } } else { $(target).value=sel.path; } };
}
$('#bw_pick_mount').addEventListener('click', async ()=>{ const r=await listMounts(); const names=r.mounts.map(m=>m.name); if(!names.length){ alert('No mounts saved.'); return; } Picker.open('Pick mount'); Picker.setPath('(mount)'); Picker.setItems(names.map(n=>({name:n,dir:false}))); Picker.onChoose=(sel)=>browseMount(sel.name,'/','#b_src'); });
$('#bw_pick_dest_mount').addEventListener('click', async ()=>{ const r=await listMounts(); const names=r.mounts.map(m=>m.name); if(!names.length){ alert('No mounts saved.'); return; } Picker.open('Pick destination mount'); Picker.setPath('(mount)'); Picker.setItems(names.map(n=>({name:n,dir:false}))); Picker.onChoose=(sel)=>{ $('#b_dest_mount').value=sel.name; browseMount(sel.name,'/','#b_dest_path'); }; });

$('#bw_mkdir_dest').addEventListener('click', async ()=>{ const mode=$('#b_dest_type').value; const base=$('#b_dest_path').value || '/config'; const folder=prompt('New folder name:'); if(!folder) return;
  if(mode==='local'){ const r=await j('/api/local/mkdir',{method:'POST',body:JSON.stringify({path:base,name:folder})}); logInto('#log_backup','mkdir local: '+JSON.stringify(r)); if(r.ok) $('#b_dest_path').value=r.path; }
  else{ const name=$('#b_dest_mount').value.trim(); if(!name){ alert('Set mount name first'); return; } const r=await j('/api/mounts/mkdir',{method:'POST',body:JSON.stringify({name, path:base, folder})}); logInto('#log_backup','mkdir mount: '+JSON.stringify(r)); if(r.ok) $('#b_dest_path').value=r.path.replace(/^.*?:/,''); }
});

$('#bw_estimate').addEventListener('click', async ()=>{ const mode=$('#b_source_type').value; const path=$('#b_src').value||'/'; let body={mode:'local',path}; if(mode==='ssh') body={mode:'ssh',path,host:$('#b_host').value,username:$('#b_user').value,password:$('#b_pass').value}; if(mode==='mount') body={mode:'mount',path,name:$('#b_dest_mount').value||''}; const r=await j('/api/estimate',{method:'POST',body:JSON.stringify(body)}); if(r.ok){ $('#bw_estimate_out').textContent=r.bytes+' bytes'; logInto('#log_backup','estimate: '+JSON.stringify(r)); }});

$('#bw_test_ssh')?.addEventListener('click', async ()=>{ const r=await j('/api/ssh/test',{method:'POST',body:JSON.stringify({host:$('#b_host').value,username:$('#b_user').value,password:$('#b_pass').value})}); alert(r.ok?'SSH OK':'SSH failed'); logInto('#log_backup','ssh test: '+JSON.stringify(r)); });

$('#bw_start').addEventListener('click', async ()=>{
  const payload={ mode:$('#b_mode').value, label:$('#b_label').value||'backup', bwlimit_kbps:parseInt($('#b_bw').value||'0'), dry_run:$('#b_dry').value==='1', profile:$('#b_profile').value.toLowerCase(),
    dest_type:$('#b_dest_type').value, dest_mount_name:$('#b_dest_mount').value, dest_path:$('#b_dest_path').value,
    source_path:$('#b_src').value||'/', host:$('#b_host').value, username:$('#b_user').value, password:$('#b_pass').value, mount_name:$('#b_dest_mount').value };
  const r=await j('/api/backup/start',{method:'POST',body:JSON.stringify(payload)}); logInto('#log_backup','start: '+JSON.stringify(r)); });

$('#bw_cancel').addEventListener('click', async ()=>{ const r=await j('/api/jobs/cancel',{method:'POST'}); logInto('#log_backup','cancel: '+JSON.stringify(r)); });

setInterval(async()=>{ const r=await j('/api/jobs'); if(Array.isArray(r)&&r.length){ const p=Math.max(0,Math.min(100,r[0].progress||0)); $('#bw_progress > div').style.width=p+'%'; } else { $('#bw_progress > div').style.width='0%'; } },1000);

// Backups tab
function fmtBytes(n){ if(!n) return '0'; const u=['B','KB','MB','GB','TB']; let i=0; while(n>=1024&&i<u.length-1){n/=1024;i++;} return n.toFixed(1)+' '+u[i]; }
function fmtWhen(ts){ if(!ts) return ''; return new Date(ts*1000).toLocaleString(); }
async function loadBackups(){ const r=await j('/api/backups'); const tb=$('#bk_table tbody'); tb.innerHTML=''; (r.items||[]).forEach(b=>{ const tr=document.createElement('tr'); const s=b.source||{}; const sdesc=s.type==='ssh'?`${s.user}@${s.host}:${s.path||s.device||''}`: s.type==='mount'?`${s.name}:${s.path}`: s.type==='local'?`${s.path}`:''; tr.innerHTML=`<td>${b.label}</td><td>${fmtWhen(b.when)}</td><td>${fmtBytes(b.size)}</td><td>${b.mode}</td><td>${sdesc}</td>
<td class="row"><button data-id="${b.id}" class="bk_restore_original">Restore (original)</button><button data-id="${b.id}" class="bk_restore_to secondary">Restore to…</button><a class="secondary" href="/api/backups/download-archive?id=${encodeURIComponent(b.id)}">Download</a><button data-id="${b.id}" class="danger bk_delete">Delete</button></td>`; tb.appendChild(tr); });
  tb.querySelectorAll('.bk_restore_original').forEach(btn=>btn.onclick=async()=>{ const id=btn.dataset.id; const pw=prompt('If original is SSH, enter password (leave blank otherwise):',''); const payload={id,original:true}; if(pw) payload.password=pw; const r=await j('/api/restore/start',{method:'POST',body:JSON.stringify(payload)}); logInto('#log_backups','restore original: '+JSON.stringify(r)); });
  tb.querySelectorAll('.bk_restore_to').forEach(btn=>btn.onclick=async()=>{ const id=btn.dataset.id; const mode=confirm('OK: restore to LOCAL. Cancel: restore to MOUNT.')?'local':'mount'; if(mode==='local'){ pickLocal('/config','#b_dest_path'); Picker.onChoose=async(sel)=>{ const r2=await j('/api/restore/start',{method:'POST',body:JSON.stringify({id,original:false,to_mode:'local',to_path:sel.path})}); logInto('#log_backups','restore to local: '+JSON.stringify(r2)); }; } else { const rm=await listMounts(); const names=rm.mounts.map(m=>m.name); Picker.open('Pick mount'); Picker.setPath('(mount)'); Picker.setItems(names.map(n=>({name:n,dir:false}))); Picker.onChoose=(sel)=>{ browseMount(sel.name,'/','#b_dest_path'); Picker.onChoose=async(fsel)=>{ const r2=await j('/api/restore/start',{method:'POST',body:JSON.stringify({id,original:false,to_mode:'mount',mount_name:sel.name,to_path:fsel.path})}); logInto('#log_backups','restore to mount: '+JSON.stringify(r2)); }; }; } });
  tb.querySelectorAll('.bk_delete').forEach(btn=>btn.onclick=async()=>{ if(!confirm('Delete this backup?')) return; const r=await j('/api/backups/delete',{method:'POST',body:JSON.stringify({id:btn.dataset.id})}); logInto('#log_backups','delete: '+JSON.stringify(r)); loadBackups(); });
}

// Mounts tab
async function refreshMounts(){ const r=await j('/api/mounts'); const tb=$('#m_table tbody'); tb.innerHTML=''; r.mounts.forEach(m=>{ const tr=document.createElement('tr'); tr.innerHTML=`<td>${m.name}</td><td>${m.type}</td><td>${m.host||''}</td><td>${m.share||''}</td>
<td>${m.mounted?'<span class="badge ok">mounted</span>':'<span class="badge err">not mounted</span>'}${m.last_error?` <span class="badge err">${m.last_error}</span>`:''}</td><td>${m.mountpoint||''}</td>
<td class="row"><button type="button" class="mini use_dst" data-name="${m.name}">Use as destination</button><button type="button" class="mini use_src" data-name="${m.name}">Use as source</button><button type="button" class="mini mnt" data-name="${m.name}">${m.mounted?'Unmount':'Mount'}</button><button type="button" class="mini danger del" data-name="${m.name}">Delete</button></td>`; 
  tr.onclick=()=>{ $('#m_name').value=m.name; $('#m_type').value=m.type; $('#m_host').value=m.host||''; $('#m_share').value=m.share||''; $('#m_user').value=m.username||''; $('#m_pass').value=m.password||''; $('#m_options').value=m.options||''; $('#m_retry').value=m.auto_retry?'1':'0'; };
  tb.appendChild(tr); });
  tb.querySelectorAll('.use_dst').forEach(b=>b.onclick=async(ev)=>{ ev.stopPropagation(); ev.preventDefault(); const n=b.dataset.name; $('#b_dest_type').value='mount'; $('#b_dest_mount').value=n; browseMount(n,'/','#b_dest_path'); document.querySelector('nav .tab[data-tab="backup"]').click(); });
  tb.querySelectorAll('.use_src').forEach(b=>b.onclick=async(ev)=>{ ev.stopPropagation(); ev.preventDefault(); const n=b.dataset.name; $('#b_source_type').value='mount'; browseMount(n,'/','#b_src'); document.querySelector('nav .tab[data-tab="backup"]').click(); });
  tb.querySelectorAll('.mnt').forEach(b=>b.onclick=async(ev)=>{ ev.stopPropagation(); ev.preventDefault(); const n=b.dataset.name; if(b.textContent==='Unmount'){ await j('/api/mounts/unmount',{method:'POST',body:JSON.stringify({name:n})}); } else { await j('/api/mounts/mount',{method:'POST',body:JSON.stringify({name:n})}); } refreshMounts(); });
  tb.querySelectorAll('.del').forEach(b=>b.onclick=async(ev)=>{ ev.stopPropagation(); ev.preventDefault(); if(!confirm('Delete this mount?')) return; await j('/api/mounts/unmount',{method:'POST',body:JSON.stringify({name:b.dataset.name})}); const r=await j('/api/mounts/delete',{method:'POST',body:JSON.stringify({name:b.dataset.name})}); logInto('#log_mounts','delete: '+JSON.stringify(r)); if(!r.ok && r.error){ alert('Delete failed: '+r.error);} refreshMounts(); });
}
$('#m_refresh').addEventListener('click',refreshMounts); refreshMounts(); setInterval(refreshMounts,5000);
$('#m_save').addEventListener('click', async ()=>{ const body={name:$('#m_name').value.trim(), type:$('#m_type').value, host:$('#m_host').value.trim(), share:$('#m_share').value.trim(), username:$('#m_user').value, password:$('#m_pass').value, options:$('#m_options').value, auto_retry:$('#m_retry').value}; const r=await j('/api/mounts/save',{method:'POST',body:JSON.stringify(body)}); logInto('#log_mounts','save: '+JSON.stringify(r)); refreshMounts(); });
$('#m_mount').addEventListener('click', async ()=>{ const r=await j('/api/mounts/mount',{method:'POST',body:JSON.stringify({name:$('#m_name').value})}); logInto('#log_mounts','mount: '+JSON.stringify(r)); refreshMounts(); });
$('#m_unmount').addEventListener('click', async ()=>{ const r=await j('/api/mounts/unmount',{method:'POST',body:JSON.stringify({name:$('#m_name').value})}); logInto('#log_mounts','unmount: '+JSON.stringify(r)); refreshMounts(); });
$('#m_test').addEventListener('click', async ()=>{ const body={type:$('#m_type').value, host:$('#m_host').value, username:$('#m_user').value, password:$('#m_pass').value}; const r=await j('/api/mounts/test',{method:'POST',body:JSON.stringify(body)}); logInto('#log_mounts','test: '+JSON.stringify(r)); alert(r.ok?'Server OK':'Server connection failed'); });
$('#m_pick_share').addEventListener('click', async ()=>{ const body={type:$('#m_type').value, host:$('#m_host').value.trim(), username:$('#m_user').value, password:$('#m_pass').value}; const r=await j('/api/mounts/test',{method:'POST',body:JSON.stringify(body)}); const items=(r.shares||r.exports||[]).map(x=>({name:x,dir:false})); if(!items.length){ alert('No shares/exports found'); return; } Picker.open('Pick share/export'); Picker.setPath(body.host); Picker.setItems(items); Picker.onChoose=async(sel)=>{ await j('/api/mounts/save',{method:'POST',body:JSON.stringify({name:$('#m_name').value.trim()||sel.name, type:$('#m_type').value, host:$('#m_host').value.trim(), share:sel.name, username:$('#m_user').value, password:$('#m_pass').value, options:$('#m_options').value, auto_retry:$('#m_retry').value})}); if(!$('#m_name').value.trim()) $('#m_name').value=sel.name; await j('/api/mounts/mount',{method:'POST',body:JSON.stringify({name:$('#m_name').value})}); browseMount($('#m_name').value,'/','#b_dest_path'); $('#b_dest_type').value='mount'; $('#b_dest_mount').value=$('#m_name').value; document.querySelector('nav .tab[data-tab="backup"]').click(); }; });
$('#m_browse').addEventListener('click', async ()=>{ const name=$('#m_name').value.trim(); if(!name){ alert('Enter Name, Save, then Mount first.'); return; } browseMount(name,'/'); });

// Alerts tab
async function loadNotify(){ const n=await j('/api/notify/get'); $('#n_enabled').value=n.enabled?'1':'0'; $('#n_url').value=n.url||''; $('#n_token').value=n.token||''; $('#n_inc_date').checked=!!(n.include&&n.include.date); $('#n_inc_name').checked=!!(n.include&&n.include.name); $('#n_inc_size').checked=!!(n.include&&n.include.size); $('#n_inc_dur').checked=!!(n.include&&n.include.duration); $('#n_on_ok').checked=!!n.on_success; $('#n_on_fail').checked=!!n.on_failure; }
$('#n_save').addEventListener('click', async ()=>{ const body={enabled:$('#n_enabled').value==='1', url:$('#n_url').value.trim(), token:$('#n_token').value.trim(), include:{date:$('#n_inc_date').checked,time:$('#n_inc_date').checked,name:$('#n_inc_name').checked,size:$('#n_inc_size').checked,duration:$('#n_inc_dur').checked}, on_success:$('#n_on_ok').checked, on_failure:$('#n_on_fail').checked}; const r=await j('/api/notify/save',{method:'POST',body:JSON.stringify(body)}); logInto('#log_alerts','save: '+JSON.stringify(r)); });
$('#n_test').addEventListener('click', async ()=>{ const r=await j('/api/notify/test',{method:'POST'}); logInto('#log_alerts','test: '+JSON.stringify(r)); });

// Schedule tab
function currentWizardTemplate(){ return { mode:$('#b_mode').value, label:$('#b_label').value||'backup', bwlimit_kbps:parseInt($('#b_bw').value||'0'), dry_run:$('#b_dry').value==='1', profile:$('#b_profile').value.toLowerCase(), dest_type:$('#b_dest_type').value, dest_mount_name:$('#b_dest_mount').value, dest_path:$('#b_dest_path').value, source_path:$('#b_src').value||'/', host:$('#b_host').value, username:$('#b_user').value, password:$('#b_pass').value, mount_name:$('#b_dest_mount').value }; }
$('#sch_use_from_wizard').addEventListener('click', ()=>{ const tpl=currentWizardTemplate(); $('#sch_tpl_preview').textContent=JSON.stringify(tpl,null,2); });
async function loadSchedules(){ const r=await j('/api/schedules'); const tb=$('#sch_table tbody'); tb.innerHTML=''; (r.items||[]).forEach(s=>{ const rule=s.rule||{}; const txt=rule.type+' '+(rule.time||'')+' '+(rule.dow||rule.dom||''); const tr=document.createElement('tr'); const when=new Date((s.next_run||0)*1000).toLocaleString(); tr.innerHTML=`<td>${s.id}</td><td>${s.enabled?'yes':'no'}</td><td>${when}</td><td>${txt}</td><td class="row"><button class="secondary toggle" data-id="${s.id}">${s.enabled?'Disable':'Enable'}</button><button class="danger del" data-id="${s.id}">Delete</button></td>`; tb.appendChild(tr); }); tb.querySelectorAll('.toggle').forEach(b=>b.onclick=async()=>{ const r=await j('/api/schedules'); const s=(r.items||[]).find(x=>x.id==b.dataset.id); if(!s) return; s.enabled=!s.enabled; const r2=await j('/api/schedules/save',{method:'POST',body:JSON.stringify(s)}); loadSchedules(); }); tb.querySelectorAll('.del').forEach(b=>b.onclick=async(ev)=>{ ev.stopPropagation(); ev.preventDefault(); await j('/api/schedules/delete',{method:'POST',body:JSON.stringify({id:parseInt(b.dataset.id)})}); loadSchedules(); }); }
$('#sch_save').addEventListener('click', async ()=>{ const rule={type:$('#sch_type').value, time:$('#sch_time').value}; const days=$('#sch_days').value.trim(); if(rule.type==='weekly'&&days) rule.dow=days.split(',').map(x=>parseInt(x)); if(rule.type==='monthly'&&days) rule.dom=days.split(',').map(x=>parseInt(x)); const tpl=JSON.parse($('#sch_tpl_preview').textContent||'{}'); if(!tpl.mode){ alert('Click "Use wizard values" first'); return; } const body={enabled:true, rule, template:tpl}; const r=await j('/api/schedules/save',{method:'POST',body:JSON.stringify(body)}); logInto('#log_schedule','save: '+JSON.stringify(r)); loadSchedules(); });

// Test SFTP (added)
document.getElementById('bw_test_ssh')?.addEventListener('click', async (e)=>{
  const host = val('#b_host'), user = val('#b_user'), pass = val('#b_pass');
  const port = num('#b_port')||22;
  const body = {host, port, username:user, password:pass};
  try{
    const r = await post('/api/ssh/test_sftp', body);
    logInto('#log_backup', 'sftp_test: '+JSON.stringify(r));
    alert(r.ok ? 'SFTP OK' : ('SFTP failed: '+(r.error||'unknown')));
  }catch(err){
    logInto('#log_backup','sftp_test error: '+err);
    alert('SFTP test error: '+err);
  }
});

async function openSshPicker(startPath){
  const host = val('#b_host'), user = val('#b_user'), pass = val('#b_pass');
  const port = num('#b_port')||22;
  const modal = Picker.open('Browse SSH', [], {extraButtons:[{label:'Go to ~', id:'goHome'}]});
  async function load(p){
    const r = await post('/api/ssh/listdir', {host, port, username:user, password:pass, path:p});
    logInto('#log_backup', 'ssh_browse: '+JSON.stringify(r));
    if(!r.ok){
      Picker.fill([{name:r.error||'Failed', dir:false, size:0, disabled:true}]);
      return;
    }
    Picker.fill(r.items||[]);
  }
  modal.on('extra','goHome', async ()=>{ await load('~'); });
  modal.on('choose', (item)=>{
    if(item && item.path){
      setVal('#b_src', item.path);
    }
  });
  await load(startPath||'/');
}
document.getElementById('bw_browse_ssh')?.addEventListener('click', (e)=>{ e.preventDefault(); e.stopPropagation(); openSshPicker('/'); });

async function openSharePicker(){
  const host = val('#m_host'), user = val('#m_user'), pass = val('#m_pass');
  const type = val('#m_type'); if(type!=='smb') return;
  const r = await post('/api/mounts/listshares', {host, username:user, password:pass, type});
  logInto('#log_dest', 'shares: '+JSON.stringify(r));
  if(!r.ok){ alert(r.error||'Failed to list shares'); return; }
  const modal = Picker.open('Pick share/export', r.items||[]);
  modal.on('choose', async (item)=>{
    if(!item || !item.name) return;
    setVal('#m_share', item.name);
    // stay on Destinations
    const name = val('#m_name')||item.name;
    const root = await post('/api/mounts/listdir', {name, path:'/'});
    logInto('#log_dest', 'share_browse_root: '+JSON.stringify(root));
  });
}
document.getElementById('m_pick_share')?.addEventListener('click', (e)=>{ e.preventDefault(); e.stopPropagation(); openSharePicker(); });
