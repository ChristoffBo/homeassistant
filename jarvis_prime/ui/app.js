(function(){
  const $ = s=>document.querySelector(s);
  const $$ = s=>document.querySelectorAll(s);

  function api(path){ return new URL(path, document.baseURI).toString(); }

  function toast(msg){
    const d=document.createElement('div');
    d.className='toast'; d.textContent=msg;
    $('#toast').appendChild(d);
    setTimeout(()=>d.remove(),3000);
  }

  async function jfetch(u,opts){
    const r=await fetch(u,opts);
    if(!r.ok) throw new Error(r.status);
    try{return await r.json();}catch{return {};}
  }

  // Tab switching
  $$('.tablink').forEach(b=>b.addEventListener('click',()=>{
    $$('.tablink').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
    $$('.tab').forEach(t=>t.classList.remove('active'));
    $('#'+b.dataset.tab).classList.add('active');
  }));

  // Inbox
  async function loadInbox(){
    try{
      const data=await jfetch(api('api/messages'));
      const tb=$('#msg-body'); tb.innerHTML='';
      if(!data.items||!data.items.length){ tb.innerHTML='<tr><td colspan=4>No messages</td></tr>'; return; }
      for(const m of data.items){
        const tr=document.createElement('tr');
        tr.innerHTML=`<td>${new Date((m.created_at||0)*1000).toLocaleString()}</td>
                      <td>${m.source||''}</td>
                      <td>${m.title||''}</td>
                      <td>
                        <button class="btn" data-id="${m.id}" data-act="arch">${m.saved?'Unarchive':'Archive'}</button>
                        <button class="btn danger" data-id="${m.id}" data-act="del">Delete</button>
                      </td>`;
        tb.appendChild(tr);
      }
    }catch(e){ toast('Inbox error'); }
  }

  $('#del-all').addEventListener('click',async()=>{
    if(!confirm('Delete all?'))return;
    await jfetch(api('api/messages'),{method:'DELETE'});
    loadInbox();
  });

  $('#msg-body').addEventListener('click',async e=>{
    if(e.target.dataset.act==='del'){
      await jfetch(api('api/messages/'+e.target.dataset.id),{method:'DELETE'});
      toast('Deleted'); loadInbox();
    }
    if(e.target.dataset.act==='arch'){
      await jfetch(api(`api/messages/${e.target.dataset.id}/save`),{method:'POST'});
      toast('Toggled archive'); loadInbox();
    }
  });

  // Personas
  $('#save-personas').addEventListener('click',async()=>{
    const payload={
      dude:$('#p-dude').checked,
      chick:$('#p-chick').checked,
      nerd:$('#p-nerd').checked,
      rager:$('#p-rager').checked
    };
    await jfetch(api('api/notify/personas'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    toast('Personas saved');
  });

  // Intakes
  $('#save-channels').addEventListener('click',async()=>{
    const payload={
      smtp:{host:$('#smtp-host').value,port:$('#smtp-port').value,user:$('#smtp-user').value,pass:$('#smtp-pass').value},
      gotify:{url:$('#gotify-url').value,token:$('#gotify-token').value},
      ntfy:{url:$('#ntfy-url').value,topic:$('#ntfy-topic').value}
    };
    await jfetch(api('api/notify/channels'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    toast('Channels saved');
  });

  $('#test-email').addEventListener('click',()=>jfetch(api('api/notify/test/email'),{method:'POST'}).then(()=>toast('Email test sent')));
  $('#test-gotify').addEventListener('click',()=>jfetch(api('api/notify/test/gotify'),{method:'POST'}).then(()=>toast('Gotify test sent')));
  $('#test-ntfy').addEventListener('click',()=>jfetch(api('api/notify/test/ntfy'),{method:'POST'}).then(()=>toast('ntfy test sent')));

  // Settings
  $('#save-retention').addEventListener('click',async()=>{
    const d=parseInt($('#retention').value,10)||30;
    await jfetch(api('api/inbox/settings'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({retention_days:d})});
    toast('Retention saved');
  });

  $('#save-quiet').addEventListener('click',async()=>{
    const payload={start:$('#qh-start').value,end:$('#qh-end').value};
    await jfetch(api('api/inbox/settings'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    toast('Quiet saved');
  });

  // LLM
  $('#save-llm').addEventListener('click',async()=>{
    const payload={model:$('#llm-model').value,ctx:$('#llm-ctx').value,timeout:$('#llm-timeout').value};
    await jfetch(api('api/llm/settings'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    toast('LLM saved');
  });

  // Enviro
  $('#save-env').addEventListener('click',async()=>{
    const payload={enabled:$('#env-enabled').checked,hot:$('#env-hot').value,cold:$('#env-cold').value};
    await jfetch(api('api/llm/enviroguard'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    toast('Enviro saved');
  });

  // Live stream updates
  function startStream(){
    const es=new EventSource(api('api/stream'));
    es.onmessage=(e)=>{
      try{
        const ev=JSON.parse(e.data||'{}');
        if(['created','deleted','deleted_all','saved','purged'].includes(ev.event)){
          loadInbox();
        }
      }catch{}
    };
    es.onerror=()=>{ es.close(); setTimeout(startStream,3000); };
  }

  // Boot
  loadInbox();
  startStream();
})();