// /app/www/js/sentinel.js
// Frontend for Sentinel autonomous monitoring system
// Integrates with Jarvis Prime UI

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
        this.isActive = false;
    }

    async init() {
        console.log('[Sentinel] Initializing...');
        await this.loadInitialData();
        this.setupEventListeners();
    }

    async activate() {
        if (this.isActive) return;
        this.isActive = true;
        
        console.log('[Sentinel] Activating...');
        await this.loadInitialData();
        this.loadDashboard();
        this.loadLiveStatus();
        this.loadRecentActivity(10);
        this.startAutoRefresh();
    }

    deactivate() {
        this.isActive = false;
        this.stopAutoRefresh();
        this.closeAllLogStreams();
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
            if (window.showToast) {
                window.showToast('Failed to load Sentinel data', 'error');
            }
        }
    }

    // ===========================
    // Data Loading
    // ===========================

    async loadServers() {
        try {
            const response = await fetch(API('api/sentinel/servers'));
            const data = await response.json();
            this.servers = data.servers || [];
        } catch (error) {
            console.error('[Sentinel] Error loading servers:', error);
        }
    }

    async loadTemplates() {
        try {
            const response = await fetch(API('api/sentinel/templates'));
            const data = await response.json();
            this.templates = data.templates || [];
        } catch (error) {
            console.error('[Sentinel] Error loading templates:', error);
        }
    }

    async loadMonitoring() {
        try {
            const response = await fetch(API('api/sentinel/monitoring'));
            const data = await response.json();
            this.monitoring = data.monitoring || [];
        } catch (error) {
            console.error('[Sentinel] Error loading monitoring:', error);
        }
    }

    async loadMaintenanceWindows() {
        try {
            const response = await fetch(API('api/sentinel/maintenance'));
            const data = await response.json();
            this.maintenanceWindows = data.windows || [];
        } catch (error) {
            console.error('[Sentinel] Error loading maintenance windows:', error);
        }
    }

    async loadQuietHours() {
        try {
            const response = await fetch(API('api/sentinel/quiet-hours'));
            this.quietHours = await response.json();
        } catch (error) {
            console.error('[Sentinel] Error loading quiet hours:', error);
        }
    }

    async loadDashboard() {
        try {
            const response = await fetch(API('api/sentinel/dashboard'));
            const metrics = await response.json();
            this.renderDashboard(metrics);
        } catch (error) {
            console.error('[Sentinel] Error loading dashboard:', error);
        }
    }

    async loadLiveStatus() {
        try {
            const response = await fetch(API('api/sentinel/status'));
            const data = await response.json();
            this.renderLiveStatus(data.status || []);
        } catch (error) {
            console.error('[Sentinel] Error loading live status:', error);
        }
    }

    async loadRecentActivity(limit = 20) {
        try {
            const response = await fetch(API(`api/sentinel/activity?limit=${limit}`));
            const data = await response.json();
            this.renderRecentActivity(data.activity || []);
        } catch (error) {
            console.error('[Sentinel] Error loading activity:', error);
        }
    }

    // ===========================
    // Event Listeners
    // ===========================

    setupEventListeners() {
        // Sub-navigation within Sentinel
        const subNavButtons = document.querySelectorAll('.sentinel-subnav-btn');
        subNavButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const view = e.target.dataset.view;
                this.showSubView(view);
            });
        });
    }

    showSubView(viewName) {
        // Hide all sub-views
        document.querySelectorAll('.sentinel-subview').forEach(view => {
            view.classList.remove('active');
        });

        // Show selected sub-view
        const view = document.querySelector(`.sentinel-subview[data-view="${viewName}"]`);
        if (view) {
            view.classList.add('active');
        }

        // Update sub-nav
        document.querySelectorAll('.sentinel-subnav-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === viewName);
        });

        // Load view data
        this.loadSubViewData(viewName);
    }

    async loadSubViewData(viewName) {
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
        // Update metric cards
        $('#sentinel-total-checks').textContent = metrics.total_checks || 0;
        $('#sentinel-checks-today').textContent = metrics.checks_today || 0;
        $('#sentinel-services-monitored').textContent = metrics.services_monitored || 0;
        $('#sentinel-servers-monitored').textContent = metrics.servers_monitored || 0;
        $('#sentinel-services-down').textContent = metrics.services_down || 0;
        $('#sentinel-uptime').textContent = `${metrics.uptime_percent || 100}%`;
        $('#sentinel-avg-response').textContent = `${metrics.avg_response_time || 0}s`;
        $('#sentinel-repairs-all').textContent = metrics.repairs_all_time || 0;
        $('#sentinel-repairs-today').textContent = metrics.repairs_today || 0;
        $('#sentinel-failed-repairs').textContent = metrics.failed_repairs || 0;
    }

    renderLiveStatus(services) {
        const container = $('#sentinel-live-status');
        if (!container) return;

        if (services.length === 0) {
            container.innerHTML = '<div class="text-center text-muted">No services being monitored</div>';
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
                        <button class="btn" onclick="sentinelUI.manualCheck('${service.server_id}', '${service.service_name}')">
                            🔍 Check Now
                        </button>
                        <button class="btn" onclick="sentinelUI.manualRepair('${service.server_id}', '${service.service_name}')">
                            🔧 Repair
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = html;
    }

    renderRecentActivity(activity) {
        const container = $('#sentinel-recent-activity');
        if (!container) return;

        if (activity.length === 0) {
            container.innerHTML = '<div class="text-center text-muted">No recent activity</div>';
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
        const container = $('#sentinel-servers-list');
        if (!container) return;

        if (this.servers.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted">
                    <p>No servers configured</p>
                    <button class="btn primary" onclick="sentinelUI.showAddServerModal()">
                        ➕ Add Server
                    </button>
                </div>
            `;
            return;
        }

        const html = this.servers.map(server => `
            <div class="glass-card" style="margin-bottom: 16px;">
                <div class="card-header">
                    <h3 class="card-title">${this.escapeHtml(server.description || server.id)}</h3>
                    <div style="display: flex; gap: 8px;">
                        <button class="btn" onclick="sentinelUI.editServer('${server.id}')">
                            ✏️ Edit
                        </button>
                        <button class="btn danger" onclick="sentinelUI.deleteServer('${server.id}')">
                            🗑️ Delete
                        </button>
                    </div>
                </div>
                <div style="padding: 16px;">
                    <div style="margin-bottom: 8px;">
                        <strong>Host:</strong> ${this.escapeHtml(server.host)}:${server.port}
                    </div>
                    <div style="margin-bottom: 8px;">
                        <strong>Username:</strong> ${this.escapeHtml(server.username)}
                    </div>
                    <div>
                        <strong>Added:</strong> ${this.formatTimestamp(server.added)}
                    </div>
                </div>
            </div>
        `).join('');

        container.innerHTML = html;
    }

    showAddServerModal() {
        const modal = $('#sentinel-add-server-modal');
        if (modal) {
            modal.style.display = 'flex';
        }
    }

    async addServer(formData) {
        try {
            const response = await fetch(API('api/sentinel/servers'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });

            const result = await response.json();
            
            if (result.success) {
                if (window.showToast) {
                    window.showToast('Server added successfully', 'success');
                }
                await this.loadServers();
                this.renderServers();
                this.closeModal();
            } else {
                if (window.showToast) {
                    window.showToast(result.error || 'Failed to add server', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error adding server:', error);
            if (window.showToast) {
                window.showToast('Failed to add server', 'error');
            }
        }
    }

    editServer(serverId) {
        const server = this.servers.find(s => s.id === serverId);
        if (!server) return;

        const modal = $('#sentinel-edit-server-modal');
        if (modal) {
            // Populate form
            $('#sentinel-edit-server-id').value = server.id;
            $('input[name="host"]', modal).value = server.host;
            $('input[name="port"]', modal).value = server.port;
            $('input[name="username"]', modal).value = server.username;
            $('input[name="password"]', modal).value = '';
            $('input[name="description"]', modal).value = server.description || '';
            
            modal.style.display = 'flex';
        }
    }

    async updateServer(serverId, updates) {
        try {
            const response = await fetch(API(`api/sentinel/servers/${serverId}`), {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updates)
            });

            const result = await response.json();
            
            if (result.success) {
                if (window.showToast) {
                    window.showToast('Server updated successfully', 'success');
                }
                await this.loadServers();
                this.renderServers();
                this.closeModal();
            } else {
                if (window.showToast) {
                    window.showToast(result.error || 'Failed to update server', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error updating server:', error);
            if (window.showToast) {
                window.showToast('Failed to update server', 'error');
            }
        }
    }

    async deleteServer(serverId) {
        if (!confirm('Are you sure you want to delete this server? This will also remove all monitoring configurations.')) {
            return;
        }

        try {
            const response = await fetch(API(`api/sentinel/servers/${serverId}`), {
                method: 'DELETE'
            });

            const result = await response.json();
            
            if (result.success) {
                if (window.showToast) {
                    window.showToast('Server deleted successfully', 'success');
                }
                await this.loadServers();
                this.renderServers();
            } else {
                if (window.showToast) {
                    window.showToast(result.error || 'Failed to delete server', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error deleting server:', error);
            if (window.showToast) {
                window.showToast('Failed to delete server', 'error');
            }
        }
    }

    // ===========================
    // Template Management
    // ===========================

    renderTemplates() {
        const container = $('#sentinel-templates-list');
        if (!container) return;

        if (this.templates.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted">
                    <p>No templates available</p>
                    <button class="btn primary" onclick="sentinelUI.syncTemplates()">
                        🔄 Sync from GitHub
                    </button>
                </div>
            `;
            return;
        }

        const html = `
            <div style="margin-bottom: 16px; display: flex; gap: 8px; flex-wrap: wrap;">
                <button class="btn primary" onclick="sentinelUI.syncTemplates()">
                    🔄 Sync from GitHub
                </button>
                <button class="btn primary" onclick="sentinelUI.showUploadTemplateModal()">
                    ⬆️ Upload Template
                </button>
                <button class="btn primary" onclick="sentinelUI.showCreateTemplateModal()">
                    ➕ Create Template
                </button>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px;">
                ${this.templates.map(template => `
                    <div class="glass-card">
                        <div class="card-header">
                            <h4>${this.escapeHtml(template.name)}</h4>
                            <span class="status-badge">${template.source}</span>
                        </div>
                        <div style="padding: 16px; font-size: 13px;">
                            <div style="margin-bottom: 8px;">
                                <strong>ID:</strong> ${this.escapeHtml(template.id)}
                            </div>
                            <div style="margin-bottom: 8px;">
                                <strong>Check:</strong><br>
                                <code style="font-size: 11px;">${this.escapeHtml(template.check_cmd)}</code>
                            </div>
                            ${template.fix_cmd ? `
                                <div>
                                    <strong>Fix:</strong><br>
                                    <code style="font-size: 11px;">${this.escapeHtml(template.fix_cmd)}</code>
                                </div>
                            ` : ''}
                        </div>
                        <div style="padding: 12px; border-top: 1px solid var(--surface-border); display: flex; gap: 8px;">
                            <button class="btn" style="flex: 1;" onclick="sentinelUI.viewTemplate('${template.filename}')">
                                👁️ View
                            </button>
                            ${template.source === 'custom' ? `
                                <button class="btn danger" onclick="sentinelUI.deleteTemplate('${template.filename}')">
                                    🗑️
                                </button>
                            ` : ''}
                        </div>
                    </div>
                `).join('')}
            </div>
        `;

        container.innerHTML = html;
    }

    async syncTemplates() {
        if (window.showToast) {
            window.showToast('Syncing templates from GitHub...', 'info');
        }
        
        try {
            const response = await fetch(API('api/sentinel/templates/sync'), {
                method: 'POST'
            });

            const result = await response.json();
            
            if (result.success) {
                const total = result.total || 0;
                if (window.showToast) {
                    window.showToast(`Synced ${total} templates successfully`, 'success');
                }
                await this.loadTemplates();
                this.renderTemplates();
            } else {
                if (window.showToast) {
                    window.showToast(result.error || 'Failed to sync templates', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error syncing templates:', error);
            if (window.showToast) {
                window.showToast('Failed to sync templates', 'error');
            }
        }
    }

    showUploadTemplateModal() {
        const modal = $('#sentinel-upload-template-modal');
        if (modal) {
            modal.style.display = 'flex';
        }
    }

    showCreateTemplateModal() {
        const modal = $('#sentinel-create-template-modal');
        if (modal) {
            modal.style.display = 'flex';
        }
    }

    async viewTemplate(filename) {
        try {
            const response = await fetch(API(`api/sentinel/templates/${filename}`));
            const result = await response.json();
            
            if (result.success) {
                const modal = $('#sentinel-view-template-modal');
                if (modal) {
                    const pre = $('pre', modal);
                    if (pre) {
                        pre.textContent = result.content;
                    }
                    modal.style.display = 'flex';
                }
            } else {
                if (window.showToast) {
                    window.showToast(result.error || 'Failed to load template', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error viewing template:', error);
            if (window.showToast) {
                window.showToast('Failed to view template', 'error');
            }
        }
    }

    async deleteTemplate(filename) {
        if (!confirm('Are you sure you want to delete this template?')) {
            return;
        }

        try {
            const response = await fetch(API(`api/sentinel/templates/${filename}`), {
                method: 'DELETE'
            });

            const result = await response.json();
            
            if (result.success) {
                if (window.showToast) {
                    window.showToast('Template deleted successfully', 'success');
                }
                await this.loadTemplates();
                this.renderTemplates();
            } else {
                if (window.showToast) {
                    window.showToast(result.error || 'Failed to delete template', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error deleting template:', error);
            if (window.showToast) {
                window.showToast('Failed to delete template', 'error');
            }
        }
    }

    // ===========================
    // Monitoring Configuration
    // ===========================

    renderMonitoring() {
        const container = $('#sentinel-monitoring-list');
        if (!container) return;

        if (this.monitoring.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted">
                    <p>No monitoring configurations</p>
                    <button class="btn primary" onclick="sentinelUI.showAddMonitoringModal()">
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
                <div class="glass-card" style="margin-bottom: 16px; ${!mon.enabled ? 'opacity: 0.6;' : ''}">
                    <div class="card-header">
                        <div>
                            <h3 class="card-title">${this.escapeHtml(serverName)}</h3>
                            <span class="status-badge ${mon.enabled ? 'status-online' : 'status-offline'}">
                                ${mon.enabled ? '✅ Enabled' : '❌ Disabled'}
                            </span>
                        </div>
                        <div style="display: flex; gap: 8px;">
                            <button class="btn ${mon.enabled ? '' : 'primary'}" onclick="sentinelUI.toggleMonitoring('${mon.server_id}', ${!mon.enabled})">
                                ${mon.enabled ? '⏸️ Disable' : '▶️ Enable'}
                            </button>
                        </div>
                    </div>
                    <div style="padding: 16px;">
                        <div style="margin-bottom: 8px;">
                            <strong>Check Interval:</strong> ${mon.check_interval}s
                        </div>
                        <div>
                            <strong>Services:</strong> ${mon.services.length}
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = `
            <div style="margin-bottom: 16px; display: flex; gap: 8px;">
                <button class="btn primary" onclick="sentinelUI.showAddMonitoringModal()">
                    ➕ Add Monitoring
                </button>
                <button class="btn success" onclick="sentinelUI.startAllMonitoring()">
                    ▶️ Start All
                </button>
            </div>
            ${html}
        `;
    }

    showAddMonitoringModal() {
        const modal = $('#sentinel-add-monitoring-modal');
        if (!modal) return;
        
        // Populate server dropdown
        const serverSelect = $('#sentinel-mon-server-select');
        if (serverSelect) {
            serverSelect.innerHTML = '<option value="">Select a server...</option>' +
                this.servers.map(server => 
                    `<option value="${this.escapeHtml(server.id)}">${this.escapeHtml(server.description || server.id)}</option>`
                ).join('');
            
            // Listen for server selection to show available templates
            serverSelect.onchange = () => {
                this.updateMonitoringTemplatesList(serverSelect.value);
            };
        }
        
        // Clear checkboxes area
        const checkboxesDiv = $('#sentinel-mon-services-checkboxes');
        if (checkboxesDiv) {
            checkboxesDiv.innerHTML = '<div class="text-center text-muted">Select a server first</div>';
        }
        
        modal.style.display = 'flex';
    }
    
    updateMonitoringTemplatesList(serverId) {
        const checkboxesDiv = $('#sentinel-mon-services-checkboxes');
        if (!checkboxesDiv) return;
        
        if (!serverId) {
            checkboxesDiv.innerHTML = '<div class="text-center text-muted">Select a server first</div>';
            return;
        }
        
        // Show all available templates as checkboxes
        const html = this.templates.map(template => `
            <label style="display: flex; align-items: center; gap: 8px; padding: 8px; cursor: pointer; border-radius: 4px; transition: background 0.2s;"
                   onmouseover="this.style.background='var(--surface-tertiary)'"
                   onmouseout="this.style.background='transparent'">
                <input type="checkbox" name="service_template" value="${this.escapeHtml(template.id)}" 
                       style="cursor: pointer;">
                <div>
                    <div style="font-weight: 500;">${this.escapeHtml(template.name)}</div>
                    <div style="font-size: 11px; color: var(--text-muted);">${this.escapeHtml(template.id)}</div>
                </div>
            </label>
        `).join('');
        
        checkboxesDiv.innerHTML = html || '<div class="text-center text-muted">No templates available</div>';
    }
    
    async saveMonitoring() {
        const form = document.getElementById('sentinel-add-monitoring-form');
        if (!form) return;
        
        const serverId = $('#sentinel-mon-server-select').value;
        if (!serverId) {
            if (window.showToast) {
                window.showToast('Please select a server', 'error');
            }
            return;
        }
        
        // Get all checked templates
        const checkboxes = document.querySelectorAll('input[name="service_template"]:checked');
        const services = Array.from(checkboxes).map(cb => cb.value);
        
        if (services.length === 0) {
            if (window.showToast) {
                window.showToast('Please select at least one service to monitor', 'error');
            }
            return;
        }
        
        const checkInterval = parseInt(document.querySelector('input[name="check_interval"]').value) || 300;
        
        try {
            const response = await fetch(API('api/sentinel/monitoring'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    server_id: serverId,
                    services: services,
                    check_interval: checkInterval
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                if (window.showToast) {
                    window.showToast('Monitoring configuration saved successfully', 'success');
                }
                await this.loadMonitoring();
                this.renderMonitoring();
                this.closeModal();
                
                // Ask if user wants to start monitoring now
                if (confirm('Monitoring configuration saved. Start monitoring this server now?')) {
                    await this.startMonitoring(serverId);
                }
            } else {
                if (window.showToast) {
                    window.showToast(result.error || 'Failed to save monitoring configuration', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error saving monitoring:', error);
            if (window.showToast) {
                window.showToast('Failed to save monitoring configuration', 'error');
            }
        }
    }

    async toggleMonitoring(serverId, enabled) {
        try {
            const response = await fetch(API(`api/sentinel/monitoring/${serverId}`), {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled })
            });

            const result = await response.json();
            
            if (result.success) {
                if (window.showToast) {
                    window.showToast(`Monitoring ${enabled ? 'enabled' : 'disabled'}`, 'success');
                }
                await this.loadMonitoring();
                this.renderMonitoring();
                
                // Start or stop monitoring
                if (enabled) {
                    await this.startMonitoring(serverId);
                } else {
                    await this.stopMonitoring(serverId);
                }
            } else {
                if (window.showToast) {
                    window.showToast(result.error || 'Failed to update monitoring', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error toggling monitoring:', error);
            if (window.showToast) {
                window.showToast('Failed to update monitoring', 'error');
            }
        }
    }

    async startMonitoring(serverId) {
        try {
            await fetch(API(`api/sentinel/start/${serverId}`), { method: 'POST' });
        } catch (error) {
            console.error('[Sentinel] Error starting monitoring:', error);
        }
    }

    async stopMonitoring(serverId) {
        try {
            await fetch(API(`api/sentinel/stop/${serverId}`), { method: 'POST' });
        } catch (error) {
            console.error('[Sentinel] Error stopping monitoring:', error);
        }
    }

    async startAllMonitoring() {
        try {
            const response = await fetch(API('api/sentinel/start-all'), { method: 'POST' });
            const result = await response.json();
            
            if (result.success) {
                if (window.showToast) {
                    window.showToast('All monitoring started', 'success');
                }
            } else {
                if (window.showToast) {
                    window.showToast('Failed to start monitoring', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error starting all monitoring:', error);
            if (window.showToast) {
                window.showToast('Failed to start monitoring', 'error');
            }
        }
    }

    // ===========================
    // Manual Testing
    // ===========================

    async manualCheck(serverId, serviceName) {
        // Find service ID from name
        const template = this.templates.find(t => t.name === serviceName);
        if (!template) {
            if (window.showToast) {
                window.showToast('Service template not found', 'error');
            }
            return;
        }

        try {
            const response = await fetch(API('api/sentinel/test/check'), {
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
                if (window.showToast) {
                    window.showToast('Failed to start check', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error starting manual check:', error);
            if (window.showToast) {
                window.showToast('Failed to start check', 'error');
            }
        }
    }

    async manualRepair(serverId, serviceName) {
        if (!confirm(`Are you sure you want to manually repair ${serviceName}?`)) {
            return;
        }

        // Find service ID from name
        const template = this.templates.find(t => t.name === serviceName);
        if (!template) {
            if (window.showToast) {
                window.showToast('Service template not found', 'error');
            }
            return;
        }

        try {
            const response = await fetch(API('api/sentinel/test/repair'), {
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
                if (window.showToast) {
                    window.showToast('Failed to start repair', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error starting manual repair:', error);
            if (window.showToast) {
                window.showToast('Failed to start repair', 'error');
            }
        }
    }

    showLogStreamModal(executionId, title) {
        const modal = $('#sentinel-log-stream-modal');
        if (!modal) return;

        const titleEl = $('.modal-title', modal);
        const logsContainer = $('.log-stream-container', modal);
        
        if (titleEl) titleEl.textContent = title;
        if (logsContainer) logsContainer.innerHTML = '<div class="text-center text-muted">Connecting...</div>';

        modal.style.display = 'flex';

        // Start SSE connection
        this.startLogStream(executionId, logsContainer);
    }

    startLogStream(executionId, container) {
        // Close existing stream if any
        if (this.activeLogStreams.has(executionId)) {
            this.activeLogStreams.get(executionId).close();
        }

        const eventSource = new EventSource(API(`api/sentinel/logs/stream?execution_id=${executionId}`));
        this.activeLogStreams.set(executionId, eventSource);

        // Clear container
        container.innerHTML = '';

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
        entry.style.padding = '8px';
        entry.style.borderBottom = '1px solid var(--surface-border)';
        entry.style.fontFamily = 'monospace';
        entry.style.fontSize = '12px';

        let content = '';
        let color = 'var(--text-primary)';
        
        switch(data.type) {
            case 'command':
                content = `<strong>Command:</strong> ${this.escapeHtml(data.command)}`;
                color = 'var(--accent-primary)';
                break;
            case 'output':
                content = this.escapeHtml(data.line);
                break;
            case 'error':
                content = `<strong>Error:</strong> ${this.escapeHtml(data.line)}`;
                color = '#ef4444';
                break;
            case 'complete':
                const icon = data.success ? '✅' : '❌';
                content = `${icon} <strong>Completed</strong> (exit code: ${data.exit_code})`;
                color = data.success ? '#10b981' : '#ef4444';
                break;
        }

        entry.style.color = color;
        entry.innerHTML = `
            <span style="color: var(--text-muted); margin-right: 8px;">${this.formatTime(data.timestamp)}</span>
            <span>${content}</span>
        `;

        container.appendChild(entry);
        container.scrollTop = container.scrollHeight;
    }

    // ===========================
    // Log History
    // ===========================

    async renderLogHistory() {
        const container = $('#sentinel-log-history');
        if (!container) return;

        try {
            const response = await fetch(API('api/sentinel/logs/history?limit=50'));
            const data = await response.json();

            if (!data.executions || data.executions.length === 0) {
                container.innerHTML = '<div class="text-center text-muted">No log history available</div>';
                return;
            }

            const html = data.executions.map(exec => {
                const lastAction = exec.actions[exec.actions.length - 1];
                const success = lastAction && lastAction.exit_code === 0;
                const icon = success ? '✅' : '❌';

                return `
                    <div class="glass-card" style="margin-bottom: 12px;">
                        <div style="padding: 16px; display: flex; justify-content: space-between; align-items: center;">
                            <div style="display: flex; align-items: center; gap: 12px;">
                                <span style="font-size: 24px;">${icon}</span>
                                <div>
                                    <div style="font-weight: 600;">${this.escapeHtml(exec.service_name)}</div>
                                    <div style="font-size: 13px; color: var(--text-muted);">
                                        ${this.escapeHtml(exec.server_id)} • ${this.formatTimeAgo(exec.timestamp)}
                                    </div>
                                </div>
                            </div>
                            <button class="btn" onclick="sentinelUI.viewExecutionLogs('${exec.execution_id}')">
                                👁️ View Logs
                            </button>
                        </div>
                    </div>
                `;
            }).join('');

            container.innerHTML = html;
        } catch (error) {
            console.error('[Sentinel] Error loading log history:', error);
            container.innerHTML = '<div class="text-center text-muted">Failed to load log history</div>';
        }
    }

    async viewExecutionLogs(executionId) {
        try {
            const response = await fetch(API(`api/sentinel/logs/execution/${executionId}`));
            const data = await response.json();

            if (data.logs) {
                const modal = $('#sentinel-view-execution-logs-modal');
                if (modal) {
                    const content = $('#sentinel-view-execution-logs-content');
                    if (content) {
                        const html = data.logs.map(log => `
                            <div style="padding: 12px; border-bottom: 1px solid var(--surface-border); font-family: monospace; font-size: 12px;">
                                <div style="color: var(--text-muted); margin-bottom: 4px;">
                                    ${this.formatTimestamp(log.timestamp)} - ${log.action}
                                </div>
                                ${log.command ? `<div style="color: var(--accent-primary); margin-bottom: 4px;"><strong>$</strong> ${this.escapeHtml(log.command)}</div>` : ''}
                                ${log.output ? `<div style="white-space: pre-wrap;">${this.escapeHtml(log.output)}</div>` : ''}
                                <div style="color: ${log.exit_code === 0 ? '#10b981' : '#ef4444'}; margin-top: 4px;">
                                    Exit code: ${log.exit_code}
                                </div>
                            </div>
                        `).join('');
                        
                        content.innerHTML = html;
                    }
                    modal.style.display = 'flex';
                }
            } else {
                if (window.showToast) {
                    window.showToast('Execution logs not found', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error loading execution logs:', error);
            if (window.showToast) {
                window.showToast('Failed to load logs', 'error');
            }
        }
    }

    // ===========================
    // Settings
    // ===========================

    renderSettings() {
        const container = $('#sentinel-settings-container');
        if (!container) return;

        container.innerHTML = `
            <div style="padding: 20px;">
                <h3>Quiet Hours</h3>
                <div style="margin-bottom: 24px;">
                    <label style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
                        <input type="checkbox" id="quiet-hours-enabled" 
                               ${this.quietHours.enabled ? 'checked' : ''}>
                        Enable Quiet Hours
                    </label>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                        <div>
                            <label style="display: block; margin-bottom: 4px; font-size: 13px;">Start Time:</label>
                            <input type="time" id="quiet-hours-start" 
                                   value="${this.quietHours.start || '22:00'}"
                                   style="width: 100%; padding: 8px; border: 1px solid var(--border-color); border-radius: 6px; background: var(--surface-secondary); color: var(--text-primary);">
                        </div>
                        <div>
                            <label style="display: block; margin-bottom: 4px; font-size: 13px;">End Time:</label>
                            <input type="time" id="quiet-hours-end" 
                                   value="${this.quietHours.end || '08:00'}"
                                   style="width: 100%; padding: 8px; border: 1px solid var(--border-color); border-radius: 6px; background: var(--surface-secondary); color: var(--text-primary);">
                        </div>
                    </div>
                    <button class="btn primary" style="margin-top: 12px;" onclick="sentinelUI.saveQuietHours()">
                        💾 Save Quiet Hours
                    </button>
                </div>

                <h3>Data Management</h3>
                <button class="btn" onclick="sentinelUI.showPurgeModal()">
                    🗑️ Purge Old Logs
                </button>
                <p style="font-size: 13px; color: var(--text-muted); margin-top: 8px;">
                    Remove old check/repair logs to free up space
                </p>
            </div>
        `;
    }

    async saveQuietHours() {
        const enabled = $('#quiet-hours-enabled').checked;
        const start = $('#quiet-hours-start').value;
        const end = $('#quiet-hours-end').value;

        try {
            const response = await fetch(API('api/sentinel/quiet-hours'), {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled, start, end })
            });

            const result = await response.json();
            
            if (result.success) {
                if (window.showToast) {
                    window.showToast('Quiet hours updated', 'success');
                }
                await this.loadQuietHours();
            } else {
                if (window.showToast) {
                    window.showToast('Failed to update quiet hours', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error saving quiet hours:', error);
            if (window.showToast) {
                window.showToast('Failed to save quiet hours', 'error');
            }
        }
    }

    showPurgeModal() {
        if (confirm('Purge logs older than 90 days?')) {
            this.purgeOldLogs({ days: 90 });
        }
    }

    async purgeOldLogs(options) {
        try {
            const response = await fetch(API('api/sentinel/purge'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(options)
            });

            const result = await response.json();
            
            if (result.success) {
                if (window.showToast) {
                    window.showToast(`Purged ${result.deleted} log entries`, 'success');
                }
            } else {
                if (window.showToast) {
                    window.showToast('Failed to purge logs', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error purging logs:', error);
            if (window.showToast) {
                window.showToast('Failed to purge logs', 'error');
            }
        }
    }

    // ===========================
    // Auto Refresh
    // ===========================

    startAutoRefresh() {
        // Refresh dashboard every 30 seconds
        this.dashboardInterval = setInterval(() => {
            if (this.isActive) {
                this.loadDashboard();
            }
        }, 30000);

        // Refresh live status every 10 seconds
        this.liveStatusInterval = setInterval(() => {
            if (this.isActive) {
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

    closeAllLogStreams() {
        this.activeLogStreams.forEach(stream => stream.close());
        this.activeLogStreams.clear();
    }

    // ===========================
    // UI Helpers
    // ===========================

    closeModal() {
        document.querySelectorAll('.modal').forEach(modal => {
            modal.style.display = 'none';
        });
    }

    getFormData(formId) {
        const form = document.getElementById(formId);
        if (!form) return {};

        const formData = new FormData(form);
        const data = {};
        
        for (let [key, value] of formData.entries()) {
            const input = form.querySelector(`[name="${key}"]`);
            if (input && input.type === 'checkbox') {
                data[key] = input.checked;
            } else if (input && input.type === 'number') {
                data[key] = parseFloat(value);
            } else {
                data[key] = value;
            }
        }
        
        return data;
    }

    // ===========================
    // Utility Functions
    // ===========================

    escapeHtml(text) {
        if (!text) return '';
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

// Utility for $ selectors
function $(selector, context = document) {
    return context.querySelector(selector);
}

// Utility for modal closing
function closeModal() {
    document.querySelectorAll('.modal').forEach(modal => {
        modal.style.display = 'none';
    });
}

// Initialize Sentinel UI instance (but don't activate)
const sentinelUI = new SentinelUI();

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    sentinelUI.init();
});
