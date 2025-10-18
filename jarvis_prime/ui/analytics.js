// Analytics Module for Jarvis Prime
// Handles all analytics UI interactions and API calls
// UPGRADED: Added retry and flap protection features
// PATCHED: analyticsLoadIncidents now handles { "incidents": [...] } format consistently
// UPGRADED: Added network monitoring capabilities

// Use the API() helper from app.js for proper path resolution
const ANALYTICS_API = (path = '') => {
  if (typeof API === 'function') {
    return API('api/analytics/' + path.replace(/^\/+/, ''));
  }
  
  // Fallback: replicate apiRoot() + API() logic from app.js
  try {
    const u = new URL(document.baseURI);
    let p = u.pathname;
    
    if (p.endsWith('/index.html')) {
      p = p.slice(0, -'/index.html'.length);
    }
    
    // Only strip /ui/ if NOT under ingress
    if (!p.includes('/ingress/') && p.endsWith('/ui/')) {
      p = p.slice(0, -4);
    }
    
    if (!p.endsWith('/')) p += '/';
    u.pathname = p + 'api/analytics/' + path.replace(/^\/+/, '');
    return u.toString();
  } catch (e) {
    return '/api/analytics/' + path.replace(/^\/+/, '');
  }
};

// Initialize analytics when tab is opened
document.addEventListener('DOMContentLoaded', () => {
  // Setup analytics tab switching
  document.querySelectorAll('[data-analytics-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.analyticsTab;
      switchAnalyticsTab(tab);
    });
  });

  // Auto-refresh every 30 seconds when analytics tab is active
  setInterval(() => {
    const analyticsTab = document.getElementById('analytics');
    if (analyticsTab && analyticsTab.classList.contains('active')) {
      analyticsRefresh();
    }
  }, 30000);
});

// Switch between analytics sub-tabs
function switchAnalyticsTab(tabName) {
  // Update tab buttons
  document.querySelectorAll('[data-analytics-tab]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.analyticsTab === tabName);
  });

  // Update tab panels
  document.querySelectorAll('#analytics .orch-panel').forEach(panel => {
    panel.classList.remove('active');
  });
  document.getElementById(`analytics-${tabName}`).classList.add('active');

  // Load data for the selected tab
  if (tabName === 'dashboard') {
    analyticsLoadDashboard();
  } else if (tabName === 'services') {
    analyticsLoadServices();
  } else if (tabName === 'incidents') {
    analyticsLoadIncidents();
  } else if (tabName === 'network') {
    analyticsLoadNetworkDashboard();
  }
}

// Refresh all analytics data
function analyticsRefresh() {
  analyticsLoadHealthScore();
  analyticsLoadDashboard();
  analyticsLoadServices();
  analyticsLoadIncidents();
}

// Load health score metrics
async function analyticsLoadHealthScore() {
  try {
    const response = await fetch(ANALYTICS_API('health-score'));
    const data = await response.json();

    document.getElementById('health-score').textContent = data.health_score + '%';
    document.getElementById('services-up').textContent = data.up_services || 0;
    document.getElementById('services-down').textContent = data.down_services || 0;
    document.getElementById('services-total').textContent = data.total_services || 0;

    // Color code health score
    const scoreEl = document.getElementById('health-score');
    if (data.health_score >= 99) {
      scoreEl.style.color = '#22c55e';
    } else if (data.health_score >= 95) {
      scoreEl.style.color = '#60a5fa';
    } else if (data.health_score >= 90) {
      scoreEl.style.color = '#f59e0b';
    } else {
      scoreEl.style.color = '#ef4444';
    }
  } catch (error) {
    console.error('Error loading health score:', error);
  }
}

// Load dashboard service cards
async function analyticsLoadDashboard() {
  const grid = document.getElementById('analytics-services-grid');
  
  try {
    const response = await fetch(ANALYTICS_API('services'));
    const services = await response.json();

    if (services.length === 0) {
      grid.innerHTML = `
        <div class="text-center text-muted">
          <p>No services configured yet</p>
          <button class="btn primary" onclick="switchAnalyticsTab('services'); analyticsShowAddService();">Add Your First Service</button>
        </div>
      `;
      return;
    }

    grid.innerHTML = '';
    
    for (const service of services) {
      const uptime = await analyticsGetUptime(service.service_name);
      const card = analyticsCreateServiceCard(service, uptime);
      grid.appendChild(card);
    }
  } catch (error) {
    console.error('Error loading dashboard:', error);
    grid.innerHTML = '<div class="text-center text-muted">Error loading services</div>';
  }
}

