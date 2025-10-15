// /share/jarvis_prime/ui/js/atlas.js
// Atlas Module for Jarvis Prime — Enhanced Visualization + Focus + Group Hover + Night Bloom
// Groups by node type, color-codes by latency, pulses alive nodes, includes legend, focus mode, and hover glow.

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
  }, 45000); // refresh every 45s (was 15s)

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

  const svg = d3.select(container)
    .append('svg')
    .attr('width', '100%')
    .attr('height', '100%')
    .attr('viewBox', [0, 0, width, height])
    .style('background', 'radial-gradient(circle at center, #0b0c10 0%, #000 100%)')
    .style('border-radius', '12px');

  const g = svg.append('g');
  svg.call(
    d3.zoom()
      .scaleExtent([0.5, 4])
      .on('zoom', (event) => g.attr('transform', event.transform))
  );

  const link = g.append('g')
    .attr('stroke', '#444')
    .attr('stroke-opacity', 0.4)
    .selectAll('line')
    .data(data.links)
    .join('line')
    .attr('stroke-width', 1.3);

  const latencyColor = (d) => {
    if (d.type === 'core') return '#00bcd4';
    if (!d.latency) return d.color || '#999';
    if (d.latency > 2) return '#e53935';
    if (d.latency > 0.5) return '#ffb300';
    return '#00c853';
  };

  const node = g.append('g')
    .selectAll('circle')
    .data(data.nodes)
    .join('circle')
    .attr('r', d => d.type === 'core' ? 18 : d.type === 'host' ? 13 : 8)
    .attr('fill', latencyColor)
    .attr('stroke', '#111')
    .attr('stroke-width', 1.5)
    .style('cursor', 'pointer')
    .on('mouseover', (event, d) => {
      showAtlasTooltip(event, d);
      hoverGroup(d, node, link, label);
      d3.select(event.currentTarget)
        .style('filter', 'drop-shadow(0 0 6px #00bcd4)');
    })
    .on('mouseout', (event, d) => {
      hideAtlasTooltip();
      resetHover(node, link, label);
      d3.select(event.currentTarget).style('filter', 'none');
    })
    .on('click', (event, d) => {
      event.stopPropagation();
      focusNode(d, node, link, label);
    });

  const label = g.append('g')
    .selectAll('text')
    .data(data.nodes)
    .join('text')
    .text(d => d.id)
    .attr('fill', '#ccc')
    .attr('font-size', 11)
    .attr('text-anchor', 'middle')
    .attr('pointer-events', 'none')
    .style('text-shadow', '0 0 2px #000');

  const sim = d3.forceSimulation(data.nodes)
    .force('link', d3.forceLink(data.links).id(d => d.id).distance(140).strength(0.4))
    .force('charge', d3.forceManyBody().strength(-480))
    .force('collide', d3.forceCollide(40))
    .force('core', d3.forceRadial(0, width / 2, height / 2).strength(d => d.type === 'core' ? 0.5 : 0))
    .force('hosts', d3.forceRadial(160, width / 2, height / 2).strength(d => d.type === 'host' ? 0.25 : 0))
    .force('services', d3.forceRadial(300, width / 2, height / 2).strength(d => d.type === 'service' ? 0.15 : 0))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .velocityDecay(0.25);

  sim.on('tick', () => {
    link
      .attr('x1', d => d.source.x)
      .attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x)
      .attr('y2', d => d.target.y);

    node
      .attr('cx', d => d.x)
      .attr('cy', d => d.y);

    label
      .attr('x', d => d.x)
      .attr('y', d => d.y - 18);
  });

  // Pulse animation for alive nodes
  node.filter(d => d.alive)
    .transition()
    .duration(2000)
    .ease(d3.easeCubic)
    .attr('r', d => d.type === 'core' ? 20 : d.type === 'host' ? 15 : 9)
    .transition()
    .duration(2000)
    .attr('r', d => d.type === 'core' ? 18 : d.type === 'host' ? 13 : 8)
    .on('end', function repeat() {
      d3.select(this)
        .transition()
        .duration(2000)
        .attr('r', d => d.type === 'core' ? 20 : d.type === 'host' ? 15 : 9)
        .transition()
        .duration(2000)
        .attr('r', d => d.type === 'core' ? 18 : d.type === 'host' ? 13 : 8)
        .on('end', repeat);
    });

  // Legend & counts overlay
  const overlay = document.createElement('div');
  overlay.className = 'atlas-overlay';
  overlay.style.cssText = `
    position: absolute;
    bottom: 10px;
    right: 10px;
    background: rgba(0,0,0,0.6);
    color: #ccc;
    padding: 6px 10px;
    border-radius: 8px;
    font-size: 12px;
    line-height: 1.4;
  `;
  overlay.innerHTML = `
    <div><b>Legend:</b></div>
    <div>🟢 Fast</div>
    <div>🟡 Medium</div>
    <div>🔴 Slow</div>
    <div>🔵 Core</div>
    <hr style="border:0;border-top:1px solid #333;margin:4px 0;">
    <div>Hosts: ${data.counts?.hosts || 0}</div>
    <div>Services: ${data.counts?.services || 0}</div>
    <div>Links: ${data.counts?.total_links || 0}</div>
  `;
  container.appendChild(overlay);

  // Reset focus when clicking empty space
  svg.on('click', () => {
    node.attr('opacity', 1).style('filter', 'none');
    link.attr('stroke', '#444').attr('stroke-opacity', 0.4);
    label.attr('opacity', 1);
  });
}

