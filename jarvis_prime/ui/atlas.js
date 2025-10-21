// /share/jarvis_prime/ui/js/atlas.js
// Atlas Module for Jarvis Prime — PROFESSIONAL ENTERPRISE EDITION
// With click-to-open WebUI support

const ATLAS_API = (path = '') => {
  if (typeof API === 'function') {
    return API('api/atlas/' + path.replace(/^\/+/, ''));
  }
  return '/api/atlas/' + path.replace(/^\/+/, '');
};

document.addEventListener('DOMContentLoaded', () => {
  const atlasTab = document.getElementById('atlas');
  if (!atlasTab) return;

  setInterval(() => {
    if (atlasTab.classList.contains('active')) atlasRender();
  }, 45000);

  atlasRender();
});

async function atlasRender() {
  const container = document.getElementById('atlas-view');
  if (!container) return;

  try {
    const res = await fetch(ATLAS_API('topology'));
    if (!res.ok) throw new Error('Failed to fetch topology');
    const data = await res.json();
    drawAtlasGraph(container, data);
  } catch (err) {
    console.error('[atlas] render failed:', err);
    container.innerHTML = `<div class="text-center text-muted" style="padding:24px;">Error loading topology</div>`;
  }
}

function drawAtlasGraph(container, data) {
  container.innerHTML = '';
  if (!data?.nodes) {
    container.innerHTML = `<div class="text-center text-muted" style="padding:24px;">No topology data</div>`;
    return;
  }

  const width = container.clientWidth;
  const height = container.clientHeight || 600;

  // Professional enterprise colors
  const COLORS = {
    background: '#1a1f2e',
    gridLines: '#2a3342',
    linkNormal: '#3a4556',
    linkActive: '#5294e2',
    core: '#5294e2',        // Professional blue
    hostOnline: '#2ecc71',  // Clean green
    hostOffline: '#95a5a6', // Neutral gray
    serviceFast: '#27ae60', // Fast < 0.5s
    serviceMed: '#f39c12',  // Medium 0.5-2s
    serviceSlow: '#e74c3c', // Slow > 2s
    serviceDown: '#c0392b',
    text: '#e8eaed',
    textMuted: '#95a5a6',
    tooltipBg: 'rgba(26, 31, 46, 0.98)',
    tooltipBorder: '#3a4556',
    webui: '#3498db',       // Blue for open WebUI
    webuiAuth: '#9b59b6'    // Purple for auth-required
  };

  const svg = d3.select(container)
    .append('svg')
    .attr('width', '100%')
    .attr('height', '100%')
    .attr('viewBox', [0, 0, width, height])
    .style('background', COLORS.background)
    .style('border-radius', '8px');

  // Add subtle grid pattern
  const defs = svg.append('defs');
  const pattern = defs.append('pattern')
    .attr('id', 'grid')
    .attr('width', 40)
    .attr('height', 40)
    .attr('patternUnits', 'userSpaceOnUse');
  
  pattern.append('path')
    .attr('d', 'M 40 0 L 0 0 0 40')
    .attr('fill', 'none')
    .attr('stroke', COLORS.gridLines)
    .attr('stroke-width', 0.5)
    .attr('opacity', 0.3);

  svg.append('rect')
    .attr('width', '100%')
    .attr('height', '100%')
    .attr('fill', 'url(#grid)');

  const g = svg.append('g');
  
  svg.call(
    d3.zoom()
      .scaleExtent([0.5, 4])
      .on('zoom', (event) => g.attr('transform', event.transform))
  );

  // Links with better styling
  const link = g.append('g')
    .selectAll('line')
    .data(data.links)
    .join('line')
    .attr('stroke', COLORS.linkNormal)
    .attr('stroke-opacity', 0.6)
    .attr('stroke-width', 1.5);

  // Enhanced color function
  const getNodeColor = (d) => {
    if (d.type === 'core') return COLORS.core;
    
    if (d.type === 'host') {
      return d.alive ? COLORS.hostOnline : COLORS.hostOffline;
    }
    
    if (d.type === 'service') {
      const status = (d.status || '').toLowerCase();
      if (status === 'down' || status === 'fail') return COLORS.serviceDown;
      
      if (d.latency) {
        if (d.latency > 2) return COLORS.serviceSlow;
        if (d.latency > 0.5) return COLORS.serviceMed;
        return COLORS.serviceFast;
      }
      
      return d.alive ? COLORS.serviceFast : COLORS.hostOffline;
    }
    
    return COLORS.hostOffline;
  };

  // Node size based on type
  const getNodeSize = (d) => {
    if (d.type === 'core') return 20;
    if (d.type === 'host') return 14;
    return 9;
  };

  // Node group for nodes + WebUI indicators
  const nodeGroup = g.append('g')
    .selectAll('g')
    .data(data.nodes)
    .join('g')
    .style('cursor', d => d.has_webui ? 'pointer' : 'default')
    .on('mouseover', (event, d) => {
      showAtlasTooltip(event, d);
      hoverGroup(d, nodeGroup, link, label);
      d3.select(event.currentTarget).select('circle')
        .attr('stroke', COLORS.linkActive)
        .attr('stroke-width', 3)
        .style('filter', 'drop-shadow(0 0 8px rgba(82, 148, 226, 0.6))');
    })
    .on('mouseout', (event, d) => {
      hideAtlasTooltip();
      resetHover(nodeGroup, link, label);
      d3.select(event.currentTarget).select('circle')
        .attr('stroke', '#1a1f2e')
        .attr('stroke-width', 2)
        .style('filter', 'none');
    })
    .on('click', (event, d) => {
      event.stopPropagation();
      if (d.has_webui && d.webui_url) {
        window.open(d.webui_url, '_blank', 'noopener,noreferrer');
      } else {
        focusNode(d, nodeGroup, link, label);
      }
    });

  // Main node circle
  nodeGroup.append('circle')
    .attr('r', getNodeSize)
    .attr('fill', getNodeColor)
    .attr('stroke', '#1a1f2e')
    .attr('stroke-width', 2);

  // WebUI indicator - professional glow ring
  const webuiRing = nodeGroup.filter(d => d.has_webui)
    .append('circle')
    .attr('r', d => getNodeSize(d) + 4)
    .attr('fill', 'none')
    .attr('stroke', d => d.requires_auth ? '#9b59b6' : '#3498db')
    .attr('stroke-width', 2)
    .attr('stroke-dasharray', '3,3')
    .attr('opacity', 0.8)
    .style('cursor', 'pointer')
    .style('filter', d => {
      const color = d.requires_auth ? '155, 89, 182' : '52, 152, 219';
      return `drop-shadow(0 0 4px rgba(${color}, 0.6))`;
    });

  // Animate the ring
  webuiRing
    .transition()
    .duration(2000)
    .ease(d3.easeCubicInOut)
    .attr('stroke-dashoffset', -12)
    .on('end', function repeat() {
      d3.select(this)
        .transition()
        .duration(2000)
        .attr('stroke-dashoffset', -24)
        .on('end', repeat);
    });

  // Labels with better readability
  const label = g.append('g')
    .selectAll('text')
    .data(data.nodes)
    .join('text')
    .text(d => d.id)
    .attr('fill', COLORS.text)
    .attr('font-size', d => d.type === 'core' ? 13 : 11)
    .attr('font-weight', d => d.type === 'core' ? 600 : 400)
    .attr('text-anchor', 'middle')
    .attr('pointer-events', 'none')
    .style('text-shadow', '0 1px 4px rgba(0,0,0,0.8)');

  // Force simulation with better spacing
  const sim = d3.forceSimulation(data.nodes)
    .force('link', d3.forceLink(data.links).id(d => d.id).distance(150).strength(0.5))
    .force('charge', d3.forceManyBody().strength(-600))
    .force('collide', d3.forceCollide(45))
    .force('core', d3.forceRadial(0, width / 2, height / 2).strength(d => d.type === 'core' ? 0.6 : 0))
    .force('hosts', d3.forceRadial(180, width / 2, height / 2).strength(d => d.type === 'host' ? 0.3 : 0))
    .force('services', d3.forceRadial(320, width / 2, height / 2).strength(d => d.type === 'service' ? 0.2 : 0))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .velocityDecay(0.3);

  sim.on('tick', () => {
    link
      .attr('x1', d => d.source.x)
      .attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x)
      .attr('y2', d => d.target.y);

    nodeGroup.attr('transform', d => `translate(${d.x},${d.y})`);

    label
      .attr('x', d => d.x)
      .attr('y', d => d.y - (d.type === 'core' ? 24 : d.type === 'host' ? 20 : 16));
  });

  // Subtle pulse for alive nodes only
  nodeGroup.filter(d => d.alive)
    .select('circle:first-child')
    .transition()
    .duration(2500)
    .ease(d3.easeCubicInOut)
    .attr('r', d => getNodeSize(d) + 2)
    .transition()
    .duration(2500)
    .attr('r', getNodeSize)
    .on('end', function repeat() {
      d3.select(this)
        .transition()
        .duration(2500)
        .attr('r', d => getNodeSize(d) + 2)
        .transition()
        .duration(2500)
        .attr('r', getNodeSize)
        .on('end', repeat);
    });

  // Professional stats overlay
  const overlay = document.createElement('div');
  overlay.style.cssText = `
    position: absolute;
    top: 12px;
    right: 12px;
    background: ${COLORS.tooltipBg};
    backdrop-filter: blur(10px);
    border: 1px solid ${COLORS.tooltipBorder};
    color: ${COLORS.text};
    padding: 10px 14px;
    border-radius: 8px;
    font-size: 12px;
    line-height: 1.6;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  `;
  
  const avgLat = data.latency_stats?.avg;
  const webuiCount = data.counts?.webui_enabled || 0;
  
  overlay.innerHTML = `
    <div style="font-weight: 600; margin-bottom: 8px; font-size: 13px;">Network Topology</div>
    <div style="display: grid; grid-template-columns: auto auto; gap: 4px 12px; font-size: 11px;">
      <span style="color: ${COLORS.textMuted};">Hosts:</span>
      <span style="font-weight: 500;">${data.counts?.hosts || 0}</span>
      <span style="color: ${COLORS.textMuted};">Services:</span>
      <span style="font-weight: 500;">${data.counts?.services || 0}</span>
      <span style="color: ${COLORS.textMuted};">Links:</span>
      <span style="font-weight: 500;">${data.counts?.total_links || 0}</span>
      <span style="color: ${COLORS.textMuted};">WebUI:</span>
      <span style="font-weight: 500;">${webuiCount}</span>
      ${avgLat ? `
        <span style="color: ${COLORS.textMuted};">Avg Latency:</span>
        <span style="font-weight: 500;">${avgLat.toFixed(2)}s</span>
      ` : ''}
    </div>
    <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid ${COLORS.tooltipBorder}; font-size: 10px;">
      <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 3px;">
        <div style="width: 10px; height: 10px; border-radius: 50%; background: ${COLORS.serviceFast};"></div>
        <span style="color: ${COLORS.textMuted};">Fast (&lt;0.5s)</span>
      </div>
      <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 3px;">
        <div style="width: 10px; height: 10px; border-radius: 50%; background: ${COLORS.serviceMed};"></div>
        <span style="color: ${COLORS.textMuted};">Medium (0.5-2s)</span>
      </div>
      <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 3px;">
        <div style="width: 10px; height: 10px; border-radius: 50%; background: ${COLORS.serviceSlow};"></div>
        <span style="color: ${COLORS.textMuted};">Slow (&gt;2s)</span>
      </div>
      <div style="display: flex; align-items: center; gap: 6px;">
        <div style="position: relative; width: 18px; height: 18px;">
          <div style="position: absolute; left: 4px; top: 4px; width: 10px; height: 10px; border-radius: 50%; background: #2ecc71;"></div>
          <div style="position: absolute; left: 2px; top: 2px; width: 14px; height: 14px; border-radius: 50%; border: 2px dashed ${COLORS.webui}; opacity: 0.8;"></div>
        </div>
        <span style="color: ${COLORS.textMuted};">WebUI Available</span>
      </div>
      <div style="display: flex; align-items: center; gap: 6px;">
        <div style="position: relative; width: 18px; height: 18px;">
          <div style="position: absolute; left: 4px; top: 4px; width: 10px; height: 10px; border-radius: 50%; background: #2ecc71;"></div>
          <div style="position: absolute; left: 2px; top: 2px; width: 14px; height: 14px; border-radius: 50%; border: 2px dashed ${COLORS.webuiAuth}; opacity: 0.8;"></div>
        </div>
        <span style="color: ${COLORS.textMuted};">Auth Required</span>
      </div>
    </div>
  `;
  container.appendChild(overlay);

  // Reset on click
  svg.on('click', () => {
    nodeGroup.select('circle:first-child')
      .attr('stroke', '#1a1f2e')
      .attr('stroke-width', 2)
      .style('filter', 'none');
    link
      .attr('stroke', COLORS.linkNormal)
      .attr('stroke-opacity', 0.6);
    label.attr('opacity', 1);
  });
}

