// Jarvis Prime UI – alignment + ingress-safe API + clearer Options(All)

// --- API root (works with HA Ingress) ------------------------------------
function apiRoot(){
  // document.baseURI contains '/api/hassio_ingress/<token>/' in HA Ingress.
  // We always append relative 'api/...'
  let root = document.baseURI || '/';
  if(!root.endsWith('/')) root += '/';
  return root;
}
const ROOT = apiRoot();
const api = (p, opts={}) => fetch(`${ROOT}api/${p}`, {headers:{'Content-Type':'application/json'}, ...opts}).then(r=>r.json());

// --- small DOM helpers ---------------------------------------------------
const el = (tag, attrs={}, ...children) => {
  const n = document.createElement(tag);
  Object.entries(attrs).forEach(([k,v]) => {
    if(k==='class') n.className = v;
    else if(k==='html') n.innerHTML = v;
    else if(k==='text') n.textContent = v;
    else n.setAttribute(k,v);
  });
  for(const c of children){ if(c!==null && c!==undefined) n.append(c.nodeType? c : document.createTextNode(String(c))); }
  return n;
};

// --- NAV -----------------------------------------------------------------
function activateTab(id){
  document.querySelectorAll('section.view').forEach(s=>s.style.display='none');
  document.getElementById(id).style.display='block';
  document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('active', a.dataset.tab===id));
}

// --- INBOX ---------------------------------------------------------------
let previewBox;
async function drawInbox(){
  const wrap = document.getElementById('inbox-wrap');
  wrap.innerHTML = '';
  previewBox = el('div', {class:'preview', id:'preview'});
  wrap.append(previewBox);

  const head = el('div',{style:'display:flex; align-items:center; gap:10px; margin-bottom:10px'},
    el('span',{class:'badge'}, el('span',{class:'dot good'}),'Messages Today: ',el('b',{id:'msgToday'},'0')),
    el('span',{class:'badge'}, el('span',{class:'dot'}),'Archived: ',el('b',{id:'msgArch'},'0')),
    el('span',{class:'badge'}, el('span',{class:'dot'}),'Errors: ',el('b',{id:'msgErr'},'0')),
    el('span',{class:'spacer'}),
    el('button',{class:'btn',id:'btnRefresh'},'Refresh')
  );
  wrap.append(head);

  const tbl = el('table',{class:'table',id:'inboxTable'});
  tbl.append(el('thead',{}, el('tr',{},
      el('th',{},'Time'), el('th',{},'Source'), el('th',{},'Title'), el('th',{},'Actions')
  )));
  tbl.append(el('tbody',{}));
  wrap.append(tbl);

  await reloadInbox();
  document.getElementById('btnRefresh').onclick = reloadInbox;
}

async function reloadInbox(){
  try{
    const data = await api('messages?limit=200');
    const tbody = document.querySelector('#inboxTable tbody');
    tbody.innerHTML='';
    document.getElementById('msgToday').textContent = data.stats?.today ?? data.messages?.length ?? 0;
    document.getElementById('msgArch').textContent = data.stats?.archived ?? 0;
    document.getElementById('msgErr').textContent  = data.stats?.errors ?? 0;

    if(!data.messages || data.messages.length===0){
      tbody.append(el('tr',{}, el('td',{colspan:'4',class:'muted'},'No messages')));
      previewBox.style.display='none';
      return;
    }

    for(const m of data.messages){
      const tr = el('tr',{},
        el('td',{}, new Date(m.ts*1000).toLocaleString() ),
        el('td',{}, m.source || '—'),
        el('td',{}, m.title || '—'),
        el('td',{},
          el('button',{class:'btn',onclick:()=>showMsg(m.id)},'Open'),
          ' ',
          el('button',{class:'btn',onclick:()=>delMsg(m.id)},'Delete')
        ),
      );
      tr.onclick = ()=> showMsg(m.id);
      tbody.append(tr);
    }
  }catch(e){
    console.error(e);
  }
}

