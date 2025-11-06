/**
 * Jarvis Prime Backup Module - WITH FILE EXPLORER
 * Click and select folders from source/destination servers
 * 
 * FIXED: Archive contents browsing now uses /api/backup/archives/{id}/contents
 * FIXED: Changed 'schedule' to 'cron' to match backend expectation
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

      if (!name || !server.host) {
        toast('Please fill in all required fields', 'error');
        return;
      }

      await backupFetch('api/backup/servers', {
        method: 'POST',
        body: JSON.stringify(server)
      });
      
      toast('Server added successfully', 'success');
      backupCloseServerModal();
      await backupLoadServers();
    } catch (error) {
      toast('Failed to add server: ' + error.message, 'error');
    }
  };

  /* =============== JOB MODALS =============== */

  window.backupOpenJobModal = function() {
    backupLoadServers(); // Ensure servers are loaded
    document.getElementById('backup-job-modal').style.display = 'flex';
  };

  window.backupCloseJobModal = function() {
    document.getElementById('backup-job-modal').style.display = 'none';
    document.getElementById('backup-job-form').reset();
    backupState.selectedPaths = [];
    backupState.selectedDestination = '';
    renderSelectedPathsPreview();
  };

  window.backupOpenSourceExplorer = async function() {
    const sourceServerId = document.getElementById('backup-job-source').value;
    if (!sourceServerId) {
      toast('Please select a source server first', 'error');
      return;
    }
    
    const server = [...backupState.sourceServers, ...backupState.destinationServers].find(s => s.id === sourceServerId);
    if (!server) return;
    
    backupState.currentBrowseServer = server;
    backupState.currentBrowsePath = '/';
    backupState.explorerSide = 'source';
    
    document.getElementById('backup-explorer-modal').style.display = 'flex';
    document.getElementById('backup-explorer-title').textContent = `Browse ${server.name}`;
    
    await backupBrowsePath('/');
  };

  window.backupOpenDestinationExplorer = async function() {
    const destServerId = document.getElementById('backup-job-destination').value;
    if (!destServerId) {
      toast('Please select a destination server first', 'error');
      return;
    }
    
    const server = [...backupState.sourceServers, ...backupState.destinationServers].find(s => s.id === destServerId);
    if (!server) return;
    
    backupState.currentBrowseServer = server;
    backupState.currentBrowsePath = '/';
    backupState.explorerSide = 'destination';
    
    document.getElementById('backup-explorer-modal').style.display = 'flex';
    document.getElementById('backup-explorer-title').textContent = `Browse ${server.name}`;
    
    await backupBrowsePath('/');
  };

  window.backupCloseExplorerModal = function() {
    document.getElementById('backup-explorer-modal').style.display = 'none';
  };

  async function backupBrowsePath(path) {
    const container = document.getElementById('backup-explorer-files');
    container.innerHTML = '<div class="text-center text-muted" style="padding: 32px;">Loading...</div>';
    
    try {
      const result = await backupFetch('api/backup/browse', {
        method: 'POST',
        body: JSON.stringify({
          server_config: backupState.currentBrowseServer,
          path: path
        })
      });
      
      if (result.success) {
        backupState.currentBrowsePath = path;
        renderExplorerFiles(result.files || []);
        
        // Update breadcrumb
        const parts = path.split('/').filter(p => p);
        let breadcrumb = '<span class="explorer-breadcrumb-item" onclick="backupBrowsePath(\'/\')">Root</span>';
        let currentPath = '';
        parts.forEach(part => {
          currentPath += '/' + part;
          breadcrumb += ' / <span class="explorer-breadcrumb-item" onclick="backupBrowsePath(\'' + currentPath + '\')">' + part + '</span>';
        });
        document.getElementById('backup-explorer-breadcrumb').innerHTML = breadcrumb;
      } else {
        throw new Error(result.error || 'Browse failed');
      }
    } catch (error) {
      toast('Failed to browse: ' + error.message, 'error');
      container.innerHTML = '<div class="text-center text-muted" style="padding: 32px; color: #ef4444;">Failed to load directory</div>';
    }
  }

  function renderExplorerFiles(files) {
    const container = document.getElementById('backup-explorer-files');
    
    if (!files || files.length === 0) {
      container.innerHTML = '<div class="text-center text-muted" style="padding: 32px;">Empty directory</div>';
      return;
    }
    
    // Sort: directories first, then alphabetically
    files.sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    
    container.innerHTML = files.map(file => {
      const icon = file.is_dir ? '📁' : '📄';
      const isSelected = backupState.explorerSide === 'source' 
        ? backupState.selectedPaths.includes(file.path)
        : backupState.selectedDestination === file.path;
      
      return `
        <div class="explorer-file-item ${isSelected ? 'selected' : ''}" 
             onclick="${file.is_dir ? `backupBrowsePath('${file.path}')` : ''}"
             style="padding: 12px; cursor: ${file.is_dir ? 'pointer' : 'default'}; border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;">
          <div style="display: flex; align-items: center; gap: 12px;">
            <span style="font-size: 20px;">${icon}</span>
            <span style="color: var(--text-primary);">${file.name}</span>
          </div>
          <div style="display: flex; gap: 8px; align-items: center;">
            ${!file.is_dir && file.size ? `<span style="font-size: 12px; color: var(--text-muted);">${formatBytes(file.size)}</span>` : ''}
            ${backupState.explorerSide === 'source' 
              ? `<button class="btn btn-sm ${isSelected ? 'success' : 'primary'}" onclick="event.stopPropagation(); backupTogglePathSelection('${file.path}')" style="padding: 4px 12px;">${isSelected ? 'Selected' : 'Select'}</button>`
              : file.is_dir 
                ? `<button class="btn primary btn-sm" onclick="event.stopPropagation(); backupSelectDestination('${file.path}')" style="padding: 4px 12px;">Choose</button>`
                : ''
            }
          </div>
        </div>
      `;
    }).join('');
  }

  window.backupTogglePathSelection = function(path) {
    const index = backupState.selectedPaths.indexOf(path);
    if (index > -1) {
      backupState.selectedPaths.splice(index, 1);
    } else {
      backupState.selectedPaths.push(path);
    }
    renderExplorerFiles(Array.from(document.querySelectorAll('.explorer-file-item')).map(el => ({
      name: el.querySelector('span:nth-child(2)').textContent,
      path: path,
      is_dir: el.querySelector('span:first-child').textContent === '📁'
    })));
    renderSelectedPathsPreview();
  };

  window.backupSelectDestination = function(path) {
    backupState.selectedDestination = path;
    document.getElementById('backup-job-dest-path').value = path;
    backupCloseExplorerModal();
    toast('Destination selected', 'success');
  };

  function renderSelectedPathsPreview() {
    const textarea = document.getElementById('backup-job-paths');
    textarea.value = backupState.selectedPaths.join('\n');
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
      cron: document.getElementById('backup-job-schedule').value, // FIXED: Changed from 'schedule' to 'cron'
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
      backupState.jobs = Object.values(data.jobs || {});
      renderJobsList();
    } catch (error) {
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
              <div><strong>Schedule:</strong> ${job.cron || job.schedule || 'Manual'}</div>
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
    
    // Store archives globally for onclick access
    window.backupArchivesForRestore = backupState.archives;
    
    tbody.innerHTML = backupState.archives.map((archive, index) => {
      // Get source server name
      const sourceServer = backupState.servers.find(s => s.id === archive.source_server_id);
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
            <button class="btn btn-sm" onclick="backupRestoreByIndex(${index})" style="padding: 4px 12px;">Restore</button>
            <button class="btn danger btn-sm" onclick="backupDeleteArchive('${archive.id}')" style="padding: 4px 12px; margin-left: 4px;">Delete</button>
          </td>
        </tr>
      `;
    }).join('');
  }

  window.backupRestoreByIndex = function(index) {
    if (window.backupArchivesForRestore && window.backupArchivesForRestore[index]) {
      backupOpenRestoreModal(window.backupArchivesForRestore[index]);
    }
  };

  function updateStatistics() {
    document.getElementById('backup-stat-total').textContent = backupState.archives.length;
    document.getElementById('backup-stat-jobs').textContent = backupState.jobs.length;
    
    // Fix: use size_mb and convert to bytes
    const totalSizeBytes = backupState.archives.reduce((sum, archive) => {
      const sizeMB = archive.size_mb || 0;
      return sum + (sizeMB * 1024 * 1024);
    }, 0);
    document.getElementById('backup-stat-size').textContent = formatBytes(totalSizeBytes);
    
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    
    // Use created_at instead of timestamp
    const todayArchives = backupState.archives.filter(a => {
      if (!a.created_at) return false;
      const archiveDate = new Date(a.created_at);
      return archiveDate >= today;
    });
    
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
      
      toast('Backup job started', 'success');
    } catch (error) {
      toast('Failed to start backup: ' + error.message, 'error');
    }
  };

  let progressPollingInterval = null;
  let progressLogEntries = [];

  window.backupOpenProgressModal = function(jobId) {
    progressLogEntries = [];
    document.getElementById('backup-progress-modal').style.display = 'flex';
    document.getElementById('backup-progress-bar').style.width = '0%';
    document.getElementById('backup-progress-message').textContent = 'Starting backup...';
    document.getElementById('backup-progress-log').innerHTML = '';
  };

  window.backupCloseProgressModal = function() {
    document.getElementById('backup-progress-modal').style.display = 'none';
    if (progressPollingInterval) {
      clearInterval(progressPollingInterval);
      progressPollingInterval = null;
    }
  };

  function backupStartProgressPolling(jobId) {
    if (progressPollingInterval) {
      clearInterval(progressPollingInterval);
    }
    
    progressPollingInterval = setInterval(async () => {
      try {
        const result = await backupFetch(`api/backup/jobs/${jobId}/status`);
        if (result.success && result.status) {
          updateProgressModal(result.status);
          
          if (result.status.status === 'completed' || result.status.status === 'failed') {
            clearInterval(progressPollingInterval);
            progressPollingInterval = null;
            
            setTimeout(() => {
              backupCloseProgressModal();
              backupRefreshArchives();
            }, 3000);
          }
        }
      } catch (error) {
        console.error('[backup] Progress polling error:', error);
      }
    }, 2000);
  }

  function updateProgressModal(status) {
    const progress = status.progress || 0;
    const message = status.message || 'Processing...';
    
    // Update progress bar
    const progressBar = document.getElementById('backup-progress-bar');
    progressBar.style.width = progress + '%';
    
    if (status.status === 'completed') {
      progressBar.style.background = 'linear-gradient(135deg, #10b981 0%, #059669 100%)';
    } else if (status.status === 'failed') {
      progressBar.style.background = 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)';
    }
    
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
    if (backupState.servers.length === 0) {
      toast('Loading servers for restore...', 'info');
      try {
        await backupLoadServers();
        if (backupState.servers.length === 0) {
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
    const sourceServer = backupState.servers.find(s => s.id === archive.source_server_id);
    const originalLocationText = sourceServer 
      ? `${sourceServer.name} - ${(archive.source_paths || [])[0] || 'Original location'}`
      : 'Original location';
    
    document.getElementById('restore-original-location-text').textContent = originalLocationText;
    
    // === SAFE DROPDOWN POPULATION ===
    const serverSelect = document.getElementById('restore-dest-server');
    serverSelect.innerHTML = '<option value="">Select destination server...</option>';
    backupState.servers.forEach(server => {
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

  window.backupBrowseRestoreDestination = async function() {
    const serverId = document.getElementById('restore-dest-server').value;
    if (!serverId) {
      toast('Please select a destination server first', 'error');
      return;
    }
    
    const server = backupState.servers.find(s => s.id === serverId);
    if (!server) return;
    
    backupState.currentBrowseServer = server;
    backupState.currentDestBrowsePath = '/';
    backupState.selectedDestPath = '';
    
    // Show inline browser in the restore modal
    const pathInput = document.getElementById('restore-dest-path');
    const browseBtn = pathInput.nextElementSibling;
    
    // Create inline browser container if it doesn't exist
    let browserContainer = document.getElementById('restore-dest-browser');
    if (!browserContainer) {
      browserContainer = document.createElement('div');
      browserContainer.id = 'restore-dest-browser';
      browserContainer.style.cssText = 'margin-top: 8px; padding: 12px; background: var(--surface-secondary); border: 1px solid var(--border-color); border-radius: 4px;';
      browseBtn.parentElement.appendChild(browserContainer);
    }
    
    browserContainer.innerHTML = '<div class="text-muted">Loading...</div>';
    
    try {
      const result = await backupFetch('api/backup/browse', {
        method: 'POST',
        body: JSON.stringify({
          server_config: server,
          path: '/'
        })
      });
      
      if (result.success) {
        renderDestBrowserInline(result.files || [], '/');
      } else {
        throw new Error(result.error || 'Browse failed');
      }
    } catch (error) {
      toast('Failed to browse: ' + error.message, 'error');
      browserContainer.innerHTML = '<div class="text-muted" style="color: #ef4444;">Failed to load directory</div>';
    }
  };
  
  async function browseDestPathInline(path) {
    const browserContainer = document.getElementById('restore-dest-browser');
    if (!browserContainer || !backupState.currentBrowseServer) return;
    
    browserContainer.innerHTML = '<div class="text-muted">Loading...</div>';
    
    try {
      const result = await backupFetch('api/backup/browse', {
        method: 'POST',
        body: JSON.stringify({
          server_config: backupState.currentBrowseServer,
          path: path
        })
      });
      
      if (result.success) {
        backupState.currentDestBrowsePath = path;
        renderDestBrowserInline(result.files || [], path);
      } else {
        throw new Error(result.error || 'Browse failed');
      }
    } catch (error) {
      toast('Failed to browse: ' + error.message, 'error');
      browserContainer.innerHTML = '<div class="text-muted" style="color: #ef4444;">Failed to load directory</div>';
    }
  }
  
  function renderDestBrowserInline(files, currentPath) {
    const container = document.getElementById('restore-dest-browser');
    if (!container) return;
    
    // Sort directories first
    files.sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    
    let html = `<div style="font-size: 12px; color: var(--text-muted); margin-bottom: 8px;">Current: ${currentPath}</div>`;
    
    if (currentPath !== '/') {
      const parentPath = currentPath.split('/').slice(0, -1).join('/') || '/';
      html += `
        <div style="padding: 8px; cursor: pointer; border-bottom: 1px solid var(--border-color);" 
             onclick="browseDestPathInline('${parentPath}')">
          <span style="font-size: 16px;">⬆️</span> ..
        </div>
      `;
    }
    
    html += files.filter(f => f.is_dir).map(file => `
      <div style="padding: 8px; cursor: pointer; border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;">
        <div onclick="browseDestPathInline('${file.path}')" style="flex: 1;">
          <span style="font-size: 16px;">📁</span> ${file.name}
        </div>
        <button class="btn primary btn-sm" onclick="selectRestoreDestPath('${file.path}')" style="padding: 4px 8px;">Choose</button>
      </div>
    `).join('');
    
    container.innerHTML = html;
  }
  
  window.selectRestoreDestPath = function(path) {
    document.getElementById('restore-dest-path').value = path;
    const browser = document.getElementById('restore-dest-browser');
    if (browser) {
      browser.remove();
    }
    toast('Destination path selected', 'success');
  };

  window.backupBrowseArchiveContents = async function() {
    const archive = backupState.currentRestoreArchive;
    if (!archive) return;
    
    // Show browse modal
    document.getElementById('backup-archive-browser-modal').style.display = 'flex';
    document.getElementById('backup-archive-browser-title').textContent = `Browse: ${archive.job_name || archive.id}`;
    
    const container = document.getElementById('backup-archive-browser-files');
    container.innerHTML = '<div class="text-center text-muted" style="padding: 32px;">Loading archive contents...</div>';
    
    try {
      // === FIXED: Use the /contents endpoint ===
      const result = await backupFetch(`api/backup/archives/${archive.id}/contents?page=1&page_size=1000`);
      
      if (result.success && result.items) {
        renderArchiveContents(result.items);
      } else {
        throw new Error(result.error || 'Failed to load archive contents');
      }
    } catch (error) {
      toast('Failed to browse archive: ' + error.message, 'error');
      container.innerHTML = '<div class="text-center" style="padding: 32px; color: #ef4444;">Failed to load archive contents</div>';
    }
  };

  function renderArchiveContents(items) {
    const container = document.getElementById('backup-archive-browser-files');
    
    if (!items || items.length === 0) {
      container.innerHTML = '<div class="text-center text-muted" style="padding: 32px;">No files found in archive</div>';
      return;
    }
    
    // Sort: directories first, then files
    items.sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
      return (a.path || a.name || '').localeCompare(b.path || b.name || '');
    });
    
    container.innerHTML = items.map(item => {
      const icon = item.is_dir ? '📁' : '📄';
      const displayName = item.name || item.path.split('/').pop() || item.path;
      const isSelected = backupState.restoreSelectedItems.includes(item.path);
      
      // Handle notes
      if (item.note) {
        return `
          <div style="padding: 12px; background: rgba(14, 165, 233, 0.08); color: var(--text-muted); font-size: 12px; border-bottom: 1px solid var(--border-color);">
            ℹ️ ${item.note}
          </div>
        `;
      }
      
      return `
        <div class="archive-file-item ${isSelected ? 'selected' : ''}" 
             style="padding: 12px; border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;">
          <div style="display: flex; align-items: center; gap: 12px; flex: 1;">
            <span style="font-size: 20px;">${icon}</span>
            <div>
              <div style="color: var(--text-primary);">${displayName}</div>
              <div style="font-size: 11px; color: var(--text-muted); font-family: monospace;">${item.path}</div>
            </div>
          </div>
          <div style="display: flex; gap: 8px; align-items: center;">
            ${item.size ? `<span style="font-size: 12px; color: var(--text-muted);">${formatBytes(item.size)}</span>` : ''}
            <button class="btn btn-sm ${isSelected ? 'success' : 'primary'}" 
                    onclick="backupToggleSelectiveItem('${item.path.replace(/'/g, "\\'")}')" 
                    style="padding: 4px 12px;">
              ${isSelected ? 'Selected' : 'Select'}
            </button>
          </div>
        </div>
      `;
    }).join('');
  }

  window.backupToggleSelectiveItem = function(path) {
    const index = backupState.restoreSelectedItems.indexOf(path);
    if (index > -1) {
      backupState.restoreSelectedItems.splice(index, 1);
    } else {
      backupState.restoreSelectedItems.push(path);
    }
    
    // Update selection count in restore modal
    const countEl = document.getElementById('restore-selected-items');
    if (backupState.restoreSelectedItems.length > 0) {
      countEl.innerHTML = `${backupState.restoreSelectedItems.length} item(s) selected`;
      countEl.style.color = '#10b981';
    } else {
      countEl.innerHTML = 'No items selected';
      countEl.style.color = 'var(--text-muted)';
    }
    
    // Re-render to update UI
    const container = document.getElementById('backup-archive-browser-files');
    const items = Array.from(container.querySelectorAll('.archive-file-item')).map(el => {
      const pathText = el.querySelector('div div:last-child').textContent;
      return { path: pathText };
    });
    
    // Just update the button states
    container.querySelectorAll('.archive-file-item button').forEach((btn, idx) => {
      const itemPath = items[idx]?.path;
      const isSelected = backupState.restoreSelectedItems.includes(itemPath);
      btn.className = `btn btn-sm ${isSelected ? 'success' : 'primary'}`;
      btn.textContent = isSelected ? 'Selected' : 'Select';
      btn.parentElement.parentElement.classList.toggle('selected', isSelected);
    });
  };

  window.backupCloseArchiveBrowser = function() {
    document.getElementById('backup-archive-browser-modal').style.display = 'none';
  };

  window.backupPerformRestore = async function() {
    const archive = backupState.currentRestoreArchive;
    if (!archive) return;
    
    const toOriginal = document.getElementById('restore-to-original').checked;
    const isFull = document.getElementById('restore-full').checked;
    
    let destServerId, destPath;
    
    if (toOriginal) {
      destServerId = archive.source_server_id;
      destPath = (archive.source_paths || [])[0] || '';
    } else {
      destServerId = document.getElementById('restore-dest-server').value;
      destPath = document.getElementById('restore-dest-path').value;
      
      if (!destServerId || !destPath) {
        toast('Please select destination server and path', 'error');
        return;
      }
    }
    
    const restoreData = {
      archive_id: archive.id,
      destination_server_id: destServerId,
      destination_path: destPath,
      selective_items: isFull ? [] : backupState.restoreSelectedItems
    };
    
    if (!isFull && restoreData.selective_items.length === 0) {
      toast('Please select items to restore or choose full restore', 'error');
      return;
    }
    
    try {
      const result = await backupFetch('api/backup/restore', {
        method: 'POST',
        body: JSON.stringify(restoreData)
      });
      
      if (result.success) {
        toast('Restore started successfully', 'success');
        backupCloseRestoreModal();
        
        // Start polling restore status
        backupStartRestorePolling(result.restore_id);
      } else {
        throw new Error(result.error || 'Restore failed');
      }
    } catch (error) {
      toast('Failed to start restore: ' + error.message, 'error');
    }
  };

  function backupStartRestorePolling(restoreId) {
    const interval = setInterval(async () => {
      try {
        const result = await backupFetch(`api/backup/restore/${restoreId}/status`);
        
        if (result.success && result.status) {
          const status = result.status.status;
          
          if (status === 'completed') {
            clearInterval(interval);
            toast('Restore completed successfully!', 'success');
          } else if (status === 'failed') {
            clearInterval(interval);
            toast('Restore failed: ' + (result.status.message || 'Unknown error'), 'error');
          }
        }
      } catch (error) {
        console.error('[backup] Restore polling error:', error);
      }
    }, 3000);
  }

  /* =============== EDIT MODALS =============== */

  window.backupOpenEditServerModal = function(server) {
    // Populate form with server data
    document.getElementById('backup-edit-server-id').value = server.id;
    document.getElementById('backup-edit-server-name').value = server.name;
    document.getElementById('backup-edit-server-type').value = server.server_type;
    document.getElementById('backup-edit-connection-type').value = server.type;
    
    backupUpdateEditConnectionFields();
    
    if (server.type === 'ssh') {
      document.getElementById('backup-edit-ssh-host').value = server.host;
      document.getElementById('backup-edit-ssh-port').value = server.port;
      document.getElementById('backup-edit-ssh-username').value = server.username;
      document.getElementById('backup-edit-ssh-password').value = server.password || '';
    } else if (server.type === 'smb') {
      document.getElementById('backup-edit-smb-host').value = server.host;
      document.getElementById('backup-edit-smb-share').value = server.share;
      document.getElementById('backup-edit-smb-username').value = server.username;
      document.getElementById('backup-edit-smb-password').value = server.password || '';
    } else if (server.type === 'nfs') {
      document.getElementById('backup-edit-nfs-host').value = server.host;
      document.getElementById('backup-edit-nfs-export').value = server.export_path;
    }
    
    document.getElementById('backup-edit-server-modal').style.display = 'flex';
  };

  window.backupCloseEditServerModal = function() {
    document.getElementById('backup-edit-server-modal').style.display = 'none';
    document.getElementById('backup-edit-server-form').reset();
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
    const serverType = document.getElementById('backup-edit-server-type').value;
    const name = document.getElementById('backup-edit-server-name').value;
    
    const server = { id: serverId, name, type, server_type: serverType };
    
    try {
      if (type === 'ssh') {
        server.host = document.getElementById('backup-edit-ssh-host').value;
        server.port = parseInt(document.getElementById('backup-edit-ssh-port').value);
        server.username = document.getElementById('backup-edit-ssh-username').value;
        server.password = document.getElementById('backup-edit-ssh-password').value;
      } else if (type === 'smb') {
        server.host = document.getElementById('backup-edit-smb-host').value;
        server.share = document.getElementById('backup-edit-smb-share').value;
        server.username = document.getElementById('backup-edit-smb-username').value;
        server.password = document.getElementById('backup-edit-smb-password').value;
      } else if (type === 'nfs') {
        server.host = document.getElementById('backup-edit-nfs-host').value;
        server.export_path = document.getElementById('backup-edit-nfs-export').value;
      }

      if (!name || !server.host) {
        toast('Please fill in all required fields', 'error');
        return;
      }

      // Delete old server
      await backupFetch(`api/backup/servers/${serverId}`, { method: 'DELETE' });
      
      // Create updated server
      await backupFetch('api/backup/servers', {
        method: 'POST',
        body: JSON.stringify(server)
      });
      
      toast('Server updated successfully', 'success');
      backupCloseEditServerModal();
      await backupLoadServers();
    } catch (error) {
      toast('Failed to update server: ' + error.message, 'error');
    }
  };

  window.backupOpenEditJobModal = async function(job) {
    backupState.editingJobId = job.id;
    
    // Load servers if needed
    if (backupState.servers.length === 0) {
      await backupLoadServers();
    }
    
    // Populate form
    document.getElementById('backup-edit-job-name').value = job.name;
    document.getElementById('backup-edit-job-paths').value = (job.paths || []).join('\n');
    document.getElementById('backup-edit-job-dest-path').value = job.destination_path || '';
    document.getElementById('backup-edit-job-type').value = job.backup_type || 'incremental';
    document.getElementById('backup-edit-job-compress').checked = job.compress !== false;
    document.getElementById('backup-edit-job-stop-containers').checked = job.stop_containers || false;
    document.getElementById('backup-edit-job-containers').value = (job.containers || []).join(',');
    document.getElementById('backup-edit-job-schedule').value = job.cron || job.schedule || '0 2 * * *';
    document.getElementById('backup-edit-job-retention-days').value = job.retention_days || 0;
    document.getElementById('backup-edit-job-retention-count').value = job.retention_count || 0;
    document.getElementById('backup-edit-job-enabled').checked = job.enabled !== false;
    
    // Store server IDs
    backupState.editingJobSourceServer = job.source_server_id;
    backupState.editingJobDestServer = job.destination_server_id;
    
    // Populate dropdowns
    const sourceSelect = document.getElementById('backup-edit-job-source');
    sourceSelect.innerHTML = '<option value="">Select source server...</option>';
    backupState.sourceServers.forEach(server => {
      const opt = document.createElement('option');
      opt.value = server.id;
      opt.textContent = `${server.name} (${server.host})`;
      opt.selected = server.id === job.source_server_id;
      sourceSelect.appendChild(opt);
    });
    
    const destSelect = document.getElementById('backup-edit-job-destination');
    destSelect.innerHTML = '<option value="">Select destination server...</option>';
    backupState.destinationServers.forEach(server => {
      const opt = document.createElement('option');
      opt.value = server.id;
      opt.textContent = `${server.name} (${server.host})`;
      opt.selected = server.id === job.destination_server_id;
      destSelect.appendChild(opt);
    });
    
    document.getElementById('backup-edit-job-modal').style.display = 'flex';
  };

  window.backupCloseEditJobModal = function() {
    document.getElementById('backup-edit-job-modal').style.display = 'none';
  };

  window.backupUpdateJob = async function(event) {
    event.preventDefault();
    
    const jobId = backupState.editingJobId;
    
    const updatedJob = {
      name: document.getElementById('backup-edit-job-name').value,
      source_server_id: backupState.editingJobSourceServer,
      paths: document.getElementById('backup-edit-job-paths').value.split('\n').filter(p => p.trim()),
      destination_server_id: backupState.editingJobDestServer,
      destination_path: document.getElementById('backup-edit-job-dest-path').value,
      backup_type: document.getElementById('backup-edit-job-type').value,
      compress: document.getElementById('backup-edit-job-compress').checked,
      stop_containers: document.getElementById('backup-edit-job-stop-containers').checked,
      containers: document.getElementById('backup-edit-job-containers').value.split(',').map(c => c.trim()).filter(c => c),
      cron: document.getElementById('backup-edit-job-schedule').value, // FIXED: Changed from 'schedule' to 'cron'
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

  window.backupOnEditSourceChange = function() {
    backupState.editingJobSourceServer = document.getElementById('backup-edit-job-source').value;
  };

  window.backupOnEditDestChange = function() {
    backupState.editingJobDestServer = document.getElementById('backup-edit-job-destination').value;
  };

  /* =============== IMPORT ARCHIVES =============== */

  window.backupImportArchives = async function() {
    if (!confirm('Import archives from /backups directory? This will scan for existing backup files.')) {
      return;
    }
    
    try {
      toast('Scanning for archives...', 'info');
      const result = await backupFetch('api/backup/import-archives', { method: 'POST' });
      
      if (result.success) {
        toast(`Imported ${result.imported} archive(s)`, 'success');
        backupRefreshArchives();
      } else {
        throw new Error(result.error || 'Import failed');
      }
    } catch (error) {
      toast('Failed to import archives: ' + error.message, 'error');
    }
  };

  /* =============== INIT =============== */

  window.backupInit = function() {
    backupLoadServers();
    backupLoadJobs();
    backupRefreshArchives();
  };

  // Auto-init on load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.backupInit);
  } else {
    window.backupInit();
  }
})();
