/* =============== CHAT FUNCTIONALITY =============== */
  let chatHistory = [];
  let waitingForResponse = false;

  // Load chat history from localStorage
  function loadChatHistory() {
    try {
      const saved = localStorage.getItem('jarvis_chat_history');
      if (saved) {
        chatHistory = JSON.parse(saved);
        restoreChatMessages();
      }
    } catch (e) {
      console.warn('Failed to load chat history:', e);
      chatHistory = [];
    }
  }

  // Save chat history to localStorage
  function saveChatHistory() {
    try {
      localStorage.setItem('jarvis_chat_history', JSON.stringify(chatHistory));
    } catch (e) {
      console.warn('Failed to save chat history:', e);
    }
  }

  // Restore chat messages in the UI
  function restoreChatMessages() {
    const messagesContainer = $('#chat-messages');
    messagesContainer.innerHTML = `
      <div class="chat-message bot">
        <div class="message-content">
          👋 Hello! I'm Jarvis, your AI assistant. I can help you with information, analysis, creative tasks, and general conversation. What would you like to talk about?
        </div>
        <div class="message-time">System initialized</div>
      </div>
    `;
    
    chatHistory.forEach(item => {
      const messageDiv = document.createElement('div');
      messageDiv.className = `chat-message ${item.isUser ? 'user' : 'bot'}`;
      const time = new Date(item.timestamp).toLocaleTimeString();
      messageDiv.innerHTML = `
        <div class="message-content">${item.content}</div>
        <div class="message-time">${time}</div>
      `;
      messagesContainer.appendChild(messageDiv);
    });
    
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  // Load chat history from localStorage
  function loadChatHistory() {
    try {
      const saved = localStorage.getItem('jarvis_chat_history');
      if (saved) {
        chat(function () {
  /* =============== CORE UTILITIES =============== */
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // API configuration
  function apiRoot() {
    if (window.JARVIS_API_BASE) {
      let v = String(window.JARVIS_API_BASE);
      return v.endsWith('/') ? v : v + '/';
    }
    try {
      const u = new URL(document.baseURI);
      let p = u.pathname;
      if (p.endsWith('/index.html')) p = p.slice(0, -'/index.html'.length);
      if (p.endsWith('/ui/')) p = p.slice(0, -4);
      if (!p.endsWith('/')) p += '/';
      u.pathname = p;
      return u.toString();
    } catch (e) {
      return document.baseURI;
    }
  }
  
  const ROOT = apiRoot();
  const API = (path) => new URL(String(path).replace(/^\/+/, ''), ROOT).toString();

  // Toast notifications
  function toast(msg, type = 'info') {
    const d = document.createElement('div');
    d.className = `toast ${type}`;
    d.textContent = msg;
    $('#toast')?.appendChild(d);
    setTimeout(() => d.remove(), 4000);
  }

  // Enhanced fetch with better error handling
  async function jfetch(url, opts = {}) {
    try {
      const r = await fetch(url, {
        ...opts,
        headers: {
          'Content-Type': 'application/json',
          ...opts.headers
        }
      });
      
      if (!r.ok) {
        const text = await r.text().catch(() => '');
        throw new Error(`${r.status} ${r.statusText}: ${text}`);
      }
      
      const ct = r.headers.get('content-type') || '';
      return ct.includes('application/json') ? r.json() : r.text();
    } catch (error) {
      console.error('API Error:', error);
      throw error;
    }
  }

  // System status management
  function updateSystemStatus(status, message) {
    const dot = $('#connection-status');
    const text = $('#system-status-text');
    
    if (dot) {
      dot.className = `status-dot ${status}`;
    }
    if (text) {
      text.textContent = message;
    }
  }

  function formatTime(ts) {
    try {
      const v = Number(ts || 0);
      const ms = v > 1e12 ? v : v * 1000;
      return new Date(ms).toLocaleString();
    } catch {
      return '';
    }
  }

  /* =============== TAB MANAGEMENT =============== */
  $$('.nav-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.nav-tab').forEach(x => x.classList.remove('active'));
      btn.classList.add('active');
      $$('.tab-panel').forEach(t => t.classList.remove('active'));
      const pane = $('#' + btn.dataset.tab);
      if (pane) pane.classList.add('active');
    });
  });

  /* =============== INBOX FUNCTIONALITY =============== */
  let INBOX_ITEMS = [];
  let SELECTED_ID = null;

  function updateCounters(items) {
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
    const today = items.filter(i => (i.created_at || 0) >= start).length;
    const archived = items.filter(i => i.saved).length;
    const errors = items.filter(i => /error|fail|exception/i.test(`${i.title || ''} ${i.body || i.message || ''}`)).length;
    
    $('#msg-today').textContent = today;
    $('#msg-arch').textContent = archived;
    $('#msg-err').textContent = errors;
  }

  function renderPreview(m) {
    if (!m) {
      $('#pv-title').textContent = 'No message selected';
      $('#pv-meta').textContent = '—';
      $('#pv-body').innerHTML = '<div class="text-center text-muted">Select a message to preview its contents</div>';
      return;
    }
    
    $('#pv-title').textContent = m.title || '(no title)';
    const bits = [];
    if (m.source) bits.push(`Source: ${m.source}`);
    if (m.created_at) bits.push(`Time: ${formatTime(m.created_at)}`);
    $('#pv-meta').textContent = bits.join(' • ') || '—';
    
    const body = (m.body || m.message || '').trim();
    $('#pv-body').textContent = body || '(empty message)';
  }

  function selectRowById(id) {
    SELECTED_ID = id;
    $$('#msg-body tr').forEach(tr => tr.classList.toggle('selected', tr.dataset.id === String(id)));
    const m = INBOX_ITEMS.find(x => String(x.id) === String(id));
    renderPreview(m);
  }

  async function loadInbox() {
    const tb = $('#msg-body');
    try {
      updateSystemStatus('connecting', 'Loading...');
      const data = await jfetch(API('api/messages'));
      const items = data && data.items ? data.items : (Array.isArray(data) ? data : []);
      INBOX_ITEMS = Array.isArray(items) ? items : [];
      tb.innerHTML = '';

      if (!INBOX_ITEMS.length) {
        tb.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No messages in inbox</td></tr>';
        updateCounters([]);
        renderPreview(null);
        updateSystemStatus('', 'Connected');
        return;
      }

      updateCounters(INBOX_ITEMS);
      
      for (const m of INBOX_ITEMS) {
        const tr = document.createElement('tr');
        tr.dataset.id = m.id;
        tr.innerHTML = `
          <td>${formatTime(m.created_at)}</td>
          <td>${m.source || ''}</td>
          <td>${m.title || ''}</td>
          <td>
            <button class="btn" data-id="${m.id}" data-act="arch">
              ${m.saved ? 'Unarchive' : 'Archive'}
            </button>
            <button class="btn danger" data-id="${m.id}" data-act="del">Delete</button>
          </td>`;
        tb.appendChild(tr);
      }

      const follow = $('#pv-follow')?.checked;
      const still = SELECTED_ID && INBOX_ITEMS.some(x => String(x.id) === String(SELECTED_ID));
      
      if (still) {
        selectRowById(SELECTED_ID);
      } else if (follow && INBOX_ITEMS.length) {
        const last = INBOX_ITEMS[INBOX_ITEMS.length - 1];
        selectRowById(last.id);
      } else {
        renderPreview(null);
      }
      
      updateSystemStatus('', 'Connected');
    } catch (e) {
      console.error('Inbox load error:', e);
      tb.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Failed to load messages</td></tr>';
      toast('Failed to load inbox', 'error');
      renderPreview(null);
      updateSystemStatus('error', 'Connection Error');
    }
  }

  // Message actions
  $('#msg-body').addEventListener('click', (ev) => {
    const btn = ev.target.closest('button[data-act]');
    if (btn) {
      const id = btn.dataset.id;
      const act = btn.dataset.act;
      
      (async () => {
        try {
          btn.classList.add('loading');
          
          if (act === 'del') {
            if (!confirm('Delete this message?')) return;
            await jfetch(API('api/messages/' + id), { method: 'DELETE' });
            toast('Message deleted', 'success');
          } else if (act === 'arch') {
            await jfetch(API(`api/messages/${id}/save`), {
              method: 'POST',
              body: JSON.stringify({})
            });
            toast('Archive status toggled', 'success');
          }
          
          await loadInbox();
        } catch (e) {
          toast('Action failed: ' + e.message, 'error');
        } finally {
          btn.classList.remove('loading');
        }
      })();
      return;
    }
    
    const tr = ev.target.closest('tr[data-id]');
    if (tr && tr.dataset.id) selectRowById(tr.dataset.id);
  });

  // Delete all messages
  $('#del-all').addEventListener('click', async () => {
    if (!confirm('Delete ALL messages? This cannot be undone!')) return;
    
    const keep = $('#keep-arch')?.checked ? 1 : 0;
    const btn = $('#del-all');
    
    try {
      btn.classList.add('loading');
      await jfetch(API(`api/messages?keep_saved=${keep}`), { method: 'DELETE' });
      toast('All messages deleted', 'success');
      await loadInbox();
    } catch (e) {
      toast('Delete all failed: ' + e.message, 'error');
    } finally {
      btn.classList.remove('loading');
    }
  });

  /* =============== CHAT FUNCTIONALITY =============== */
  let chatHistory = [];
  let waitingForResponse = false;

  function addChatMessage(content, isUser = false) {
    const messagesContainer = $('#chat-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${isUser ? 'user' : 'bot'}`;
    
    const now = new Date().toLocaleTimeString();
    messageDiv.innerHTML = `
      <div class="message-content">${content}</div>
      <div class="message-time">${now}</div>
    `;
    
    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    
    chatHistory.push({ content, isUser, timestamp: Date.now() });
  }

  function updateChatStatus(status) {
    $('#chat-status').textContent = status;
  }

  async function sendChatMessage() {
    const input = $('#chat-input');
    const text = input.value.trim();
    if (!text) return;

    const sendBtn = $('#chat-send');
    
    try {
      sendBtn.classList.add('loading');
      updateChatStatus('Processing...');
      
      addChatMessage(text, true);
      input.value = '';
      waitingForResponse = true;
      
      // Format message exactly like Gotify does to trigger your bot.py chat routing
      try {
        const messagePayload = {
          title: 'chat',                    // Keep title as "chat" for consistency
          message: `chat ${text}`,          // Include "chat" prefix in message body
          body: `chat ${text}`,             // Include "chat" prefix in body field
          source: 'webui-chat',
          priority: 5,
          created_at: Math.floor(Date.now() / 1000)
        };
        
        console.log('🚀 Sending chat message to trigger LLM:', messagePayload);
        
        const response = await fetch(API('api/messages'), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(messagePayload)
        });
        
        if (response.ok) {
          const result = await response.json().catch(() => ({}));
          console.log('✅ Message sent successfully:', result);
          
          updateChatStatus('Sent to AI...');
          toast('Message sent to Jarvis AI', 'success');
          
          // Set timeout for response - increased to 30 seconds for LLM processing
          const responseTimeout = setTimeout(() => {
            if (waitingForResponse) {
              console.log('⏰ Chat response timeout');
              addChatMessage('⏰ No response received. Check the inbox for any new messages.', false);
              waitingForResponse = false;
              updateChatStatus('Ready');
            }
          }, 30000); // 30 second timeout
          
          // Store timeout so we can clear it if we get a response
          window.lastChatTimeout = responseTimeout;
          
        } else {
          const errorText = await response.text().catch(() => 'Unknown error');
          throw new Error(`API failed: ${response.status} - ${errorText}`);
        }
        
      } catch (apiError) {
        console.error('❌ API method failed:', apiError);
        waitingForResponse = false;
        
        addChatMessage(`🔧 API unavailable. Try using Gotify instead:`, false);
        addChatMessage(`📱 Send to Gotify: "chat ${text}"`, false);
        
        updateChatStatus('Use Gotify');
        toast(`Send via Gotify: "chat ${text}"`, 'info');
      }
      
    } catch (e) {
      console.error('❌ Chat system error:', e);
      waitingForResponse = false;
      addChatMessage('❌ Chat system error. Try using Gotify with "chat" prefix.', false);
      updateChatStatus('Error');
      toast('Chat system error', 'error');
    } finally {
      sendBtn.classList.remove('loading');
    }
  }

  // Listen for chat responses in the SSE stream
  function handleChatResponse(data) {
    console.log('🔍 Checking message for chat response:', data);
    
    // Look for responses from your chatbot.py system
    const title = (data.title || '').toLowerCase().trim();
    const source = (data.source || '').toLowerCase().trim();
    const message = data.message || data.body || '';
    
    console.log('Chat detection - waiting:', waitingForResponse, 'title:', title, 'source:', source);
    
    // Enhanced detection for jarvis_out responses with "Chat" title
    const isChatResponse = (
      (source === 'jarvis_out' && title === 'chat') ||  // Exact match for your system
      title.includes('chat') ||
      title.includes('response') ||
      title.includes('assistant') ||
      source.includes('chatbot') ||
      source.includes('llm') ||
      source.includes('openai') ||
      source.includes('claude')
    );
    
    if (isChatResponse && message.trim()) {
      console.log('✅ Chat response detected!', { title, source, messageLength: message.length });
      
      // Clear the timeout since we got a response
      if (window.lastChatTimeout) {
        clearTimeout(window.lastChatTimeout);
        window.lastChatTimeout = null;
      }
      
      addChatMessage(message.trim(), false);
      waitingForResponse = false;
      updateChatStatus('Ready');
      toast('Response received from Jarvis', 'success');
      return true; // Mark as handled
    }
    
    console.log('❌ Not identified as chat response');
    return false; // Not a chat response
  }

  $('#chat-send').addEventListener('click', sendChatMessage);
  $('#chat-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      sendChatMessage();
    }
  });

  $('#clear-chat').addEventListener('click', () => {
    if (confirm('Clear all chat messages?')) {
      $('#chat-messages').innerHTML = `
        <div class="chat-message bot">
          <div class="message-content">
            👋 Hello! I'm Jarvis, your AI assistant. I can help you with information, analysis, creative tasks, and general conversation. What would you like to talk about?
          </div>
          <div class="message-time">System initialized</div>
        </div>
      `;
      chatHistory = [];
      toast('Chat cleared', 'success');
    }
  });

  /* =============== WAKE FUNCTIONALITY =============== */
  let wakeHistory = [];

  function addWakeToHistory(command) {
    wakeHistory.unshift({
      command,
      timestamp: Date.now()
    });
    
    // Keep only last 20 wake commands
    if (wakeHistory.length > 20) {
      wakeHistory = wakeHistory.slice(0, 20);
    }
    
    updateWakeHistory();
    $('#last-wake').textContent = new Date().toLocaleTimeString();
  }

  function updateWakeHistory() {
    const historyDiv = $('#wake-history');
    if (wakeHistory.length === 0) {
      historyDiv.innerHTML = '<div class="text-center text-muted">No commands executed yet</div>';
      return;
    }
    
    historyDiv.innerHTML = wakeHistory.map(item => 
      `<div class="wake-history-item">
        <div class="wake-command">jarvis ${item.command}</div>
        <div class="wake-time">${new Date(item.timestamp).toLocaleString()}</div>
      </div>`
    ).join('');
  }

  async function sendWake() {
    const input = $('#wake-input');
    const text = input.value.trim();
    if (!text) return;

    const sendBtn = $('#wake-send');
    
    try {
      sendBtn.classList.add('loading');
      
      // Send to the internal wake endpoint (which handles jarvis commands)
      await jfetch(API('internal/wake'), {
        method: 'POST',
        body: JSON.stringify({ text })  // bot.py will prepend "jarvis" automatically
      });
      
      addWakeToHistory(text);
      input.value = '';
      toast('Command executed', 'success');
      
    } catch (e) {
      console.error('Wake command error:', e);
      toast('Command failed: ' + e.message, 'error');
    } finally {
      sendBtn.classList.remove('loading');
    }
  }

  $('#wake-send').addEventListener('click', sendWake);
  $('#wake-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      sendWake();
    }
  });

  /* =============== PURGE FUNCTIONALITY =============== */
  const PURGE_KEY = 'jarvis_purge_days';
  
  function getDaysSel() {
    const v = ($('#purge-select')?.value || '7').trim();
    const n = parseInt(v, 10);
    return isNaN(n) ? 7 : n;
  }
  
  function saveDaysSel(n) {
    try { localStorage.setItem(PURGE_KEY, String(n)); } catch {}
    $('#purge-select') && ($('#purge-select').value = String(n));
    
    jfetch(API('api/inbox/settings'), {
      method: 'POST',
      body: JSON.stringify({ retention_days: n })
    }).catch(() => {});
  }
  
  function restoreDaysSel() {
    let v = 7;
    try {
      const s = localStorage.getItem(PURGE_KEY);
      if (s) v = parseInt(s, 10) || 7;
    } catch {}
    saveDaysSel(v);
  }
  
  async function runPurge(days) {
    const btn = $('#purge-now');
    try {
      btn.classList.add('loading');
      await jfetch(API('api/inbox/purge'), {
        method: 'POST',
        body: JSON.stringify({ days: Number(days) })
      });
      toast(`Purged messages older than ${days} day(s)`, 'success');
      await loadInbox();
    } catch (e) {
      toast('Purge failed: ' + e.message, 'error');
    } finally {
      btn.classList.remove('loading');
    }
  }

  $('#purge-select')?.addEventListener('change', () => saveDaysSel(getDaysSel()));
  $('#purge-now')?.addEventListener('click', () => runPurge(getDaysSel()));

  /* =============== LIVE UPDATES =============== */
  (function startStream() {
    let es = null, backoff = 1000;
    
    function connect() {
      try { es && es.close(); } catch {}
      
      updateSystemStatus('connecting', 'Connecting...');
      es = new EventSource(API('api/stream'));
      
      es.onopen = () => {
        backoff = 1000;
        updateSystemStatus('', 'Connected');
      };
      
      es.onerror = () => {
        try { es.close(); } catch {}
        updateSystemStatus('error', 'Reconnecting...');
        setTimeout(connect, Math.min(backoff, 15000));
        backoff = Math.min(backoff * 2, 15000);
      };
      
      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data || '{}');
          
          // Check if this is a chat response first
          if (data.event === 'created') {
            const isHandled = handleChatResponse(data);
            if (isHandled) {
              console.log('Chat response handled:', data);
              // Still refresh inbox but don't auto-select if chat handled it
              loadInbox();
              return;
            }
          }
          
          // Handle other inbox events
          if (['created', 'deleted', 'deleted_all', 'saved', 'purged'].includes(data.event)) {
            loadInbox().then(() => {
              if (data.event === 'created' && $('#pv-follow')?.checked) {
                if (data.id) selectRowById(data.id);
              }
            });
          }
        } catch {}
      };
    }
    
    connect();
    setInterval(loadInbox, 5 * 60 * 1000); // Refresh every 5 minutes
  })();

  /* =============== AUTO-RESIZE INPUTS =============== */
  $('#chat-input').addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
  });

  /* =============== INITIALIZATION =============== */
  restoreDaysSel();
  loadInbox();
  updateWakeHistory();
  
  // Show welcome message
  setTimeout(() => {
    toast('Jarvis Prime Control System initialized successfully', 'success');
  }, 1000);
})();