async function showMsg(id){
  try{
    const m = await api(`message/${id}`);
    let body = m.body || m.text || JSON.stringify(m,null,2);
    previewBox.innerHTML = '';
    previewBox.append(
      el('div',{style:'margin-bottom:6px; color:#94a3b8'}, `${m.source||'source'} • ${new Date(m.ts*1000).toLocaleString()} • p${m.priority??'-'}`),
      el('pre',{}, body)
    );
    previewBox.style.display='block';
    scrollTo(0,0);
  }catch(e){ console.error(e); }
}
async function delMsg(id){
  if(!confirm('Delete this message?')) return;
  await api(`message/${id}`, {method:'DELETE'});
  await reloadInbox();
}

// --- PERSONAS ------------------------------------------------------------
async function drawPersonas(){
  const root = document.getElementById('personas-wrap');
  root.innerHTML='';
  const box = el('div',{class:'panel'}, el('h2',{},'Personas'), el('div',{class:'form-grid',id:'pg'}));
  root.append(box);

  const o = await api('options');
  const pg = document.getElementById('pg');

  // toggles on top as 2-column matrix (label under each column)
  const toggles = [
    ['enable_dude','Dude'],['enable_chick','Chick'],['enable_nerd','Nerd'],
    ['enable_rager','Rager'],['enable_comedian','Comedian'],['enable_action','Action'],
    ['enable_jarvis','Jarvis'],['enable_ops','Ops'],
  ];
  pg.append(el('div',{class:'row pad-top'},
    el('label',{class:'k'},'Active persona'),
    inputBox('active_persona', o.active_persona || 'auto')
  ));
  pg.append(el('div',{class:'row'},
    el('label',{class:'k'},'Persistent'), checkbox('personality_persistent', o.personality_persistent)
  ));
  pg.append(el('div',{class:'row'},
    el('label',{class:'k'},'Family friendly'), checkbox('personality_family_friendly', o.personality_family_friendly)
  ));
  pg.append(el('div',{class:'row'},
    el('label',{class:'k'},'Min interval (min)'), number('personality_min_interval_minutes', o.personality_min_interval_minutes||90)
  ));
  pg.append(el('div',{class:'row'},
    el('label',{class:'k'},'Jitter %'), number('personality_interval_jitter_pct', o.personality_interval_jitter_pct||0)
  ));
  pg.append(el('div',{class:'row'},
    el('label',{class:'k'},'Daily max'), number('personality_daily_max', o.personality_daily_max||6)
  ));
  pg.append(el('div',{class:'row'},
    el('label',{class:'k'},'Quiet hours'), inputBox('personality_quiet_hours', o.personality_quiet_hours||'23:00-06:00'),
    el('div',{class:'help'},'Format: HH:MM‑HH:MM (local time)')
  ));

  // persona toggles grid
  const matrix = el('div',{style:'display:grid; grid-template-columns:repeat(4, minmax(120px, 1fr)); gap:10px; margin-top:8px'});
  toggles.forEach(([k,lab])=>{
    const row = el('label',{class:'btn',style:'justify-content:space-between'},
      el('span',{}, lab),
      checkbox(k, o[k]===true)
    );
    matrix.append(row);
  });
  pg.append(el('div',{class:'row pad-top'}, el('label',{class:'k'},'Enable'), matrix));

  const save = el('div',{style:'margin-top:12px'}, el('button',{class:'btn primary',onclick:savePersonas},'Save Personas'));
  pg.append(el('div',{class:'row'}, el('label',{class:'k'},''), save));
}

async function savePersonas(){
  const keys = [
    'active_persona','personality_persistent','personality_family_friendly',
    'personality_min_interval_minutes','personality_interval_jitter_pct','personality_daily_max',
    'personality_quiet_hours',
    'enable_dude','enable_chick','enable_nerd','enable_rager','enable_comedian','enable_action','enable_jarvis','enable_ops'
  ];
  const body = {};
  keys.forEach(k=>{
    const n = document.querySelector(`[name='${k}']`);
    if(!n) return;
    body[k] = (n.type==='checkbox') ? n.checked : n.value;
  });
  await api('options', {method:'PATCH', body:JSON.stringify(body)});
  alert('Saved.');
}

