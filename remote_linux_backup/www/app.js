(() => {
  'use strict';

  // ---------- Helpers ----------
  const $ = (sel, el=document) => el.querySelector(sel);
  const $$ = (sel, el=document) => Array.from(el.querySelectorAll(sel));
  const on = (el, ev, fn) => el && el.addEventListener(ev, fn);
  const val = (id) => (document.getElementById(id)?.value ?? '').trim();

  function showTab(id) {
    $$('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === id));
    $$('.tab-panel').forEach(p => p.classList.toggle('active', p.id === id));
    localStorage.setItem('rlb_active_tab', id);
  }

  function numberOrZero(s) {
    const n = parseFloat(s);
    return isFinite(n) && n >= 0 ? n : 0;
  }

  function fetchJSON(url, opts={}) {
    return fetch(url, Object.assign({headers: {'Content-Type':'application/json'}}, opts))
      .then(r => r.json());
  }

  function logLine(text) {
    const el = $('#log');
    if (!el) return;
    el.textContent += text + '\n';
    el.scrollTop = el.scrollHeight;
  }

  // ---------- Tabs ----------
  on(document, 'DOMContentLoaded', () => {
    // Wire tab buttons
    $$('#tabs .tab-btn').forEach(btn => {
      on(btn, 'click', () => showTab(btn.dataset.tab));
    });
    const savedTab = localStorage.getItem('rlb_active_tab');
    if (savedTab && document.getElementById(savedTab)) showTab(savedTab);

    // Dynamic rows for mode
    const modeSel = $('#b_mode');
    const syncRow = $('#rsync-row');
    const imgRow = $('#image-row');
    const updateRows = () => {
      const m = modeSel.value;
      syncRow.classList.toggle('hidden', m !== 'rsync' && m !== 'copy_local' && m !== 'copy_mount');
      imgRow.classList.toggle('hidden', m !== 'image');
    };
    on(modeSel, 'change', updateRows);
    updateRows();

    // SocketIO
    const socket = io();
    socket.on('connect', () => logLine('[socket] connected'));
    socket.on('job_update', (job) => {
      const p = $('#b_progress');
      const pct = Math.max(0, Math.min(100, job.progress || 0));
      if (p) p.value = pct;
      const pctEl = $('#b_progress_pct');
      if (pctEl) pctEl.textContent = `${pct}%`;
    });
    socket.on('job_log', (d) => logLine(d.line || ''));

    // Buttons
    on($('#b_estimate'), 'click', async () => {
      const body = {
        host: val('b_host'),
        port: parseInt(val('b_port') || '22', 10) || 22,
        username: val('b_user'),
        password: val('b_pass'),
        path: val('b_src') || '/'
      };
      try {
        const r = await fetchJSON('/api/estimate/ssh_size', {method:'POST', body: JSON.stringify(body)});
        if (r.ok) { logLine(`Estimated size: ${r.bytes} bytes`); }
        else { alert('Estimate failed: ' + (r.error || '')); }
      } catch (e) { alert('Estimate error: ' + e); }
    });

    on($('#b_browse'), 'click', async () => {
      // Minimal: just prefill root for now (server provides sftp_listdir API in future)
      const p = prompt('Enter remote path to back up (example: /var/log)');
      if (p) $('#b_src').value = p;
    });

    on($('#b_start'), 'click', async () => {
      const mode = $('#b_mode').value;
      const bwMB = numberOrZero($('#b_bwlimit').value);
      const bwKB = Math.round(bwMB * 1024);
      const label = val('b_label');
      let body = { mode, label, bwlimit_kbps: bwKB };

      if (mode === 'rsync') {
        body.host = val('b_host'); body.port = 22;
        body.username = val('b_user'); body.password = val('b_pass');
        body.source_path = val('b_src') || '/';
      } else if (mode === 'copy_local') {
        body.source_path = val('b_src') || '/';
      } else if (mode === 'copy_mount') {
        body.mount_name = val('b_conn') || ''; // reuse dropdown to choose a mount name if populated later
        body.source_path = val('b_src') || '/';
      } else if (mode === 'image') {
        body.host = val('b_host'); body.port = 22;
        body.username = val('b_user'); body.password = val('b_pass');
        body.device = val('b_device');
        body.encrypt = ($('#b_encrypt').value === '1');
        body.passphrase = val('b_passphrase');
      }

      try {
        const r = await fetchJSON('/api/backup/start', {method:'POST', body: JSON.stringify(body)});
        if (!r.ok) { alert('Start failed: ' + (r.error || '')); return; }
        logLine('Job started: ' + r.job_id);
      } catch (e) {
        alert('Start error: ' + e);
      }
    });

    on($('#b_cancel'), 'click', async () => {
      try {
        const jobs = await fetchJSON('/api/jobs');
        const running = jobs.find(j => j.status === 'running');
        if (!running) { alert('No running job'); return; }
        const r = await fetchJSON('/api/jobs/cancel', {method:'POST', body: JSON.stringify({job_id: running.id})});
        if (!r.ok) { alert('Cancel failed: ' + (r.error || '')); }
      } catch (e) { alert('Cancel error: ' + e); }
    });

    // Restore UI switching
    const rMode = $('#r_mode');
    const rSyncRow = $('#r-row-rsync');
    const rImgRow = $('#r-row-image');
    const rUpdate = () => {
      const v = rMode.value;
      rSyncRow.classList.toggle('hidden', v !== 'rsync');
      rImgRow.classList.toggle('hidden', v !== 'image');
    };
    on(rMode, 'change', rUpdate); rUpdate();

    on($('#r_start'), 'click', async () => {
      const mode = $('#r_mode').value;
      const body = { mode, host: val('r_host'), port: 22, username: val('r_user'), password: val('r_pass') };
      if (mode === 'rsync') {
        body.local_src = val('r_src'); body.dest_path = val('r_dest');
        body.dry_run = $('#r_dry').value === '1';
      } else {
        body.local_src = val('r_img'); body.device = val('r_dev');
        body.confirm = val('r_confirm');
      }
      try {
        const r = await fetchJSON('/api/restore/start', {method:'POST', body: JSON.stringify(body)});
        if (!r.ok) { alert('Restore failed: ' + (r.error || '')); return; }
        $('#r_log').textContent += 'Restore job: ' + r.job_id + '\n';
      } catch (e) { alert('Restore error: ' + e); }
    });

    // Connections
    async function loadConns() {
      const d = await fetchJSON('/api/connections');
      const tbody = $('#c_table tbody'); tbody.innerHTML = '';
      (d.connections || []).forEach(c => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${c.name||''}</td><td>${c.host||''}</td><td>${c.port||''}</td><td>${c.username||''}</td>
          <td><button class="small danger" data-del="${c.name}">Delete</button></td>`;
        tbody.appendChild(tr);
      });
    }
    on($('#c_refresh'), 'click', loadConns);
    on($('#c_save'), 'click', async () => {
      const body = {name: val('c_name'), host: val('c_host'), port: parseInt(val('c_port')||'22',10), username: val('c_user'), password: val('c_pass')};
      const r = await fetchJSON('/api/connections', {method:'POST', body: JSON.stringify(body)});
      if (!r.ok) { alert('Save failed'); return; }
      await loadConns();
    });
    on($('#c_table'), 'click', async (ev) => {
      const b = ev.target.closest('button[data-del]'); if (!b) return;
      const name = b.dataset.del;
      const r = await fetchJSON('/api/connections/delete', {method:'POST', body: JSON.stringify({name})});
      if (!r.ok) { alert('Delete failed'); return; }
      await loadConns();
    });
    loadConns();

    // Mounts
    async function loadMounts(){
      const d = await fetchJSON('/api/mounts');
      const tbody = $('#m_table tbody'); tbody.innerHTML = '';
      (d.mounts||[]).forEach(m => {
        const tr = document.createElement('tr');
        const st = m.mounted ? 'mounted' : 'not mounted';
        const lastErr = m.status && m.status.last_error ? m.status.last_error : '';
        tr.innerHTML = `<td>${m.name}</td><td>${m.type}</td><td>${m.host}</td><td>${m.share||m.export||''}</td>
          <td>${st}</td><td>${m.mountpoint||''}</td><td class="muted">${lastErr}</td>
          <td>
            <button class="small" data-mount="${m.name}">Mount</button>
            <button class="small" data-umount="${m.name}">Umount</button>
            <button class="small danger" data-del="${m.name}">Delete</button>
          </td>`;
        tbody.appendChild(tr);
      });
    }
    on($('#m_refresh'), 'click', loadMounts);
    on($('#m_save'), 'click', async () => {
      const body = {
        name: val('m_name'), type: val('m_type'), host: val('m_host'), share: val('m_share'),
        export: val('m_share'), username: val('m_user'), password: val('m_pass'),
        options: val('m_opts'), auto_mount: true, auto_retry: $('#m_retry').value === '1'
      };
      const r = await fetchJSON('/api/mounts', {method:'POST', body: JSON.stringify(body)});
      if (!r.ok) { alert('Save failed'); return; }
      await loadMounts();
    });
    on($('#m_table'), 'click', async (ev) => {
      const b = ev.target.closest('button'); if (!b) return;
      if (b.dataset.mount) await fetchJSON('/api/mounts/mount', {method:'POST', body: JSON.stringify({name: b.dataset.mount})});
      else if (b.dataset.umount) await fetchJSON('/api/mounts/umount', {method:'POST', body: JSON.stringify({name: b.dataset.umount})});
      else if (b.dataset.del) await fetchJSON('/api/mounts/delete', {method:'POST', body: JSON.stringify({name: b.dataset.del})});
      await loadMounts();
    });
    loadMounts();

    // Backups
    async function loadBackups(){
      const rows = await fetchJSON('/api/backups');
      const tbody = $('#b_table tbody'); tbody.innerHTML = '';
      rows.forEach(r => {
        const tr = document.createElement('tr');
        const dt = new Date(r.mtime*1000).toLocaleString();
        tr.innerHTML = `<td>${r.rel}</td><td>${r.is_dir?'yes':'no'}</td><td>${r.size_h}</td><td>${dt}</td>
          <td><button class="small" data-dl="${r.rel}">Download</button>
              <button class="small danger" data-del="${r.rel}">Delete</button>
              ${r.is_dir ? '<button class="small" data-verify="'+r.rel+'">Verify</button>' : ''}
          </td>`;
        tbody.appendChild(tr);
      });
    }
    on($('#b_refresh'), 'click', loadBackups);
    on($('#b_table'), 'click', async (ev) => {
      const b = ev.target.closest('button'); if(!b) return;
      if (b.dataset.dl) window.open('/api/backups/download?rel='+encodeURIComponent(b.dataset.dl), '_blank');
      if (b.dataset.del) { await fetchJSON('/api/backups/delete', {method:'POST', body: JSON.stringify({rel: b.dataset.del})}); await loadBackups(); }
      if (b.dataset.verify) { await fetchJSON('/api/verify/start', {method:'POST', body: JSON.stringify({rel: b.dataset.verify})}); }
    });
    on($('#b_export_settings'), 'click', () => window.open('/api/settings/export','_blank'));
    on($('#b_download_logs'), 'click', () => window.open('/api/logs/download','_blank'));
    on($('#b_upload'), 'change', async (ev) => {
      const f = ev.target.files[0]; if(!f) return;
      const fd = new FormData(); fd.append('file', f);
      const r = await fetch('/api/backups/upload', {method:'POST', body: fd}).then(r=>r.json());
      if (!r.ok) { alert('Upload failed: '+(r.error||'')); }
      else { alert('Uploaded: '+r.rel); await loadBackups(); }
    });
    loadBackups();

    // Jobs config
    async function loadJobsCfg() {
      const cfg = await fetchJSON('/api/jobs/config');
      $('#j_max').value = cfg.max_concurrent || 1;
      $('#j_bw').value = cfg.default_bwlimit_kbps || 0;
    }
    on($('#j_save'), 'click', async () => {
      const body = {max_concurrent: parseInt(val('j_max')||'1',10), default_bwlimit_kbps: parseInt(val('j_bw')||'0',10)};
      await fetchJSON('/api/jobs/config', {method:'POST', body: JSON.stringify(body)});
      alert('Saved.');
    });
    loadJobsCfg();

    // System update (apt)
    on($('#sys_apt'), 'click', async () => {
      $('#sys_log').textContent = 'Running apt update/upgrade...\n';
      try {
        const r = await fetchJSON('/api/system/apt_upgrade', {method:'POST'});
        if (!r.ok) { $('#sys_log').textContent += 'Error: '+(r.error||r.output||'')+'\n'; }
        else { $('#sys_log').textContent += r.output + '\n'; }
      } catch (e) { $('#sys_log').textContent += 'Error: '+e+'\n'; }
    });

  });
})();

// Copy-to-clipboard for code blocks (optional)
function copyCodeBlocks(){
  document.querySelectorAll('pre.code').forEach(pre => {
    if (pre.querySelector('.copy-btn')) return;
    const btn = document.createElement('button');
    btn.textContent = 'Copy';
    btn.className = 'small secondary copy-btn';
    btn.style.cssText = 'position:absolute;right:10px;top:10px';
    const wrap = document.createElement('div');
    wrap.style.position = 'relative';
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    wrap.appendChild(btn);
    btn.addEventListener('click', () => {
      const text = pre.innerText;
      navigator.clipboard.writeText(text).then(()=>{
        btn.textContent = 'Copied';
        setTimeout(()=>btn.textContent='Copy', 1200);
      });
    });
  });
}
document.addEventListener('DOMContentLoaded', copyCodeBlocks);

// ---------- Generic modal picker ----------
function openPicker(kind, opts){
  // kind: 'ssh' | 'local' | 'mount'
  // opts: {host, port, username, password, name, startPath, onSelect(path)}
  const modal = document.getElementById('picker-modal');
  const tbody = document.querySelector('#picker-table tbody');
  const pathEl = document.getElementById('picker-path');
  let cwd = opts.startPath || '/';
  let lastItems = [];

  async function load(path){
    cwd = path || '/';
    pathEl.textContent = cwd;
    tbody.innerHTML = '';
    let resp;
    if (kind === 'ssh'){
      resp = await fetch('/api/ssh/listdir', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({host: opts.host, port: opts.port||22, username: opts.username, password: opts.password, path: cwd})}).then(r=>r.json());
    } else if (kind === 'local'){
      resp = await fetch('/api/local/listdir?path='+encodeURIComponent(cwd)).then(r=>r.json());
    } else if (kind === 'mount'){
      resp = await fetch('/api/mounts/listdir', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name: opts.name, path: cwd})}).then(r=>r.json());
    }
    if (!resp.ok){
      alert('Browse failed: ' + (resp.error||'')); return;
    }
    lastItems = resp.items || [];
    // Parent row
    const up = document.createElement('tr'); up.innerHTML = '<td>..</td><td>dir</td><td></td>'; up.dataset.up='1';
    tbody.appendChild(up);
    lastItems.forEach(it => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${it.name}</td><td>${it.dir?'dir':'file'}</td><td>${it.dir?'':it.size||''}</td>`;
      tr.dataset.name = it.name;
      tr.dataset.dir = it.dir ? '1':'0';
      tbody.appendChild(tr);
    });
  }

  function joinPath(a,b){
    if (!a || a === '/') return '/' + (b||'');
    return (a.replace(/\/+$/,'') + '/' + (b||'')).replace(/\/+/g,'/');
  }

  let selected = null;
  tbody?.addEventListener('click', (ev)=>{
    const tr = ev.target.closest('tr'); if(!tr) return;
    $$('tr.sel', tbody).forEach(x=>x.classList.remove('sel'));
    tr.classList.add('sel');
    selected = tr;
    if (tr.dataset.up === '1'){
      const parent = cwd.replace(/\/+$/,'').replace(/\/[^\/]+\/?$/,'') || '/';
      load(parent);
    } else if (tr.dataset.dir === '1'){
      load(joinPath(cwd, tr.dataset.name));
    }
  });
  document.getElementById('picker-up').onclick = ()=>{
    const parent = cwd.replace(/\/+$/,'').replace(/\/[^\/]+\/?$/,'') || '/';
    load(parent);
  };
  document.getElementById('picker-select').onclick = ()=>{
    const p = cwd;
    modal.classList.add('hidden');
    opts.onSelect && opts.onSelect(p);
  };
  document.getElementById('picker-close').onclick = ()=> modal.classList.add('hidden');
  modal.classList.remove('hidden');
  load(cwd);
}

// Backup: pick local folder
document.addEventListener('DOMContentLoaded', () => {
  const lp = document.getElementById('b_pick_local');
  if (lp) lp.addEventListener('click', () => {
    openPicker('local', {startPath: '/config', onSelect: (p)=>{ document.getElementById('b_src').value = p; }});
  });
  const mp = document.getElementById('b_pick_mount');
  if (mp) mp.addEventListener('click', async () => {
    // Ask for mount name
    const name = prompt('Enter saved mount name'); if(!name) return;
    openPicker('mount', {name, startPath: '/', onSelect: (p)=>{ document.getElementById('b_src').value = p; }});
  });
});

// Mounts: Connect & pick share/export
document.addEventListener('DOMContentLoaded', () => {
  const btnConn = document.getElementById('m_connect');
  const btnPick = document.getElementById('m_pick_share');
  if (btnConn) btnConn.addEventListener('click', async () => {
    const type = document.getElementById('m_type').value;
    const host = document.getElementById('m_host').value.trim();
    if (!host) return alert('Enter host first');
    if (type === 'smb'){
      const username = document.getElementById('m_user').value;
      const password = document.getElementById('m_pass').value;
      const r = await fetch('/api/smb/shares', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({host, username, password})}).then(r=>r.json());
      if (!r.ok) return alert('SMB query failed: ' + (r.error||''));
      window._lastShares = r.shares || [];
      alert('Found shares: ' + (window._lastShares.join(', ')||'(none)'));
    } else {
      const r = await fetch('/api/nfs/exports', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({host})}).then(r=>r.json());
      if (!r.ok) return alert('NFS query failed: ' + (r.error||''));
      window._lastShares = r.exports || [];
      alert('Found exports: ' + (window._lastShares.join(', ')||'(none)'));
    }
  });
  if (btnPick) btnPick.addEventListener('click', () => {
    const list = window._lastShares || [];
    if (!list.length) return alert('Click Connect first to load shares/exports');
    const choice = prompt('Type a share/export exactly as shown:\n' + list.join('\n'));
    if (choice) document.getElementById('m_share').value = choice;
  });
});

// ---- Backup form helpers ----
document.addEventListener('DOMContentLoaded', () => {
  async function refreshConnections(){
    const d = await fetch('/api/connections').then(r=>r.json());
    const sel = document.getElementById('b_conn');
    if (!sel) return;
    sel.innerHTML = '<option value="">-- none --</option>';
    (d.connections||[]).forEach(c => {
      const o = document.createElement('option'); o.value = c.name; o.textContent = c.name;
      o.dataset.host = c.host; o.dataset.port = c.port; o.dataset.username = c.username; o.dataset.password = c.password || '';
      sel.appendChild(o);
    });
    sel.addEventListener('change', () => {
      const opt = sel.options[sel.selectedIndex];
      if (opt && opt.dataset.host){
        document.getElementById('b_host').value = opt.dataset.host || '';
        document.getElementById('b_user').value = opt.dataset.username || '';
        document.getElementById('b_pass').value = opt.dataset.password || '';
      }
    });
  }
  refreshConnections();

  async function refreshMounts(){
    const d = await fetch('/api/mounts').then(r=>r.json());
    const sel = document.getElementById('dest_mount');
    if (!sel) return;
    sel.innerHTML = '<option value="">-- select mount --</option>';
    (d.mounts||[]).forEach(m => {
      const o = document.createElement('option'); o.value = m.name; o.textContent = m.name + (m.mounted ? ' (mounted)' : ' (not mounted)');
      sel.appendChild(o);
    });
  }
  refreshMounts();

  // Test SSH button
  let testBtn = document.getElementById('b_test');
  if (!testBtn){
    const hostInput = document.getElementById('b_host');
    const userInput = document.getElementById('b_user');
    const passInput = document.getElementById('b_pass');
    const btn = document.createElement('button'); btn.id='b_test'; btn.textContent='Test SSH'; btn.className='secondary'; btn.type='button';
    hostInput.parentElement.appendChild(btn);
    btn.addEventListener('click', async () => {
      const body = {host: hostInput.value, port: 22, username: userInput.value, password: passInput.value};
      const r = await fetch('/api/ssh/test', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)}).then(r=>r.json());
      alert(r.ok ? 'SSH OK' : ('SSH failed: ' + (r.error||'')));
    });
  }

  // Estimate button switch by mode
  const est = document.getElementById('b_estimate');
  const modeSel = document.getElementById('b_mode');
  est?.addEventListener('click', async () => {
    const mode = modeSel.value;
    if (mode === 'rsync'){
      const body = {host: document.getElementById('b_host').value, port:22, username: document.getElementById('b_user').value, password: document.getElementById('b_pass').value, path: document.getElementById('b_src').value || '/'};
      const r = await fetch('/api/estimate/ssh_size', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)}).then(r=>r.json());
      alert(r.ok ? ('Estimated ' + r.bytes + ' bytes') : ('Failed: ' + (r.error||'')));
    } else if (mode === 'copy_mount'){
      // mount estimate via server existing endpoint
      const name = prompt('Mount name to estimate?');
      if (!name) return;
      const p = document.getElementById('b_src').value || '/';
      const r = await fetch('/api/estimate/mount_size?name='+encodeURIComponent(name)+'&path='+encodeURIComponent(p)).then(r=>r.json());
      alert(r.ok ? ('Estimated ' + r.bytes + ' bytes') : ('Failed: ' + (r.error||'')));
    } else { // local
      const p = document.getElementById('b_src').value || '/config';
      const r = await fetch('/api/estimate/local_size?path='+encodeURIComponent(p)).then(r=>r.json());
      alert(r.ok ? ('Estimated ' + r.bytes + ' bytes') : ('Failed: ' + (r.error||'')));
    }
  });

  // Include destination fields in start body
  const startBtn = document.getElementById('b_start');
  startBtn?.addEventListener('click', () => {
    // overwritten handler above already builds body; this ensures dest fields are appended
  }, {once:true});

  // Override existing start handler to include destination
  const origStart = document.getElementById('b_start');
  if (origStart){
    origStart.addEventListener('click', async (ev) => {
      ev.stopImmediatePropagation();
      const mode = document.getElementById('b_mode').value;
      const bwMB = parseFloat(document.getElementById('b_bwlimit')?.value || '0'); const bwKB = isFinite(bwMB)? Math.round(bwMB*1024):0;
      const label = document.getElementById('b_label').value.trim();
      const dest_type = document.getElementById('dest_type').value;
      const dest_mount = document.getElementById('dest_mount').value;
      const dest_subdir = document.getElementById('dest_subdir').value.trim();
      let body = {mode, label, bwlimit_kbps: bwKB, dest_type, dest_mount_name: dest_mount, dest_subdir};

      if (mode === 'rsync'){
        body.host = document.getElementById('b_host').value; body.port = 22;
        body.username = document.getElementById('b_user').value; body.password = document.getElementById('b_pass').value;
        body.source_path = document.getElementById('b_src').value || '/';
      } else if (mode === 'copy_local'){
        body.source_path = document.getElementById('b_src').value || '/config';
      } else if (mode === 'copy_mount'){
        // ask for mount name
        const name = prompt('Enter saved mount name to read from'); if (!name){ alert('Mount name required'); return; }
        body.mount_name = name; body.source_path = document.getElementById('b_src').value || '/';
      } else if (mode === 'image'){
        body.host = document.getElementById('b_host').value; body.port = 22;
        body.username = document.getElementById('b_user').value; body.password = document.getElementById('b_pass').value;
        body.device = document.getElementById('b_device').value;
        body.encrypt = (document.getElementById('b_encrypt').value === '1');
        body.passphrase = document.getElementById('b_passphrase').value;
      }

      try{
        const r = await fetch('/api/backup/start', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)}).then(r=>r.json());
        if (!r.ok){ alert('Start failed: '+(r.error||'')); return; }
        logLine('Job started: '+ r.job_id);
      }catch(e){ alert('Start error: '+e); }
    }, {capture:true});
  }
});


