// Analytics Module for Jarvis Prime
// Handles all analytics UI interactions and API calls
// UPGRADED: Added retry and flap protection features
// PATCHED: analyticsLoadIncidents now handles { "incidents": [...] } format consistently
// UPGRADED: Added network monitoring capabilities
// FIXED: Line 327 - Changed incident.service to incident.service_name to match backend data
// ENHANCED: Completely redesigned incident display with card-based layout and better formatting
// ✨ NEW: Added Internet Speed Test monitoring

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
  } else if (tabName === 'internet') {
    analyticsLoadInternetDashboard();
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

  // Format average response time from service data
  let avgResponseDisplay = 'N/A';
  if (service.avg_response !== null && service.avg_response !== undefined) {
    const ms = parseFloat(service.avg_response);
    if (!isNaN(ms)) {
      avgResponseDisplay = ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(2)}s`;
    }
  }

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
          <div style="font-size: 18px; font-weight: 600;">${avgResponseDisplay}</div>
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

// Load services list
async function analyticsLoadServices() {
  const tbody = document.getElementById('analytics-services-list');
  
  try {
    const response = await fetch(ANALYTICS_API('services'));
    const services = await response.json();

    if (services.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" class="text-center text-muted">
            <div style="padding: 2rem;">
              <p>No services configured yet</p>
              <button class="btn primary" onclick="analyticsShowAddService()">Add Your First Service</button>
            </div>
          </td>
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

// Load incidents - COMPLETELY REDESIGNED with card layout
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
      const startTime = new Date(incident.start_time * 1000);
      const endTime = incident.end_time ? new Date(incident.end_time * 1000) : null;
      
      const duration = incident.duration 
        ? formatDurationDetailed(incident.duration)
        : 'Ongoing';

      const isOngoing = incident.status !== 'resolved';
      const statusColor = isOngoing ? '#ef4444' : '#22c55e';
      const statusIcon = isOngoing ? '🔴' : '✅';
      const statusText = isOngoing ? 'ONGOING' : 'RESOLVED';

      // Format timestamps more readably
      const startTimeFormatted = formatIncidentTime(startTime);
      const endTimeFormatted = endTime ? formatIncidentTime(endTime) : '<span style="color: var(--text-muted);">—</span>';

      // Get error message with better formatting
      const errorMsg = incident.error_message || 'Service unavailable';
      const truncatedError = errorMsg.length > 80 ? errorMsg.substring(0, 77) + '...' : errorMsg;

      tr.innerHTML = `
        <td style="padding: 16px 12px;">
          <div style="display: flex; align-items: center; gap: 12px;">
            <div style="font-size: 20px;">${statusIcon}</div>
            <div style="flex: 1;">
              <div style="font-weight: 600; font-size: 15px; margin-bottom: 4px; color: var(--text-primary);">
                ${incident.service_name || 'Unknown Service'}
              </div>
              <div style="font-size: 12px; color: var(--text-muted); font-family: monospace; line-height: 1.4;">
                ${truncatedError}
              </div>
            </div>
          </div>
        </td>
        <td style="padding: 16px 12px; min-width: 180px;">
          <div style="font-size: 13px; color: var(--text-primary); margin-bottom: 4px;">
            <strong>Started:</strong> ${startTimeFormatted}
          </div>
          ${endTime ? `
            <div style="font-size: 13px; color: var(--text-muted);">
              <strong>Ended:</strong> ${endTimeFormatted}
            </div>
          ` : ''}
        </td>
        <td style="padding: 16px 12px; text-align: center; min-width: 100px;">
          <div style="font-size: 18px; font-weight: 600; color: ${isOngoing ? '#ef4444' : '#22c55e'};">
            ${duration}
          </div>
          <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase; margin-top: 4px;">
            Duration
          </div>
        </td>
        <td style="padding: 16px 12px; text-align: center;">
          <span style="padding: 6px 14px; background: ${statusColor}15; color: ${statusColor}; border-radius: 8px; font-size: 11px; font-weight: 700; text-transform: uppercase; border: 1px solid ${statusColor}40;">
            ${statusText}
          </span>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (error) {
    console.error('Error loading incidents:', error);
    tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Error loading incidents</td></tr>';
  }
}

// Format duration with more detail
function formatDurationDetailed(seconds) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
  }
  if (seconds < 86400) {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
  }
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
}