// --- INTAKES -------------------------------------------------------------
async function drawIntakes(){
  const root = document.getElementById('intakes-wrap'); root.innerHTML='';
  const box = el('div',{class:'panel'}, el('h2',{},'Intakes'), el('div',{class:'form-grid',id:'ig'}));
  root.append(box);
  const o = await api('options'); const ig = document.getElementById('ig');

  ig.append(el('div',{class:'row'},
    el('label',{class:'k'},'Gotify intake'), checkbox('ingest_gotify_enabled', o.ingest_gotify_enabled)
  ));
  ig.append(el('div',{class:'row'},
    el('label',{class:'k'},'ntfy intake'), checkbox('ingest_ntfy_enabled', o.ingest_ntfy_enabled)
  ));
  ig.append(el('div',{class:'row'},
    el('label',{class:'k'},'SMTP intake'), checkbox('ingest_smtp_enabled', o.ingest_smtp_enabled)
  ));
  ig.append(el('div',{class:'row'},
    el('label',{class:'k'},'Apprise intake'), checkbox('ingest_apprise_enabled', o.ingest_apprise_enabled)
  ));
  ig.append(el('div',{class:'row'},
    el('label',{class:'k'},'Allow HTML (SMTP)'), checkbox('smtp_allow_html', o.smtp_allow_html)
  ));
  ig.append(el('div',{class:'row'},
    el('label',{class:'k'},'Accept any SMTP auth'), checkbox('smtp_accept_any_auth', o.smtp_accept_any_auth)
  ));

  ig.append(el('div',{class:'row pad-top'}, el('label',{class:'k subtle'},'SMTP (Intake)')));
  addKV(ig,'Bind','smtp_bind', o.smtp_bind||'0.0.0.0');
  addKV(ig,'Port','smtp_port', o.smtp_port||2525, 'number');
  addKV(ig,'Max bytes','smtp_max_bytes', o.smtp_max_bytes||262144, 'number');
  addKV(ig,'Dummy RCPT','smtp_dummy_rcpt', o.smtp_dummy_rcpt||'alerts@jarvis.local');
  addKV(ig,'Title prefix','smtp_rewrite_title_prefix', o.smtp_rewrite_title_prefix||'[SMTP]');
  addKV(ig,'Priority default','smtp_priority_default', o.smtp_priority_default||5, 'number');
  addKV(ig,'Priority map','smtp_priority_map', o.smtp_priority_map||'{}', 'textarea');

  ig.append(el('div',{class:'row pad-top'}, el('label',{class:'k subtle'},'Apprise (Intake)')));
  addKV(ig,'Enabled','intake_apprise_enabled', o.intake_apprise_enabled, 'checkbox');
  addKV(ig,'Port','intake_apprise_port', o.intake_apprise_port||2591, 'number');
  addKV(ig,'Token','intake_apprise_token', o.intake_apprise_token||'');
  addKV(ig,'Accept any key','intake_apprise_accept_any_key', o.intake_apprise_accept_any_key, 'checkbox');
  addKV(ig,'Allowed keys (csv)','intake_apprise_allowed_keys', o.intake_apprise_allowed_keys||'');
  ig.append(el('div',{class:'row'}, el('label',{class:'k'},''), el('button',{class:'btn primary',onclick:saveIntakes},'Save Intakes')));
}
function addKV(root, label, key, val, mode='text'){
  let node;
  if(mode==='checkbox') node = checkbox(key, !!val);
  else if(mode==='textarea') node = textarea(key, String(val));
  else if(mode==='number') node = number(key, Number(val));
  else node = inputBox(key, String(val));

  root.append(el('div',{class:'row'}, el('label',{class:'k'},label), node));
}
async function saveIntakes(){
  const keys = ['ingest_gotify_enabled','ingest_ntfy_enabled','ingest_smtp_enabled','ingest_apprise_enabled','smtp_allow_html','smtp_accept_any_auth',
    'smtp_bind','smtp_port','smtp_max_bytes','smtp_dummy_rcpt','smtp_rewrite_title_prefix','smtp_priority_default','smtp_priority_map',
    'intake_apprise_enabled','intake_apprise_port','intake_apprise_token','intake_apprise_accept_any_key','intake_apprise_allowed_keys'];
  const body={};
  for(const k of keys){
    const n = document.querySelector(`[name='${k}']`);
    if(!n) continue;
    body[k] = (n.type==='checkbox') ? n.checked : (n.type==='number'? Number(n.value): n.value);
  }
  await api('options',{method:'PATCH', body:JSON.stringify(body)});
  alert('Saved.');
}

