# 🧩 Jarvis Prime — Home Assistant Add-on

**Jarvis Prime is a Unified Homelab Operations Platform**

Jarvis Prime is your standalone Notification Orchestrator, Automation Engine, Monitoring System, and Command Center. It centralizes, beautifies, and orchestrates notifications from across your homelab while providing powerful job scheduling, playbook execution, and real-time service monitoring capabilities. Raw events come in through multiple intakes (SMTP, Proxy, Webhook, Apprise, Gotify, ntfy, WebSocket), are polished by the Beautify Engine, and are pushed back out through Gotify, ntfy, email, or its own sleek dark-mode Web UI. Every notification arrives consistent, enriched, and alive with personality. Jarvis now also includes a Chat lane: a pure chat channel into your local LLM (no riffs, no personas) that works alongside notifications when the LLM is enabled.

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

### Analytics & Monitoring
• **Service Health Monitoring**: Real-time HTTP, TCP, and ICMP Ping endpoint checks  
• **Uptime Tracking**: 24-hour uptime percentage and response time metrics  
• **Incident Detection**: Automatic incident creation when services go down  
• **Health Score Dashboard**: Overall homelab health percentage with visual status cards  
• **Service Management**: Add, edit, enable/disable services via Web UI  
• **Configurable Checks**: Set custom intervals, timeouts, and expected status codes  
• **Multi-Protocol Support**: Monitor HTTP endpoints (with status code validation), TCP ports, or ICMP Ping hosts  
• **Incident History**: Track downtime incidents with duration and error details  
• **Visual Dashboard**: Service status cards showing current state, uptime %, avg response time  
• **Retries** – Each service must fail a configurable number of consecutive checks before being marked **DOWN**, filtering out temporary timeouts or network hiccups.  
• **Flap Window** – Defines the time window (in seconds) used to detect service instability; older state changes automatically expire outside this period.  
• **Flap Threshold** – Sets how many up/down flips are allowed within the flap window before the service is considered “flapping.”  
• **Suppression Duration** – When flapping exceeds the threshold, alerts for that service are automatically muted for a defined duration while metrics continue to be recorded.  
• **Flap Tracking & Recovery** – The system tracks every state change, applies suppression intelligently, and resumes normal alerting once the suppression window ends.  
• **Result:** clean, noise-free uptime data with zero false positives — enterprise-grade stability built in.  

## 🛡️ Sentinel — Self-Healing Monitoring Engine - Alpha Testing Stage

**Sentinel** is the autonomous self-healing and service-monitoring subsystem inside Jarvis Prime. It runs scheduled checks, performs automatic repairs, and tracks every action in a live dashboard.

### How Sentinel Works
Sentinel is a **manual-configuration monitoring system** — it only monitors what you tell it to.

1. **Add Servers (Servers Tab)**  
   - Add each SSH-enabled server you want monitored.  
   - Provide hostname/IP, port, and credentials.  
   - Example: “Production Server,” “Media Server,” “Database Server.”

2. **Review Templates (Templates Tab)**  
   - Templates define how to **check**, **repair**, and **verify** services.  
   - Pre-configured templates include Docker, Plex, Nginx, MySQL, Disk Usage, etc.  
   - You can create or upload custom templates as needed.

3. **Configure Monitoring (Monitoring Tab)**  
   - Assign specific templates to each server.  
   - Example:  
     - *Media Server*: Plex + Docker + Disk Usage  
     - *Web Server*: Nginx + Docker  
     - *Database Server*: MySQL only  

4. **Scheduling**  
   - Each check runs at your defined interval (default: 300 s).  
   - Sentinel retries failed checks before escalating.

### What Sentinel Does
- Executes service checks via SSH on schedule.  
- Runs automatic repair commands when failures are detected.  
- Verifies results and logs outcomes.  
- Maintains full execution history (checks, repairs, durations, results).  
- Integrates with Jarvis Prime notifications for alerts and summaries.

### Smart Features
- **Retry Logic** – Waits before rechecking to avoid false negatives.  
- **Escalation** – Progressive repair/alert sequence.  
- **Quiet Hours** – Suppresses low-priority alerts overnight.  
- **Maintenance Windows** – Temporarily pauses checks.  
- **Flap Detection** – Filters noisy up/down toggles.  
- **Dashboard Metrics** – Displays uptime %, failed repairs, and total checks.  

### Quick Start
1. Go to **Sentinel → Servers** → add your first server.  
2. Go to **Templates** → click **Sync from GitHub** to load default templates.  
3. Go to **Monitoring** → click **Add Monitoring**.  
4. Select the server, choose templates, set check interval (e.g. 300 s).  
5. Click **Start Monitoring**.  
6. Open the **Dashboard** for live service status and uptime stats.

### Example Setup
**Server 1: Media Server (192.168.1.100)**  
- ✅ Plex Media Server  
- ✅ Docker Engine  
- ✅ Disk Usage  

**Server 2: Web Server (192.168.1.101)**  
- ✅ Nginx  
- ✅ Docker Engine  

