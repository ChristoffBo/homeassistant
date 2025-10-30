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
    explorerSide: 'source', // 'source' or 'destination'
    restoreSelectedItems: [] // NEW: Track selective restore items
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
        toast('Connection successful!', 'success');
      } else {
        toast('Connection failed: ' + (result.error || 'Unknown error'), 'error');
      }
    } catch (error) {
      toast('Connection test failed: ' + error.message, 'error');
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
      
      toast('Server saved successfully', 'success');
      backupCloseServerModal();
      await backupLoadServers();
    } catch (error) {
      toast('Failed to save server: ' + error.message, 'error');
    }
  };

  /* =============== FILE EXPLORER MODAL =============== */

  window.backupOpenFileExplorer = function(side) {
    backupState.explorerSide = side;
    const servers = side === 'source' ? backupState.sourceServers : backupState.destinationServers;
    
    if (servers.length === 0) {
      toast(`No ${side} servers configured`, 'error');
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
      toast('Failed to browse: ' + error.message, 'error');
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
        <tr style="cursor: pointer; border-bottom: 1px solid rgba(255,255,255,0.05);" data-action="navigate" data-path="${parent}">
          <td style="padding: 12px;">..</td>
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
      
      const icon = file.is_dir ? '' : '';
      const size = file.is_dir ? '' : formatBytes(file.size);
      const modified = file.mtime ? new Date(file.mtime * 1000).toLocaleString() : '';
      const isSelected = backupState.selectedPaths.includes(fullPath);
      
      html += `
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); ${isSelected ? 'background: rgba(14, 165, 233, 0.1);' : ''}">
          <td style="padding: 12px;">
            ${file.is_dir 
              ? `<span style="cursor: pointer; color: #0ea5e9;" data-action="navigate" data-path="${fullPath}">${icon} ${file.name}</span>`
              : `${icon} ${file.name}`
            }
          </td>
          <td style="padding: 12px; text-align: right; color: var(--text-muted);">${size}</td>
          <td style="padding: 12px; text-align: right; color: var(--text-muted);">${modified}</td>
          <td style="padding: 12px; text-align: center;">
            <button class="btn btn-sm" data-action="select" data-path="${fullPath}" data-is-dir="${file.is_dir}" style="padding: 4px 8px;">
              ${isSelected ? 'Selected' : 'Select'}
            </button>
          </td>
        </tr>
      `;
    });
    
    html += '</tbody></table>';
    container.innerHTML = html;
    
    // Add event delegation
    container.onclick = function(e) {
      const target = e.target.closest('[data-action]');
      if (!target) return;
      
      const action = target.getAttribute('data-action');
      const path = target.getAttribute('data-path');
      
      if (action === 'navigate') {
        backupBrowseDirectory(path);
      } else if (action === 'select') {
        const isDir = target.getAttribute('data-is-dir') === 'true';
        backupToggleSelection(path, isDir);
      }
    };
  }

  window.backupToggleSelection = function(path, isDir) {
    const index = backupState.selectedPaths.indexOf(path);
    if (index > -1) {
      backupState.selectedPaths.splice(index, 1);
    } else {
      if (backupState.explorerSide === 'destination' || backupState.explorerSide === 'restore-dest') {
        // Only one destination folder (must be directory)
        if (!isDir) {
          toast('Destination must be a folder, not a file', 'error');
          return;
        }
        backupState.selectedPaths = [path];
      } else {
        // Source can have multiple files/folders
        backupState.selectedPaths.push(path);
      }
    }
    
    // Update display
    backupBrowseDirectory(backupState.currentBrowsePath);
    
    // Show current selection count
    const itemType = isDir ? 'folder' : 'file';
    const count = backupState.selectedPaths.length;
    if (index > -1) {
      toast(`Deselected ${itemType}`, 'info');
    } else {
      toast(`Selected ${itemType} (${count} total)`, 'success');
    }
  };

  window.backupConfirmSelection = function() {
    if (backupState.selectedPaths.length === 0) {
      toast('No items selected', 'error');
      return;
    }

    if (backupState.explorerSide === 'restore-dest' && backupState.selectedPaths.length === 0) {
      toast('Please select a destination folder', 'error');
      return;
    }
    
    if (backupState.explorerSide === 'source') {
      const textarea = backupState.editMode 
        ? document.getElementById('backup-edit-job-paths')
        : document.getElementById('backup-job-paths');
      textarea.value = backupState.selectedPaths.join('\n');
      toast(`Selected ${backupState.selectedPaths.length} items for backup`, 'success');
    } else if (backupState.explorerSide === 'destination') {
      const input = backupState.editMode
        ? document.getElementById('backup-edit-job-dest-path')
        : document.getElementById('backup-job-dest-path');
      input.value = backupState.selectedPaths[0] || '/backups';
      toast(`Destination set to: ${backupState.selectedPaths[0]}`, 'success');
    } else if (backupState.explorerSide === 'restore-dest') {
      document.getElementById('restore-dest-path').value = backupState.selectedPaths[0] || '/';
      toast(`Restore destination set`, 'success');
    } else if (backupState.explorerSide === 'restore-selective') {
      backupState.restoreSelectedItems = backupState.selectedPaths.slice();
      const itemsDiv = document.getElementById('restore-selected-items');
      if (backupState.restoreSelectedItems.length > 0) {
        itemsDiv.innerHTML = backupState.restoreSelectedItems.map(p => `<div>${p}</div>`).join('');
        itemsDiv.style.color = 'var(--text-primary)';
      } else {
        itemsDiv.innerHTML = 'No items selected';
        itemsDiv.style.color = 'var(--text-muted)';
      }
      toast(`Selected ${backupState.restoreSelectedItems.length} items to restore`, 'success');
    }
    
    backupState.selectedPaths = [];
    backupState.editMode = false;
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
      const option = document.createElement('option');
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
      retention_days: parseInt(document.getElementById('backup-job-retention-days').value) || 0,
      retention_count: parseInt(document.getElementById('backup-job-retention-count').value) || 0,
      enabled: true
    };
    
    try {
      await backupFetch('api/backup/jobs', {
        method: 'POST',
        body: JSON.stringify(job)
      });
      
      toast('Backup job created successfully', 'success');
      backupCloseJobModal();
      await backupLoadJobs();
    } catch (error) {
      toast('Failed to create job: ' + error.message, 'error');
    }
  };

  /* =============== DATA LOADING =============== */

  async function backupLoadServers() {
    try {
      const data = await backupFetch('api/backup/servers');
      backupState.sourceServers = data.source_servers || [];
      backupState.destinationServers = data.destination_servers || [];
      backupState.servers = [...backupState.sourceServers, ...backupState.destinationServers];
      
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
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-sm" onclick='backupOpenEditServerModal(${JSON.stringify(server).replace(/'/g, "\\'")} )' style="padding: 4px 8px;">Edit</button>
            <button class="btn danger btn-sm" onclick="backupDeleteServer('${server.id}')" style="padding: 4px 8px;">Delete</button>
          </div>
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
              <div><strong>Status:</strong> ${job.enabled ? '<span style="color: #10b981;">Active</span>' : '<span style="color: #ef4444;">Disabled</span>'}</div>
            </div>
          </div>
          <div style="display: flex; gap: 8px;">
            <button class="btn primary btn-sm" onclick="backupRunJob('${job.id}')">Run Now</button>
            <button class="btn btn-sm" onclick='backupOpenEditJobModal(${JSON.stringify(job).replace(/'/g, "\\'")} )'>Edit</button>
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
    
    tbody.innerHTML = backupState.archives.map((archive, index) => {
      // Get source server name
      const allServers = [...backupState.sourceServers, ...backupState.destinationServers];
      const sourceServer = allServers.find(s => s.id === archive.source_server_id);
      const sourceName = sourceServer ? sourceServer.name : archive.source_server_id || 'Unknown';
      
      // Format date
      const date = archive.created_at ? new Date(archive.created_at).toLocaleString() : 'N/A';
      
      // Format size
      const sizeBytes = (archive.size_mb || 0) * 1024 * 1024;
      const sizeStr = formatBytes(sizeBytes);
      
      return `
        <tr>
          <td>${archive.job_name || archive.id}</td>
          <td>${archive.job_name || 'Manual'}</td>
          <td>${sourceName}</td>
          <td>${sizeStr}</td>
          <td>${date}</td>
          <td>
            <span style="display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; ${
              archive.status === 'completed' ? 'background: rgba(16, 185, 129, 0.12); color: #10b981;' : 'background: rgba(239, 68, 68, 0.12); color: #ef4444;'
            }">
              ${archive.status || 'Unknown'}
            </span>
          </td>
          <td>
            <button class="btn btn-sm restore-btn-${index}" style="padding: 4px 12px;">Restore</button>
            <button class="btn danger btn-sm delete-btn-${index}" style="padding: 4px 12px; margin-left: 4px;">Delete</button>
          </td>
        </tr>
      `;
    }).join('');
    
    // Attach event listeners after rendering
    backupState.archives.forEach((archive, index) => {
      const restoreBtn = document.querySelector(`.restore-btn-${index}`);
      const deleteBtn = document.querySelector(`.delete-btn-${index}`);
      
      if (restoreBtn) {
        restoreBtn.addEventListener('click', () => backupOpenRestoreModal(archive));
      }
      
      if (deleteBtn) {
        deleteBtn.addEventListener('click', () => backupDeleteArchive(archive.id));
      }
    });
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
      toast('Server deleted', 'success');
      await backupLoadServers();
    } catch (error) {
      toast('Failed to delete server: ' + error.message, 'error');
    }
  };

  window.backupDeleteJob = async function(jobId) {
    if (!confirm('Delete this backup job? This cannot be undone.')) return;
    
    try {
      await backupFetch(`api/backup/jobs/${jobId}`, { method: 'DELETE' });
      toast('Job deleted', 'success');
      await backupLoadJobs();
    } catch (error) {
      toast('Failed to delete job: ' + error.message, 'error');
    }
  };

  window.backupRunJob = async function(jobId) {
    try {
      await backupFetch(`api/backup/jobs/${jobId}/run`, { method: 'POST' });
      
      // Open progress modal
      backupOpenProgressModal(jobId);
      
      // Start polling for progress
      backupStartProgressPolling(jobId);
      
    } catch (error) {
      toast('Failed to run job: ' + error.message, 'error');
    }
  };

  let progressPollingInterval = null;
  let progressLogEntries = [];

  window.backupOpenProgressModal = function(jobId) {
    // Find job details
    const job = backupState.jobs.find(j => j.id === jobId);
    if (job) {
      document.getElementById('backup-progress-job-name').textContent = job.name;
    }
    
    // Reset progress
    document.getElementById('backup-progress-bar').style.width = '0%';
    document.getElementById('backup-progress-percent').textContent = '0%';
    document.getElementById('backup-progress-status').textContent = 'Starting...';
    document.getElementById('backup-progress-message').textContent = 'Initializing backup...';
    document.getElementById('backup-progress-log').innerHTML = '<div style="color: var(--text-muted);">Starting backup...</div>';
    progressLogEntries = ['[' + new Date().toLocaleTimeString() + '] Backup job started'];
    
    backupState.currentProgressJobId = jobId;
    document.getElementById('backup-progress-modal').style.display = 'flex';
  };

  window.backupCloseProgressModal = function() {
    document.getElementById('backup-progress-modal').style.display = 'none';
    if (progressPollingInterval) {
      clearInterval(progressPollingInterval);
      progressPollingInterval = null;
    }
    backupLoadJobs(); // Refresh job list
  };

  window.backupStartProgressPolling = function(jobId) {
    // Clear any existing interval
    if (progressPollingInterval) {
      clearInterval(progressPollingInterval);
    }
    
    // Poll every 2 seconds
    progressPollingInterval = setInterval(async () => {
      try {
        const result = await backupFetch(`api/backup/jobs/${jobId}/status`);
        const status = result.status || result; // Handle both {status: {...}} and direct status
        backupUpdateProgressDisplay(status);
        
        // Stop polling if completed or failed
        if (status.status === 'completed' || status.status === 'failed') {
          clearInterval(progressPollingInterval);
          progressPollingInterval = null;
          
          setTimeout(() => {
            backupLoadJobs();
            backupRefreshArchives();
          }, 2000);
        }
      } catch (error) {
        console.error('Progress polling error:', error);
      }
    }, 2000);
  };

  function backupUpdateProgressDisplay(status) {
    if (!status) return;
    
    const progress = status.progress || 0;
    const statusText = status.status || 'running';
    const message = status.message || 'Processing...';
    
    // Update progress bar
    document.getElementById('backup-progress-bar').style.width = progress + '%';
    document.getElementById('backup-progress-percent').textContent = progress + '%';
    
    // Update status text
    let statusColor = '#0ea5e9';
    let statusDisplay = statusText.toUpperCase();
    
    if (statusText === 'completed') {
      statusColor = '#10b981';
      statusDisplay = 'COMPLETED';
      document.getElementById('backup-progress-bar').style.background = 'linear-gradient(90deg, #10b981, #059669)';
    } else if (statusText === 'failed') {
      statusColor = '#ef4444';
      statusDisplay = 'FAILED';
      document.getElementById('backup-progress-bar').style.background = 'linear-gradient(90deg, #ef4444, #dc2626)';
    } else if (statusText === 'running') {
      statusDisplay = 'RUNNING';
    }
    
    document.getElementById('backup-progress-status').textContent = statusDisplay;
    document.getElementById('backup-progress-status').style.color = statusColor;
    
    // Update message
    document.getElementById('backup-progress-message').textContent = message;
    
    // Add to log if message changed
    if (progressLogEntries[progressLogEntries.length - 1] !== message) {
      const timestamp = new Date().toLocaleTimeString();
      progressLogEntries.push(`[${timestamp}] ${message}`);
      
      // Keep last 20 entries
      if (progressLogEntries.length > 20) {
        progressLogEntries.shift();
      }
      
      // Update log display
      const logHtml = progressLogEntries.map(entry => {
        let color = 'var(--text-muted)';
        if (entry.includes('completed') || entry.includes('success')) color = '#10b981';
        if (entry.includes('failed') || entry.includes('error')) color = '#ef4444';
        return `<div style="color: ${color};">${entry}</div>`;
      }).join('');
      
      const logContainer = document.getElementById('backup-progress-log');
      logContainer.innerHTML = logHtml;
      logContainer.scrollTop = logContainer.scrollHeight;
    }
  }

  window.backupCancelJob = function() {
    if (confirm('Are you sure you want to cancel this backup?')) {
      // TODO: Add cancel endpoint
      toast('Cancel feature coming soon', 'info');
    }
  };

  window.backupDeleteArchive = async function(archiveId) {
    if (!confirm('Delete this backup? This cannot be undone.')) return;
    
    try {
      await backupFetch(`api/backup/archives/${archiveId}`, { method: 'DELETE' });
      toast('Backup deleted', 'success');
      backupRefreshArchives();
    } catch (error) {
      toast('Failed to delete backup: ' + error.message, 'error');
    }
  };

  // === FIXED: Made async + force load + safe dropdown + selective restore ===
  window.backupOpenRestoreModal = async function(archive) {
    backupState.currentRestoreArchive = archive;
    backupState.restoreSelectedItems = []; // Reset selective items

    // === FORCE LOAD SERVERS IF EMPTY ===
    const allServers = [...backupState.sourceServers, ...backupState.destinationServers];
    if (allServers.length === 0) {
      toast('Loading servers for restore...', 'info');
      try {
        await backupLoadServers();
        const reloadedServers = [...backupState.sourceServers, ...backupState.destinationServers];
        if (reloadedServers.length === 0) {
          toast('No servers configured. Add servers first.', 'error');
          return;
        }
      } catch (e) {
        toast('Failed to load servers: ' + e.message, 'error');
        return;
      }
    }
    // === END FORCE LOAD ===

    // Populate modal
    document.getElementById('restore-archive-name').textContent = archive.job_name || archive.id;
    document.getElementById('restore-archive-date').textContent = archive.created_at ? new Date(archive.created_at).toLocaleString() : 'N/A';
    document.getElementById('restore-archive-size').textContent = formatBytes((archive.size_mb || 0) * 1024 * 1024);
    
    // Show original paths
    const pathsList = (archive.source_paths || []).join('\n');
    document.getElementById('restore-original-paths').textContent = pathsList || 'N/A';
    
    // Get source server info for "restore to original"
    const allServersForLookup = [...backupState.sourceServers, ...backupState.destinationServers];
    const sourceServer = allServersForLookup.find(s => s.id === archive.source_server_id);
    const originalLocationText = sourceServer 
      ? `${sourceServer.name} - ${(archive.source_paths || [])[0] || 'Original location'}`
      : 'Original location';
    
    document.getElementById('restore-original-location-text').textContent = originalLocationText;
    
    // === SAFE DROPDOWN POPULATION ===
    const serverSelect = document.getElementById('restore-dest-server');
    serverSelect.innerHTML = '<option value="">Select destination server...</option>';
    allServersForLookup.forEach(server => {
      const opt = document.createElement('option');
      opt.value = server.id;
      opt.textContent = `${server.name} (${server.host}${server.port ? ':' + server.port : ''})`;
      serverSelect.appendChild(opt);
    });
    
    // Set default to original location
    document.getElementById('restore-to-original').checked = true;
    document.getElementById('restore-custom-path-group').style.display = 'none';
    document.getElementById('restore-full').checked = true;
    document.getElementById('restore-selective-group').style.display = 'none';
    document.getElementById('restore-selected-items').innerHTML = 'No items selected';
    document.getElementById('restore-selected-items').style.color = 'var(--text-muted)';
    
    // FORCE MODAL TO DISPLAY
    const modal = document.getElementById('backup-restore-modal');
    if (modal) {
      modal.style.display = 'flex';
      modal.style.position = 'fixed';
      modal.style.top = '0';
      modal.style.left = '0';
      modal.style.right = '0';
      modal.style.bottom = '0';
      modal.style.zIndex = '99999';
      modal.style.background = 'rgba(0, 0, 0, 0.8)';
      modal.style.alignItems = 'center';
      modal.style.justifyContent = 'center';
    }
  };

  window.backupCloseRestoreModal = function() {
    const modal = document.getElementById('backup-restore-modal');
    if (modal) {
      modal.style.display = 'none';
    }
  };

  window.backupToggleRestoreLocation = function() {
    const toOriginal = document.getElementById('restore-to-original').checked;
    document.getElementById('restore-custom-path-group').style.display = toOriginal ? 'none' : 'block';
  };

  window.backupToggleRestoreScope = function() {
    const isFull = document.getElementById('restore-full').checked;
    document.getElementById('restore-selective-group').style.display = isFull ? 'none' : 'block';
  };

  window.backupBrowseRestoreDestination = function() {
    const serverId = document.getElementById('restore-dest-server').value;
    if (!serverId) {
      toast('Please select a destination server first', 'error');
      return;
    }
    
    const server = backupState.servers.find(s => s.id === serverId);
    if (!server) return;
    
    backupState.explorerSide = 'restore-dest';
    backupState.currentBrowseServer = server;
    backupState.selectedPaths = [];
    
    document.getElementById('backup-explorer-modal').style.display = 'flex';
    document.getElementById('backup-explorer-title').textContent = `Browse ${server.name} - Select Destination`;
    
    backupBrowseDirectory('/');
  };

  window.backupBrowseBackupContents = function() {
    const archive = backupState.currentRestoreArchive;
    if (!archive) {
      toast('No archive selected', 'error');
      return;
    }
    
    // Find the backup storage server
    const backupServer = backupState.servers.find(s => s.id === archive.dest_server_id);
    if (!backupServer) {
      toast('Backup storage server not found', 'error');
      return;
    }
    
    backupState.explorerSide = 'restore-selective';
    backupState.currentBrowseServer = backupServer;
    backupState.selectedPaths = backupState.restoreSelectedItems || [];
    backupState.currentBrowsePath = archive.destination_path;
    
    document.getElementById('backup-explorer-modal').style.display = 'flex';
    document.getElementById('backup-explorer-title').textContent = `Browse Backup - Select Items to Restore`;
    
    backupBrowseDirectory(archive.destination_path);
  };

  window.backupSubmitRestore = async function(e) {
    e.preventDefault();
    
    const archive = backupState.currentRestoreArchive;
    if (!archive) {
      toast('No archive selected', 'error');
      return;
    }
    
    const toOriginal = document.getElementById('restore-to-original').checked;
    const isFull = document.getElementById('restore-full').checked;
    let destServerId, destPath;
    
    if (toOriginal) {
      destServerId = archive.source_server_id;
      // Extract parent directory from first source path
      const firstPath = (archive.source_paths || [])[0];
      destPath = firstPath ? firstPath.substring(0, firstPath.lastIndexOf('/')) || '/' : '/';
    } else {
      destServerId = document.getElementById('restore-dest-server').value;
      destPath = document.getElementById('restore-dest-path').value;
    }
    
    if (!destServerId || !destPath) {
      toast('Please select destination server and path', 'error');
      return;
    }
    
    const restoreData = {
      archive_id: archive.id,
      destination_server_id: destServerId,
      destination_path: destPath,
      overwrite: document.getElementById('restore-overwrite').checked
    };
    
    // Add selective restore items if applicable
    if (!isFull && backupState.restoreSelectedItems && backupState.restoreSelectedItems.length > 0) {
      restoreData.selective_items = backupState.restoreSelectedItems;
    }
    
    try {
      const result = await backupFetch('api/backup/restore', {
        method: 'POST',
        body: JSON.stringify(restoreData)
      });
      
      toast('Restore started!', 'success');
      backupCloseRestoreModal();
      
      // TODO: Show restore progress modal similar to backup progress
      
    } catch (error) {
      toast('Failed to start restore: ' + error.message, 'error');
    }
  };

  /* =============== EDIT SERVER MODAL =============== */

  window.backupOpenEditServerModal = function(server) {
    document.getElementById('backup-edit-server-id').value = server.id;
    document.getElementById('backup-edit-server-name').value = server.name;
    document.getElementById('backup-edit-connection-type').value = server.type;
    
    backupUpdateEditConnectionFields();
    
    if (server.type === 'ssh') {
      document.getElementById('backup-edit-ssh-host').value = server.host || '';
      document.getElementById('backup-edit-ssh-port').value = server.port || 22;
      document.getElementById('backup-edit-ssh-username').value = server.username || '';
      document.getElementById('backup-edit-ssh-password').value = server.password || '';
    } else if (server.type === 'smb') {
      document.getElementById('backup-edit-smb-host').value = server.host || '';
      document.getElementById('backup-edit-smb-share').value = server.share || '';
      document.getElementById('backup-edit-smb-username').value = server.username || '';
      document.getElementById('backup-edit-smb-password').value = server.password || '';
    } else if (server.type === 'nfs') {
      document.getElementById('backup-edit-nfs-host').value = server.host || '';
      document.getElementById('backup-edit-nfs-export').value = server.export_path || '';
    }
    
    document.getElementById('backup-edit-server-modal').style.display = 'flex';
  };

  window.backupCloseEditServerModal = function() {
    document.getElementById('backup-edit-server-modal').style.display = 'none';
  };

  window.backupUpdateEditConnectionFields = function() {
    const type = document.getElementById('backup-edit-connection-type').value;
    document.getElementById('backup-edit-ssh-fields').style.display = type === 'ssh' ? 'block' : 'none';
    document.getElementById('backup-edit-smb-fields').style.display = type === 'smb' ? 'block' : 'none';
    document.getElementById('backup-edit-nfs-fields').style.display = type === 'nfs' ? 'block' : 'none';
  };

  window.backupUpdateServer = async function(event) {
    event.preventDefault();
    
    const serverId = document.getElementById('backup-edit-server-id').value;
    const type = document.getElementById('backup-edit-connection-type').value;
    const name = document.getElementById('backup-edit-server-name').value;
    
    // Get current server to preserve server_type
    const allServers = [...backupState.sourceServers, ...backupState.destinationServers];
    const currentServer = allServers.find(s => s.id === serverId);
    
    const updatedServer = {
      id: serverId,
      name,
      type,
      server_type: currentServer ? currentServer.server_type : 'source'
    };
    
    try {
      if (type === 'ssh') {
        updatedServer.host = document.getElementById('backup-edit-ssh-host').value;
        updatedServer.port = parseInt(document.getElementById('backup-edit-ssh-port').value);
        updatedServer.username = document.getElementById('backup-edit-ssh-username').value;
        updatedServer.password = document.getElementById('backup-edit-ssh-password').value;
      } else if (type === 'smb') {
        updatedServer.host = document.getElementById('backup-edit-smb-host').value;
        updatedServer.share = document.getElementById('backup-edit-smb-share').value;
        updatedServer.username = document.getElementById('backup-edit-smb-username').value;
        updatedServer.password = document.getElementById('backup-edit-smb-password').value;
      } else if (type === 'nfs') {
        updatedServer.host = document.getElementById('backup-edit-nfs-host').value;
        updatedServer.export_path = document.getElementById('backup-edit-nfs-export').value;
      }

      // Delete old server
      await backupFetch(`api/backup/servers/${serverId}`, { method: 'DELETE' });
      
      // Add updated server
      await backupFetch('api/backup/servers', {
        method: 'POST',
        body: JSON.stringify(updatedServer)
      });
      
      toast('Server updated successfully', 'success');
      backupCloseEditServerModal();
      await backupLoadServers();
    } catch (error) {
      toast('Failed to update server: ' + error.message, 'error');
    }
  };

  /* =============== EDIT JOB MODAL =============== */

  window.backupOpenEditJobModal = function(job) {
    document.getElementById('backup-edit-job-id').value = job.id;
    document.getElementById('backup-edit-job-name').value = job.name;
    document.getElementById('backup-edit-job-paths').value = Array.isArray(job.paths) ? job.paths.join('\n') : job.paths;
    document.getElementById('backup-edit-job-dest-path').value = job.destination_path || '/backups';
    document.getElementById('backup-edit-job-type').value = job.backup_type || 'full';
    document.getElementById('backup-edit-job-compress').checked = job.compress !== false;
    document.getElementById('backup-edit-job-stop-containers').checked = job.stop_containers || false;
    document.getElementById('backup-edit-job-containers').value = Array.isArray(job.containers) ? job.containers.join(', ') : '';
    document.getElementById('backup-edit-job-schedule').value = job.schedule || '0 2 * * *';
    document.getElementById('backup-edit-job-retention-days').value = job.retention_days || 0;
    document.getElementById('backup-edit-job-retention-count').value = job.retention_count || 0;
    document.getElementById('backup-edit-job-enabled').checked = job.enabled !== false;
    
    // Show/hide container field
    document.getElementById('backup-edit-container-field').style.display = job.stop_containers ? 'block' : 'none';
    
    // Store source/dest server IDs for update
    backupState.editingJobSourceServer = job.source_server_id;
    backupState.editingJobDestServer = job.destination_server_id;
    
    document.getElementById('backup-edit-job-modal').style.display = 'flex';
  };

  window.backupCloseEditJobModal = function() {
    document.getElementById('backup-edit-job-modal').style.display = 'none';
  };

  window.backupUpdateJob = async function(event) {
    event.preventDefault();
    
    const jobId = document.getElementById('backup-edit-job-id').value;
    
    const updatedJob = {
      id: jobId,
      name: document.getElementById('backup-edit-job-name').value,
      source_server_id: backupState.editingJobSourceServer,
      paths: document.getElementById('backup-edit-job-paths').value.split('\n').filter(p => p.trim()),
      destination_server_id: backupState.editingJobDestServer,
      destination_path: document.getElementById('backup-edit-job-dest-path').value,
      backup_type: document.getElementById('backup-edit-job-type').value,
      compress: document.getElementById('backup-edit-job-compress').checked,
      stop_containers: document.getElementById('backup-edit-job-stop-containers').checked,
      containers: document.getElementById('backup-edit-job-containers').value.split(',').map(c => c.trim()).filter(c => c),
      schedule: document.getElementById('backup-edit-job-schedule').value,
      retention_days: parseInt(document.getElementById('backup-edit-job-retention-days').value) || 0,
      retention_count: parseInt(document.getElementById('backup-edit-job-retention-count').value) || 0,
      enabled: document.getElementById('backup-edit-job-enabled').checked
    };
    
    try {
      // Delete old job
      await backupFetch(`api/backup/jobs/${jobId}`, { method: 'DELETE' });
      
      // Create updated job
      await backupFetch('api/backup/jobs', {
        method: 'POST',
        body: JSON.stringify(updatedJob)
      });
      
      toast('Job updated successfully', 'success');
      backupCloseEditJobModal();
      await backupLoadJobs();
    } catch (error) {
      toast('Failed to update job: ' + error.message, 'error');
    }
  };

  window.backupOpenFileExplorerForEdit = function(side) {
    // Use the same file explorer but remember we're in edit mode
    backupState.editMode = true;
    backupOpenFileExplorer(side);
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

  const stopContainersEditCheckbox = document.getElementById('backup-edit-job-stop-containers');
  if (stopContainersEditCheckbox) {
    stopContainersEditCheckbox.addEventListener('change', function() {
      const field = document.getElementById('backup-edit-container-field');
      if (field) field.style.display = this.checked ? 'block' : 'none';
    });
  }

  console.log('[backup] Module loaded and ready');

})();
