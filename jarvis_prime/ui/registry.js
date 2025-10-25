/**
 * Jarvis Registry Hub - Frontend
 * Manages Docker registry cache with sub-tab navigation
 */

// ============================================================================
// STATE MANAGEMENT
// ============================================================================

const RegistryState = {
    images: [],
    stats: null,
    settings: null,
    loading: false,
    currentView: 'images', // images, settings, stats
    pullModalOpen: false,
    selectedImage: null
};

// ============================================================================
// INITIALIZATION
// ============================================================================

function initRegistry() {
    console.log('[Registry] Initializing');
    
    // Setup sub-tab navigation
    setupRegistrySubnav();
    
    // Setup event listeners
    setupRegistryEventListeners();
    
    // Load initial data
    loadRegistryImages();
    loadRegistryStats();
    loadRegistrySettings();
    
    // Auto-refresh every 30 seconds
    setInterval(() => {
        if (document.querySelector('#registry.active')) {
            if (RegistryState.currentView === 'images') {
                loadRegistryImages();
            }
            loadRegistryStats(); // Always refresh stats for cards
        }
    }, 30000);
    
    console.log('[Registry] Initialized');
}

// ============================================================================
// SUB-TAB NAVIGATION (matching Sentinel/Orchestrator pattern)
// ============================================================================

function setupRegistrySubnav() {
    const subnavButtons = document.querySelectorAll('.registry-subnav-btn');
    
    subnavButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;
            switchRegistryView(view);
        });
    });
    
    // Default to images view
    switchRegistryView('images');
}

function switchRegistryView(view) {
    RegistryState.currentView = view;
    
    // Update active button
    document.querySelectorAll('.registry-subnav-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    const activeBtn = document.querySelector(`.registry-subnav-btn[data-view="${view}"]`);
    if (activeBtn) {
        activeBtn.classList.add('active');
    }
    
    // Hide all views
    document.querySelectorAll('.registry-view').forEach(v => {
        v.style.display = 'none';
    });
    
    // Show selected view
    const selectedView = document.getElementById(`registry-${view}-view`);
    if (selectedView) {
        selectedView.style.display = 'block';
    }
    
    // Load data for view if needed
    if (view === 'images') {
        loadRegistryImages();
    } else if (view === 'settings') {
        loadRegistrySettings();
    } else if (view === 'stats') {
        renderStatsView();
    }
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
    
    // Refresh button
    const refreshBtn = document.getElementById('registry-refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            if (RegistryState.currentView === 'images') {
                loadRegistryImages();
            } else if (RegistryState.currentView === 'settings') {
                loadRegistrySettings();
            }
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
        pullModalBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            executePull(e);
        });
    }
    
    // Pull modal - image input (Enter key)
    const pullImageInput = document.getElementById('pull-image-input');
    if (pullImageInput) {
        pullImageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                e.stopPropagation();
                executePull(e);
            }
        });
    }
    
    // Settings form - save button
    const saveSettingsBtn = document.getElementById('registry-save-settings');
    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener('click', () => saveSettings());
    }
    
    // Storage type selector - show/hide backend fields
    const storageTypeSelector = document.getElementById('registry-storage-type');
    if (storageTypeSelector) {
        storageTypeSelector.addEventListener('change', (e) => {
            updateStorageFields(e.target.value);
        });
    }
    
    // Storage test button
    const testStorageBtn = document.getElementById('registry-test-storage');
    if (testStorageBtn) {
        testStorageBtn.addEventListener('click', () => testStorageConnection());
    }
}

// ============================================================================
// DATA LOADING
// ============================================================================

async function loadRegistryImages() {
    try {
        RegistryState.loading = true;
        renderImagesLoading();
        
        const data = await fetch(window.API('api/registry/images')).then(r => r.json());
        RegistryState.images = data.images || [];
        
        renderImages();
    } catch (error) {
        console.error('[Registry] Failed to load images:', error);
        renderImagesError(error.message);
    } finally {
        RegistryState.loading = false;
    }
}

async function loadRegistryStats() {
    try {
        const data = await fetch(window.API('api/registry/stats')).then(r => r.json());
        RegistryState.stats = data;
        renderStatsCards();
    } catch (error) {
        console.error('[Registry] Failed to load stats:', error);
        renderStatsError();
    }
}

async function loadRegistrySettings() {
    try {
        const data = await fetch(window.API('api/registry/settings')).then(r => r.json());
        RegistryState.settings = data;
        renderSettings();
    } catch (error) {
        console.error('[Registry] Failed to load settings:', error);
        renderSettingsError(error.message);
    }
}

// ============================================================================
// RENDERING - STATS CARDS (always visible)
// ============================================================================

