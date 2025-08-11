// Tab nav
const tabs = document.querySelectorAll('.tab-link');
const sections = document.querySelectorAll('.tab');
tabs.forEach(t => t.addEventListener('click', (e) => {
  e.preventDefault();
  tabs.forEach(x => x.classList.remove('active'));
  t.classList.add('active');
  sections.forEach(s => s.classList.remove('active'));
  const target = document.querySelector(t.getAttribute('href'));
  if (target) target.classList.add('active');
}));

async function api(path, opts={}){
  const r = await fetch(path, {headers: {'Content-Type':'application/json'}, ...opts});
  if(!r.ok) throw new Error('HTTP '+r.status);
  return await r.json();
}

// Refresh loop
let refreshTimer=null;
function setRefreshInterval(sec){
  if(refreshTimer) clearInterval(refreshTimer);
  refreshTimer=setInterval(()=>refreshDashboard(true), sec*1000);
}

// Dashboard refresh
async function refreshDashboard(silent=false){
  const res = await api('/api/sync', {method:'POST', body: JSON.stringify({dry_run:true})});
  const total = res.summary.total || 0;
  const blocked = res.summary.blocked || 0;
  const allowed = res.summary.allowed || Math.max(0, total-blocked);
  const percent = total ? ((blocked/total)*100).toFixed(1) : 0;
  document.getElementById('kpi-total').textContent = total;
  document.getElementById('kpi-blocked').textContent = blocked;
  document.getElementById('kpi-allowed').textContent = allowed;
  document.getElementById('kpi-percent').textContent = percent + '%';
  document.getElementById('kpi-busiest').textContent = res.top3.busiest || 'n/a';

  const tq = document.getElementById('top-queried'); tq.innerHTML='';
  (res.top3.queried || []).forEach(i=>{ const li=document.createElement('li'); li.textContent=`${i.domain} (${i.hits})`; tq.appendChild(li); });
  const tb = document.getElementById('top-blocked'); tb.innerHTML='';
  (res.top3.blocked || []).forEach(i=>{ const li=document.createElement('li'); li.textContent=`${i.domain} (${i.hits})`; tb.appendChild(li); });

  const tbody = document.querySelector('#servers-table tbody'); tbody.innerHTML='';
  const cfg = await api('/api/config');
  Object.entries(res.servers).forEach(([name, info])=>{
    const tr = document.createElement('tr');
    const spec = (cfg.servers||[]).find(s=>s.name===name);
    const type = spec ? spec.type : '?';
    const totalS = info.stats?.total ?? 0;
    const blockedS = info.stats?.blocked ?? 0;
    const allowedS = Math.max(0, totalS - blockedS);
    tr.innerHTML = `<td>${name}${spec&&spec.primary?' <span class="badge primary-badge">Primary</span>':''}</td>`+
                   `<td>${type}</td><td>${info.status}</td><td>${totalS}</td><td>${blockedS}</td><td>${allowedS}</td>`;
    const tdActions = document.createElement('td');
    const btn = document.createElement('button'); btn.textContent='Clear Stats';
    btn.disabled = !(type==='technitium' || type==='adguard');
    btn.title = btn.disabled ? 'Not supported by this server type' : '';
    btn.addEventListener('click', async ()=>{ btn.setAttribute('aria-busy','true'); try{ await api('/api/clear_stats',{method:'POST', body: JSON.stringify({name})}); } finally{ btn.removeAttribute('aria-busy'); refreshDashboard(); } });
    tdActions.appendChild(btn); tr.appendChild(tdActions); tbody.appendChild(tr);
  });

  const now = Date.now(); const allowedSeries=[], blockedSeries=[];
  for(let i=19;i>=0;i--){ allowedSeries.push({y: Math.round(allowed/20), t: new Date(now - i*60000)}); blockedSeries.push({y: Math.round(blocked/20), t: new Date(now - i*60000)}); }
  UnifiedCharts.renderUnifiedChart(document.getElementById('chart-unified'), allowedSeries, blockedSeries);

  if(!silent) console.log('Dashboard updated');
  refreshSyncServers();
  renderCachePerServer();
  const gl = await api('/api/cachelist'); document.getElementById('cache-global').value = (gl.global||[]).join('\n');
}

