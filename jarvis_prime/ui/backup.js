/**
 * Jarvis Prime Backup Module - WITH FILE EXPLORER
 * Click and select folders from source/destination servers
 */

(function() {
  'use strict';

  const API = window.API || ((path) => path);
  const toast = window.showToast || ((msg, type) => console.log(`[${type}] ${msg}`));

  // State
  const backupState = {
    sourceServers: [],
    destinationServers: [],
    jobs: [],
    archives: [],
    currentServerType: 'source',
    selectedPaths: [],
    selectedDestination: '',
    currentBrowseServer: null,
    currentBrowsePath: '/',
    explorerSide: 'source' // 'source' or 'destination'
  };

  /* =============== UTILITY =============== */
  
  async function backupFetch(url, options = {}) {
    try {
      const response = await fetch(API(url), {
        ...options,
        headers: { 'Content-Type': 'application/json', ...options.headers }
      });
      
      if (!response.ok) {
        const text = await response.text().catch(() => '');
        throw new Error(`${response.status}: ${text}`);
      }
      
      return response.headers.get('content-type')?.includes('application/json') 
        ? response.json() 
        : response.text();
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
      return new Date(timestamp * 1000).toLocaleString();
    } catch {
      return 'Invalid date';
    }
  }

  /* =============== SERVER MODALS =============== */

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
    
    const server = { name, type, server_type: serverType };
    
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

      await backupFetch('api/backup/servers', {
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

  /* =============== FILE EXPLORER MODAL =============== */

  window.backupOpenFileExplorer = function(side) {
    backupState.explorerSide = side;
    const servers = side === 'source' ? backupState.sourceServers : backupState.destinationServers;
    
    if (servers.length === 0) {
      toast(`❌ No ${side} servers configured`, 'error');
      return;
    }
    
    // Populate server dropdown
    const select = document.getElementById('backup-explorer-server');
    select.innerHTML = '<option value="">Select server...</option>';
    servers.forEach(server => {
      const option = document.createElement('option');
      option.value = server.id;
      option.textContent = `${server.name} (${server.host})`;
      select.appendChild(option);
    });
    
    document.getElementById('backup-explorer-modal-title').textContent = 
      side === 'source' ? 'Select Source Folders' : 'Select Destination Folder';
    document.getElementById('backup-explorer-modal').style.display = 'flex';
    document.getElementById('backup-explorer-list').innerHTML = '<div class="text-muted">Select a server to browse</div>';
  };

  window.backupCloseFileExplorer = function() {
    document.getElementById('backup-explorer-modal').style.display = 'none';
  };

  window.backupExplorerServerChanged = async function() {
    const serverId = document.getElementById('backup-explorer-server').value;
    if (!serverId) return;
    
    const allServers = [...backupState.sourceServers, ...backupState.destinationServers];
    backupState.currentBrowseServer = allServers.find(s => s.id === serverId);
    backupState.currentBrowsePath = '/';
    
    await backupBrowseDirectory('/');
  };

  async function backupBrowseDirectory(path) {
    if (!backupState.currentBrowseServer) return;
    
    try {
      document.getElementById('backup-explorer-list').innerHTML = '<div class="text-muted">Loading...</div>';
      
      const result = await backupFetch('api/backup/browse', {
        method: 'POST',
        body: JSON.stringify({
          server_id: backupState.currentBrowseServer.id,
          server_config: backupState.currentBrowseServer,
          path: path
        })
      });
      
      if (!result.success) {
        throw new Error(result.error || 'Browse failed');
      }
      
      backupState.currentBrowsePath = path;
      document.getElementById('backup-current-path').textContent = path;
      
      renderFileExplorer(result.files || []);
    } catch (error) {
      toast('❌ Failed to browse: ' + error.message, 'error');
      document.getElementById('backup-explorer-list').innerHTML = '<div class="text-muted">Failed to load directory</div>';
    }
  }

  function renderFileExplorer(files) {
    const container = document.getElementById('backup-explorer-list');
    
    if (files.length === 0) {
      container.innerHTML = '<div class="text-muted">Empty directory</div>';
      return;
    }
    
    // Sort: directories first, then files
    files.sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    
    let html = '<table style="width: 100%; border-collapse: collapse;">';
    html += '<thead><tr style="border-bottom: 1px solid var(--border-color);"><th style="text-align: left; padding: 8px;">Name</th><th style="text-align: right; padding: 8px;">Size</th><th style="text-align: right; padding: 8px;">Modified</th><th style="width: 80px;"></th></tr></thead><tbody>';
    
    // Parent directory
    if (backupState.currentBrowsePath !== '/') {
      const parent = backupState.currentBrowsePath.split('/').slice(0, -1).join('/') || '/';
      html += `
        <tr style="cursor: pointer; border-bottom: 1px solid rgba(255,255,255,0.05);" onclick="backupBrowseDirectory('${parent}')">
          <td style="padding: 12px;">📁 ..</td>
          <td></td>
          <td></td>
          <td></td>
        </tr>
      `;
    }
    
    files.forEach(file => {
      const fullPath = backupState.currentBrowsePath === '/' 
        ? `/${file.name}` 
        : `${backupState.currentBrowsePath}/${file.name}`;
      
      const icon = file.is_dir ? '📁' : '📄';
      const size = file.is_dir ? '' : formatBytes(file.size);
      const modified = file.mtime ? new Date(file.mtime * 1000).toLocaleString() : '';
      const isSelected = backupState.selectedPaths.includes(fullPath);
      
      html += `
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); ${isSelected ? 'background: rgba(14, 165, 233, 0.1);' : ''}">
          <td style="padding: 12px; cursor: pointer;" onclick="${file.is_dir ? `backupBrowseDirectory('${fullPath}')` : ''}">
            ${icon} ${file.name}
          </td>
          <td style="padding: 12px; text-align: right; color: var(--text-muted);">${size}</td>
          <td style="padding: 12px; text-align: right; color: var(--text-muted);">${modified}</td>
          <td style="padding: 12px; text-align: center;">
            ${file.is_dir ? `
              <button class="btn btn-sm" onclick="event.stopPropagation(); backupToggleSelection('${fullPath}')" style="padding: 4px 8px;">
                ${isSelected ? '✓ Selected' : 'Select'}
              </button>
            ` : ''}
          </td>
        </tr>
      `;
    });
    
    html += '</tbody></table>';
    container.innerHTML = html;
  }

  window.backupToggleSelection = function(path) {
    const index = backupState.selectedPaths.indexOf(path);
    if (index > -1) {
      backupState.selectedPaths.splice(index, 1);
    } else {
      if (backupState.explorerSide === 'destination') {
        // Only one destination folder
        backupState.selectedPaths = [path];
      } else {
        backupState.selectedPaths.push(path);
      }
    }
    backupBrowseDirectory(backupState.currentBrowsePath);
  };

  window.backupConfirmSelection = function() {
    if (backupState.explorerSide === 'source') {
      const textarea = document.getElementById('backup-job-paths');
      textarea.value = backupState.selectedPaths.join('\n');
      toast(`✅ Selected ${backupState.selectedPaths.length} folders`, 'success');
    } else {
      const input = document.getElementById('backup-job-dest-path');
      input.value = backupState.selectedPaths[0] || '/backups';
      toast(`✅ Selected destination: ${backupState.selectedPaths[0]}`, 'success');
    }
    backupState.selectedPaths = [];
    backupCloseFileExplorer();
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
    
    sourceSelect.innerHTML = '<option value="">Select source server...</option>';
    destSelect.innerHTML = '<option value="">Select destination server...</option>';
    
    backupState.sourceServers.forEach(server => {
      const option = document.getElementById('option');
      option.value = server.id;
      option.textContent = `${server.name} (${server.host})`;
      sourceSelect.appendChild(option);
    });
    
    backupState.destinationServers.forEach(server => {
      const option = document.createElement('option');
      option.value = server.id;
      option.textContent = `${server.name} (${server.host})`;
      destSelect.appendChild(option);
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
      retention_days: parseInt(document.getElementById('backup-job-retention').value),
      enabled: true
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

  /* =============== DATA LOADING =============== */

  async function backupLoadServers() {
    try {
      const data = await backupFetch('api/backup/servers');
      backupState.sourceServers = data.source_servers || [];
      backupState.destinationServers = data.destination_servers || [];
      
      renderServersList('source');
      renderServersList('destination');
    } catch (error) {
      console.error('[backup] Failed to load servers:', error);
    }
  }

  async function backupLoadJobs() {
    try {
      const data = await backupFetch('api/backup/jobs');
      backupState.jobs = data.jobs || [];
      
      renderJobsList();
      toast('Backup data refreshed', 'success');
    } catch (error) {
      toast('Failed to load jobs', 'error');
      console.error('[backup] Failed to load jobs:', error);
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
    }
  };

  window.backupRefreshAll = async function() {
    toast('Refreshing backup data...', 'info');
    await Promise.all([
      backupLoadServers(),
      backupLoadJobs(),
      backupRefreshArchives()
    ]);
  };

  /* =============== RENDERING =============== */

  function renderServersList(type) {
    const container = document.getElementById(`backup-${type}-servers`);
    if (!container) return;
    
    const servers = type === 'source' ? backupState.sourceServers : backupState.destinationServers;
    
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
    document.getElementById('backup-stat-total').textContent = backupState.archives.length;
    document.getElementById('backup-stat-jobs').textContent = backupState.jobs.length;
    
    const totalSize = backupState.archives.reduce((sum, archive) => sum + (archive.size || 0), 0);
    document.getElementById('backup-stat-size').textContent = formatBytes(totalSize);
    
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

  /* =============== RESTORE MODAL =============== */

  window.backupOpenRestoreModal = function(archive) {
    // TODO: Implement restore modal
    toast('Restore feature coming soon', 'info');
  };

  window.backupCloseRestoreModal = function() {
    document.getElementById('backup-restore-modal').style.display = 'none';
  };

  /* =============== INIT =============== */

  window.backupModule = {
    init: async function() {
      console.log('[backup] Initializing module...');
      await backupRefreshAll();
      console.log('[backup] Module initialized');
    }
  };

  // Container toggle
  const stopContainersCheckbox = document.getElementById('backup-job-stop-containers');
  if (stopContainersCheckbox) {
    stopContainersCheckbox.addEventListener('change', function() {
      const field = document.getElementById('backup-container-field');
      if (field) field.style.display = this.checked ? 'block' : 'none';
    });
  }

  console.log('[backup] Module loaded and ready');

})();
