
const $ = (sel, el=document) => el.querySelector(sel);
const $$ = (sel, el=document) => Array.from(el.querySelectorAll(sel));
const on = (el, ev, cb) => el && el.addEventListener(ev, cb);
async function fetchJSON(url, opts={}){
  const headers = Object.assign({'Content-Type':'application/json'}, opts.headers||{});
  const res = await fetch(url, Object.assign({}, opts, {headers}));
  return res.json().catch(()=>({}));
}
function activateTabByHash(){
  const hash = location.hash || '#tab-backup';
  const id = hash.replace('#','');
  $$('.tab-panel').forEach(p => p.style.display='none');
  const panel = document.getElementById(id) || document.getElementById('tab-backup');
  if (panel) panel.style.display='block';
  $$('#tabs .tab-btn').forEach(a => a.classList.toggle('active', a.getAttribute('href') === '#'+id));
  localStorage.setItem('rlb_active_tab', id);
}
on(window,'hashchange', activateTabByHash);
on(document,'DOMContentLoaded', () => {
  const saved = localStorage.getItem('rlb_active_tab');
  if (!location.hash && saved) location.hash = '#'+saved;
  activateTabByHash();
});

// Progress polling
setInterval(async () => {
  try{
    const jobs = await fetchJSON('/api/jobs');
    const running = Array.isArray(jobs) && jobs.find(j => j.status==='running');
    if (running){
      const p = $('#b_progress'); const pct = Math.max(0, Math.min(100, running.progress||0));
      if (p) p.value = pct; const t = $('#b_progress_pct'); if (t) t.textContent = pct+'%';
    }
  }catch(e){}
}, 1500);

// Minimal wiring to prove tabs/buttons work (full wiring provided earlier)
on(document,'DOMContentLoaded', () => {
  // Tooltip titles are already in markup
  // Example: refresh Connections/Mounts if endpoints exist
  async function tryRefresh(selId, url, key){
    try{
      const d = await fetchJSON(url);
      const sel = $(selId); if (!sel || !d[key]) return;
      sel.innerHTML=''; (d[key]||[]).forEach(x=>{ const o=document.createElement('option'); o.textContent=x.name||x; o.value=x.name||x; sel.appendChild(o); });
    }catch(e){}
  }
  tryRefresh('#b_conn','/api/connections','connections');
  tryRefresh('#dest_mount','/api/mounts','mounts');
});