// Focus mode
function focusNode(target, node, link, label) {
  const connected = new Set();
  link.each(l => {
    if (l.source.id === target.id) connected.add(l.target.id);
    if (l.target.id === target.id) connected.add(l.source.id);
  });
  connected.add(target.id);
  node.attr('opacity', d => (connected.has(d.id) ? 1 : 0.15));
  label.attr('opacity', d => (connected.has(d.id) ? 1 : 0.15));
  link.attr('stroke', d =>
    d.source.id === target.id || d.target.id === target.id ? '#00bcd4' : '#333'
  );
  link.attr('stroke-opacity', d =>
    d.source.id === target.id || d.target.id === target.id ? 0.9 : 0.1
  );
}

// Group hover mode
function hoverGroup(target, node, link, label) {
  const connected = new Set();
  link.each(l => {
    if (l.source.id === target.id) connected.add(l.target.id);
    if (l.target.id === target.id) connected.add(l.source.id);
  });
  connected.add(target.id);
  node.attr('opacity', d => (connected.has(d.id) ? 1 : 0.3));
  label.attr('opacity', d => (connected.has(d.id) ? 1 : 0.3));
  link.attr('stroke', d =>
    d.source.id === target.id || d.target.id === target.id ? '#00e5ff' : '#333'
  );
  link.attr('stroke-opacity', d =>
    d.source.id === target.id || d.target.id === target.id ? 0.9 : 0.1
  );
}

function resetHover(node, link, label) {
  node.attr('opacity', 1);
  link.attr('stroke', '#444').attr('stroke-opacity', 0.4);
  label.attr('opacity', 1);
}

// Tooltip
let atlasTooltip;
function showAtlasTooltip(event, d) {
  hideAtlasTooltip();
  atlasTooltip = document.createElement('div');
  atlasTooltip.className = 'atlas-tooltip';
  atlasTooltip.style.cssText = `
    position: fixed;
    left: ${event.pageX + 10}px;
    top: ${event.pageY + 10}px;
    background: rgba(20,20,25,0.95);
    border: 1px solid #333;
    border-radius: 8px;
    padding: 8px 12px;
    color: #fff;
    font-size: 12px;
    z-index: 9999;
    pointer-events: none;
    box-shadow: 0 0 6px rgba(0,0,0,0.5);
  `;
  atlasTooltip.innerHTML = `
    <div><b>${d.id}</b> (${d.type})</div>
    ${d.ip ? `<div>${d.ip}</div>` : ''}
    ${d.group ? `<div>Group: ${d.group}</div>` : ''}
    ${d.status ? `<div>Status: ${d.status}</div>` : ''}
    ${d.latency ? `<div>Latency: ${d.latency.toFixed(2)}s</div>` : ''}
  `;
  document.body.appendChild(atlasTooltip);
}

function hideAtlasTooltip() {
  if (atlasTooltip) {
    atlasTooltip.remove();
    atlasTooltip = null;
  }
}