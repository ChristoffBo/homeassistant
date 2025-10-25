/**
 * Jarvis Prime - Backup Module Frontend
 * File explorer UI with SSH/SMB/NFS support
 */

class BackupModule {
    constructor() {
        this.sourceConnection = null;
        this.destConnection = null;
        this.currentSourcePath = '/';
        this.currentDestPath = '/';
        this.selectedSourcePaths = [];
        this.jobs = {};
        this.statusPollInterval = null;
    }

    async init() {
        this.bindEvents();
        await this.loadJobs();
        this.startStatusPolling();
    }

    bindEvents() {
        // Source connection
        document.getElementById('btn-source-connect').addEventListener('click', () => this.connectSource());
        document.getElementById('source-type').addEventListener('change', () => this.updateSourceForm());
        
        // Destination connection
        document.getElementById('btn-dest-connect').addEventListener('click', () => this.connectDestination());
        document.getElementById('dest-type').addEventListener('change', () => this.updateDestForm());
        
        // Backup actions
        document.getElementById('btn-create-backup').addEventListener('click', () => this.createBackupJob());
        document.getElementById('btn-run-backup').addEventListener('click', () => this.runSelectedJob());
        document.getElementById('btn-delete-backup').addEventListener('click', () => this.deleteSelectedJob());
        
        // Update forms on load
        this.updateSourceForm();
        this.updateDestForm();
    }

    updateSourceForm() {
        const type = document.getElementById('source-type').value;
        const sshFields = document.getElementById('source-ssh-fields');
        const smbFields = document.getElementById('source-smb-fields');
        const nfsFields = document.getElementById('source-nfs-fields');
        
        sshFields.style.display = type === 'ssh' ? 'block' : 'none';
        smbFields.style.display = type === 'smb' ? 'block' : 'none';
        nfsFields.style.display = type === 'nfs' ? 'block' : 'none';
    }

    updateDestForm() {
        const type = document.getElementById('dest-type').value;
        const sshFields = document.getElementById('dest-ssh-fields');
        const smbFields = document.getElementById('dest-smb-fields');
        const nfsFields = document.getElementById('dest-nfs-fields');
        
        sshFields.style.display = type === 'ssh' ? 'block' : 'none';
        smbFields.style.display = type === 'smb' ? 'block' : 'none';
        nfsFields.style.display = type === 'nfs' ? 'block' : 'none';
    }

    getSourceConnectionConfig() {
        const type = document.getElementById('source-type').value;
        const config = { type };
        
        if (type === 'ssh') {
            config.host = document.getElementById('source-host').value;
            config.port = parseInt(document.getElementById('source-port').value) || 22;
            config.username = document.getElementById('source-username').value;
            config.password = document.getElementById('source-password').value;
        } else if (type === 'smb') {
            config.host = document.getElementById('source-smb-host').value;
            config.share = document.getElementById('source-smb-share').value;
            config.username = document.getElementById('source-smb-username').value;
            config.password = document.getElementById('source-smb-password').value;
        } else if (type === 'nfs') {
            config.host = document.getElementById('source-nfs-host').value;
            config.export_path = document.getElementById('source-nfs-export').value;
        }
        
        return config;
    }

    getDestConnectionConfig() {
        const type = document.getElementById('dest-type').value;
        const config = { type };
        
        if (type === 'ssh') {
            config.host = document.getElementById('dest-host').value;
            config.port = parseInt(document.getElementById('dest-port').value) || 22;
            config.username = document.getElementById('dest-username').value;
            config.password = document.getElementById('dest-password').value;
        } else if (type === 'smb') {
            config.host = document.getElementById('dest-smb-host').value;
            config.share = document.getElementById('dest-smb-share').value;
            config.username = document.getElementById('dest-smb-username').value;
            config.password = document.getElementById('dest-smb-password').value;
        } else if (type === 'nfs') {
            config.host = document.getElementById('dest-nfs-host').value;
            config.export_path = document.getElementById('dest-nfs-export').value;
        }
        
        return config;
    }

    async connectSource() {
        const config = this.getSourceConnectionConfig();
        
        try {
            const response = await fetch('/api/backup/test-connection', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.sourceConnection = config;
                this.currentSourcePath = '/';
                await this.browseSource('/');
                this.showNotification('Source connected successfully', 'success');
            } else {
                this.showNotification('Source connection failed: ' + data.message, 'error');
            }
        } catch (error) {
            this.showNotification('Connection error: ' + error.message, 'error');
        }
    }

    async connectDestination() {
        const config = this.getDestConnectionConfig();
        
        try {
            const response = await fetch('/api/backup/test-connection', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.destConnection = config;
                this.currentDestPath = '/';
                await this.browseDest('/');
                this.showNotification('Destination connected successfully', 'success');
            } else {
                this.showNotification('Destination connection failed: ' + data.message, 'error');
            }
        } catch (error) {
            this.showNotification('Connection error: ' + error.message, 'error');
        }
    }

