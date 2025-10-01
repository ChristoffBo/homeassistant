# 🧩 Jarvis Prime — Home Assistant Add-on

**Jarvis Prime is a Unified Homelab Operations Platform**

Jarvis Prime is your standalone Notification Orchestrator, Automation Engine, and Command Center. It centralizes, beautifies, and orchestrates notifications from across your homelab while providing powerful job scheduling and playbook execution capabilities. Raw events come in through multiple intakes (SMTP, Proxy, Webhook, Apprise, Gotify, ntfy, WebSocket), are polished by the Beautify Engine, and are pushed back out through Gotify, ntfy, email, or its own sleek dark-mode Web UI. Every notification arrives consistent, enriched, and alive with personality. Jarvis now also includes a Chat lane: a pure chat channel into your local LLM (no riffs, no personas) that works alongside notifications when the LLM is enabled.

## Features

### Notification System
• Standalone Notification Orchestrator and Server  
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

### Orchestration & Automation
• **Job Orchestration**: Run playbooks, scripts, and commands across your infrastructure  
• **Playbook Management**: Upload and organize Ansible playbooks, shell scripts, and Python scripts  
• **Server Inventory**: Manage SSH-enabled servers with groups and descriptions  
• **Scheduling**: Cron-based job scheduling with flexible timing (every 5 minutes to yearly)  
• **Live Execution Logs**: Real-time WebSocket streaming of job output  
• **Job History**: Track all executions with status, duration, and full logs  
• **Manual Execution**: Run any playbook on-demand against any server or group  
• **Notification Integration**: Optional notifications on job completion (can be disabled for frequent jobs)  
• **Multi-Runner Support**: Execute Ansible playbooks (.yml), shell scripts (.sh), or Python scripts (.py)  

### Chat & Intelligence
• Chat Lane: pure LLM chat (no riff/persona), works via Gotify, ntfy, or Web UI when LLM is enabled  
• RAG Integration: if you have set a long lived token and your Home Assistant URL, chat will now answer questions regarding your systems  

## Supported Sources

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
• Chat → Direct LLM conversation (prefix with "chat …" or "talk …" in Gotify/ntfy or use Web UI chat tab)  

## Intake Setup Details

### 1. SMTP Intake (Mailrise replacement)
• Start Jarvis Prime and note the SMTP port (default 2525)  
• In your app (Duplicati, Proxmox, etc.), set SMTP server to 10.0.0.100 and port 2525  
• Authentication: any username/password (ignored)  
• Subject = Jarvis Card title, body = Card body  
• Example: configure Duplicati → Notifications → SMTP → server=10.0.0.100, port=2525  

### 2. Webhook Intake
• URL: http://10.0.0.100:2590/webhook  
• Accepts plain text or JSON  
• Example plain text:  
```bash
curl -X POST http://10.0.0.100:2590/webhook \
  -H "Content-Type: text/plain" \
  -d 'Backup finished'
```
• Example JSON:  
```bash
curl -X POST http://10.0.0.100:2590/webhook \
  -H "Content-Type: application/json" \
  -d '{"title":"Backup Complete","message":"Node 1 finished","priority":7}'
```

### 3. Apprise Intake
• URL: http://10.0.0.100:2591/intake/apprise/notify?token=YOUR_LONG_TOKEN  
• Place token into /data/options.json under "intake_apprise_token"  
• Example:  
```bash
curl -X POST "http://10.0.0.100:2591/intake/apprise/notify?token=yourtoken" \
  -H "Content-Type: application/json" \
  -d '{"title":"Apprise Test","body":"Hello","type":"info"}'
```

### 4. Gotify Intake (proxy)
• URL: http://10.0.0.100:2580  
• Example:  
```bash
curl -X POST "http://10.0.0.100:2580/message?token=YOUR_GOTIFY_APP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Gotify Direct","message":"Hello from Gotify","priority":5}'
```

### 5. ntfy Intake (proxy)
• URL: http://10.0.0.100:2580/jarvis  
• Example:  
```bash
curl -X POST "http://10.0.0.100:2580/jarvis" \
  -H "Content-Type: text/plain" \
  -d 'Hello from ntfy direct push'
```