// ---- Notifications form ----
document.addEventListener('DOMContentLoaded', async () => {
  async function loadN(){
    const d = await fetch('/api/notify/config').then(r=>r.json());
    document.getElementById('n_enabled').value = d.enabled ? '1':'0';
    document.getElementById('n_url').value = d.url || '';
    document.getElementById('n_token').value = d.token || '';
    document.getElementById('n_priority').value = d.priority || 5;
  }
  on($('#n_save'),'click', async ()=>{
    const body = {enabled: $('#n_enabled').value==='1', url: $('#n_url').value.trim(), token: $('#n_token').value.trim(), priority: parseInt($('#n_priority').value||'5',10)};
    await fetchJSON('/api/notify/config', {method:'POST', body: JSON.stringify(body)});
    alert('Saved.');
  });
  on($('#n_test'),'click', async ()=>{
    const r = await fetchJSON('/api/notify/test', {method:'POST'});
    alert(r.ok ? 'Sent' : ('Failed: '+(r.info||'')));
  });
  loadN();
});


// ---- Schedule wiring ----
document.addEventListener('DOMContentLoaded', () => {
  async function loadSched(){
    const d = await fetch('/api/schedules').then(r=>r.json());
    const tbody = document.querySelector('#sch_table tbody'); if(!tbody) return;
    tbody.innerHTML = '';
    (d.schedules||[]).forEach(e => {
      const tr = document.createElement('tr');
      const nr = e.next_run ? new Date(e.next_run*1000).toLocaleString() : '-';
      tr.innerHTML = `<td>${e.name||''}</td><td>${e.freq||''}</td><td>${e.time||''}</td><td>${nr}</td><td><code>${(e.template&&e.template.mode)||''}</code></td><td>${e.enabled?'Yes':'No'}</td>
        <td>
          <button class="small" data-run="${e.id}">Run now</button>
          <button class="small danger" data-del="${e.id}">Delete</button>
        </td>`;
      tbody.appendChild(tr);
    });
  }
  on($('#sch_add'),'click', async ()=>{
    const e = {
      name: $('#sch_name').value.trim(),
      freq: $('#sch_freq').value,
      time: $('#sch_time').value.trim(),
      dow: $('#sch_freq').value==='weekly' ? parseInt($('#sch_day').value||'0',10) : null,
      dom: $('#sch_freq').value==='monthly' ? parseInt($('#sch_day').value||'1',10) : null,
      enabled: $('#sch_enabled').value==='1',
      template: {
        mode: $('#sch_mode').value,
        label: $('#sch_label').value.trim(),
        bwlimit_kbps: parseInt($('#sch_bw').value||'0',10),
        host: $('#sch_host').value.trim(),
        port: parseInt($('#sch_port').value||'22',10),
        username: $('#sch_user').value.trim(),
        password: $('#sch_pass').value,
        source_path: $('#sch_src').value.trim(),
        device: $('#sch_src').value.trim(),
        mount_name: $('#sch_mount').value.trim(),
        dest_type: $('#sch_dest_type').value,
        dest_mount_name: $('#sch_dest_mount').value.trim(),
        dest_subdir: $('#sch_dest_subdir').value.trim()
      }
    };
    const r = await fetch('/api/schedules', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(e)}).then(r=>r.json());
    if (!r.ok){ alert('Save failed'); return; }
    await loadSched();
  });
  on($('#sch_table'),'click', async (ev)=>{
    const b = ev.target.closest('button'); if(!b) return;
    if (b.dataset.run){ await fetch('/api/schedules/run_now', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id:b.dataset.run})}); }
    if (b.dataset.del){ await fetch('/api/schedules/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id:b.dataset.del})}); }
    await loadSched();
  });
  loadSched();
});

