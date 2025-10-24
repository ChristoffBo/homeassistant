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

  const serviceId = document.getEl