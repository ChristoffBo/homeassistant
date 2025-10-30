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
    servers: [], // Added unified servers array
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
    
    backupState.currentBrowseServer = null;
    backupState.currentBrowsePath = '/';
    backupState.selectedPaths = [];
    
    document.getElementById('backup-explorer-modal').style.display = 'flex';
    document.getElementById('backup-explorer-content').innerHTML = '<p class="text-muted">Select a server to browse</p>';
  };

  window.backupSelectExplorerServer = function() {
    const serverId = document.getElementById('backup-explorer-server').value;
    if (!serverId) {
      document.getElementById('backup-explorer-content').innerHTML = '<p class="text-muted">Select a server to browse</p>';
      return;
    }
    
    const servers = backupState.explorerSide === 'source' ? backupState.sourceServers : backupState.destinationServers;
    const server = servers.find(s => s.id === serverId);
    
    if (!server) return;
    
    backupState.currentBrowseServer = server;
    backupBrowseDirectory('/');
  };

  async function backupBrowseDirectory(path) {
    if (!backupState.currentBrowseServer) {
      toast('No server selected', 'error');
      return;
    }
    
    try {
      const result = await backupFetch('api/backup/browse', {
        method: 'POST',
        body: JSON.stringify({
          server_id: backupState.currentBrowseServer.id,
          path: path
        })
      });
      
      backupState.currentBrowsePath = path;
      renderFileExplorer(result.items || []);
    } catch (error) {
      toast('Failed to browse directory: ' + error.message, 'error');
    }
  }

  function renderFileExplorer(items) {
    const content = document.getElementById('backup-explorer-content');
    const side = backupState.explorerSide;
    
    let html = `
      <div style="padding: 12px; background: var(--bg-secondary); border-radius: 8px; margin-bottom: 16px;">
        <strong>Current Path:</strong> ${backupState.currentBrowsePath}
      </div>
    `;
    
    // Parent directory button
    if (backupState.currentBrowsePath !== '/') {
      html += `
        <div class="file-item" style="cursor: pointer;" onclick="backupBrowseParentDirectory()">
          <span>📁 ..</span>
        </div>
      `;
    }
    
    // List items
    items.forEach(item => {
      const isDir = item.is_directory;
      const icon = isDir ? '📁' : '📄';
      const itemPath = backupState.currentBrowsePath + (backupState.currentBrowsePath.endsWith('/') ? '' : '/') + item.name;
      
      html += `
        <div class="file-item" style="display: flex; justify-content: space-between; align-items: center; padding: 8px; border-bottom: 1px solid var(--border);">
          <span style="cursor: ${isDir ? 'pointer' : 'default'};" ${isDir ? `onclick="backupBrowseDirectory('${itemPath}')"` : ''}>
            ${icon} ${item.name}
          </span>
          ${side === 'source' || (side === 'restore-selective') ? `
            <button class="btn btn-sm" onclick="backupTogglePathSelection('${itemPath.replace(/'/g, "\\'")}', this)">
              ${backupState.selectedPaths.includes(itemPath) ? 'Deselect' : 'Select'}
            </button>
          ` : (side === 'destination' && isDir ? `
            <button class="btn btn-sm" onclick="backupSelectDestinationPath('${itemPath.replace(/'/g, "\\'")}')">
              Use This Folder
            </button>
          ` : '')}
        </div>
      `;
    });
    
    content.innerHTML = html;
  }

  window.backupBrowseParentDirectory = function() {
    const path = backupState.currentBrowsePath;
    const parentPath = path.substring(0, path.lastIndexOf('/')) || '/';
    backupBrowseDirectory(parentPath);
  };

  window.backupTogglePathSelection = function(path, button) {
    const index = backupState.selectedPaths.indexOf(path);
    
    if (index > -1) {
      backupState.selectedPaths.splice(index, 1);
      button.textContent = 'Select';
    } else {
      backupState.selectedPaths.push(path);
      button.textContent = 'Deselect';
    }
    
    // Update selected count
    const selectedDiv = document.getElementById('backup-explorer-selected');
    if (selectedDiv) {
      selectedDiv.textContent = `Selected: ${backupState.selectedPaths.length} items`;
    }
  };

  window.backupSelectDestinationPath = function(path) {
    backupState.selectedDestination = path;
    backupCloseExplorer();
    
    // Update the input field
    if (backupState.explorerSide === 'destination') {
      document.getElementById('backup-job-dest-path').value = path;
    }
  };

  window.backupCloseExplorer = function() {
    document.getElementById('backup-explorer-modal').style.display = 'none';
    
    // If we were selecting source paths, update the form
    if (backupState.explorerSide === 'source' && backupState.selectedPaths.length > 0) {
      document.getElementById('backup-job-paths').value = backupState.selectedPaths.join('\n');
    }
    
    // If we were selecting for restore, update the restore items
    if (backupState.explorerSide === 'restore-selective' && backupState.selectedPaths.length > 0) {
      backupState.restoreSelectedItems = backupState.selectedPaths;
      
      const selectedDiv = document.getElementById('restore-selected-items');
      if (selectedDiv) {
        selectedDiv.innerHTML = backupState.selectedPaths.map(p => `<div>• ${p}</div>`).join('');
        selectedDiv.style.color = 'var(--text-primary)';
      }
    }
    
    // If we were selecting restore destination
    if (backupState.explorerSide === 'restore-dest' && backupState.selectedDestination) {
      document.getElementById('restore-dest-path').value = backupState.selectedDestination;
    }
  };

  /* =============== JOB MANAGEMENT =============== */

  window.backupCreateJob = async function(event) {
    event.preventDefault();
    
    const job = {
      name: document.getElementById('backup-job-name').value,
      source_server_id: document.getElementById('backup-source-server').value,
      paths: document.getElementById('backup-job-paths').value.split('\n').filter(p => p.trim()),
      destination_server_id: document.getElementById('backup-dest-server').value,
      destination_path: document.getElementById('backup-job-dest-path').value,
      backup_type: document.getElementById('backup-job-type').value,
      compress: document.getElementById('backup-job-compress').checked,
      stop_containers: document.getElementById('backup-job-stop-containers').checked,
      containers: document.getElementById('backup-job-containers').value.split(',').map(c => c.trim()).filter(c => c),
      schedule: document.getElementById('backup-job-schedule').value,
      retention_days: parseInt(document.getElementById('backup-job-retention-days').value) || 0,
      retention_count: parseInt(document.getElementById('backup-job-retention-count').value) || 0,
      enabled: document.getElementById('backup-job-enabled').checked
    };
    
    if (!job.name || !job.source_server_id || !job.destination_server_id || job.paths.length === 0) {
      toast('Please fill in all required fields', 'error');
      return;
    }
    
    try {
      await backupFetch('api/backup/jobs', {
        method: 'POST',
        body: JSON.stringify(job)
      });
      
      toast('Backup job created successfully', 'success');
      document.getElementById('backup-job-form').reset();
      await backupLoadJobs();
    } catch (error) {
      toast('Failed to create job: ' + error.message, 'error');
    }
  };

  window.backupDeleteJob = async function(jobId) {
    if (!confirm('Delete this backup job?')) return;
    
    try {
      await backupFetch(`api/backup/jobs/${jobId}`, { method: 'DELETE' });
      toast('Job deleted', 'success');
      backupLoadJobs();
    } catch (error) {
      toast('Failed to delete job: ' + error.message, 'error');
    }
  };

  window.backupRunJob = async function(jobId) {
    try {
      toast('Starting backup...', 'info');
      await backupFetch(`api/backup/jobs/${jobId}/run`, { method: 'POST' });
      toast('Backup started!', 'success');
      
      // Open progress modal
      backupOpenProgressModal(jobId);
      backupStartProgressPolling(jobId);
      
    } catch (error) {
      toast('Failed to start backup: ' + error.message, 'error');
    }
  };

  /* =============== DATA LOADING =============== */

  async function backupLoadServers() {
    try {
      const result = await backupFetch('api/backup/servers');
      const servers = result.servers || result || [];
      
      // Store unified servers list
      backupState.servers = servers;
      
      // Split by type for compatibility
      backupState.sourceServers = servers.filter(s => s.server_type === 'source');
      backupState.destinationServers = servers.filter(s => s.server_type === 'destination');
      
      renderServerLists();
    } catch (error) {
      console.error('Failed to load servers:', error);
      toast('Failed to load servers', 'error');
    }
  }

  async function backupLoadJobs() {
    try {
      const result = await backupFetch('api/backup/jobs');
      backupState.jobs = result.jobs || result || [];
      renderJobsList();
    } catch (error) {
      console.error('Failed to load jobs:', error);
    }
  }

  async function backupLoadArchives() {
    try {
      const result = await backupFetch('api/backup/archives');
      backupState.archives = result.archives || result || [];
      renderArchivesList();
      updateStatistics();
    } catch (error) {
      console.error('Failed to load archives:', error);
    }
  }

  async function backupRefreshArchives() {
    toast('Refreshing backups...', 'info');
    await backupLoadArchives();
    toast('Backup data refreshed', 'success');
  }

  async function backupRefreshAll() {
    try {
      await Promise.all([
        backupLoadServers(),
        backupLoadJobs(),
        backupLoadArchives()
      ]);
    } catch (error) {
      console.error('Failed to refresh data:', error);
    }
  }

  /* =============== RENDERING =============== */

  function renderServerLists() {
    // Render source servers
    const sourceList = document.getElementById('backup-source-servers-list');
    if (sourceList) {
      if (backupState.sourceServers.length === 0) {
        sourceList.innerHTML = '<p class="text-muted">No source servers configured</p>';
      } else {
        sourceList.innerHTML = backupState.sourceServers.map(server => `
          <div class="server-card">
            <div>
              <div style="font-weight: 500; margin-bottom: 4px;">${server.name}</div>
              <div style="color: var(--text-muted); font-size: 14px;">${server.host}${server.port ? ':' + server.port : ''}</div>
              <div style="color: var(--text-muted); font-size: 12px; margin-top: 4px;">${server.type.toUpperCase()}</div>
            </div>
            <div style="display: flex; gap: 8px;">
              <button class="btn btn-sm" onclick='backupOpenEditServerModal(${JSON.stringify(server).replace(/'/g, "\\'")} )'>Edit</button>
              <button class="btn danger btn-sm" onclick="backupDeleteServer('${server.id}')">Delete</button>
            </div>
          </div>
        `).join('');
      }
    }
    
    // Render destination servers
    const destList = document.getElementById('backup-dest-servers-list');
    if (destList) {
      if (backupState.destinationServers.length === 0) {
        destList.innerHTML = '<p class="text-muted">No destination servers configured</p>';
      } else {
        destList.innerHTML = backupState.destinationServers.map(server => `
          <div class="server-card">
            <div>
              <div style="font-weight: 500; margin-bottom: 4px;">${server.name}</div>
              <div style="color: var(--text-muted); font-size: 14px;">${server.host}${server.port ? ':' + server.port : ''}</div>
              <div style="color: var(--text-muted); font-size: 12px; margin-top: 4px;">${server.type.toUpperCase()}</div>
            </div>
            <div style="display: flex; gap: 8px;">
              <button class="btn btn-sm" onclick='backupOpenEditServerModal(${JSON.stringify(server).replace(/'/g, "\\'")} )'>Edit</button>
              <button class="btn danger btn-sm" onclick="backupDeleteServer('${server.id}')">Delete</button>
            </div>
          </div>
        `).join('');
      }
    }
    
    // Update dropdowns in job form
    const sourceSelect = document.getElementById('backup-source-server');
    const destSelect = document.getElementById('backup-dest-server');
    
    if (sourceSelect) {
      sourceSelect.innerHTML = '<option value="">Select source server...</option>' + 
        backupState.sourceServers.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
    }
    
    if (destSelect) {
      destSelect.innerHTML = '<option value="">Select destination server...</option>' + 
        backupState.destinationServers.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
    }
  }

  function renderJobsList() {
    const container = document.getElementById('backup-jobs-list');
    if (!container) return;
    
    if (backupState.jobs.length === 0) {
      container.innerHTML = '<p class="text-muted">No backup jobs configured</p>';
      return;
    }
    
    container.innerHTML = backupState.jobs.map(job => {
      const sourceServer = backupState.servers.find(s => s.id === job.source_server_id);
      const destServer = backupState.servers.find(s => s.id === job.destination_server_id);
      
      return `
        <div class="job-card">
          <div style="flex: 1;">
            <div style="font-weight: 500; font-size: 16px; margin-bottom: 8px;">${job.name}</div>
            <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; font-size: 14px;">
              <div><strong>Source:</strong> ${sourceServer ? sourceServer.name : 'Unknown'}</div>
              <div><strong>Destination:</strong> ${destServer ? destServer.name : 'Unknown'}</div>
              <div><strong>Schedule:</strong> ${job.schedule || 'Manual'}</div>
              <div><strong>Type:</strong> ${job.backup_type || 'full'}</div>
              <div><strong>Status:</strong> ${job.enabled ? '<span style="color: #10b981;">Active</span>' : '<span style="color: #ef4444;">Disabled</span>'}</div>
            </div>
          </div>
          <div style="display: flex; gap: 8px;">
            <button class="btn primary btn-sm" onclick="backupRunJob('${job.id}')">Run Now</button>
            <button class="btn btn-sm" onclick='backupOpenEditJobModal(${JSON.stringify(job).replace(/'/g, "\\'")} )'>Edit</button>
            <button class="btn danger btn-sm" onclick="backupDeleteJob('${job.id}')">Delete</button>
          </div>
        </div>
      `;
    }).join('');
  }

  function renderArchivesList() {
    const tbody = document.getElementById('backup-archives-list');
    if (!tbody) return;
    
    if (backupState.archives.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No backups available</td></tr>';
      return;
    }
    
    tbody.innerHTML = backupState.archives.map(archive => {
      // Get source server name
      const sourceServer = backupState.servers.find(s => s.id === archive.source_server_id);
      const sourceName = sourceServer ? sourceServer.name : archive.source_server_id || 'Unknown';
      
      // Format date
      const date = archive.created_at ? new Date(archive.created_at).toLocaleString() : 'N/A';
      
      // Format size
      const sizeBytes = (archive.size_mb || 0) * 1024 * 1024;
      const sizeStr = formatBytes(sizeBytes);
      
      // Store archive in a data attribute instead of inline onclick
      const archiveId = 'archive_' + (archive.id || Math.random().toString(36).substr(2, 9));
      
      // Store the archive object in window for access
      if (!window.backupArchivesData) window.backupArchivesData = {};
      window.backupArchivesData[archiveId] = archive;
      
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
            <button class="btn btn-sm" onclick="backupRestoreFromId('${archiveId}')" style="padding: 4px 12px;">Restore</button>
            <button class="btn danger btn-sm" onclick="backupDeleteArchive('${archive.id}')" style="padding: 4px 12px; margin-left: 4px;">Delete</button>
          </td>
        </tr>
      `;
    }).join('');
  }

  // NEW: Helper function to open restore modal from stored data
  window.backupRestoreFromId = async function(archiveId) {
    const archive = window.backupArchivesData[archiveId];
    if (!archive) {
      toast('Archive data not found', 'error');
      return;
    }
    await backupOpenRestoreModal(archive);
  };

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
      backupLoadServers();
    } catch (error) {
      toast('Failed to delete server: ' + error.message, 'error');
    }
  };

  /* =============== PROGRESS MODAL =============== */

  let progressPollingInterval = null;
  let progressLogEntries = [];

  window.backupOpenProgressModal = function(jobId) {
    document.getElementById('backup-progress-bar').style.width = '0%';
    document.getElementById('backup-progress-bar').style.background = 'linear-gradient(90deg, #0ea5e9, #0284c7)';
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
    console.log('[backup] Opening restore modal for archive:', archive);
    
    backupState.currentRestoreArchive = archive;
    backupState.restoreSelectedItems = []; // Reset selective items

    // === FORCE LOAD SERVERS IF EMPTY ===
    if (!backupState.servers || backupState.servers.length === 0) {
      toast('Loading servers for restore...', 'info');
      try {
        await backupLoadServers();
        if (!backupState.servers || backupState.servers.length === 0) {
          toast('No servers configured. Add servers first.', 'error');
          return;
        }
      } catch (e) {
        console.error('[backup] Failed to load servers:', e);
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
    const sourceServer = backupState.servers.find(s => s.id === archive.source_server_id);
    const originalLocationText = sourceServer 
      ? `${sourceServer.name} - ${(archive.source_paths || [])[0] || 'Original location'}`
      : 'Original location';
    
    document.getElementById('restore-original-location-text').textContent = originalLocationText;
    
    // === SAFE DROPDOWN POPULATION ===
    const serverSelect = document.getElementById('restore-dest-server');
    if (serverSelect) {
      serverSelect.innerHTML = '<option value="">Select destination server...</option>';
      backupState.servers.forEach(server => {
        const opt = document.createElement('option');
        opt.value = server.id;
        opt.textContent = `${server.name} (${server.host}${server.port ? ':' + server.port : ''})`;
        serverSelect.appendChild(opt);
      });
    }
    
    // Set default to original location
    document.getElementById('restore-to-original').checked = true;
    document.getElementById('restore-custom-path-group').style.display = 'none';
    document.getElementById('restore-full').checked = true;
    document.getElementById('restore-selective-group').style.display = 'none';
    document.getElementById('restore-selected-items').innerHTML = 'No items selected';
    document.getElementById('restore-selected-items').style.color = 'var(--text-muted)';
    
    console.log('[backup] Showing restore modal');
    document.getElementById('backup-restore-modal').style.display = 'flex';
  };

  window.backupCloseRestoreModal = function() {
    document.getElementById('backup-restore-modal').style.display = 'none';
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
