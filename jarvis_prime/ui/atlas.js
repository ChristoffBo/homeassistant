// /share/jarvis_prime/ui/js/atlas.js
// Atlas Module for Jarvis Prime
// Renders live topology graph from /api/atlas/topology
// Uses D3.js (auto-included in index.html) and app.js's API() resolver

const ATLAS_API = (path = '') => {
  if (typeof API === 'function') {
    return API('api/atlas/' + path.replace(/^\/+/, ''));
  }
  return '/api/atlas/' + path.replace(/^\/+/, '');
};

document.addEventListener('DOMContentLoaded', () => {
  // Refresh Atlas whenever tab becomes active
  const atlasTab = document.getElementById('atlas');
  if (!atlasTab) return;

  setInterval(() => {
    if (atlasTab.classList.contains('active')) {
      atlasRender();
    }
  }, 10000);

  // First draw
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
    .style('background', '#0b0c10')
    .style('border-radius', '12px');

  const g = svg.append('g');
  svg.call(
    d3.zoom()
      .scaleExtent([0.3, 3])
      .on('zoom', (event) => g.attr('transform', event.transform))
  );

  const link = g.append('g')
    .attr('stroke', '#444')
    .attr('stroke-opacity', 0.4)
    .selectAll('line')
    .data(data.links)
    .join('line')
    .attr('stroke-width', 1.2);

  const node = g.append('g')
    .selectAll('circle')
    .data(data.nodes)
    .join('circle')
    .attr('r', d => d.type === 'core' ? 14 : d.type === 'host' ? 10 : 6)
    .attr('fill', d => d.color || '#777')
    .attr('stroke', d => d.type === 'core' ? '#00bcd4' : '#111')
    .attr('stroke-width', 1.5)
    .on('click', (event, d) => {
  // Disable navigation – keep Atlas read-only (no 404s)
  event.preventDefault();
  console.log(`[atlas] clicked ${d.id} (${d.type}) — view-only`);
})
    .on('mouseover', (event, d) => showAtlasTooltip(event, d))
    .on('mouseout', hideAtlasTooltip);

  const label = g.append('g')
    .selectAll('text')
    .data(data.nodes)
    .join('text')
    .text(d => d.id)
    .attr('fill', '#ccc')
    .attr('font-size', 10)
    .attr('text-anchor', 'middle');

  const sim = d3.forceSimulation(data.nodes)
    .force('link', d3.forceLink(data.links).id(d => d.id).distance(80))
    .force('charge', d3.forceManyBody().strength(-250))
    .force('center', d3.forceCenter(width / 2, height / 2));

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
      .attr('y', d => d.y - 14);
  });
}

// Tooltip helpers
let atlasTooltip;
function showAtlasTooltip(event, d) {
  hideAtlasTooltip();
  atlasTooltip = document.createElement('div');
  atlasTooltip.className = 'atlas-tooltip';
  atlasTooltip.style.cssText = `
    position: fixed;
    left: ${event.pageX + 10}px;
    top: ${event.pageY + 10}px;
    background: rgba(17,17,17,0.9);
    border: 1px solid #333;
    border-radius: 8px;
    padding: 8px 12px;
    color: #fff;
    font-size: 12px;
    z-index: 9999;
    pointer-events: none;
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