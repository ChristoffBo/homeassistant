/**
 * Jarvis Registry Hub - Frontend
 * Manages Docker registry cache, image pulling, updates, and settings
 */

// ============================================================================
// STATE MANAGEMENT
// ============================================================================

const RegistryState = {
    images: [],
    stats: null,
    settings: null,
    loading: false,
    settingsPanelOpen: false,
    pullModalOpen: false,
    selectedImage: null,
    storageTestInProgress: false,
    storageTestResult: null
};

// ============================================================================
// INITIALIZATION
// ============================================================================

function initRegistry() {
    console.log('[Registry] Initializing');
    
    // Load initial data
    loadRegistryImages();
    loadRegistryStats();
    loadRegistrySettings();
    
    // Setup event listeners
    setupRegistryEventListeners();
    
    // Auto-refresh every 30 seconds
    setInterval(() => {
        if (document.querySelector('#registry.active')) {
            loadRegistryImages();
            loadRegistryStats();
        }
    }, 30000);
    
    console.log('[Registry] Initialized');
}

// ============================================================================
// EVENT LISTENERS
// ============================================================================

function setupRegistryEventListeners() {
    // Pull button
    const pullBtn = document.getElementById('registry-pull-btn');
    if (pullBtn) {
        pullBtn.addEventListener('click', () => openPullModal());
    }
    
    // Settings button
    const settingsBtn = document.getElementById('registry-settings-btn');
    if (settingsBtn) {
        settingsBtn.addEventListener('click', () => toggleSettingsPanel());
    }
    
    // Refresh button
    const refreshBtn = document.getElementById('registry-refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            loadRegistryImages();
            loadRegistryStats();
            showToast('Refreshing registry data...', 'info');
        });
    }
    
    // Check updates button
    const checkUpdatesBtn = document.getElementById('registry-check-updates-btn');
    if (checkUpdatesBtn) {
        checkUpdatesBtn.addEventListener('click', () => checkForUpdates());
    }
    
    // Search input
    const searchInput = document.getElementById('registry-search');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => filterImages(e.target.value));
    }
    
    // Pull modal - close button
    const pullModalClose = document.getElementById('pull-modal-close');
    if (pullModalClose) {
        pullModalClose.addEventListener('click', () => closePullModal());
    }
    
    // Pull modal - pull button
    const pullModalBtn = document.getElementById('pull-modal-btn');
    if (pullModalBtn) {
        pullModalBtn.addEventListener('click', () => executePull());
    }
    
    // Pull modal - image input (Enter key)
    const pullImageInput = document.getElementById('pull-image-input');
    if (pullImageInput) {
        pullImageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                executePull();
            }
        });
    }
    
    // Settings panel - close button
    const settingsClose = document.getElementById('settings-panel-close');
    if (settingsClose) {
        settingsClose.addEventListener('click', () => closeSettingsPanel());
    }
    
    // Settings panel - save button
    const settingsSaveBtn = document.getElementById('settings-save-btn');
    if (settingsSaveBtn) {
        settingsSaveBtn.addEventListener('click', () => saveSettings());
    }
    
    // Storage type selector
    const storageTypeSelect = document.getElementById('storage-type');
    if (storageTypeSelect) {
        storageTypeSelect.addEventListener('change', (e) => updateStorageForm(e.target.value));
    }
    
    // Test storage button
    const testStorageBtn = document.getElementById('test-storage-btn');
    if (testStorageBtn) {
        testStorageBtn.addEventListener('click', () => testStorageConnection());
    }
    
    // Settings panel - purge buttons
    const purgeHistoryBtn = document.getElementById('purge-history-btn');
    if (purgeHistoryBtn) {
        purgeHistoryBtn.addEventListener('click', () => purgeHistory());
    }
    
    const cleanOrphanedBtn = document.getElementById('clean-orphaned-btn');
    if (cleanOrphanedBtn) {
        cleanOrphanedBtn.addEventListener('click', () => cleanOrphaned());
    }
    
    const resetDbBtn = document.getElementById('reset-db-btn');
    if (resetDbBtn) {
        resetDbBtn.addEventListener('click', () => resetDatabase());
    }
    
    const cleanupStorageBtn = document.getElementById('cleanup-storage-btn');
    if (cleanupStorageBtn) {
        cleanupStorageBtn.addEventListener('click', () => cleanupStorage());
    }
    
    // Common images shortcuts
    document.querySelectorAll('.common-image-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const imageName = e.target.dataset.image;
            document.getElementById('pull-image-input').value = imageName;
        });
    });
}