function renderStatsCards() {
    const stats = RegistryState.stats || {};
    
    // Update stat cards
    const cachedImagesEl = document.getElementById('registry-stat-cached-images');
    if (cachedImagesEl) {
        cachedImagesEl.textContent = stats.cached_images || 0;
    }
    
    const storageUsedEl = document.getElementById('registry-stat-storage-used');
    if (storageUsedEl) {
        const gb = ((stats.storage_used || 0) / 1024 / 1024 / 1024).toFixed(2);
        storageUsedEl.textContent = `${gb} GB`;
    }
    
    const updatesAvailableEl = document.getElementById('registry-stat-updates');
    if (updatesAvailableEl) {
        updatesAvailableEl.textContent = stats.updates_available || 0;
    }
}

function renderStatsError() {
    const cachedImagesEl = document.getElementById('registry-stat-cached-images');
    if (cachedImagesEl) cachedImagesEl.textContent = '-';
    
    const storageUsedEl = document.getElementById('registry-stat-storage-used');
    if (storageUsedEl) storageUsedEl.textContent = '-';
    
    const updatesAvailableEl = document.getElementById('registry-stat-updates');
    if (updatesAvailableEl) updatesAvailableEl.textContent = '-';
}

// ============================================================================
// RENDERING - IMAGES VIEW
// ============================================================================

function renderImagesLoading() {
    const container = document.getElementById('registry-images-list');
    if (!container) return;
    
    container.innerHTML = '<div class="text-center"><div class="spinner"></div><p>Loading images...</p></div>';
}

function renderImagesError(message) {
    const container = document.getElementById('registry-images-list');
    if (!container) return;
    
    container.innerHTML = `<div class="alert alert-danger">Failed to load images: ${message}</div>`;
}

function renderImages() {
    const container = document.getElementById('registry-images-list');
    if (!container) return;
    
    const images = RegistryState.images;
    
    if (images.length === 0) {
        container.innerHTML = '<div class="text-center text-muted">No images cached yet. Pull an image to get started.</div>';
        return;
    }
    
    container.innerHTML = images.map(img => `
        <div class="registry-image-card">
            <div class="registry-image-header">
                <span class="registry-image-name">${escapeHtml(img.name || 'unknown')}</span>
                <span class="registry-image-tag">${escapeHtml(img.tag || 'latest')}</span>
            </div>
            <div class="registry-image-details">
                <div class="registry-image-detail">
                    <span class="label">Digest:</span>
                    <span class="value">${escapeHtml((img.digest || '').substring(0, 16))}...</span>
                </div>
                <div class="registry-image-detail">
                    <span class="label">Size:</span>
                    <span class="value">${formatBytes(img.size || 0)}</span>
                </div>
                <div class="registry-image-detail">
                    <span class="label">Pulled:</span>
                    <span class="value">${formatDate(img.pulled_at)}</span>
                </div>
                ${img.update_available ? '<div class="registry-update-badge">Update Available</div>' : ''}
            </div>
            <div class="registry-image-actions">
                <button class="btn btn-sm" onclick="deleteImage('${escapeHtml(img.id || '')}')">Delete</button>
            </div>
        </div>
    `).join('');
}

function filterImages(query) {
    const cards = document.querySelectorAll('.registry-image-card');
    const lowerQuery = query.toLowerCase();
    
    cards.forEach(card => {
        const name = card.querySelector('.registry-image-name')?.textContent.toLowerCase() || '';
        const tag = card.querySelector('.registry-image-tag')?.textContent.toLowerCase() || '';
        
        if (name.includes(lowerQuery) || tag.includes(lowerQuery)) {
            card.style.display = 'block';
        } else {
            card.style.display = 'none';
        }
    });
}

// ============================================================================
// RENDERING - SETTINGS VIEW
// ============================================================================

function renderSettings() {
    const settings = RegistryState.settings || {};
    
    // Auto-pull enabled
    const autoPullEl = document.getElementById('registry-auto-pull');
    if (autoPullEl) {
        autoPullEl.checked = settings.auto_pull !== false;
    }
    
    // Check interval
    const intervalEl = document.getElementById('registry-check-interval');
    if (intervalEl) {
        intervalEl.value = settings.check_interval_hours || 12;
    }
    
    // Keep versions
    const keepVersionsEl = document.getElementById('registry-keep-versions');
    if (keepVersionsEl) {
        keepVersionsEl.value = settings.keep_versions || 2;
    }
    
    // Max storage
    const maxStorageEl = document.getElementById('registry-max-storage');
    if (maxStorageEl) {
        maxStorageEl.value = settings.max_storage_gb || 50;
    }
    
    // Storage backend type
    const backend = settings.storage_backend || {};
    const storageTypeEl = document.getElementById('registry-storage-type');
    if (storageTypeEl) {
        storageTypeEl.value = backend.type || 'local';
        updateStorageFields(backend.type || 'local');
    }
    
    // NFS backend fields
    if (backend.type === 'nfs') {
        const nfsServerEl = document.getElementById('registry-nfs-server');
        const nfsPathEl = document.getElementById('registry-nfs-path');
        if (nfsServerEl) nfsServerEl.value = backend.server || '';
        if (nfsPathEl) nfsPathEl.value = backend.path || '';
    }
    
    // SMB backend fields
    if (backend.type === 'smb') {
        const smbServerEl = document.getElementById('registry-smb-server');
        const smbShareEl = document.getElementById('registry-smb-share');
        const smbUsernameEl = document.getElementById('registry-smb-username');
        if (smbServerEl) smbServerEl.value = backend.server || '';
        if (smbShareEl) smbShareEl.value = backend.share || '';
        if (smbUsernameEl) smbUsernameEl.value = backend.username || '';
    }
}

