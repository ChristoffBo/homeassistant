(() => {
  'use strict';

  // ------- Config -------
  const API_BASE = './api';   // relative for HA Ingress
  const $ = (q, ctx=document) => ctx.querySelector(q);
  const $$ = (q, ctx=document) => Array.from(ctx.querySelectorAll(q));
  const fmt = (d)=> new Date(d).toLocaleString();

  // ------- State -------
  const state = {
    hosts: [],
    backups: [],
    jobs: [],
    settings: {},
  };

  // ------- Helpers -------
  function toast(msg, type='info'){
    console.log(`[${type}]`, msg);
  }

  function setApiStatus(ok){ 
    const el = $('#apiStatus'); 
    el.classList.toggle('online', !!ok);
    el.classList.toggle('offline', !ok);
    el.title = ok ? 'API online' : 'API offline';
  }

  async function fetchJSON(path, opts={}){
    const controller = new AbortController();
    const t = setTimeout(()=>controller.abort(), 20000);
    try{
      const res = await fetch(`${API_BASE}${path}`, {headers: {'Content-Type':'application/json'}, signal: controller.signal, ...opts});
      if(!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const data = await res.json().catch(()=> ({}));
      setApiStatus(true);
      return data;
    }catch(err){
      setApiStatus(false);
      toast(err.message, 'error');
      throw err;
    }finally{
      clearTimeout(t);
    }
  }

  function table(container, columns, rows){
    const tpl = $('#tpl-table').content.cloneNode(true);
    const thead = tpl.querySelector('thead'); const tbody = tpl.querySelector('tbody');
    const tr = document.createElement('tr');
    columns.forEach(c => {
      const th = document.createElement('th'); th.textContent = c.label; tr.appendChild(th);
    });
    thead.appendChild(tr);
    rows.forEach(r => {
      const trb = document.createElement('tr');
      columns.forEach(c => {
        const td = document.createElement('td');
        const v = typeof c.value === 'function' ? c.value(r) : r[c.value];
        if(v instanceof Node) td.appendChild(v); else td.textContent = v ?? '';
        trb.appendChild(td);
      });
      tbody.appendChild(trb);
    });
    container.innerHTML = ''; container.appendChild(tpl);
  }

  function modalConfirm({title='Confirm', body, okText='OK', onOk}){
    const dlg = $('#modal');
    $('#modalTitle').textContent = title;
    $('#modalBody').innerHTML = '';
    if(typeof body === 'string'){ $('#modalBody').textContent = body; } else { $('#modalBody').appendChild(body); }
    $('#modalOk').textContent = okText;
    const close = ()=> dlg.close();
    $('#modalClose').onclick = close;
    $('#modalCancel').onclick = close;
    $('#modalOk').onclick = async() => { try{ await onOk?.(); close(); } catch(e){ toast(e.message,'error'); } };
    dlg.showModal();
  }

  function fillSelect(sel, items, {value='value', label='label', empty='-- select --'}={}){
    sel.innerHTML = '';
    const opt0 = document.createElement('option'); opt0.value=''; opt0.textContent = empty; sel.appendChild(opt0);
    for(const it of items){
      const o = document.createElement('option');
      o.value = it[value]; o.textContent = it[label]; sel.appendChild(o);
    }
  }

  function persistLocal(key, val){ localStorage.setItem(`rlb:${key}`, JSON.stringify(val)); }
  function loadLocal(key, def){ try{ return JSON.parse(localStorage.getItem(`rlb:${key}`)) ?? def; } catch{ return def; } }

  // ------- Loaders -------
  async function loadHosts(){
    try{
      const data = await fetchJSON('/hosts');
      state.hosts = data.hosts || [];
      persistLocal('hosts', state.hosts);
    }catch{
      state.hosts = loadLocal('hosts', []);
    }
    // populate selects
    const hostOpts = state.hosts.map(h => ({ value: h.id || h.address, label: `${h.label || h.address} (${h.user || 'user'}@${h.address})` }));
    [$('#bkSrcHost'), $('#rsTargetHost'), $('#scSrcHost')].forEach(sel => fillSelect(sel, hostOpts));
    renderHostsTable();
  }

  async function loadBackups(){
    try{
      const data = await fetchJSON('/backups');
      state.backups = data.backups || [];
    }catch{
      state.backups = [];
    }
    renderBackups();
    fillSelect($('#rsBackupSelect'), state.backups.map(b => ({value: b.id, label: `${b.name} • ${b.size || ''} • ${b.created ? fmt(b.created): ''}`})));
  }

  async function loadJobs(){
    try{
      const data = await fetchJSON('/scheduler/jobs');
      state.jobs = data.jobs || [];
    }catch{ state.jobs = []; }
    renderJobs();
  }

  async function loadSettings(){
    try{
      const data = await fetchJSON('/settings');
      state.settings = data || {};
      $('#setDropboxToken').value = data.dropbox_token || '';
      $('#setDropboxFolder').value = data.dropbox_folder || '';
      $('#setGotifyUrl').value = data.gotify_url || '';
      $('#setGotifyToken').value = data.gotify_token || '';
    }catch{}
  }

  // ------- Renderers -------
  function renderHostsTable(){
    const rows = state.hosts.map(h => ({
      label: h.label || '',
      addr: h.address,
      user: h.user || 'root',
      path: h.default_path || '',
      actions: (()=>{
        const w = document.createElement('div');
        const e = document.createElement('button'); e.textContent='Edit'; e.className='btn ghost'; e.onclick=()=>{
          $('#hLabel').value = h.label || '';
          $('#hAddr').value = h.address || '';
          $('#hUser').value = h.user || 'root';
          $('#hPath').value = h.default_path || '';
        };
        const d = document.createElement('button'); d.textContent='Delete'; d.className='btn ghost'; d.onclick=()=>{
          modalConfirm({title:'Delete host', body:`Remove ${h.label || h.address}?`, onOk: async()=>{
            await fetchJSON('/hosts', {method:'DELETE', body: JSON.stringify({address: h.address})});
            await loadHosts();
          }});
        };
        w.appendChild(e); w.appendChild(d);
        return w;
      })()
    }));
    table($('#hostsTable'),
      [{label:'Label',value:'label'},{label:'Address',value:'addr'},{label:'User',value:'user'},{label:'Default path',value:'path'},{label:'',value:'actions'}],
      rows);
  }

  function renderBackups(){
    const rows = state.backups.map(b => ({
      name: b.name || b.id,
      type: b.type,
      size: b.size || '',
      created: b.created ? fmt(b.created) : '',
      location: b.location || '',
      actions: (()=>{
        const a = document.createElement('button'); a.textContent='Restore…'; a.className='btn';
        a.onclick = () => promptRestore(b);
        return a;
      })()
    }));
    table($('#backupsTable'),
      [{label:'Name',value:'name'},{label:'Type',value:(r)=> r.type==='dd'?'Full image':'Folder/Files'},{label:'Size',value:'size'},{label:'Created',value:'created'},{label:'Stored at',value:'location'},{label:'',value:'actions'}],
      rows);
  }

  function renderJobs(){
    const rows = state.jobs.map(j => ({
      name: j.name,
      src: `${j.source?.host_label || j.source?.host} • ${j.source?.path}`,
      dest: j.destination?.type === 'dropbox' ? `Dropbox ${j.destination?.folder}` : j.destination?.path,
      schedule: j.cron || j.human || '',
      actions: (()=>{
        const w = document.createElement('div');
        const run = document.createElement('button'); run.textContent='Run now'; run.className='btn';
        run.onclick = async()=>{ await fetchJSON(`/scheduler/run`, {method:'POST', body: JSON.stringify({name:j.name})}); };
        const del = document.createElement('button'); del.textContent='Delete'; del.className='btn ghost';
        del.onclick = ()=> modalConfirm({title:'Delete job', body:j.name, onOk: async()=>{ await fetchJSON('/scheduler/jobs', {method:'DELETE', body: JSON.stringify({name:j.name})}); await loadJobs(); }});
        w.appendChild(run); w.appendChild(del);
        return w;
      })()
    }));
    table($('#jobsTable'),
      [{label:'Name',value:'name'},{label:'Source',value:'src'},{label:'Destination',value:'dest'},{label:'Schedule',value:'schedule'},{label:'',value:'actions'}],
      rows);
  }

  // ------- Actions -------
  function currentSourceFromUI(prefix){
    const type = $(prefix+'Type')?.value || $('#bkType').value;
    const host = $(prefix+'SrcHost')?.value || $('#bkSrcHost').value;
    const path = $(prefix+'SrcPath')?.value || $('#bkSrcPath').value;
    return { type, host, path };
  }

  function currentDestinationFromUI(prefix){
    const destType = $(prefix+'DestType')?.value || $('#bkDestType').value;
    if(destType === 'dropbox'){
      const folder = $(prefix+'DropboxFolder')?.value || $('#bkDropboxFolder').value;
      return { type: 'dropbox', folder };
    }
    const path = $(prefix+'DestPath')?.value || $('#bkDestPath').value;
    return { type: 'path', path };
  }

  async function startBackup(){
    const source = currentSourceFromUI('#bk');
    const destination = currentDestinationFromUI('#bk');
    const compression = $('#bkCompression').value;
    const name = $('#bkName').value || undefined;
    if(!source.host || !source.path){ return toast('Source host and path are required','error'); }
    if(destination.type==='path' && !destination.path){ return toast('Destination path required','error'); }
    if(destination.type==='dropbox' && !destination.folder){ return toast('Dropbox folder required','error'); }
    const body = {source, destination, compression, name};
    modalConfirm({
      title:'Start backup',
      body:`${source.type==='dd'?'Full image':'Folder/files'} from ${source.host}:${source.path}`,
      okText:'Start',
      onOk: async()=>{
        await fetchJSON('/backup', {method:'POST', body: JSON.stringify(body)});
        await loadBackups();
      }
    });
  }

  function promptRestore(backup){
    const body = document.createElement('div');
    body.innerHTML = `
      <div class="form-grid two">
        <label>Restore to host
          <select id="mdlHost"></select>
        </label>
        <label>Restore path / device
          <input id="mdlPath" type="text" placeholder="/restore/path or /dev/sda" />
        </label>
      </div>
    `;
    const sel = body.querySelector('#mdlHost');
    fillSelect(sel, state.hosts.map(h=>({value:h.id||h.address,label:h.label||h.address})));
    modalConfirm({
      title:`Restore: ${backup.name}`,
      body,
      okText:'Restore',
      onOk: async()=>{
        const host = body.querySelector('#mdlHost').value;
        const path = body.querySelector('#mdlPath').value;
        if(!host || !path) throw new Error('Host and path required');
        await fetchJSON('/restore', {method:'POST', body: JSON.stringify({backup_id: backup.id, target: {host, path}})});
      }
    });
  }

  async function startRestore(){
    const id = $('#rsBackupSelect').value;
    const host = $('#rsTargetHost').value;
    const path = $('#rsTargetPath').value;
    if(!id || !host || !path){ return toast('Select backup, host and path','error'); }
    await fetchJSON('/restore', {method:'POST', body: JSON.stringify({backup_id: id, target: {host, path}})});
  }

  function buildSchedule(){
    const mode = $('#scMode').value;
    if(mode==='weekly'){
      const wd = $('#scWeekday').value; const t = $('#scTime').value;
      const [hh,mm] = t.split(':');
      return { human:`Weekly ${['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][+wd]} at ${t}`, cron:`${mm} ${hh} * * ${wd}` };
    }
    if(mode==='monthly'){
      const d = $('#scMonthday').value; const t = $('#scTime').value;
      const [hh,mm] = t.split(':');
      return { human:`Monthly day ${d} at ${t}`, cron:`${mm} ${hh} ${d} * *` };
    }
    if(mode==='once'){
      const dt = $('#scOnceDateTime').value;
      return { human:`Once at ${dt}`, once_at: dt };
    }
    const cron = $('#scCron').value;
    return { human:`Cron ${cron}`, cron };
  }

  async function createJob(){
    const name = $('#scName').value;
    const source = { type: $('#scType').value, host: $('#scSrcHost').value, path: $('#scSrcPath').value };
    const destination = ( ()=> {
      if($('#scDestType').value === 'dropbox') return { type:'dropbox', folder: $('#scDropboxFolder').value };
      return { type:'path', path: $('#scDestPath').value };
    })();
    const sched = buildSchedule();
    if(!name || !source.host || !source.path) return toast('Missing required fields','error');
    const body = { name, source, destination, schedule: sched };
    await fetchJSON('/scheduler/jobs', {method:'POST', body: JSON.stringify(body)});
    await loadJobs();
  }

  async function saveSettings(){
    const body = {
      dropbox_token: $('#setDropboxToken').value || undefined,
      dropbox_folder: $('#setDropboxFolder').value || undefined,
      gotify_url: $('#setGotifyUrl').value || undefined,
      gotify_token: $('#setGotifyToken').value || undefined,
    };
    await fetchJSON('/settings', {method:'POST', body: JSON.stringify(body)});
    await loadSettings();
  }

  async function addHost(){
    const host = {
      label: $('#hLabel').value,
      address: $('#hAddr').value,
      user: $('#hUser').value || 'root',
      password: $('#hPass').value || undefined,
      default_path: $('#hPath').value || undefined,
    };
    if(!host.address) return toast('Address required','error');
    await fetchJSON('/hosts', {method:'POST', body: JSON.stringify(host)});
    await loadHosts();
  }

  async function testDropbox(){
    await fetchJSON('/dropbox/test', {method:'POST'});
    toast('Dropbox OK', 'ok');
  }

  // ------- Events -------
  function bind(){
    // tabs
    $$('.tab').forEach(btn => btn.addEventListener('click', () => {
      $$('.tab').forEach(b=>b.classList.remove('active')); btn.classList.add('active');
      $$('.tabpanel').forEach(p=>p.classList.remove('active'));
      $(`#tab-${btn.dataset.tab}`).classList.add('active');
    }));
    // dynamic UI show/hide
    $('#bkType').addEventListener('change', e => {
      $('#bkPathLabel').firstChild.textContent = (e.target.value==='dd'?'Device (e.g., /dev/sda)':'Path (folder or file)');
    });
    $('#bkDestType').addEventListener('change', e => {
      const drop = e.target.value==='dropbox';
      $('#bkDestPathWrap').classList.toggle('hidden', drop);
      $('#bkDropboxWrap').classList.toggle('hidden', !drop);
    });
    $('#scDestType').addEventListener('change', e => {
      const drop = e.target.value==='dropbox';
      $('#scDestPathLabel').classList.toggle('hidden', drop);
      $('#scDropboxWrap').classList.toggle('hidden', !drop);
    });
    $('#scMode').addEventListener('change', e => {
      const m = e.target.value;
      $('#scWeeklyWrap').classList.toggle('hidden', m!=='weekly');
      $('#scMonthlyWrap').classList.toggle('hidden', m!=='monthly');
      $('#scTimeWrap').classList.toggle('hidden', m==='once' || m==='cron');
      $('#scOnceWrap').classList.toggle('hidden', m!=='once');
      $('#scCronWrap').classList.toggle('hidden', m!=='cron');
    });

    // actions
    $('#startBackup').onclick = startBackup;
    $('#startRestore').onclick = startRestore;
    $('#scCreate').onclick = createJob;
    $('#saveSettings').onclick = saveSettings;
    $('#hAdd').onclick = addHost;
    $('#hTest').onclick = async()=>{ await fetchJSON('/hosts/test', {method:'POST', body: JSON.stringify({address: $('#hAddr').value, user: $('#hUser').value})}); };
    $('#testDropbox').onclick = testDropbox;
    $('#refreshBtn').onclick = init;
  }

  async function init(){
    bind();
    await Promise.all([loadHosts(), loadBackups(), loadJobs(), loadSettings()]).catch(()=>{});
    // Logs
    try{
      const log = await fetchJSON('/logs');
      $('#logView').textContent = (log?.text || '').trim();
    }catch{
      $('#logView').textContent = 'No logs yet.';
    }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
