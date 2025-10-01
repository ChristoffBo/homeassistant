# 🧩 Jarvis Prime — Home Assistant Add-on

Jarvis Prime is a Unified Homelab Operations Platform

Jarvis Prime is your standalone Notification Orchestrator and Server. It centralizes, beautifies, and orchestrates notifications from across your homelab. Raw events come in through multiple intakes (SMTP, Proxy, Webhook, Apprise, Gotify, ntfy, WebSocket), are polished by the Beautify Engine, and are pushed back out through Gotify, ntfy, email, or its own sleek dark-mode Web UI. Every notification arrives consistent, enriched, and alive with personality. Jarvis now also includes a Chat lane: a pure chat channel into your local LLM (no riffs, no personas) that works alongside notifications when the LLM is enabled.

Features
• Standalone Notification Orchestrator and Server.  
• Optional review via Gotify or ntfy apps (push notifications, history, filters)  
• Beautify Engine (LLM + formatting pipeline) normalizes events into Jarvis Cards  
• SMTP Intake: drop-in Mailrise replacement, accepts LAN-only emails with any auth  
• HTTP Proxy Intake: accepts Gotify/ntfy POSTs and beautifies them  
• Webhook Intake: accepts plain text or JSON from scripts, GitHub, health checks, etc.  
• Apprise Intake: accepts Apprise client POSTs with token auth  
• WebSocket Intake: persistent bi-directional intake channel with token auth  
• Built-in dark-mode Web UI with inbox, filters, purge, retention, and live updates  
• ARR Module: Radarr/Sonarr posters, episode/movie facts, upcoming releases  
• DNS Module: Technitium DNS block stats, failures, totals  
• Weather Intake: current + multi-day snapshot  
• Uptime Kuma: status without duplicate noise  
• Multiple selectable personas: The Dude, Chick, Nerd, Rager, Comedian, Action, Ops  
• EnviroGuard: adaptive LLM throttle adjusts CPU use based on ambient temperature  
• Purge & Retention: configurable lifecycle for old messages  
• Chat Lane: pure LLM chat (no riff/persona), works via Gotify, ntfy, or Web UI when LLM is enabled  
• Chat Lane: Rag added, if you have set a long lived token and your Home Assistant url chat will now answer questions regarding your systems.  

Supported Sources
• Radarr / Sonarr → Posters, runtime, SxxEyy, quality, size  
• QNAP / Unraid → System/storage notices normalized  
• Watchtower → Container update summaries  
• Speedtest → Ping/down/up facts  
• Technitium DNS → Blocking/failure stats  
• Weather → Current + forecast  
• Uptime Kuma → Uptime checks  
• JSON/YAML → Parsed into Jarvis Cards  
• Email → Sent into SMTP intake  
• Gotify / ntfy → Via proxy intake  
• Webhooks → Generic POSTs  
• Apprise → POSTs from any Apprise client  
• WebSocket → Persistent WS connections for apps/agents  
• Plain text → Beautified into sleek cards  
• Chat → Direct LLM conversation (prefix with “chat …” or “talk …” in Gotify/ntfy or use Web UI chat tab)  

Intake Setup Details

1. SMTP Intake (Mailrise replacement)  
• Start Jarvis Prime and note the SMTP port (default 2525).  
• In your app (Duplicati, Proxmox, etc.), set SMTP server to 10.0.0.100 and port 2525.  
• Authentication: any username/password (ignored).  
• Subject = Jarvis Card title, body = Card body.  
• Example: configure Duplicati → Notifications → SMTP → server=10.0.0.100, port=2525.  

2. Webhook Intake  
• URL: http://10.0.0.100:2590/webhook  
• Accepts plain text or JSON.  
• Example plain text:  
  curl -X POST http://10.0.0.100:2590/webhook -H "Content-Type: text/plain" -d 'Backup finished'  
• Example JSON:  
  curl -X POST http://10.0.0.100:2590/webhook -H "Content-Type: application/json" -d '{"title":"Backup Complete","message":"Node 1 finished","priority":7}'  

3. Apprise Intake  
• URL: http://10.0.0.100:2591/intake/apprise/notify?token=YOUR_LONG_TOKEN  
• Place token into /data/options.json under "intake_apprise_token".  
• Example:  
  curl -X POST "http://10.0.0.100:2591/intake/apprise/notify?token=yourtoken" -H "Content-Type: application/json" -d '{"title":"Apprise Test","body":"Hello","type":"info"}'  

4. Gotify Intake (proxy)  
• URL: http://10.0.0.100:2580  
• Example:  
  curl -X POST "http://10.0.0.100:2580/message?token=YOUR_GOTIFY_APP_TOKEN" -H "Content-Type: application/json" -d '{"title":"Gotify Direct","message":"Hello from Gotify","priority":5}'  

5. ntfy Intake (proxy)  
• URL: http://10.0.0.100:2580/jarvis  
• Example:  
  curl -X POST "http://10.0.0.100:2580/jarvis" -H "Content-Type: text/plain" -d 'Hello from ntfy direct push'  

6. WebSocket Intake  
• URL: ws://10.0.0.100:8765/intake/ws?token=YOUR_WS_TOKEN  
• Configure your token in /data/options.json under "intake_ws_token".  
• Example test with websocat:  
  websocat "ws://10.0.0.100:8765/intake/ws?token=YOUR_WS_TOKEN"  
  {"title":"WS Test","message":"Hello from WebSocket","priority":5}  
• Jarvis will respond with {"status":"ok"} and forward to its pipeline.  
• Multiple clients can stay connected simultaneously.  

7. Chat Intake (Gotify/ntfy or Web UI)  
• Prefix your message with "chat" or "talk".  
• Example Gotify:  
  curl -X POST "http://10.0.0.100:2580/message?token=YOUR_GOTIFY_APP_TOKEN" -H "Content-Type: application/json" -d '{"title":"chat","message":"What is the difference between an i7 and i9 processor?"}'  
• Example ntfy:  
  curl -X POST "http://10.0.0.100:2580/jarvis" -H "Content-Type: text/plain" -d 'chat Explain the plot of Interstellar'  

Web UI Access  
• Ingress via Home Assistant → Add-on → Jarvis Prime → OPEN WEB UI.  
• Or direct browser: http://10.0.0.100:PORT.  
• Inbox view shows beautified cards with filters, retention, purge, and live updates.  
• Chat lane tab allows pure conversation with your LLM.  

Self-Hosting Statement  
Jarvis Prime is fully self-contained. Gotify, ntfy, and WebSocket are optional — use them only if you want push or persistent WS. The add-on runs standalone with its own intakes, Beautify Engine, personas, Chat lane, and dark-mode UI.
