const $  = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));

function apiRoot() {
  if (window.JARVIS_API_BASE) {
    let v = String(window.JARVIS_API_BASE);
    return v.endsWith('/') ? v : v + '/';
  }
  try {
    const u = new URL(document.baseURI);
    let p = u.pathname;
    if (p.endsWith('/index.html')) p = p.slice(0, -'/index.html'.length);
    if (!p.endsWith('/')) p += '/';
    u.pathname = p;
    return u.toString();
  } catch (e) {
    return document.baseURI;
  }
}
const ROOT = apiRoot();

function toast(msg) {
  let d = document.createElement('div');
  d.className = 'toast';
  d.textContent = msg;
  $('#toast').appendChild(d);
  setTimeout(()=>d.remove(),4000);
}

// ---- Chat wiring ----
$('#chat-send').onclick = async () => {
  const text = $('#chat-input').value.trim();
  if (!text) return;
  try {
    let r = await fetch(ROOT + 'api/wake', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ text })
    });
    if (r.ok) {
      toast('Sent wake: ' + text);
      $('#chat-input').value = '';
    } else {
      toast('Wake failed: ' + r.status);
    }
  } catch(e) { toast('Wake error: ' + e); }
};

// ---- Purge wiring ----
$('#purge-now').onclick = async () => {
  const days = $('#purge-select').value;
  try {
    let r = await fetch(ROOT + 'api/inbox/purge', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ days })
    });
    let j = await r.json();
    toast('Purged messages older than ' + days + ' days');
  } catch(e) { toast('Purge error: ' + e); }
};

// Auto purge schedule
async function autoPurge() {
  const days = $('#purge-select').value;
  try {
    await fetch(ROOT + 'api/inbox/purge', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ days })
    });
  } catch(e) {}
}
setInterval(autoPurge, 6*60*60*1000); // run every 6h

// ---- Inbox logic (unchanged) ----
// ... keep all your existing inbox code here