// --- NOTIFY OUTPUTS ------------------------------------------------------
async function drawOutputs(){
  const root = document.getElementById('outputs-wrap'); root.innerHTML='';
  const box = el('div',{class:'panel'}, el('h2',{},'Notify Outputs'), el('div',{class:'form-grid',id:'og'}));
  root.append(box);
  const o = await api('options'); const g = document.getElementById('og');

  addKV(g,'Push to Gotify','push_gotify_enabled', o.push_gotify_enabled,'checkbox');
  addKV(g,'Push to ntfy','push_ntfy_enabled', o.push_ntfy_enabled,'checkbox');
  addKV(g,'Push to SMTP','push_smtp_enabled', o.push_smtp_enabled,'checkbox');

  g.append(el('div',{class:'row pad-top'}, el('label',{class:'k subtle'},'Gotify')));
  addKV(g,'URL','gotify_url', o.gotify_url||'');
  addKV(g,'Client token','gotify_client_token', o.gotify_client_token||'');
  addKV(g,'App token','gotify_app_token', o.gotify_app_token||'');

  g.append(el('div',{class:'row pad-top'}, el('label',{class:'k subtle'},'ntfy')));
  addKV(g,'URL','ntfy_url', o.ntfy_url||'');
  addKV(g,'Topic','ntfy_topic', o.ntfy_topic||'');
  addKV(g,'User','ntfy_user', o.ntfy_user||'');
  addKV(g,'Pass','ntfy_pass', o.ntfy_pass||'');
  addKV(g,'Token','ntfy_token', o.ntfy_token||'');

  g.append(el('div',{class:'row pad-top'}, el('label',{class:'k subtle'},'SMTP (Push)')));
  addKV(g,'Host','push_smtp_host', o.push_smtp_host||'');
  addKV(g,'Port','push_smtp_port', o.push_smtp_port||587, 'number');
  addKV(g,'User','push_smtp_user', o.push_smtp_user||'');
  addKV(g,'Password','push_smtp_pass', o.push_smtp_pass||'');
  addKV(g,'To','push_smtp_to', o.push_smtp_to||'');

  g.append(el('div',{class:'row'}, el('label',{class:'k'},''), el('button',{class:'btn primary',onclick:saveOutputs},'Save Outputs')));
}
async function saveOutputs(){
  const ks=['push_gotify_enabled','push_ntfy_enabled','push_smtp_enabled','gotify_url','gotify_client_token','gotify_app_token','ntfy_url','ntfy_topic','ntfy_user','ntfy_pass','ntfy_token','push_smtp_host','push_smtp_port','push_smtp_user','push_smtp_pass','push_smtp_to'];
  const body={};
  ks.forEach(k=>{
    const n=document.querySelector(`[name='${k}']`); if(!n) return;
    body[k] = (n.type==='checkbox')? n.checked : n.type==='number'? Number(n.value): n.value;
  });
  await api('options',{method:'PATCH', body:JSON.stringify(body)});
  alert('Saved.');
}

// --- SETTINGS (Quiet Hours etc.) ----------------------------------------
async function drawSettings(){
  const root=document.getElementById('settings-wrap'); root.innerHTML='';
  const box = el('div',{class:'panel'}, el('h2',{},'Settings'), el('div',{class:'form-grid',id:'sg'}));
  root.append(box);

  const o=await api('options'); const g=document.getElementById('sg');
  addKV(g,'Retention days','retention_days', o.retention_days||30,'number');
  addKV(g,'Retention hours','retention_hours', o.retention_hours||24,'number');
  addKV(g,'Auto purge policy','auto_purge_policy', o.auto_purge_policy||'off');

  g.append(el('div',{class:'row pad-top'}, el('label',{class:'k subtle'},'Quiet Hours')));
  addKV(g,'Timezone','quiet_timezone', o.quiet_timezone||'Africa/Johannesburg');
  addKV(g,'Quiet start','quiet_start', o.quiet_start||'22:00');
  addKV(g,'Quiet end','quiet_end', o.quiet_end||'06:00');
  // button
  g.append(el('div',{class:'row'}, el('label',{class:'k'},''), el('button',{class:'btn primary',onclick:saveSettings},'Save Settings')));
}
async function saveSettings(){
  const ks=['retention_days','retention_hours','auto_purge_policy','quiet_timezone','quiet_start','quiet_end'];
  const body={};
  for(const k of ks){ const n=document.querySelector(`[name='${k}']`); if(!n) continue; body[k]=(n.type==='number'? Number(n.value): n.value); }
  await api('options',{method:'PATCH', body:JSON.stringify(body)}); alert('Saved.');
}