    async browseSource(path) {
        if (!this.sourceConnection) {
            this.showNotification('Not connected to source', 'error');
            return;
        }
        
        try {
            const response = await fetch('/api/backup/browse', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    connection: this.sourceConnection,
                    path: path
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.currentSourcePath = path;
                this.renderSourceExplorer(data.items);
            } else {
                this.showNotification('Browse failed: ' + data.message, 'error');
            }
        } catch (error) {
            this.showNotification('Browse error: ' + error.message, 'error');
        }
    }

    async browseDest(path) {
        if (!this.destConnection) {
            this.showNotification('Not connected to destination', 'error');
            return;
        }
        
        try {
            const response = await fetch('/api/backup/browse', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    connection: this.destConnection,
                    path: path
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.currentDestPath = path;
                this.renderDestExplorer(data.items);
            } else {
                this.showNotification('Browse failed: ' + data.message, 'error');
            }
        } catch (error) {
            this.showNotification('Browse error: ' + error.message, 'error');
        }
    }

    renderSourceExplorer(items) {
        const container = document.getElementById('source-explorer');
        const pathDisplay = document.getElementById('source-path');
        pathDisplay.textContent = this.currentSourcePath;
        
        let html = '';
        
        // Parent directory link
        if (this.currentSourcePath !== '/') {
            const parentPath = this.currentSourcePath.split('/').slice(0, -1).join('/') || '/';
            html += `
                <div class="file-item" onclick="backupModule.browseSource('${parentPath}')">
                    <span class="file-icon">📁</span>
                    <span class="file-name">..</span>
                </div>
            `;
        }
        
        // Files and folders
        items.forEach(item => {
            const icon = item.is_dir ? '📁' : '📄';
            const size = item.is_dir ? '' : this.formatBytes(item.size);
            const checkbox = `<input type="checkbox" class="source-checkbox" data-path="${item.path}" 
                ${this.selectedSourcePaths.includes(item.path) ? 'checked' : ''}>`;
            
            if (item.is_dir) {
                html += `
                    <div class="file-item">
                        ${checkbox}
                        <span class="file-icon" onclick="backupModule.browseSource('${item.path}')">${icon}</span>
                        <span class="file-name" onclick="backupModule.browseSource('${item.path}')">${item.name}</span>
                        <span class="file-size">${size}</span>
                    </div>
                `;
            } else {
                html += `
                    <div class="file-item">
                        ${checkbox}
                        <span class="file-icon">${icon}</span>
                        <span class="file-name">${item.name}</span>
                        <span class="file-size">${size}</span>
                    </div>
                `;
            }
        });
        
        container.innerHTML = html;
        
        // Bind checkbox events
        document.querySelectorAll('.source-checkbox').forEach(cb => {
            cb.addEventListener('change', (e) => {
                const path = e.target.dataset.path;
                if (e.target.checked) {
                    if (!this.selectedSourcePaths.includes(path)) {
                        this.selectedSourcePaths.push(path);
                    }
                } else {
                    this.selectedSourcePaths = this.selectedSourcePaths.filter(p => p !== path);
                }
                this.updateSelectedCount();
            });
        });
    }

    renderDestExplorer(items) {
        const container = document.getElementById('dest-explorer');
        const pathDisplay = document.getElementById('dest-path');
        pathDisplay.textContent = this.currentDestPath;
        
        let html = '';
        
        // Parent directory link
        if (this.currentDestPath !== '/') {
            const parentPath = this.currentDestPath.split('/').slice(0, -1).join('/') || '/';
            html += `
                <div class="file-item" onclick="backupModule.browseDest('${parentPath}')">
                    <span class="file-icon">📁</span>
                    <span class="file-name">..</span>
                </div>
            `;
        }
        
        // Files and folders
        items.forEach(item => {
            const icon = item.is_dir ? '📁' : '📄';
            const size = item.is_dir ? '' : this.formatBytes(item.size);
            
            if (item.is_dir) {
                html += `
                    <div class="file-item" onclick="backupModule.browseDest('${item.path}')">
                        <span class="file-icon">${icon}</span>
                        <span class="file-name">${item.name}</span>
                        <span class="file-size">${size}</span>
                    </div>
                `;
            } else {
                html += `
                    <div class="file-item">
                        <span class="file-icon">${icon}</span>
                        <span class="file-name">${item.name}</span>
                        <span class="file-size">${size}</span>
                    </div>
                `;
            }
        });
        
        container.innerHTML = html;
    }

    updateSelectedCount() {
        const count = this.selectedSourcePaths.length;
        document.getElementById('selected-count').textContent = `${count} item(s) selected`;
    }

