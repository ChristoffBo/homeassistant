const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

function toast(msg){
  const d=document.createElement('div');
  d.className='toast';
  d.textContent=msg;
  $('#toast').appendChild(d);
  setTimeout(()=> d.remove(), 3200);
}

// API root
function api(path){ return new URL(path.replace(/^\/+/,''), document.baseURI).toString(); }

async function jfetch(url, opts={}){
  const r = await fetch(url, opts);
  if(!r.ok) throw new Error(await r.text());
  const ct = r.headers.get('content-type')||'';
  return ct.includes('json') ? r.json() : r.text();
}

// Tabs
$$(".tablink").forEach(btn=>{
  btn.addEventListener("click", ()=>{
    $$(".tablink").forEach(b=>b.classList.remove("active"));
    $$(".tabcontent").forEach(sec=>sec.classList.remove("show"));
    btn.classList.add("active");
    $("#"+btn.dataset.tab).classList.add("show");
  });
});

// Inbox
async function loadInbox(){
  try {
    const data = await jfetch(api("api/messages"));
    const list = Array.isArray(data.items) ? data.items : (data||[]);
    const tbody=$("#msg-list");
    tbody.innerHTML='';
    if(!list.length){ tbody.innerHTML='<tr><td colspan=3>No messages</td></tr>'; return; }
    for(const it of list){
      const tr=document.createElement("tr");
      tr.innerHTML=`<td>${new Date(it.created_at*1000).toLocaleString()}</td>
        <td>${it.source||''}</td>
        <td>${it.title||''}</td>`;
      tr.addEventListener("click", async()=>{
        try{
          const full=await jfetch(api("api/messages/"+it.id));
          $("#msg-preview").textContent=full.body||full.message||'';
        }catch{}
      });
      tbody.appendChild(tr);
    }
  } catch(e){ toast("Inbox error"); }
}

// Personas
$("#save-personas")?.addEventListener("click", async()=>{
  try{
    await jfetch(api("api/notify/personas"),{
      method:"POST",headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        dude:$("#p-dude").checked,
        chick:$("#p-chick").checked,
        nerd:$("#p-nerd").checked,
        rager:$("#p-rager").checked
      })
    });
    toast("Personas saved");
  }catch{toast("Save failed");}
});

// Channels
$("#save-channels")?.addEventListener("click", async()=>{
  try{
    await jfetch(api("api/notify/channels"),{
      method:"POST",headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        smtp:{host:$("#smtp-host").value,port:$("#smtp-port").value,user:$("#smtp-user").value,pass:$("#smtp-pass").value,from:$("#smtp-from").value},
        gotify:{url:$("#gotify-url").value,token:$("#gotify-token").value},
        ntfy:{url:$("#ntfy-url").value,topic:$("#ntfy-topic").value}
      })
    });
    toast("Channels saved");
  }catch{toast("Save failed");}
});

// Outputs tests
$("#test-email")?.addEventListener("click",()=> jfetch(api("api/notify/test/email"),{method:"POST"}).then(()=>toast("Email test sent")).catch(()=>toast("Fail")));
$("#test-gotify")?.addEventListener("click",()=> jfetch(api("api/notify/test/gotify"),{method:"POST"}).then(()=>toast("Gotify test sent")).catch(()=>toast("Fail")));
$("#test-ntfy")?.addEventListener("click",()=> jfetch(api("api/notify/test/ntfy"),{method:"POST"}).then(()=>toast("ntfy test sent")).catch(()=>toast("Fail")));

// Settings
$("#save-retention")?.addEventListener("click", async()=>{
  try{
    await jfetch(api("api/inbox/settings"),{method:"POST",headers:{'Content-Type':'application/json'},body:JSON.stringify({retention_days:$("#retention").value})});
    toast("Retention saved");
  }catch{toast("Fail");}
});
$("#purge")?.addEventListener("click", async()=>{
  try{
    await jfetch(api("api/inbox/purge"),{method:"POST",headers:{'Content-Type':'application/json'},body:JSON.stringify({days:$("#purge-days").value})});
    toast("Purge triggered");
  }catch{toast("Fail");}
});
$("#save-quiet")?.addEventListener("click", async()=>{
  try{
    await jfetch(api("api/notify/quiet"),{method:"POST",headers:{'Content-Type':'application/json'},
      body:JSON.stringify({tz:$("#qh-tz").value,start:$("#qh-start").value,end:$("#qh-end").value,allow_critical:$("#qh-allow-critical").checked})});
    toast("Quiet hours saved");
  }catch{toast("Fail");}
});

// LLM
$("#save-llm")?.addEventListener("click", async()=>{
  try{
    await jfetch(api("api/llm/settings"),{method:"POST",headers:{'Content-Type':'application/json'},
      body:JSON.stringify({model:$("#llm-model").value,ctx:$("#llm-ctx").value,timeout:$("#llm-timeout").value})});
    toast("LLM saved");
  }catch{toast("Fail");}
});

// EnviroGuard
$("#save-env")?.addEventListener("click", async()=>{
  try{
    await jfetch(api("api/llm/enviroguard"),{method:"POST",headers:{'Content-Type':'application/json'},
      body:JSON.stringify({hot:$("#env-hot").value,cold:$("#env-cold").value,hyst:$("#env-hyst").value})});
    toast("EnviroGuard saved");
  }catch{toast("Fail");}
});

// Boot
loadInbox();
setInterval(loadInbox, 60000);