### 6. WebSocket Intake
• URL: ws://10.0.0.100:8765/intake/ws?token=YOUR_WS_TOKEN  
• Configure your token in /data/options.json under "intake_ws_token"  
• Example test with websocat:  
```bash
websocat "ws://10.0.0.100:8765/intake/ws?token=YOUR_WS_TOKEN"
{"title":"WS Test","message":"Hello from WebSocket","priority":5}
```
• Jarvis will respond with {"status":"ok"} and forward to its pipeline  
• Multiple clients can stay connected simultaneously  

### 7. Chat Intake (Gotify/ntfy or Web UI)
• Prefix your message with "chat" or "talk"  
• Example Gotify:  
```bash
curl -X POST "http://10.0.0.100:2580/message?token=YOUR_GOTIFY_APP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"chat","message":"What is the difference between an i7 and i9 processor?"}'
```
• Example ntfy:  
```bash
curl -X POST "http://10.0.0.100:2580/jarvis" \
  -H "Content-Type: text/plain" \
  -d 'chat Explain the plot of Interstellar'
```

## Orchestration Setup

### Server Management
1. Navigate to the **Orchestrator** tab in the Web UI
2. Click **Manage Servers** to add SSH-enabled servers
3. Provide: name, hostname/IP, username, password, port (default 22)
4. Optional: assign servers to groups (e.g., "proxmox", "docker-hosts", "production")
5. Test connectivity with the **Test** button

### Playbook Management
1. Upload playbooks via the **Upload Playbook** button
2. Supported formats: `.yml` (Ansible), `.sh` (shell scripts), `.py` (Python scripts)
3. Playbooks are stored in `/share/jarvis_prime/playbooks/`
4. View, delete, or execute playbooks from the playbook list

### Running Jobs
**Manual Execution:**
1. Select a playbook from the list
2. Choose target server or server group
3. Click **Run Now** to execute immediately
4. Watch live logs stream in real-time via WebSocket

**Scheduled Execution:**
1. Click **Schedule Job** on any playbook
2. Provide a schedule name and description
3. Select frequency: every 5/10/15/30 minutes, hourly, daily, weekly, monthly, or yearly
4. Choose specific time/day as needed
5. Select target server or group
6. Toggle **Send notifications** (disable for frequent health checks)
7. Schedules run automatically in the background

### Job History
• View all past executions with status (success/failed/running)
• Filter by playbook or status
• Review full execution logs for troubleshooting
• Track execution duration and timestamps
• Purge old history by criteria (all, failed, completed, older than 30/90 days)

## Web UI Access

• Ingress via Home Assistant → Add-on → Jarvis Prime → OPEN WEB UI  
• Or direct browser: http://10.0.0.100:PORT  
• **Inbox** tab: shows beautified cards with filters, retention, purge, and live updates  
• **Chat** tab: pure conversation with your LLM  
• **Orchestrator** tab: manage servers, playbooks, schedules, and view execution logs  

## Self-Hosting Statement

Jarvis Prime is fully self-contained. Gotify, ntfy, and WebSocket are optional — use them only if you want push or persistent WS. The add-on runs standalone with its own intakes, Beautify Engine, personas, Chat lane, Orchestration engine, and dark-mode UI. All functionality works offline without external dependencies.

## Use Cases

**Notification Orchestration:**
• Aggregate alerts from Proxmox, Unraid, Docker, monitoring tools
• Beautify and normalize disparate notification formats
• Review notifications in a unified inbox with intelligent filtering

**Infrastructure Automation:**
• Schedule health checks across server fleet
• Automate backup verification scripts
• Deploy configuration updates via Ansible playbooks
• Execute maintenance tasks on cron schedules
• Monitor job execution with detailed history and logs

**Intelligent Operations:**
• Chat with LLM about your Home Assistant entities
• Get natural language answers about system state
• Combine notifications with automation in one platform

---

**Jarvis Prime**: Your homelab's unified notification hub and automation command center.