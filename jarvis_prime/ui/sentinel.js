// /app/www/js/sentinel.js
// Frontend for Sentinel autonomous monitoring system

class SentinelUI {
    constructor() {
        this.servers = [];
        this.templates = [];
        this.monitoring = [];
        this.maintenanceWindows = [];
        this.quietHours = {};
        this.liveStatusInterval = null;
        this.dashboardInterval = null;
        this.activeLogStreams = new Map();
        this.currentView = 'dashboard';
        
        this.init();
    }

    async init() {
        console.log('[Sentinel] Initializing...');
        await this.loadInitialData();
        this.setupEventListeners();
        this.showView('dashboard');
        this.startAutoRefresh();
    }

    async loadInitialData() {
        try {
            await Promise.all([
                this.loadServers(),
                this.loadTemplates(),
                this.loadMonitoring(),
                this.loadMaintenanceWindows(),
                this.loadQuietHours()
            ]);
        } catch (error) {
            console.error('[Sentinel] Error loading initial data:', error);
            this.showNotification('Failed to load Sentinel data', 'error');
        }
    }

    // ===========================
    // Data Loading
    // ===========================

    async loadServers() {
        try {
            const response = await fetch('/api/sentinel/servers');
            const data = await response.json();
            this.servers = data.servers || [];
        } catch (error) {
            console.error('[Sentinel] Error loading servers:', error);
        }
    }

    async loadTemplates() {
        try {
            const response = await fetch('/api/sentinel/templates');
            const data = await response.json();
            this.templates = data.templates || [];
        } catch (error) {
            console.error('[Sentinel] Error loading templates:', error);
        }
    }

    async loadMonitoring() {
        try {
            const response = await fetch('/api/sentinel/monitoring');
            const data = await response.json();
            this.monitoring = data.monitoring || [];
        } catch (error) {
            console.error('[Sentinel] Error loading monitoring:', error);
        }
    }

    async loadMaintenanceWindows() {
        try {
            const response = await fetch('/api/sentinel/maintenance');
            const data = await response.json();
            this.maintenanceWindows = data.windows || [];
        } catch (error) {
            console.error('[Sentinel] Error loading maintenance windows:', error);
        }
    }

    async loadQuietHours() {
        try {
            const response = await fetch('/api/sentinel/quiet-hours');
            this.quietHours = await response.json();
        } catch (error) {
            console.error('[Sentinel] Error loading quiet hours:', error);
        }
    }

    async loadDashboard() {
        try {
            const response = await fetch('/api/sentinel/dashboard');
            const metrics = await response.json();
            this.renderDashboard(metrics);
        } catch (error) {
            console.error('[Sentinel] Error loading dashboard:', error);
        }
    }

    async loadLiveStatus() {
        try {
            const response = await fetch('/api/sentinel/status');
            const data = await response.json();
            this.renderLiveStatus(data.status || []);
        } catch (error) {
            console.error('[Sentinel] Error loading live status:', error);
        }
    }

    async loadRecentActivity(limit = 20) {
        try {
            const response = await fetch(`/api/sentinel/activity?limit=${limit}`);
            const data = await response.json();
            this.renderRecentActivity(data.activity || []);
        } catch (error) {
            console.error('[Sentinel] Error loading activity:', error);
        }
    }

    // ===========================
    // View Management
    // ===========================

