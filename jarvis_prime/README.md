🧩 Jarvis Prime — Home Assistant Add-on
Jarvis Prime is in deep ALPHA and work is ongoing
Jarvis Prime is your standalone Notification Orchestrator and Server. Now with real AI builtin. It is a fully flat, self-sufficient notification hub that runs inside Home Assistant. Jarvis Prime is not bound to Gotify — it supports Gotify, ntfy, email, and includes its own web UI. This means you can centralize, beautify, and orchestrate all your notifications in one place. It listens to incoming messages, beautifies them into sleek AI-style cards, reposts them to your chosen outputs, and responds to wake-word commands like “Jarvis weather” or “Jarvis dns”. Jarvis Prime includes a seven-layer Beautify Engine, a LAN SMTP intake (Mailrise replacement), a lightweight HTTP proxy for Gotify/ntfy, and a full modern web UI. Every notification you throw at it arrives polished, consistent, and alive with personality.

What it is and what it does
Jarvis Prime is more than a bridge — it is the core. A standalone Notification Orchestrator and Server that centralizes all formatting, command handling, and orchestration of messages across your home systems. It runs a seven-layer Beautify Engine to normalize, interpret, and render heterogeneous notifications into clean, unified AI-styled cards. It includes built-in wake-word command handling, live weather and DNS stats, ARR insights, and uptime checks. Jarvis Prime operates as your **home notification brain**, either fully standalone or integrated with Gotify, ntfy, and Home Assistant side by side.

Features
• Standalone Notification Orchestrator and Server
• Unified Beautify Engine (7 layers: ingest → detect → normalize → interpret → render → de-dupe → image restore)
• Out-of-the-box beautification for ARR (Radarr/Sonarr), QNAP/Unraid, Watchtower, Speedtest, JSON/YAML, DNS, Weather, Kuma, generic text
• Optional rules file /data/beautify_rules.yaml to extend beautification without coding
• Consistent Jarvis Card look with interpretation line
• SMTP Intake (Mailrise replacement): LAN-only, accepts any auth, subject/body → beautified
• HTTP Proxy Intake (Gotify/ntfy): POST /gotify or /ntfy, beautified and optionally forwarded
• Built-in dark-mode Web UI: inbox, filters, live updates, purge, retention, wakeword push
• ARR module: Radarr/Sonarr counts, posters, upcoming events
• Technitium DNS: totals, blocked, failures, live stats
• Weather forecast: current and multi-day snapshot
• Uptime Kuma: on-demand status (no duplicate alerts)
• Seven selectable personalities (eg. The Dude, AI assistant, serious ops, etc.)
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
• Generic text → framed as Jarvis Cards

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
  "personality": "The Dude",
  "smtp_enabled": true,
  "smtp_port": 2525,
  "proxy_enabled": true,
  "proxy_port": 8099,
  "weather_enabled": true,
  "radarr_enabled": true,
  "sonarr_enabled": true,
  "technitium_enabled": true,
  "uptimekuma_enabled": true
}

Ports
• 2525/tcp → SMTP intake (if enabled)
• 8099/tcp → Proxy intake (if enabled)

File Map
• /app/bot.py → core brain
• /app/beautify.py → beautify engine
• /app/smtp_server.py → smtp intake
• /app/proxy.py → proxy intake
• /app/arr.py → Radarr/Sonarr integration
• /app/weather.py → Weather forecast
• /app/technitium.py → DNS
• /app/uptimekuma.py → Kuma
• /app/personality.py → personality engine with 7 selectable personas
• /app/alias.py → command normalization
• /data/options.json → configuration
• /data/beautify_rules.yaml → optional custom rules

Jarvis Prime is your fully flat standalone Notification Orchestrator and AI-driven Notification Server. It unifies every message, powers them with personality, and ensures your home notifications are sleek, reliable, and alive.