// --- LLM -----------------------------------------------------------------
async function drawLLM(){
  const root=document.getElementById('llm-wrap'); root.innerHTML='';
  const box = el('div',{class:'panel'}, el('h2',{},'LLM Settings'), el('div',{class:'form-grid',id:'lg'}));
  root.append(box);
  const o=await api('options'); const g=document.getElementById('lg');

  addKV(g,'LLM enabled','llm_enabled', o.llm_enabled,'checkbox');
  addKV(g,'Persona riffs enabled','llm_persona_riffs_enabled', o.llm_persona_riffs_enabled,'checkbox');
  addKV(g,'Cleanup on disable','llm_cleanup_on_disable', o.llm_cleanup_on_disable,'checkbox');
  addKV(g,'Models dir','llm_models_dir', o.llm_models_dir||'/share/jarvis_prime/models');
  addKV(g,'Timeout (s)','llm_timeout_seconds', o.llm_timeout_seconds||20,'number');

  addKV(g,'Max CPU %','llm_max_cpu_percent', o.llm_max_cpu_percent||80,'number');
  addKV(g,'Context tokens','llm_ctx_tokens', o.llm_ctx_tokens||4096,'number');
  addKV(g,'Gen tokens','llm_gen_tokens', o.llm_gen_tokens||300,'number');
  addKV(g,'Max lines','llm_max_lines', o.llm_max_lines||30,'number');

  addKV(g,'System prompt','llm_system_prompt', o.llm_system_prompt||'','textarea');
  addKV(g,'Model preference','llm_model_preference', o.llm_model_preference||'phi,qwen,tinyllama');

  g.append(el('div',{class:'row pad-top'}, el('label',{class:'k subtle'},'Model Sources')));
  addKV(g,'Model URL','llm_model_url', o.llm_model_url||'');
  addKV(g,'Model path','llm_model_path', o.llm_model_path||'');
  addKV(g,'SHA256','llm_model_sha256', o.llm_model_sha256||'');
  addKV(g,'Ollama base URL','llm_ollama_base_url', o.llm_ollama_base_url||'');
  addKV(g,'HF token','llm_hf_token', o.llm_hf_token||'');

  g.append(el('div',{class:'row pad-top'}, el('label',{class:'k subtle'},'Per‑model toggles')));
  addKV(g,'phi3 enabled','llm_phi3_enabled', o.llm_phi3_enabled,'checkbox');
  addKV(g,'phi3 URL','llm_phi3_url', o.llm_phi3_url||'');
  addKV(g,'phi3 Path','llm_phi3_path', o.llm_phi3_path||'');
  addKV(g,'tinyllama enabled','llm_tinyllama_enabled', o.llm_tinyllama_enabled,'checkbox');
  addKV(g,'tinyllama URL','llm_tinyllama_url', o.llm_tinyllama_url||'');
  addKV(g,'tinyllama Path','llm_tinyllama_path', o.llm_tinyllama_path||'');
  addKV(g,'qwen0.5b enabled','llm_qwen05_enabled', o.llm_qwen05_enabled,'checkbox');
  addKV(g,'qwen0.5b URL','llm_qwen05_url', o.llm_qwen05_url||'');
  addKV(g,'qwen0.5b Path','llm_qwen05_path', o.llm_qwen05_path||'');

  g.append(el('div',{class:'row'}, el('label',{class:'k'},''), el('button',{class:'btn primary',onclick:saveLLM},'Save LLM')));
}
async function saveLLM(){
  const ks=['llm_enabled','llm_persona_riffs_enabled','llm_cleanup_on_disable','llm_models_dir','llm_timeout_seconds','llm_max_cpu_percent','llm_ctx_tokens','llm_gen_tokens','llm_max_lines','llm_system_prompt','llm_model_preference','llm_model_url','llm_model_path','llm_model_sha256','llm_ollama_base_url','llm_hf_token','llm_phi3_enabled','llm_phi3_url','llm_phi3_path','llm_tinyllama_enabled','llm_tinyllama_url','llm_tinyllama_path','llm_qwen05_enabled','llm_qwen05_url','llm_qwen05_path'];
  const body={};
  ks.forEach(k=>{ const n=document.querySelector(`[name='${k}']`); if(!n) return; body[k]=(n.type==='checkbox')?n.checked:(n.type==='number'?Number(n.value):n.value); });
  await api('options',{method:'PATCH', body:JSON.stringify(body)}); alert('Saved.');
}