// Settings
async function refreshSettings(){
  const cfg = await api('/api/config');
  const tbody = document.querySelector('#settings-servers tbody'); tbody.innerHTML='';
  (cfg.servers || []).forEach(s => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${s.name}</td><td>${s.type}</td><td>${s.base_url}</td><td>${s.primary ? 'Yes':'No'}</td>`;
    const td = document.createElement('td');
    const del = document.createElement('button'); del.className='secondary'; del.textContent='Delete';
    del.addEventListener('click', async ()=>{ await api('/api/servers', {method:'DELETE', body: JSON.stringify({name: s.name})}); refreshSettings(); refreshDashboard(); });
    const makePrimary = document.createElement('button'); makePrimary.textContent='Make Primary';
    makePrimary.addEventListener('click', async ()=>{ await api('/api/primary', {method:'POST', body: JSON.stringify({name: s.name})}); refreshSettings(); refreshDashboard(); });
    td.appendChild(makePrimary); td.appendChild(del); tr.appendChild(td); tbody.appendChild(tr);
  });

  const nf = document.getElementById('notify-form');
  nf.gotify_url.value = cfg.gotify_url || '';
  nf.gotify_token.value = cfg.gotify_token || '';
}

async function refreshSyncServers(){
  const cfg = await api('/api/config');
  const wrap = document.getElementById('sync-servers'); wrap.innerHTML='';
  (cfg.servers || []).forEach(s => {
    const tr = document.createElement('tr');
    const isPrimary = !!s.primary;
    const base = btoa(s.name).replace(/=/g,'');
    const mk = (id, enabled, checked) => `<input type="checkbox" id="${id}_${base}" ${enabled?'':'disabled'} ${enabled&&checked?'checked':''}>`;
    const canFwd = s.type!=='pihole' && !isPrimary;
    const canBlk = false;
    const canUps = false;
    const canOvr = false;
    const canCB  = true && !isPrimary;
    const canPrep= true && !isPrimary;
    tr.innerHTML = `<td>${s.name} ${isPrimary?'<span class="badge primary-badge">Primary</span>':''}</td>`+
      `<td>${mk('fwd', canFwd, canFwd)}</td>`+
      `<td>${mk('blk', canBlk, false)}</td>`+
      `<td>${mk('ups', canUps, false)}</td>`+
      `<td>${mk('ovr', canOvr, false)}</td>`+
      `<td>${mk('cbl', canCB, true)}</td>`+
      `<td>${mk('prep', canPrep, false)}</td>`;
    wrap.appendChild(tr);
  });
}

// Forms
document.getElementById('server-form').addEventListener('submit', async (e)=>{
  e.preventDefault();
  const fd = new FormData(e.target);
  const data = {
    name: fd.get('name'),
    type: fd.get('type'),
    base_url: fd.get('base_url'),
    dns_host: fd.get('dns_host') || null,
    dns_port: fd.get('dns_port') ? parseInt(fd.get('dns_port'),10) : null,
    dns_protocol: fd.get('dns_protocol') || 'udp',
    username: fd.get('username') || null,
    password: fd.get('password') || null,
    token: fd.get('token') || null,
    verify_tls: !!fd.get('verify_tls'),
    primary: !!fd.get('primary')
  };
  await api('/api/servers', {method:'POST', body: JSON.stringify(data)});
  e.target.reset();
  refreshSettings(); refreshDashboard();
});

document.getElementById('cache-global-form').addEventListener('submit', async (e)=>{
  e.preventDefault();
  const entries = document.getElementById('cache-global').value.split('\n').map(x=>x.trim()).filter(Boolean);
  await api('/api/cachelist', {method:'POST', body: JSON.stringify({entries})});
  refreshDashboard();
});

function renderCachePerServer(){
  const container = document.getElementById('cache-per-server');
  container.innerHTML='';
  api('/api/config').then(cfg=>{
    (cfg.servers||[]).forEach(async s => {
      const panel = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = s.name + ' ('+s.type+')';
      panel.appendChild(summary);
      const resp = await api(`/api/cachelist?name=${encodeURIComponent(s.name)}`);
      const override = !!resp.override;
      const local = (resp.local||[]).join('\n');
      const effective = (resp.effective||[]).join('\n');
      const div = document.createElement('div');
      div.innerHTML = `
        <label><input type="checkbox" class="cb-override" ${override?'checked':''}> Override Primary list</label>
        <div class="grid">
          <label>Local list (used only if override ON)
            <textarea class="cb-local" rows="6">${local}</textarea>
          </label>
          <label>Effective (read-only)
            <textarea class="cb-effective" rows="6" disabled>${effective}</textarea>
          </label>
        </div>
        <div class="row">
          <button class="cb-save">Save</button>
          <button class="cb-prep">Run Cache Prep</button>
          <label><input type="checkbox" class="cb-dry"> Dry run</label>
          <select class="cb-listmode">
            <option value="effective">Use Effective</option>
            <option value="primary">Use Primary List</option>
            <option value="local">Use Local List</option>
          </select>
        </div>
        <pre class="cb-output code"></pre>
      `;
      panel.appendChild(div);
      container.appendChild(panel);

      panel.querySelector('.cb-save').addEventListener('click', async (e)=>{
        e.preventDefault();
        const overrideNow = panel.querySelector('.cb-override').checked;
        const entries = panel.querySelector('.cb-local').value.split('\n').map(x=>x.trim()).filter(Boolean);
        await api('/api/cachelist', {method:'POST', body: JSON.stringify({name: s.name, override: overrideNow, entries})});
        await refreshDashboard();
      });

      panel.querySelector('.cb-prep').addEventListener('click', async (e)=>{
        e.preventDefault();
        const listmode = panel.querySelector('.cb-listmode').value;
        const dry = panel.querySelector('.cb-dry').checked;
        const out = panel.querySelector('.cb-output');
        out.textContent='Running...';
        const res = await api('/api/cacheprep', {method:'POST', body: JSON.stringify({name: s.name, list: listmode, dry_run: dry})});
        out.textContent = JSON.stringify(res, null, 2);
      });
    });
  });
}

document.getElementById('notify-form').addEventListener('submit', async (e)=>{
  e.preventDefault();
  const fd = new FormData(e.target);
  await api('/api/config', {method:'POST', body: JSON.stringify({gotify_url: fd.get('gotify_url') || '', gotify_token: fd.get('gotify_token') || ''})});
  document.getElementById('notify-status').textContent = 'Saved.';
});
document.getElementById('notify-test').addEventListener('click', async ()=>{
  const r = await api('/api/notify/test', {method:'POST'});
  document.getElementById('notify-status').textContent = r.ok ? 'Test sent.' : ('Failed: '+r.detail);
});

document.getElementById('sync-form').addEventListener('submit', async (e)=>{
  e.preventDefault();
  const dry = document.getElementById('dry-run').checked;
  const doPrep = document.getElementById('cache-prep').checked;
  const cfg = await api('/api/config');
  const targets = [];
  (cfg.servers||[]).forEach(s=>{
    if(s.primary) return;
    const base = btoa(s.name).replace(/=/g,'');
    const fwd = document.getElementById('fwd_'+base);
    if(fwd && !fwd.disabled && fwd.checked){ targets.push(s.name); }
  });
  const res = await api('/api/sync', {method:'POST', body: JSON.stringify({dry_run: dry, servers: targets, cache_prep: doPrep})});
  document.getElementById('sync-output').textContent = JSON.stringify(res, null, 2);
  refreshDashboard();
});

document.getElementById('refresh-logs').addEventListener('click', async ()=>{
  const logs = await api('/api/logs');
  document.getElementById('logs-output').textContent = JSON.stringify(logs, null, 2);
});

// Self-Check wiring
document.getElementById('run-selfcheck').addEventListener('click', async ()=>{
  const out = document.getElementById('selfcheck-output');
  out.textContent = 'Running...';
  const res = await api('/api/selfcheck');
  out.textContent = JSON.stringify(res, null, 2);
});

// Refresh controls
const sel=document.getElementById('refresh-interval'); const btn=document.getElementById('refresh-now');
if(sel){ setRefreshInterval(parseInt(sel.value,10)); sel.addEventListener('change',()=>setRefreshInterval(parseInt(sel.value,10))); }
if(btn){ btn.addEventListener('click', ()=>refreshDashboard()); }

// Initial load
refreshSettings().then(()=>refreshDashboard());
