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

---

## 🗺️ Atlas — Network Topology Visualization (New)

**Atlas** provides a **live, interactive topology map** of your entire homelab infrastructure — visually linking all hosts and services discovered by Orchestrator and Analytics.  
It renders using an offline local copy of **D3.js**, meaning it works entirely without internet access.

### How Atlas Works
- Reads live topology data from `/api/atlas/topology`.  
- Automatically merges host data from **Orchestrator** and service data from **Analytics**.  
- Displays connections as nodes (hosts, services, and core) with color-coded status.  
- Zoom and pan supported (mouse, touch, mobile-friendly).  
- Tooltips show IPs, groups, latency, and current state.  
- Refreshes automatically every 10 seconds when the Atlas tab is active.  
- Clicking a node is now **read-only** (no more 404s).  
- Works fully offline using `/share/jarvis_prime/ui/js/d3.v7.min.js`.  

### Legend
- 🟢 **Green** → Service or Host is healthy (`status: up`)  
- ⚪ **Gray** → Host detected but inactive or unreachable  
- 🔵 **Blue core** → Central Jarvis Prime node  

### Access
- Open the **Atlas tab** in the Web UI (`/ui/index.html`)  
- Uses the same dark theme as the rest of Jarvis Prime  
- No configuration required — data is auto-generated  

---

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

### 🧩 Sentinel Template Deduplication Behavior
Sentinel automatically **deduplicates templates** when loading from both sources:
- `/app/sentinel_templates` → GitHub defaults  
- `/share/jarvis_prime/sentinel/custom_templates` → Local overrides  
If a template with the same **`id`** and **`name`** exists in both locations, **the GitHub version is always kept**.  

---

### Chat & Intelligence
• Chat Lane: pure LLM chat (no riff/persona), works via Gotify, ntfy, or Web UI when LLM is enabled  
• RAG Integration: if you have set a long lived token and your Home Assistant URL, chat will now answer questions regarding your systems  

### Progressive Web App (PWA) Support
Jarvis Prime supports installation as a Progressive Web App (PWA), allowing app-like offline use with HTTPS, caching, and push notifications.  

---

## Supported Sources
Radarr / Sonarr, QNAP, Unraid, Watchtower, Speedtest, Technitium DNS, Weather, Uptime Kuma, JSON/YAML, Email, Gotify, ntfy, Webhooks, Apprise, WebSocket, plain text, Chat  

---

## Web UI Access
• Ingress via Home Assistant → Add-on → OPEN WEB UI  
• Or direct: http://10.0.0.100:PORT  

## Self-Hosting Statement
Jarvis Prime is fully self-contained. Gotify, ntfy, and WebSocket are optional — use them only if you want push or persistent WS.  

## Use Cases
Unified notification hub, automation command center, monitoring dashboard, and self-healing reliability engine in one platform.