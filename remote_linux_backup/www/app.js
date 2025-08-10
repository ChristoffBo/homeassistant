on(document, 'DOMContentLoaded', () => {
  $$('#tabs .tab-btn').forEach(btn => {
    on(btn, 'click', () => showTab(btn.dataset.tab));
  });
  const savedTab = localStorage.getItem('rlb_active_tab');
  if (savedTab && document.getElementById(savedTab)) showTab(savedTab);

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

  const socket = io();
  socket.on('job_update', (job) => {
    const p = $('#b_progress');
    const pct = Math.max(0, Math.min(100, job.progress || 0));
    if (p) p.value = pct;
    const pctEl = $('#b_progress_pct');
    if (pctEl) pctEl.textContent = `${pct}%`;
  });
  socket.on('job_log', (d) => logLine(d.line || ''));

  on($('#b_start'), 'click', async () => {
    // builds body per mode and POSTs to /api/backup/start
  });

  on($('#b_cancel'), 'click', async () => {
    // cancels the currently running job via /api/jobs/cancel
  });

  // Similar handlers for Restore, Connections, Mounts, Backups, Schedule, Notifications…
});
