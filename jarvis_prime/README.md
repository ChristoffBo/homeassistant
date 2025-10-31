🧩 Jarvis Prime — Home Assistant Add-on
Jarvis Prime is a Unified Homelab Operations Platform

Jarvis Prime is your standalone Notification Orchestrator, Automation Engine, Monitoring System, and Command Center. It centralizes, beautifies, and orchestrates notifications from across your homelab while providing powerful job scheduling, playbook execution, and real-time service monitoring capabilities. Raw events come in through multiple intakes (SMTP, Proxy, Webhook, Apprise, Gotify, ntfy, WebSocket), are polished by the Beautify Engine, and are pushed back out through Gotify, ntfy, email, or its own sleek dark-mode Web UI. Every notification arrives consistent, enriched, and alive with personality. Jarvis now also includes a Chat lane: a pure chat channel into your local LLM (no riffs, no personas) that works alongside notifications when the LLM is enabled.

Jarvis Prime now includes a built-in authentication system that protects both the Web UI and API. On first startup, an Initial Setup overlay appears prompting you to create a username and password. Credentials are stored securely in /data/users.json with full encryption and password hashing. Once logged in, your session remains active for one hour of inactivity before automatically logging out for security. If the credentials file is deleted, Jarvis automatically recreates a default admin account on the next startup.

✅ Features

Notification System
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
• Weather Intake: current conditions + multi-day snapshot
• Uptime Kuma: status without duplicate noise
• Multiple selectable personas: The Dude, Chick, Nerd, Rager, Comedian, Action, Ops
• EnviroGuard: adaptive LLM throttle adjusts CPU use based on ambient temperature
• Purge & Retention: configurable lifecycle for old messages

Orchestration & Automation
• Job Orchestration: Run playbooks, scripts, and commands across your infrastructure
• Playbook Management: Upload and organize Ansible playbooks, shell scripts, and Python scripts
• Server Inventory: Manage SSH-enabled servers with groups and descriptions
• Scheduling: Cron-based job scheduling with flexible timing (every 5 minutes to yearly)
• Live Execution Logs: Real-time WebSocket streaming of job output
• Job History: Track all executions with status, duration, and full logs
• Manual Execution: Run any playbook on-demand against any server or group
• Notification Integration: Optional notifications on job completion (can be disabled for frequent jobs)
• Multi-Runner Support: Execute Ansible playbooks (.yml), shell scripts (.sh), or Python scripts (.py)