function renderSettingsError(message) {
    const container = document.getElementById('registry-settings-view');
    if (!container) return;
    
    const alert = document.createElement('div');
    alert.className = 'alert alert-danger';
    alert.textContent = `Failed to load settings: ${message}`;
    container.insertBefore(alert, container.firstChild);
}

function updateStorageFields(type) {
    // Show/hide storage backend fields based on type
    const nfsFields = document.getElementById('registry-nfs-fields');
    const smbFields = document.getElementById('registry-smb-fields');
    
    if (nfsFields) nfsFields.style.display = type === 'nfs' ? 'block' : 'none';
    if (smbFields) smbFields.style.display = type === 'smb' ? 'block' : 'none';
    
    console.log('[Registry] Storage type changed to:', type);
}

// ============================================================================
// RENDERING - STATS VIEW
// ============================================================================

function renderStatsView() {
    const container = document.getElementById('registry-stats-view');
    if (!container) return;
    
    const stats = RegistryState.stats || {};
    
    container.innerHTML = `
        <div class="stats-grid">
            <div class="stat-card">
                <h3>Cached Images</h3>
                <div class="stat-value">${stats.cached_images || 0}</div>
            </div>
            <div class="stat-card">
                <h3>Storage Used</h3>
                <div class="stat-value">${formatBytes(stats.storage_used || 0)}</div>
            </div>
            <div class="stat-card">
                <h3>Updates Available</h3>
                <div class="stat-value">${stats.updates_available || 0}</div>
            </div>
            <div class="stat-card">
                <h3>Total Pulls</h3>
                <div class="stat-value">${stats.total_pulls || 0}</div>
            </div>
        </div>
        
        <div class="stats-details">
            <h3>Registry Status</h3>
            <table class="table">
                <tr>
                    <td>Registry Port</td>
                    <td>${stats.registry_port || 5001}</td>
                </tr>
                <tr>
                    <td>Storage Path</td>
                    <td>${escapeHtml(stats.storage_path || '/share/jarvis_prime/registry')}</td>
                </tr>
                <tr>
                    <td>Auto-Pull</td>
                    <td>${stats.auto_pull ? 'Enabled' : 'Disabled'}</td>
                </tr>
                <tr>
                    <td>Last Update Check</td>
                    <td>${formatDate(stats.last_check || null)}</td>
                </tr>
            </table>
        </div>
    `;
}

// ============================================================================
// ACTIONS - PULL IMAGE
// ============================================================================

function openPullModal() {
    const modal = document.getElementById('registry-pull-modal');
    if (modal) {
        modal.style.display = 'flex';
        RegistryState.pullModalOpen = true;
        document.getElementById('pull-image-input')?.focus();
    }
}

function closePullModal() {
    const modal = document.getElementById('registry-pull-modal');
    if (modal) {
        modal.style.display = 'none';
        RegistryState.pullModalOpen = false;
        document.getElementById('pull-image-input').value = '';
    }
}