// ============================================================================
// API CALLS
// ============================================================================

async function loadRegistryImages() {
    try {
        const response = await fetch('/api/registry/images');
        const data = await response.json();
        
        if (data.images) {
            RegistryState.images = data.images;
            renderImageList();
        }
    } catch (error) {
        console.error('[Registry] Error loading images:', error);
        showToast('Failed to load images', 'error');
    }
}

async function loadRegistryStats() {
    try {
        const response = await fetch('/api/registry/stats');
        const data = await response.json();
        
        if (data) {
            RegistryState.stats = data;
            renderStats();
        }
    } catch (error) {
        console.error('[Registry] Error loading stats:', error);
    }
}

async function loadRegistrySettings() {
    try {
        const response = await fetch('/api/registry/settings');
        const data = await response.json();
        
        if (data) {
            RegistryState.settings = data;
            renderSettings();
        }
    } catch (error) {
        console.error('[Registry] Error loading settings:', error);
    }
}

async function pullImage(imageName) {
    try {
        showToast(`Pulling ${imageName}...`, 'info');
        
        const response = await fetch('/api/registry/images/pull', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: imageName })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(`Successfully pulled ${imageName}`, 'success');
            closePullModal();
            loadRegistryImages();
            loadRegistryStats();
        } else {
            showToast(data.error || 'Pull failed', 'error');
        }
    } catch (error) {
        console.error('[Registry] Error pulling image:', error);
        showToast('Failed to pull image', 'error');
    }
}