// Format incident time for better readability
function formatIncidentTime(date) {
  const now = new Date();
  const diffMs = now - date;
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  // If within last 24 hours, show relative time
  if (diffDays < 1) {
    if (diffHours < 1) {
      if (diffMins < 1) return 'Just now';
      return `${diffMins}m ago`;
    }
    return `${diffHours}h ago`;
  }

  // Otherwise show formatted date/time
  const timeStr = date.toLocaleTimeString('en-US', { 
    hour: '2-digit', 
    minute: '2-digit',
    hour12: false 
  });
  
  if (diffDays < 7) {
    return `${diffDays}d ago at ${timeStr}`;
  }

  return date.toLocaleDateString('en-US', { 
    month: 'short', 
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  });
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
    showToast('Failed to load service details', 'error');
  }
}

// Delete service
async function analyticsDeleteService(serviceId, serviceName) {
  if (!confirm(`Delete service "${serviceName}"? This will also remove all metrics and incidents.`)) {
    return;
  }

  try {
    const response = await fetch(ANALYTICS_API(`services/${serviceId}`), {
      method: 'DELETE'
    });

    const result = await response.json();
    
    if (result.success) {
      showToast('Service deleted successfully', 'success');
      analyticsRefresh();
    } else {
      showToast('Failed to delete service', 'error');
    }
  } catch (error) {
    console.error('Error deleting service:', error);
    showToast('Failed to delete service', 'error');
  }
}

// Close service modal
function analyticsCloseServiceModal() {
  document.getElementById('analytics-service-modal').classList.remove('active');
}

// Toggle status code field visibility
function analyticsToggleStatusCode() {
  const checkType = document.getElementById('analytics-check-type').value;
  const statusCodeField = document.getElementById('analytics-status-code-field');
  statusCodeField.style.display = checkType === 'http' ? 'block' : 'none';
}