// Focus mode - professional highlighting
function focusNode(target, nodeGroup, link, label) {
  const connected = new Set();
  link.each(l => {
    if (l.source.id === target.id) connected.add(l.target.id);
    if (l.target.id === target.id) connected.add(l.source.id);
  });
  connected.add(target.id);
  
  nodeGroup.attr('opacity', d => (connected.has(d.id) ? 1 : 0.2));
  label.attr('opacity', d => (connected.has(d.id) ? 1 : 0.2));
  link
    .attr('stroke', d => {
      const isConnected = d.source.id === target.id || d.target.id === target.id;
      return isConnected ? '#5294e2' : '#3a4556';
    })
    .attr('stroke-opacity', d => {
      const isConnected = d.source.id === target.id || d.target.id === target.id;
      return isConnected ? 1 : 0.15;
    })
    .attr('stroke-width', d => {
      const isConnected = d.source.id === target.id || d.target.id === target.id;
      return isConnected ? 2.5 : 1.5;
    });
}

// Hover mode - subtle highlight
function hoverGroup(target, nodeGroup, link, label) {
  const connected = new Set();
  link.each(l => {
    if (l.source.id === target.id) connected.add(l.target.id);
    if (l.target.id === target.id) connected.add(l.source.id);
  });
  connected.add(target.id);
  
  nodeGroup.attr('opacity', d => (connected.has(d.id) ? 1 : 0.4));
  label.attr('opacity', d => (connected.has(d.id) ? 1 : 0.4));
  link
    .attr('stroke', d => {
      const isConnected = d.source.id === target.id || d.target.id === target.id;
      return isConnected ? '#5294e2' : '#3a4556';
    })
    .attr('stroke-opacity', d => {
      const isConnected = d.source.id === target.id || d.target.id === target.id;
      return isConnected ? 0.9 : 0.3;
    });
}