async function deleteImage(imageId, imageName) {
    if (!confirm(`Delete ${imageName}?\n\nThis will remove the cached image from the registry.`)) {
        return;
    }
    
    try {
        showToast(`Deleting ${imageName}...`, 'info');
        
        const response = await fetch(`/api/registry/images/${imageId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(`Deleted ${imageName}`, 'success');
            loadRegistryImages();
            loadRegistryStats();
        } else {
            showToast(data.error || 'Delete failed', 'error');
        }
    } catch (error) {
        console.error('[Registry] Error deleting image:', error);
        showToast('Failed to delete image', 'error');
    }
}

async function saveSettings() {
    try {
        const settings = {
            auto_pull: document.getElementById('setting-auto-pull').checked,
            check_interval_hours: parseInt(document.getElementById('setting-check-interval').value),
            keep_versions: parseInt(document.getElementById('setting-keep-versions').value),
            max_storage_gb: parseInt(document.getElementById('setting-max-storage').value),
            purge_history_days: parseInt(document.getElementById('setting-purge-days').value),
            notifications_enabled: document.getElementById('setting-notifications').checked,
            storage_backend: collectStorageBackendSettings()
        };
        
        const response = await fetch('/api/registry/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Settings saved', 'success');
            RegistryState.settings = settings;
            closeSettingsPanel();
        } else {
            showToast('Failed to save settings', 'error');
        }
    } catch (error) {
        console.error('[Registry] Error saving settings:', error);
        showToast('Failed to save settings', 'error');
    }
}

async function checkForUpdates() {
    try {
        showToast('Checking for updates...', 'info');
        
        const response = await fetch('/api/registry/check-updates', {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (data.success) {
            const count = data.updates_found;
            if (count > 0) {
                showToast(`Found ${count} update${count > 1 ? 's' : ''}`, 'success');
            } else {
                showToast('All images are up to date', 'success');
            }
            loadRegistryImages();
            loadRegistryStats();
        } else {
            showToast('Update check failed', 'error');
        }
    } catch (error) {
        console.error('[Registry] Error checking updates:', error);
        showToast('Failed to check updates', 'error');
    }
}

async function purgeHistory() {
    const days = RegistryState.settings?.purge_history_days || 30;
    
    if (!confirm(`Purge history older than ${days} days?`)) {
        return;
    }
    
    try {
        const response = await fetch('/api/registry/db/purge-history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ days })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(`Purged ${data.deleted} old records`, 'success');
            loadRegistryStats();
        } else {
            showToast('Purge failed', 'error');
        }
    } catch (error) {
        console.error('[Registry] Error purging history:', error);
        showToast('Failed to purge history', 'error');
    }
}

async function cleanOrphaned() {
    if (!confirm('Clean orphaned database records?\n\nThis will remove metadata for images no longer in cache.')) {
        return;
    }
    
    try {
        const response = await fetch('/api/registry/db/clean-orphaned', {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(`Cleaned ${data.deleted} orphaned records`, 'success');
            loadRegistryImages();
            loadRegistryStats();
        } else {
            showToast('Cleanup failed', 'error');
        }
    } catch (error) {
        console.error('[Registry] Error cleaning orphaned:', error);
        showToast('Failed to clean orphaned records', 'error');
    }
}

async function resetDatabase() {
    const confirmation = prompt('⚠️ DANGER: Reset Registry Database?\n\nThis will delete ALL registry data from the database.\nCached images will remain on disk.\n\nType "RESET" to confirm:');
    
    if (confirmation !== 'RESET') {
        return;
    }
    
    try {
        const response = await fetch('/api/registry/db/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirmation: 'RESET' })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Database reset complete', 'success');
            loadRegistryImages();
            loadRegistryStats();
            loadRegistrySettings();
        } else {
            showToast('Reset failed', 'error');
        }
    } catch (error) {
        console.error('[Registry] Error resetting database:', error);
        showToast('Failed to reset database', 'error');
    }
}

async function cleanupStorage() {
    if (!confirm('Run storage garbage collection?\n\nThis will remove unused image layers to free space.')) {
        return;
    }
    
    try {
        showToast('Running garbage collection...', 'info');
        
        const response = await fetch('/api/registry/storage/cleanup', {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Storage cleanup complete', 'success');
            loadRegistryStats();
        } else {
            showToast('Cleanup failed', 'error');
        }
    } catch (error) {
        console.error('[Registry] Error cleaning storage:', error);
        showToast('Failed to cleanup storage', 'error');
    }
}

// ============================================================================
// RENDERING
// ============================================================================

function renderImageList() {
    const container = document.getElementById('registry-images-list');
    if (!container) return;
    
    if (RegistryState.images.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📦</div>
                <div class="empty-title">No cached images</div>
                <div class="empty-text">Pull an image to get started</div>
                <button class="btn btn-primary" onclick="openPullModal()">Pull Image</button>
            </div>
        `;
        return;
    }
    
    let html = '';
    
    RegistryState.images.forEach(image => {
        const updateBadge = image.update_available ? 
            '<span class="badge badge-warning">🔄 Update Available</span>' : 
            '<span class="badge badge-success">✅ Up to date</span>';
        
        const size = formatBytes(image.size);
        const pulledAt = formatTimeAgo(image.pulled_at);
        
        html += `
            <div class="registry-image-card" data-image-id="${image.id}">
                <div class="image-card-header">
                    <div class="image-info">
                        <div class="image-name">${escapeHtml(image.name)}:${escapeHtml(image.tag)}</div>
                        <div class="image-meta">
                            ${size} • ${pulledAt}
                        </div>
                    </div>
                    <div class="image-status">
                        ${updateBadge}
                    </div>
                </div>
                <div class="image-card-actions">
                    ${image.update_available ? 
                        `<button class="btn btn-sm btn-primary" onclick="pullImage('${escapeHtml(image.name)}:${escapeHtml(image.tag)}')">
                            Update Now
                        </button>` : 
                        ''
                    }
                    <button class="btn btn-sm btn-secondary" onclick="viewImageDetails('${escapeHtml(image.id)}')">
                        View
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="deleteImage('${escapeHtml(image.id)}', '${escapeHtml(image.name)}:${escapeHtml(image.tag)}')">
                        Delete
                    </button>
                </div>
            </div>
        `;
    });
    
    container.innerHTML = html;
}

function renderStats() {
    if (!RegistryState.stats) return;
    
    // Image count
    const imageCountEl = document.getElementById('stat-image-count');
    if (imageCountEl) {
        imageCountEl.textContent = RegistryState.stats.database.image_count || 0;
    }
    
    // Storage used
    const storageUsedEl = document.getElementById('stat-storage-used');
    if (storageUsedEl) {
        const used = formatBytes(RegistryState.stats.storage.used || 0);
        const total = formatBytes(RegistryState.stats.storage.total || 0);
        const percent = RegistryState.stats.storage.percent || 0;
        storageUsedEl.textContent = `${used} / ${total} (${percent.toFixed(1)}%)`;
    }
    
    // Updates available
    const updatesEl = document.getElementById('stat-updates-available');
    if (updatesEl) {
        const count = RegistryState.stats.updates_available || 0;
        updatesEl.textContent = count;
        
        // Add warning class if updates available
        if (count > 0) {
            updatesEl.classList.add('text-warning');
        } else {
            updatesEl.classList.remove('text-warning');
        }
    }
    
    // Storage progress bar
    const storageBarEl = document.getElementById('storage-progress-bar');
    if (storageBarEl) {
        const percent = RegistryState.stats.storage.percent || 0;
        storageBarEl.style.width = `${percent}%`;
        
        // Color based on usage
        storageBarEl.className = 'progress-bar';
        if (percent > 90) {
            storageBarEl.classList.add('bg-danger');
        } else if (percent > 75) {
            storageBarEl.classList.add('bg-warning');
        } else {
            storageBarEl.classList.add('bg-success');
        }
    }
}

function renderSettings() {
    if (!RegistryState.settings) return;
    
    // Auto-pull
    const autoPullEl = document.getElementById('setting-auto-pull');
    if (autoPullEl) {
        autoPullEl.checked = RegistryState.settings.auto_pull;
    }
    
    // Check interval
    const checkIntervalEl = document.getElementById('setting-check-interval');
    if (checkIntervalEl) {
        checkIntervalEl.value = RegistryState.settings.check_interval_hours;
    }
    
    // Keep versions
    const keepVersionsEl = document.getElementById('setting-keep-versions');
    if (keepVersionsEl) {
        keepVersionsEl.value = RegistryState.settings.keep_versions;
    }
    
    // Max storage
    const maxStorageEl = document.getElementById('setting-max-storage');
    if (maxStorageEl) {
        maxStorageEl.value = RegistryState.settings.max_storage_gb;
    }
    
    // Purge days
    const purgeDaysEl = document.getElementById('setting-purge-days');
    if (purgeDaysEl) {
        purgeDaysEl.value = RegistryState.settings.purge_history_days;
    }
    
    // Notifications
    const notificationsEl = document.getElementById('setting-notifications');
    if (notificationsEl) {
        notificationsEl.checked = RegistryState.settings.notifications_enabled;
    }
    
    // Storage backend
    if (RegistryState.settings.storage_backend) {
        renderStorageBackendSettings(RegistryState.settings.storage_backend);
    }
}

function viewImageDetails(imageId) {
    const image = RegistryState.images.find(img => img.id === imageId);
    if (!image) return;
    
    const details = `
Image: ${image.name}:${image.tag}
Digest: ${image.digest}
Size: ${formatBytes(image.size)}
Pulled: ${new Date(image.pulled_at).toLocaleString()}
Last Checked: ${image.last_checked ? new Date(image.last_checked).toLocaleString() : 'Never'}
Update Available: ${image.update_available ? 'Yes' : 'No'}
    `.trim();
    
    alert(details);
}

// ============================================================================
// MODALS & PANELS
// ============================================================================

function openPullModal() {
    const modal = document.getElementById('pull-modal');
    if (modal) {
        modal.classList.add('active');
        RegistryState.pullModalOpen = true;
        
        // Focus input
        setTimeout(() => {
            document.getElementById('pull-image-input')?.focus();
        }, 100);
    }
}

function closePullModal() {
    const modal = document.getElementById('pull-modal');
    if (modal) {
        modal.classList.remove('active');
        RegistryState.pullModalOpen = false;
        
        // Clear input
        const input = document.getElementById('pull-image-input');
        if (input) input.value = '';
    }
}

function executePull() {
    const input = document.getElementById('pull-image-input');
    if (!input) return;
    
    const imageName = input.value.trim();
    
    if (!imageName) {
        showToast('Please enter an image name', 'warning');
        return;
    }
    
    // Add :latest if no tag specified
    const fullImageName = imageName.includes(':') ? imageName : `${imageName}:latest`;
    
    pullImage(fullImageName);
}

function toggleSettingsPanel() {
    if (RegistryState.settingsPanelOpen) {
        closeSettingsPanel();
    } else {
        openSettingsPanel();
    }
}

function openSettingsPanel() {
    const panel = document.getElementById('settings-panel');
    if (panel) {
        panel.classList.add('active');
        RegistryState.settingsPanelOpen = true;
    }
}

function closeSettingsPanel() {
    const panel = document.getElementById('settings-panel');
    if (panel) {
        panel.classList.remove('active');
        RegistryState.settingsPanelOpen = false;
    }
}

// ============================================================================
// SEARCH & FILTER
// ============================================================================

function filterImages(searchTerm) {
    const term = searchTerm.toLowerCase();
    
    document.querySelectorAll('.registry-image-card').forEach(card => {
        const imageId = card.dataset.imageId;
        const image = RegistryState.images.find(img => img.id === imageId);
        
        if (!image) {
            card.style.display = 'none';
            return;
        }
        
        const searchableText = `${image.name} ${image.tag}`.toLowerCase();
        
        if (searchableText.includes(term)) {
            card.style.display = 'block';
        } else {
            card.style.display = 'none';
        }
    });
}

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function formatTimeAgo(timestamp) {
    if (!timestamp) return 'Unknown';
    
    const now = new Date();
    const then = new Date(timestamp);
    const seconds = Math.floor((now - then) / 1000);
    
    if (seconds < 60) return 'Just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
    if (seconds < 2592000) return `${Math.floor(seconds / 604800)}w ago`;
    
    return then.toLocaleDateString();
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

function showToast(message, type = 'info') {
    // Use existing Jarvis toast system if available
    if (typeof showNotification === 'function') {
        showNotification(message, type);
        return;
    }
    
    // Fallback to console
    console.log(`[Registry] ${type.toUpperCase()}: ${message}`);
}

// ============================================================================
// STORAGE BACKEND MANAGEMENT
// ============================================================================

function renderStorageBackendSettings(storageBackend) {
    const storageTypeEl = document.getElementById('storage-type');
    if (storageTypeEl) {
        storageTypeEl.value = storageBackend.type || 'local';
    }
    
    // Show appropriate form based on type
    updateStorageForm(storageBackend.type || 'local');
    
    // Populate local settings
    const localPathEl = document.getElementById('storage-local-path');
    if (localPathEl && storageBackend.local) {
        localPathEl.value = storageBackend.local.path || '';
    }
    
    // Populate NFS settings
    if (storageBackend.nfs) {
        const nfsServerEl = document.getElementById('storage-nfs-server');
        const nfsExportEl = document.getElementById('storage-nfs-export');
        const nfsMountEl = document.getElementById('storage-nfs-mount');
        const nfsOptionsEl = document.getElementById('storage-nfs-options');
        
        if (nfsServerEl) nfsServerEl.value = storageBackend.nfs.server || '';
        if (nfsExportEl) nfsExportEl.value = storageBackend.nfs.export || '';
        if (nfsMountEl) nfsMountEl.value = storageBackend.nfs.mount_point || '';
        if (nfsOptionsEl) nfsOptionsEl.value = storageBackend.nfs.options || '';
    }
    
    // Populate SMB settings
    if (storageBackend.smb) {
        const smbServerEl = document.getElementById('storage-smb-server');
        const smbShareEl = document.getElementById('storage-smb-share');
        const smbUserEl = document.getElementById('storage-smb-username');
        const smbPassEl = document.getElementById('storage-smb-password');
        const smbMountEl = document.getElementById('storage-smb-mount');
        const smbOptionsEl = document.getElementById('storage-smb-options');
        
        if (smbServerEl) smbServerEl.value = storageBackend.smb.server || '';
        if (smbShareEl) smbShareEl.value = storageBackend.smb.share || '';
        if (smbUserEl) smbUserEl.value = storageBackend.smb.username || '';
        if (smbPassEl) smbPassEl.value = storageBackend.smb.password || '';
        if (smbMountEl) smbMountEl.value = storageBackend.smb.mount_point || '';
        if (smbOptionsEl) smbOptionsEl.value = storageBackend.smb.options || '';
    }
}

function updateStorageForm(storageType) {
    // Hide all storage forms
    const localForm = document.getElementById('storage-local-form');
    const nfsForm = document.getElementById('storage-nfs-form');
    const smbForm = document.getElementById('storage-smb-form');
    
    if (localForm) localForm.style.display = 'none';
    if (nfsForm) nfsForm.style.display = 'none';
    if (smbForm) smbForm.style.display = 'none';
    
    // Show selected form
    if (storageType === 'local' && localForm) {
        localForm.style.display = 'block';
    } else if (storageType === 'nfs' && nfsForm) {
        nfsForm.style.display = 'block';
    } else if (storageType === 'smb' && smbForm) {
        smbForm.style.display = 'block';
    }
    
    // Clear test result
    clearStorageTestResult();
}

function collectStorageBackendSettings() {
    const storageType = document.getElementById('storage-type')?.value || 'local';
    
    const config = {
        type: storageType,
        local: {
            path: document.getElementById('storage-local-path')?.value || '/share/jarvis_prime/registry'
        },
        nfs: {
            server: document.getElementById('storage-nfs-server')?.value || '',
            export: document.getElementById('storage-nfs-export')?.value || '',
            mount_point: document.getElementById('storage-nfs-mount')?.value || '/mnt/registry-nfs',
            options: document.getElementById('storage-nfs-options')?.value || 'rw,sync,hard,intr'
        },
        smb: {
            server: document.getElementById('storage-smb-server')?.value || '',
            share: document.getElementById('storage-smb-share')?.value || '',
            username: document.getElementById('storage-smb-username')?.value || '',
            password: document.getElementById('storage-smb-password')?.value || '',
            mount_point: document.getElementById('storage-smb-mount')?.value || '/mnt/registry-smb',
            options: document.getElementById('storage-smb-options')?.value || 'vers=3.0,dir_mode=0777,file_mode=0666'
        }
    };
    
    return config;
}

async function testStorageConnection() {
    if (RegistryState.storageTestInProgress) {
        return;
    }
    
    try {
        RegistryState.storageTestInProgress = true;
        updateStorageTestUI('testing');
        
        const storageBackend = collectStorageBackendSettings();
        
        const response = await fetch('/api/registry/storage/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ storage_backend: storageBackend })
        });
        
        const data = await response.json();
        
        RegistryState.storageTestResult = data;
        
        if (data.success) {
            updateStorageTestUI('success', data);
            showToast('Storage connection successful', 'success');
        } else {
            updateStorageTestUI('error', data);
            showToast(data.error || 'Storage connection failed', 'error');
        }
    } catch (error) {
        console.error('[Registry] Error testing storage:', error);
        RegistryState.storageTestResult = { success: false, error: error.message };
        updateStorageTestUI('error', { error: error.message });
        showToast('Storage connection test failed', 'error');
    } finally {
        RegistryState.storageTestInProgress = false;
    }
}

function updateStorageTestUI(status, data = null) {
    const testBtn = document.getElementById('test-storage-btn');
    const resultEl = document.getElementById('storage-test-result');
    
    if (!testBtn || !resultEl) return;
    
    if (status === 'testing') {
        testBtn.disabled = true;
        testBtn.textContent = 'Testing...';
        resultEl.className = 'storage-test-result testing';
        resultEl.textContent = 'Testing connection...';
        resultEl.style.display = 'block';
    } else if (status === 'success' && data) {
        testBtn.disabled = false;
        testBtn.textContent = 'Test Connection';
        resultEl.className = 'storage-test-result success';
        
        let message = '✓ Connection successful';
        if (data.total_gb && data.free_gb) {
            message += ` - ${data.free_gb.toFixed(1)}GB free of ${data.total_gb.toFixed(1)}GB`;
        }
        if (data.type === 'nfs') {
            message += ` (NFS: ${data.server}:${data.export})`;
        } else if (data.type === 'smb') {
            message += ` (SMB: //${data.server}/${data.share})`;
        }
        
        resultEl.textContent = message;
        resultEl.style.display = 'block';
    } else if (status === 'error' && data) {
        testBtn.disabled = false;
        testBtn.textContent = 'Test Connection';
        resultEl.className = 'storage-test-result error';
        resultEl.textContent = `✗ ${data.error || 'Connection failed'}`;
        resultEl.style.display = 'block';
    }
}

function clearStorageTestResult() {
    const resultEl = document.getElementById('storage-test-result');
    if (resultEl) {
        resultEl.style.display = 'none';
        resultEl.textContent = '';
    }
    RegistryState.storageTestResult = null;
}

// ============================================================================
// EXPORT FOR GLOBAL ACCESS
// ============================================================================

// Make functions globally available
window.RegistryHub = {
    init: initRegistry,
    pullImage: pullImage,
    deleteImage: deleteImage,
    viewImageDetails: viewImageDetails,
    openPullModal: openPullModal,
    closePullModal: closePullModal,
    openSettingsPanel: openSettingsPanel,
    closeSettingsPanel: closeSettingsPanel,
    checkForUpdates: checkForUpdates,
    refresh: () => {
        loadRegistryImages();
        loadRegistryStats();
    }
};

// Auto-initialize when tab becomes active
document.addEventListener('DOMContentLoaded', () => {
    const registryTab = document.querySelector('[data-tab="registry"]');
    if (registryTab) {
        registryTab.addEventListener('click', () => {
            setTimeout(initRegistry, 100);
        });
    }
});

console.log('[Registry] Module loaded');
