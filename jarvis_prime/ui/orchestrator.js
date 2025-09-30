// orchestrator.js - Orchestrator tab functionality for Jarvis Prime

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
  // PLAYBOOKS
  // ============================================
  window.orchLoadPlaybooks = async function() {
    const container = document.getElementById('playbooks-list');
    if (!container) return;
    
    try {
      container.innerHTML = '<div class="text-center text-muted">Loading playbooks...</div>';
      const data = await jfetch(API('api/orchestrator/playbooks'));
      
      if (!data.playbooks || data.playbooks.length === 0) {
        container.innerHTML = '<div class="text-center text-muted">No playbooks found. Add .sh, .py, or .yml files to /share/jarvis_prime/playbooks/</div>';
        return;
      }
      
      container.innerHTML = data.playbooks.map(p => `
        <div class="playbook-card">
          <div class="playbook-name">${p.name}</div>
          <div class="playbook-meta">
            Type: ${p.type.toUpperCase()} | 
            Modified: ${new Date(p.modified).toLocaleString()}
          </div>
          <div class="playbook-actions">
            <button class="btn primary" onclick="orchRunPlaybook('${p.name}')">▶ Run</button>
          </div>
        </div>
      `).join('');
    } catch (e) {
      container.innerHTML = '<div class="text-center text-muted">Failed to load playbooks</div>';
      toast('Failed to load playbooks: ' + e.message, 'error');
    }
  };

  window.orchRefreshPlaybooks = orchLoadPlaybooks;

  window.orchRunPlaybook = async function(name) {
    try {
      // Clear logs
      const logOutput = document.getElementById('orch-logs');
      if (logOutput) logOutput.innerHTML = '';
      
      const response = await jfetch(API(`api/orchestrator/run/${encodeURIComponent(name)}`), {
        method: 'POST',
        body: JSON.stringify({ triggered_by: 'web_ui' })
      });
      
      if (response.success) {
        currentJobId = response.job_id;
        appendLog(`[JARVIS] Starting playbook: ${name} (Job ID: ${response.job_id})`);
        appendLog(`[JARVIS] Streaming output...\n`);
        toast(`Playbook "${name}" started`, 'success');
        
        // Poll for completion
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
            <button class="btn danger" onclick="orchDeleteServer(${s.id}, '${s.name}')">🗑️ Delete</button>
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
  // SCHEDULES
  // ============================================
  window.orchLoadSchedules = async function() {
    const tbody = document.getElementById('schedules-list');
    if (!tbody) return;
    
    try {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Loading schedules...</td></tr>';
      const data = await jfetch(API('api/orchestrator/schedules'));
      
      if (!data.schedules || data.schedules.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No schedules configured. Click "Add Schedule" to create one.</td></tr>';
        return;
      }
      
      tbody.innerHTML = data.schedules.map(s => `
        <tr>
          <td>${s.playbook}</td>
          <td><code style="background: var(--surface-tertiary); padding: 2px 6px; border-radius: 4px;">${s.cron}</code></td>
          <td>${s.inventory_group || 'all'}</td>
          <td>${s.last_run ? new Date(s.last_run).toLocaleString() : 'Never'}</td>
          <td>${s.next_run ? new Date(s.next_run).toLocaleString() : '—'}</td>
          <td><span class="status-badge ${s.enabled ? 'completed' : 'disabled'}">${s.enabled ? 'Enabled' : 'Disabled'}</span></td>
          <td>
            <button class="btn" onclick="orchToggleSchedule(${s.id}, ${s.enabled})">${s.enabled ? 'Disable' : 'Enable'}</button>
            <button class="btn danger" onclick="orchDeleteSchedule(${s.id}, '${s.playbook}')">Delete</button>
          </td>
        </tr>
      `).join('');
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Failed to load schedules</td></tr>';
      toast('Failed to load schedules: ' + e.message, 'error');
    }
  };

  window.orchShowAddSchedule = async function() {
    const modal = document.getElementById('schedule-modal');
    if (!modal) return;
    
    // Populate playbook dropdown
    try {
      const data = await jfetch(API('api/orchestrator/playbooks'));
      const select = document.getElementById('sched-playbook');
      
      if (select && data.playbooks) {
        select.innerHTML = '<option value="">Select a playbook...</option>' +
          data.playbooks.map(p => `<option value="${p.name}">${p.name}</option>`).join('');
      }
      
      modal.classList.add('active');
      document.getElementById('schedule-form').reset();
    } catch (e) {
      toast('Failed to load playbooks: ' + e.message, 'error');
    }
  };

  window.orchCloseScheduleModal = function() {
    const modal = document.getElementById('schedule-modal');
    if (modal) modal.classList.remove('active');
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
    
    const data = {
      playbook: document.getElementById('sched-playbook').value,
      cron: document.getElementById('sched-cron').value,
      inventory_group: document.getElementById('sched-group').value || null,
      enabled: true
    };
    
    try {
      const btn = event.submitter;
      btn.classList.add('loading');
      
      await jfetch(API('api/orchestrator/schedules'), {
        method: 'POST',
        body: JSON.stringify(data)
      });
      
      orchCloseScheduleModal();
      orchLoadSchedules();
      toast('Schedule created successfully', 'success');
    } catch (e) {
      toast('Failed to create schedule: ' + e.message, 'error');
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
      toast(`Schedule ${!currentlyEnabled ? 'enabled' : 'disabled'}`, 'success');
    } catch (e) {
      toast('Failed to toggle schedule: ' + e.message, 'error');
    }
  };

  window.orchDeleteSchedule = async function(scheduleId, playbookName) {
    if (!confirm(`Delete schedule for "${playbookName}"?`)) return;
    
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
  // HISTORY
  // ============================================
  window.orchLoadHistory = async function() {
    const tbody = document.getElementById('history-list');
    if (!tbody) return;
    
    try {
      tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Loading history...</td></tr>';
      const data = await jfetch(API('api/orchestrator/history?limit=20'));
      
      if (!data.jobs || data.jobs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No job history yet</td></tr>';
        return;
      }
      
      tbody.innerHTML = data.jobs.map(j => `
        <tr>
          <td>${j.playbook}</td>
          <td><span class="status-badge ${j.status}">${j.status.toUpperCase()}</span></td>
          <td>${new Date(j.started_at).toLocaleString()}</td>
          <td>${j.completed_at ? new Date(j.completed_at).toLocaleString() : '—'}</td>
          <td>${j.exit_code !== null ? j.exit_code : '—'}</td>
          <td>${j.triggered_by}</td>
        </tr>
      `).join('');
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Failed to load history</td></tr>';
      toast('Failed to load history: ' + e.message, 'error');
    }
  };

  // ============================================
  // INITIALIZATION
  // ============================================
  function initOrchestrator() {
    // Connect WebSocket for live logs
    connectWebSocket();
    
    // Load initial data
    orchLoadPlaybooks();
    
    console.log('[Orchestrator] Frontend initialized');
  }

  // Wait for DOM to be ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initOrchestrator);
  } else {
    initOrchestrator();
  }
})();