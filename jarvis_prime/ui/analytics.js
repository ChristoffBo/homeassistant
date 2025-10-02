// Analytics Module for Jarvis Prime
// Handles all analytics UI interactions and API calls

// Use the API() helper from app.js for proper path resolution
const ANALYTICS_API = (path = '') => {
  if (typeof API === 'function') {
    // Always prefix with analytics, remove leading slashes from path
    return API('api/analytics/' + path.replace(/^\/+/, ''));
  }
  // Fallback: resolve against document.baseURI (Ingress-safe)
  const base = new URL(document.baseURI);
  return base.pathname.replace(/\/+$/, '') + '/api/analytics/' + path.replace(/^\/+/, '');
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

  card.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 12px;">
      <h3 style="margin: 0; font-size: 18px;">${service.service_name}</h3>
      <span style="padding: 4px 12px; background: ${statusColors[status]}22; color: ${statusColors[status]}; border-radius: 12px; font-size: 11px; font-weight: 600; text-transform: uppercase;">
        ${status}
      </span>
    </div>
    <div style="font-family: monospace; font-size: 13px; color: #60a5fa; margin-bottom: 8px;">
      ${service.endpoint}
    </div>
    <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 16px;">
      Last check: ${lastCheck} • ${service.check_type.toUpperCase()}
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
      const row = document.createElement('tr');
      const status = service.current_status || 'unknown';
      const statusColors = {
        up: '#22c55e',
        down: '#ef4444',
        degraded: '#f59e0b',
        unknown: '#6b7280'
      };
      
      row.innerHTML = `
        <td>${service.service_name}</td>
        <td style="font-family: monospace; font-size: 12px;">${service.endpoint}</td>
        <td>${service.check_type.toUpperCase()}</td>
        <td>${service.check_interval}s</td>
        <td>
          <span style="padding: 4px 12px; background: ${statusColors[status]}22; color: ${statusColors[status]}; border-radius: 12px; font-size: 11px; font-weight: 600; text-transform: uppercase;">
            ${status}
          </span>
        </td>
        <td>
          <span class="btn ${service.enabled ? 'primary' : ''}" style="padding: 4px 12px; font-size: 11px; cursor: default;">
            ${service.enabled ? 'Enabled' : 'Disabled'}
          </span>
        </td>
        <td>
          <div style="display: flex; gap: 8px;">
            <button class="btn" style="background: #fb923c; color: white;" onclick="analyticsEditService(${service.id})">Edit</button>
            <button class="btn danger" onclick="analyticsDeleteService(${service.id}, '${service.service_name}')">Delete</button>
          </div>
        </td>
      `;
      tbody.appendChild(row);
    });
  } catch (error) {
    console.error('Error loading services:', error);
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Error loading services</td></tr>';
  }
}

// Load incidents
async function analyticsLoadIncidents() {
  const list = document.getElementById('analytics-incidents-list');
  
  try {
    const response = await fetch(ANALYTICS_API('incidents?days=7'));
    const incidents = await response.json();

    if (incidents.length === 0) {
      list.innerHTML = `
        <div class="text-center text-muted">
          <div style="font-size: 48px; margin-bottom: 16px; opacity: 0.5;">✅</div>
          <p>No incidents in the last 7 days</p>
        </div>
      `;
      return;
    }

    list.innerHTML = '';
    
    incidents.forEach(incident => {
      const item = document.createElement('div');
      item.style.cssText = `
        background: var(--surface-secondary);
        border-left: 4px solid ${incident.status === 'resolved' ? '#22c55e' : '#ef4444'};
        border-radius: 6px;
        padding: 16px;
        margin-bottom: 12px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        ${incident.status === 'resolved' ? 'opacity: 0.7;' : ''}
      `;

      const startTime = new Date(incident.start_time * 1000).toLocaleString();
      const endTime = incident.end_time 
        ? new Date(incident.end_time * 1000).toLocaleString()
        : 'Ongoing';
      
      const duration = incident.duration 
        ? analyticsFormatDuration(incident.duration)
        : 'Ongoing';

      item.innerHTML = `
        <div style="flex: 1;">
          <div style="font-weight: 600; font-size: 16px; margin-bottom: 4px;">${incident.service_name}</div>
          <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 4px;">${startTime} → ${endTime}</div>
          <div style="font-size: 13px; color: #ef4444; font-family: monospace;">${incident.error_message || 'Unknown error'}</div>
        </div>
        <div style="padding: 6px 12px; background: var(--surface-tertiary); border-radius: 6px; font-size: 13px; font-weight: 500;">
          ⏱ ${duration}
        </div>
      `;
      
      list.appendChild(item);
    });
  } catch (error) {
    console.error('Error loading incidents:', error);
    list.innerHTML = '<div class="text-center text-muted">Error loading incidents</div>';
  }
}

// Format duration in seconds to human readable
function analyticsFormatDuration(seconds) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

// Show add service modal
function analyticsShowAddService() {
  document.getElementById('analytics-service-modal-title').textContent = 'Add Service';
  document.getElementById('analytics-service-form').reset();
  document.getElementById('analytics-service-id').value = '';
  document.getElementById('analytics-service-modal').classList.add('active');
  analyticsToggleStatusCode();
}

// Show edit service modal
async function analyticsEditService(id) {
  try {
    const response = await fetch(ANALYTICS_API(`services/${id}`));
    const service = await response.json();

    document.getElementById('analytics-service-modal-title').textContent = 'Edit Service';
    document.getElementById('analytics-service-id').value = service.id;
    document.getElementById('analytics-service-name').value = service.service_name;
    document.getElementById('analytics-service-endpoint').value = service.endpoint;
    document.getElementById('analytics-check-type').value = service.check_type;
    document.getElementById('analytics-expected-status').value = service.expected_status;
    document.getElementById('analytics-check-interval').value = service.check_interval;
    document.getElementById('analytics-check-timeout').value = service.timeout;
    document.getElementById('analytics-service-enabled').checked = service.enabled;

    analyticsToggleStatusCode();
    document.getElementById('analytics-service-modal').classList.add('active');
  } catch (error) {
    console.error('Error loading service:', error);
    showToast('Failed to load service', 'error');
  }
}

// Delete service
async function analyticsDeleteService(id, name) {
  if (!confirm(`Are you sure you want to delete ${name}?`)) return;

  try {
    await fetch(ANALYTICS_API(`services/${id}`), { method: 'DELETE' });
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

// Save service
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
    enabled: document.getElementById('analytics-service-enabled').checked
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