    setupEventListeners() {
        // Navigation
        document.querySelectorAll('[data-sentinel-nav]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const view = e.target.dataset.sentinelNav;
                this.showView(view);
            });
        });

        // Modal close buttons
        document.querySelectorAll('[data-close-modal]').forEach(btn => {
            btn.addEventListener('click', () => this.closeAllModals());
        });
    }

    showView(viewName) {
        this.currentView = viewName;
        
        // Hide all views
        document.querySelectorAll('[data-sentinel-view]').forEach(view => {
            view.style.display = 'none';
        });

        // Show selected view
        const view = document.querySelector(`[data-sentinel-view="${viewName}"]`);
        if (view) {
            view.style.display = 'block';
        }

        // Update nav
        document.querySelectorAll('[data-sentinel-nav]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.sentinelNav === viewName);
        });

        // Load view data
        this.loadViewData(viewName);
    }

    async loadViewData(viewName) {
        switch(viewName) {
            case 'dashboard':
                await this.loadDashboard();
                await this.loadLiveStatus();
                await this.loadRecentActivity(10);
                break;
            case 'servers':
                this.renderServers();
                break;
            case 'templates':
                this.renderTemplates();
                break;
            case 'monitoring':
                this.renderMonitoring();
                break;
            case 'maintenance':
                this.renderMaintenanceWindows();
                break;
            case 'logs':
                await this.renderLogHistory();
                break;
            case 'settings':
                this.renderSettings();
                break;
        }
    }

    // ===========================
    // Dashboard Rendering
    // ===========================

    renderDashboard(metrics) {
        const container = document.getElementById('sentinel-dashboard-metrics');
        if (!container) return;

        const uptimeColor = metrics.uptime_percent >= 99 ? 'success' : 
                          metrics.uptime_percent >= 95 ? 'warning' : 'error';

        container.innerHTML = `
            <div class="sentinel-metrics-grid">
                <div class="sentinel-metric-card">
                    <div class="metric-icon">📊</div>
                    <div class="metric-value">${metrics.total_checks.toLocaleString()}</div>
                    <div class="metric-label">Total Checks</div>
                    <div class="metric-sub">${metrics.checks_today} today</div>
                </div>

                <div class="sentinel-metric-card">
                    <div class="metric-icon">🖥️</div>
                    <div class="metric-value">${metrics.services_monitored}</div>
                    <div class="metric-label">Services Monitored</div>
                    <div class="metric-sub">${metrics.servers_monitored} servers</div>
                </div>

                <div class="sentinel-metric-card ${metrics.services_down > 0 ? 'status-error' : ''}">
                    <div class="metric-icon">${metrics.services_down > 0 ? '❌' : '✅'}</div>
                    <div class="metric-value">${metrics.services_down}</div>
                    <div class="metric-label">Services Down</div>
                    <div class="metric-sub">${metrics.services_monitored - metrics.services_down} healthy</div>
                </div>

                <div class="sentinel-metric-card status-${uptimeColor}">
                    <div class="metric-icon">⏱️</div>
                    <div class="metric-value">${metrics.uptime_percent}%</div>
                    <div class="metric-label">Uptime (24h)</div>
                    <div class="metric-sub">${metrics.avg_response_time}s avg</div>
                </div>

                <div class="sentinel-metric-card">
                    <div class="metric-icon">🔧</div>
                    <div class="metric-value">${metrics.repairs_all_time}</div>
                    <div class="metric-label">Repairs Made</div>
                    <div class="metric-sub">${metrics.repairs_today} today</div>
                </div>

                <div class="sentinel-metric-card ${metrics.failed_repairs > 0 ? 'status-warning' : ''}">
                    <div class="metric-icon">⚠️</div>
                    <div class="metric-value">${metrics.failed_repairs}</div>
                    <div class="metric-label">Failed Repairs</div>
                    <div class="metric-sub">Needs attention</div>
                </div>

                <div class="sentinel-metric-card">
                    <div class="metric-icon">🔄</div>
                    <div class="metric-value">${metrics.active_schedules}</div>
                    <div class="metric-label">Active Schedules</div>
                    <div class="metric-sub">Monitoring configs</div>
                </div>

                <div class="sentinel-metric-card">
                    <div class="metric-icon">🏆</div>
                    <div class="metric-value">${metrics.most_repaired_count}</div>
                    <div class="metric-label">Most Repaired</div>
                    <div class="metric-sub">${metrics.most_repaired_service}</div>
                </div>
            </div>

            <div class="sentinel-last-check">
                Last check: ${metrics.last_check ? this.formatTimestamp(metrics.last_check) : 'Never'}
            </div>
        `;
    }

    renderLiveStatus(services) {
        const container = document.getElementById('sentinel-live-status');
        if (!container) return;

        if (services.length === 0) {
            container.innerHTML = '<div class="sentinel-empty">No services being monitored</div>';
            return;
        }

        const html = services.map(service => {
            const statusIcon = service.status === 'up' ? '✅' : 
                             service.status === 'down' ? '❌' : '❓';
            const statusClass = service.status === 'up' ? 'status-success' : 
                              service.status === 'down' ? 'status-error' : 'status-unknown';

            return `
                <div class="sentinel-status-card ${statusClass}">
                    <div class="status-header">
                        <span class="status-icon">${statusIcon}</span>
                        <div class="status-info">
                            <div class="status-service">${this.escapeHtml(service.service_name)}</div>
                            <div class="status-server">${this.escapeHtml(service.server_name)}</div>
                        </div>
                    </div>
                    <div class="status-metrics">
                        <div class="status-metric">
                            <span class="metric-label">Uptime (24h)</span>
                            <span class="metric-value">${service.uptime_24h}%</span>
                        </div>
                        <div class="status-metric">
                            <span class="metric-label">Response Time</span>
                            <span class="metric-value">${service.response_time ? service.response_time.toFixed(3) + 's' : 'N/A'}</span>
                        </div>
                        <div class="status-metric">
                            <span class="metric-label">Last Check</span>
                            <span class="metric-value">${service.last_check ? this.formatTimeAgo(service.last_check) : 'Never'}</span>
                        </div>
                    </div>
                    <div class="status-actions">
                        <button class="btn-sm btn-primary" onclick="sentinelUI.manualCheck('${service.server_id}', '${service.service_name}')">
                            🔍 Check Now
                        </button>
                        <button class="btn-sm btn-warning" onclick="sentinelUI.manualRepair('${service.server_id}', '${service.service_name}')">
                            🔧 Repair
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = html;
    }

    renderRecentActivity(activity) {
        const container = document.getElementById('sentinel-recent-activity');
        if (!container) return;

        if (activity.length === 0) {
            container.innerHTML = '<div class="sentinel-empty">No recent activity</div>';
            return;
        }

        const html = activity.map(item => {
            const icon = item.type === 'check' ? '🔍' : 
                        item.type === 'repair' ? '🔧' : '❌';
            const typeClass = item.type === 'repair' && item.message === 'repaired' ? 'activity-success' :
                            item.type === 'failure' ? 'activity-error' : 'activity-info';

            return `
                <div class="sentinel-activity-item ${typeClass}">
                    <span class="activity-icon">${icon}</span>
                    <div class="activity-content">
                        <div class="activity-title">
                            ${this.escapeHtml(item.service_name)} on ${this.escapeHtml(item.server_id)}
                        </div>
                        <div class="activity-message">
                            ${this.escapeHtml(item.message)}
                            ${item.attempts ? ` (${item.attempts} attempts)` : ''}
                        </div>
                        <div class="activity-time">${this.formatTimeAgo(item.timestamp)}</div>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = html;
    }

    // ===========================
    // Server Management
    // ===========================

    renderServers() {
        const container = document.getElementById('sentinel-servers-list');
        if (!container) return;

        if (this.servers.length === 0) {
            container.innerHTML = `
                <div class="sentinel-empty">
                    <p>No servers configured</p>
                    <button class="btn-primary" onclick="sentinelUI.showAddServerModal()">
                        ➕ Add Server
                    </button>
                </div>
            `;
            return;
        }

        const html = this.servers.map(server => `
            <div class="sentinel-server-card">
                <div class="server-header">
                    <div class="server-title">
                        <h3>${this.escapeHtml(server.description || server.id)}</h3>
                        <span class="server-id">${this.escapeHtml(server.id)}</span>
                    </div>
                    <div class="server-actions">
                        <button class="btn-sm btn-primary" onclick="sentinelUI.editServer('${server.id}')">
                            ✏️ Edit
                        </button>
                        <button class="btn-sm btn-danger" onclick="sentinelUI.deleteServer('${server.id}')">
                            🗑️ Delete
                        </button>
                    </div>
                </div>
                <div class="server-details">
                    <div class="detail-row">
                        <span class="detail-label">Host:</span>
                        <span class="detail-value">${this.escapeHtml(server.host)}:${server.port}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Username:</span>
                        <span class="detail-value">${this.escapeHtml(server.username)}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Added:</span>
                        <span class="detail-value">${this.formatTimestamp(server.added)}</span>
                    </div>
                </div>
            </div>
        `).join('');

        container.innerHTML = `
            <div class="sentinel-servers-header">
                <button class="btn-primary" onclick="sentinelUI.showAddServerModal()">
                    ➕ Add Server
                </button>
            </div>
            <div class="sentinel-servers-grid">
                ${html}
            </div>
        `;
    }

    showAddServerModal() {
        this.showModal('add-server-modal', {
            id: '',
            host: '',
            port: 22,
            username: '',
            password: '',
            description: ''
        });
    }

    async addServer(formData) {
        try {
            const response = await fetch('/api/sentinel/servers', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });

            const result = await response.json();
            
            if (result.success) {
                this.showNotification('Server added successfully', 'success');
                await this.loadServers();
                this.renderServers();
                this.closeAllModals();
            } else {
                this.showNotification(result.error || 'Failed to add server', 'error');
            }
        } catch (error) {
            console.error('[Sentinel] Error adding server:', error);
            this.showNotification('Failed to add server', 'error');
        }
    }

    editServer(serverId) {
        const server = this.servers.find(s => s.id === serverId);
        if (!server) return;

        this.showModal('edit-server-modal', server);
    }

    async updateServer(serverId, updates) {
        try {
            const response = await fetch(`/api/sentinel/servers/${serverId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updates)
            });

            const result = await response.json();
            
            if (result.success) {
                this.showNotification('Server updated successfully', 'success');
                await this.loadServers();
                this.renderServers();
                this.closeAllModals();
            } else {
                this.showNotification(result.error || 'Failed to update server', 'error');
            }
        } catch (error) {
            console.error('[Sentinel] Error updating server:', error);
            this.showNotification('Failed to update server', 'error');
        }
    }

    async deleteServer(serverId) {
        if (!confirm('Are you sure you want to delete this server? This will also remove all monitoring configurations.')) {
            return;
        }

        try {
            const response = await fetch(`/api/sentinel/servers/${serverId}`, {
                method: 'DELETE'
            });

            const result = await response.json();
            
            if (result.success) {
                this.showNotification('Server deleted successfully', 'success');
                await this.loadServers();
                this.renderServers();
            } else {
                this.showNotification(result.error || 'Failed to delete server', 'error');
            }
        } catch (error) {
            console.error('[Sentinel] Error deleting server:', error);
            this.showNotification('Failed to delete server', 'error');
        }
    }

    // ===========================
    // Template Management
    // ===========================

    renderTemplates() {
        const container = document.getElementById('sentinel-templates-list');
        if (!container) return;

        if (this.templates.length === 0) {
            container.innerHTML = `
                <div class="sentinel-empty">
                    <p>No templates available</p>
                    <button class="btn-primary" onclick="sentinelUI.syncTemplates()">
                        🔄 Sync from GitHub
                    </button>
                </div>
            `;
            return;
        }

        const defaultTemplates = this.templates.filter(t => t.source === 'default');
        const customTemplates = this.templates.filter(t => t.source === 'custom');

        let html = `
            <div class="sentinel-templates-header">
                <button class="btn-primary" onclick="sentinelUI.syncTemplates()">
                    🔄 Sync from GitHub
                </button>
                <button class="btn-primary" onclick="sentinelUI.showUploadTemplateModal()">
                    ⬆️ Upload Template
                </button>
                <button class="btn-primary" onclick="sentinelUI.showCreateTemplateModal()">
                    ➕ Create Template
                </button>
            </div>
        `;

        if (defaultTemplates.length > 0) {
            html += '<h3>Default Templates</h3>';
            html += '<div class="sentinel-templates-grid">';
            html += defaultTemplates.map(t => this.renderTemplateCard(t, false)).join('');
            html += '</div>';
        }

        if (customTemplates.length > 0) {
            html += '<h3>Custom Templates</h3>';
            html += '<div class="sentinel-templates-grid">';
            html += customTemplates.map(t => this.renderTemplateCard(t, true)).join('');
            html += '</div>';
        }

        container.innerHTML = html;
    }

    renderTemplateCard(template, canDelete) {
        return `
            <div class="sentinel-template-card">
                <div class="template-header">
                    <h4>${this.escapeHtml(template.name)}</h4>
                    <span class="template-source">${template.source}</span>
                </div>
                <div class="template-details">
                    <div class="detail-row">
                        <span class="detail-label">ID:</span>
                        <span class="detail-value">${this.escapeHtml(template.id)}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Check:</span>
                        <code class="detail-value">${this.escapeHtml(template.check_cmd)}</code>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Fix:</span>
                        <code class="detail-value">${this.escapeHtml(template.fix_cmd || 'N/A')}</code>
                    </div>
                </div>
                <div class="template-actions">
                    <button class="btn-sm btn-primary" onclick="sentinelUI.downloadTemplate('${template.filename}')">
                        ⬇️ Download
                    </button>
                    <button class="btn-sm btn-primary" onclick="sentinelUI.viewTemplate('${template.filename}')">
                        👁️ View
                    </button>
                    ${canDelete ? `
                        <button class="btn-sm btn-danger" onclick="sentinelUI.deleteTemplate('${template.filename}')">
                            🗑️ Delete
                        </button>
                    ` : ''}
                </div>
            </div>
        `;
    }

    async syncTemplates() {
        this.showNotification('Syncing templates from GitHub...', 'info');
        
        try {
            const response = await fetch('/api/sentinel/templates/sync', {
                method: 'POST'
            });

            const result = await response.json();
            
            if (result.success) {
                const total = result.total || 0;
                this.showNotification(`Synced ${total} templates successfully`, 'success');
                await this.loadTemplates();
                this.renderTemplates();
            } else {
                this.showNotification(result.error || 'Failed to sync templates', 'error');
            }
        } catch (error) {
            console.error('[Sentinel] Error syncing templates:', error);
            this.showNotification('Failed to sync templates', 'error');
        }
    }

    async downloadTemplate(filename) {
        try {
            const response = await fetch(`/api/sentinel/templates/${filename}`);
            const result = await response.json();
            
            if (result.success) {
                const blob = new Blob([result.content], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                a.click();
                URL.revokeObjectURL(url);
            } else {
                this.showNotification(result.error || 'Failed to download template', 'error');
            }
        } catch (error) {
            console.error('[Sentinel] Error downloading template:', error);
            this.showNotification('Failed to download template', 'error');
        }
    }

    async viewTemplate(filename) {
        try {
            const response = await fetch(`/api/sentinel/templates/${filename}`);
            const result = await response.json();
            
            if (result.success) {
                const template = JSON.parse(result.content);
                this.showModal('view-template-modal', template);
            } else {
                this.showNotification(result.error || 'Failed to load template', 'error');
            }
        } catch (error) {
            console.error('[Sentinel] Error viewing template:', error);
            this.showNotification('Failed to view template', 'error');
        }
    }

    async deleteTemplate(filename) {
        if (!confirm('Are you sure you want to delete this template?')) {
            return;
        }

        try {
            const response = await fetch(`/api/sentinel/templates/${filename}`, {
                method: 'DELETE'
            });

            const result = await response.json();
            
            if (result.success) {
                this.showNotification('Template deleted successfully', 'success');
                await this.loadTemplates();
                this.renderTemplates();
            } else {
                this.showNotification(result.error || 'Failed to delete template', 'error');
            }
        } catch (error) {
            console.error('[Sentinel] Error deleting template:', error);
            this.showNotification('Failed to delete template', 'error');
        }
    }

    showUploadTemplateModal() {
        this.showModal('upload-template-modal');
    }

    showCreateTemplateModal() {
        this.showModal('create-template-modal', {
            id: '',
            name: '',
            check_cmd: '',
            fix_cmd: '',
            verify_cmd: '',
            expected_output: '',
            retry_count: 2,
            retry_delay: 30
        });
    }

    // ===========================
    // Monitoring Configuration
    // ===========================

    renderMonitoring() {
        const container = document.getElementById('sentinel-monitoring-list');
        if (!container) return;

        if (this.monitoring.length === 0) {
            container.innerHTML = `
                <div class="sentinel-empty">
                    <p>No monitoring configurations</p>
                    <button class="btn-primary" onclick="sentinelUI.showAddMonitoringModal()">
                        ➕ Add Monitoring
                    </button>
                </div>
            `;
            return;
        }

        const html = this.monitoring.map(mon => {
            const server = this.servers.find(s => s.id === mon.server_id);
            const serverName = server ? (server.description || server.id) : mon.server_id;

            return `
                <div class="sentinel-monitoring-card ${mon.enabled ? '' : 'monitoring-disabled'}">
                    <div class="monitoring-header">
                        <div class="monitoring-title">
                            <h3>${this.escapeHtml(serverName)}</h3>
                            <span class="monitoring-status">${mon.enabled ? '✅ Enabled' : '❌ Disabled'}</span>
                        </div>
                        <div class="monitoring-actions">
                            <button class="btn-sm btn-primary" onclick="sentinelUI.editMonitoring('${mon.server_id}')">
                                ✏️ Edit
                            </button>
                            <button class="btn-sm ${mon.enabled ? 'btn-warning' : 'btn-success'}" 
                                    onclick="sentinelUI.toggleMonitoring('${mon.server_id}', ${!mon.enabled})">
                                ${mon.enabled ? '⏸️ Disable' : '▶️ Enable'}
                            </button>
                        </div>
                    </div>
                    <div class="monitoring-details">
                        <div class="detail-row">
                            <span class="detail-label">Check Interval:</span>
                            <span class="detail-value">${mon.check_interval}s</span>
                        </div>
                        <div class="detail-row">
                            <span class="detail-label">Services:</span>
                            <span class="detail-value">${mon.services.length}</span>
                        </div>
                        <div class="detail-row">
                            <span class="detail-label">Services Monitored:</span>
                            <div class="service-tags">
                                ${mon.services.map(serviceId => {
                                    const template = this.templates.find(t => t.id === serviceId);
                                    return `<span class="service-tag">${this.escapeHtml(template ? template.name : serviceId)}</span>`;
                                }).join('')}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = `
            <div class="sentinel-monitoring-header">
                <button class="btn-primary" onclick="sentinelUI.showAddMonitoringModal()">
                    ➕ Add Monitoring
                </button>
                <button class="btn-success" onclick="sentinelUI.startAllMonitoring()">
                    ▶️ Start All
                </button>
            </div>
            <div class="sentinel-monitoring-grid">
                ${html}
            </div>
        `;
    }

    showAddMonitoringModal() {
        this.showModal('add-monitoring-modal', {
            server_id: '',
            services: [],
            check_interval: 300
        });
    }

    editMonitoring(serverId) {
        const mon = this.monitoring.find(m => m.server_id === serverId);
        if (!mon) return;

        this.showModal('edit-monitoring-modal', mon);
    }

    async toggleMonitoring(serverId, enabled) {
        try {
            const response = await fetch(`/api/sentinel/monitoring/${serverId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled })
            });

            const result = await response.json();
            
            if (result.success) {
                this.showNotification(`Monitoring ${enabled ? 'enabled' : 'disabled'}`, 'success');
                await this.loadMonitoring();
                this.renderMonitoring();
                
                // Start or stop monitoring
                if (enabled) {
                    await this.startMonitoring(serverId);
                } else {
                    await this.stopMonitoring(serverId);
                }
            } else {
                this.showNotification(result.error || 'Failed to update monitoring', 'error');
            }
        } catch (error) {
            console.error('[Sentinel] Error toggling monitoring:', error);
            this.showNotification('Failed to update monitoring', 'error');
        }
    }

    async startMonitoring(serverId) {
        try {
            await fetch(`/api/sentinel/start/${serverId}`, { method: 'POST' });
        } catch (error) {
            console.error('[Sentinel] Error starting monitoring:', error);
        }
    }

    async stopMonitoring(serverId) {
        try {
            await fetch(`/api/sentinel/stop/${serverId}`, { method: 'POST' });
        } catch (error) {
            console.error('[Sentinel] Error stopping monitoring:', error);
        }
    }

    async startAllMonitoring() {
        try {
            const response = await fetch('/api/sentinel/start-all', { method: 'POST' });
            const result = await response.json();
            
            if (result.success) {
                this.showNotification('All monitoring started', 'success');
            } else {
                this.showNotification('Failed to start monitoring', 'error');
            }
        } catch (error) {
            console.error('[Sentinel] Error starting all monitoring:', error);
            this.showNotification('Failed to start monitoring', 'error');
        }
    }

    // ===========================
    // Manual Testing with Live Logs
    // ===========================

    async manualCheck(serverId, serviceName) {
        // Find service ID from name
        const template = this.templates.find(t => t.name === serviceName);
        if (!template) {
            this.showNotification('Service template not found', 'error');
            return;
        }

        try {
            const response = await fetch('/api/sentinel/test/check', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    server_id: serverId,
                    service_id: template.id
                })
            });

            const result = await response.json();
            
            if (result.execution_id) {
                this.showLogStreamModal(result.execution_id, `Check: ${serviceName}`);
            } else {
                this.showNotification('Failed to start check', 'error');
            }
        } catch (error) {
            console.error('[Sentinel] Error starting manual check:', error);
            this.showNotification('Failed to start check', 'error');
        }
    }

    async manualRepair(serverId, serviceName) {
        if (!confirm(`Are you sure you want to manually repair ${serviceName}?`)) {
            return;
        }

        // Find service ID from name
        const template = this.templates.find(t => t.name === serviceName);
        if (!template) {
            this.showNotification('Service template not found', 'error');
            return;
        }

        try {
            const response = await fetch('/api/sentinel/test/repair', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    server_id: serverId,
                    service_id: template.id
                })
            });

            const result = await response.json();
            
            if (result.execution_id) {
                this.showLogStreamModal(result.execution_id, `Repair: ${serviceName}`);
            } else {
                this.showNotification('Failed to start repair', 'error');
            }
        } catch (error) {
            console.error('[Sentinel] Error starting manual repair:', error);
            this.showNotification('Failed to start repair', 'error');
        }
    }

    showLogStreamModal(executionId, title) {
        const modal = document.getElementById('log-stream-modal');
        if (!modal) return;

        const titleEl = modal.querySelector('.modal-title');
        const logsContainer = modal.querySelector('.log-stream-container');
        
        if (titleEl) titleEl.textContent = title;
        if (logsContainer) logsContainer.innerHTML = '';

        modal.style.display = 'flex';

        // Start SSE connection
        this.startLogStream(executionId, logsContainer);
    }

    startLogStream(executionId, container) {
        // Close existing stream if any
        if (this.activeLogStreams.has(executionId)) {
            this.activeLogStreams.get(executionId).close();
        }

        const eventSource = new EventSource(`/api/sentinel/logs/stream?execution_id=${executionId}`);
        this.activeLogStreams.set(executionId, eventSource);

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.appendLogEntry(container, data);

                // Auto-close on completion
                if (data.type === 'complete') {
                    setTimeout(() => {
                        eventSource.close();
                        this.activeLogStreams.delete(executionId);
                    }, 2000);
                }
            } catch (error) {
                console.error('[Sentinel] Error parsing log entry:', error);
            }
        };

        eventSource.onerror = () => {
            console.error('[Sentinel] SSE connection error');
            eventSource.close();
            this.activeLogStreams.delete(executionId);
            this.appendLogEntry(container, {
                type: 'error',
                line: 'Connection lost'
            });
        };
    }

    appendLogEntry(container, data) {
        const entry = document.createElement('div');
        entry.className = `log-entry log-${data.type}`;

        let content = '';
        switch(data.type) {
            case 'command':
                content = `<strong>Command:</strong> ${this.escapeHtml(data.command)}`;
                break;
            case 'output':
                content = this.escapeHtml(data.line);
                break;
            case 'error':
                content = `<strong>Error:</strong> ${this.escapeHtml(data.line)}`;
                break;
            case 'complete':
                const icon = data.success ? '✅' : '❌';
                content = `${icon} <strong>Completed</strong> (exit code: ${data.exit_code})`;
                break;
        }

        entry.innerHTML = `
            <span class="log-timestamp">${this.formatTime(data.timestamp)}</span>
            <span class="log-content">${content}</span>
        `;

        container.appendChild(entry);
        container.scrollTop = container.scrollHeight;
    }

    // ===========================
    // Log History
    // ===========================

    async renderLogHistory() {
        const container = document.getElementById('sentinel-log-history');
        if (!container) return;

        try {
            const response = await fetch('/api/sentinel/logs/history?limit=50');
            const data = await response.json();

            if (!data.executions || data.executions.length === 0) {
                container.innerHTML = '<div class="sentinel-empty">No log history available</div>';
                return;
            }

            const html = data.executions.map(exec => {
                const lastAction = exec.actions[exec.actions.length - 1];
                const success = lastAction && lastAction.exit_code === 0;
                const icon = success ? '✅' : '❌';

                return `
                    <div class="sentinel-log-card ${success ? 'log-success' : 'log-error'}">
                        <div class="log-header">
                            <span class="log-icon">${icon}</span>
                            <div class="log-info">
                                <div class="log-title">${this.escapeHtml(exec.service_name)}</div>
                                <div class="log-server">${this.escapeHtml(exec.server_id)}</div>
                            </div>
                            <div class="log-actions">
                                <button class="btn-sm btn-primary" onclick="sentinelUI.viewExecutionLogs('${exec.execution_id}')">
                                    👁️ View Logs
                                </button>
                            </div>
                        </div>
                        <div class="log-details">
                            <span class="log-time">${this.formatTimeAgo(exec.timestamp)}</span>
                            <span class="log-actions-count">${exec.actions.length} actions</span>
                            ${exec.manual ? '<span class="log-badge">Manual</span>' : ''}
                        </div>
                    </div>
                `;
            }).join('');

            container.innerHTML = html;
        } catch (error) {
            console.error('[Sentinel] Error loading log history:', error);
            container.innerHTML = '<div class="sentinel-error">Failed to load log history</div>';
        }
    }

    async viewExecutionLogs(executionId) {
        try {
            const response = await fetch(`/api/sentinel/logs/execution/${executionId}`);
            const data = await response.json();

            if (data.logs) {
                this.showModal('view-execution-logs-modal', data);
            } else {
                this.showNotification('Execution logs not found', 'error');
            }
        } catch (error) {
            console.error('[Sentinel] Error loading execution logs:', error);
            this.showNotification('Failed to load logs', 'error');
        }
    }

    // ===========================
    // Settings
    // ===========================

    renderSettings() {
        const container = document.getElementById('sentinel-settings-container');
        if (!container) return;

        container.innerHTML = `
            <div class="sentinel-settings">
                <h3>Quiet Hours</h3>
                <div class="settings-section">
                    <label>
                        <input type="checkbox" id="quiet-hours-enabled" 
                               ${this.quietHours.enabled ? 'checked' : ''}>
                        Enable Quiet Hours
                    </label>
                    <div class="settings-row">
                        <label>
                            Start Time:
                            <input type="time" id="quiet-hours-start" 
                                   value="${this.quietHours.start || '22:00'}">
                        </label>
                        <label>
                            End Time:
                            <input type="time" id="quiet-hours-end" 
                                   value="${this.quietHours.end || '08:00'}">
                        </label>
                    </div>
                    <button class="btn-primary" onclick="sentinelUI.saveQuietHours()">
                        💾 Save Quiet Hours
                    </button>
                </div>

                <h3>Maintenance Windows</h3>
                <div class="settings-section">
                    <button class="btn-primary" onclick="sentinelUI.addMaintenanceWindow()">
                        ➕ Add Maintenance Window
                    </button>
                    <div id="maintenance-windows-list">
                        ${this.renderMaintenanceWindowsList()}
                    </div>
                </div>

                <h3>Data Management</h3>
                <div class="settings-section">
                    <button class="btn-warning" onclick="sentinelUI.showPurgeModal()">
                        🗑️ Purge Old Logs
                    </button>
                    <p class="settings-help">Remove old check/repair logs to free up space</p>
                </div>
            </div>
        `;
    }

    renderMaintenanceWindowsList() {
        if (this.maintenanceWindows.length === 0) {
            return '<p class="settings-empty">No maintenance windows configured</p>';
        }

        return this.maintenanceWindows.map((window, index) => `
            <div class="maintenance-window-card">
                <div class="window-info">
                    <strong>${window.start_time} - ${window.end_time}</strong>
                    <span>${window.days ? window.days.join(', ') : 'All days'}</span>
                    ${window.server_id ? `<span>Server: ${window.server_id}</span>` : '<span>All servers</span>'}
                </div>
                <div class="window-actions">
                    <button class="btn-sm btn-danger" onclick="sentinelUI.deleteMaintenanceWindow(${index})">
                        🗑️
                    </button>
                </div>
            </div>
        `).join('');
    }

    async saveQuietHours() {
        const enabled = document.getElementById('quiet-hours-enabled').checked;
        const start = document.getElementById('quiet-hours-start').value;
        const end = document.getElementById('quiet-hours-end').value;

        try {
            const response = await fetch('/api/sentinel/quiet-hours', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled, start, end })
            });

            const result = await response.json();
            
            if (result.success) {
                this.showNotification('Quiet hours updated', 'success');
                await this.loadQuietHours();
            } else {
                this.showNotification('Failed to update quiet hours', 'error');
            }
        } catch (error) {
            console.error('[Sentinel] Error saving quiet hours:', error);
            this.showNotification('Failed to save quiet hours', 'error');
        }
    }

    addMaintenanceWindow() {
        this.showModal('add-maintenance-window-modal', {
            start_time: '22:00',
            end_time: '06:00',
            days: [],
            server_id: null,
            enabled: true
        });
    }

    async deleteMaintenanceWindow(index) {
        if (!confirm('Delete this maintenance window?')) return;

        try {
            const response = await fetch(`/api/sentinel/maintenance/${index}`, {
                method: 'DELETE'
            });

            const result = await response.json();
            
            if (result.success) {
                this.showNotification('Maintenance window deleted', 'success');
                await this.loadMaintenanceWindows();
                this.renderSettings();
            } else {
                this.showNotification('Failed to delete maintenance window', 'error');
            }
        } catch (error) {
            console.error('[Sentinel] Error deleting maintenance window:', error);
            this.showNotification('Failed to delete maintenance window', 'error');
        }
    }

    showPurgeModal() {
        this.showModal('purge-logs-modal', {
            days: 90,
            server_id: null,
            service_name: null,
            successful_only: false
        });
    }

    async purgeOldLogs(options) {
        if (!confirm('This will permanently delete old logs. Continue?')) return;

        try {
            const response = await fetch('/api/sentinel/purge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(options)
            });

            const result = await response.json();
            
            if (result.success) {
                this.showNotification(`Purged ${result.deleted} log entries`, 'success');
                this.closeAllModals();
            } else {
                this.showNotification('Failed to purge logs', 'error');
            }
        } catch (error) {
            console.error('[Sentinel] Error purging logs:', error);
            this.showNotification('Failed to purge logs', 'error');
        }
    }

    // ===========================
    // Auto Refresh
    // ===========================

    startAutoRefresh() {
        // Refresh dashboard every 30 seconds
        this.dashboardInterval = setInterval(() => {
            if (this.currentView === 'dashboard') {
                this.loadDashboard();
            }
        }, 30000);

        // Refresh live status every 10 seconds
        this.liveStatusInterval = setInterval(() => {
            if (this.currentView === 'dashboard') {
                this.loadLiveStatus();
            }
        }, 10000);
    }

    stopAutoRefresh() {
        if (this.dashboardInterval) {
            clearInterval(this.dashboardInterval);
        }
        if (this.liveStatusInterval) {
            clearInterval(this.liveStatusInterval);
        }
    }

    // ===========================
    // UI Helpers
    // ===========================

    showModal(modalId, data = null) {
        const modal = document.getElementById(modalId);
        if (!modal) return;

        if (data) {
            // Populate modal with data
            Object.keys(data).forEach(key => {
                const input = modal.querySelector(`[name="${key}"]`);
                if (input) {
                    if (input.type === 'checkbox') {
                        input.checked = data[key];
                    } else {
                        input.value = data[key];
                    }
                }
            });
        }

        modal.style.display = 'flex';
    }

    closeAllModals() {
        document.querySelectorAll('.sentinel-modal').forEach(modal => {
            modal.style.display = 'none';
        });

        // Close all log streams
        this.activeLogStreams.forEach(stream => stream.close());
        this.activeLogStreams.clear();
    }

    showNotification(message, type = 'info') {
        // Use Jarvis notify system if available
        if (window.jarvisNotify) {
            const priority = type === 'error' ? 7 : type === 'warning' ? 5 : 3;
            window.jarvisNotify({
                title: 'Sentinel',
                body: message,
                source: 'sentinel',
                priority
            });
        } else {
            console.log(`[Sentinel ${type}]`, message);
            alert(message);
        }
    }

    // ===========================
    // Utility Functions
    // ===========================

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    formatTimestamp(timestamp) {
        if (!timestamp) return 'Never';
        const date = new Date(timestamp);
        return date.toLocaleString();
    }

    formatTimeAgo(timestamp) {
        if (!timestamp) return 'Never';
        
        const now = new Date();
        const then = new Date(timestamp);
        const seconds = Math.floor((now - then) / 1000);

        if (seconds < 60) return `${seconds}s ago`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
        return `${Math.floor(seconds / 86400)}d ago`;
    }

    formatTime(timestamp) {
        if (!timestamp) return '';
        const date = new Date(timestamp);
        return date.toLocaleTimeString();
    }
}

// Initialize Sentinel UI
let sentinelUI;
document.addEventListener('DOMContentLoaded', () => {
    sentinelUI = new SentinelUI();
});