async function executePull(event) {
    // Prevent form submission and page refresh
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    
    const input = document.getElementById('pull-image-input');
    const imageName = input?.value.trim();
    
    if (!imageName) {
        if (typeof showToast === 'function') {
            showToast('Please enter an image name', 'error');
        } else {
            alert('Please enter an image name');
        }
        return false;
    }
    
    const btn = document.getElementById('pull-modal-btn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = '⏳ Pulling...';
    }
    
    try {
        console.log('[Registry] Pulling image:', imageName);
        
        const response = await fetch(window.API('api/registry/pull'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: imageName })
        });
        
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${errorText}`);
        }
        
        const data = await response.json();
        
        if (data.success) {
            if (typeof showToast === 'function') {
                showToast(`Successfully pulled ${imageName}`, 'success');
            } else {
                alert(`Successfully pulled ${imageName}`);
            }
            closePullModal();
            loadRegistryImages();
            loadRegistryStats();
        } else {
            throw new Error(data.error || 'Pull failed');
        }
    } catch (error) {
        console.error('[Registry] Pull error:', error);
        if (typeof showToast === 'function') {
            showToast(`Failed to pull image: ${error.message}`, 'error');
        } else {
            alert(`Failed to pull image: ${error.message}`);
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = '⬇️ Pull Image';
        }
    }
    
    return false;
}

// ============================================================================
// ACTIONS - DELETE IMAGE
// ============================================================================

async function deleteImage(imageId) {
    if (!confirm('Delete this image from cache?')) return;
    
    try {
        const response = await fetch(window.API(`api/registry/images/${imageId}`), {
            method: 'DELETE'
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        showToast('Image deleted', 'success');
        loadRegistryImages();
        loadRegistryStats();
    } catch (error) {
        console.error('[Registry] Delete error:', error);
        showToast(`Failed to delete image: ${error.message}`, 'error');
    }
}

// ============================================================================
// ACTIONS - CHECK UPDATES
// ============================================================================

async function checkForUpdates() {
    const btn = document.getElementById('registry-check-updates-btn');
    if (btn) btn.classList.add('loading');
    
    try {
        const response = await fetch(window.API('api/registry/check-updates'), {
            method: 'POST'
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        showToast('Update check complete', 'success');
        loadRegistryImages();
        loadRegistryStats();
    } catch (error) {
        console.error('[Registry] Update check error:', error);
        showToast(`Update check failed: ${error.message}`, 'error');
    } finally {
        if (btn) btn.classList.remove('loading');
    }
}

// ============================================================================
// ACTIONS - SAVE SETTINGS
// ============================================================================

async function saveSettings() {
    const storageType = document.getElementById('registry-storage-type')?.value || 'local';
    
    const settings = {
        auto_pull: document.getElementById('registry-auto-pull')?.checked || false,
        check_interval_hours: parseInt(document.getElementById('registry-check-interval')?.value || '12'),
        keep_versions: parseInt(document.getElementById('registry-keep-versions')?.value || '2'),
        max_storage_gb: parseInt(document.getElementById('registry-max-storage')?.value || '50'),
        storage_backend: {
            type: storageType
        }
    };
    
    // Add NFS-specific fields
    if (storageType === 'nfs') {
        settings.storage_backend.server = document.getElementById('registry-nfs-server')?.value || '';
        settings.storage_backend.path = document.getElementById('registry-nfs-path')?.value || '';
    }
    
    // Add SMB-specific fields
    if (storageType === 'smb') {
        settings.storage_backend.server = document.getElementById('registry-smb-server')?.value || '';
        settings.storage_backend.share = document.getElementById('registry-smb-share')?.value || '';
        settings.storage_backend.username = document.getElementById('registry-smb-username')?.value || '';
        settings.storage_backend.password = document.getElementById('registry-smb-password')?.value || '';
    }
    
    const btn = document.getElementById('registry-save-settings');
    if (btn) {
        btn.disabled = true;
        btn.textContent = '💾 Saving...';
    }
    
    try {
        const response = await fetch(window.API('api/registry/settings'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        if (typeof showToast === 'function') {
            showToast('Settings saved', 'success');
        } else {
            alert('Settings saved');
        }
        loadRegistrySettings();
    } catch (error) {
        console.error('[Registry] Save settings error:', error);
        if (typeof showToast === 'function') {
            showToast(`Failed to save settings: ${error.message}`, 'error');
        } else {
            alert(`Failed to save settings: ${error.message}`);
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = '💾 Save Settings';
        }
    }
}

// ============================================================================
// ACTIONS - TEST STORAGE
// ============================================================================

async function testStorageConnection() {
    const storageType = document.getElementById('registry-storage-type')?.value;
    
    const btn = document.getElementById('registry-test-storage');
    if (btn) btn.classList.add('loading');
    
    try {
        const response = await fetch(window.API('api/registry/storage/test'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ storage_backend: { type: storageType } })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Storage connection successful', 'success');
        } else {
            showToast(`Storage test failed: ${data.error || 'Unknown error'}`, 'error');
        }
    } catch (error) {
        console.error('[Registry] Storage test error:', error);
        showToast(`Storage test failed: ${error.message}`, 'error');
    } finally {
        if (btn) btn.classList.remove('loading');
    }
}

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatDate(timestamp) {
    if (!timestamp) return 'Never';
    try {
        return new Date(timestamp).toLocaleString();
    } catch {
        return 'Invalid date';
    }
}

// Expose functions globally
window.initRegistry = initRegistry;
window.deleteImage = deleteImage;
