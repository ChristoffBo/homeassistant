// orchestrator.js - Orchestrator tab functionality for Jarvis Prime
// Sprint 4: QoL Features - Search, Cancel, Retry, Pause, Run Now, View Output

(function() {
  'use strict';

  // Get API root from existing app.js
  function apiRoot() {
    if (window.JARVIS_API_BASE) {
      let v = String(window.JARVIS_API_BASE);
      return v.endsWith('/') ? v : v + '/';
    }
    try {
      const u = new URL(document.baseURI);
      let p = u.pathname;
      if (p.endsWith('/index.html')) p = p.slice(0, -'/index.html'.length);
      if (p.endsWith('/ui/')) p = p.slice(0, -4);
      if (!p.endsWith('/')) p += '/';
      u.pathname = p;
      return u.toString();
    } catch (e) {
      return document.baseURI;
    }
  }

  const ROOT = apiRoot();
  const API = (path) => new URL(String(path).replace(/^\/+/, ''), ROOT).toString();

  // Toast helper (reuse from main app)
  function toast(msg, type = 'info') {
    const d = document.createElement('div');
    d.className = `toast ${type}`;
    d.textContent = msg;
    const container = document.getElementById('toast');
    if (container) {
      container.appendChild(d);
      setTimeout(() => d.remove(), 4000);
    }
  }

  // Enhanced fetch
  async function jfetch(url, opts = {}) {
    try {
      const r = await fetch(url, {
        ...opts,
        headers: {
          'Content-Type': 'application/json',
          ...opts.headers
        }
      });
      
      if (!r.ok) {
        const text = await r.text().catch(() => '');
        throw new Error(`${r.status} ${r.statusText}: ${text}`);
      }
      
      const ct = r.headers.get('content-type') || '';
      return ct.includes('application/json') ? r.json() : r.text();
    } catch (error) {
      console.error('Orchestrator API Error:', error);
      throw error;
    }
  }

  let currentJobId = null;
  let wsConnection = null;
  let editingScheduleId = null;
  let allPlaybooks = {}; // Store for filtering

  // ============================================
  // ORCHESTRATOR SUB-TAB SWITCHING
  // ============================================
  document.querySelectorAll('.orch-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.orch-tab').forEach(x => x.classList.remove('active'));
      btn.classList.add('active');
      
      document.querySelectorAll('.orch-panel').forEach(p => p.classList.remove('active'));
      const panelId = 'orch-' + btn.dataset.orchTab;
      const panel = document.getElementById(panelId);
      if (panel) panel.classList.add('active');

      // Load data when switching tabs
      const tab = btn.dataset.orchTab;
      if (tab === 'playbooks') orchLoadPlaybooks();
      else if (tab === 'servers') orchLoadServers();
      else if (tab === 'schedules') orchLoadSchedules();
      else if (tab === 'history') orchLoadHistory();
    });
  });

  // ============================================
  // PLAYBOOK SEARCH (QOL)
  // ============================================
  function initPlaybookSearch() {
    const searchInput = document.getElementById('playbook-search');
    if (!searchInput) return;
    
    searchInput.addEventListener('input', (e) => {
      const query = e.target.value.toLowerCase();
      filterPlaybooks(query);
    });
  }

  function filterPlaybooks(query) {
    if (!query) {
      renderPlaybooks(allPlaybooks);
      return;
    }
    
    const filtered = {};
    for (const [category, playbooks] of Object.entries(allPlaybooks)) {
      const matchingPlaybooks = playbooks.filter(p => 
        p.name.toLowerCase().includes(query) || 
        p.path.toLowerCase().includes(query)
      );
      
      if (matchingPlaybooks.length > 0) {
        filtered[category] = matchingPlaybooks;
      }
    }
    
    renderPlaybooks(filtered);
  }

  // ============================================
  // PLAYBOOK UPLOAD
  // ============================================
  function initPlaybookUpload() {
    const uploadZone = document.getElementById('playbook-upload-zone');
    const fileInput = document.getElementById('playbook-file-input');
    
    if (!uploadZone || !fileInput) return;
    
    uploadZone.addEventListener('click', () => {
      fileInput.click();
    });
    
    uploadZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      uploadZone.style.borderColor = 'var(--accent-primary)';
      uploadZone.style.background = 'rgba(14, 165, 233, 0.05)';
    });
    
    uploadZone.addEventListener('dragleave', (e) => {
      e.preventDefault();
      uploadZone.style.borderColor = 'var(--border-color)';
      uploadZone.style.background = 'var(--surface-secondary)';
    });
    
    uploadZone.addEventListener('drop', (e) => {
      e.preventDefault();
      uploadZone.style.borderColor = 'var(--border-color)';
      uploadZone.style.background = 'var(--surface-secondary)';
      
      const files = Array.from(e.dataTransfer.files);
      uploadPlaybookFiles(files);
    });
    
    fileInput.addEventListener('change', (e) => {
      const files = Array.from(e.target.files);
      uploadPlaybookFiles(files);
      fileInput.value = '';
    });
  }

  async function uploadPlaybookFiles(files) {
    if (!files || files.length === 0) return;
    
    const validExtensions = ['.yml', '.yaml', '.sh', '.py'];
    const validFiles = files.filter(f => {
      const ext = '.' + f.name.split('.').pop().toLowerCase();
      return validExtensions.includes(ext);
    });
    
    if (validFiles.length === 0) {
      toast('No valid playbook files selected (.yml, .yaml, .sh, .py)', 'error');
      return;
    }
    
    for (const file of validFiles) {
      try {
        const formData = new FormData();
        formData.append('file', file);
        
        const response = await fetch(API('api/orchestrator/playbooks/upload'), {
          method: 'POST',
          body: formData
        });
        
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || 'Upload failed');
        }
        
        const result = await response.json();
        toast(`✓ ${file.name} uploaded successfully`, 'success');
      } catch (e) {
        toast(`✗ Failed to upload ${file.name}: ${e.message}`, 'error');
      }
    }
    
    orchLoadPlaybooks();
  }

  // ============================================
  // PLAYBOOK DOWNLOAD
  // ============================================
  window.orchDownloadPlaybook = async function(playbookPath, playbookName) {
    try {
      const response = await fetch(API(`api/orchestrator/playbooks/download/${encodeURIComponent(playbookPath)}`));
      
      if (!response.ok) {
        throw new Error('Download failed');
      }
      
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = playbookName;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      
      toast(`Downloaded ${playbookName}`, 'success');
    } catch (e) {
      toast('Failed to download playbook: ' + e.message, 'error');
    }
  };

  // ============================================
  // WEBSOCKET FOR LIVE LOGS
  // ============================================
  function connectWebSocket() {
    try {
      const wsUrl = API('api/orchestrator/ws').replace('http://', 'ws://').replace('https://', 'wss://');
      wsConnection = new WebSocket(wsUrl);
      
      wsConnection.onopen = () => {
        console.log('[Orchestrator] WebSocket connected');
      };
      
      wsConnection.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.event === 'orchestration_log' && data.job_id === currentJobId) {
            appendLog(data.line);
          }
        } catch (e) {
          console.error('WebSocket message parse error:', e);
        }
      };
      
      wsConnection.onerror = (error) => {
        console.error('[Orchestrator] WebSocket error:', error);
      };
      
      wsConnection.onclose = () => {
        console.log('[Orchestrator] WebSocket closed, reconnecting in 5s...');
        setTimeout(connectWebSocket, 5000);
      };
    } catch (e) {
      console.error('[Orchestrator] WebSocket connection failed:', e);
    }
  }

  function appendLog(line) {
    const logOutput = document.getElementById('orch-logs');
    if (!logOutput) return;
    
    const logLine = document.createElement('div');
    logLine.className = 'log-line';
    logLine.textContent = line;
    logOutput.appendChild(logLine);
    logOutput.scrollTop = logOutput.scrollHeight;
  }

  // ============================================
  // PLAYBOOKS - ORGANIZED BY CATEGORY
  // ============================================
  window.orchLoadPlaybooks = async function() {
    const container = document.getElementById('playbooks-list');
    if (!container) return;
    
    try {
      container.innerHTML = '<div class="text-center text-muted">Loading playbooks...</div>';
      const data = await jfetch(API('api/orchestrator/playbooks/organized'));
      
      if (!data.playbooks || Object.keys(data.playbooks).length === 0) {
        container.innerHTML = '<div class="text-center text-muted">No playbooks found. Upload .sh, .py, or .yml files above.</div>';
        return;
      }
      
      allPlaybooks = data.playbooks;
      renderPlaybooks(allPlaybooks);
      orchLoadServerOptionsForPlaybooks();
    } catch (e) {
      container.innerHTML = '<div class="text-center text-muted">Failed to load playbooks</div>';
      toast('Failed to load playbooks: ' + e.message, 'error');
    }
  };

  function renderPlaybooks(playbooks) {
    const container = document.getElementById('playbooks-list');
    if (!container) return;
    
    if (!playbooks || Object.keys(playbooks).length === 0) {
      container.innerHTML = '<div class="text-center text-muted">No playbooks match your search</div>';
      return;
    }
    
    let html = '';
    for (const [category, playbookList] of Object.entries(playbooks).sort()) {
      const categoryName = category === 'root' ? 'Root' : category.charAt(0).toUpperCase() + category.slice(1);
      const categoryIcon = {
        'lxc': '📦',
        'debian': '🐧',
        'proxmox': '🔧',
        'network': '🌐',
        'docker': '🐳',
        'security': '🔒',
        'root': '📁'
      }[category] || '📄';
      
      html += `<div class="playbook-category" style="margin-bottom: 24px;">
        <h4 style="color: var(--text-primary); margin-bottom: 12px; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px;">
          ${categoryIcon} ${categoryName}
        </h4>`;
      
      playbookList.forEach(p => {
        const safeId = p.path.replace(/[^a-zA-Z0-9]/g, '_');
        html += `
          <div class="playbook-card">
            <div class="playbook-name">${p.name}</div>
            <div class="playbook-meta">
              Type: ${p.type.toUpperCase()} | 
              Path: ${p.path} | 
              Modified: ${new Date(p.modified).toLocaleString()}
            </div>
            <div class="playbook-actions">
              <select class="playbook-target" id="target-${safeId}" style="margin-bottom: 8px;">
                <option value="">All servers</option>
              </select>
              <div style="display: flex; gap: 8px;">
                <button class="btn primary" onclick="orchRunPlaybook('${p.path.replace(/'/g, "\\'")}')">▶ Run</button>
                <button class="btn" onclick="orchDownloadPlaybook('${p.path.replace(/'/g, "\\'")}', '${p.name.replace(/'/g, "\\'")}')">⬇ Download</button>
              </div>
            </div>
          </div>
        `;
      });
      
      html += '</div>';
    }
    
    container.innerHTML = html;
  }

  window.orchRefreshPlaybooks = orchLoadPlaybooks;

  async function orchLoadServerOptionsForPlaybooks() {
    try {
      const data = await jfetch(API('api/orchestrator/servers'));
      if (!data.servers) return;
      
      const groups = new Set();
      const servers = [];
      
      data.servers.forEach(s => {
        servers.push(s);
        if (s.groups) {
          s.groups.split(',').forEach(g => {
            const trimmed = g.trim();
            if (trimmed) groups.add(trimmed);
          });
        }
      });
      
      document.querySelectorAll('.playbook-target').forEach(select => {
        let options = '<option value="">All servers</option>';
        
        if (groups.size > 0) {
          options += '<optgroup label="Server Groups">';
          groups.forEach(g => {
            options += `<option value="group:${g}">${g} (group)</option>`;
          });
          options += '</optgroup>';
        }
        
        if (servers.length > 0) {
          options += '<optgroup label="Individual Servers">';
          servers.forEach(s => {
            options += `<option value="server:${s.name}">${s.name}</option>`;
          });
          options += '</optgroup>';
        }
        
        select.innerHTML = options;
      });
    } catch (e) {
      console.error('Failed to load server options:', e);
    }
  }

  window.orchRunPlaybook = async function(name) {
    try {
      const safeId = name.replace(/[^a-zA-Z0-9]/g, '_');
      const targetSelect = document.getElementById(`target-${safeId}`);
      const target = targetSelect ? targetSelect.value : '';
      
      let inventoryGroup = null;
      if (target.startsWith('group:')) {
        inventoryGroup = target.replace('group:', '');
      } else if (target.startsWith('server:')) {
        inventoryGroup = target.replace('server:', '');
      }
      
      const logOutput = document.getElementById('orch-logs');
      if (logOutput) logOutput.innerHTML = '';
      
      const response = await jfetch(API(`api/orchestrator/run/${encodeURIComponent(name)}`), {
        method: 'POST',
        body: JSON.stringify({ 
          triggered_by: 'web_ui',
          inventory_group: inventoryGroup
        })
      });
      
      if (response.success) {
        currentJobId = response.job_id;
        appendLog(`[JARVIS] Starting playbook: ${name} (Job ID: ${response.job_id})`);
        if (inventoryGroup) {
          appendLog(`[JARVIS] Target: ${inventoryGroup}`);
        } else {
          appendLog(`[JARVIS] Target: All servers`);
        }
        appendLog(`[JARVIS] Streaming output...\n`);
        toast(`Playbook "${name}" started`, 'success');
        
        pollJobStatus(response.job_id);
      } else {
        appendLog(`[ERROR] Failed to start playbook: ${response.error || 'Unknown error'}`);
        toast('Failed to start playbook', 'error');
      }
    } catch (e) {
      appendLog(`[ERROR] ${e.message}`);
      toast('Failed to run playbook: ' + e.message, 'error');
    }
  };

  function pollJobStatus(jobId) {
    const interval = setInterval(async () => {
      try {
        const job = await jfetch(API(`api/orchestrator/status/${jobId}`));
        
        if (job.status === 'completed' || job.status === 'failed') {
          clearInterval(interval);
          appendLog(`\n[JARVIS] Job ${job.status.toUpperCase()} (Exit code: ${job.exit_code})`);
          orchLoadHistory();
        }
      } catch (e) {
        clearInterval(interval);
      }
    }, 2000);
  }

  // ============================================
  // SERVERS
  // ============================================
  window.orchLoadServers = async function() {
    const container = document.getElementById('servers-list');
    if (!container) return;
    
    try {
      container.innerHTML = '<div class="text-center text-muted">Loading servers...</div>';
      const data = await jfetch(API('api/orchestrator/servers'));
      
      if (!data.servers || data.servers.length === 0) {
        container.innerHTML = '<div class="text-center text-muted">No servers configured yet. Click "Add Server" to get started.</div>';
        return;
      }
      
      container.innerHTML = data.servers.map(s => `
        <div class="server-card">
          <div class="server-info">
            <div class="server-name">${s.name}</div>
            <div class="server-details">
              ${s.username}@${s.hostname}:${s.port} | 
              Groups: ${s.groups || 'none'} | 
              Auth: ${s.has_password ? '🔐 Password' : '🔑 Key'}
            </div>
            ${s.description ? `<div class="server-details" style="margin-top: 4px; color: var(--text-muted);">${s.description}</div>` : ''}
          </div>
          <div class="server-actions">
            <button class="btn" onclick="orchEditServer(${s.id})">✏️ Edit</button>
            <button class="btn danger" onclick="orchDeleteServer(${s.id}, '${s.name.replace(/'/g, "\\'")}')">🗑️ Delete</button>
          </div>
        </div>
      `).join('');
    } catch (e) {
      container.innerHTML = '<div class="text-center text-muted">Failed to load servers</div>';
      toast('Failed to load servers: ' + e.message, 'error');
    }
  };

  window.orchShowAddServer = function() {
    const modal = document.getElementById('server-modal');
    if (modal) {
      modal.classList.add('active');
      document.getElementById('server-form').reset();
    }
  };

  window.orchCloseServerModal = function() {
    const modal = document.getElementById('server-modal');
    if (modal) modal.classList.remove('active');
  };

  window.orchSaveServer = async function(event) {
    event.preventDefault();
    
    const data = {
      name: document.getElementById('srv-name').value,
      hostname: document.getElementById('srv-host').value,
      port: parseInt(document.getElementById('srv-port').value),
      username: document.getElementById('srv-user').value,
      password: document.getElementById('srv-pass').value,
      groups: document.getElementById('srv-groups').value,
      description: document.getElementById('srv-desc').value
    };
    
    try {
      const btn = event.submitter;
      btn.classList.add('loading');
      
      await jfetch(API('api/orchestrator/servers'), {
        method: 'POST',
        body: JSON.stringify(data)
      });
      
      orchCloseServerModal();
      orchLoadServers();
      toast('Server added successfully', 'success');
    } catch (e) {
      toast('Failed to add server: ' + e.message, 'error');
    } finally {
      const btn = event.submitter;
      if (btn) btn.classList.remove('loading');
    }
  };

  window.orchEditServer = async function(serverId) {
    const modal = document.getElementById('edit-server-modal');
    if (!modal) return;
    
    try {
      const server = await jfetch(API(`api/orchestrator/servers/${serverId}`));
      
      if (!server) {
        toast('Server not found', 'error');
        return;
      }
      
      document.getElementById('edit-srv-id').value = server.id;
      document.getElementById('edit-srv-name').value = server.name;
      document.getElementById('edit-srv-host').value = server.hostname;
      document.getElementById('edit-srv-port').value = server.port;
      document.getElementById('edit-srv-user').value = server.username;
      document.getElementById('edit-srv-pass').value = '';
      document.getElementById('edit-srv-groups').value = server.groups || '';
      document.getElementById('edit-srv-desc').value = server.description || '';
      
      modal.classList.add('active');
    } catch (e) {
      toast('Failed to load server: ' + e.message, 'error');
    }
  };

  window.orchCloseEditServerModal = function() {
    const modal = document.getElementById('edit-server-modal');
    if (modal) modal.classList.remove('active');
  };

  window.orchUpdateServer = async function(event) {
    event.preventDefault();
    
    const serverId = document.getElementById('edit-srv-id').value;
    const password = document.getElementById('edit-srv-pass').value;
    
    const data = {
      name: document.getElementById('edit-srv-name').value,
      hostname: document.getElementById('edit-srv-host').value,
      port: parseInt(document.getElementById('edit-srv-port').value),
      username: document.getElementById('edit-srv-user').value,
      groups: document.getElementById('edit-srv-groups').value,
      description: document.getElementById('edit-srv-desc').value
    };
    
    if (password) {
      data.password = password;
    }
    
    try {
      const btn = event.submitter;
      btn.classList.add('loading');
      
      await jfetch(API(`api/orchestrator/servers/${serverId}`), {
        method: 'PUT',
        body: JSON.stringify(data)
      });
      
      orchCloseEditServerModal();
      orchLoadServers();
      toast('Server updated successfully', 'success');
    } catch (e) {
      toast('Failed to update server: ' + e.message, 'error');
    } finally {
      const btn = event.submitter;
      if (btn) btn.classList.remove('loading');
    }
  };

  window.orchDeleteServer = async function(serverId, serverName) {
    if (!confirm(`Delete server "${serverName}"?`)) return;
    
    try {
      await jfetch(API(`api/orchestrator/servers/${serverId}`), {
        method: 'DELETE'
      });
      
      orchLoadServers();
      toast('Server deleted', 'success');
    } catch (e) {
      toast('Failed to delete server: ' + e.message, 'error');
    }
  };

  // ============================================
  // SCHEDULES (QOL: PAUSE, RUN NOW)
  // ============================================
  window.orchLoadSchedules = async function() {
    const tbody = document.getElementById('schedules-list');
    if (!tbody) return;
    
    try {
      tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">Loading schedules...</td></tr>';
      const data = await jfetch(API('api/orchestrator/schedules'));
      
      if (!data.schedules || data.schedules.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">No schedules configured. Click "Add Schedule" to create one.</td></tr>';
        return;
      }
      
      tbody.innerHTML = data.schedules.map(s => `
        <tr>
          <td><strong style="color: var(--accent-primary);">${s.name || s.playbook.split('/').pop()}</strong></td>
          <td style="font-size: 12px; color: var(--text-muted);">${s.playbook}</td>
          <td><code style="background: var(--surface-tertiary); padding: 2px 6px; border-radius: 4px; font-size: 11px;">${s.cron}</code></td>
          <td>${s.inventory_group || 'all'}</td>
          <td style="font-size: 12px;">${s.last_run ? new Date(s.last_run).toLocaleString() : 'Never'}</td>
          <td style="font-size: 12px;">${s.next_run ? new Date(s.next_run).toLocaleString() : '—'}</td>
          <td>
            <span class="status-badge ${s.enabled ? 'completed' : 'disabled'}">${s.enabled ? 'Active' : 'Paused'}</span>
            ${s.notify_on_completion ? '' : '<span class="status-badge disabled" style="margin-left: 4px;">🔕</span>'}
          </td>
          <td>
            <button class="btn" onclick="orchRunScheduleNow(${s.id}, '${s.playbook.replace(/'/g, "\\'")}', '${(s.inventory_group || '').replace(/'/g, "\\'")}')">▶ Run Now</button>
            <button class="btn" onclick="orchToggleSchedule(${s.id}, ${s.enabled})">${s.enabled ? '⏸ Pause' : '▶ Resume'}</button>
            <button class="btn" onclick="orchEditSchedule(${s.id})">✏️</button>
            <button class="btn danger" onclick="orchDeleteSchedule(${s.id}, '${(s.name || s.playbook).replace(/'/g, "\\'")}')">Delete</button>
          </td>
        </tr>
      `).join('');
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">Failed to load schedules</td></tr>';
      toast('Failed to load schedules: ' + e.message, 'error');
    }
  };

  // QOL: Run schedule immediately
  window.orchRunScheduleNow = async function(scheduleId, playbook, inventoryGroup) {
    try {
      const response = await jfetch(API(`api/orchestrator/run/${encodeURIComponent(playbook)}`), {
        method: 'POST',
        body: JSON.stringify({ 
          triggered_by: `manual_schedule_${scheduleId}`,
          inventory_group: inventoryGroup || null
        })
      });
      
      if (response.success) {
        toast('Schedule triggered successfully', 'success');
        orchLoadHistory();
        
        // Switch to playbooks tab to see live output
        document.querySelector('[data-orch-tab="playbooks"]').click();
        currentJobId = response.job_id;
        const logOutput = document.getElementById('orch-logs');
        if (logOutput) {
          logOutput.innerHTML = '';
          appendLog(`[JARVIS] Manually triggered schedule (Job ID: ${response.job_id})`);
          appendLog(`[JARVIS] Playbook: ${playbook}`);
          appendLog(`[JARVIS] Streaming output...\n`);
        }
        pollJobStatus(response.job_id);
      }
    } catch (e) {
      toast('Failed to trigger schedule: ' + e.message, 'error');
    }
  };

  window.orchShowAddSchedule = async function() {
    const modal = document.getElementById('schedule-modal');
    if (!modal) return;
    
    editingScheduleId = null;
    const modalTitle = modal.querySelector('h2');
    if (modalTitle) modalTitle.textContent = 'Create Schedule';
    
    try {
      const data = await jfetch(API('api/orchestrator/playbooks/organized'));
      const select = document.getElementById('sched-playbook');
      
      if (select && data.playbooks) {
        let options = '<option value="">Select a playbook...</option>';
        
        for (const [category, playbooks] of Object.entries(data.playbooks).sort()) {
          const categoryName = category === 'root' ? 'Root' : category.charAt(0).toUpperCase() + category.slice(1);
          options += `<optgroup label="${categoryName}">`;
          playbooks.forEach(p => {
            options += `<option value="${p.path}">${p.name}</option>`;
          });
          options += '</optgroup>';
        }
        
        select.innerHTML = options;
      }
      
      modal.classList.add('active');
      document.getElementById('schedule-form').reset();
      document.getElementById('sched-notify').checked = true;
    } catch (e) {
      toast('Failed to load playbooks: ' + e.message, 'error');
    }
  };

  window.orchEditSchedule = async function(scheduleId) {
    const modal = document.getElementById('schedule-modal');
    if (!modal) return;
    
    try {
      editingScheduleId = scheduleId;
      const modalTitle = modal.querySelector('h2');
      if (modalTitle) modalTitle.textContent = 'Edit Schedule';
      
      const schedule = await jfetch(API(`api/orchestrator/schedules/${scheduleId}`));
      
      if (!schedule) {
        toast('Schedule not found', 'error');
        return;
      }
      
      const playbooksData = await jfetch(API('api/orchestrator/playbooks/organized'));
      const select = document.getElementById('sched-playbook');
      
      if (select && playbooksData.playbooks) {
        let options = '<option value="">Select a playbook...</option>';
        for (const [category, playbooks] of Object.entries(playbooksData.playbooks).sort()) {
          const categoryName = category === 'root' ? 'Root' : category.charAt(0).toUpperCase() + category.slice(1);
          options += `<optgroup label="${categoryName}">`;
          playbooks.forEach(p => {
            options += `<option value="${p.path}">${p.name}</option>`;
          });
          options += '</optgroup>';
        }
        select.innerHTML = options;
      }
      
      document.getElementById('sched-name').value = schedule.name || '';
      document.getElementById('sched-playbook').value = schedule.playbook;
      document.getElementById('sched-group').value = schedule.inventory_group || '';
      document.getElementById('sched-cron').value = schedule.cron;
      document.getElementById('sched-notify').checked = schedule.notify_on_completion !== 0;
      
      modal.classList.add('active');
    } catch (e) {
      toast('Failed to load schedule: ' + e.message, 'error');
    }
  };

  window.orchCloseScheduleModal = function() {
    const modal = document.getElementById('schedule-modal');
    if (modal) modal.classList.remove('active');
    editingScheduleId = null;
  };

  window.orchApplyPreset = function() {
    const preset = document.getElementById('sched-preset').value;
    const cronInput = document.getElementById('sched-cron');
    if (preset && cronInput) {
      cronInput.value = preset;
    }
  };

  window.orchSaveSchedule = async function(event) {
    event.preventDefault();
    
    const jobName = document.getElementById('sched-name').value.trim();
    const playbookPath = document.getElementById('sched-playbook').value;
    
    const data = {
      name: jobName || playbookPath.split('/').pop(),
      playbook: playbookPath,
      cron: document.getElementById('sched-cron').value,
      inventory_group: document.getElementById('sched-group').value || null,
      notify_on_completion: document.getElementById('sched-notify').checked,
      enabled: true
    };
    
    try {
      const btn = event.submitter;
      btn.classList.add('loading');
      
      if (editingScheduleId) {
        await jfetch(API(`api/orchestrator/schedules/${editingScheduleId}`), {
          method: 'PUT',
          body: JSON.stringify(data)
        });
        toast('Schedule updated successfully', 'success');
      } else {
        await jfetch(API('api/orchestrator/schedules'), {
          method: 'POST',
          body: JSON.stringify(data)
        });
        toast('Schedule created successfully', 'success');
      }
      
      orchCloseScheduleModal();
      orchLoadSchedules();
    } catch (e) {
      toast('Failed to save schedule: ' + e.message, 'error');
    } finally {
      const btn = event.submitter;
      if (btn) btn.classList.remove('loading');
    }
  };

  window.orchToggleSchedule = async function(scheduleId, currentlyEnabled) {
    try {
      await jfetch(API(`api/orchestrator/schedules/${scheduleId}`), {
        method: 'PUT',
        body: JSON.stringify({ enabled: !currentlyEnabled })
      });
      
      orchLoadSchedules();
      toast(`Schedule ${!currentlyEnabled ? 'resumed' : 'paused'}`, 'success');
    } catch (e) {
      toast('Failed to toggle schedule: ' + e.message, 'error');
    }
  };

  window.orchDeleteSchedule = async function(scheduleId, jobName) {
    if (!confirm(`Delete schedule "${jobName}"?`)) return;
    
    try {
      await jfetch(API(`api/orchestrator/schedules/${scheduleId}`), {
        method: 'DELETE'
      });
      
      orchLoadSchedules();
      toast('Schedule deleted', 'success');
    } catch (e) {
      toast('Failed to delete schedule: ' + e.message, 'error');
    }
  };

  // ============================================
  // HISTORY (QOL: VIEW OUTPUT, RETRY, CANCEL)
  // ============================================
  window.orchLoadHistory = async function() {
    const tbody = document.getElementById('history-list');
    if (!tbody) return;
    
    try {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Loading history...</td></tr>';
      const data = await jfetch(API('api/orchestrator/history?limit=20'));
      
      if (!data.jobs || data.jobs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No job history yet</td></tr>';
        return;
      }
      
      tbody.innerHTML = data.jobs.map(j => {
        const displayName = j.job_name || j.playbook.split('/').pop();
        const isRunning = j.status === 'running';
        
        return `
        <tr onclick="orchViewJobOutput(${j.id})" style="cursor: pointer;">
          <td>
            <strong style="color: var(--accent-primary);">${displayName}</strong>
            <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">${j.playbook}</div>
          </td>
          <td><span class="status-badge ${j.status}">${j.status.toUpperCase()}</span></td>
          <td style="font-size: 12px;">${new Date(j.started_at).toLocaleString()}</td>
          <td style="font-size: 12px;">${j.completed_at ? new Date(j.completed_at).toLocaleString() : '—'}</td>
          <td>${j.exit_code !== null ? j.exit_code : '—'}</td>
          <td style="font-size: 12px;">${j.triggered_by}</td>
          <td onclick="event.stopPropagation()">
            ${isRunning ? 
              `<button class="btn danger" onclick="orchCancelJob(${j.id}, ${j.pid || 0})">✕ Cancel</button>` :
              j.status === 'failed' ? 
              `<button class="btn" onclick="orchRetryJob('${j.playbook.replace(/'/g, "\\'")}', '${(j.inventory_group || '').replace(/'/g, "\\'")}')">↻ Retry</button>` :
              ''
            }
          </td>
        </tr>
      `;
      }).join('');
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Failed to load history</td></tr>';
      toast('Failed to load history: ' + e.message, 'error');
    }
  };

  // QOL: View job output
  window.orchViewJobOutput = async function(jobId) {
    try {
      const job = await jfetch(API(`api/orchestrator/status/${jobId}`));
      
      if (!job) {
        toast('Job not found', 'error');
        return;
      }
      
      const modal = document.getElementById('job-output-modal');
      if (!modal) return;
      
      const displayName = job.job_name || job.playbook.split('/').pop();
      document.getElementById('job-output-title').textContent = displayName;
      document.getElementById('job-output-status').innerHTML = `<span class="status-badge ${job.status}">${job.status.toUpperCase()}</span>`;
      document.getElementById('job-output-exit-code').textContent = job.exit_code !== null ? job.exit_code : '—';
      document.getElementById('job-output-started').textContent = new Date(job.started_at).toLocaleString();
      document.getElementById('job-output-completed').textContent = job.completed_at ? new Date(job.completed_at).toLocaleString() : '—';
      
      const outputContainer = document.getElementById('job-output-content');
      if (job.output) {
        const lines = job.output.split('\n');
        outputContainer.innerHTML = lines.map(line => 
          `<div class="log-line">${line || ' '}</div>`
        ).join('');
      } else {
        outputContainer.innerHTML = '<div class="text-center text-muted">No output available</div>';
      }
      
      modal.classList.add('active');
    } catch (e) {
      toast('Failed to load job output: ' + e.message, 'error');
    }
  };

  window.orchCloseJobOutputModal = function() {
    const modal = document.getElementById('job-output-modal');
    if (modal) modal.classList.remove('active');
  };

  // QOL: Retry failed job
  window.orchRetryJob = async function(playbook, inventoryGroup) {
    try {
      const response = await jfetch(API(`api/orchestrator/run/${encodeURIComponent(playbook)}`), {
        method: 'POST',
        body: JSON.stringify({ 
          triggered_by: 'retry',
          inventory_group: inventoryGroup || null
        })
      });
      
      if (response.success) {
        toast('Job retried successfully', 'success');
        orchLoadHistory();
        
        // Switch to playbooks tab
        document.querySelector('[data-orch-tab="playbooks"]').click();
        currentJobId = response.job_id;
        const logOutput = document.getElementById('orch-logs');
        if (logOutput) {
          logOutput.innerHTML = '';
          appendLog(`[JARVIS] Retrying job (Job ID: ${response.job_id})`);
          appendLog(`[JARVIS] Streaming output...\n`);
        }
        pollJobStatus(response.job_id);
      }
    } catch (e) {
      toast('Failed to retry job: ' + e.message, 'error');
    }
  };

  // QOL: Cancel running job
  window.orchCancelJob = async function(jobId, pid) {
    if (!confirm('Cancel this running job?')) return;
    
    try {
      await jfetch(API(`api/orchestrator/jobs/${jobId}/cancel`), {
        method: 'POST',
        body: JSON.stringify({ pid })
      });
      
      toast('Job cancelled', 'success');
      orchLoadHistory();
    } catch (e) {
      toast('Failed to cancel job: ' + e.message, 'error');
    }
  };

  // ============================================
  // HISTORY MANAGEMENT
  // ============================================
  window.orchShowHistorySettings = async function() {
    const modal = document.getElementById('history-modal');
    if (!modal) return;
    
    try {
      const stats = await jfetch(API('api/orchestrator/history/stats'));
      document.getElementById('history-total').textContent = stats.total_entries || 0;
    } catch (e) {
      console.error('Failed to load history stats:', e);
    }
    
    modal.classList.add('active');
  };

  window.orchCloseHistoryModal = function() {
    const modal = document.getElementById('history-modal');
    if (modal) modal.classList.remove('active');
  };

  window.orchPurgeHistory = async function(criteria) {
    let confirmMsg = '';
    
    switch(criteria) {
      case 'all':
        confirmMsg = '⚠️ DELETE ALL HISTORY?\n\nThis will permanently delete all execution history and cannot be undone.\n\nAre you absolutely sure?';
        break;
      case 'failed':
        confirmMsg = 'Delete all failed job executions?';
        break;
      case 'completed':
        confirmMsg = 'Delete all successful job executions?';
        break;
      case 'older_than_30':
        confirmMsg = 'Delete all history older than 30 days?';
        break;
      case 'older_than_90':
        confirmMsg = 'Delete all history older than 90 days?';
        break;
    }
    
    if (!confirm(confirmMsg)) return;
    
    try {
      const result = await jfetch(API('api/orchestrator/history/purge'), {
        method: 'POST',
        body: JSON.stringify({ criteria })
      });
      
      toast(`Deleted ${result.deleted} entries`, 'success');
      orchLoadHistory();
      
      if (criteria === 'all') {
        orchCloseHistoryModal();
      } else {
        orchShowHistorySettings();
      }
    } catch (e) {
      toast('Failed to purge history: ' + e.message, 'error');
    }
  };

  // ============================================
  // INITIALIZATION
  // ============================================
  function initOrchestrator() {
    connectWebSocket();
    initPlaybookUpload();
    initPlaybookSearch();
    orchLoadPlaybooks();
    
    console.log('[Orchestrator] Frontend initialized - Sprint 4 QoL features active');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initOrchestrator);
  } else {
    initOrchestrator();
  }
})();
