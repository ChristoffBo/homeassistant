🧩 Jarvis Prime — Home Assistant Add-on

Jarvis Prime is your Notification AI (kind of). It is a full-fat, Gotify-aware assistant that runs inside Home Assistant. It listens to incoming notifications, beautifies them into sleek AI-style cards, reposts them to your Jarvis app in Gotify, and responds to wake-word commands like “Jarvis digest” or “Jarvis weather”. Prime also includes a unified Beautify Engine, a LAN SMTP intake (Mailrise replacement), and a lightweight HTTP proxy for Gotify/ntfy so anything you throw at it arrives looking polished and consistent.

What it is and what it does
Jarvis Prime is a Gotify-aware assistant. It centralizes formatting, command handling, and adds personality to your notifications. It subscribes to your Gotify stream via Client token, reposts via App token, and runs a five-layer Beautify Engine to standardize visual style across heterogeneous sources. It can also ingest via SMTP or HTTP proxy and still beautify before posting. It offers moods and personality so your notifications feel alive, and includes wake-word commands, a daily digest, and optional heartbeat.

Features
• Unified Beautify Engine (7 layers: Ingest → Detect → Normalize → Interpret → Render → Checks Duplicate Sentencaes → Tries and Places Images Back)
• Works out-of-the-box for unknown senders, with built-ins for ARR (Radarr/Sonarr), QNAP/Unraid, Watchtower, Speedtest, JSON/YAML, DNS, Weather, generic text
• Optional rules file /data/beautify_rules.yaml to add detectors/extractors without code
• Consistent “Jarvis Card” look with mood tint and AI interpretation line
• SMTP Intake (Mailrise replacement): LAN-only, accepts any auth, subject/body → beautified
• HTTP Proxy Intake (Gotify/ntfy): POST /gotify or /ntfy, beautified and optionally forwarded
• ARR module: Radarr/Sonarr counts, posters, upcoming events
• Technitium DNS: totals/blocked/failures, digest briefs
• Weather module: one-liners + forecasts, digest briefs
• Digest: scheduled daily summary (Media, DNS, Weather, Kuma if enabled)
• Uptime Kuma: on-demand status (Prime does not duplicate Kuma alerts)
• Personality + Mood: AI, Serious, Calm, Excited, Sarcastic, Angry, Tired, Depressed, Playful
• Purge & Retention: original messages deleted after repost, retention configurable

Supported Sources
• Radarr / Sonarr (ARR) → Posters, runtime, SxxEyy, quality, size
• QNAP / Unraid → system/storage notices normalized
• Watchtower → container update summaries
• Speedtest → ping/down/up facts
• Technitium DNS → blocking/failure stats
• Weather → current and forecast
• JSON/YAML → parsed into bullet facts
• Generic text → framed as a Jarvis Card

Wake-Word & Commands
Wake-word is “Jarvis …” in the title or message. Examples:
• Jarvis dns → DNS summary
• Jarvis weather / forecast → Weather snapshot or forecast
• Jarvis digest → Daily digest now
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
  "personality_mood": "AI",
  "smtp_enabled": true,
  "smtp_port": 2525,
  "proxy_enabled": true,
  "proxy_port": 8099,
  "digest_enabled": true,
  "digest_time": "08:00",
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
• /app/weather.py → Weather
• /app/technitium.py → DNS
• /app/uptimekuma.py → Kuma
• /app/digest.py → Daily digest
• /app/personality.py → Mood & quips
• /app/alias.py → command normalization
• /data/options.json → configuration
• /data/beautify_rules.yaml → optional custom rules

Jarvis Prime is your Notification AI (kind of). Built with ChatGPT-5.