// --- OPTIONS (ALL) -------------------------------------------------------
async function drawOptionsAll(){
  const root=document.getElementById('options-wrap'); root.innerHTML='';
  const box = el('div',{class:'panel'}, el('h2',{},'Options (All)'), el('div',{class:'form-grid',id:'og'}));
  root.append(box);
  const o=await api('options'); const s=await api('schema');
  const g=document.getElementById('og');

  const groups = {
    'Core': ['active_persona','personality_persistent','personality_family_friendly','personality_daily_max','greeting_enabled','greeting_times','heartbeat_interval_minutes','bot_name','jarvis_app_name'],
    'I/O & Channels': ['gotify_app_token','gotify_client_token','gotify_url','push_gotify_enabled','ntfy_topic','ntfy_url','intake_apprise_port','intake_apprise_enabled',
      'proxy_port','proxy_enabled','smtp_port','smtp_dummy_rcpt','smtp_accept_any_auth'],
    'SMTP (limits)': ['smtp_max_bytes','smtp_priority_default','smtp_rewrite_title_prefix','smtp_bind'],
    'Webhook': ['webhook_port'],
  };

  function labelize(k){ return k.replace(/_/g,' ').replace(/\b\w/g,m=>m.toUpperCase()) }

  Object.entries(groups).forEach(([title, keys])=>{
    g.append(el('div',{class:'row pad-top'}, el('label',{class:'k subtle'}, title)));
    for(const k of keys){
      const val = o[k]; const typ = (s[k]||'str').startsWith('int')? 'number' : (s[k]==='bool'?'checkbox':'text');
      addKV(g, labelize(k), k, val, typ);
    }
  });

  // read-only dump at the end
  g.append(el('div',{class:'row pad-top'}, el('label',{class:'k subtle'},'Raw')));
  const dump = el('textarea',{class:'v', readonly:'', style:'height:180px'}, JSON.stringify(o,null,2));
  g.append(el('div',{class:'row'}, el('label',{class:'k'},'options.json'), dump));
}

// --- tiny input helpers --------------------------------------------------
function inputBox(name, value){ return el('input',{class:'v', name, value}); }
function number(name, value){ return el('input',{class:'v', type:'number', name, value}); }
function checkbox(name, checked){ const n=el('input',{type:'checkbox', name}); n.checked=!!checked; return n; }
function textarea(name, value){ return el('textarea',{class:'v', name}, value); }

// --- boot ---------------------------------------------------------------
window.addEventListener('DOMContentLoaded', async ()=>{
  // wire nav
  document.querySelectorAll('nav a[data-tab]').forEach(a=> a.onclick=(e)=>{e.preventDefault(); activateTab(a.dataset.tab)});
  // initial draw
  await drawInbox(); activateTab('inbox');

  // wire tabs
  document.querySelector('a[data-tab="personas"]').onclick = async (e)=>{e.preventDefault(); await drawPersonas(); activateTab('personas');}
  document.querySelector('a[data-tab="intakes"]').onclick  = async (e)=>{e.preventDefault(); await drawIntakes();  activateTab('intakes');}
  document.querySelector('a[data-tab="outputs"]').onclick  = async (e)=>{e.preventDefault(); await drawOutputs();  activateTab('outputs');}
  document.querySelector('a[data-tab="settings"]').onclick = async (e)=>{e.preventDefault(); await drawSettings(); activateTab('settings');}
  document.querySelector('a[data-tab="llm"]').onclick      = async (e)=>{e.preventDefault(); await drawLLM();      activateTab('llm');}
  document.querySelector('a[data-tab="options"]').onclick  = async (e)=>{e.preventDefault(); await drawOptionsAll();activateTab('options');}
});
