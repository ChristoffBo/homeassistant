🧩 Jarvis Prime — Home Assistant Add-on  
Jarvis Prime is in deep ALPHA and work is ongoing  
Jarvis Prime is your Notification AI. Now with real AI builtin. It is a fully flat standalone Notification Orchestrator and Server that runs inside Home Assistant. Jarvis Prime is not bound to Gotify — it supports Gotify, ntfy, email, and includes its own web UI so you can centralize, beautify, and orchestrate all your notifications. It listens to incoming messages, beautifies them into sleek AI-style cards, reposts them to your chosen outputs, and responds to wake-word commands like “Jarvis weather” or “Jarvis dns”. Prime includes a unified Beautify Engine, a LAN SMTP intake (Mailrise replacement), a lightweight HTTP proxy for Gotify/ntfy, and a full web-based notification UI. Everything you throw at it arrives polished and consistent.  

What it is and what it does  
Jarvis Prime is a notification orchestrator. It centralizes formatting, command handling, and adds character to your notifications. It runs a seven-layer Beautify Engine to standardize style across heterogeneous sources, whether they arrive from Gotify, ntfy, email (SMTP), or the integrated proxy. It includes wake-word commands, live weather forecast, and optional heartbeat. Jarvis Prime can operate standalone as your home notification hub, or integrate with Gotify, ntfy, and Home Assistant side by side.  

Features  
• Unified Beautify Engine (7 layers: ingest → detect → normalize → interpret → render → de-dupe → image restore)  
• Works out-of-the-box for unknown senders, with built-ins for ARR (Radarr/Sonarr), QNAP/Unraid, Watchtower, Speedtest, JSON/YAML, DNS, Weather, generic text  
• Optional rules file /data/beautify_rules.yaml to add detectors/extractors without code  
• Consistent “Jarvis Card” look with interpretation line  
• SMTP Intake (Mailrise replacement): LAN-only, accepts any auth, subject/body → beautified  
• HTTP Proxy Intake (Gotify/ntfy): POST /gotify or /ntfy, beautified and optionally forwarded  
• Built-in notification UI: view and manage beautified messages directly in Jarvis Prime  
• ARR module: Radarr/Sonarr counts, posters, upcoming events  
• Technitium DNS: totals/blocked/failures, live stats  
• Weather forecast: current snapshot + upcoming forecast lines  
• Uptime Kuma: on-demand status (Prime does not duplicate Kuma alerts)  
• Seven selectable personalities, each completely different, such as “The Dude” modeled after The Big Lebowski, plus others with unique speech and style  
• Purge & Retention: original messages deleted after repost, retention configurable  

Supported Sources  
• Radarr / Sonarr (ARR) → Posters, runtime, SxxEyy, quality, size  
• QNAP / Unraid → system/storage notices normalized  
• Watchtower → container update summaries  
• Speedtest → ping/down/up facts  
• Technitium DNS → blocking/failure stats  
• Weather forecast → current and multi-day  
• JSON/YAML → parsed into bullet facts  
• Email via SMTP intake  
• Gotify and ntfy via proxy intake  
• Generic text → framed as a Jarvis Card  

Wake-Word & Commands  
Wake-word is “Jarvis …” in the title or message. Examples:  
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
• /app/personality.py → Personality engine with 7 selectable personas  
• /app/alias.py → command normalization  
• /data/options.json → configuration  
• /data/beautify_rules.yaml → optional custom rules  

Jarvis Prime is your fully flat Notification Orchestrator and AI-driven Notification Server with seven distinct personalities to choose from. Built with ChatGPT-5.