function resetHover(nodeGroup, link, label) {
  nodeGroup.attr('opacity', 1);
  link
    .attr('stroke', '#3a4556')
    .attr('stroke-opacity', 0.6);
  label.attr('opacity', 1);
}

// Professional tooltip with WebUI indication
let atlasTooltip;
function showAtlasTooltip(event, d) {
  hideAtlasTooltip();
  
  atlasTooltip = document.createElement('div');
  atlasTooltip.style.cssText = `
    position: fixed;
    left: ${event.pageX + 12}px;
    top: ${event.pageY + 12}px;
    background: rgba(26, 31, 46, 0.98);
    backdrop-filter: blur(10px);
    border: 1px solid #3a4556;
    border-radius: 8px;
    padding: 10px 14px;
    color: #e8eaed;
    font-size: 12px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    z-index: 9999;
    pointer-events: none;
    box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    line-height: 1.5;
  `;
  
  const statusColor = d.alive ? '#2ecc71' : '#95a5a6';
  const latencyColor = !d.latency ? '#95a5a6' : 
                       d.latency > 2 ? '#e74c3c' : 
                       d.latency > 0.5 ? '#f39c12' : '#27ae60';
  
  let html = `
    <div style="font-weight: 600; margin-bottom: 6px; font-size: 13px;">${d.id}</div>
    <div style="display: grid; grid-template-columns: auto auto; gap: 4px 10px; font-size: 11px;">
      <span style="color: #95a5a6;">Type:</span>
      <span>${d.type}</span>
  `;
  
  if (d.ip) {
    html += `
      <span style="color: #95a5a6;">IP:</span>
      <span style="font-family: monospace;">${d.ip}</span>
    `;
  }
  
  if (d.group) {
    html += `
      <span style="color: #95a5a6;">Group:</span>
      <span>${d.group}</span>
    `;
  }
  
  if (d.status) {
    html += `
      <span style="color: #95a5a6;">Status:</span>
      <span style="color: ${statusColor}; font-weight: 500;">${d.status}</span>
    `;
  }
  
  if (d.latency) {
    html += `
      <span style="color: #95a5a6;">Latency:</span>
      <span style="color: ${latencyColor}; font-weight: 500;">${d.latency.toFixed(3)}s</span>
    `;
  }
  
  if (d.has_webui) {
    html += `
      <span style="color: #95a5a6;">WebUI:</span>
      <span style="color: #3498db; font-weight: 500;">
        ${d.requires_auth ? '🔒 ' : ''}Click to open
      </span>
    `;
  }
  
  html += `</div>`;
  
  if (d.description) {
    html += `<div style="margin-top: 6px; padding-top: 6px; border-top: 1px solid #3a4556; font-size: 11px; color: #95a5a6;">${d.description}</div>`;
  }
  
  atlasTooltip.innerHTML = html;
  document.body.appendChild(atlasTooltip);
}

function hideAtlasTooltip() {
  if (atlasTooltip) {
    atlasTooltip.remove();
    atlasTooltip = null;
  }
}