// Get uptime stats for a service
async function analyticsGetUptime(serviceName) {
  try {
    const response = await fetch(ANALYTICS_API(`uptime/${encodeURIComponent(serviceName)}`));
    return await response.json();
  } catch {
    return null;
  }
}

// Create a service card element
function analyticsCreateServiceCard(service, uptime) {
  const card = document.createElement('div');
  card.className = 'playbook-card';

  const status = service.current_status || 'unknown';
  const statusColors = {
    up: '#22c55e',
    down: '#ef4444',
    degraded: '#f59e0b',
    unknown: '#6b7280'
  };

  const lastCheck = service.last_check 
    ? new Date(service.last_check * 1000).toLocaleString()
    : 'Never';

  // NEW: Flap protection indicators
  const flapBadge = service.is_suppressed 
    ? `<span style="padding: 4px 8px; background: rgba(245, 158, 11, 0.2); color: #f59e0b; border-radius: 6px; font-size: 10px; font-weight: 600; margin-left: 8px;">
         🔇 SUPPRESSED
       </span>`
    : service.flap_count > 0
    ? `<span style="padding: 4px 8px; background: rgba(245, 158, 11, 0.1); color: #f59e0b; border-radius: 6px; font-size: 10px; margin-left: 8px;">
         ${service.flap_count} flaps
       </span>`
    : '';

  card.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 12px;">
      <div style="flex: 1;">
        <h3 style="margin: 0; font-size: 18px;">${service.service_name}</h3>
        ${flapBadge}
      </div>
      <span style="padding: 4px 12px; background: ${statusColors[status]}22; color: ${statusColors[status]}; border-radius: 12px; font-size: 11px; font-weight: 600; text-transform: uppercase;">
        ${status}
      </span>
    </div>
    <div style="font-family: monospace; font-size: 13px; color: #60a5fa; margin-bottom: 8px;">
      ${service.endpoint}
    </div>
    <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 16px;">
      Last check: ${lastCheck} • ${service.check_type.toUpperCase()} • ${service.retries || 3} retries
    </div>
    ${uptime ? `
      <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; padding-top: 12px; border-top: 1px solid var(--border);">
        <div style="text-align: center;">
          <div style="font-size: 18px; font-weight: 600;">${uptime.uptime_percentage}%</div>
          <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase;">Uptime 24h</div>
        </div>
        <div style="text-align: center;">
          <div style="font-size: 18px; font-weight: 600;">${uptime.avg_response_time ? uptime.avg_response_time + 's' : 'N/A'}</div>
          <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase;">Avg Response</div>
        </div>
        <div style="text-align: center;">
          <div style="font-size: 18px; font-weight: 600;">${uptime.total_checks}</div>
          <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase;">Checks</div>
        </div>
      </div>
    ` : ''}
  `;

  return card;
}

// Load services table
async function analyticsLoadServices() {
  const tbody = document.getElementById('analytics-services-list');
  
  try {
    const response = await fetch(ANALYTICS_API('services'));
    const services = await response.json();

    if (services.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" class="text-center text-muted">No services configured yet</td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = '';
    
    services.forEach(service => {
      const tr = document.createElement('tr');
      const status = service.current_status || 'unknown';
      const statusColors = {
        up: '#22c55e',
        down: '#ef4444',
        degraded: '#f59e0b',
        unknown: '#6b7280'
      };

      tr.innerHTML = `
        <td>${service.service_name}</td>
        <td><code style="font-size: 12px;">${service.endpoint}</code></td>
        <td>${service.check_type.toUpperCase()}</td>
        <td>
          <span style="padding: 4px 8px; background: ${statusColors[status]}22; color: ${statusColors[status]}; border-radius: 6px; font-size: 11px; font-weight: 600; text-transform: uppercase;">
            ${status}
          </span>
        </td>
        <td>${service.check_interval}s</td>
        <td>
          <span class="badge ${service.enabled ? 'badge-success' : 'badge-default'}">
            ${service.enabled ? 'Enabled' : 'Disabled'}
          </span>
        </td>
        <td>
          <button class="btn btn-sm" onclick="analyticsEditService(${service.id})" title="Edit">✏️</button>
          <button class="btn btn-sm" onclick="analyticsDeleteService(${service.id}, '${service.service_name}')" title="Delete">🗑️</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (error) {
    console.error('Error loading services:', error);
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Error loading services</td></tr>';
  }
}