**Server 3: Database Server (192.168.1.102)**  
- ✅ MySQL  

### Common Questions
**Does Sentinel auto-detect installed services?**  
No — you choose which templates apply.  

**What if I monitor a service that isn’t installed?**  
That check will fail every time; deselect unused templates.  

**Can I make my own templates?**  
Yes — click *Create Template* to define custom `check`, `fix`, and `verify` commands.  

**Can I test a check immediately?**  
Yes — on the Dashboard, click **Check Now** beside any service.

### Monitor Packs
You can import the ready-to-use **Sentinel Monitor Pack** for 18+ essential checks:
- Disk & inode usage, log cleanup  
- Docker, Plex, SSH, Nginx  
- SMART, ZFS, RAID, Memory, Swap, CPU Load, Temperature  
- APT updates, WireGuard, Proxmox core services, `/var` usage  
Download: `sentinel_monitor_pack.json` and import via *Templates → Upload Template*.  

### File Locations
Replace these in your Jarvis add-on build if updating manually:
- `/app/www/js/sentinel.js` – UI logic  
- `/app/www/index.html` – monitor-form bindings  

### Summary
Sentinel adds **automated self-healing**, **manual service selection**, and a **real-time dark-mode dashboard** to Jarvis Prime — turning it from a monitoring dashboard into a full **homelab reliability engine**.

### Chat & Intelligence
• Chat Lane: pure LLM chat (no riff/persona), works via Gotify, ntfy, or Web UI when LLM is enabled  
• RAG Integration: if you have set a long lived token and your Home Assistant URL, chat will now answer questions regarding your systems  

### Progressive Web App (PWA) Support
Jarvis Prime includes support for installation as a Progressive Web App (PWA). This allows you to add Jarvis directly to your home screen or desktop and run it like a native application with its own window and icon. The PWA includes offline caching, automatic updates via service worker, and notification support.  
**Setup Instructions:**  
1. Ensure Jarvis is served over **HTTPS** (via Home Assistant Ingress or a reverse proxy with a valid certificate).  
2. Confirm that the included `manifest.json` and `service-worker.js` are being served from the Jarvis web root.  
3. Open Jarvis in Chrome/Edge/Android/iOS Safari. You should see an “Install App” or “Add to Home Screen” option.  
4. After installation, Jarvis runs as a standalone app with its own icon (using `logo.png`).  
**Benefits:**  
• Secure HTTPS app-like access from any device  
• One-click launch with persistent login  
• Offline fallback support via caching  
• Automatic background updates  
• Push notification support for future expansion  

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

## LLM Best Practices & Tested Settings
Jarvis Prime supports Phi-3.5, Phi-4 Q4, Q5, Q6, Q8 for chat, riffs, and message beautification. These settings balance **performance, coherence, memory use, and response length**.

### Recommended Settings by Model
| Model | Context Window (CTX) | Riff Max Tokens | Riff Cutoff Tokens | Message Rewrite Max Tokens | Notes |
|--------|------------------|-----------------|-----------------|------------------------|------|
| Phi-3.5 | 4096 | 50 | 45 | 45 | Lightweight; low memory. |
| Phi-4 Q4 | 8000 | 55 | 50 | 50 | Better context, moderate CPU. |
| Phi-4 Q5 | 12000 | 60 | 55 | 50 | Recommended balance. |
| Phi-4 Q6 | 12000 | 60 | 55 | 50 | Higher memory. |
| Phi-4 Q8 | 12000 | 60 | 55 | 50 | Heaviest but most precise. |

## Intake Setup Details
1. SMTP Intake: port 2525, LAN-only, accepts any auth  
2. Webhook Intake: http://10.0.0.100:2590/webhook  
3. Apprise Intake: http://10.0.0.100:2591/intake/apprise/notify?token=YOUR_TOKEN  
4. Gotify Proxy: http://10.0.0.100:2580  
5. ntfy Proxy: http://10.0.0.100:2580/jarvis  
6. WebSocket Intake: ws://10.0.0.100:8765/intake/ws?token=YOUR_TOKEN  
7. Chat Intake: prefix messages with “chat” or “talk”  

## Orchestration Setup
1. Go to Orchestrator tab → Add servers → Test connectivity  
2. Upload playbooks/scripts to `/share/jarvis_prime/playbooks/`  
3. Run jobs manually or schedule with cron-style intervals  
4. View job history, logs, duration, and results  

## Analytics & Monitoring Setup
1. Open Analytics → Services → Add Service  
2. Configure endpoints (HTTP/TCP/ICMP), intervals, and timeouts  
3. Save → Dashboard updates automatically  
4. View uptime %, response time, incident logs  

## Web UI Access
• Ingress via Home Assistant → Add-on → OPEN WEB UI  
• Or direct: http://10.0.0.100:PORT  

## Self-Hosting Statement
Jarvis Prime is fully self-contained. Gotify, ntfy, and WebSocket are optional — use them only if you want push or persistent WS.  

## Use Cases
Unified notification hub, automation command center, monitoring dashboard, and self-healing reliability engine in one platform.
