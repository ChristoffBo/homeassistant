const u = p => (p.startsWith('/')?p:`/${p}`);

async function postWake(text){
  const res = await fetch(u('internal/wake'), {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({text})
  });
  const j = await res.json().catch(()=>({}));
  return j;
}

function render(items){
  const root = document.getElementById('inbox');
  root.innerHTML = '';
  items.forEach(m => {
    const el = document.createElement('div');
    el.className = 'card';
    el.innerHTML = `<div class="meta">${m.id ? '#'+m.id : ''} • ${m.source||''}</div>
      <div class="title">${m.title||'Untitled'}</div>
      <div class="body">${(m.body||'').replace(/\n/g,'<br>')}</div>`;
    root.appendChild(el);
  });
}

async function refresh(){
  const res = await fetch(u('api/messages?limit=50'));
  const j = await res.json();
  render(j.items || []);
}

document.getElementById('wakeBtn').addEventListener('click', async ()=>{
  const txt = document.getElementById('wakeText').value.trim();
  if(!txt) return;
  await fetch(u('api/messages'), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({title:'UI Wake', body:txt, source:'ui'})});
  const resp = await postWake(txt);
  console.log('wake resp', resp);
  refresh();
});

refresh();
