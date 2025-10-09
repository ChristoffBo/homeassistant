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

### Advanced Reliability Logic (Anti-Flap & Retries)
• **Retries** – Each service must fail a configurable number of consecutive checks before being marked **DOWN**, filtering out temporary timeouts or network hiccups.  
• **Flap Window** – Defines the time window (in seconds) used to detect service instability; older state changes automatically expire outside this period.  
• **Flap Threshold** – Sets how many up/down flips are allowed within the flap window before the service is considered “flapping.”  
• **Suppression Duration** – When flapping exceeds the threshold, alerts for that service are automatically muted for a defined duration while metrics continue to be recorded.  
• **Flap Tracking & Recovery** – The system tracks every state change, applies suppression intelligently, and resumes normal alerting once the suppression window ends.  
• **Result:** clean, noise-free uptime data with zero false positives — enterprise-grade stability built in.  

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
| Model       | Context Window (CTX) | Riff Max Tokens | Riff Cutoff Tokens | Message Rewrite Max Tokens | Notes |
|------------|--------------------|----------------|-----------------|---------------------------|------|
| Phi-3.5    | 4,096              | 50             | 45              | 45                        | Lightweight, good for smaller systems; less context retention. |
| Phi-4 Q4   | 8,000              | 55             | 50              | 50                        | Better context than 3.5; slightly slower on CPU. |
| Phi-4 Q5   | 12,000             | 60             | 55              | 50                        | Recommended sweet spot: fast, coherent, large context. |
| Phi-4 Q6   | 12,000             | 60             | 55              | 50                        | Slightly higher memory usage than Q5; similar output quality. |
| Phi-4 Q8   | 12,000             | 60             | 55              | 50                        | Highest memory usage; may slow on low-resource systems. |

### What Each Setting Does
- **Context Window (CTX)**: Number of prior tokens the model “remembers”; larger CTX preserves more conversation/notification history.  
- **Riff Max Tokens**: Maximum tokens for generated riffs; model stops naturally if fewer are needed.  
- **Cutoff Tokens**: Optional buffer to avoid mid-thought truncation.  
- **Message Rewrite Max Tokens**: Limits length of rewrites; ensures concise, polished output.  

### Middle-Ground Recommendation
For most users on moderate hardware:  
- **Model**: Phi-4 Q5  
- **CTX**: 12,000  
- **Riff Max Tokens**: 60  
- **Cutoff Tokens**: 55  
- **Message Rewrite Max Tokens**: 50  

This combination provides **good performance, coherent responses, and avoids excessive CPU/memory use**.

## Intake Setup Details
### 1. SMTP Intake (Mailrise replacement)
• Start Jarvis Prime and note the SMTP port (default 2525)  
• In your app (Duplicati, Proxmox, etc.), set SMTP server to 10.0.0.100 and port 2525  
• Authentication: any username/password (ignored)  
• Subject = Jarvis Card title, body = Card body  

### 2. Webhook Intake
• URL: http://10.0.0.100:2590/webhook  
• Accepts plain text or JSON  

### 3. Apprise Intake
• URL: http://10.0.0.100:2591/intake/apprise/notify?token=YOUR_LONG_TOKEN  

### 4. Gotify Intake (proxy)
• URL: http://10.0.0.100:2580  

### 5. ntfy Intake (proxy)
• URL: http://10.0.0.100:2580/jarvis  

### 6. WebSocket Intake
• URL: ws://10.0.0.100:8765/intake/ws?token=YOUR_WS_TOKEN  

### 7. Chat Intake (Gotify/ntfy or Web UI)
• Prefix your message with "chat" or "talk"  

## Orchestration Setup
### Server Management
1. Navigate to the **Orchestrator** tab in the Web UI  
2. Add SSH-enabled servers, groups, and test connectivity  

### Playbook Management
• Upload `.yml`, `.sh`, `.py` playbooks to `/share/jarvis_prime/playbooks/`  

### Running Jobs
• Select playbook, choose server/group, run now or schedule, see live logs  

### Job History
• View executions, status, logs, durations, purge old history  

## Analytics & Monitoring Setup
### Adding Services to Monitor
1. Navigate to the **Analytics** tab in the Web UI  
2. Click **Services** sub-tab  
3. Click **Add Service** button  
4. Configure service:  
   - **Service Name**: Friendly name (e.g., "Home Assistant", "Plex", "Proxmox")  
   - **Endpoint**:  
     - HTTP: Full URL (http://homeassistant.local:8123)  
     - TCP: host:port (192.168.1.100:22)  
     - ICMP Ping: hostname or IP (192.168.1.1)  
   - **Check Type**: HTTP, TCP, or ICMP Ping  
   - **Expected Status Code**: For HTTP checks, specify expected code (default: 200)  
   - **Check Interval**: How often to check in seconds (minimum 10, recommended 60+)  
   - **Timeout**: How long to wait before marking as failed (1-30 seconds)  
   - **Enabled**: Toggle monitoring on/off  
5. Click **Save Service**  

### Monitoring Dashboard
• **Health Score**: Overall homelab health percentage (99%+ = excellent, 95-99% = good, 90-95% = fair, <90% = poor)  
• **Service Cards**: Visual status cards showing current status, last check, uptime %, avg response time  
• **Auto-Refresh**: Dashboard updates every 30 seconds automatically  

### Incident Management
• **Automatic Detection**: Incidents created automatically when services go down  
• **Auto-Resolution**: Incidents resolved when services come back up  
• **Incident History**: View last 7 days of incidents with service name, timestamps, duration, error message  

### Example Monitored Services
Home Assistant → http://homeassistant.local:8123 (HTTP)  
Plex Media Server → http://plex.local:32400 (HTTP)  
Proxmox → https://proxmox.local:8006 (HTTP, expects 200)  
SSH Server → 192.168.1.10:22 (TCP)  
Radarr → http://radarr.local:7878 (HTTP)  
Sonarr → http://sonarr.local:8989 (HTTP)  
PostgreSQL → 192.168.1.20:5432 (TCP)  
Redis → 192.168.1.20:6379 (TCP)  
WiFi Router → 192.168.1.1 (ICMP Ping)  

## Web UI Access
• Ingress via Home Assistant → Add-on → Jarvis Prime → OPEN WEB UI  
• Or direct browser: http://10.0.0.100:PORT  

## Self-Hosting Statement
Jarvis Prime is fully self-contained. Gotify, ntfy, and WebSocket are optional — use them only if you want push or persistent WS.  

## Use Cases
Notification orchestration, infrastructure automation, service monitoring (HTTP/TCP/ICMP Ping), and LLM chat in one platform.

**Jarvis Prime**: Your homelab's unified notification hub, automation command center, and monitoring dashboard.