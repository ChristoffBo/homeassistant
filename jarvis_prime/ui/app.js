(function () {
  
  // ============================================
  // SERVICE WORKER REGISTRATION (PWA)
  // ============================================
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('sw.js')
        .then((registration) => {
          console.log('✅ Jarvis Service Worker registered:', registration.scope);
          
          // Check for updates every minute
          setInterval(() => {
            registration.update();
          }, 60000);

          // Handle service worker updates
          registration.addEventListener('updatefound', () => {
            const newWorker = registration.installing;
            
            newWorker.addEventListener('statechange', () => {
              if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                console.log('🔄 New version of Jarvis Prime available');
                
                // Show toast if available
                if (typeof toast === 'function') {
                  toast('New version available! Reload to update.', 'info');
                }
              }
            });
          });
        })
        .catch((error) => {
          console.error('❌ Service Worker registration failed:', error);
        });
    });
  }

  // Request notification permission (for future push notifications)
  if ('Notification' in window && Notification.permission === 'default') {
    console.log('💬 Notification permission not yet granted');
  }
  
  /* =============== CORE UTILITIES =============== */
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // API configuration - WORKS FOR BOTH INGRESS AND DIRECT ACCESS
  function apiRoot() {
    if (window.JARVIS_API_BASE) {
      let v = String(window.JARVIS_API_BASE);
      return v.endsWith('/') ? v : v + '/';
    }
    try {
      const u = new URL(document.baseURI);
      let p = u.pathname;
      
      // Strip index.html if present
      if (p.endsWith('/index.html')) {
        p = p.slice(0, -'/index.html'.length);
      }
      
      // Only strip /ui/ if NOT under ingress
      if (!p.includes('/ingress/') && p.endsWith('/ui/')) {
        p = p.slice(0, -4);
      }
      
      if (!p.endsWith('/')) p += '/';
      u.pathname = p;
      return u.toString();
    } catch (e) {
      return document.baseURI;
    }
  }
  
  const ROOT = apiRoot();
  const API = (path) => new URL(String(path).replace(/^\/+/, ''), ROOT).toString();

  // Expose API helper globally for other modules
  window.API = API;

  /* =============== THEME TOGGLE =============== */
  const THEME_KEY = 'jarvis_theme_mode';
  
  // Load saved theme on startup
  function loadTheme() {
    const savedTheme = localStorage.getItem(THEME_KEY);
    if (savedTheme === 'dark') {
      document.body.classList.add('dark-mode');
      updateThemeIcon(true);
    }
  }
  
  // Toggle theme
  function toggleTheme() {
    const isDark = document.body.classList.toggle('dark-mode');
    localStorage.setItem(THEME_KEY, isDark ? 'dark' : 'light');
    updateThemeIcon(isDark);
  }
  
  // Update icon based on theme
  function updateThemeIcon(isDark) {
    const icon = $('#theme-icon');
    if (icon) {
      icon.textContent = isDark ? '☀️' : '🌙';
    }
  }
  
  // Setup theme toggle button
  const themeToggle = $('#theme-toggle');
  if (themeToggle) {
    themeToggle.addEventListener('click', toggleTheme);
  }
  
  // Load theme immediately
  loadTheme();

  // Toast notifications
  window.showToast = function(msg, type = 'info') {
    const d = document.createElement('div');
    d.className = `toast ${type}`;
    d.textContent = msg;
    $('#toast')?.appendChild(d);
    setTimeout(() => d.remove(), 4000);
  };

  // Alias for compatibility
  const toast = window.showToast;

  // Enhanced fetch with better error handling
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
      console.error('API Error:', error);
      throw error;
    }
  }

  // System status management
  function updateSystemStatus(status, message) {
    const dot = $('#connection-status');
    const text = $('#system-status-text');
    
    if (dot) {
      dot.className = `status-dot ${status}`;
    }
    if (text) {
      text.textContent = message;
    }
  }

  function formatTime(ts) {
    try {
      const v = Number(ts || 0);
      const ms = v > 1e12 ? v : v * 1000;
      return new Date(ms).toLocaleString();
    } catch {
      return '';
    }
  }

  /* =============== TAB MANAGEMENT =============== */
  $$('.nav-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.nav-tab').forEach(x => x.classList.remove('active'));
      btn.classList.add('active');
      $$('.tab-panel').forEach(t => t.classList.remove('active'));
      const pane = $('#' + btn.dataset.tab);
      if (pane) {
        pane.classList.add('active');
        
        // Load data when switching to specific tabs
        if (btn.dataset.tab === 'analytics') {
          if (typeof analyticsLoadHealthScore === 'function') {
            analyticsLoadHealthScore();
            analyticsLoadDashboard();
          }
        }
        
        if (btn.dataset.tab === 'dashboard') {
          updateDashboardMetrics();
        }
      }
    });
  });

  // Expose switchTab globally for other modules
  window.switchTab = function(tabName) {
    const btn = $(`.nav-tab[data-tab="${tabName}"]`);
    if (btn) btn.click();
  };

  /* =============== DASHBOARD METRICS =============== */
  async function updateDashboardMetrics() {
    // Update inbox metrics
    if (INBOX_ITEMS && INBOX_ITEMS.length !== undefined) {
      const now = new Date();
      const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
      const todayCount = INBOX_ITEMS.filter(i => (i.created_at || 0) >= start).length;
      
      // Total messages
      const dashInboxTotal = $('#dash-inbox-total');
      if (dashInboxTotal) dashInboxTotal.textContent = INBOX_ITEMS.length;
      
      // Messages today
      const dashInboxToday = $('#dash-inbox-today');
      if (dashInboxToday) dashInboxToday.textContent = todayCount;
      
      // Error messages
      const errorCount = INBOX_ITEMS.filter(i => 
        /error|fail|exception/i.test(`${i.title || ''} ${i.body || i.message || ''}`)
      ).length;
      const dashInboxErrors = $('#dash-inbox-errors');
      if (dashInboxErrors) dashInboxErrors.textContent = errorCount;
    }
    
    // Update chat status
    const chatStatus = $('#chat-status');
    const dashChatStatus = $('#dash-chat-status');
    if (chatStatus && dashChatStatus) {
      dashChatStatus.textContent = chatStatus.textContent || 'Ready';
    }
    
    // Update commands count
    const dashCommands = $('#dash-commands');
    const dashLastCommand = $('#dash-last-command');
    
    if (dashCommands && wakeHistory) {
      dashCommands.textContent = wakeHistory.length;
    }
    
    const lastWake = $('#last-wake');
    if (dashLastCommand && lastWake) {
      dashLastCommand.textContent = lastWake.textContent || 'No commands sent';
    }
    
    // Update playbooks/schedules counts
    await updateOrchestrationMetrics();
    
    // Update health score from analytics if available
    const healthScore = $('#health-score');
    const dashHealth = $('#dash-health');
    if (healthScore && dashHealth) {
      dashHealth.textContent = healthScore.textContent || '0%';
      
      // Color code based on health
      const score = parseFloat(healthScore.textContent) || 0;
      if (score >= 99) {
        dashHealth.style.color = '#10b981';
      } else if (score >= 95) {
        dashHealth.style.color = '#0ea5e9';
      } else if (score >= 90) {
        dashHealth.style.color = '#f59e0b';
      } else {
        dashHealth.style.color = '#ef4444';
      }
    }
    
    // Update activity feed
    updateDashboardActivity();
  }

  // Update orchestration metrics
  async function updateOrchestrationMetrics() {
    try {
      // Get playbooks count
      const playbooksData = await jfetch(API('api/orchestrator/playbooks/organized')).catch(() => null);
      if (playbooksData && playbooksData.playbooks) {
        let totalPlaybooks = 0;
        for (const category in playbooksData.playbooks) {
          totalPlaybooks += playbooksData.playbooks[category].length;
        }
        const dashPlaybooks = $('#dash-playbooks');
        if (dashPlaybooks) dashPlaybooks.textContent = totalPlaybooks;
      }
      
      // Get schedules count
      const schedulesData = await jfetch(API('api/orchestrator/schedules')).catch(() => null);
      if (schedulesData && schedulesData.schedules) {
        const enabledSchedules = schedulesData.schedules.filter(s => s.enabled).length;
        const dashSchedules = $('#dash-schedules');
        if (dashSchedules) dashSchedules.textContent = `${enabledSchedules} scheduled`;
      }
      
      // Get job history for success/error counts
      const historyData = await jfetch(API('api/orchestrator/history?limit=100')).catch(() => null);
      if (historyData && historyData.jobs) {
        const successCount = historyData.jobs.filter(j => j.status === 'completed' && j.exit_code === 0).length;
        const errorCount = historyData.jobs.filter(j => j.status === 'failed' || j.exit_code !== 0).length;
        
        const dashOrchSuccess = $('#dash-orch-success');
        const dashOrchErrors = $('#dash-orch-errors');
        
        if (dashOrchSuccess) dashOrchSuccess.textContent = successCount;
        if (dashOrchErrors) dashOrchErrors.textContent = errorCount;
      }
    } catch (e) {
      console.error('Failed to update orchestration metrics:', e);
    }
  }

  // Expose globally
  window.updateDashboardMetrics = updateDashboardMetrics;

  function updateDashboardActivity() {
    const activityList = $('#dash-activity');
    if (!activityList) return;
    
    const activities = [];
    
    // Add recent inbox messages (last 3)
    if (INBOX_ITEMS && INBOX_ITEMS.length > 0) {
      const recentMessages = INBOX_ITEMS.slice(-3).reverse();
      recentMessages.forEach(msg => {
        const timeAgo = getTimeAgo(msg.created_at);
        activities.push({
          icon: '📬',
          color: 'rgba(16, 185, 129, 0.12)',
          iconColor: '#10b981',
          title: `New message: ${msg.title || 'Untitled'}`,
          time: timeAgo,
          timestamp: msg.created_at,
          type: 'message',
          messageId: msg.id
        });
      });
    }
    
    // Add recent wake commands (last 2)
    if (wakeHistory && wakeHistory.length > 0) {
      const recentCommands = wakeHistory.slice(0, 2);
      recentCommands.forEach(cmd => {
        const timeAgo = getTimeAgo(cmd.timestamp / 1000);
        activities.push({
          icon: '⚡',
          color: 'rgba(56, 189, 248, 0.12)',
          iconColor: '#38bdf8',
          title: `Command executed: jarvis ${cmd.command}`,
          time: timeAgo,
          timestamp: cmd.timestamp / 1000,
          type: 'command'
        });
      });
    }
    
    // Sort by timestamp (newest first)
    activities.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
    
    // Limit to 4 most recent
    const limitedActivities = activities.slice(0, 4);
    
    if (limitedActivities.length === 0) {
      activityList.innerHTML = `
        <li class="activity-item">
          <div class="activity-icon" style="background: rgba(14, 165, 233, 0.12); color: #0ea5e9;">
            <svg class="icon" fill="none" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/>
              <path d="M12 6v6l4 2" stroke="currentColor" stroke-width="2"/>
            </svg>
          </div>
          <div class="activity-content">
            <div class="activity-title">System initialized</div>
            <div class="activity-time">Just now</div>
          </div>
        </li>
      `;
      return;
    }
    
    activityList.innerHTML = limitedActivities.map((activity, index) => `
      <li class="activity-item" data-activity-type="${activity.type}" data-message-id="${activity.messageId || ''}" style="cursor: pointer;">
        <div class="activity-icon" style="background: ${activity.color}; color: ${activity.iconColor};">
          ${activity.icon}
        </div>
        <div class="activity-content">
          <div class="activity-title">${activity.title}</div>
          <div class="activity-time">${activity.time}</div>
        </div>
      </li>
    `).join('');
    
    // Add click handlers to activity items
    $$('#dash-activity .activity-item').forEach(item => {
      item.addEventListener('click', () => {
        const type = item.dataset.activityType;
        const messageId = item.dataset.messageId;
        
        if (type === 'message' && messageId) {
          // Switch to inbox tab
          switchTab('inbox');
          
          // Wait a bit for the tab to load, then select the message
          setTimeout(() => {
            selectRowById(messageId);
          }, 200);
        }
      });
    });
  }

  function getTimeAgo(timestamp) {
    if (!timestamp) return 'Just now';
    
    const now = Date.now() / 1000;
    const seconds = Math.floor(now - timestamp);
    
    if (seconds < 60) return 'Just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)} minutes ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} hours ago`;
    return `${Math.floor(seconds / 86400)} days ago`;
  }

  /* =============== CHAT FUNCTIONALITY =============== */
  function updateChatStatus(status) {
    const statusEl = $('#chat-status');
    if (statusEl) {
      statusEl.textContent = status;
      updateDashboardMetrics();
    }
  }

  async function sendChatMessage() {
    const input = $('#chat-input');
    if (!input) return;
    
    const text = input.value.trim();
    if (!text) return;

    const sendBtn = $('#chat-send');
    
    try {
      if (sendBtn) sendBtn.classList.add('loading');
      updateChatStatus('Processing...');
      
      input.value = '';
      
      console.log('Sending chat message via emit endpoint:', `chat ${text}`);
      
      await jfetch(API('internal/emit'), {
        method: 'POST',
        body: JSON.stringify({ 
          title: 'chat',
          body: `chat ${text}`,
          source: 'webui-chat',
          priority: 5
        })
      });
      
      updateChatStatus('Sent to AI...');
      toast('Message sent to Jarvis AI', 'success');
      
      // Reset status after a delay
      setTimeout(() => {
        updateChatStatus('Ready');
      }, 3000);
      
    } catch (e) {
      console.error('Chat error:', e);
      updateChatStatus('Error');
      toast('Chat failed: ' + e.message, 'error');
      
      setTimeout(() => {
        updateChatStatus('Ready');
      }, 3000);
    } finally {
      if (sendBtn) sendBtn.classList.remove('loading');
    }
  }

  // Chat event listeners
  const chatSendBtn = $('#chat-send');
  const chatInput = $('#chat-input');

  if (chatSendBtn) {
    chatSendBtn.addEventListener('click', sendChatMessage);
  }

  if (chatInput) {
    chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        sendChatMessage();
      }
    });
    
    // Auto-resize chat input
    chatInput.addEventListener('input', function() {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });
  }

  /* =============== INBOX FUNCTIONALITY =============== */
  let INBOX_ITEMS = [];
  let SELECTED_ID = null;

  function updateCounters(items) {
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
    const today = items.filter(i => (i.created_at || 0) >= start).length;
    const archived = items.filter(i => i.saved).length;
    const errors = items.filter(i => /error|fail|exception/i.test(`${i.title || ''} ${i.body || i.message || ''}`)).length;
    
    $('#msg-today').textContent = today;
    $('#msg-arch').textContent = archived;
    $('#msg-err').textContent = errors;
  }

  function renderPreview(m) {
    if (!m) {
      $('#pv-title').textContent = 'No message selected';
      $('#pv-meta').textContent = '—';
      $('#pv-body').innerHTML = '<div class="text-center text-muted">Select a message to preview its contents</div>';
      return;
    }
    
    $('#pv-title').textContent = m.title || '(no title)';
    const bits = [];
    if (m.source) bits.push(`Source: ${m.source}`);
    if (m.created_at) bits.push(`Time: ${formatTime(m.created_at)}`);
    $('#pv-meta').textContent = bits.join(' • ') || '—';
    
    const body = (m.body || m.message || '').trim();
    $('#pv-body').textContent = body || '(empty message)';
  }

  function selectRowById(id) {
    SELECTED_ID = id;
    $$('#msg-body tr').forEach(tr => tr.classList.toggle('selected', tr.dataset.id === String(id)));
    const m = INBOX_ITEMS.find(x => String(x.id) === String(id));
    renderPreview(m);
  }

  async function loadInbox() {
    const tb = $('#msg-body');
    try {
      updateSystemStatus('connecting', 'Loading...');
      const data = await jfetch(API('api/messages'));
      const items = data && data.items ? data.items : (Array.isArray(data) ? data : []);
      INBOX_ITEMS = Array.isArray(items) ? items : [];
      tb.innerHTML = '';

      if (!INBOX_ITEMS.length) {
        tb.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No messages in inbox</td></tr>';
        updateCounters([]);
        renderPreview(null);
        updateSystemStatus('', 'Connected');
        updateDashboardMetrics();
        return;
      }

      updateCounters(INBOX_ITEMS);
      
      for (const m of INBOX_ITEMS) {
        const tr = document.createElement('tr');
        tr.dataset.id = m.id;
        tr.innerHTML = `
          <td>${formatTime(m.created_at)}</td>
          <td>${m.source || ''}</td>
          <td>${m.title || ''}</td>
          <td>
            <button class="btn" data-id="${m.id}" data-act="arch">
              ${m.saved ? 'Unarchive' : 'Archive'}
            </button>
            <button class="btn danger" data-id="${m.id}" data-act="del">Delete</button>
          </td>`;
        tb.appendChild(tr);
      }

      const follow = $('#pv-follow')?.checked;
      const still = SELECTED_ID && INBOX_ITEMS.some(x => String(x.id) === String(SELECTED_ID));
      
      if (still) {
        selectRowById(SELECTED_ID);
      } else if (follow && INBOX_ITEMS.length) {
        const last = INBOX_ITEMS[INBOX_ITEMS.length - 1];
        selectRowById(last.id);
      } else {
        renderPreview(null);
      }
      
      updateSystemStatus('', 'Connected');
      updateDashboardMetrics();
    } catch (e) {
      console.error('Inbox load error:', e);
      tb.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Failed to load messages</td></tr>';
      toast('Failed to load inbox', 'error');
      renderPreview(null);
      updateSystemStatus('error', 'Connection Error');
    }
  }

  // Message actions
  $('#msg-body').addEventListener('click', (ev) => {
    const btn = ev.target.closest('button[data-act]');
    if (btn) {
      const id = btn.dataset.id;
      const act = btn.dataset.act;
      
      (async () => {
        try {
          btn.classList.add('loading');
          
          if (act === 'del') {
            if (!confirm('Delete this message?')) return;
            await jfetch(API('api/messages/' + id), { method: 'DELETE' });
            toast('Message deleted', 'success');
          } else if (act === 'arch') {
            await jfetch(API(`api/messages/${id}/save`), {
              method: 'POST',
              body: JSON.stringify({})
            });
            toast('Archive status toggled', 'success');
          }
          
          await loadInbox();
        } catch (e) {
          toast('Action failed: ' + e.message, 'error');
        } finally {
          btn.classList.remove('loading');
        }
      })();
      return;
    }
    
    const tr = ev.target.closest('tr[data-id]');
    if (tr && tr.dataset.id) selectRowById(tr.dataset.id);
  });

  // Delete all messages
  $('#del-all').addEventListener('click', async () => {
    if (!confirm('Delete ALL messages? This cannot be undone!')) return;
    
    const keep = $('#keep-arch')?.checked ? 1 : 0;
    const btn = $('#del-all');
    
    try {
      btn.classList.add('loading');
      await jfetch(API(`api/messages?keep_saved=${keep}`), { method: 'DELETE' });
      toast('All messages deleted', 'success');
      await loadInbox();
    } catch (e) {
      toast('Delete all failed: ' + e.message, 'error');
    } finally {
      btn.classList.remove('loading');
    }
  });

  /* =============== WAKE FUNCTIONALITY =============== */
  let wakeHistory = [];

  function addWakeToHistory(command) {
    wakeHistory.unshift({
      command,
      timestamp: Date.now()
    });
    
    if (wakeHistory.length > 20) {
      wakeHistory = wakeHistory.slice(0, 20);
    }
    
    updateWakeHistory();
    const lastWakeEl = $('#last-wake');
    if (lastWakeEl) {
      lastWakeEl.textContent = new Date().toLocaleTimeString();
    }
    updateDashboardMetrics();
  }

  function updateWakeHistory() {
    const historyDiv = $('#wake-history');
    if (!historyDiv) return;
    
    if (wakeHistory.length === 0) {
      historyDiv.innerHTML = '<div class="text-center text-muted">No commands executed yet</div>';
      return;
    }
    
    historyDiv.innerHTML = wakeHistory.map(item => 
      `<div class="wake-history-item">
        <div class="wake-command">jarvis ${item.command}</div>
        <div class="wake-time">${new Date(item.timestamp).toLocaleString()}</div>
      </div>`
    ).join('');
  }

  async function sendWake() {
    const input = $('#wake-input');
    const text = input.value.trim();
    if (!text) return;

    const sendBtn = $('#wake-send');
    
    try {
      sendBtn.classList.add('loading');
      
      await jfetch(API('internal/wake'), {
        method: 'POST',
        body: JSON.stringify({ text })
      });
      
      addWakeToHistory(text);
      input.value = '';
      toast('Command executed', 'success');
      
    } catch (e) {
      console.error('Wake command error:', e);
      toast('Command failed: ' + e.message, 'error');
    } finally {
      sendBtn.classList.remove('loading');
    }
  }

  $('#wake-send')?.addEventListener('click', sendWake);
  $('#wake-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      sendWake();
    }
  });

  /* =============== PURGE FUNCTIONALITY =============== */
  const PURGE_KEY = 'jarvis_purge_days';
  
  function getDaysSel() {
    const v = ($('#purge-select')?.value || '7').trim();
    const n = parseInt(v, 10);
    return isNaN(n) ? 7 : n;
  }
  
  function saveDaysSel(n) {
    try { localStorage.setItem(PURGE_KEY, String(n)); } catch {}
    $('#purge-select') && ($('#purge-select').value = String(n));
    
    jfetch(API('api/inbox/settings'), {
      method: 'POST',
      body: JSON.stringify({ retention_days: n })
    }).catch(() => {});
  }
  
  function restoreDaysSel() {
    let v = 7;
    try {
      const s = localStorage.getItem(PURGE_KEY);
      if (s) v = parseInt(s, 10) || 7;
    } catch {}
    saveDaysSel(v);
  }
  
  async function runPurge(days) {
    const btn = $('#purge-now');
    try {
      btn.classList.add('loading');
      await jfetch(API('api/inbox/purge'), {
        method: 'POST',
        body: JSON.stringify({ days: Number(days) })
      });
      toast(`Purged messages older than ${days} day(s)`, 'success');
      await loadInbox();
    } catch (e) {
      toast('Purge failed: ' + e.message, 'error');
    } finally {
      btn.classList.remove('loading');
    }
  }

  $('#purge-select')?.addEventListener('change', () => saveDaysSel(getDaysSel()));
  $('#purge-now')?.addEventListener('click', () => runPurge(getDaysSel()));

  /* =============== LIVE UPDATES =============== */
  (function startStream() {
    let es = null, backoff = 1000;
    
    function connect() {
      try { es && es.close(); } catch {}
      
      updateSystemStatus('connecting', 'Connecting...');
      es = new EventSource(API('api/stream'));
      
      es.onopen = () => {
        backoff = 1000;
        updateSystemStatus('', 'Connected');
      };
      
      es.onerror = () => {
        try { es.close(); } catch {}
        updateSystemStatus('error', 'Reconnecting...');
        setTimeout(connect, Math.min(backoff, 15000));
        backoff = Math.min(backoff * 2, 15000);
      };
      
      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data || '{}');
          
          if (['created', 'deleted', 'deleted_all', 'saved', 'purged'].includes(data.event)) {
            loadInbox().then(() => {
              if (data.event === 'created' && $('#pv-follow')?.checked) {
                if (data.id) selectRowById(data.id);
              }
            });
          }
        } catch {}
      };
    }
    
    connect();
    setInterval(loadInbox, 5 * 60 * 1000);
  })();

  /* =============== INITIALIZATION =============== */
  restoreDaysSel();
  loadInbox();
  updateWakeHistory();
  
  // Initial dashboard update after a short delay
  setTimeout(() => {
    updateDashboardMetrics();
    toast('Jarvis Prime Control System initialized successfully', 'success');
  }, 1000);
})();