// Save service
async function analyticsSaveService(event) {
  event.preventDefault();

  const serviceId = document.getElementById('analytics-service-id').value;
  const serviceName = document.getElementById('analytics-service-name').value;
  const endpoint = document.getElementById('analytics-service-endpoint').value;
  const checkType = document.getElementById('analytics-check-type').value;
  const expectedStatus = document.getElementById('analytics-expected-status').value;
  const checkInterval = parseInt(document.getElementById('analytics-check-interval').value);
  const timeout = parseInt(document.getElementById('analytics-check-timeout').value);
  const enabled = document.getElementById('analytics-service-enabled').checked;
  
  // NEW: Collect retry and flap protection values
  const retries = parseInt(document.getElementById('analytics-retries').value);
  const flapWindow = parseInt(document.getElementById('analytics-flap-window').value);
  const flapThreshold = parseInt(document.getElementById('analytics-flap-threshold').value);
  const suppressionDuration = parseInt(document.getElementById('analytics-suppression-duration').value);

  const service = {
    service_name: serviceName,
    endpoint: endpoint,
    check_type: checkType,
    expected_status: checkType === 'http' ? parseInt(expectedStatus) : null,
    check_interval: checkInterval,
    timeout: timeout,
    enabled: enabled,
    retries: retries,
    flap_window: flapWindow,
    flap_threshold: flapThreshold,
    suppression_duration: suppressionDuration
  };

  try {
    let response;
    if (serviceId) {
      // Update existing service
      response = await fetch(ANALYTICS_API(`services/${serviceId}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(service)
      });
    } else {
      // Add new service
      response = await fetch(ANALYTICS_API('services'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(service)
      });
    }

    const result = await response.json();
    
    if (result.success) {
      showToast(serviceId ? 'Service updated successfully' : 'Service added successfully', 'success');
      analyticsCloseServiceModal();
      analyticsRefresh();
    } else {
      showToast(result.error || 'Failed to save service', 'error');
    }
  } catch (error) {
    console.error('Error saving service:', error);
    showToast('Failed to save service', 'error');
  }
}

// Reset health scores
async function analyticsResetHealth() {
  if (!confirm('Reset all health scores? This will clear service status history but keep the services.')) {
    return;
  }

  try {
    const response = await fetch(ANALYTICS_API('reset-health'), {
      method: 'POST'
    });
    
    const result = await response.json();
    
    if (result.success) {
      showToast('Health scores reset successfully', 'success');
      analyticsRefresh();
    } else {
      showToast('Failed to reset health scores', 'error');
    }
  } catch (error) {
    console.error('Error resetting health:', error);
    showToast('Failed to reset health scores', 'error');
  }
}

// Clear all incidents
async function analyticsResetIncidents() {
  if (!confirm('Clear all incidents from history?')) {
    return;
  }

  try {
    const response = await fetch(ANALYTICS_API('reset-incidents'), {
      method: 'POST'
    });
    
    const result = await response.json();
    
    if (result.success) {
      showToast(`Cleared ${result.deleted} incidents`, 'success');
      analyticsLoadIncidents();
    } else {
      showToast('Failed to clear incidents', 'error');
    }
  } catch (error) {
    console.error('Error clearing incidents:', error);
    showToast('Failed to clear incidents', 'error');
  }
}

// Reset specific service data
async function analyticsResetServiceData(serviceName) {
  if (!confirm(`Reset all data for ${serviceName}? This will clear metrics and incidents.`)) {
    return;
  }

  try {
    const response = await fetch(ANALYTICS_API(`reset-service/${encodeURIComponent(serviceName)}`), {
      method: 'POST'
    });
    
    const result = await response.json();
    
    if (result.success) {
      showToast('Service data reset successfully', 'success');
      analyticsRefresh();
    } else {
      showToast('Failed to reset service data', 'error');
    }
  } catch (error) {
    console.error('Error resetting service:', error);
    showToast('Failed to reset service data', 'error');
  }
}

// Purge all metrics
async function analyticsPurgeAll() {
  if (!confirm('⚠️ DANGER: Purge ALL metrics and incidents? This cannot be undone!')) return;

  try {
    const response = await fetch(ANALYTICS_API('purge-all'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    
    const result = await response.json();
    if (result.success) {
      showToast(`Purged ${result.deleted_metrics} metrics and ${result.deleted_incidents} incidents`, 'success');
      analyticsRefresh();
    } else {
      showToast('Failed to purge: ' + result.error, 'error');
    }
  } catch (error) {
    console.error('Error purging all:', error);
    showToast('Failed to purge data', 'error');
  }
}

// Purge week metrics
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

// Purge month metrics
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
            No devices found. Run a scan to discover devices on your network.
          </td>
        </tr>
      `;
      return;
    }

    networkDevices.forEach(device => {
      const tr = document.createElement('tr');
      
      const lastSeen = new Date(device.last_seen * 1000);
      const isOnline = (Date.now() / 1000 - device.last_seen) < 300; // 5 min threshold
      
      const onlineIndicator = isOnline 
        ? '<span style="color: #22c55e;">●</span>' 
        : '<span style="color: #6b7280;">●</span>';
      
      const permanentBadge = device.is_permanent 
        ? '<span class="badge badge-primary" style="font-size: 10px;">PERMANENT</span>' 
        : '';
      
      const monitoredBadge = device.is_monitored 
        ? '<span class="badge badge-success" style="font-size: 10px;">MONITORED</span>' 
        : '';

      tr.innerHTML = `
        <td>${onlineIndicator}</td>
        <td>
          <code style="font-size: 11px;">${device.mac_address}</code>
        </td>
        <td>
          <span id="device-name-${device.mac_address.replace(/:/g, '')}" style="cursor: pointer;" 
                onclick="networkEditDeviceName('${device.mac_address}')">
            ${device.custom_name || device.hostname || '<span style="color: var(--text-muted);">Unknown</span>'}
          </span>
        </td>
        <td>${device.ip_address || '<span style="color: var(--text-muted);">N/A</span>'}</td>
        <td style="font-size: 11px;">${device.vendor || '<span style="color: var(--text-muted);">Unknown</span>'}</td>
        <td style="font-size: 11px;">${formatTimestamp(lastSeen)}</td>
        <td>
          ${permanentBadge} ${monitoredBadge}
          <button class="btn btn-sm" 
                  onclick="networkTogglePermanent('${device.mac_address}')" 
                  title="${device.is_permanent ? 'Remove from permanent list' : 'Mark as permanent'}">
            ${device.is_permanent ? '📌' : '📍'}
          </button>
          <button class="btn btn-sm" 
                  onclick="networkToggleMonitoring('${device.mac_address}')" 
                  title="${device.is_monitored ? 'Stop monitoring' : 'Start monitoring'}">
            ${device.is_monitored ? '👁️' : '👁️‍🗨️'}
          </button>
          <button class="btn btn-sm" 
                  onclick="networkDeleteDevice('${device.mac_address}')" 
                  title="Delete device">
            🗑️
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (error) {
    console.error('Error loading network devices:', error);
  }
}

// Run network scan
async function networkRunScan() {
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = '⏳ Scanning...';
  
  try {
    const response = await fetch(ANALYTICS_API('network/scan'), {
      method: 'POST'
    });
    
    const result = await response.json();
    
    if (result.success) {
      showToast(`Found ${result.devices_found} devices (${result.new_devices} new)`, 'success');
      await analyticsLoadNetworkDashboard();
    } else {
      showToast('Scan failed: ' + result.error, 'error');
    }
  } catch (error) {
    console.error('Error running scan:', error);
    showToast('Scan failed', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '🔍 Scan Network';
  }
}

// Edit device name
function networkEditDeviceName(macAddress) {
  const device = networkDevices.find(d => d.mac_address === macAddress);
  if (!device) return;
  
  const currentName = device.custom_name || device.hostname || '';
  const newName = prompt('Enter device name:', currentName);
  
  if (newName !== null && newName !== currentName) {
    networkSaveDeviceName(macAddress, newName);
  }
}

// Save device name
async function networkSaveDeviceName(macAddress, customName) {
  try {
    const response = await fetch(ANALYTICS_API(`network/devices/${macAddress}`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ custom_name: customName })
    });
    
    const result = await response.json();
    
    if (result.success) {
      showToast('Device name updated', 'success');
      await analyticsLoadNetworkDevices();
    } else {
      showToast('Failed to update device name', 'error');
    }
  } catch (error) {
    console.error('Error updating device name:', error);
    showToast('Failed to update device name', 'error');
  }
}

// Toggle device monitoring
async function networkToggleMonitoring(macAddress) {
  const device = networkDevices.find(d => d.mac_address === macAddress);
  if (!device) return;
  
  const newState = !device.is_monitored;
  
  try {
    const response = await fetch(ANALYTICS_API(`network/devices/${macAddress}`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_monitored: newState })
    });
    
    const result = await response.json();
    
    if (result.success) {
      showToast(newState ? 'Monitoring enabled' : 'Monitoring disabled', 'success');
      await analyticsLoadNetworkDevices();
    } else {
      showToast('Failed to update monitoring', 'error');
    }
  } catch (error) {
    console.error('Error toggling monitoring:', error);
    showToast('Failed to update monitoring', 'error');
  }
}

// Toggle permanent device
async function networkTogglePermanent(macAddress) {
  const device = networkDevices.find(d => d.mac_address === macAddress);
  if (!device) return;
  
  const newState = !device.is_permanent;
  
  try {
    const response = await fetch(ANALYTICS_API(`network/devices/${macAddress}`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_permanent: newState })
    });
    
    const result = await response.json();
    
    if (result.success) {
      showToast(newState ? 'Marked as permanent' : 'Removed from permanent list', 'success');
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
// ✨ INTERNET SPEED TEST ADDITIONS
// ============================================

// Load internet speed test dashboard
async function analyticsLoadInternetDashboard() {
  console.log('Loading internet speed test dashboard...');
  
  try {
    const [statsResponse, latestResponse, statusResponse, scheduleResponse] = await Promise.all([
      fetch(ANALYTICS_API('speedtest/stats')),
      fetch(ANALYTICS_API('speedtest/latest')).catch(() => ({ ok: false })),
      fetch(ANALYTICS_API('speedtest/monitoring/status')),
      fetch(ANALYTICS_API('speedtest/schedule'))
    ]);
    
    const stats = await statsResponse.json();
    const status = await statusResponse.json();
    const schedule = await scheduleResponse.json();
    
    // Update stats
    document.getElementById('speed-avg-download').textContent = stats.recent_avg_download ? 
      stats.recent_avg_download.toFixed(1) + ' Mbps' : 'N/A';
    document.getElementById('speed-avg-upload').textContent = stats.recent_avg_upload ? 
      stats.recent_avg_upload.toFixed(1) + ' Mbps' : 'N/A';
    document.getElementById('speed-avg-ping').textContent = stats.recent_avg_ping ? 
      stats.recent_avg_ping.toFixed(1) + ' ms' : 'N/A';
    document.getElementById('speed-total-tests').textContent = stats.total_tests;
    
    // Display latest result
    if (latestResponse.ok) {
      const latest = await latestResponse.json();
      analyticsDisplayLatestSpeedTest(latest.test);
    } else {
      document.getElementById('speed-latest-result').innerHTML = 
        '<p style="text-align: center; color: #888;">No tests yet. Click "Run Test Now"</p>';
    }
    
    // Update schedule UI
    analyticsUpdateScheduleUI(schedule, status);
    
    // Update monitoring button
    const monitorBtn = document.getElementById('speed-monitoring-toggle');
    if (status.monitoring) {
      monitorBtn.textContent = '⏸️ Stop Auto-Testing';
      monitorBtn.classList.remove('btn-success');
      monitorBtn.classList.add('btn-warning');
    } else {
      monitorBtn.textContent = '▶️ Start Auto-Testing';
      monitorBtn.classList.remove('btn-warning');
      monitorBtn.classList.add('btn-success');
    }
    
    // Update test button state
    if (status.testing) {
      document.getElementById('speed-test-btn').disabled = true;
      document.getElementById('speed-test-btn').textContent = '⏳ Testing...';
    } else {
      document.getElementById('speed-test-btn').disabled = false;
      document.getElementById('speed-test-btn').textContent = '🚀 Run Test Now';
    }
    
    // Load history
    await analyticsLoadSpeedTestHistory();
    
  } catch (error) {
    console.error('Failed to load internet dashboard:', error);
    showToast('Failed to load internet dashboard', 'error');
  }
}

// Display latest speed test result
function analyticsDisplayLatestSpeedTest(test) {
  const resultDiv = document.getElementById('speed-latest-result');
  const timestamp = new Date(test.timestamp * 1000).toLocaleString();
  
  const statusClass = test.status === 'normal' ? 'status-up' : 
                     test.status === 'degraded' ? 'status-degraded' : 'status-down';
  
  const statusColor = test.status === 'normal' ? '#22c55e' : 
                      test.status === 'degraded' ? '#f59e0b' : '#ef4444';
  
  resultDiv.innerHTML = `
    <div style="padding: 2rem; background: linear-gradient(135deg, #1a1a1a 0%, #2a2a2a 100%); border-radius: 12px; border: 2px solid ${statusColor};">
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 2rem; margin-bottom: 1.5rem;">
        <div style="text-align: center;">
          <div style="font-size: 12px; color: #888; margin-bottom: 0.5rem;">DOWNLOAD</div>
          <div style="font-size: 2.5rem; font-weight: bold; color: ${statusColor};">
            ${test.download} <span style="font-size: 1rem; color: #888;">Mbps</span>
          </div>
        </div>
        <div style="text-align: center;">
          <div style="font-size: 12px; color: #888; margin-bottom: 0.5rem;">UPLOAD</div>
          <div style="font-size: 2.5rem; font-weight: bold; color: ${statusColor};">
            ${test.upload} <span style="font-size: 1rem; color: #888;">Mbps</span>
          </div>
        </div>
        <div style="text-align: center;">
          <div style="font-size: 12px; color: #888; margin-bottom: 0.5rem;">PING</div>
          <div style="font-size: 2.5rem; font-weight: bold; color: ${statusColor};">
            ${test.ping} <span style="font-size: 1rem; color: #888;">ms</span>
          </div>
        </div>
      </div>
      <div style="padding-top: 1rem; border-top: 1px solid #333; font-size: 12px; color: #888;">
        <div style="margin-bottom: 0.5rem;"><strong>Server:</strong> ${test.server}</div>
        <div style="margin-bottom: 0.5rem;"><strong>Time:</strong> ${timestamp}</div>
        ${test.jitter ? `<div style="margin-bottom: 0.5rem;"><strong>Jitter:</strong> ${test.jitter} ms</div>` : ''}
        ${test.packet_loss ? `<div><strong>Packet Loss:</strong> ${test.packet_loss}%</div>` : ''}
      </div>
    </div>
  `;
}

// Run speed test
async function analyticsRunSpeedTest() {
  const btn = document.getElementById('speed-test-btn');
  btn.disabled = true;
  btn.textContent = '⏳ Testing...';
  
  showToast('Speed test started (may take 30-60 seconds)...', 'info');
  
  try {
    const response = await fetch(ANALYTICS_API('speedtest/run'), {
      method: 'POST'
    });
    
    if (response.ok) {
      const data = await response.json();
      showToast('Speed test completed', 'success');
      analyticsLoadInternetDashboard();
    } else {
      const error = await response.json();
      showToast(error.error || 'Speed test failed', 'error');
    }
  } catch (error) {
    console.error('Speed test error:', error);
    showToast('Speed test failed', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '🚀 Run Test Now';
  }
}

// Toggle speed test monitoring
async function analyticsToggleSpeedMonitoring() {
  const btn = document.getElementById('speed-monitoring-toggle');
  const isCurrentlyMonitoring = btn.textContent.includes('Stop');
  
  try {
    const endpoint = isCurrentlyMonitoring ? 
      'speedtest/monitoring/stop' : 
      'speedtest/monitoring/start';
    
    // Get current schedule settings
    const scheduleResponse = await fetch(ANALYTICS_API('speedtest/schedule'));
    const schedule = await scheduleResponse.json();
    
    const response = await fetch(ANALYTICS_API(endpoint), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(schedule)
    });
    
    if (response.ok) {
      const mode = schedule.schedule_mode === 'interval' ? 
        `${schedule.interval_hours}h interval` : 
        `scheduled at ${schedule.schedule_times.join(', ')}`;
      showToast(isCurrentlyMonitoring ? 'Auto-testing stopped' : `Auto-testing started (${mode})`, 'success');
      analyticsLoadInternetDashboard();
    } else {
      showToast('Failed to toggle auto-testing', 'error');
    }
  } catch (error) {
    console.error('Failed to toggle monitoring:', error);
    showToast('Failed to toggle auto-testing', 'error');
  }
}

// Update schedule UI based on settings
function analyticsUpdateScheduleUI(schedule, status) {
  const mode = schedule.schedule_mode || 'interval';
  
  // Update mode buttons
  const intervalBtn = document.getElementById('schedule-mode-interval');
  const scheduledBtn = document.getElementById('schedule-mode-scheduled');
  
  if (intervalBtn && scheduledBtn) {
    intervalBtn.classList.toggle('active', mode === 'interval');
    scheduledBtn.classList.toggle('active', mode === 'scheduled');
  }
  
  // Show/hide appropriate controls
  const intervalControls = document.getElementById('interval-controls');
  const scheduledControls = document.getElementById('scheduled-controls');
  
  if (intervalControls && scheduledControls) {
    intervalControls.style.display = mode === 'interval' ? 'block' : 'none';
    scheduledControls.style.display = mode === 'scheduled' ? 'block' : 'none';
  }
  
  // Update interval slider
  const intervalSlider = document.getElementById('interval-hours');
  const intervalValue = document.getElementById('interval-value');
  if (intervalSlider && intervalValue) {
    intervalSlider.value = schedule.interval_hours || 12;
    intervalValue.textContent = `${schedule.interval_hours || 12} hours`;
  }
  
  // Update scheduled times list
  analyticsDisplayScheduledTimes(schedule.schedule_times || []);
}

// Display scheduled times
function analyticsDisplayScheduledTimes(times) {
  const container = document.getElementById('scheduled-times-list');
  if (!container) return;
  
  if (times.length === 0) {
    container.innerHTML = '<p style="color: #888; text-align: center;">No times scheduled</p>';
    return;
  }
  
  container.innerHTML = times.map(time => `
    <div style="display: flex; align-items: center; justify-content: space-between; padding: 0.5rem; background: #2a2a2a; border-radius: 4px; margin-bottom: 0.5rem;">
      <span style="font-size: 1.1rem; font-weight: 500;">${time}</span>
      <button onclick="analyticsRemoveScheduledTime('${time}')" class="btn btn-sm btn-danger" style="padding: 0.25rem 0.5rem;">✕</button>
    </div>
  `).join('');
}

// Switch schedule mode
async function analyticsSwitchScheduleMode(mode) {
  try {
    const response = await fetch(ANALYTICS_API('speedtest/schedule'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schedule_mode: mode })
    });
    
    if (response.ok) {
      showToast(`Switched to ${mode} mode`, 'success');
      analyticsLoadInternetDashboard();
    } else {
      showToast('Failed to switch mode', 'error');
    }
  } catch (error) {
    console.error('Failed to switch schedule mode:', error);
    showToast('Failed to switch mode', 'error');
  }
}

// Update interval hours
async function analyticsUpdateInterval() {
  const slider = document.getElementById('interval-hours');
  const hours = parseInt(slider.value);
  
  try {
    const response = await fetch(ANALYTICS_API('speedtest/schedule'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ interval_hours: hours })
    });
    
    if (response.ok) {
      document.getElementById('interval-value').textContent = `${hours} hours`;
      showToast(`Interval updated to ${hours} hours`, 'success');
    } else {
      showToast('Failed to update interval', 'error');
    }
  } catch (error) {
    console.error('Failed to update interval:', error);
    showToast('Failed to update interval', 'error');
  }
}

// Add scheduled time
async function analyticsAddScheduledTime() {
  const input = document.getElementById('scheduled-time-input');
  const time = input.value;
  
  if (!time) {
    showToast('Please select a time', 'error');
    return;
  }
  
  try {
    // Get current schedule
    const scheduleResponse = await fetch(ANALYTICS_API('speedtest/schedule'));
    const schedule = await scheduleResponse.json();
    
    // Add new time if not already exists
    if (!schedule.schedule_times.includes(time)) {
      schedule.schedule_times.push(time);
      schedule.schedule_times.sort();
      
      const response = await fetch(ANALYTICS_API('speedtest/schedule'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schedule_times: schedule.schedule_times })
      });
      
      if (response.ok) {
        showToast(`Added ${time} to schedule`, 'success');
        input.value = '';
        analyticsLoadInternetDashboard();
      } else {
        showToast('Failed to add time', 'error');
      }
    } else {
      showToast('Time already scheduled', 'error');
    }
  } catch (error) {
    console.error('Failed to add scheduled time:', error);
    showToast('Failed to add time', 'error');
  }
}

// Remove scheduled time
async function analyticsRemoveScheduledTime(time) {
  try {
    // Get current schedule
    const scheduleResponse = await fetch(ANALYTICS_API('speedtest/schedule'));
    const schedule = await scheduleResponse.json();
    
    // Remove time
    schedule.schedule_times = schedule.schedule_times.filter(t => t !== time);
    
    const response = await fetch(ANALYTICS_API('speedtest/schedule'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schedule_times: schedule.schedule_times })
    });
    
    if (response.ok) {
      showToast(`Removed ${time} from schedule`, 'success');
      analyticsLoadInternetDashboard();
    } else {
      showToast('Failed to remove time', 'error');
    }
  } catch (error) {
    console.error('Failed to remove scheduled time:', error);
    showToast('Failed to remove time', 'error');
  }
}

// Load speed test history
async function analyticsLoadSpeedTestHistory() {
  try {
    const response = await fetch(ANALYTICS_API('speedtest/history?hours=168'));
    const data = await response.json();
    
    analyticsRenderSpeedTestHistory(data.tests);
    
  } catch (error) {
    console.error('Failed to load speed test history:', error);
  }
}

// Render speed test history table
function analyticsRenderSpeedTestHistory(tests) {
  const tbody = document.getElementById('speed-history-tbody');
  tbody.innerHTML = '';
  
  if (tests.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 2rem; color: #888;">No test history. Run a test to get started.</td></tr>';
    return;
  }
  
  tests.slice(0, 20).forEach(test => {
    const tr = document.createElement('tr');
    const timestamp = new Date(test.timestamp * 1000).toLocaleString();
    
    const statusColor = test.status === 'normal' ? '#22c55e' : 
                       test.status === 'degraded' ? '#f59e0b' : '#ef4444';
    
    tr.innerHTML = `
      <td style="font-size: 12px;">${timestamp}</td>
      <td style="font-weight: 600; color: ${statusColor};">${test.download} Mbps</td>
      <td style="font-weight: 600; color: ${statusColor};">${test.upload} Mbps</td>
      <td>${test.ping} ms</td>
      <td>
        <span style="padding: 4px 8px; background: ${statusColor}22; color: ${statusColor}; border-radius: 6px; font-size: 10px; font-weight: 600; text-transform: uppercase;">
          ${test.status}
        </span>
      </td>
      <td style="font-size: 11px; color: #888;">${test.server}</td>
    `;
    
    tbody.appendChild(tr);
  });
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
window.analyticsLoadInternetDashboard = analyticsLoadInternetDashboard;
window.analyticsRunSpeedTest = analyticsRunSpeedTest;
window.analyticsToggleSpeedMonitoring = analyticsToggleSpeedMonitoring;
