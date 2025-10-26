/**
 * Jarvis Prime Backup Module - Frontend
 * Manages backup operations, server configuration, and restore functionality
 */

(function() {
  'use strict';

  // Use global API helper from app.js
  const API = window.API || ((path) => path);
  const toast = window.showToast || ((msg, type) => console.log(`[${type}] ${msg}`));

  // State management
  const backupState = {
    sourceServers: [],
    destinationServers: [],
    jobs: [],
    archives: [],
    currentServerType: 'source',
    currentRestoreBackup: null,
    currentJobId: null
  };

  /* =============== UTILITY FUNCTIONS =============== */
  
  async function backupFetch(url, options = {}) {
    try {
      const response = await fetch(API(url), {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          ...options.headers
        }
      });
      
      if (!response.ok) {
        const text = await response.text().catch(() => '');
        throw new Error(`${response.status}: ${text}`);
      }
      
      const contentType = response.headers.get('content-type') || '';
      return contentType.includes('application/json') ? response.json() : response.text();
    } catch (error) {
      console.error('[backup] API Error:', error);
      throw error;
    }
  }

  function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
  }

  function formatDate(timestamp) {
    if (!timestamp) return 'N/A';
    try {
      const date = new Date(timestamp * 1000);
      return date.toLocaleString();
    } catch {
      return 'Invalid date';
    }
  }

  /* =============== SERVER MODAL =============== */

  window.backupOpenServerModal = function(type) {
    backupState.currentServerType = type;
    document.getElementById('backup-server-type').value = type;
    document.getElementById('backup-server-modal-title').textContent = 
      type === 'source' ? 'Add Source Server' : 'Add Destination Server';
    document.getElementById('backup-server-modal').style.display = 'flex';
    backupUpdateConnectionFields();
  };

  window.backupCloseServerModal = function() {
    document.getElementById('backup-server-modal').style.display = 'none';
    document.getElementById('backup-server-form').reset();
  };

  window.backupUpdateConnectionFields = function() {
    const type = document.getElementById('backup-connection-type').value;
    document.getElementById('backup-ssh-fields').style.display = type === 'ssh' ? 'block' : 'none';
    document.getElementById('backup-smb-fields').style.display = type === 'smb' ? 'block' : 'none';
    document.getElementById('backup-nfs-fields').style.display = type === 'nfs' ? 'block' : 'none';
  };

  window.backupTestConnection = async function() {
    const type = document.getElementById('backup-connection-type').value;
    const config = { type };
    
    try {
      if (type === 'ssh') {
        config.host = document.getElementById('backup-ssh-host').value;
        config.port = parseInt(document.getElementById('backup-ssh-port').value);
        config.username = document.getElementById('backup-ssh-username').value;
        config.password = document.getElementById('backup-ssh-password').value;
      } else if (type === 'smb') {
        config.host = document.getElementById('backup-smb-host').value;
        config.share = document.getElementById('backup-smb-share').value;
        config.username = document.getElementById('backup-smb-username').value;
        config.password = document.getElementById('backup-smb-password').value;
      } else if (type === 'nfs') {
        config.host = document.getElementById('backup-nfs-host').value;
        config.export_path = document.getElementById('backup-nfs-export').value;
      }

      if (!config.host) {
        toast('Please fill in hostname/IP', 'error');
        return;
      }

      toast('Testing connection...', 'info');
      const result = await backupFetch('api/backup/test-connection', {
        method: 'POST',
        body: JSON.stringify(config)
      });
      
      if (result.success) {
        toast('✅ Connection successful!', 'success');
      } else {
        toast('❌ Connection failed: ' + (result.error || 'Unknown error'), 'error');
      }
    } catch (error) {
      toast('❌ Connection test failed: ' + error.message, 'error');
    }
  };

  window.backupSaveServer = async function(event) {
    event.preventDefault();
    
    const type = document.getElementById('backup-connection-type').value;
    const serverType = document.getElementById('backup-server-type').value;
    const name = document.getElementById('backup-server-name').value;
    
    const server = {
      name,
      type,
      server_type: serverType
    };
    
    try {
      if (type === 'ssh') {
        server.host = document.getElementById('backup-ssh-host').value;
        server.port = parseInt(document.getElementById('backup-ssh-port').value);
        server.username = document.getElementById('backup-ssh-username').value;
        server.password = document.getElementById('backup-ssh-password').value;
      } else if (type === 'smb') {
        server.host = document.getElementById('backup-smb-host').value;
        server.share = document.getElementById('backup-smb-share').value;
        server.username = document.getElementById('backup-smb-username').value;
        server.password = document.getElementById('backup-smb-password').value;
      } else if (type === 'nfs') {
        server.host = document.getElementById('backup-nfs-host').value;
        server.export_path = document.getElementById('backup-nfs-export').value;
      }

      const result = await backupFetch('api/backup/servers', {
        method: 'POST',
        body: JSON.stringify(server)
      });
      
      toast('✅ Server saved successfully', 'success');
      backupCloseServerModal();
      await backupLoadServers();
    } catch (error) {
      toast('❌ Failed to save server: ' + error.message, 'error');
    }
  };

  /* =============== JOB MODAL =============== */

  window.backupOpenJobModal = function() {
    document.getElementById('backup-job-modal').style.display = 'flex';
    backupPopulateServerDropdowns();
  };

  window.backupCloseJobModal = function() {
    document.getElementById('backup-job-modal').style.display = 'none';
    document.getElementById('backup-job-form').reset();
  };

  function backupPopulateServerDropdowns() {
    const sourceSelect = document.getElementById('backup-job-source');
    const destSelect = document.getElementById('backup-job-destination');
    const restoreSelect = document.getElementById('backup-restore-destination');
    
    // Clear existing options (except first)
    sourceSelect.innerHTML = '<option value="">Select source server...</option>';
    destSelect.innerHTML = '<option value="">Select destination server...</option>';
    if (restoreSelect) {
      restoreSelect.innerHTML = '<option value="">Select destination server...</option>';
    }
    
    // Populate source servers
    backupState.sourceServers.forEach(server => {
      const option = document.createElement('option');
      option.value = server.id;
      option.textContent = `${server.name} (${server.host})`;
      sourceSelect.appendChild(option);
    });
    
    // Populate destination servers
    backupState.destinationServers.forEach(server => {
      const option = document.createElement('option');
      option.value = server.id;
      option.textContent = `${server.name} (${server.host})`;
      destSelect.appendChild(option);
      
      if (restoreSelect) {
        const restoreOption = document.createElement('option');
        restoreOption.value = server.id;
        restoreOption.textContent = `${server.name} (${server.host})`;
        restoreSelect.appendChild(restoreOption);
      }
    });
  }

  window.backupCreateJob = async function(event) {
    event.preventDefault();
    
    const job = {
      name: document.getElementById('backup-job-name').value,
      source_server_id: document.getElementById('backup-job-source').value,
      paths: document.getElementById('backup-job-paths').value.split('\n').filter(p => p.trim()),
      destination_server_id: document.getElementById('backup-job-destination').value,
      destination_path: document.getElementById('backup-job-dest-path').value,
      backup_type: document.getElementById('backup-job-type').value,
      compress: document.getElementById('backup-job-compress').checked,
      stop_containers: document.getElementById('backup-job-stop-containers').checked,
      containers: document.getElementById('backup-job-containers').value.split(',').map(c => c.trim()).filter(c => c),
      schedule: document.getElementById('backup-job-schedule').value,
      retention_days: parseInt(document.getElementById('backup-job-retention').value)
    };
    
    try {
      await backupFetch('api/backup/jobs', {
        method: 'POST',
        body: JSON.stringify(job)
      });
      
      toast('✅ Backup job created successfully', 'success');
      backupCloseJobModal();
      await backupLoadJobs();
    } catch (error) {
      toast('❌ Failed to create job: ' + error.message, 'error');
    }
  };

  /* =============== RESTORE MODAL =============== */

  window.backupOpenRestoreModal = function(backup) {
    backupState.currentRestoreBackup = backup;
    document.getElementById('backup-restore-name').textContent = backup.name || backup.id;
    document.getElementById('backup-restore-modal').style.display = 'flex';
    backupPopulateServerDropdowns();
  };

  window.backupCloseRestoreModal = function() {
    document.getElementById('backup-restore-modal').style.display = 'none';
    backupState.currentRestoreBackup = null;
  };

  window.backupConfirmRestore = async function() {
    if (!confirm('Are you sure you want to restore this backup? This will overwrite existing files.')) {
      return;
    }
    
    const backup = backupState.currentRestoreBackup;
    if (!backup) {
      toast('❌ No backup selected', 'error');
      return;
    }
    
    const restore = {
      backup_id: backup.id,
      destination_server_id: document.getElementById('backup-restore-destination').value,
      restore_path: document.getElementById('backup-restore-path').value,
      overwrite: document.getElementById('backup-restore-overwrite').checked
    };
    
    try {
      await backupFetch('api/backup/restore', {
        method: 'POST',
        body: JSON.stringify(restore)
      });
      
      toast('✅ Restore initiated successfully', 'info');
      backupCloseRestoreModal();
    } catch (error) {
      toast('❌ Restore failed: ' + error.message, 'error');
    }
  };

  /* =============== JOB DETAILS MODAL =============== */

  window.backupOpenJobDetailsModal = async function(jobId) {
    backupState.currentJobId = jobId;
    document.getElementById('backup-job-details-modal').style.display = 'flex';
    
    try {
      const job = await backupFetch(`api/backup/jobs/${jobId}`);
      renderJobDetails(job);
    } catch (error) {
      toast('❌ Failed to load job details: ' + error.message, 'error');
    }
  };

  window.backupCloseJobDetailsModal = function() {
    document.getElementById('backup-job-details-modal').style.display = 'none';
    backupState.currentJobId = null;
  };

  window.backupRunJobFromDetails = async function() {
    if (!backupState.currentJobId) return;
    
    try {
      await backupFetch(`api/backup/jobs/${backupState.currentJobId}/run`, {
        method: 'POST'
      });
      
      toast('✅ Backup job started', 'info');
      backupCloseJobDetailsModal();
      await backupLoadJobs();
    } catch (error) {
      toast('❌ Failed to run job: ' + error.message, 'error');
    }
  };

  function renderJobDetails(job) {
    const content = document.getElementById('backup-job-details-content');
    content.innerHTML = `
      <div class="form-group">
        <label class="form-label">Job Name</label>
        <div style="padding: 12px; background: var(--surface-secondary); border-radius: 6px;">${job.name}</div>
      </div>
      
      <div class="form-group">
        <label class="form-label">Source Server</label>
        <div style="padding: 12px; background: var(--surface-secondary); border-radius: 6px;">${job.source_server}</div>
      </div>
      
      <div class="form-group">
        <label class="form-label">Paths</label>
        <div style="padding: 12px; background: var(--surface-secondary); border-radius: 6px;">${job.paths.join('<br>')}</div>
      </div>
      
      <div class="form-group">
        <label class="form-label">Schedule</label>
        <div style="padding: 12px; background: var(--surface-secondary); border-radius: 6px;">${job.schedule}</div>
      </div>
      
      <div class="form-group">
        <label class="form-label">Status</label>
        <div style="padding: 12px; background: var(--surface-secondary); border-radius: 6px;">${job.enabled ? '✅ Enabled' : '❌ Disabled'}</div>
      </div>
    `;
  }

  /* =============== DATA LOADING =============== */

  async function backupLoadServers() {
    try {
      const data = await backupFetch('api/backup/servers');
      backupState.sourceServers = data.source_servers || [];
      backupState.destinationServers = data.destination_servers || [];
      
      renderServerLists();
      updateStatistics();
    } catch (error) {
      console.error('[backup] Failed to load servers:', error);
      toast('Failed to load servers', 'error');
    }
  }

  async function backupLoadJobs() {
    try {
      const data = await backupFetch('api/backup/jobs');
      backupState.jobs = data.jobs || [];
      
      renderJobsList();
      updateStatistics();
    } catch (error) {
      console.error('[backup] Failed to load jobs:', error);
      toast('Failed to load jobs', 'error');
    }
  }

  window.backupRefreshArchives = async function() {
    try {
      const data = await backupFetch('api/backup/archives');
      backupState.archives = data.archives || [];
      
      renderArchivesList();
      updateStatistics();
    } catch (error) {
      console.error('[backup] Failed to load archives:', error);
      toast('Failed to load archives', 'error');
    }
  };

  window.backupRefreshAll = async function() {
    toast('Refreshing backup data...', 'info');
    await Promise.all([
      backupLoadServers(),
      backupLoadJobs(),
      backupRefreshArchives()
    ]);
    toast('✅ Backup data refreshed', 'success');
  };

  /* =============== RENDERING =============== */

  function renderServerLists() {
    renderServerList('backup-source-servers', backupState.sourceServers, 'source');
    renderServerList('backup-destination-servers', backupState.destinationServers, 'destination');
  }

  function renderServerList(containerId, servers, type) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    if (servers.length === 0) {
      container.innerHTML = `
        <div class="text-center text-muted" style="padding: 32px;">
          No ${type} servers configured<br>
          <small>Click "Add ${type === 'source' ? 'Source' : 'Destination'}" to get started</small>
        </div>
      `;
      return;
    }
    
    container.innerHTML = servers.map(server => `
      <div class="server-card" style="padding: 16px; background: var(--surface-secondary); border-radius: 8px; border: 1px solid var(--border-color);">
        <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 8px;">
          <div>
            <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 4px;">${server.name}</div>
            <div style="font-size: 13px; color: var(--text-muted);">
              <span style="display: inline-block; padding: 2px 8px; background: rgba(14, 165, 233, 0.12); color: #0ea5e9; border-radius: 4px; margin-right: 8px;">${server.type.toUpperCase()}</span>
              ${server.host}${server.port ? ':' + server.port : ''}
            </div>
          </div>
          <button class="btn danger btn-sm" onclick="backupDeleteServer('${server.id}')" style="padding: 4px 8px;">Delete</button>
        </div>
      </div>
    `).join('');
  }

  function renderJobsList() {
    const container = document.getElementById('backup-jobs-list');
    if (!container) return;
    
    if (backupState.jobs.length === 0) {
      container.innerHTML = `
        <div class="text-center text-muted" style="padding: 32px;">
          No backup jobs configured<br>
          <small>Create a job to schedule automated backups</small>
        </div>
      `;
      return;
    }
    
    container.innerHTML = backupState.jobs.map(job => `
      <div class="job-card" style="padding: 16px; background: var(--surface-secondary); border-radius: 8px; border: 1px solid var(--border-color); margin-bottom: 12px;">
        <div style="display: flex; justify-content: space-between; align-items: start;">
          <div style="flex: 1;">
            <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 8px;">${job.name}</div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; font-size: 13px; color: var(--text-muted);">
              <div><strong>Schedule:</strong> ${job.schedule}</div>
              <div><strong>Last Run:</strong> ${job.last_run ? formatDate(job.last_run) : 'Never'}</div>
              <div><strong>Status:</strong> ${job.enabled ? '<span style="color: #10b981;">✅ Active</span>' : '<span style="color: #ef4444;">❌ Disabled</span>'}</div>
            </div>
          </div>
          <div style="display: flex; gap: 8px;">
            <button class="btn primary btn-sm" onclick="backupRunJob('${job.id}')">Run Now</button>
            <button class="btn btn-sm" onclick="backupOpenJobDetailsModal('${job.id}')">Details</button>
            <button class="btn danger btn-sm" onclick="backupDeleteJob('${job.id}')">Delete</button>
          </div>
        </div>
      </div>
    `).join('');
  }

  function renderArchivesList() {
    const tbody = document.getElementById('backup-archives-list');
    if (!tbody) return;
    
    if (backupState.archives.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No backups available</td></tr>';
      return;
    }
    
    tbody.innerHTML = backupState.archives.map(archive => `
      <tr>
        <td>${archive.name || archive.id}</td>
        <td>${archive.job_name || 'Manual'}</td>
        <td>${archive.source_server || 'N/A'}</td>
        <td>${formatBytes(archive.size || 0)}</td>
        <td>${formatDate(archive.timestamp)}</td>
        <td>
          <span style="display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; ${
            archive.status === 'completed' ? 'background: rgba(16, 185, 129, 0.12); color: #10b981;' : 'background: rgba(239, 68, 68, 0.12); color: #ef4444;'
          }">
            ${archive.status || 'Unknown'}
          </span>
        </td>
        <td>
          <button class="btn btn-sm" onclick='backupOpenRestoreModal(${JSON.stringify(archive).replace(/'/g, "\\'")} )' style="padding: 4px 12px;">Restore</button>
          <button class="btn danger btn-sm" onclick="backupDeleteArchive('${archive.id}')" style="padding: 4px 12px; margin-left: 4px;">Delete</button>
        </td>
      </tr>
    `).join('');
  }

  function updateStatistics() {
    // Update metrics
    document.getElementById('backup-stat-total').textContent = backupState.archives.length;
    document.getElementById('backup-stat-jobs').textContent = backupState.jobs.length;
    
    // Calculate total size
    const totalSize = backupState.archives.reduce((sum, archive) => sum + (archive.size || 0), 0);
    document.getElementById('backup-stat-size').textContent = formatBytes(totalSize);
    
    // Count today's successes and failures
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const todayTimestamp = today.getTime() / 1000;
    
    const todayArchives = backupState.archives.filter(a => (a.timestamp || 0) >= todayTimestamp);
    const successCount = todayArchives.filter(a => a.status === 'completed').length;
    const failedCount = todayArchives.filter(a => a.status === 'failed').length;
    
    document.getElementById('backup-stat-success').textContent = successCount;
    document.getElementById('backup-stat-failed').textContent = failedCount;
  }

  /* =============== DELETE OPERATIONS =============== */

  window.backupDeleteServer = async function(serverId) {
    if (!confirm('Delete this server? This cannot be undone.')) return;
    
    try {
      await backupFetch(`api/backup/servers/${serverId}`, { method: 'DELETE' });
      toast('✅ Server deleted', 'success');
      await backupLoadServers();
    } catch (error) {
      toast('❌ Failed to delete server: ' + error.message, 'error');
    }
  };

  window.backupDeleteJob = async function(jobId) {
    if (!confirm('Delete this backup job? This cannot be undone.')) return;
    
    try {
      await backupFetch(`api/backup/jobs/${jobId}`, { method: 'DELETE' });
      toast('✅ Job deleted', 'success');
      await backupLoadJobs();
    } catch (error) {
      toast('❌ Failed to delete job: ' + error.message, 'error');
    }
  };

  window.backupRunJob = async function(jobId) {
    try {
      await backupFetch(`api/backup/jobs/${jobId}/run`, { method: 'POST' });
      toast('✅ Backup job started', 'info');
      setTimeout(() => backupLoadJobs(), 2000);
    } catch (error) {
      toast('❌ Failed to run job: ' + error.message, 'error');
    }
  };

  window.backupDeleteArchive = async function(archiveId) {
    if (!confirm('Delete this backup? This cannot be undone.')) return;
    
    try {
      await backupFetch(`api/backup/archives/${archiveId}`, { method: 'DELETE' });
      toast('✅ Backup deleted', 'success');
      await backupRefreshArchives();
    } catch (error) {
      toast('❌ Failed to delete backup: ' + error.message, 'error');
    }
  };

  /* =============== SEARCH FUNCTIONALITY =============== */

  const searchInput = document.getElementById('backup-search');
  if (searchInput) {
    searchInput.addEventListener('input', function() {
      const searchTerm = this.value.toLowerCase();
      const rows = document.querySelectorAll('#backup-archives-list tr');
      
      rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(searchTerm) ? '' : 'none';
      });
    });
  }

  /* =============== CONTAINER TOGGLE =============== */

  const stopContainersCheckbox = document.getElementById('backup-job-stop-containers');
  if (stopContainersCheckbox) {
    stopContainersCheckbox.addEventListener('change', function() {
      const field = document.getElementById('backup-container-field');
      if (field) {
        field.style.display = this.checked ? 'block' : 'none';
      }
    });
  }

  /* =============== INITIALIZATION =============== */

  window.backupModule = {
    init: async function() {
      console.log('[backup] Initializing module...');
      await backupRefreshAll();
      console.log('[backup] Module initialized');
    }
  };

  // Auto-initialize when backup tab is activated
  if (typeof window !== 'undefined') {
    console.log('[backup] Module loaded and ready');
  }

})();
