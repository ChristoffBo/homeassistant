(() => {
  'use strict';
  const API_BASE = './api';
  const $ = (q, ctx=document) => ctx.querySelector(q);
  const $$ = (q, ctx=document) => Array.from(ctx.querySelectorAll(q));
  const fmt = (d)=> new Date(d).toLocaleString();

  // Feature detection
  const caps = { browseHosts:false, browseShares:false, shares:true, dropbox:false };
  function setCapNote(){ const el=$('#capNote'); const ok=[]; if(caps.shares) ok.push('Shares'); if(caps.browseHosts) ok.push('Host Picker'); if(caps.browseShares) ok.push('Share Picker'); el.textContent = ok.length? 'Features: '+ok.join(', ') : ''; }
  function setApiStatus(ok){ const el=$('#apiStatus'); el.classList.toggle('online', !!ok); el.classList.toggle('offline', !ok); }

  async function tryJSON(path, opts={}){
    try{
      const res = await fetch(`${API_BASE}${path}`, {headers:{'Content-Type':'application/json'}, ...opts});
      if(!res.ok) throw new Error(`${res.status}`);
      setApiStatus(true);
      return await res.json().catch(()=>({}));
    }catch(e){ setApiStatus(false); throw e; }
  }

  const state = { hosts:[], backups:[], jobs:[], shares:[] };

  function table(container, cols, rows){
    const tpl = $('#tpl-table').content.cloneNode(true);
    const thead = tpl.querySelector('thead'); const tbody = tpl.querySelector('tbody');
    const tr = document.createElement('tr'); cols.forEach(c=>{ const th=document.createElement('th'); th.textContent=c.label; tr.appendChild(th); }); thead.appendChild(tr);
    rows.forEach(r=>{ const trb=document.createElement('tr'); cols.forEach(c=>{ const td=document.createElement('td'); const v=typeof c.value==='function'?c.value(r):r[c.value]; if(v instanceof Node) td.appendChild(v); else td.textContent=v??''; trb.appendChild(td); }); tbody.appendChild(trb);});
    container.innerHTML=''; container.appendChild(tpl);
  }
  function fillSelect(sel, items, {value='value', label='label', empty='-- select --'}={}){
    sel.innerHTML=''; const o0=document.createElement('option'); o0.value=''; o0.textContent=empty; sel.appendChild(o0);
    for(const it of items){ const o=document.createElement('option'); o.value=it[value]; o.textContent=it[label]; sel.appendChild(o); }
  }

  async function detect(){
    try{
      const c = await tryJSON('/capabilities');
      caps.browseHosts = !!c?.browse_hosts;
      caps.browseShares = !!c?.browse_shares;
      caps.shares = c?.shares !== false;
      caps.dropbox = !!c?.dropbox;
    }catch{}
    setCapNote();
    $('#bkBrowseSrc').classList.toggle('hidden', !caps.browseHosts);
    $('#rsBrowseTarget').classList.toggle('hidden', !caps.browseHosts);
    $('#scBrowseSrc').classList.toggle('hidden', !caps.browseHosts);
    $('#bkShareBrowse').classList.toggle('hidden', !caps.browseShares);
    $('#scShareBrowse').classList.toggle('hidden', !caps.browseShares);
    $('#bkPickDropbox').classList.toggle('hidden', !caps.dropbox);
    $('#scPickDropbox').classList.toggle('hidden', !caps.dropbox);
  }

  async function loadHosts(){ const d=await tryJSON('/hosts'); state.hosts=d.hosts||[];
    const opts = state.hosts.map(h=>({value:h.id||h.address, label:`${h.label||h.address} (${h.user||'user'}@${h.address})`}));
    [$('#bkSrcHost'), $('#rsTargetHost'), $('#scSrcHost')].forEach(sel=> fillSelect(sel, opts));
    renderHosts(); }
  async function loadBackups(){ const d=await tryJSON('/backups'); state.backups=d.backups||[]; renderBackups();
    fillSelect($('#rsBackupSelect'), state.backups.map(b=>({value:b.id, label:`${b.name} • ${b.size||''} • ${b.created?fmt(b.created):''}`}))); }
  async function loadJobs(){ const d=await tryJSON('/scheduler/jobs'); state.jobs=d.jobs||[]; renderJobs(); }
  async function loadShares(){ if(!caps.shares) return; const d=await tryJSON('/shares'); state.shares=d.shares||[]; renderShares();
    fillSelect($('#bkShare'), state.shares.map(s=>({value:s.id, label:`${s.name} (${s.type})`})));
    fillSelect($('#scShare'), state.shares.map(s=>({value:s.id, label:`${s.name} (${s.type})`})));
  }

  function renderHosts(){
    const rows = state.hosts.map(h=>({ label:h.label||'', addr:h.address, user:h.user||'root', path:h.default_path||'',
      actions:(()=>{ const w=document.createElement('div');
        const e=document.createElement('button'); e.textContent='Edit'; e.className='btn ghost'; e.onclick=()=>{ $('#hLabel').value=h.label||''; $('#hAddr').value=h.address||''; $('#hUser').value=h.user||'root'; $('#hPath').value=h.default_path||''; };
        const d=document.createElement('button'); d.textContent='Delete'; d.className='btn ghost'; d.onclick=async()=>{ await tryJSON('/hosts',{method:'DELETE', body:JSON.stringify({address:h.address})}); await loadHosts(); };
        w.appendChild(e); w.appendChild(d); return w; })()
    }));
    table($('#hostsTable'),[{label:'Label',value:'label'},{label:'Address',value:'addr'},{label:'User',value:'user'},{label:'Default path',value:'path'},{label:'',value:'actions'}], rows);
  }
  function renderBackups(){
    const rows = state.backups.map(b=>({ name:b.name||b.id, type:b.type, size:b.size||'', created:b.created?fmt(b.created):'', location:b.location||'',
      actions:(()=>{ const a=document.createElement('button'); a.textContent='Restore…'; a.className='btn'; a.onclick=()=>{ $('#rsBackupSelect').value=b.id; $$('[data-tab="restore"]')[0].click(); }; return a; })()
    }));
    table($('#backupsTable'),[{label:'Name',value:'name'},{label:'Type',value:(r)=> r.type==='dd'?'Full image':'Folder/Files'},{label:'Size',value:'size'},{label:'Created',value:'created'},{label:'Stored at',value:'location'},{label:'',value:'actions'}], rows);
  }
  function renderJobs(){
    const rows = state.jobs.map(j=>({ name:j.name, src:`${j.source?.host_label||j.source?.host} • ${j.source?.path}`, dest:j.destination?.type==='dropbox'?`Dropbox ${j.destination?.folder}`: (j.destination?.type==='share'?`${j.destination?.share_name||j.destination?.share_id}${j.destination?.subpath||''}`: j.destination?.path), schedule:j.cron||j.human||'',
      actions:(()=>{ const w=document.createElement('div'); const run=document.createElement('button'); run.textContent='Run now'; run.className='btn'; run.onclick=async()=>{ await tryJSON('/scheduler/run',{method:'POST', body:JSON.stringify({name:j.name})}); };
        const del=document.createElement('button'); del.textContent='Delete'; del.className='btn ghost'; del.onclick=async()=>{ await tryJSON('/scheduler/jobs',{method:'DELETE', body:JSON.stringify({name:j.name})}); await loadJobs(); };
        w.appendChild(run); w.appendChild(del); return w; })()
    }));
    table($('#jobsTable'),[{label:'Name',value:'name'},{label:'Source',value:'src'},{label:'Destination',value:'dest'},{label:'Schedule',value:'schedule'},{label:'',value:'actions'}], rows);
  }
  function renderShares(){
    const rows = state.shares.map(s=>({ name:s.name, type:(s.type||'').toUpperCase(), mount:s.mount_point||'', status:(s.connected? 'Connected':'Disconnected'),
      actions:(()=>{ const w=document.createElement('div');
        const c=document.createElement('button'); c.textContent = s.connected?'Disconnect':'Connect'; c.className='btn'; c.onclick=async()=>{ await tryJSON(`/shares/${s.connected?'disconnect':'connect'}`, {method:'POST', body:JSON.stringify({id:s.id})}); await loadShares(); };
        const e=document.createElement('button'); e.textContent='Edit'; e.className='btn ghost'; e.onclick=()=>{ $('#shName').value=s.name; $('#shType').value=s.type; $('#shServer').value=s.server||''; $('#shShare').value=s.share||''; $('#shMount').value=s.mount_point||''; $('#shLocal').value=s.local||''; $('#shUser').value=s.username||''; };
        const d=document.createElement('button'); d.textContent='Delete'; d.className='btn ghost'; d.onclick=async()=>{ await tryJSON('/shares', {method:'DELETE', body:JSON.stringify({id:s.id})}); await loadShares(); };
        w.appendChild(c); w.appendChild(e); w.appendChild(d); return w; })()
    }));
    table($('#sharesTable'),[{label:'Name',value:'name'},{label:'Type',value:'type'},{label:'Mount',value:'mount'},{label:'Status',value:'status'},{label:'',value:'actions'}], rows);
    const sel = $('#bkShare'); const share = state.shares.find(x=> String(x.id)===String(sel.value));
    $('#bkShareStatus').textContent = share? (share.connected?'Connected':'Disconnected') : 'Unknown';
  }

  // Picker modal
  let pickerCtx = null;
  async function openPicker({title, mode='dirs', hostId=null, shareId=null, inputEl}){
    pickerCtx = {mode, hostId, shareId, inputEl};
    $('#pickerTitle').textContent = title || 'Browse';
    $('#picker').showModal();
    $('#pickerPath').value = inputEl.value || '/';
    $('#pickerSupport').textContent = shareId && !caps.browseShares ? 'Share picker not supported by backend' : (!shareId && !caps.browseHosts ? 'Host picker not supported by backend' : '');
    if((shareId && !caps.browseShares) || (!shareId && !caps.browseHosts)) return;
    await refreshPicker();
  }
  async function refreshPicker(){
    const list = $('#pickerList'); const path = $('#pickerPath').value || '/';
    let entries = [];
    if(pickerCtx.shareId){
      const d = await tryJSON('/shares/browse', {method:'POST', body: JSON.stringify({id: pickerCtx.shareId, path})});
      entries = d.entries || [];
    }else if(pickerCtx.hostId){
      const d = await tryJSON('/hosts/browse', {method:'POST', body: JSON.stringify({host: pickerCtx.hostId, path})});
      entries = d.entries || [];
    }
    const rows = entries.filter(e=> pickerCtx.mode==='dirs' ? e.type==='dir' : true).map(e=>({name:e.name, type:e.type, actions:(()=>{
      const b=document.createElement('button'); b.textContent='Open'; b.className='btn'; b.onclick=()=>{ $('#pickerPath').value = (path.replace(/\/$/,'') + '/' + e.name).replace(/\/+/g,'/'); refreshPicker(); };
      return b;
    })()}));
    table(list, [{label:'Name',value:'name'},{label:'Type',value:'type'},{label:'',value:'actions'}], rows);
  }
  function closePicker(){ $('#picker').close(); pickerCtx=null; }
  function selectPicker(){ if(!pickerCtx) return closePicker(); pickerCtx.inputEl.value = $('#pickerPath').value; closePicker(); }

  function destFromUI(prefix){
    const t = $(prefix+'DestType')?.value || $('#bkDestType').value;
    if(t==='dropbox'){ const folder = $(prefix+'DropboxFolder')?.value || $('#bkDropboxFolder').value; return { type:'dropbox', folder }; }
    if(t==='share'){ const share_id = $(prefix+'Share')?.value || $('#bkShare').value; const subpath = $(prefix+'ShareSubpath')?.value || $('#bkShareSubpath').value; const sh = state.shares.find(s=>String(s.id)===String(share_id)); return { type:'share', share_id, share_name: sh?.name, subpath }; }
    const path = $(prefix+'DestPath')?.value || $('#bkDestPath').value; return { type:'path', path };
  }
  async function startBackup(){
    const source = { type: $('#bkType').value, host: $('#bkSrcHost').value, path: $('#bkSrcPath').value };
    const destination = destFromUI('#bk');
    const compression = $('#bkCompression').value;
    const name = $('#bkName').value || undefined;
    if(!source.host || !source.path) return;
    await tryJSON('/backup', {method:'POST', body: JSON.stringify({source, destination, compression, name})});
    await loadBackups();
  }
  async function startRestore(){
    const id=$('#rsBackupSelect').value; const host=$('#rsTargetHost').value; const path=$('#rsTargetPath').value;
    if(!id || !host || !path) return;
    await tryJSON('/restore', {method:'POST', body: JSON.stringify({backup_id:id, target:{host, path}})});
  }
  function buildSchedule(){
    const mode=$('#scMode').value;
    if(mode==='weekly'){ const wd=$('#scWeekday').value; const t=$('#scTime').value; const [hh,mm]=t.split(':'); return { human:`Weekly ${['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][+wd]} at ${t}`, cron:`${mm} ${hh} * * ${wd}` }; }
    if(mode==='monthly'){ const d=$('#scMonthday').value; const t=$('#scTime').value; const [hh,mm]=t.split(':'); return { human:`Monthly day ${d} at ${t}`, cron:`${mm} ${hh} ${d} * *` }; }
    if(mode==='once'){ const dt=$('#scOnceDateTime').value; return { human:`Once at ${dt}`, once_at: dt }; }
    const cron=$('#scCron').value; return { human:`Cron ${cron}`, cron };
  }
  async function createJob(){
    const name=$('#scName').value;
    const source={ type:$('#scType').value, host:$('#scSrcHost').value, path:$('#scSrcPath').value };
    let destination;
    if($('#scDestType').value==='share') destination={ type:'share', share_id:$('#scShare').value, subpath:$('#scShareSubpath').value };
    else if($('#scDestType').value==='dropbox') destination={ type:'dropbox', folder:$('#scDropboxFolder').value };
    else destination={ type:'path', path:$('#scDestPath').value };
    const schedule=buildSchedule();
    if(!name || !source.host || !source.path) return;
    await tryJSON('/scheduler/jobs', {method:'POST', body: JSON.stringify({ name, source, destination, schedule })});
    await loadJobs();
  }
  async function addHost(){ const host={ label:$('#hLabel').value, address:$('#hAddr').value, user:$('#hUser').value||'root', password:$('#hPass').value||undefined, default_path:$('#hPath').value||undefined }; if(!host.address) return; await tryJSON('/hosts',{method:'POST', body:JSON.stringify(host)}); await loadHosts(); }
  async function testHost(){ const addr=$('#hAddr').value; if(!addr) return; await tryJSON('/hosts/test',{method:'POST', body:JSON.stringify({address:addr, user:$('#hUser').value})}); }
  async function addShare(){ if(!caps.shares) return; const sh={ name:$('#shName').value, type:$('#shType').value, server:$('#shServer').value||undefined, share:$('#shShare').value||undefined, mount_point:$('#shMount').value, local:$('#shLocal').value||undefined, username:$('#shUser').value||undefined, password:$('#shPass').value||undefined }; if(!sh.name||!sh.type||!sh.mount_point) return; await tryJSON('/shares',{method:'POST', body:JSON.stringify(sh)}); await loadShares(); }
  async function connectShare(){ const id=$('#bkShare').value || $('#scShare').value || null; if(!id) return; await tryJSON('/shares/connect',{method:'POST', body:JSON.stringify({id})}); await loadShares(); }
  async function disconnectShare(){ const id=$('#bkShare').value || $('#scShare').value || null; if(!id) return; await tryJSON('/shares/disconnect',{method:'POST', body:JSON.stringify({id})}); await loadShares(); }
  async function testShare(){ const mp=$('#shMount').value; if(!mp) return; await tryJSON('/shares/test',{method:'POST', body:JSON.stringify({mount_point:mp})}); }

  function bind(){
    $$('.tab').forEach(btn => btn.addEventListener('click', () => {
      $$('.tab').forEach(b=>b.classList.remove('active')); btn.classList.add('active');
      $$('.tabpanel').forEach(p=>p.classList.remove('active')); $('#tab-'+btn.dataset.tab).classList.add('active');
    }));
    $('#bkDestType').addEventListener('change', e=>{ const t=e.target.value; $('#bkShareWrap').classList.toggle('hidden', t!=='share'); $('#bkDropboxWrap').classList.toggle('hidden', t!=='dropbox'); $('#bkDestPathWrap').classList.toggle('hidden', t!=='path'); });
    $('#scDestType').addEventListener('change', e=>{ const t=e.target.value; $('#scShareWrap').classList.toggle('hidden', t!=='share'); $('#scDropboxWrap').classList.toggle('hidden', t!=='dropbox'); $('#scDestPathLabel').classList.toggle('hidden', t!=='path'); });
    $('#bkBrowseSrc').onclick = ()=> openPicker({title:'Browse source path', mode:'dirs', hostId: $('#bkSrcHost').value, inputEl: $('#bkSrcPath')});
    $('#rsBrowseTarget').onclick = ()=> openPicker({title:'Browse restore target', mode:'dirs', hostId: $('#rsTargetHost').value, inputEl: $('#rsTargetPath')});
    $('#scBrowseSrc').onclick = ()=> openPicker({title:'Browse job source path', mode:'dirs', hostId: $('#scSrcHost').value, inputEl: $('#scSrcPath')});
    $('#bkShareBrowse').onclick = ()=> openPicker({title:'Browse share folder', mode:'dirs', shareId: $('#bkShare').value, inputEl: $('#bkShareSubpath')});
    $('#scShareBrowse').onclick = ()=> openPicker({title:'Browse share folder', mode:'dirs', shareId: $('#scShare').value, inputEl: $('#scShareSubpath')});
    $('#pickerRefresh').onclick = refreshPicker; $('#pickerUp').onclick = ()=>{ const p=$('#pickerPath'); p.value = (p.value.replace(/\/$/,'').split('/').slice(0,-1).join('/')||'/'); refreshPicker(); }; $('#pickerCancel').onclick = ()=> $('#picker').close(); $('#pickerSelect').onclick = selectPicker; $('#pickerClose').onclick = ()=> $('#picker').close();
    $('#startBackup').onclick = startBackup; $('#startRestore').onclick = startRestore; $('#scCreate').onclick = createJob;
    $('#hAdd').onclick = addHost; $('#hTest').onclick = testHost;
    $('#shAdd').onclick = addShare; $('#shConnect').onclick = connectShare; $('#shDisconnect').onclick = disconnectShare; $('#shTest').onclick = testShare;
    $('#refreshBtn').onclick = init;
  }

  async function init(){
    bind();
    await detect();
    await Promise.all([loadHosts(), loadBackups(), loadJobs(), loadShares()]);
    try{ const log = await tryJSON('/logs'); $('#logView').textContent = (log?.text||'').trim(); }catch{}
  }
  document.addEventListener('DOMContentLoaded', init);
})();
