// /app/www/js/sentinel.js
// Frontend for Sentinel autonomous monitoring system
// FIXED: Added edit/delete monitoring, flexible purge (all/1w/1m/3m), delete logs, per-service intervals, reset stats, GitHub URL input

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

    // Data Loading
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

    // Event Listeners
    setupEventListeners() {
        const subNavButtons = document.querySelectorAll('.sentinel-subnav-btn');
        subNavButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const view = e.target.dataset.view;
                this.showSubView(view);
            });
        });
    }

    showSubView(viewName) {
        document.querySelectorAll('.sentinel-subview').forEach(view => {
            view.classList.remove('active');
        });

        const view = document.querySelector(`.sentinel-subview[data-view="${viewName}"]`);
        if (view) {
            view.classList.add('active');
        }

        document.querySelectorAll('.sentinel-subnav-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === viewName);
        });

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

    // Dashboard Rendering
    renderDashboard(metrics) {
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

    // Server Management
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

    // Template Management
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

    // FIXED: GitHub sync with URL prompt
    async syncTemplates(url = null) {
        // If no URL provided, show prompt to ask for URL
        if (!url) {
            const savedUrl = localStorage.getItem('sentinel_github_url') || '';
            url = prompt('Enter GitHub templates URL (leave blank to use saved):\n\nExample: https://api.github.com/repos/user/repo/contents/path', savedUrl);
            
            if (url === null) return; // User cancelled
            
            // Save URL if provided
            if (url) {
                localStorage.setItem('sentinel_github_url', url);
            } else {
                url = savedUrl;
            }
        }
        
        if (window.showToast) {
            window.showToast('Syncing templates from GitHub...', 'info');
        }
        
        try {
            const response = await fetch(API('api/sentinel/templates/sync'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url || undefined })
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
            
            if (response.ok) {
                const content = await response.text();
                const modal = $('#sentinel-view-template-modal');
                if (modal) {
                    const pre = $('pre', modal);
                    if (pre) {
                        pre.textContent = content;
                    }
                    modal.style.display = 'flex';
                }
            } else {
                if (window.showToast) {
                    window.showToast('Failed to load template', 'error');
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

    // Monitoring Configuration
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
                            <button class="btn" onclick="sentinelUI.editMonitoring('${mon.server_id}')">
                                ✏️ Edit
                            </button>
                            <button class="btn ${mon.enabled ? '' : 'primary'}" onclick="sentinelUI.toggleMonitoring('${mon.server_id}', ${!mon.enabled})">
                                ${mon.enabled ? '⏸️ Disable' : '▶️ Enable'}
                            </button>
                            <button class="btn danger" onclick="sentinelUI.deleteMonitoring('${mon.server_id}')">
                                🗑️ Delete
                            </button>
                        </div>
                    </div>
                    <div style="padding: 16px;">
                        <div style="margin-bottom: 8px;">
                            <strong>Default Interval:</strong> ${mon.check_interval}s
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
        
        const serverSelect = $('#sentinel-mon-server-select');
        if (serverSelect) {
            serverSelect.innerHTML = '<option value="">Select a server...</option>' +
                this.servers.map(server => 
                    `<option value="${this.escapeHtml(server.id)}">${this.escapeHtml(server.description || server.id)}</option>`
                ).join('');
            
            serverSelect.onchange = () => {
                this.updateMonitoringTemplatesList(serverSelect.value);
            };
        }
        
        const checkboxesDiv = $('#sentinel-mon-services-checkboxes');
        if (checkboxesDiv) {
            checkboxesDiv.innerHTML = '<div class="text-center text-muted">Select a server first</div>';
        }
        
        // Reset form
        document.querySelector('input[name="check_interval"]').value = 300;
        
        modal.style.display = 'flex';
    }

    editMonitoring(serverId) {
        const mon = this.monitoring.find(m => m.server_id === serverId);
        if (!mon) return;

        const modal = $('#sentinel-add-monitoring-modal');
        if (!modal) return;

        // Populate server select
        const serverSelect = $('#sentinel-mon-server-select');
        if (serverSelect) {
            serverSelect.innerHTML = '<option value="">Select a server...</option>' +
                this.servers.map(server => 
                    `<option value="${this.escapeHtml(server.id)}" ${server.id === serverId ? 'selected' : ''}>${this.escapeHtml(server.description || server.id)}</option>`
                ).join('');
            
            serverSelect.disabled = true; // Can't change server in edit mode
        }

        // Load templates and check the ones in this config
        this.updateMonitoringTemplatesList(serverId, mon.services);

        // Set interval
        document.querySelector('input[name="check_interval"]').value = mon.check_interval || 300;

        modal.style.display = 'flex';
    }

    updateMonitoringTemplatesList(serverId, selectedServices = []) {
        const checkboxesDiv = $('#sentinel-mon-services-checkboxes');
        if (!checkboxesDiv) return;
        
        if (!serverId) {
            checkboxesDiv.innerHTML = '<div class="text-center text-muted">Select a server first</div>';
            return;
        }
        
        const html = this.templates.map(template => {
            const checked = selectedServices.includes(template.id) ? 'checked' : '';
            return `
                <label style="display: flex; align-items: center; gap: 8px; padding: 8px; cursor: pointer; border-radius: 4px; transition: background 0.2s;"
                       onmouseover="this.style.background='var(--surface-tertiary)'"
                       onmouseout="this.style.background='transparent'">
                    <input type="checkbox" name="service_template" value="${this.escapeHtml(template.id)}" ${checked}
                           style="cursor: pointer;">
                    <div style="flex: 1;">
                        <div style="font-weight: 500;">${this.escapeHtml(template.name)}</div>
                        <div style="font-size: 11px; color: var(--text-muted);">${this.escapeHtml(template.id)}</div>
                    </div>
                    <input type="number" name="service_interval_${this.escapeHtml(template.id)}" 
                           placeholder="Default" min="60" max="86400" 
                           style="width: 80px; padding: 4px 8px; font-size: 12px; border: 1px solid var(--border-color); border-radius: 4px; background: var(--surface-secondary); color: var(--text-primary);"
                           title="Custom interval (seconds) - leave blank for default">
                </label>
            `;
        }).join('');
        
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
        
        const checkboxes = document.querySelectorAll('input[name="service_template"]:checked');
        const services = Array.from(checkboxes).map(cb => cb.value);
        
        if (services.length === 0) {
            if (window.showToast) {
                window.showToast('Please select at least one service to monitor', 'error');
            }
            return;
        }
        
        const checkInterval = parseInt(document.querySelector('input[name="check_interval"]').value) || 300;
        
        // Collect per-service intervals
        const serviceIntervals = {};
        services.forEach(serviceId => {
            const intervalInput = document.querySelector(`input[name="service_interval_${serviceId}"]`);
            if (intervalInput && intervalInput.value) {
                serviceIntervals[serviceId] = parseInt(intervalInput.value);
            }
        });
        
        try {
            const response = await fetch(API('api/sentinel/monitoring'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    server_id: serverId,
                    services: services,
                    check_interval: checkInterval,
                    service_intervals: serviceIntervals
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

    async deleteMonitoring(serverId) {
        if (!confirm('Are you sure you want to delete this monitoring configuration?')) {
            return;
        }

        try {
            const response = await fetch(API(`api/sentinel/monitoring/${serverId}`), {
                method: 'DELETE'
            });

            const result = await response.json();
            
            if (result.success) {
                if (window.showToast) {
                    window.showToast('Monitoring configuration deleted', 'success');
                }
                await this.loadMonitoring();
                this.renderMonitoring();
            } else {
                if (window.showToast) {
                    window.showToast(result.error || 'Failed to delete monitoring', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error deleting monitoring:', error);
            if (window.showToast) {
                window.showToast('Failed to delete monitoring', 'error');
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

    // Manual Testing
    async manualCheck(serverId, serviceName) {
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
        this.startLogStream(executionId, logsContainer);
    }

    startLogStream(executionId, container) {
        if (this.activeLogStreams.has(executionId)) {
            this.activeLogStreams.get(executionId).close();
        }

        const eventSource = new EventSource(API(`api/sentinel/logs/stream?execution_id=${executionId}`));
        this.activeLogStreams.set(executionId, eventSource);

        container.innerHTML = '';

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.appendLogEntry(container, data);

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

    // Log History
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
                            <div style="display: flex; gap: 8px;">
                                <button class="btn" onclick="sentinelUI.viewExecutionLogs('${exec.execution_id}')">
                                    👁️ View
                                </button>
                                <button class="btn danger" onclick="sentinelUI.deleteExecutionLogs('${exec.execution_id}')">
                                    🗑️ Delete
                                </button>
                            </div>
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

    async deleteExecutionLogs(executionId) {
        if (!confirm('Are you sure you want to delete these logs?')) {
            return;
        }

        try {
            const response = await fetch(API(`api/sentinel/logs/${executionId}`), {
                method: 'DELETE'
            });

            const result = await response.json();
            
            if (result.success) {
                if (window.showToast) {
                    window.showToast('Logs deleted successfully', 'success');
                }
                await this.renderLogHistory();
            } else {
                if (window.showToast) {
                    window.showToast(result.error || 'Failed to delete logs', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error deleting logs:', error);
            if (window.showToast) {
                window.showToast('Failed to delete logs', 'error');
            }
        }
    }

    // Settings
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

                <h3>Statistics</h3>
                <div style="background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; padding: 16px; margin-bottom: 24px;">
                    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px;">
                        <span style="font-size: 24px;">⚠️</span>
                        <span style="color: #ef4444; font-weight: 600;">Reset Dashboard Statistics</span>
                    </div>
                    <p style="color: var(--text-muted); font-size: 13px; margin-bottom: 12px;">
                        Clear all check history, repairs, failures, and metrics. Monitoring will continue, but all historical data will be permanently deleted.
                    </p>
                    <button class="btn danger" style="width: 100%;" onclick="sentinelUI.resetStats()">
                        🔄 Reset All Statistics
                    </button>
                </div>

                <h3>Data Management</h3>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 16px;">
                    <button class="btn" onclick="sentinelUI.purgeOldLogs({days: 7})">
                        🗑️ Purge 1 Week
                    </button>
                    <button class="btn" onclick="sentinelUI.purgeOldLogs({days: 30})">
                        🗑️ Purge 1 Month
                    </button>
                    <button class="btn" onclick="sentinelUI.purgeOldLogs({days: 90})">
                        🗑️ Purge 3 Months
                    </button>
                    <button class="btn danger" onclick="sentinelUI.purgeOldLogs({days: null})">
                        ⚠️ Purge ALL
                    </button>
                </div>
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

    async resetStats() {
        if (!confirm('⚠️ Are you sure you want to reset ALL statistics?\n\nThis will permanently delete:\n• All check history\n• All repair records\n• All failure logs\n• All metrics\n• All execution logs\n\nMonitoring will continue, but historical data cannot be recovered.')) {
            return;
        }

        try {
            const response = await fetch(API('api/sentinel/reset-stats'), {
                method: 'POST'
            });

            const result = await response.json();
            
            if (result.success) {
                const total = result.deleted?.total || 0;
                if (window.showToast) {
                    window.showToast(`Statistics reset: ${total} records deleted`, 'success');
                }
                
                // Refresh dashboard to show zeroed stats
                await this.loadDashboard();
                await this.loadLiveStatus();
                await this.loadRecentActivity(10);
            } else {
                if (window.showToast) {
                    window.showToast(result.error || 'Failed to reset statistics', 'error');
                }
            }
        } catch (error) {
            console.error('[Sentinel] Error resetting stats:', error);
            if (window.showToast) {
                window.showToast('Failed to reset statistics', 'error');
            }
        }
    }

    async purgeOldLogs(options) {
        const confirmMsg = options.days === null ? 

'⚠️ Are you sure you want to purge ALL logs? This cannot be undone!' :
            `Purge logs older than ${options.days} days?`;
            
        if (!confirm(confirmMsg)) {
            return;
        }

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

    // Auto Refresh
    startAutoRefresh() {
        this.dashboardInterval = setInterval(() => {
            if (this.isActive) {
                this.loadDashboard();
            }
        }, 30000);

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

    // UI Helpers
    closeModal() {
        document.querySelectorAll('.modal').forEach(modal => {
            modal.style.display = 'none';
        });
        
        // Re-enable server select if it was disabled
        const serverSelect = $('#sentinel-mon-server-select');
        if (serverSelect) {
            serverSelect.disabled = false;
        }
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

    // Utility Functions
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

// Utility functions
function $(selector, context = document) {
    return context.querySelector(selector);
}

function closeModal() {
    document.querySelectorAll('.modal').forEach(modal => {
        modal.style.display = 'none';
    });
}

// Initialize Sentinel UI instance
const sentinelUI = new SentinelUI();

document.addEventListener('DOMContentLoaded', () => {
    sentinelUI.init();
});


/* ============================================================================
   SENTINEL AUTO-HEAL UI ADDITIONS
   Integrated auto-heal template management
   ============================================================================ */

/* ============================================================================
   SENTINEL AUTO-HEAL UI ADDITIONS
   Add to sentinel.js
   ============================================================================ */

// ============================================================================
// API Functions
// ============================================================================

async function loadHealTemplates() {
    try {
        const response = await fetch('/api/sentinel/heal/templates');
        const data = await response.json();
        return data.templates || [];
    } catch (error) {
        console.error('Failed to load heal templates:', error);
        return [];
    }
}

async function loadPresets() {
    try {
        const response = await fetch('/api/sentinel/heal/presets');
        return await response.json();
    } catch (error) {
        console.error('Failed to load presets:', error);
        return { heal: [], check: [] };
    }
}

async function saveHealTemplate(template) {
    try {
        const method = template.id ? 'PUT' : 'POST';
        const url = template.id 
            ? `/api/sentinel/heal/templates/${template.id}`
            : '/api/sentinel/heal/templates';
        
        const response = await fetch(url, {
            method,
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(template)
        });
        
        const data = await response.json();
        
        if (data.success || data.template) {
            showNotification('Template saved successfully', 'success');
            loadHealTemplatesUI();
            clearHealTemplateForm();
        } else {
            throw new Error(data.error || 'Failed to save template');
        }
        
        return data;
    } catch (error) {
        console.error('Failed to save template:', error);
        showNotification('Failed to save template: ' + error.message, 'error');
    }
}

async function deleteHealTemplate(templateId) {
    if (!confirm('Delete this heal template?')) return;
    
    try {
        const response = await fetch(`/api/sentinel/heal/templates/${templateId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('Template deleted', 'success');
            loadHealTemplatesUI();
        } else {
            throw new Error(data.error || 'Failed to delete');
        }
    } catch (error) {
        console.error('Failed to delete template:', error);
        showNotification('Failed to delete template', 'error');
    }
}

async function toggleHealTemplate(templateId, enabled) {
    try {
        const response = await fetch(`/api/sentinel/heal/templates/${templateId}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ enabled })
        });
        
        const data = await response.json();
        
        if (data.success || data.template) {
            showNotification(`Template ${enabled ? 'enabled' : 'disabled'}`, 'success');
            loadHealTemplatesUI();
        } else {
            throw new Error(data.error || 'Failed to toggle');
        }
    } catch (error) {
        console.error('Failed to toggle template:', error);
        showNotification('Failed to toggle template', 'error');
    }
}

async function loadHealHistory(service = null, limit = 50) {
    try {
        let url = `/api/sentinel/heal/history?limit=${limit}`;
        if (service) url += `&service=${service}`;
        
        const response = await fetch(url);
        const data = await response.json();
        return data.history || [];
    } catch (error) {
        console.error('Failed to load heal history:', error);
        return [];
    }
}

async function loadAnalyticsServices() {
    try {
        const response = await fetch('/api/analytics/services');
        const data = await response.json();
        return data.services || [];
    } catch (error) {
        console.error('Failed to load analytics services:', error);
        return [];
    }
}

async function loadServers() {
    try {
        const response = await fetch('/api/sentinel/servers');
        const data = await response.json();
        return data.servers || [];
    } catch (error) {
        console.error('Failed to load servers:', error);
        return [];
    }
}

async function updateAutoHealMode() {
    const mode = document.getElementById('auto-heal-mode').value;
    
    try {
        const response = await fetch('/api/sentinel/settings', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ auto_heal_mode: mode })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification(`Auto-heal mode set to: ${mode}`, 'success');
        }
    } catch (error) {
        console.error('Failed to update auto-heal mode:', error);
        showNotification('Failed to update settings', 'error');
    }
}

// ============================================================================
// UI Rendering
// ============================================================================

function renderHealTemplateEditor(container) {
    const html = `
        <div class="heal-template-editor">
            <div class="section-header">
                <h3>🔧 Auto-Heal Templates</h3>
                <button class="btn-primary" onclick="showNewHealTemplateForm()">+ New Template</button>
            </div>
            
            <div id="heal-template-form" class="template-form" style="display:none;">
                <h4 id="heal-form-title">New Heal Template</h4>
                
                <div class="form-group">
                    <label>Service Name *</label>
                    <input type="text" id="heal-service-name" placeholder="plex" required>
                    <small>Unique name for this service</small>
                </div>
                
                <div class="form-group">
                    <label>Trigger Source *</label>
                    <select id="heal-trigger-source">
                        <option value="analytics">Analytics Only</option>
                        <option value="manual">Manual Only</option>
                        <option value="both">Both</option>
                    </select>
                    <small>When this template should trigger</small>
                </div>
                
                <div class="form-group">
                    <label>Link to Analytics Service</label>
                    <select id="heal-analytics-service">
                        <option value="">None (Manual only)</option>
                    </select>
                    <small>Optional: Link to existing Analytics monitored service</small>
                </div>
                
                <div class="form-group">
                    <label>Server *</label>
                    <select id="heal-server-id" required>
                        <option value="">Select server...</option>
                    </select>
                    <small>Which server to run commands on</small>
                </div>
                
                <div class="form-group">
                    <label>Check Command</label>
                    <div class="preset-selector">
                        <select id="heal-check-preset" onchange="applyCheckPreset()">
                            <option value="">Select preset...</option>
                        </select>
                        <input type="text" id="heal-check-command" placeholder="docker inspect -f '{{.State.Running}}' plex">
                    </div>
                    <small>Command to verify service is actually down</small>
                </div>
                
                <div class="form-group">
                    <label>Expected Output</label>
                    <input type="text" id="heal-expected-output" placeholder="true">
                    <small>What check command should return when service is UP</small>
                </div>
                
                <div class="form-group">
                    <label>Heal Commands *</label>
                    <div class="preset-selector">
                        <select id="heal-command-preset">
                            <option value="">Select preset...</option>
                        </select>
                        <button type="button" class="btn-secondary" onclick="addHealCommandFromPreset()">Add Preset</button>
                    </div>
                    <textarea id="heal-commands" rows="5" placeholder="docker restart plex
systemctl restart plexmediaserver" required></textarea>
                    <small>One command per line. Use {name}, {image}, {mac}, etc. as placeholders</small>
                </div>
                
                <div class="form-group">
                    <label>Verify Command</label>
                    <input type="text" id="heal-verify-command" placeholder="docker inspect -f '{{.State.Running}}' plex">
                    <small>Command to verify service recovered (can be same as check command)</small>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label>Retry Count</label>
                        <input type="number" id="heal-retry-count" value="3" min="1" max="10">
                        <small>Max heal attempts</small>
                    </div>
                    
                    <div class="form-group">
                        <label>Retry Delay (seconds)</label>
                        <input type="number" id="heal-retry-delay" value="10" min="5" max="300">
                        <small>Wait time between attempts</small>
                    </div>
                </div>
                
                <div class="form-group">
                    <label>
                        <input type="checkbox" id="heal-enabled" checked>
                        Enable this template
                    </label>
                </div>
                
                <div class="form-actions">
                    <button type="button" class="btn-primary" onclick="saveHealTemplateFromForm()">Save Template</button>
                    <button type="button" class="btn-secondary" onclick="cancelHealTemplateForm()">Cancel</button>
                </div>
            </div>
            
            <div class="section-header">
                <h4>📋 Existing Templates</h4>
            </div>
            <div id="heal-templates-list" class="templates-list">
                <div class="loading">Loading templates...</div>
            </div>
            
            <div class="section-header">
                <h4>📊 Heal History</h4>
                <button class="btn-secondary" onclick="loadHealHistoryUI()">Refresh</button>
            </div>
            <div id="heal-history-list" class="history-list">
                <div class="loading">Loading history...</div>
            </div>
        </div>
    `;
    
    container.innerHTML = html;
    loadHealTemplatesUI();
}

async function loadHealTemplatesUI() {
    const templates = await loadHealTemplates();
    const servers = await loadServers();
    const services = await loadAnalyticsServices();
    const presets = await loadPresets();
    
    // Populate server dropdown
    const serverSelect = document.getElementById('heal-server-id');
    if (serverSelect) {
        serverSelect.innerHTML = '<option value="">Select server...</option>';
        servers.forEach(server => {
            const opt = document.createElement('option');
            opt.value = server.id;
            opt.textContent = server.name || server.host;
            serverSelect.appendChild(opt);
        });
    }
    
    // Populate analytics service dropdown
    const serviceSelect = document.getElementById('heal-analytics-service');
    if (serviceSelect) {
        serviceSelect.innerHTML = '<option value="">None (Manual only)</option>';
        services.forEach(service => {
            const opt = document.createElement('option');
            opt.value = service.service_name;
            opt.textContent = service.service_name;
            serviceSelect.appendChild(opt);
        });
    }
    
    // Populate check presets
    const checkPresetSelect = document.getElementById('heal-check-preset');
    if (checkPresetSelect) {
        checkPresetSelect.innerHTML = '<option value="">Select preset...</option>';
        presets.check.forEach(preset => {
            const opt = document.createElement('option');
            opt.value = preset.check_command;
            opt.textContent = preset.label;
            opt.dataset.expected = preset.expected_output;
            checkPresetSelect.appendChild(opt);
        });
    }
    
    // Populate heal command presets
    const healPresetSelect = document.getElementById('heal-command-preset');
    if (healPresetSelect) {
        healPresetSelect.innerHTML = '<option value="">Select preset...</option>';
        presets.heal.forEach(preset => {
            const opt = document.createElement('option');
            opt.value = preset.cmd;
            opt.textContent = preset.label;
            healPresetSelect.appendChild(opt);
        });
    }
    
    // Render templates list
    const listDiv = document.getElementById('heal-templates-list');
    if (listDiv) {
        if (templates.length === 0) {
            listDiv.innerHTML = '<div class="empty-state">No heal templates yet. Create one to get started!</div>';
        } else {
            listDiv.innerHTML = templates.map(t => `
                <div class="heal-template-card ${t.enabled ? 'enabled' : 'disabled'}">
                    <div class="template-header">
                        <h5>${t.service_name}</h5>
                        <span class="status-badge ${t.enabled ? 'badge-success' : 'badge-muted'}">
                            ${t.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                    </div>
                    <div class="template-details">
                        <p><strong>Trigger:</strong> ${t.trigger_source}</p>
                        <p><strong>Retries:</strong> ${t.retry_count} × ${t.retry_delay}s delay</p>
                        <p><strong>Server:</strong> ${t.server_id}</p>
                        <p><strong>Commands:</strong> ${(t.heal_commands || []).length}</p>
                    </div>
                    <div class="template-actions">
                        <button class="btn-small btn-primary" onclick="editHealTemplate('${t.id}')">Edit</button>
                        <button class="btn-small ${t.enabled ? 'btn-warning' : 'btn-success'}" onclick="toggleHealTemplate('${t.id}', ${!t.enabled})">
                            ${t.enabled ? 'Disable' : 'Enable'}
                        </button>
                        <button class="btn-small btn-danger" onclick="deleteHealTemplate('${t.id}')">Delete</button>
                    </div>
                </div>
            `).join('');
        }
    }
    
    // Load history
    loadHealHistoryUI();
}

async function loadHealHistoryUI() {
    const history = await loadHealHistory();
    const listDiv = document.getElementById('heal-history-list');
    
    if (!listDiv) return;
    
    if (history.length === 0) {
        listDiv.innerHTML = '<div class="empty-state">No heal executions yet.</div>';
        return;
    }
    
    listDiv.innerHTML = history.map(h => {
        const date = new Date(h.timestamp * 1000);
        const commands = JSON.parse(h.commands_run || '[]');
        
        return `
            <div class="heal-history-card ${h.success ? 'success' : 'failed'}">
                <div class="history-header">
                    <h6>${h.service_name}</h6>
                    <span class="status-badge ${h.success ? 'badge-success' : 'badge-danger'}">
                        ${h.success ? '✅ Success' : '❌ Failed'}
                    </span>
                </div>
                <div class="history-details">
                    <p><strong>Time:</strong> ${date.toLocaleString()}</p>
                    <p><strong>Source:</strong> ${h.trigger_source}</p>
                    <p><strong>Attempts:</strong> ${h.attempts}</p>
                    <p><strong>Final Status:</strong> ${h.final_status || 'unknown'}</p>
                    ${commands.length > 0 ? `<p><strong>Commands:</strong> ${commands.join(', ')}</p>` : ''}
                    ${h.error_message ? `<p class="error-message">Error: ${h.error_message}</p>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

// ============================================================================
// Form Handlers
// ============================================================================

function showNewHealTemplateForm() {
    const form = document.getElementById('heal-template-form');
    const title = document.getElementById('heal-form-title');
    
    if (form) {
        form.style.display = 'block';
        title.textContent = 'New Heal Template';
        clearHealTemplateForm();
        form.scrollIntoView({ behavior: 'smooth' });
    }
}

function cancelHealTemplateForm() {
    const form = document.getElementById('heal-template-form');
    if (form) {
        form.style.display = 'none';
        clearHealTemplateForm();
    }
}

function clearHealTemplateForm() {
    document.getElementById('heal-service-name').value = '';
    document.getElementById('heal-trigger-source').value = 'analytics';
    document.getElementById('heal-analytics-service').value = '';
    document.getElementById('heal-server-id').value = '';
    document.getElementById('heal-check-command').value = '';
    document.getElementById('heal-expected-output').value = '';
    document.getElementById('heal-commands').value = '';
    document.getElementById('heal-verify-command').value = '';
    document.getElementById('heal-retry-count').value = '3';
    document.getElementById('heal-retry-delay').value = '10';
    document.getElementById('heal-enabled').checked = true;
    
    // Remove template ID from form
    delete document.getElementById('heal-template-form').dataset.templateId;
}

async function saveHealTemplateFromForm() {
    const form = document.getElementById('heal-template-form');
    const templateId = form.dataset.templateId;
    
    const serviceName = document.getElementById('heal-service-name').value.trim();
    const serverId = document.getElementById('heal-server-id').value;
    const commands = document.getElementById('heal-commands').value.trim();
    
    if (!serviceName || !serverId || !commands) {
        showNotification('Please fill required fields: Service Name, Server, Heal Commands', 'error');
        return;
    }
    
    const template = {
        service_name: serviceName,
        trigger_source: document.getElementById('heal-trigger-source').value,
        analytics_service: document.getElementById('heal-analytics-service').value || null,
        server_id: serverId,
        check_command: document.getElementById('heal-check-command').value.trim() || null,
        expected_output: document.getElementById('heal-expected-output').value.trim() || '',
        heal_commands: commands.split('\n').filter(c => c.trim()),
        verify_command: document.getElementById('heal-verify-command').value.trim() || null,
        retry_count: parseInt(document.getElementById('heal-retry-count').value) || 3,
        retry_delay: parseInt(document.getElementById('heal-retry-delay').value) || 10,
        enabled: document.getElementById('heal-enabled').checked
    };
    
    if (templateId) {
        template.id = templateId;
    }
    
    await saveHealTemplate(template);
}

async function editHealTemplate(templateId) {
    const templates = await loadHealTemplates();
    const template = templates.find(t => t.id === templateId);
    
    if (!template) {
        showNotification('Template not found', 'error');
        return;
    }
    
    const form = document.getElementById('heal-template-form');
    const title = document.getElementById('heal-form-title');
    
    if (form) {
        form.style.display = 'block';
        title.textContent = 'Edit Heal Template';
        form.dataset.templateId = templateId;
        
        document.getElementById('heal-service-name').value = template.service_name || '';
        document.getElementById('heal-trigger-source').value = template.trigger_source || 'analytics';
        document.getElementById('heal-analytics-service').value = template.analytics_service || '';
        document.getElementById('heal-server-id').value = template.server_id || '';
        document.getElementById('heal-check-command').value = template.check_command || '';
        document.getElementById('heal-expected-output').value = template.expected_output || '';
        document.getElementById('heal-commands').value = (template.heal_commands || []).join('\n');
        document.getElementById('heal-verify-command').value = template.verify_command || '';
        document.getElementById('heal-retry-count').value = template.retry_count || 3;
        document.getElementById('heal-retry-delay').value = template.retry_delay || 10;
        document.getElementById('heal-enabled').checked = template.enabled !== false;
        
        form.scrollIntoView({ behavior: 'smooth' });
    }
}

function applyCheckPreset() {
    const select = document.getElementById('heal-check-preset');
    const opt = select.selectedOptions[0];
    
    if (opt && opt.value) {
        document.getElementById('heal-check-command').value = opt.value;
        document.getElementById('heal-expected-output').value = opt.dataset.expected || '';
    }
}

function addHealCommandFromPreset() {
    const preset = document.getElementById('heal-command-preset').value;
    if (!preset) return;
    
    const textarea = document.getElementById('heal-commands');
    const current = textarea.value.trim();
    textarea.value = current ? `${current}\n${preset}` : preset;
}

// ============================================================================
// Settings Loader
// ============================================================================

async function loadSentinelSettings() {
    try {
        const response = await fetch('/api/sentinel/settings');
        const settings = await response.json();
        
        const modeSelect = document.getElementById('auto-heal-mode');
        if (modeSelect) {
            modeSelect.value = settings.auto_heal_mode || 'explicit';
        }
    } catch (error) {
        console.error('Failed to load Sentinel settings:', error);
    }
}

// ============================================================================
// Initialization
// ============================================================================

function initSentinelAutoHeal() {
    const container = document.getElementById('heal-template-container');
    if (container) {
        renderHealTemplateEditor(container);
    }
    
    loadSentinelSettings();
}

// Auto-initialize on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSentinelAutoHeal);
} else {
    initSentinelAutoHeal();
}

// Helper function for notifications (if not already defined)
function showNotification(message, type = 'info') {
    // Replace with your existing notification system
    console.log(`[${type.toUpperCase()}] ${message}`);
    alert(message);
}