Analytics & Monitoring
• Service Health Monitoring: Real-time HTTP, TCP, and ICMP Ping endpoint checks
• Uptime Tracking: 24-hour uptime percentage and response time metrics
• Incident Detection: Automatic incident creation when services go down
• Health Score Dashboard: Overall homelab health percentage with visual status cards
• Service Management: Add, edit, enable/disable services via Web UI
• Configurable Checks: Set custom intervals, timeouts, and expected status codes
• Multi-Protocol Support: Monitor HTTP endpoints (with status code validation), TCP ports, or ICMP Ping hosts
• Incident History: Track downtime incidents with duration and error details
• Visual Dashboard: Service status cards showing current state, uptime %, avg response time
• Retries – Each service must fail a configurable number of consecutive checks before being marked DOWN, filtering out temporary timeouts or network hiccups
• Flap Window – Defines the time window (in seconds) used to detect service instability; older state changes automatically expire outside this period
• Flap Threshold – Sets how many up/down flips are allowed within the flap window before the service is considered “flapping”
• Suppression Duration – When flapping exceeds the threshold, alerts for that service are automatically muted for a defined duration while metrics continue to be recorded
• Flap Tracking & Recovery – The system tracks every state change, applies suppression intelligently, and resumes normal alerting once the suppression window ends
• Result – Clean, noise-free uptime data with zero false positives — enterprise-grade stability built in
• Network Intelligence – Adds local network scanning and device awareness. Jarvis discovers active devices on your LAN via ARP/IP, recording MAC, IP, vendor, and hostname. Newly seen devices trigger notifications; monitored ones are tracked for uptime. Promote any device to an Analytics service with one click for automated ping checks
• Continuous Scanning – Background scans run automatically at intervals and handle retries gracefully
• Offline Detection – Monitored devices are flagged if not seen for a defined period
• Network Stats Dashboard – Totals for discovered devices, monitored devices, and recent scan activity
• API – Network scan/device operations under /api/analytics/network/*
• Internet Speed Monitoring – Integrated Ookla Speedtest CLI. Scheduled tests record download, upload, ping, jitter, and server info. Trend analysis detects degradations or recoveries, with optional Gotify/ntfy alerts. Results charted in Analytics with full purge options. Interval is user-adjustable. All data persisted in SQLite

🗺️ Atlas — Network Topology Visualization (New)
Atlas provides a live, interactive topology map of your entire homelab infrastructure — visually linking all hosts and services discovered by Orchestrator and Analytics. It renders using an offline local copy of D3.js, so it works entirely without internet access.
How Atlas Works
• Reads live topology data from /api/atlas/topology
• Merges host data from Orchestrator and service data from Analytics
• Displays nodes (hosts, services, core) with color-coded status
• Zoom and pan supported (mouse, touch, mobile-friendly)
• Tooltips show IPs, groups, latency, and current state
• Auto-refresh every 10 seconds when Atlas tab is active
• Works fully offline
Legend
• 🟢 Green → Service/Host healthy (up)
• ⚪ Gray → Host detected but inactive or unreachable
• 🔵 Blue core → Central Jarvis Prime node
Access
• Open the Atlas tab in the Web UI (/ui/index.html)
• Uses the same dark theme as the rest of Jarvis Prime
• No configuration required — data is auto-generated

🛡️ Sentinel — Self-Healing Monitoring Engine (Alpha Testing)
Sentinel is the autonomous self-healing subsystem. It runs scheduled checks, performs automatic repairs, and tracks every action in a live dashboard.
How Sentinel Works
• Sentinel monitors only what you configure (manual opt-in)
Add Servers (Servers Tab)
• Add each SSH-enabled server with hostname/IP, port, and credentials
Templates (Templates Tab)
• Templates define how to check, repair, and verify services
• Pre-configured templates include Docker, Plex, Nginx, MySQL, Disk Usage, etc.
• You can create or upload custom templates
Configure Monitoring (Monitoring Tab)
• Assign templates per server (e.g., Media Server: Plex + Docker + Disk Usage)
Scheduling
• Each check runs at your defined interval (default 300 s) with retries before escalation
What Sentinel Does
• Executes checks via SSH on schedule
• Runs automated repair commands on failures
• Verifies results, logs outcomes, and maintains full execution history
• Integrates with Jarvis notifications for alerts/summaries
Smart Features
• Retry Logic, Escalation, Quiet Hours, Maintenance Windows, Flap Detection
• Dashboard metrics: uptime %, failed repairs, total checks
Sentinel Template Deduplication
• Templates are loaded from two locations:
  /app/sentinel_templates (GitHub defaults)
  /share/jarvis_prime/sentinel/custom_templates (Local overrides)
• If same id+name exists in both, the GitHub version is kept

🧩 Backup Module — Agentless Backup & Restore Engine (New)
The Backup Module provides full agentless backup and restore across your infrastructure using SSH, SMB, and NFS. It replaces duplicati-style tools with a transparent, verifiable system integrated into Jarvis Prime.
What It Does
• Creates compressed archives (tar.gz) or streams disk images (dd over SSH)
• Stores per-job metadata: start/end time, duration, size, checksum, status
• Sends fan-out notifications to Gotify/ntfy/UI with job summaries and errors
• Runs asynchronously in its own process — no UI blocking
• Offers a UI file explorer to browse remote hosts and archives
• Supports restore to original location or a new path/host
• Supports cloud/NAS restores via the same protocol used to store backups
How It Works
• Define jobs with:
  - name, source paths (local or remote via SSH), destination path (local/NAS/SMB/NFS/cloud mount)
  - schedule (cron), retention policy, compression (on/off), exclude patterns, bandwidth limits
• For file backups: archives are tar.gz with stable, timestamped names
• For disk images: dd over SSH writes to destination with progress and integrity checks
• Retention: per-job pruning keeps last N or age-based windows while protecting most-recent success
• Restore Mode:
  - File restore: choose archive → target host/path → original or new location → restore
  - Image restore: pick image → target block device over SSH → streamed write with confirmation
• Import Existing Backups: point to a directory to index and manage prior archives in the UI
• Safety:
  - Dry-run previews file lists for file backups
  - Confirmations for destructive image writes
  - Disk size and device guardrails for dd restores
• All operations log to SQLite and surface in the UI with status, duration, and size
Result
• A fully self-contained, agentless backup system with visual management, multi-protocol support, restore automation, and real-time notifications — no external dependencies required

Chat & Intelligence
• Chat Lane: pure LLM chat (no riffs/personas), available via Gotify, ntfy, or Web UI when LLM is enabled
• RAG Integration: if you set a long lived token and your Home Assistant URL, chat can answer questions about your systems

Progressive Web App (PWA) Support
• Installable web app with offline caching and push capabilities (requires HTTPS)

Supported Sources
• Radarr / Sonarr, QNAP, Unraid, Watchtower, Speedtest, Technitium DNS, Weather, Uptime Kuma, JSON/YAML, Email, Gotify, ntfy, Webhooks, Apprise, WebSocket, plain text, Chat

🌍 Web UI Access
• Ingress via Home Assistant → Add-on → OPEN WEB UI
• Or direct: http://10.0.0.100:PORT

🧠 Self-Hosting Statement
• Jarvis Prime is fully self-contained. Gotify, ntfy, and WebSocket are optional — enable them only if you want push or persistent WS

Use Cases
• Unified notification hub, automation command center, monitoring dashboard, self-healing reliability engine, and agentless backup/restore system — all in one platform