    async createBackupJob() {
        if (!this.sourceConnection || !this.destConnection) {
            this.showNotification('Please connect both source and destination', 'error');
            return;
        }
        
        if (this.selectedSourcePaths.length === 0) {
            this.showNotification('Please select files/folders to backup', 'error');
            return;
        }
        
        const jobConfig = {
            name: document.getElementById('job-name').value || 'Unnamed Backup',
            source: this.sourceConnection,
            destination: this.destConnection,
            source_paths: this.selectedSourcePaths,
            destination_path: this.currentDestPath,
            backup_type: document.getElementById('backup-type').value,
            compress: document.getElementById('backup-compress').checked,
            stop_containers: document.getElementById('backup-stop-containers').checked,
            containers: document.getElementById('backup-containers').value.split(',').map(c => c.trim()).filter(c => c),
            schedule: document.getElementById('backup-schedule').value
        };
        
        try {
            const response = await fetch('/api/backup/jobs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(jobConfig)
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.showNotification('Backup job created successfully', 'success');
                await this.loadJobs();
                // Reset form
                this.selectedSourcePaths = [];
                this.updateSelectedCount();
            } else {
                this.showNotification('Failed to create job: ' + data.message, 'error');
            }
        } catch (error) {
            this.showNotification('Error creating job: ' + error.message, 'error');
        }
    }

    async loadJobs() {
        try {
            const response = await fetch('/api/backup/jobs');
            const data = await response.json();
            
            if (data.success) {
                this.jobs = data.jobs;
                this.renderJobsList(data.jobs, data.statuses);
            }
        } catch (error) {
            console.error('Failed to load jobs:', error);
        }
    }

    renderJobsList(jobs, statuses) {
        const container = document.getElementById('jobs-list');
        
        let html = '';
        
        for (const [jobId, job] of Object.entries(jobs)) {
            const status = statuses[jobId] || {};
            const statusClass = status.status || 'pending';
            const progress = status.progress || 0;
            
            html += `
                <div class="job-item" data-job-id="${jobId}">
                    <div class="job-header">
                        <input type="radio" name="selected-job" value="${jobId}">
                        <strong>${job.name}</strong>
                        <span class="job-status status-${statusClass}">${statusClass}</span>
                    </div>
                    <div class="job-details">
                        <div>Type: ${job.backup_type} | Compress: ${job.compress ? 'Yes' : 'No'}</div>
                        <div>Source: ${job.source.host} → Dest: ${job.destination.host}</div>
                        <div>Paths: ${job.source_paths.length} item(s)</div>
                        ${status.status === 'running' ? `
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${progress}%"></div>
                            </div>
                            <div class="progress-text">${status.message}</div>
                        ` : ''}
                    </div>
                </div>
            `;
        }
        
        container.innerHTML = html || '<div class="no-jobs">No backup jobs configured</div>';
    }

    getSelectedJobId() {
        const selected = document.querySelector('input[name="selected-job"]:checked');
        return selected ? selected.value : null;
    }

    async runSelectedJob() {
        const jobId = this.getSelectedJobId();
        if (!jobId) {
            this.showNotification('Please select a job to run', 'error');
            return;
        }
        
        try {
            const response = await fetch(`/api/backup/jobs/${jobId}/run`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.showNotification('Backup job started', 'success');
            } else {
                this.showNotification('Failed to start job: ' + data.message, 'error');
            }
        } catch (error) {
            this.showNotification('Error starting job: ' + error.message, 'error');
        }
    }

    async deleteSelectedJob() {
        const jobId = this.getSelectedJobId();
        if (!jobId) {
            this.showNotification('Please select a job to delete', 'error');
            return;
        }
        
        if (!confirm('Are you sure you want to delete this backup job?')) {
            return;
        }
        
        try {
            const response = await fetch(`/api/backup/jobs/${jobId}`, {
                method: 'DELETE'
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.showNotification('Backup job deleted', 'success');
                await this.loadJobs();
            } else {
                this.showNotification('Failed to delete job: ' + data.message, 'error');
            }
        } catch (error) {
            this.showNotification('Error deleting job: ' + error.message, 'error');
        }
    }

    startStatusPolling() {
        // Poll for job status updates every 2 seconds
        this.statusPollInterval = setInterval(async () => {
            await this.loadJobs();
        }, 2000);
    }

    formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
    }

    showNotification(message, type) {
        // Use Jarvis notification system if available
        if (window.jarvis && window.jarvis.showNotification) {
            window.jarvis.showNotification(message, type);
        } else {
            alert(message);
        }
    }
}

// Initialize when DOM is ready
let backupModule;
document.addEventListener('DOMContentLoaded', () => {
    backupModule = new BackupModule();
    backupModule.init();
});
