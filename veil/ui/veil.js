/**
 * Veil UI - Privacy-First DNS/DHCP Management Interface
 * For Jarvis Prime
 */
const VeilUI = {
  stats: {},
  config: {},
  updateInterval: null,

  /**
   * Initialize Veil UI
   */
  async init() {
    console.log('[Veil] Initializing UI');
    await this.loadStats();
    await this.loadConfig();
    this.renderUI();
    this.startAutoRefresh();

    // Load full settings UI
    this.loadAllSettings();
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
   * Start auto-refresh timer
   */
  startAutoRefresh() {
    if (this.updateInterval) clearInterval(this.updateInterval);
    this.updateInterval = setInterval(async () => {
      await this.loadStats();
      this.updateStatsDisplay();
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
          <h2>Veil - Privacy-First DNS/DHCP</h2>
          <div class="veil-status" id="veil-status">
            <span class="status-dot status-healthy"></span>
            <span>Loading...</span>
          </div>
        </div>

        <!-- Stats Cards -->
        <div class="veil-stats-grid">
          <div class="stat-card">
            <div class="stat-icon">Search</div>
            <div class="stat-content">
              <div class="stat-value" id="stat-queries">0</div>
              <div class="stat-label">DNS Queries</div>
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-icon">Lightning</div>
            <div class="stat-content">
              <div class="stat-value" id="stat-cached">0%</div>
              <div class="stat-label">Cache Hit Rate</div>
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-icon">Shield</div>
            <div class="stat-content">
              <div class="stat-value" id="stat-blocked">0</div>
              <div class="stat-label">Blocked</div>
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-icon">Chart</div>
            <div class="stat-content">
              <div class="stat-value" id="stat-cache-size">0</div>
              <div class="stat-label">Cache Size</div>
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-icon">Lock</div>
            <div class="stat-content">
              <div class="stat-value" id="stat-privacy">0</div>
              <div class="stat-label">Privacy Features</div>
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-icon">Computer</div>
            <div class="stat-content">
              <div class="stat-value" id="stat-dhcp">0</div>
              <div class="stat-label">DHCP Leases</div>
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
        </div>

        <!-- Tab Content -->
        <div class="veil-tab-content">
          <div id="tab-dns" class="tab-pane active"></div>
          <div id="tab-dhcp" class="tab-pane"></div>
          <div id="tab-privacy" class="tab-pane"></div>
          <div id="tab-blocking" class="tab-pane"></div>
          <div id="tab-settings" class="tab-pane"></div>
        </div>
      </div>
    `;

    this.attachEventListeners();
    this.renderDNSTab();
    this.renderDHCPTab();
    this.renderPrivacyTab();
    this.renderBlockingTab();
    this.renderSettingsTab();
    this.updateStatsDisplay();
  },

  /**
   * Attach event listeners
   */
  attachEventListeners() {
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
    document.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
    document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
    document.getElementById(`tab-${tab}`).classList.add('active');
  },

  /**
   * Update stats display
   */
  updateStatsDisplay() {
    const s = this.stats;

    const statusEl = document.getElementById('veil-status');
    if (statusEl) {
      const isHealthy = s.dns_queries > 0 || this.config.enabled;
      statusEl.innerHTML = `
        <span class="status-dot ${isHealthy ? 'status-healthy' : 'status-degraded'}"></span>
        <span>${isHealthy ? 'Healthy' : 'Inactive'}</span>
      `;
    }

    document.getElementById('stat-queries').textContent = (s.dns_queries || 0).toLocaleString();

    const cacheHitRate = s.dns_queries > 0
      ? Math.round((s.dns_cached / s.dns_queries) * 100)
      : 0;
    document.getElementById('stat-cached').textContent = `${cacheHitRate}%`;

    document.getElementById('stat-blocked').textContent = (s.dns_blocked || 0).toLocaleString();
    document.getElementById('stat-cache-size').textContent = (s.cache_size || 0).toLocaleString();

    const privacyFeatures = (s.dns_padded || 0) + (s.dns_0x20 || 0) + (s.dns_dnssec_validated || 0);
    document.getElementById('stat-privacy').textContent = privacyFeatures.toLocaleString();

    document.getElementById('stat-dhcp').textContent = (s.dhcp_leases || 0).toLocaleString();
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
    `;

    this.renderUpstreamList();
    this.renderLocalRecords();
  },

  /**
   * Render upstream servers list
   */
  renderUpstreamList() {
    const container = document.getElementById('upstream-list');
    if (!container) return;

    const servers = this.config.upstream_servers || [];
    const health = this.stats.upstream_health || {};

    container.innerHTML = servers.map(server => {
      const status = health[server];
      const isHealthy = !status || status.healthy;
      const latency = status ? status.latency : 0;

      return `
        <div class="upstream-server">
          <span class="status-dot ${isHealthy ? 'status-healthy' : 'status-error'}"></span>
          <span class="server-ip">${server}</span>
          ${latency > 0 ? `<span class="server-latency">${Math.round(latency * 1000)}ms</span>` : ''}
        </div>
      `;
    }).join('');
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
    `;

    this.loadDHCPLeases();
  },

  /**
   * Load and display DHCP leases
   */
  async loadDHCPLeases() {
    try {
      const response = await fetch('/api/veil/dhcp/leases');
      const data = await response.json();
      const leases = data.leases || [];

      const container = document.getElementById('dhcp-leases-list');
      if (!container) return;

      if (leases.length === 0) {
        container.innerHTML = '<p class="empty-state">No active leases</p>';
        return;
      }

      container.innerHTML = `
        <div class="leases-table">
          <div class="lease-header">
            <div>MAC Address</div>
            <div>IP Address</div>
            <div>Hostname</div>
            <div>Expires</div>
            <div>Actions</div>
          </div>
          ${leases.map(lease => `
            <div class="lease-row">
              <div class="lease-mac">${lease.mac}</div>
              <div class="lease-ip">${lease.ip}</div>
              <div class="lease-hostname">${lease.hostname || '-'}</div>
              <div class="lease-expires">${this.formatLeaseExpiry(lease.remaining)}</div>
              <div class="lease-actions">
                ${!lease.static ? `<button class="btn-icon" onclick="VeilUI.deleteLease('${lease.mac}')" title="Delete"><i class="icon-trash"></i></button>` : '<span class="badge">Static</span>'}
              </div>
            </div>
          `).join('')}
        </div>
      `;
    } catch (error) {
      console.error('[Veil] Failed to load DHCP leases:', error);
    }
  },

  /**
   * Format lease expiry time
   */
  formatLeaseExpiry(seconds) {
    if (seconds <= 0) return 'Expired';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
    return `${Math.floor(seconds / 86400)}d`;
  },

  /**
   * Render Privacy Tab
   */
  renderPrivacyTab() {
    const container = document.getElementById('tab-privacy');
    container.innerHTML = `
      <div class="veil-section">
        <h3>Encrypted DNS</h3>
        <div class="setting-row">
          <label>
            <input type="checkbox" id="doh-enabled" ${this.config.doh_enabled ? 'checked' : ''}>
            DNS-over-HTTPS (DoH)
          </label>
        </div>
        <div class="setting-row">
          <label>
            <input type="checkbox" id="dot-enabled" ${this.config.dot_enabled ? 'checked' : ''}>
            DNS-over-TLS (DoT)
          </label>
        </div>
        <div class="setting-row">
          <label>
            <input type="checkbox" id="doq-enabled" ${this.config.doq_enabled ? 'checked' : ''}>
            DNS-over-QUIC (DoQ)
          </label>
        </div>
      </div>

      <div class="veil-section">
        <h3>Privacy Features</h3>
        <div class="setting-row">
          <label>
            <input type="checkbox" id="ecs-strip" ${this.config.ecs_strip ? 'checked' : ''}>
            Strip EDNS Client Subnet (ECS)
          </label>
          <p class="help-text">Prevents location tracking via DNS</p>
        </div>
        <div class="setting-row">
          <label>
            <input type="checkbox" id="padding-enabled" ${this.config.padding_enabled ? 'checked' : ''}>
            RFC 7830 Query Padding
          </label>
          <p class="help-text">Uniform query length to prevent fingerprinting</p>
        </div>
        <div class="setting-row">
          <label>Padding Block Size</label>
          <input type="number" id="padding-block-size" value="${this.config.padding_block_size}" min="128" max="512">
        </div>
        <div class="setting-row">
          <label>
            <input type="checkbox" id="case-randomization" ${this.config.case_randomization ? 'checked' : ''}>
            0x20 Case Randomization
          </label>
          <p class="help-text">Random letter case for entropy</p>
        </div>
        <div class="setting-row">
          <label>
            <input type="checkbox" id="qname-minimization" ${this.config.qname_minimization ? 'checked' : ''}>
            QNAME Minimization (RFC 9156)
          </label>
        </div>
        <div class="setting-row">
          <label>
            <input type="checkbox" id="query-jitter" ${this.config.query_jitter ? 'checked' : ''}>
            Query Timing Jitter
          </label>
          <p class="help-text">Random delays to prevent timing correlation</p>
        </div>
      </div>

      <div class="veil-section">
        <h3>DNSSEC</h3>
        <div class="setting-row">
          <label>
            <input type="checkbox" id="dnssec-validate" ${this.config.dnssec_validate ? 'checked' : ''}>
            DNSSEC Validation
          </label>
        </div>
        <div class="stats-row">
          <div>Validated: ${this.stats.dns_dnssec_validated || 0}</div>
          <div>Failed: ${this.stats.dns_dnssec_failed || 0}</div>
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
          <label>Queries Per Second (per client)</label>
          <input type="number" id="rate-limit-qps" value="${this.config.rate_limit_qps}" min="1" max="100">
        </div>
        <div class="setting-row">
          <label>Burst Allowance</label>
          <input type="number" id="rate-limit-burst" value="${this.config.rate_limit_burst}" min="1" max="200">
        </div>
        <div class="stats-row">
          <div>Rate Limited: ${this.stats.dns_rate_limited || 0}</div>
        </div>
      </div>

      <div class="veil-section">
        <h3>SafeSearch</h3>
        <div class="setting-row">
          <label>
            <input type="checkbox" id="safesearch-enabled" ${this.config.safesearch_enabled ? 'checked' : ''}>
            Enable SafeSearch Enforcement
          </label>
        </div>
        <div class="setting-row">
          <label>
            <input type="checkbox" id="safesearch-google" ${this.config.safesearch_google ? 'checked' : ''}>
            Google SafeSearch
          </label>
        </div>
        <div class="setting-row">
          <label>
            <input type="checkbox" id="safesearch-bing" ${this.config.safesearch_bing ? 'checked' : ''}>
            Bing SafeSearch
          </label>
        </div>
        <div class="setting-row">
          <label>
            <input type="checkbox" id="safesearch-duckduckgo" ${this.config.safesearch_duckduckgo ? 'checked' : ''}>
            DuckDuckGo SafeSearch
          </label>
        </div>
        <div class="setting-row">
          <label>
            <input type="checkbox" id="safesearch-youtube" ${this.config.safesearch_youtube ? 'checked' : ''}>
            YouTube Restricted Mode
          </label>
        </div>
        <div class="stats-row">
          <div>SafeSearch Rewrites: ${this.stats.dns_safesearch || 0}</div>
        </div>
      </div>
    `;
  },

  /**
   * Render Blocking Tab
   */
  renderBlockingTab() {
    const urls = (this.config.blocklist_urls || []).join('\n');
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
          <label>Block Response Type</label>
          <select id="block-response-type">
            <option value="NXDOMAIN" ${this.config.block_response_type === 'NXDOMAIN' ? 'selected' : ''}>NXDOMAIN</option>
            <option value="REFUSED" ${this.config.block_response_type === 'REFUSED' ? 'selected' : ''}>REFUSED</option>
            <option value="0.0.0.0" ${this.config.block_response_type === '0.0.0.0' ? 'selected' : ''}>0.0.0.0</option>
            <option value="custom_ip" ${this.config.block_response_type === 'custom_ip' ? 'selected' : ''}>Custom IP</option>
          </select>
        </div>
        <div class="setting-row">
          <label>Custom Block IP</label>
          <input type="text" id="block-custom-ip" value="${this.config.block_custom_ip}" placeholder="0.0.0.0">
        </div>
        <div class="stats-row">
          <div>Blocklist Size: ${(this.stats.blocklist_size || 0).toLocaleString()} domains</div>
          <div>Blocked: ${(this.stats.dns_blocked || 0).toLocaleString()}</div>
        </div>
      </div>

      <div class="veil-section">
        <h3>Blocklists</h3>
        <div class="setting-row">
          <label>
            <input type="checkbox" id="blocklist-update-enabled" ${this.config.blocklist_update_enabled ? 'checked' : ''}>
            Auto-Update Blocklists
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
        <div class="setting-row">
          <label>Blocklist URLs (one per line)</label>
          <textarea id="blocklist-urls" rows="6" placeholder="https://example.com/blocklist.txt">${urls}</textarea>
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
   * Render Settings Tab — ALL SECTIONS FROM FIX
   */
  renderSettingsTab() {
    const container = document.getElementById('tab-settings');
    container.innerHTML = `
      <!-- DNS Settings Section -->
      <div class="section">
        <div class="section-title">DNS Settings</div>
        <div class="setting-item">
          <label>DNS Enabled</label>
          <input type="checkbox" id="dns-enabled" checked>
        </div>
        <div class="setting-item">
          <label>Upstream Servers (one per line)</label>
          <textarea id="upstream-servers" rows="6" style="width: 100%; background: rgba(0,255,255,0.05); border: 1px solid rgba(0,255,255,0.3); color: cyan; padding: 10px; border-radius: 4px;">1.1.1.1
1.0.0.1
8.8.8.8
8.8.4.4</textarea>
        </div>
        <div class="setting-item">
          <label>Upstream Timeout (seconds)</label>
          <input type="number" id="upstream-timeout" value="5" min="1" max="30" step="0.5">
        </div>
        <div class="setting-item">
          <label>Parallel Upstream Queries</label>
          <input type="checkbox" id="upstream-parallel">
        </div>
      </div>

      <!-- Cache Settings Section -->
      <div class="section">
        <div class="section-title">Cache Settings</div>
        <div class="setting-item">
          <label>Cache Enabled</label>
          <input type="checkbox" id="cache-enabled" checked>
        </div>
        <div class="setting-item">
          <label>Cache TTL (seconds)</label>
          <input type="number" id="cache-ttl" value="3600" min="60" max="86400">
        </div>
        <div class="setting-item">
          <label>Cache Max Size (entries)</label>
          <input type="number" id="cache-max-size" value="10000" min="100" max="100000" step="100">
        </div>
        <div class="setting-item">
          <label>Negative Cache TTL (seconds)</label>
          <input type="number" id="negative-cache-ttl" value="300" min="30" max="3600">
        </div>
        <div class="setting-item">
          <label>Stale Serving</label>
          <input type="checkbox" id="stale-serving">
        </div>
      </div>

      <!-- Privacy Settings Section -->
      <div class="section">
        <div class="section-title">Privacy Settings</div>
        <div class="setting-item">
          <label>DoH (DNS-over-HTTPS)</label>
          <input type="checkbox" id="doh-enabled" checked>
        </div>
        <div class="setting-item">
          <label>DoT (DNS-over-TLS)</label>
          <input type="checkbox" id="dot-enabled" checked>
        </div>
        <div class="setting-item">
          <label>DoQ (DNS-over-QUIC) - Experimental</label>
          <input type="checkbox" id="doq-enabled">
        </div>
        <div class="setting-item">
          <label>Strip EDNS Client Subnet</label>
          <input type="checkbox" id="ecs-strip" checked>
        </div>
        <div class="setting-item">
          <label>DNSSEC Validation</label>
          <input type="checkbox" id="dnssec-validate" checked>
        </div>
        <div class="setting-item">
          <label>Query Padding (RFC 7830)</label>
          <input type="checkbox" id="padding-enabled" checked>
        </div>
        <div class="setting-item">
          <label>Padding Block Size (bytes)</label>
          <input type="number" id="padding-block-size" value="468" min="128" max="1024" step="16">
        </div>
        <div class="setting-item">
          <label>0x20 Case Randomization</label>
          <input type="checkbox" id="case-randomization" checked>
        </div>
        <div class="setting-item">
          <label>QNAME Minimization</label>
         548          <input type="checkbox" id="qname-minimization" checked>
        </div>
        <div class="setting-item">
          <label>Query Jitter</label>
          <input type="checkbox" id="query-jitter" checked>
        </div>
      </div>

      <!-- Rate Limiting Section -->
      <div class="section">
        <div class="section-title">Rate Limiting</div>
        <div class="setting-item">
          <label>Rate Limiting Enabled</label>
          <input type="checkbox" id="rate-limit-enabled" checked>
        </div>
        <div class="setting-item">
          <label>Queries Per Client</label>
          <input type="number" id="rate-limit-per-client" value="100" min="10" max="1000">
        </div>
        <div class="setting-item">
          <label>Time Window (seconds)</label>
          <input type="number" id="rate-limit-window" value="60" min="10" max="600">
        </div>
        <div class="setting-item">
          <label>Burst Limit</label>
          <input type="number" id="rate-limit-burst" value="50" min="5" max="500">
        </div>
      </div>

      <!-- SafeSearch Section -->
      <div class="section">
        <div class="section-title">SafeSearch Enforcement</div>
        <div class="setting-item">
          <label>SafeSearch Enabled</label>
          <input type="checkbox" id="safesearch-enabled">
        </div>
        <div class="setting-item">
          <label>Force Google SafeSearch</label>
          <input type="checkbox" id="safesearch-google">
        </div>
        <div class="setting-item">
          <label>Force Bing SafeSearch</label>
          <input type="checkbox" id="safesearch-bing">
        </div>
        <div class="setting-item">
          <label>Force DuckDuckGo SafeSearch</label>
          <input type="checkbox" id="safesearch-duckduckgo">
        </div>
        <div class="setting-item">
          <label>Force YouTube Restricted Mode</label>
          <input type="checkbox" id364="safesearch-youtube">
        </div>
      </div>

      <!-- DHCP Settings Section -->
      <div class="section">
        <div class="section-title">DHCP Settings</div>
        <div class="setting-item">
          <label>DHCP Server Enabled</label>
          <input type="checkbox" id="dhcp-enabled">
        </div>
        <div class="setting-item">
          <label>DHCP Interface</label>
          <input type="text" id="dhcp-interface" value="eth0">
        </div>
        <div class="setting-item">
          <label>IP Range Start</label>
          <input type="text" id="dhcp-range-start" value="192.168.1.100" placeholder="192.168.1.100">
        </div>
        <div class="setting-item">
          <label>IP Range End</label>
          <input type="text" id="dhcp-range-end" value="192.168.1.200" placeholder="192.168.1.200">
        </div>
        <div class="setting-item">
          <label>Subnet Mask</label>
          <input type="text" id="dhcp-subnet-mask" value="255.255.255.0">
        </div>
        <div class="setting-item">
          <label>Gateway</label>
          <input type="text" id="dhcp-gateway" value="192.168.1.1" placeholder="192.168.1.1">
        </div>
        <div class="setting-item">
          <label>Domain Name</label>
          <input type="text" id="dhcp-domain-name" value="home.lan" placeholder="home.lan">
        </div>
        <div class="setting-item">
          <label>Lease Time (seconds)</label>
          <input type="number" id="dhcp-lease-time" value="86400" min="3600" max="604800">
        </div>
        <div class="setting-item">
          <label>DNS Servers (one per line)</label>
          <textarea id="dhcp-dns-servers" rows="3" style="width: 100%; background: rgba(0,255,255,0.05); border: 1px solid rgba(0,255,255,0.3); color: cyan; padding: 10px; border-radius: 4px;">127.0.0.1</textarea>
        </div>
      </div>

      <!-- DNS Rewrites Section -->
      <div class="section">
        <div class="section-title">DNS Rewrites</div>
        <div class="setting-item">
          <label>Domain to Rewrite</label>
          <input type="text" id="rewrite-domain" placeholder="example.com">
        </div>
        <div class="setting-item">
          <label>Target IP</label>
          <input type="text" id="rewrite-target" placeholder="192.168.1.100">
        </div>
        <button onclick="VeilUI.addDNSRewrite()">Add DNS Rewrite</button>
        <div id="dns-rewrites-list" style="margin-top: 20px;">
          <!-- Populated dynamically -->
        </div>
      </div>

      <!-- Local DNS Records Section -->
      <div class="section">
        <div class="section-title">Local DNS Records</div>
        <div class="setting-item">
          <label>Hostname</label>
          <input type="text" id="local-hostname" placeholder="myserver.local">
        </div>
        <div class="setting-item">
          <label>IP Address</label>
          <input type="text" id="local-ip" placeholder="192.168.1.50">
        </div>
        <button onclick="VeilUI.addLocalRecord()">Add Local Record</button>
        <div id="local-records-list" style="margin-top: 20px;">
          <!-- Populated dynamically -->
        </div>
      </div>

      <!-- Blocklist Settings -->
      <div class="section">
        <div class="section-title">Blocklist Settings</div>
        <div class="setting-item">
          <label>Blocking Enabled</label>
          <input type="checkbox" id="blocking-enabled" checked>
        </div>
        <div class="setting-item">
          <label>Auto-Update Blocklists</label>
          <input type="checkbox" id="blocklist-update-enabled">
        </div>
        <div class="setting-item">
          <label>Update Interval (seconds)</label>
          <input type="number" id="blocklist-update-interval" value="86400" min="3600" max="604800">
        </div>
        <div class="setting-item">
          <label>Blocklist URLs (one per line)</label>
          <textarea id="blocklist-urls" rows="6" style="width: 100%; background: rgba(0,255,255,0.05); border: 1px solid rgba(0,255,255,0.3); color: cyan; padding: 10px; border-radius: 4px;" placeholder="https://example.com/blocklist.txt"></textarea>
        </div>
      </div>

      <!-- Save Button -->
      <div style="margin-top: 30px; text-align: center;">
        <button onclick="VeilUI.saveAllSettings()" style="padding: 15px 40px; font-size: 16px; background: linear-gradient(135deg, #00ffff, #00cccc); color: #001a1a; border: none; border-radius: 8px; cursor: pointer; font-weight: bold;">
          Save All Settings
        </button>
      </div>
    `;
  },

  /**
   * Save All Settings — ONE CALL FOR EVERYTHING
   */
  async saveAllSettings() {
    try {
      const settings = {
        // DNS
        enabled: document.getElementById('dns-enabled')?.checked || true,
        upstream_servers: document.getElementById('upstream-servers')?.value.split('\n').map(s => s.trim()).filter(s => s) || [],
        upstream_timeout: parseFloat(document.getElementById('upstream-timeout')?.value) || 5.0,
        upstream_parallel: document.getElementById('upstream-parallel')?.checked || false,

        // Cache
        cache_enabled: document.getElementById('cache-enabled')?.checked || true,
        cache_ttl: parseInt(document.getElementById('cache-ttl')?.value) || 3600,
        cache_max_size: parseInt(document.getElementById('cache-max-size')?.value) || 10000,
        negative_cache_ttl: parseInt(document.getElementById('negative-cache-ttl')?.value) || 300,
        stale_serving: document.getElementById('stale-serving')?.checked || false,

        // Privacy
        doh_enabled: document.getElementById('doh-enabled')?.checked || true,
        dot_enabled: document.getElementById('dot-enabled')?.checked || true,
        doq_enabled: document.getElementById('doq-enabled')?.checked || false,
        ecs_strip: document.getElementById('ecs-strip')?.checked || true,
        dnssec_validate: document.getElementById('dnssec-validate')?.checked || true,
        padding_enabled: document.getElementById('padding-enabled')?.checked || true,
        padding_block_size: parseInt(document.getElementById('padding-block-size')?.value) || 468,
        case_randomization: document.getElementById('case-randomization')?.checked || true,
        qname_minimization: document.getElementById('qname-minimization')?.checked || true,
        query_jitter: document.getElementById('query-jitter')?.checked || true,

        // Rate Limiting
        rate_limit_enabled: document.getElementById('rate-limit-enabled')?.checked || true,
        rate_limit_per_client: parseInt(document.getElementById('rate-limit-per-client')?.value) || 100,
        rate_limit_window: parseInt(document.getElementById('rate-limit-window')?.value) || 60,
        rate_limit_burst: parseInt(document.getElementById('rate-limit-burst')?.value) || 50,

        // SafeSearch
        safespoof_enabled: document.getElementById('safesearch-enabled')?.checked || false,
        safesearch_google: document.getElementById('safesearch-google')?.checked || false,
        safesearch_bing: document.getElementById('safesearch-bing')?.checked || false,
        safesearch_duckduckgo: document.getElementById('safesearch-duckduckgo')?.checked || false,
        safesearch_youtube: document.getElementById('safesearch-youtube')?.checked || false,

        // DHCP
        dhcp_enabled: document.getElementById('dhcp-enabled')?.checked || false,
        dhcp_interface: document.getElementById('dhcp-interface')?.value || 'eth0',
        dhcp_range_start: document.getElementById('dhcp-range-start')?.value || '192.168.1.100',
        dhcp_range_end: document.getElementById('dhcp-range-end')?.value || '192.168.1.200',
        dhcp_subnet_mask: document.getElementById('dhcp-subnet-mask')?.value || '255.255.255.0',
        dhcp_gateway: document.getElementById('dhcp-gateway')?.value || '192.168.1.1',
        dhcp_domain_name: document.getElementById('dhcp-domain-name')?.value || 'home.lan',
        dhcp_lease_time: parseInt(document.getElementById('dhcp-lease-time')?.value) || 86400,
        dhcp_dns_servers: document.getElementById('dhcp-dns-servers')?.value.split('\n').map(s => s.trim()).filter(s => s) || ['127.0.0.1'],

        // Blocklists
        blocking_enabled: document.getElementById('blocking-enabled')?.checked || true,
        blocklist_update_enabled: document.getElementById('blocklist-update-enabled')?.checked || false,
        blocklist_update_interval: parseInt(document.getElementById('blocklist-update-interval')?.value) || 86400,
        blocklist_urls: document.getElementById('blocklist-urls')?.value.split('\n').map(s => s.trim()).filter(s => s) || [],
      };

      const response = await fetch('/api/veil/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
      });

      if (response.ok) {
        alert('Settings saved successfully!');
      } else {
        alert('Failed to save settings');
      }
    } catch (error) {
      console.error('Save settings error:', error);
      alert('Error saving settings: ' + error.message);
    }
  },

  /**
   * Load All Settings into UI
   */
  async loadAllSettings() {
    try {
      const response = await fetch('/api/veil/config');
      const config = await response.json();

      // DNS
      if (document.getElementById('dns-enabled')) document.getElementById('dns-enabled').checked = config.enabled !== false;
      if (document.getElementById('upstream-servers')) document.getElementById('upstream-servers').value = (config.upstream_servers || []).join('\n');
      if (document.getElementById('upstream-timeout')) document.getElementById('upstream-timeout').value = config.upstream_timeout || 5.0;
      if (document.getElementById('upstream-parallel')) document.getElementById('upstream-parallel').checked = config.upstream_parallel || false;

      // Cache
      if (document.getElementById('cache-enabled')) document.getElementById('cache-enabled').checked = config.cache_enabled !== false;
      if (document.getElementById('cache-ttl')) document.getElementById('cache-ttl').value = config.cache_ttl || 3600;
      if (document.getElementById('cache-max-size')) document.getElementById('cache-max-size').value = config.cache_max_size || 10000;
      if (document.getElementById('negative-cache-ttl')) document.getElementById('negative-cache-ttl').value = config.negative_cache_ttl || 300;
      if (document.getElementById('stale-serving')) document.getElementById('stale-serving').checked = config.stale_serving || false;

      // Privacy
      if (document.getElementById('doh-enabled')) document.getElementById('doh-enabled').checked = config.doh_enabled !== false;
      if (document.getElementById('dot-enabled')) document.getElementById('dot-enabled').checked = config.dot_enabled !== false;
      if (document.getElementById('doq-enabled')) document.getElementById('doq-enabled').checked = config.doq_enabled || false;
      if (document.getElementById('ecs-strip')) document.getElementById('ecs-strip').checked = config.ecs_strip !== false;
      if (document.getElementById('dnssec-validate')) document.getElementById('dnssec-validate').checked = config.dnssec_validate !== false;
      if (document.getElementById('padding-enabled')) document.getElementById('padding-enabled').checked = config.padding_enabled !== false;
      if (document.getElementById('padding-block-size')) document.getElementById('padding-block-size').value = config.padding_block_size || 468;
      if (document.getElementById('case-randomization')) document.getElementById('case-randomization').checked = config.case_randomization !== false;
      if (document.getElementById('qname-minimization')) document.getElementById('qname-minimization').checked = config.qname_minimization !== false;
      if (document.getElementById('query-jitter')) document.getElementById('query-jitter').checked = config.query_jitter !== false;

      // Rate Limiting
      if (document.getElementById('rate-limit-enabled')) document.getElementById('rate-limit-enabled').checked = config.rate_limit_enabled !== false;
      if (document.getElementById('rate-limit-per-client')) document.getElementById('rate-limit-per-client').value = config.rate_limit_per_client || 100;
      if (document.getElementById('rate-limit-window')) document.getElementById('rate-limit-window').value = config.rate_limit_window || 60;
      if (document.getElementById('rate-limit-burst')) document.getElementById('rate-limit-burst').value = config.rate_limit_burst || 50;

      // SafeSearch
      if (document.getElementById('safesearch-enabled')) document.getElementById('safesearch-enabled').checked = config.safesearch_enabled || false;
      if (document.getElementById('safesearch-google')) document.getElementById('safesearch-google').checked = config.safesearch_google || false;
      if (document.getElementById('safesearch-bing')) document.getElementById('safesearch-bing').checked = config.safesearch_bing || false;
      if (document.getElementById('safesearch-duckduckgo')) document.getElementById('safesearch-duckduckgo').checked = config.safesearch_duckduckgo || false;
      if (document.getElementById('safesearch-youtube')) document.getElementById('safesearch-youtube').checked = config.safesearch_youtube || false;

      // DHCP
      if (document.getElementById('dhcp-enabled')) document.getElementById('dhcp-enabled').checked = config.dhcp_enabled || false;
      if (document.getElementById('dhcp-interface')) document.getElementById('dhcp-interface').value = config.dhcp_interface || 'eth0';
      if (document.getElementById('dhcp-range-start')) document.getElementById('dhcp-range-start').value = config.dhcp_range_start || '192.168.1.100';
      if (document.getElementById('dhcp-range-end')) document.getElementById('dhcp-range-end').value = config.dhcp_range_end || '192.168.1.200';
      if (document.getElementById('dhcp-subnet-mask')) document.getElementById('dhcp-subnet-mask').value = config.dhcp_subnet_mask || '255.255.255.0';
      if (document.getElementById('dhcp-gateway')) document.getElementById('dhcp-gateway').value = config.dhcp_gateway || '192.168.1.1';
      if (document.getElementById('dhcp-domain-name')) document.getElementById('dhcp-domain-name').value = config.dhcp_domain_name || 'home.lan';
      if (document.getElementById('dhcp-lease-time')) document.getElementById('dhcp-lease-time').value = config.dhcp_lease_time || 86400;
      if (document.getElementById('dhcp-dns-servers')) document.getElementById('dhcp-dns-servers').value = (config.dhcp_dns_servers || ['127.0.0.1']).join('\n');

      // Blocklists
      if (document.getElementById('blocking-enabled')) document.getElementById('blocking-enabled').checked = config.blocking_enabled !== false;
      if (document.getElementById('blocklist-update-enabled')) document.getElementById('blocklist-update-enabled').checked = config.blocklist_update_enabled || false;
      if (document.getElementById('blocklist-update-interval')) document.getElementById('blocklist-update-interval').value = config.blocklist_update_interval || 86400;
      if (document.getElementById('blocklist-urls')) document.getElementById('blocklist-urls').value = (config.blocklist_urls || []).join('\n');

    } catch (error) {
      console.error('Load settings error:', error);
    }
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
        this.renderBlockingTab();
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

      if response.ok) {
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