// Load incidents
async function analyticsLoadIncidents() {
  const tbody = document.getElementById('analytics-incidents-list');
  
  try {
    const response = await fetch(ANALYTICS_API('incidents?days=7'));
    const data = await response.json();
    
    // PATCHED: Handle both array and object formats
    const incidents = Array.isArray(data) ? data : (data.incidents || []);

    if (incidents.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="5" class="text-center text-muted">
            <div style="padding: 2rem;">
              <div style="font-size: 48px; opacity: 0.5;">✅</div>
              <p>No incidents in the last 7 days</p>
            </div>
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = '';
    
    incidents.forEach(incident => {
      const tr = document.createElement('tr');
      const startTime = new Date(incident.start_time * 1000).toLocaleString();
      const endTime = incident.end_time 
        ? new Date(incident.end_time * 1000).toLocaleString()
        : 'Ongoing';
      
      const duration = incident.duration 
        ? formatDuration(incident.duration)
        : 'Ongoing';

      const statusColor = incident.status === 'resolved' ? '#22c55e' : '#ef4444';

      tr.innerHTML = `
        <td>${incident.service}</td>
        <td>${incident.message || 'Service unavailable'}</td>
        <td>${startTime}</td>
        <td>${duration}</td>
        <td>
          <span style="padding: 4px 8px; background: ${statusColor}22; color: ${statusColor}; border-radius: 6px; font-size: 11px; font-weight: 600; text-transform: uppercase;">
            ${incident.status}
          </span>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (error) {
    console.error('Error loading incidents:', error);
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Error loading incidents</td></tr>';
  }
}

function formatDuration(seconds) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

// Show add service modal
function analyticsShowAddService() {
  document.getElementById('analytics-service-id').value = '';
  document.getElementById('analytics-service-name').value = '';
  document.getElementById('analytics-service-endpoint').value = '';
  document.getElementById('analytics-check-type').value = 'http';
  document.getElementById('analytics-expected-status').value = '200';
  document.getElementById('analytics-check-interval').value = '60';
  document.getElementById('analytics-check-timeout').value = '5';
  document.getElementById('analytics-service-enabled').checked = true;
  
  // NEW: Reset retry and flap protection fields
  document.getElementById('analytics-retries').value = '3';
  document.getElementById('analytics-flap-window').value = '3600';
  document.getElementById('analytics-flap-threshold').value = '5';
  document.getElementById('analytics-suppression-duration').value = '3600';
  
  analyticsToggleStatusCode();
  document.getElementById('analytics-service-modal').classList.add('active');
}

// Edit service
async function analyticsEditService(serviceId) {
  try {
    const response = await fetch(ANALYTICS_API(`services/${serviceId}`));
    const service = await response.json();

    document.getElementById('analytics-service-id').value = service.id;
    document.getElementById('analytics-service-name').value = service.service_name;
    document.getElementById('analytics-service-endpoint').value = service.endpoint;
    document.getElementById('analytics-check-type').value = service.check_type;
    document.getElementById('analytics-expected-status').value = service.expected_status;
    document.getElementById('analytics-check-interval').value = service.check_interval;
    document.getElementById('analytics-check-timeout').value = service.timeout;
    document.getElementById('analytics-service-enabled').checked = service.enabled;
    
    // NEW: Load retry and flap protection values
    document.getElementById('analytics-retries').value = service.retries || 3;
    document.getElementById('analytics-flap-window').value = service.flap_window || 3600;
    document.getElementById('analytics-flap-threshold').value = service.flap_threshold || 5;
    document.getElementById('analytics-suppression-duration').value = service.suppression_duration || 3600;

    analyticsToggleStatusCode();
    document.getElementById('analytics-service-modal').classList.add('active');
  } catch (error) {
    console.error('Error loading service:', error);
    showToast('Failed to load service', 'error');
  }
}

// Delete service
async function analyticsDeleteService(serviceId, serviceName) {
  if (!confirm(`Delete service "${serviceName}"? This will also remove all associated metrics.`)) return;

  try {
    await fetch(ANALYTICS_API(`services/${serviceId}`), {
      method: 'DELETE'
    });

    showToast('Service deleted', 'success');
    analyticsRefresh();
  } catch (error) {
    console.error('Error deleting service:', error);
    showToast('Failed to delete service', 'error');
  }
}

// Close service modal
function analyticsCloseServiceModal() {
  document.getElementById('analytics-service-modal').classList.remove('active');
}

// Toggle status code field based on check type
function analyticsToggleStatusCode() {
  const checkType = document.getElementById('analytics-check-type').value;
  const statusGroup = document.getElementById('analytics-status-code-group');
  statusGroup.style.display = checkType === 'http' ? 'block' : 'none';
}

// Save service - UPDATED to include retry and flap protection
async function analyticsSaveService(event) {
  event.preventDefault();

  const serviceId = document.getElementById('analytics-service-id').value;
  const data = {
    service_name: document.getElementById('analytics-service-name').value,
    endpoint: document.getElementById('analytics-service-endpoint').value,
    check_type: document.getElementById('analytics-check-type').value,
    expected_status: parseInt(document.getElementById('analytics-expected-status').value),
    timeout: parseInt(document.getElementById('analytics-check-timeout').value),
    check_interval: parseInt(document.getElementById('analytics-check-interval').value),
    enabled: document.getElementById('analytics-service-enabled').checked,
    
    // NEW: Include retry and flap protection fields
    retries: parseInt(document.getElementById('analytics-retries').value) || 3,
    flap_window: parseInt(document.getElementById('analytics-flap-window').value) || 3600,
    flap_threshold: parseInt(document.getElementById('analytics-flap-threshold').value) || 5,
    suppression_duration: parseInt(document.getElementById('analytics-suppression-duration').value) || 3600
  };

  try {
    const url = serviceId ? ANALYTICS_API(`services/${serviceId}`) : ANALYTICS_API('services');
    const method = serviceId ? 'PUT' : 'POST';

    await fetch(url, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });

    showToast(serviceId ? 'Service updated' : 'Service added', 'success');
    analyticsCloseServiceModal();
    analyticsRefresh();
  } catch (error) {
    console.error('Error saving service:', error);
    showToast('Failed to save service', 'error');
  }
}

// Reset health scores
async function analyticsResetHealth() {
  if (!confirm('Reset all health scores? This will clear all metrics history and start fresh.')) return;

  try {
    const response = await fetch(ANALYTICS_API('reset-health'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    
    const result = await response.json();
    
    if (result.success) {
      showToast('Health scores reset successfully', 'success');
      analyticsRefresh();
    } else {
      showToast('Failed to reset: ' + result.error, 'error');
    }
  } catch (error) {
    console.error('Error resetting health scores:', error);
    showToast('Failed to reset health scores', 'error');
  }
}

// Reset incidents
async function analyticsResetIncidents() {
  if (!confirm('Clear all incidents? This will permanently delete all incident history.')) return;

  try {
    const response = await fetch(ANALYTICS_API('reset-incidents'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    
    const result = await response.json();
    
    if (result.success) {
      showToast('All incidents cleared', 'success');
      analyticsRefresh();
    } else {
      showToast('Failed to clear: ' + result.error, 'error');
    }
  } catch (error) {
    console.error('Error clearing incidents:', error);
    showToast('Failed to clear incidents', 'error');
  }
}

// Reset service data (optional - for per-service reset)
async function analyticsResetServiceData(serviceName) {
  if (!confirm(`Reset all data for ${serviceName}? This will clear metrics and incidents for this service only.`)) return;

  try {
    const response = await fetch(ANALYTICS_API(`reset-service/${encodeURIComponent(serviceName)}`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    
    const result = await response.json();
    
    if (result.success) {
      showToast(`Data reset for ${serviceName}`, 'success');
      analyticsRefresh();
    } else {
      showToast('Failed to reset: ' + result.error, 'error');
    }
  } catch (error) {
    console.error('Error resetting service data:', error);
    showToast('Failed to reset service data', 'error');
  }
}

// ============================================
// PURGE FUNCTIONS - FIXED ROUTES
// ============================================

// Purge ALL metrics
async function analyticsPurgeAll() {
  if (!confirm('⚠️ DANGER: Purge ALL metrics history? This cannot be undone!')) return;
  if (!confirm('Are you absolutely sure? This will delete EVERYTHING.')) return;

  try {
    const response = await fetch(ANALYTICS_API('purge-all'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    
    const result = await response.json();
    if (result.success) {
      showToast(`Purged all ${result.deleted} metrics`, 'success');
      analyticsRefresh();
    } else {
      showToast('Failed to purge: ' + result.error, 'error');
    }
  } catch (error) {
    console.error('Error purging all metrics:', error);
    showToast('Failed to purge metrics', 'error');
  }
}

// Purge metrics older than 1 week
async function analyticsPurgeWeek() {
  if (!confirm('Purge metrics older than 1 week (7 days)?')) return;

  try {
    const response = await fetch(ANALYTICS_API('purge-week'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    
    const result = await response.json();
    if (result.success) {
      showToast(`Purged ${result.deleted} metrics older than 1 week`, 'success');
      analyticsRefresh();
    } else {
      showToast('Failed to purge: ' + result.error, 'error');
    }
  } catch (error) {
    console.error('Error purging week metrics:', error);
    showToast('Failed to purge metrics', 'error');
  }
}

// Purge metrics older than 1 month
async function analyticsPurgeMonth() {
  if (!confirm('Purge metrics older than 1 month (30 days)?')) return;

  try {
    const response = await fetch(ANALYTICS_API('purge-month'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    
    const result = await response.json();
    if (result.success) {
      showToast(`Purged ${result.deleted} metrics older than 1 month`, 'success');
      analyticsRefresh();
    } else {
      showToast('Failed to purge: ' + result.error, 'error');
    }
  } catch (error) {
    console.error('Error purging month metrics:', error);
    showToast('Failed to purge metrics', 'error');
  }
}

// ============================================
// NETWORK MONITORING ADDITIONS
// ============================================

// Network Monitoring State
let networkDevices = [];
let networkMonitoringActive = false;
let networkAlertNewDevices = true;
let selectedDevicesForMonitoring = new Set();

// Load network monitoring dashboard
async function analyticsLoadNetworkDashboard() {
  await Promise.all([
    analyticsLoadNetworkStats(),
    analyticsLoadNetworkDevices(),
    analyticsLoadNetworkEvents(),
    analyticsLoadNetworkStatus()
  ]);
}

// Load network statistics
async function analyticsLoadNetworkStats() {
  try {
    const response = await fetch(ANALYTICS_API('network/stats'));
    const stats = await response.json();

    document.getElementById('net-total-devices').textContent = stats.total_devices || 0;
    document.getElementById('net-monitored-devices').textContent = stats.monitored_devices || 0;
    document.getElementById('net-permanent-devices').textContent = stats.permanent_devices || 0;
    document.getElementById('net-scans-24h').textContent = stats.scans_24h || 0;

    // Update last scan time
    if (stats.last_scan) {
      const lastScan = new Date(stats.last_scan * 1000);
      document.getElementById('net-last-scan').textContent = formatTimestamp(lastScan);
    } else {
      document.getElementById('net-last-scan').textContent = 'Never';
    }
  } catch (error) {
    console.error('Error loading network stats:', error);
  }
}

// Load network devices
async function analyticsLoadNetworkDevices() {
  try {
    const response = await fetch(ANALYTICS_API('network/devices'));
    const data = await response.json();
    networkDevices = data.devices || [];

    const tbody = document.getElementById('network-devices-list');
    tbody.innerHTML = '';

    if (networkDevices.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" style="text-align: center; padding: 2rem; color: var(--text-muted);">
            No devices found. Run a network scan to discover devices.
          </td>
        </tr>
      `;
      return;
    }

    networkDevices.forEach(device => {
      const tr = document.createElement('tr');
      
      // Determine display name (custom_name > hostname > "Unknown")
      const displayName = device.custom_name || device.hostname || '<span style="color: var(--text-muted);">Unknown</span>';
      
      // Check if already in services
      const isInServices = device.in_services || false;
      const checkboxDisabled = isInServices ? 'disabled' : '';
      const checkboxTitle = isInServices ? 'Already monitored in Services tab' : 'Monitor this device';
      
      tr.innerHTML = `
        <td>
          <input type="checkbox" 
                 class="device-checkbox" 
                 data-mac="${device.mac_address}"
                 ${device.is_monitored ? 'checked' : ''}
                 ${checkboxDisabled}
                 title="${checkboxTitle}"
                 onchange="networkToggleMonitoring('${device.mac_address}', this.checked)">
        </td>
        <td><code>${device.mac_address}</code></td>
        <td><code>${device.ip_address || 'Unknown'}</code></td>
        <td>
          <span class="device-name-display" id="name-${device.mac_address}" 
                onclick="networkEditDeviceName('${device.mac_address}')" 
                style="cursor: pointer;" 
                title="Click to edit name">
            ${displayName} ✏️
          </span>
          <input type="text" 
                 class="device-name-input" 
                 id="name-input-${device.mac_address}" 
                 style="display: none; width: 150px;"
                 value="${device.custom_name || device.hostname || ''}"
                 onblur="networkSaveDeviceName('${device.mac_address}')"
                 onkeypress="if(event.key==='Enter') networkSaveDeviceName('${device.mac_address}')">
        </td>
        <td>${device.vendor || '<span style="color: var(--text-muted);">Unknown</span>'}</td>
        <td>
          <span class="badge ${device.is_permanent ? 'badge-success' : 'badge-default'}">
            ${device.is_permanent ? 'Permanent' : 'Temporary'}
          </span>
          ${device.is_monitored ? '<span class="badge badge-info">Monitored</span>' : ''}
          ${isInServices ? '<span class="badge badge-warning">In Services</span>' : ''}
        </td>
        <td>
          <button class="btn btn-sm" onclick="networkTogglePermanent('${device.mac_address}', ${!device.is_permanent})" 
                  title="${device.is_permanent ? 'Mark as Temporary' : 'Mark as Permanent'}">
            ${device.is_permanent ? '📌' : '📍'}
          </button>
          <button class="btn btn-sm" onclick="networkDeleteDevice('${device.mac_address}')" title="Delete Device">
            🗑️
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (error) {
    console.error('Error loading network devices:', error);
    showToast('Failed to load devices', 'error');
  }
}

// Edit device name
function networkEditDeviceName(macAddress) {
  const displayEl = document.getElementById(`name-${macAddress}`);
  const inputEl = document.getElementById(`name-input-${macAddress}`);
  
  if (displayEl && inputEl) {
    displayEl.style.display = 'none';
    inputEl.style.display = 'inline-block';
    inputEl.focus();
    inputEl.select();
  }
}

// Save device name
async function networkSaveDeviceName(macAddress) {
  const displayEl = document.getElementById(`name-${macAddress}`);
  const inputEl = document.getElementById(`name-input-${macAddress}`);
  
  if (!inputEl) return;
  
  const newName = inputEl.value.trim();
  
  try {
    const response = await fetch(ANALYTICS_API(`network/devices/${macAddress}`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ custom_name: newName })
    });
    
    const result = await response.json();
    
    if (result.success) {
      showToast(newName ? 'Device renamed' : 'Name cleared', 'success');
      await analyticsLoadNetworkDevices();
    } else {
      showToast('Failed to rename device', 'error');
      if (displayEl && inputEl) {
        displayEl.style.display = 'inline';
        inputEl.style.display = 'none';
      }
    }
  } catch (error) {
    console.error('Error saving device name:', error);
    showToast('Failed to rename device', 'error');
    if (displayEl && inputEl) {
      displayEl.style.display = 'inline';
      inputEl.style.display = 'none';
    }
  }
}

// Run network scan
async function networkRunScan() {
  const scanBtn = document.getElementById('btn-network-scan');
  const originalText = scanBtn.textContent;
  
  try {
    scanBtn.disabled = true;
    scanBtn.textContent = '🔍 Scanning...';
    
    const response = await fetch(ANALYTICS_API('network/scan'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    
    const result = await response.json();
    
    if (result.success) {
      showToast(`Network scan complete: ${result.devices_found} devices found`, 'success');
      await analyticsLoadNetworkDashboard();
    } else {
      showToast('Network scan failed', 'error');
    }
  } catch (error) {
    console.error('Error running network scan:', error);
    showToast('Failed to run network scan', 'error');
  } finally {
    scanBtn.disabled = false;
    scanBtn.textContent = originalText;
  }
}

// Toggle device monitoring
async function networkToggleMonitoring(macAddress, isMonitored) {
  try {
    const response = await fetch(ANALYTICS_API(`network/devices/${macAddress}`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_monitored: isMonitored })
    });
    
    const result = await response.json();
    
    if (result.success) {
      showToast(isMonitored ? 'Device added to monitoring' : 'Device removed from monitoring', 'success');
      await analyticsLoadNetworkDashboard();
    } else {
      showToast('Failed to update device', 'error');
    }
  } catch (error) {
    console.error('Error toggling monitoring:', error);
    showToast('Failed to update device', 'error');
  }
}

// Toggle permanent status
async function networkTogglePermanent(macAddress, isPermanent) {
  try {
    const response = await fetch(ANALYTICS_API(`network/devices/${macAddress}`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_permanent: isPermanent })
    });
    
    const result = await response.json();
    
    if (result.success) {
      showToast(isPermanent ? 'Marked as permanent device' : 'Marked as temporary device', 'success');
      await analyticsLoadNetworkDevices();
    } else {
      showToast('Failed to update device', 'error');
    }
  } catch (error) {
    console.error('Error toggling permanent:', error);
    showToast('Failed to update device', 'error');
  }
}

// Delete device
async function networkDeleteDevice(macAddress) {
  if (!confirm('Delete this device from the database?')) return;
  
  try {
    const response = await fetch(ANALYTICS_API(`network/devices/${macAddress}`), {
      method: 'DELETE'
    });
    
    const result = await response.json();
    
    if (result.success) {
      showToast('Device deleted', 'success');
      await analyticsLoadNetworkDevices();
    } else {
      showToast('Failed to delete device', 'error');
    }
  } catch (error) {
    console.error('Error deleting device:', error);
    showToast('Failed to delete device', 'error');
  }
}

// Start/Stop network monitoring
async function networkToggleMonitoringMode() {
  try {
    const endpoint = networkMonitoringActive ? 'monitoring/stop' : 'monitoring/start';
    
    const response = await fetch(ANALYTICS_API(`network/${endpoint}`), {
      method: 'POST'
    });
    
    const result = await response.json();
    
    if (result.success) {
      networkMonitoringActive = result.monitoring;
      showToast(networkMonitoringActive ? 'Network monitoring started' : 'Network monitoring stopped', 'success');
      await analyticsLoadNetworkStatus();
    } else {
      showToast('Failed to toggle monitoring', 'error');
    }
  } catch (error) {
    console.error('Error toggling monitoring:', error);
    showToast('Failed to toggle monitoring', 'error');
  }
}

// Load network monitoring status
async function analyticsLoadNetworkStatus() {
  try {
    const response = await fetch(ANALYTICS_API('network/monitoring/status'));
    const status = await response.json();
    
    networkMonitoringActive = status.monitoring;
    networkAlertNewDevices = status.alert_new_devices;
    
    // Update UI
    const monitorBtn = document.getElementById('btn-toggle-monitoring');
    if (monitorBtn) {
      monitorBtn.textContent = networkMonitoringActive ? '⏸️ Stop Monitoring' : '▶️ Start Monitoring';
      monitorBtn.classList.toggle('btn-success', !networkMonitoringActive);
      monitorBtn.classList.toggle('btn-warning', networkMonitoringActive);
    }
    
    const alertToggle = document.getElementById('toggle-alert-new-devices');
    if (alertToggle) {
      alertToggle.checked = networkAlertNewDevices;
    }
    
    const statusEl = document.getElementById('network-monitoring-status');
    if (statusEl) {
      statusEl.textContent = networkMonitoringActive ? 'Active' : 'Inactive';
      statusEl.className = `badge ${networkMonitoringActive ? 'badge-success' : 'badge-default'}`;
    }
  } catch (error) {
    console.error('Error loading network status:', error);
  }
}

// Toggle new device alerts
async function networkToggleAlerts() {
  const enabled = document.getElementById('toggle-alert-new-devices').checked;
  
  try {
    const response = await fetch(ANALYTICS_API('network/settings'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ alert_new_devices: enabled })
    });
    
    const result = await response.json();
    
    if (result.success) {
      networkAlertNewDevices = enabled;
      showToast(enabled ? 'New device alerts enabled' : 'New device alerts disabled', 'success');
    } else {
      showToast('Failed to update settings', 'error');
    }
  } catch (error) {
    console.error('Error updating alerts:', error);
    showToast('Failed to update settings', 'error');
  }
}

// Load network events
async function analyticsLoadNetworkEvents() {
  try {
    const response = await fetch(ANALYTICS_API('network/events?hours=24'));
    const data = await response.json();
    const events = data.events || [];

    const tbody = document.getElementById('network-events-list');
    tbody.innerHTML = '';

    if (events.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="5" style="text-align: center; padding: 2rem; color: var(--text-muted);">
            No events in the last 24 hours
          </td>
        </tr>
      `;
      return;
    }

    events.slice(0, 20).forEach(event => {
      const tr = document.createElement('tr');
      const eventTime = new Date(event.timestamp * 1000);
      
      let eventIcon = '📡';
      let eventColor = 'var(--text-primary)';
      
      if (event.event_type === 'new_device') {
        eventIcon = '🆕';
        eventColor = '#10b981';
      } else if (event.event_type === 'device_offline') {
        eventIcon = '⚠️';
        eventColor = '#f59e0b';
      } else if (event.event_type === 'device_online') {
        eventIcon = '✅';
        eventColor = '#3b82f6';
      }
      
      tr.innerHTML = `
        <td style="color: ${eventColor};">${eventIcon}</td>
        <td>${event.event_type.replace('_', ' ').toUpperCase()}</td>
        <td><code>${event.mac_address}</code></td>
        <td>${event.ip_address || '<span style="color: var(--text-muted);">N/A</span>'}</td>
        <td>${formatTimestamp(eventTime)}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (error) {
    console.error('Error loading network events:', error);
  }
}

// Helper function to format timestamps
function formatTimestamp(date) {
  const now = new Date();
  const diff = (now - date) / 1000; // seconds
  
  if (diff < 60) {
    return 'Just now';
  } else if (diff < 3600) {
    const mins = Math.floor(diff / 60);
    return `${mins} min${mins > 1 ? 's' : ''} ago`;
  } else if (diff < 86400) {
    const hours = Math.floor(diff / 3600);
    return `${hours} hour${hours > 1 ? 's' : ''} ago`;
  } else {
    return date.toLocaleString();
  }
}

// ============================================
// TOAST FALLBACK - Ensures showToast exists
// ============================================

if (typeof window.showToast !== "function") {
  window.showToast = function (msg, type = "info") {
    console.log(`[TOAST ${type.toUpperCase()}] ${msg}`);
    alert(`[${type}] ${msg}`);
  };
}

// Export functions to global scope
window.analyticsRefresh = analyticsRefresh;
window.analyticsLoadHealthScore = analyticsLoadHealthScore;
window.analyticsLoadDashboard = analyticsLoadDashboard;
window.analyticsShowAddService = analyticsShowAddService;
window.analyticsEditService = analyticsEditService;
window.analyticsDeleteService = analyticsDeleteService;
window.analyticsCloseServiceModal = analyticsCloseServiceModal;
window.analyticsToggleStatusCode = analyticsToggleStatusCode;
window.analyticsSaveService = analyticsSaveService;
window.analyticsResetHealth = analyticsResetHealth;
window.analyticsResetIncidents = analyticsResetIncidents;
window.analyticsResetServiceData = analyticsResetServiceData;
window.analyticsPurgeAll = analyticsPurgeAll;
window.analyticsPurgeWeek = analyticsPurgeWeek;
window.analyticsPurgeMonth = analyticsPurgeMonth;
window.networkRunScan = networkRunScan;
window.networkToggleMonitoring = networkToggleMonitoring;
window.networkTogglePermanent = networkTogglePermanent;
window.networkDeleteDevice = networkDeleteDevice;
window.networkToggleMonitoringMode = networkToggleMonitoringMode;
window.networkToggleAlerts = networkToggleAlerts;
window.networkEditDeviceName = networkEditDeviceName;
window.networkSaveDeviceName = networkSaveDeviceName;
window.analyticsLoadNetworkDashboard = analyticsLoadNetworkDashboard;
