# 🧩 Jarvis Prime — Home Assistant Add-on

Jarvis Prime is your standalone Notification Orchestrator and Server. It can run fully self-contained, or side-by-side with Gotify or ntfy for mobile review. It centralizes, beautifies, and orchestrates notifications from across your homelab, turning raw events into sleek, unified cards with personality. Jarvis listens to multiple intakes (SMTP, Proxy, Webhook), rewrites and beautifies messages, and pushes them back out through Gotify, ntfy, email, or its own dark-mode web UI.

Jarvis is not just a bridge — it is the core. It centralizes formatting, command handling, and orchestration of messages across your home systems. Every notification you throw at it arrives polished, consistent, and alive with personality.

Features
• Standalone Notification Orchestrator and Server (no Gotify required)  
• Optional review via Gotify or ntfy apps (mobile push, history, filters)  
• Beautify Engine (LLM + Aesthetic pipeline) to normalize and render events  
• SMTP Intake (Mailrise replacement): LAN-only, accepts any auth, subject/body → beautified  
• HTTP Proxy Intake (Gotify/ntfy): POST → beautified and optionally forwarded  
• Webhook Intake: POST /webhook, parses JSON or raw text (GitHub, health checks, generic)  
• Built-in dark-mode Web UI: inbox, filters, live updates, purge, retention, wakeword push  
• ARR module: Radarr/Sonarr counts, posters, upcoming events  
• Technitium DNS: totals, blocked, failures, live stats  
• Weather forecast: current and multi-day snapshot  
• Uptime Kuma: on-demand status (no duplicate alerts)  
• Multiple selectable personalities (The Dude, Chick, Nerd, Rager, Comedian, Action, Ops)  
• Purge & Retention: configurable lifecycle for messages  

Supported Sources
• Radarr / Sonarr → Posters, runtime, SxxEyy, quality, size  
• QNAP / Unraid → system/storage notices normalized  
• Watchtower → container update summaries  
• Speedtest → ping/down/up facts  
• Technitium DNS → blocking/failure stats  
• Weather forecast → current + multi-day  
• Uptime Kuma → status checks  
• JSON/YAML → parsed into bullet facts  
• Email → via SMTP intake  
• Gotify & ntfy → via proxy intake  
• Webhooks → POST events from any app or script  
• Generic text → framed as Jarvis Cards  

Webhook Intake Examples
Jarvis’ webhook endpoint is flexible. Send JSON or raw text and it will parse intelligently.

Generic text webhook:
curl -X POST http://10.0.0.100:2590/webhook \
  -H "Content-Type: text/plain" \
  -d 'Hello Jarvis, something happened on my server.'

JSON webhook:
curl -X POST http://10.0.0.100:2590/webhook \
  -H "Content-Type: application/json" \
  -d '{"title":"Backup Complete","message":"Proxmox node 1 finished nightly backup.","priority":7}'

GitHub style webhook (auto-detected by headers):
curl -X POST http://10.0.0.100:2590/webhook \
  -H "X-GitHub-Event: push" \
  -d '{"repository":"homeassistant","pusher":"Christoff"}'

Health check webhook:
curl -X POST http://10.0.0.100:2590/webhook \
  -H "X-Health-Check: true" \
  -d 'Service heartbeat OK'

Wake-Word & Commands
Wake-word is “Jarvis …” in the title or body. Examples:  
• Jarvis dns → DNS summary  
• Jarvis weather / forecast → Weather snapshot or forecast  
• Jarvis joke → One-liner  
• Jarvis upcoming movies / series, counts, longest → ARR queries  
• Jarvis help → Command list  

Configuration (options.json)
{
  "bot_name": "Jarvis Prime",
  "bot_icon": "🧠",
  "gotify_url": "http://YOUR_GOTIFY_HOST:8091",
  "gotify_client_token": "CLIENT_TOKEN",
  "gotify_app_token": "APP_TOKEN",
  "jarvis_app_name": "Jarvis",
  "retention_hours": 24,
  "beautify_enabled": true,
  "silent_repost": true,
  "smtp_enabled": true,
  "smtp_port": 2525,
  "proxy_enabled": true,
  "proxy_port": 2580,
  "webhook_enabled": true,
  "webhook_bind": "0.0.0.0",
  "webhook_port": 2590,
  "webhook_token": "",
  "weather_enabled": true,
  "radarr_enabled": true,
  "sonarr_enabled": true,
  "technitium_enabled": true,
  "uptimekuma_enabled": true
}

Ports
• 2525/tcp → SMTP intake (if enabled)  
• 2580/tcp → Proxy intake (Gotify/ntfy if enabled)  
• 2581/tcp → Web UI (Ingress)  
• 2590/tcp → Webhook intake (if enabled)  

File Map
• /app/bot.py → core brain  
• /app/beautify.py → beautify engine  
• /app/smtp_server.py → smtp intake  
• /app/proxy.py → proxy intake  
• /app/webhook_server.py → webhook intake  
• /app/arr.py → Radarr/Sonarr integration  
• /app/weather.py → Weather forecast  
• /app/technitium.py → DNS  
• /app/uptimekuma.py → Kuma  
• /app/personality.py → personality engine  
• /app/alias.py → command normalization  
• /data/options.json → configuration  
• /data/beautify_rules.yaml → optional custom rules  

Gotify/ntfy Review
Jarvis can run fully standalone with its own UI. But if you want mobile notifications, simply configure:  
• gotify_url + gotify_app_token → Jarvis will repost to Gotify  
• ntfy_url + ntfy_topic → Jarvis will repost to ntfy  
This way you can review messages via the Gotify or ntfy app while still keeping Jarvis as the core brain.

Roadmap
Jarvis Prime is evolving fast. Planned additions:  
• DNS + DHCP with ad-blocking module (TechNitium-lite)  
• Ansible-lite orchestration (run playbooks via SSH, schedule jobs, push logs into Jarvis Inbox)  
• Full WebUI rewrite to accommodate every option from config.json (UI-driven setup)  
• More integrations for homelab sources and monitoring  

Jarvis Prime is your fully flat standalone Notification Orchestrator and AI-driven Notification Server. It unifies every message, powers them with personality, and ensures your home notifications are sleek, reliable, and alive.