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
