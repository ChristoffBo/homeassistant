/**
 * 🧩 Veil UI - Privacy-First DNS/DHCP Management Interface
 * For Jarvis Prime
 */
const VeilUI = {
  stats: {},
  config: {},
  updateInterval: null,
  logs: [],  // Store logs locally for export
 
  /**
   * Initialize Veil UI
   */
  async init() {
    console.log('[Veil] Initializing UI');
    await this.loadStats();
    await this.loadConfig();
    this.renderUI();
    this.startAutoRefresh();
  },
 
  /**
   * Load statistics from API
   */
  async loadStats() {
    try {
      const response = await fetch('/api/veil/stats');
      this.stats = await response.json();
    } catch (error) {
      console.error('[Veil] Failed to load stats:', error);
      toast('Failed to load Veil statistics', 'error');
    }
  },
 
  /**
   * Load configuration from API
   */
  async loadConfig() {
    try {
      const response = await fetch('/api/veil/config');
      this.config = await response.json();
    } catch (error) {
      console.error('[Veil] Failed to load config:', error);
      toast('Failed to load Veil configuration', 'error');
    }
  },
 
  /**
   * Load query logs from API
   */
  async loadLogs() {
    try {
      const response = await fetch('/api/veil/logs');
      this.logs = await response.json();
      this.updateLogsDisplay();
    } catch (error) {
      console.error('[Veil] Failed to load logs:', error);
      toast('Failed to load query logs', 'error');
    }
  },
 
  /**
   * Start auto-refresh timer
   */
  startAutoRefresh() {
    if (this.updateInterval) clearInterval(this.updateInterval);
   
    this.updateInterval = setInterval(async () => {
      await this.loadStats();
      this.updateStatsDisplay();
      // Refresh logs if logs tab is active
      const activeTab = document.querySelector('.tab-button.active').dataset.tab;
      if (activeTab === 'logs') {
        await this.loadLogs();
      }
    }, 5000);
  },
 
  /**
   * Stop auto-refresh
   */
  stopAutoRefresh() {
    if (this.updateInterval) {
      clearInterval(this.updateInterval);
      this.updateInterval = null;
    }
  },
 
  /**
   * Render main UI
   */
  renderUI() {
    const container = document.getElementById('veil-container');
    if (!container) return;
   
    container.innerHTML = `
      <div class="veil-dashboard">
        <!-- Header -->
        <div class="veil-header">
          <h2>🧩 Veil - Privacy-First DNS/DHCP</h2>
          <div class="veil-status" id="veil-status">
            <span class="status-dot status-healthy"></span>
            <span>Loading...</span>
          </div>
        </div>
       
        <!-- Stats Cards -->
        <div class="veil-stats-grid">
          <div class="stat-card">
            <div class="stat-icon">🔍</div>
            <div class="stat-content">
              <div class="stat-value" id="stat-queries">0</div>
              <div class="stat-label">DNS Queries</div>
            </div>
          </div>
         
          <div class="stat-card">
            <div class="stat-icon">⚡</div>
            <div class="stat-content">
              <div class="stat-value" id="stat-cached">0%</div>
              <div class="stat-label">Cache Hit Rate</div>
            </div>
          </div>
         
          <div class="stat-card">
            <div class="stat-icon">🛡️</div>
            <div class="stat-content">
              <div class="stat-value" id="stat-blocked">0</div>
              <div class="stat-label">Blocked</div>
            </div>
          </div>
         
          <div class="stat-card">
            <div class="stat-icon">📊</div>
            <div class="stat-content">
              <div class="stat-value" id="stat-cache-size">0</div>
              <div class="stat-label">Cache Size</div>
            </div>
          </div>
         
          <div class="stat-card">
            <div class="stat-icon">🔒</div>
            <div class="stat-content">
              <div class="stat-value" id="stat-privacy">0</div>
              <div class="stat-label">Privacy Features</div>
            </div>
          </div>
         
          <div class="stat-card">
            <div class="stat-icon">🖥️</div>
            <div class="stat-content">
              <div class="stat-value" id="stat-dhcp">0</div>
              <div class="stat-label">DHCP Leases</div>
            </div>
          </div>
         
          <!-- New Stat Cards for Metrics -->
          <div class="stat-card">
            <div class="stat-icon">⏱️</div>
            <div class="stat-content">
              <div class="stat-value" id="stat-avg-time">0ms</div>
              <div class="stat-label">Avg Response Time</div>
            </div>
          </div>
          
          <div class="stat-card">
            <div class="stat-icon">📈</div>
            <div class="stat-content">
              <div class="stat-value" id="stat-protocol">UDP</div>
              <div class="stat-label">Top Protocol</div>
            </div>
          </div>
        </div>
       
        <!-- Tabs -->
        <div class="veil-tabs">
          <button class="tab-button active" data-tab="dns">DNS</button>
          <button class="tab-button" data-tab="dhcp">DHCP</button>
          <button class="tab-button" data-tab="privacy">Privacy</button>
          <button class="tab-button" data-tab="blocking">Blocking</button>
          <button class="tab-button" data-tab="settings">Settings</button>
          <button class="tab-button" data-tab="logs">Logs</button> <!-- New Logs Tab -->
          <button class="tab-button" data-tab="health">Health</button> <!-- New Health Tab -->
        </div>
       
        <!-- Tab Content -->
        <div class="veil-tab-content">
          <div id="tab-dns" class="tab-pane active"></div>
          <div id="tab-dhcp" class="tab-pane"></div>
          <div id="tab-privacy" class="tab-pane"></div>
          <div id="tab-blocking" class="tab-pane"></div>
          <div id="tab-settings" class="tab-pane"></div>
          <div id="tab-logs" class="tab-pane"></div>
          <div id="tab-health" class="tab-pane"></div>
        </div>
      </div>
    `;
   
    this.attachEventListeners();
    this.renderDNSTab();
    this.renderDHCPTab();
    this.renderPrivacyTab();
    this.renderBlockingTab();
    this.renderSettingsTab();
    this.renderLogsTab();
    this.renderHealthTab();
    this.updateStatsDisplay();
  },
 
  /**
   * Attach event listeners
   */
  attachEventListeners() {
    // Tab switching
    document.querySelectorAll('.tab-button').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const tab = e.target.dataset.tab;
        this.switchTab(tab);
      });
    });
  },
 
  /**
   * Switch tabs
   */
  switchTab(tab) {
    document.querySelectorAll('.tab-button').forEach(btn => {
      btn.classList.remove('active');
    });
    document.querySelectorAll('.tab-pane').forEach(pane => {
      pane.classList.remove('active');
    });
   
    document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
    document.getElementById(`tab-${tab}`).classList.add('active');
  },
 
  /**
   * Update stats display
   */
  updateStatsDisplay() {
    const s = this.stats;

    // Status
    const statusEl = document.getElementById('veil-status');
    if (statusEl) {
      const isHealthy = s.dns_queries > 0 || this.config.enabled;
      statusEl.innerHTML = `
        <span class="status-dot ${isHealthy ? 'status-healthy' : 'status-degraded'}"></span>
        <span>${isHealthy ? 'Healthy' : 'Inactive'}</span>
      `;
    }

    // Stats
    document.getElementById('stat-queries').textContent = (s.dns_queries || 0).toLocaleString();

    // ✅ FIX: use nested fallback for cache hits
    const cacheHits = s.dns_cached || (s.cache && s.cache.hits) || 0;
    const cacheHitRate = s.dns_queries > 0
      ? Math.round((cacheHits / s.dns_queries) * 100)
      : 0;
    document.getElementById('stat-cached').textContent = `${cacheHitRate}%`;

    document.getElementById('stat-blocked').textContent = (s.dns_blocked || 0).toLocaleString();

    // ✅ FIX: use nested fallback for cache size
    const cacheSize = s.cache_size || (s.cache && s.cache.size) || 0;
    document.getElementById('stat-cache-size').textContent = cacheSize.toLocaleString();

    const privacyFeatures =
      (s.dns_padded || 0) +
      (s.dns_0x20 || 0) +
      (s.dns_dnssec_validated || 0);
    document.getElementById('stat-privacy').textContent = privacyFeatures.toLocaleString();

    document.getElementById('stat-dhcp').textContent = (s.dhcp_leases || 0).toLocaleString();

    // New Metrics
    document.getElementById('stat-avg-time').textContent = `${Math.round(s.avg_response_time * 1000 || 0)}ms`;

    const protocols = s.protocol_usage || {};
    const totalProtocol = Object.values(protocols).reduce((a, b) => a + b, 0) || 1;
    const topProtocol = Object.entries(protocols).reduce((a, b) => b[1] > a[1] ? b : a, ['UDP', 0])[0].toUpperCase();
    document.getElementById('stat-protocol').textContent = topProtocol;

    // Update Top Clients and Blocked Domains if in dashboard view
    this.updateTopDisplays();

    // Update Category Counters
    this.updateCategoryCounters();

    // Update Protocol Bars if health tab active
    this.updateProtocolBars();
  },

  /**
   * Update top clients and blocked domains displays
   */
  updateTopDisplays() {
    const s = this.stats;

    // Top Clients
    const topClients = s.top_clients || [];
    const topClientsContainer = document.getElementById('top-clients');
    if (topClientsContainer) {
      topClientsContainer.innerHTML = topClients.map(([ip, count]) => `
        <div class="record-row">
          <div>${ip}</div>
          <div>${count.toLocaleString()}</div>
        </div>
      `).join('');
    }

    // Top Blocked Domains
    const topBlocked = s.top_blocked || [];
    const topBlockedContainer = document.getElementById('top-blocked');
    if (topBlockedContainer) {
      topBlockedContainer.innerHTML = topBlocked.map(([domain, count]) => `
        <div class="record-row">
          <div>${domain}</div>
          <div>${count.toLocaleString()}</div>
        </div>
      `).join('');
    }
  },

  /**
   * Update category counters
   */
  updateCategoryCounters() {
    const s = this.stats;
    const categories = s.block_categories || {};
    const categoryContainer = document.getElementById('category-counters');
    if (categoryContainer) {
      categoryContainer.innerHTML = Object.entries(categories).map(([cat, count]) => `
        <div class="stat-card">
          <div class="stat-value">${count.toLocaleString()}</div>
          <div class="stat-label">${cat.charAt(0).toUpperCase() + cat.slice(1)}</div>
        </div>
      `).join('');
    }
  },

  /**
   * Update protocol bars
   */
  updateProtocolBars() {
    const s = this.stats;
    const protocols = s.protocol_usage || {};
    const total = Object.values(protocols).reduce((a, b) => a + b, 0) || 1;
    const container = document.getElementById('protocol-bars');
    if (container) {
      container.innerHTML = Object.entries(protocols).map(([proto, count]) => `
        <div class="progress-bar">
          <div class="progress-fill" style="width: ${(count / total * 100)}%;"></div>
        </div>
        <div>${proto.toUpperCase()}: ${Math.round((count / total * 100))}%</div>
      `).join('');
    }
  },

  /**
   * Update logs display
   */
  updateLogsDisplay() {
    const table = document.getElementById('query-log-table');
    if (table) {
      table.innerHTML = this.logs.map(log => `
        <div class="record-row">
          <div>${new Date(log.timestamp * 1000).toLocaleString()}</div>
          <div>${log.client_ip}</div>
          <div>${log.domain}</div>
          <div>${log.result}</div>
          <div>${Math.round(log.latency)}ms</div>
        </div>
      `).join('');
    }
  },

  /**
   * Export logs
   */
  exportLogs(type) {
    let content, filename, mime;
    if (type === 'json') {
      content = JSON.stringify(this.logs, null, 2);
      filename = 'veil_logs.json';
      mime = 'application/json';
    } else if (type === 'csv') {
      content = 'timestamp,client_ip,domain,result,latency\n' + this.logs.map(l => `${new Date(l.timestamp * 1000).toLocaleString()},${l.client_ip},${l.domain},${l.result},${l.latency}`).join('\n');
      filename = 'veil_logs.csv';
      mime = 'text/csv';
    } else {
      return;
    }
    const blob = new Blob([content], {type: mime});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  },

  /**
   * Backup configuration
   */
  backupConfig() {
    const content = JSON.stringify(this.config, null, 2);
    const blob = new Blob([content], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'veil_config.json';
    a.click();
    URL.revokeObjectURL(url);
  },

  /**
   * Restore configuration
   */
  restoreConfig(file) {
    const reader = new FileReader();
    reader.onload = async (e) => {
      try {
        const data = JSON.parse(e.target.result);
        await this.updateConfig(data);
        toast('Configuration restored', 'success');
        location.reload();
      } catch (err) {
        toast('Invalid configuration file', 'error');
      }
    };
    reader.readAsText(file);
  },

  /**
   * Show add upstream dialog
   */
  showAddUpstreamDialog() {
    // Simple prompt for simplicity; can be replaced with modal
    const server = prompt('Enter upstream server (e.g., https://dns.example.com)');
    const type = prompt('Enter type (udp, doh, dot, doq)');
    if (server && type) {
      this.addUpstream(server, type);
    }
  },

  /**
   * Add upstream
   */
  async addUpstream(server, type) {
    try {
      const response = await fetch('/api/veil/upstream/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ server, type })
      });
      if (response.ok) {
        toast('Upstream added', 'success');
        await this.loadConfig();
        this.renderUpstreamList();
      }
    } catch (error) {
      toast('Failed to add upstream', 'error');
    }
  },

  /**
   * Remove upstream
   */
  async removeUpstream(server) {
    if (confirm(`Remove upstream ${server}?`)) {
      try {
        const response = await fetch('/api/veil/upstream/remove', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ server })
        });
        if (response.ok) {
          toast('Upstream removed', 'success');
          await this.loadConfig();
          this.renderUpstreamList();
        }
      } catch (error) {
        toast('Failed to remove upstream', 'error');
      }
    }
  },

  /**
   * Show add conditional forward dialog
   */
  showAddConditionalDialog() {
    const domain = prompt('Enter domain (e.g., example.com)');
    const upstream = prompt('Enter upstream server');
    const type = prompt('Enter type (udp, doh, dot, doq)');
    if (domain && upstream && type) {
      this.addConditional(domain, upstream, type);
    }
  },

  /**
   * Add conditional forward
   */
  async addConditional(domain, upstream, type) {
    try {
      const response = await fetch('/api/veil/conditional/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain, upstream, type })
      });
      if (response.ok) {
        toast('Conditional forward added', 'success');
        await this.loadConfig();
        this.renderConditionalList();
      }
    } catch (error) {
      toast('Failed to add conditional forward', 'error');
    }
  },

  /**
   * Render DNS Tab
   */
  renderDNSTab() {
    const container = document.getElementById('tab-dns');
    container.innerHTML = `
      <div class="veil-section">
        <h3>DNS Server</h3>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="dns-enabled" ${this.config.enabled ? 'checked' : ''}>
            Enable DNS Server
          </label>
        </div>
       
        <div class="setting-row">
          <label>DNS Port</label>
          <input type="number" id="dns-port" value="${this.config.dns_port}" min="1" max="65535">
        </div>
       
        <div class="setting-row">
          <label>Bind Address</label>
          <input type="text" id="dns-bind" value="${this.config.dns_bind}" placeholder="0.0.0.0">
        </div>
      </div>
     
      <div class="veil-section">
        <h3>Cache</h3>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="cache-enabled" ${this.config.cache_enabled ? 'checked' : ''}>
            Enable Caching
          </label>
        </div>
       
        <div class="setting-row">
          <label>Cache TTL (seconds)</label>
          <input type="number" id="cache-ttl" value="${this.config.cache_ttl}" min="60">
        </div>
       
        <div class="setting-row">
          <label>Max Cache Size</label>
          <input type="number" id="cache-max-size" value="${this.config.cache_max_size}" min="100">
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="stale-serving" ${this.config.stale_serving ? 'checked' : ''}>
            Stale Cache Serving
          </label>
        </div>
       
        <div class="button-group">
          <button class="btn-secondary" onclick="VeilUI.flushCache()">Flush Cache</button>
          <button class="btn-secondary" onclick="VeilUI.prewarmCache()">Prewarm Cache</button>
        </div>
      </div>
     
      <div class="veil-section">
        <h3>Upstream Servers</h3>
       
        <div class="upstream-list" id="upstream-list"></div>
       
        <div class="button-group">
          <button class="btn-primary" onclick="VeilUI.showAddUpstreamDialog()">Add Upstream</button>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="upstream-parallel" ${this.config.upstream_parallel ? 'checked' : ''}>
            Parallel Upstream Queries
          </label>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="upstream-rotation" ${this.config.upstream_rotation ? 'checked' : ''}>
            Rotate Upstream Servers
          </label>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="dynamic-weighting" ${this.config.dynamic_upstream_weighting ? 'checked' : ''}>
            Dynamic Weighting (prefer fastest)
          </label>
        </div>
       
        <div class="setting-row">
          <label>Upstream Timeout (seconds)</label>
          <input type="number" id="upstream-timeout" value="${this.config.upstream_timeout}" min="1" max="10" step="0.1">
        </div>
      </div>
     
      <div class="veil-section">
        <h3>Local Records</h3>
        <div id="local-records-list"></div>
        <div class="button-group">
          <button class="btn-primary" onclick="VeilUI.showAddRecordDialog()">Add Record</button>
        </div>
      </div>
     
      <div class="veil-section">
        <h3>Conditional Forwards</h3>
        <div id="conditional-list"></div>
        <div class="button-group">
          <button class="btn-primary" onclick="VeilUI.showAddConditionalDialog()">Add Conditional</button>
        </div>
      </div>
     
      <div class="button-group">
        <button class="btn-primary" onclick="VeilUI.saveDNSSettings()">Save DNS Settings</button>
      </div>
    `;
   
    this.renderUpstreamList();
    this.renderLocalRecords();
    this.renderConditionalList();
  },
 
  /**
   * Render upstream servers list
   */
  renderUpstreamList() {
    const container = document.getElementById('upstream-list');
    if (!container) return;
   
    const servers = this.config.upstream_servers || [];
    const health = this.stats.upstream_health || {};
   
    container.innerHTML = servers.map(srv => {
      const server = srv.server;
      const type = srv.type.toUpperCase();
      const status = health[server];
      const isHealthy = !status || status.healthy;
      const latency = status ? status.latency : 0;
     
      return `
        <div class="upstream-server">
          <span class="status-dot ${isHealthy ? 'status-healthy' : 'status-error'}"></span>
          <span>${type}</span>
          <span class="server-ip">${server}</span>
          ${latency > 0 ? `<span class="server-latency">${Math.round(latency * 1000)}ms</span>` : ''}
          <button class="btn-icon" onclick="VeilUI.removeUpstream('${server}')">Remove</button>
        </div>
      `;
    }).join('');
  },
 
  /**
   * Render conditional forwards list
   */
  renderConditionalList() {
    const container = document.getElementById('conditional-list');
    if (!container) return;
   
    const forwards = this.config.conditional_forwards || [];
   
    container.innerHTML = forwards.map(fwd => `
      <div class="record-row">
        <div>${fwd.domain}</div>
        <div>${fwd.upstream.type.toUpperCase()} - ${fwd.upstream.server}</div>
        <button class="btn-icon" onclick="VeilUI.removeConditional('${fwd.domain}')">Remove</button>
      </div>
    `).join('');
  },

  /**
   * Remove conditional forward
   */
  async removeConditional(domain) {
    if (confirm(`Remove conditional for ${domain}?`)) {
      try {
        const response = await fetch('/api/veil/conditional/remove', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ domain })
        });
        if (response.ok) {
          toast('Conditional removed', 'success');
          await this.loadConfig();
          this.renderConditionalList();
        }
      } catch (error) {
        toast('Failed to remove conditional', 'error');
      }
    }
  },

  /**
   * Render local records
   */
  renderLocalRecords() {
    const container = document.getElementById('local-records-list');
    if (!container) return;
   
    const records = this.config.local_records || {};
   
    if (Object.keys(records).length === 0) {
      container.innerHTML = '<p class="empty-state">No local records configured</p>';
      return;
    }
   
    container.innerHTML = `
      <div class="records-table">
        ${Object.entries(records).map(([domain, record]) => `
          <div class="record-row">
            <div class="record-domain">${domain}</div>
            <div class="record-type">${record.type}</div>
            <div class="record-value">${record.value}</div>
            <button class="btn-icon" onclick="VeilUI.deleteRecord('${domain}')" title="Delete">
              <i class="icon-trash"></i>
            </button>
          </div>
        `).join('')}
      </div>
    `;
  },
 
  /**
   * Render DHCP Tab
   */
  renderDHCPTab() {
    const container = document.getElementById('tab-dhcp');
    container.innerHTML = `
      <div class="veil-section">
        <h3>DHCP Server</h3>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="dhcp-enabled" ${this.config.dhcp_enabled ? 'checked' : ''}>
            Enable DHCP Server
          </label>
        </div>
       
        <div class="setting-row">
          <label>DHCP Port</label>
          <input type="number" id="dhcp-port" value="${this.config.dhcp_port}" min="1" max="65535">
        </div>
       
        <div class="setting-row">
          <label>Interface</label>
          <input type="text" id="dhcp-interface" value="${this.config.dhcp_interface}" placeholder="eth0">
        </div>
      </div>
     
      <div class="veil-section">
        <h3>Network Configuration</h3>
       
        <div class="setting-row">
          <label>Subnets</label>
          <input type="text" id="dhcp-subnet" value="${this.config.dhcp_subnet}" placeholder="192.168.1.0">
        </div>
       
        <div class="setting-row">
          <label>Netmask</label>
          <input type="text" id="dhcp-netmask" value="${this.config.dhcp_netmask}" placeholder="255.255.255.0">
        </div>
       
        <div class="setting-row">
          <label>Gateway</label>
          <input type="text" id="dhcp-gateway" value="${this.config.dhcp_gateway}" placeholder="192.168.1.1">
        </div>
       
        <div class="setting-row">
          <label>IP Range Start</label>
          <input type="text" id="dhcp-range-start" value="${this.config.dhcp_range_start}" placeholder="192.168.1.100">
        </div>
       
        <div class="setting-row">
          <label>IP Range End</label>
          <input type="text" id="dhcp-range-end" value="${this.config.dhcp_range_end}" placeholder="192.168.1.200">
        </div>
       
        <div class="setting-row">
          <label>Lease Time (seconds)</label>
          <input type="number" id="dhcp-lease-time" value="${this.config.dhcp_lease_time}" min="600">
        </div>
       
        <div class="setting-row">
          <label>Domain Name</label>
          <input type="text" id="dhcp-domain" value="${this.config.dhcp_domain || ''}" placeholder="local">
        </div>
      </div>
     
      <div class="veil-section">
        <h3>DNS Servers</h3>
        <div class="setting-row">
          <label>DNS Servers (comma-separated)</label>
          <input type="text" id="dhcp-dns-servers" value="${(this.config.dhcp_dns_servers || []).join(', ')}" placeholder="192.168.1.1">
        </div>
      </div>
     
      <div class="veil-section">
        <h3>NTP Servers</h3>
        <div class="setting-row">
          <label>NTP Servers (comma-separated)</label>
          <input type="text" id="dhcp-ntp-servers" value="${(this.config.dhcp_ntp_servers || []).join(', ')}" placeholder="pool.ntp.org, time.google.com">
        </div>
        <p class="help-text">Enter IP addresses or hostnames. Hostnames will be resolved automatically.</p>
      </div>
     
      <div class="veil-section">
        <h3>Options</h3>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="dhcp-ping-check" ${this.config.dhcp_ping_check ? 'checked' : ''}>
            Ping Check Before Offer
          </label>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="dhcp-relay-support" ${this.config.dhcp_relay_support ? 'checked' : ''}>
            DHCP Relay Support
          </label>
        </div>
      </div>
     
      <div class="veil-section">
        <h3>Active Leases</h3>
        <div id="dhcp-leases-list"></div>
        <button class="btn-secondary" onclick="VeilUI.loadDHCPLeases()">Refresh Leases</button>
      </div>
     
      <div class="veil-section">
        <h3>Static Leases</h3>
        <div id="dhcp-static-list"></div>
        <button class="btn-primary" onclick="VeilUI.showAddStaticLeaseDialog()">Add Static Lease</button>
      </div>
     
      <div class="button-group">
        <button class="btn-primary" onclick="VeilUI.saveDHCPSettings()">Save DHCP Settings</button>
      </div>
    `;
   
    this.loadDHCPLeases();
    this.renderStaticLeases();
  },

  /**
   * Render static leases
   */
  renderStaticLeases() {
    const container = document.getElementById('dhcp-static-list');
    if (!container) return;
   
    const leases = this.config.dhcp_static_leases || {};
   
    container.innerHTML = Object.entries(leases).map(([mac, lease]) => `
      <div class="record-row">
        <div>${mac}</div>
        <div>${lease.ip}</div>
        <div>${lease.hostname || ''}</div>
        <button class="btn-icon" onclick="VeilUI.removeStaticLease('${mac}')">Remove</button>
      </div>
    `).join('');
  },

  /**
   * Show add static lease dialog
   */
  showAddStaticLeaseDialog() {
    const mac = prompt('Enter MAC address');
    const ip = prompt('Enter IP address');
    const hostname = prompt('Enter hostname (optional)');
    if (mac && ip) {
      this.addStaticLease(mac, ip, hostname);
    }
  },

  /**
   * Add static lease
   */
  async addStaticLease(mac, ip, hostname) {
    try {
      const response = await fetch('/api/veil/dhcp/static', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mac, ip, hostname })
      });
      if (response.ok) {
        toast('Static lease added', 'success');
        await this.loadConfig();
        this.renderStaticLeases();
      }
    } catch (error) {
      toast('Failed to add static lease', 'error');
    }
  },

  /**
   * Remove static lease
   */
  async removeStaticLease(mac) {
    if (confirm(`Remove static lease for ${mac}?`)) {
      try {
        const response = await fetch('/api/veil/dhcp/static/remove', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mac })
        });
        if (response.ok) {
          toast('Static lease removed', 'success');
          await this.loadConfig();
          this.renderStaticLeases();
        }
      } catch (error) {
        toast('Failed to remove static lease', 'error');
      }
    }
  },

  /**
   * Load and display DHCP leases
   */
  async loadDHCPLeases() {
    try {
      const response = await fetch('/api/veil/dhcp/leases');
      const leases = await response.json().leases;
      const container = document.getElementById('dhcp-leases-list');
      container.innerHTML = leases.map(lease => `
        <div class="record-row">
          <div>${lease.mac}</div>
          <div>${lease.ip}</div>
          <div>${lease.hostname || ''}</div>
          <div>${new Date(lease.expiry * 1000).toLocaleString()}</div>
          <button class="btn-icon" onclick="VeilUI.deleteLease('${lease.mac}')">Delete</button>
        </div>
      `).join('');
    } catch (error) {
      console.error('[Veil] Failed to load DHCP leases:', error);
      toast('Failed to load DHCP leases', 'error');
    }
  },
 
  /**
   * Render Privacy Tab
   */
  renderPrivacyTab() {
    const container = document.getElementById('tab-privacy');
    container.innerHTML = `
      <div class="veil-section">
        <h3>Encrypted Transports</h3>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="doh-enabled" ${this.config.doh_enabled ? 'checked' : ''}>
            Enable DoH
          </label>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="dot-enabled" ${this.config.dot_enabled ? 'checked' : ''}>
            Enable DoT
          </label>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="doq-enabled" ${this.config.doq_enabled ? 'checked' : ''}>
            Enable DoQ
          </label>
        </div>
      </div>
     
      <div class="veil-section">
        <h3>Privacy Options</h3>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="ecs-strip" ${this.config.ecs_strip ? 'checked' : ''}>
            Strip ECS
          </label>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="padding-enabled" ${this.config.padding_enabled ? 'checked' : ''}>
            Enable Padding
          </label>
        </div>
       
        <div class="setting-row">
          <label>Padding Block Size</label>
          <input type="number" id="padding-block-size" value="${this.config.padding_block_size}" min="128">
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="case-randomization" ${this.config.case_randomization ? 'checked' : ''}>
            Case Randomization (0x20)
          </label>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="qname-minimization" ${this.config.qname_minimization ? 'checked' : ''}>
            QNAME Minimization
          </label>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="query-jitter" ${this.config.query_jitter ? 'checked' : ''}>
            Query Jitter
          </label>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="dnssec-validate" ${this.config.dnssec_validate ? 'checked' : ''}>
            DNSSEC Validation
          </label>
        </div>
      </div>
     
      <div class="veil-section">
        <h3>Rate Limiting</h3>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="rate-limit-enabled" ${this.config.rate_limit_enabled ? 'checked' : ''}>
            Enable Rate Limiting
          </label>
        </div>
       
        <div class="setting-row">
          <label>Queries Per Second</label>
          <input type="number" id="rate-limit-qps" value="${this.config.rate_limit_qps}" min="1">
        </div>
       
        <div class="setting-row">
          <label>Burst Allowance</label>
          <input type="number" id="rate-limit-burst" value="${this.config.rate_limit_burst}" min="1">
        </div>
      </div>
     
      <div class="veil-section">
        <h3>SafeSearch</h3>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="safesearch-enabled" ${this.config.safesearch_enabled ? 'checked' : ''}>
            Enable SafeSearch
          </label>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="safesearch-google" ${this.config.safesearch_google ? 'checked' : ''}>
            Google
          </label>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="safesearch-bing" ${this.config.safesearch_bing ? 'checked' : ''}>
            Bing
          </label>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="safesearch-duckduckgo" ${this.config.safesearch_duckduckgo ? 'checked' : ''}>
            DuckDuckGo
          </label>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="safesearch-youtube" ${this.config.safesearch_youtube ? 'checked' : ''}>
            YouTube
          </label>
        </div>
      </div>
     
      <div class="veil-section">
        <h3>SafeSearch Schedule</h3>
       
        <div class="setting-row">
          <label>Start Time (HH:MM)</label>
          <input type="text" id="safesearch-start" value="${this.config.safesearch_schedule?.start || ''}" placeholder="08:00">
        </div>
       
        <div class="setting-row">
          <label>End Time (HH:MM)</label>
          <input type="text" id="safesearch-end" value="${this.config.safesearch_schedule?.end || ''}" placeholder="20:00">
        </div>
      </div>
     
      <div class="button-group">
        <button class="btn-primary" onclick="VeilUI.savePrivacySettings()">Save Privacy Settings</button>
      </div>
    `;
  },
 
  /**
   * Render Blocking Tab
   */
  renderBlockingTab() {
    const container = document.getElementById('tab-blocking');
    container.innerHTML = `
      <div class="veil-section">
        <h3>Blocking</h3>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="blocking-enabled" ${this.config.blocking_enabled ? 'checked' : ''}>
            Enable Blocking
          </label>
        </div>
       
        <div class="setting-row">
          <label>Response Type</label>
          <select id="block-response-type">
            <option value="NXDOMAIN" ${this.config.block_response_type === 'NXDOMAIN' ? 'selected' : ''}>NXDOMAIN</option>
            <option value="CUSTOM_IP" ${this.config.block_response_type === 'CUSTOM_IP' ? 'selected' : ''}>Custom IP</option>
          </select>
        </div>
       
        <div class="setting-row">
          <label>Custom Block IP</label>
          <input type="text" id="block-custom-ip" value="${this.config.block_custom_ip}" placeholder="0.0.0.0">
        </div>
      </div>
     
      <div class="veil-section">
        <h3>Blocklists</h3>
       
        <div class="setting-row">
          <label>Blocklist URLs (one per line)</label>
          <textarea id="blocklist-urls" rows="5">${(this.config.blocklist_urls || []).join('\n')}</textarea>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="blocklist-update-enabled" ${this.config.blocklist_update_enabled ? 'checked' : ''}>
            Auto Update
          </label>
        </div>
       
        <div class="setting-row">
          <label>Update Interval (seconds)</label>
          <input type="number" id="blocklist-update-interval" value="${this.config.blocklist_update_interval}" min="3600">
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="blocklist-update-on-start" ${this.config.blocklist_update_on_start ? 'checked' : ''}>
            Update on Start
          </label>
        </div>
       
        <div class="button-group">
          <button class="btn-secondary" onclick="VeilUI.updateBlocklists()">Update Now</button>
          <button class="btn-secondary" onclick="VeilUI.reloadBlocklists()">Reload</button>
          <button class="btn-secondary" onclick="VeilUI.showUploadBlocklist()">Upload Blocklist</button>
        </div>
      </div>
     
      <div class="veil-section">
        <h3>Blacklist (Always Block)</h3>
        <div id="blacklist-container"></div>
        <div class="input-group">
          <input type="text" id="blacklist-domain" placeholder="example.com">
          <button class="btn-primary" onclick="VeilUI.addToBlacklist()">Add</button>
        </div>
      </div>
     
      <div class="veil-section">
        <h3>Whitelist (Never Block)</h3>
        <div id="whitelist-container"></div>
        <div class="input-group">
          <input type="text" id="whitelist-domain" placeholder="example.com">
          <button class="btn-primary" onclick="VeilUI.addToWhitelist()">Add</button>
        </div>
      </div>
     
      <div class="button-group">
        <button class="btn-primary" onclick="VeilUI.saveBlockingSettings()">Save Blocking Settings</button>
      </div>
    `;
   
    this.renderBlacklist();
    this.renderWhitelist();
  },
 
  /**
   * Render blacklist
   */
  renderBlacklist() {
    const container = document.getElementById('blacklist-container');
    if (!container) return;
   
    const blacklist = this.config.blacklist || [];
   
    if (blacklist.length === 0) {
      container.innerHTML = '<p class="empty-state">No blacklisted domains</p>';
      return;
    }
   
    container.innerHTML = `
      <div class="domain-list">
        ${blacklist.map(domain => `
          <div class="domain-item">
            <span>${domain}</span>
            <button class="btn-icon" onclick="VeilUI.removeFromBlacklist('${domain}')" title="Remove">
              <i class="icon-x"></i>
            </button>
          </div>
        `).join('')}
      </div>
    `;
  },
 
  /**
   * Render whitelist
   */
  renderWhitelist() {
    const container = document.getElementById('whitelist-container');
    if (!container) return;
   
    const whitelist = this.config.whitelist || [];
   
    if (whitelist.length === 0) {
      container.innerHTML = '<p class="empty-state">No whitelisted domains</p>';
      return;
    }
   
    container.innerHTML = `
      <div class="domain-list">
        ${whitelist.map(domain => `
          <div class="domain-item">
            <span>${domain}</span>
            <button class="btn-icon" onclick="VeilUI.removeFromWhitelist('${domain}')" title="Remove">
              <i class="icon-x"></i>
            </button>
          </div>
        `).join('')}
      </div>
    `;
  },
 
  /**
   * Render Settings Tab
   */
  renderSettingsTab() {
    const container = document.getElementById('tab-settings');
    container.innerHTML = `
      <div class="veil-section">
        <h3>Cache Prewarming</h3>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="cache-prewarm-enabled" ${this.config.cache_prewarm_enabled ? 'checked' : ''}>
            Enable Cache Prewarming
          </label>
        </div>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="cache-prewarm-on-start" ${this.config.cache_prewarm_on_start ? 'checked' : ''}>
            Prewarm on Start
          </label>
        </div>
       
        <div class="setting-row">
          <label>Prewarm Interval (seconds)</label>
          <input type="number" id="cache-prewarm-interval" value="${this.config.cache_prewarm_interval}" min="600">
        </div>
       
        <div class="setting-row">
          <label>Concurrent Queries</label>
          <input type="number" id="cache-prewarm-concurrent" value="${this.config.cache_prewarm_concurrent}" min="1" max="50">
        </div>
       
        <div class="stats-row">
          <div>Runs: ${this.stats.cache_prewarm_runs || 0}</div>
          <div>Domains: ${this.stats.cache_prewarm_domains || 0}</div>
        </div>
      </div>
     
      <div class="veil-section">
        <h3>Security</h3>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="rebinding-protection" ${this.config.rebinding_protection ? 'checked' : ''}>
            DNS Rebinding Protection
          </label>
        </div>
      </div>
     
      <div class="veil-section">
        <h3>Logging</h3>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="zero-log" ${this.config.zero_log ? 'checked' : ''}>
            Zero Query Logging
          </label>
        </div>
       
        <div class="setting-row">
          <label>Log Retention (days)</label>
          <input type="number" id="log-retention-days" value="${this.config.log_retention_days || 7}" min="1">
        </div>
      </div>
     
      <div class="veil-section">
        <h3>Notifications</h3>
       
        <div class="setting-row">
          <label>
            <input type="checkbox" id="notification-enabled" ${this.config.notification_enabled ? 'checked' : ''}>
            Enable Notifications
          </label>
        </div>
       
        <div class="setting-row">
          <label>Notification URL</label>
          <input type="text" id="notification-url" value="${this.config.notification_url || ''}" placeholder="https://ntfy.sh/topic">
        </div>
       
        <div class="setting-row">
          <label>Notification Token</label>
          <input type="text" id="notification-token" value="${this.config.notification_token || ''}" placeholder="Token (optional)">
        </div>
      </div>
     
      <div class="veil-section">
        <h3>System</h3>
       
        <div class="setting-row">
          <label>Self-Check Interval (seconds)</label>
          <input type="number" id="self-check-interval" value="${this.config.system_self_check_interval || 300}" min="60">
        </div>
      </div>
     
      <div class="veil-section">
        <h3>Backup / Restore</h3>
       
        <div class="button-group">
          <button class="btn-secondary" onclick="VeilUI.backupConfig()">Backup Config</button>
          <input type="file" id="restore-file" accept=".json" style="display:none;" onchange="VeilUI.restoreConfig(this.files[0])">
          <button class="btn-secondary" onclick="document.getElementById('restore-file').click()">Restore Config</button>
        </div>
      </div>
     
      <div class="button-group">
        <button class="btn-primary" onclick="VeilUI.saveSettings()">Save Settings</button>
      </div>
    `;
  },
 
  /**
   * Render Logs Tab
   */
  renderLogsTab() {
    const container = document.getElementById('tab-logs');
    container.innerHTML = `
      <div class="veil-section">
        <h3>Query Logs</h3>
        <div id="query-log-table" class="records-table"></div>
        <div class="button-group">
          <button class="btn-secondary" onclick="VeilUI.loadLogs()">Refresh Logs</button>
          <button class="btn-secondary" onclick="VeilUI.exportLogs('json')">Export JSON</button>
          <button class="btn-secondary" onclick="VeilUI.exportLogs('csv')">Export CSV</button>
        </div>
      </div>
      
      <div class="veil-section">
        <h3>Top 5 Clients</h3>
        <div id="top-clients" class="records-table"></div>
      </div>
      
      <div class="veil-section">
        <h3>Top 5 Blocked Domains</h3>
        <div id="top-blocked" class="records-table"></div>
      </div>
      
      <div class="veil-section">
        <h3>Category Counters</h3>
        <div id="category-counters" class="stats-grid"></div>
      </div>
    `;
    this.loadLogs();
  },

  /**
   * Render Health Tab
   */
  renderHealthTab() {
    const container = document.getElementById('tab-health');
    container.innerHTML = `
      <div class="veil-section">
        <h3>Protocol Usage</h3>
        <div id="protocol-bars"></div>
      </div>
      
      <div class="veil-section">
        <h3>Upstream Health</h3>
        <div id="upstream-health-list"></div>
      </div>
    `;
    this.renderUpstreamHealthList();
  },

  /**
   * Render upstream health list
   */
  renderUpstreamHealthList() {
    const container = document.getElementById('upstream-health-list');
    if (!container) return;
   
    const health = this.stats.upstream_health || {};
   
    container.innerHTML = Object.entries(health).map(([server, status]) => `
      <div class="record-row">
        <div>${server}</div>
        <div>${status.healthy ? 'Healthy' : 'Degraded'}</div>
        <div>${Math.round(status.latency * 1000)}ms</div>
      </div>
    `).join('');
  },

  /**
   * Save DNS settings
   */
  async saveDNSSettings() {
    const config = {
      enabled: document.getElementById('dns-enabled').checked,
      dns_port: parseInt(document.getElementById('dns-port').value),
      dns_bind: document.getElementById('dns-bind').value,
      cache_enabled: document.getElementById('cache-enabled').checked,
      cache_ttl: parseInt(document.getElementById('cache-ttl').value),
      cache_max_size: parseInt(document.getElementById('cache-max-size').value),
      stale_serving: document.getElementById('stale-serving').checked,
      upstream_parallel: document.getElementById('upstream-parallel').checked,
      upstream_rotation: document.getElementById('upstream-rotation').checked,
      dynamic_upstream_weighting: document.getElementById('dynamic-weighting').checked,
      upstream_timeout: parseFloat(document.getElementById('upstream-timeout').value)
    };
   
    await this.updateConfig(config);
  },
 
  /**
   * Save DHCP settings
   */
  async saveDHCPSettings() {
    const config = {
      dhcp_enabled: document.getElementById('dhcp-enabled').checked,
      dhcp_port: parseInt(document.getElementById('dhcp-port').value),
      dhcp_interface: document.getElementById('dhcp-interface').value,
      dhcp_subnet: document.getElementById('dhcp-subnet').value,
      dhcp_netmask: document.getElementById('dhcp-netmask').value,
      dhcp_gateway: document.getElementById('dhcp-gateway').value,
      dhcp_range_start: document.getElementById('dhcp-range-start').value,
      dhcp_range_end: document.getElementById('dhcp-range-end').value,
      dhcp_lease_time: parseInt(document.getElementById('dhcp-lease-time').value),
      dhcp_domain: document.getElementById('dhcp-domain').value,
      dhcp_dns_servers: document.getElementById('dhcp-dns-servers').value.split(',').map(s => s.trim()).filter(s => s),
      dhcp_ntp_servers: document.getElementById('dhcp-ntp-servers').value.split(',').map(s => s.trim()).filter(s => s),
      dhcp_ping_check: document.getElementById('dhcp-ping-check').checked,
      dhcp_relay_support: document.getElementById('dhcp-relay-support').checked
    };
   
    await this.updateConfig(config);
  },
 
  /**
   * Save privacy settings
   */
  async savePrivacySettings() {
    const config = {
      doh_enabled: document.getElementById('doh-enabled').checked,
      dot_enabled: document.getElementById('dot-enabled').checked,
      doq_enabled: document.getElementById('doq-enabled').checked,
      ecs_strip: document.getElementById('ecs-strip').checked,
      padding_enabled: document.getElementById('padding-enabled').checked,
      padding_block_size: parseInt(document.getElementById('padding-block-size').value),
      case_randomization: document.getElementById('case-randomization').checked,
      qname_minimization: document.getElementById('qname-minimization').checked,
      query_jitter: document.getElementById('query-jitter').checked,
      dnssec_validate: document.getElementById('dnssec-validate').checked,
      rate_limit_enabled: document.getElementById('rate-limit-enabled').checked,
      rate_limit_qps: parseInt(document.getElementById('rate-limit-qps').value),
      rate_limit_burst: parseInt(document.getElementById('rate-limit-burst').value),
      safesearch_enabled: document.getElementById('safesearch-enabled').checked,
      safesearch_google: document.getElementById('safesearch-google').checked,
      safesearch_bing: document.getElementById('safesearch-bing').checked,
      safesearch_duckduckgo: document.getElementById('safesearch-duckduckgo').checked,
      safesearch_youtube: document.getElementById('safesearch-youtube').checked,
      safesearch_schedule: {
        start: document.getElementById('safesearch-start').value,
        end: document.getElementById('safesearch-end').value
      }
    };
   
    await this.updateConfig(config);
  },
 
  /**
   * Save blocking settings
   */
  async saveBlockingSettings() {
    const urls = document.getElementById('blocklist-urls').value
      .split('\n')
      .map(s => s.trim())
      .filter(s => s && s.startsWith('http'));
 
    const config = {
      blocking_enabled: document.getElementById('blocking-enabled').checked,
      block_response_type: document.getElementById('block-response-type').value,
      block_custom_ip: document.getElementById('block-custom-ip').value,
      blocklist_update_enabled: document.getElementById('blocklist-update-enabled').checked,
      blocklist_update_interval: parseInt(document.getElementById('blocklist-update-interval').value),
      blocklist_update_on_start: document.getElementById('blocklist-update-on-start').checked,
      blocklist_urls: urls
    };
   
    await this.updateConfig(config);
  },
 
  /**
   * Save general settings
   */
  async saveSettings() {
    const config = {
      cache_prewarm_enabled: document.getElementById('cache-prewarm-enabled').checked,
      cache_prewarm_on_start: document.getElementById('cache-prewarm-on-start').checked,
      cache_prewarm_interval: parseInt(document.getElementById('cache-prewarm-interval').value),
      cache_prewarm_concurrent: parseInt(document.getElementById('cache-prewarm-concurrent').value),
      rebinding_protection: document.getElementById('rebinding-protection').checked,
      zero_log: document.getElementById('zero-log').checked,
      log_retention_days: parseInt(document.getElementById('log-retention-days').value),
      notification_enabled: document.getElementById('notification-enabled').checked,
      notification_url: document.getElementById('notification-url').value,
      notification_token: document.getElementById('notification-token').value,
      system_self_check_interval: parseInt(document.getElementById('self-check-interval').value)
    };
   
    await this.updateConfig(config);
  },
 
  /**
   * Update configuration
   */
  async updateConfig(updates) {
    try {
      const response = await fetch('/api/veil/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      });
     
      if (response.ok) {
        toast('Configuration updated', 'success');
        await this.loadConfig();
        // Re-render relevant tabs
        this.renderDNSTab();
        this.renderDHCPTab();
        this.renderPrivacyTab();
        this.renderBlockingTab();
        this.renderSettingsTab();
        this.renderLogsTab();
        this.renderHealthTab();
      } else {
        throw new Error('Failed to update configuration');
      }
    } catch (error) {
      console.error('[Veil] Failed to update config:', error);
      toast('Failed to update configuration', 'error');
    }
  },
 
  /**
   * Flush DNS cache
   */
  async flushCache() {
    try {
      const response = await fetch('/api/veil/cache', { method: 'DELETE' });
      if (response.ok) {
        toast('Cache flushed', 'success');
        await this.loadStats();
      }
    } catch (error) {
      console.error('[Veil] Failed to flush cache:', error);
      toast('Failed to flush cache', 'error');
    }
  },
 
  /**
   * Prewarm cache
   */
  async prewarmCache() {
    try {
      const response = await fetch('/api/veil/cache/prewarm', { method: 'POST' });
      if (response.ok) {
        toast('Cache prewarm started', 'success');
      }
    } catch (error) {
      console.error('[Veil] Failed to prewarm cache:', error);
      toast('Failed to prewarm cache', 'error');
    }
  },
 
  /**
   * Update blocklists
   */
  async updateBlocklists() {
    try {
      toast('Updating blocklists...', 'info');
      const response = await fetch('/api/veil/blocklist/update', { method: 'POST' });
      if (response.ok) {
        const data = await response.json();
        toast(`Blocklists updated: ${data.size.toLocaleString()} domains`, 'success');
        await this.loadStats();
      }
    } catch (error) {
      console.error('[Veil] Failed to update blocklists:', error);
      toast('Failed to update blocklists', 'error');
    }
  },
 
  /**
   * Reload blocklists
   */
  async reloadBlocklists() {
    try {
      const response = await fetch('/api/veil/blocklist/reload', { method: 'POST' });
      if (response.ok) {
        const data = await response.json();
        toast(`Blocklists reloaded: ${data.size.toLocaleString()} domains`, 'success');
        await this.loadStats();
      }
    } catch (error) {
      console.error('[Veil] Failed to reload blocklists:', error);
      toast('Failed to reload blocklists', 'error');
    }
  },
 
  /**
   * Add domain to blacklist
   */
  async addToBlacklist() {
    const domain = document.getElementById('blacklist-domain').value.trim();
    if (!domain) return;
   
    try {
      const response = await fetch('/api/veil/blacklist/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain })
      });
     
      if (response.ok) {
        toast(`Added ${domain} to blacklist`, 'success');
        document.getElementById('blacklist-domain').value = '';
        await this.loadConfig();
        this.renderBlacklist();
      }
    } catch (error) {
      console.error('[Veil] Failed to add to blacklist:', error);
      toast('Failed to add domain', 'error');
    }
  },
 
  /**
   * Remove domain from blacklist
   */
  async removeFromBlacklist(domain) {
    try {
      const response = await fetch('/api/veil/blacklist/remove', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain })
      });
     
      if (response.ok) {
        toast(`Removed ${domain} from blacklist`, 'success');
        await this.loadConfig();
        this.renderBlacklist();
      }
    } catch (error) {
      console.error('[Veil] Failed to remove from blacklist:', error);
      toast('Failed to remove domain', 'error');
    }
  },
 
  /**
   * Add domain to whitelist
   */
  async addToWhitelist() {
    const domain = document.getElementById('whitelist-domain').value.trim();
    if (!domain) return;
   
    try {
      const response = await fetch('/api/veil/whitelist/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain })
      });
     
      if (response.ok) {
        toast(`Added ${domain} to whitelist`, 'success');
        document.getElementById('whitelist-domain').value = '';
        await this.loadConfig();
        this.renderWhitelist();
      }
    } catch (error) {
      console.error('[Veil] Failed to add to whitelist:', error);
      toast('Failed to add domain', 'error');
    }
  },
 
  /**
   * Remove domain from whitelist
   */
  async removeFromWhitelist(domain) {
    try {
      const response = await fetch('/api/veil/whitelist/remove', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain })
      });
     
      if (response.ok) {
        toast(`Removed ${domain} from whitelist`, 'success');
        await this.loadConfig();
        this.renderWhitelist();
      }
    } catch (error) {
      console.error('[Veil] Failed to remove from whitelist:', error);
      toast('Failed to remove domain', 'error');
    }
  },
 
  /**
   * Delete DHCP lease
   */
  async deleteLease(mac) {
    if (!confirm(`Delete lease for ${mac}?`)) return;
   
    try {
      const response = await fetch('/api/veil/dhcp/lease', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mac })
      });
     
      if (response.ok) {
        toast('Lease deleted', 'success');
        await this.loadDHCPLeases();
      }
    } catch (error) {
      console.error('[Veil] Failed to delete lease:', error);
      toast('Failed to delete lease', 'error');
    }
  },
 
  /**
   * Cleanup
   */
  cleanup() {
    this.stopAutoRefresh();
  }
};
// Auto-initialize when page loads
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => VeilUI.init());
} else {
  VeilUI.init();
}
