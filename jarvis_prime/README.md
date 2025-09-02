# 🧩 Jarvis Prime — Home Assistant Add-on

Jarvis Prime is in active ALPHA and under heavy development.  
It is your standalone Notification Orchestrator and Server — one flat self-sufficient hub that runs inside Home Assistant.  
Jarvis Prime ingests, rewrites, and beautifies notifications into sleek AI-style cards, reposts them to Gotify/ntfy/email, shows them in its own dark-mode Web UI, and responds to wake-word commands like “Jarvis weather” or “Jarvis dns”.

Jarvis is the point — it is one unified app. SMTP intake, HTTP proxy, webhook ingestion, LLM-driven Neural Core, Beautifier (Aesthetic Engine), ARR stats, DNS, Weather, Kuma, Personas, Retention — all in a single orchestrator.

✅ Features  
• Standalone Notification Orchestrator and Server  
• Neural Core (LLM rewrite) + Aesthetic Engine (beautifier) pipeline  
• Personas: Dude, Chick, Nerd, Rager, Comedian, Action, Jarvis, Ops — overlay tone on any message  
• SMTP Intake (Mailrise replacement): LAN-only, accepts any auth, subject/body → unified Jarvis card  
• HTTP Proxy Intake (Gotify/ntfy): POST into Jarvis, unified & optionally reposted  
• Webhook Intake: POST to /webhook or /hook/*, JSON or text payloads accepted  
• Built-in dark-mode Web UI: inbox, filters, purge, retention, wake-word push  
• ARR module: Radarr/Sonarr counts, posters, upcoming events  
• Technitium DNS: totals, blocked, failures, live stats  
• Weather forecast: current and multi-day snapshot  
• Uptime Kuma: on-demand status (no duplicate alerts)  
• Purge & Retention: configurable lifecycle for messages  
• Full Home Assistant Ingress support  

📡 Supported Sources  
• Radarr / Sonarr → Posters, runtime, SxxEyy, quality, size  
• QNAP / Unraid → system/storage notices normalized  
• Watchtower → container update summaries  
• Speedtest → ping/down/up facts  
• Technitium DNS → blocking/failure stats  
• Weather forecast → current + multi-day  
• Uptime Kuma → status checks  
• Email → via SMTP intake  
• Gotify & ntfy → via proxy intake  
• Webhook → any service that can POST JSON/text  
• Generic text → framed as Jarvis Cards  

🗣️ Wake-Word & Commands  
Wake-word is “Jarvis …” in the title or body. Examples:  
• Jarvis dns → DNS summary  
• Jarvis weather / forecast → Weather snapshot or forecast  
• Jarvis joke → One-liner  
• Jarvis upcoming movies / series, counts, longest → ARR queries  
• Jarvis help → Command list  

⚙️ Configuration (options.json)  
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
  "smtp_bind": "0.0.0.0",
  "smtp_port": 2525,

  "proxy_enabled": true,
  "proxy_bind": "0.0.0.0",
  "proxy_port": 2580,

  "webhook_enabled": true,
  "webhook_bind": "0.0.0.0",
  "webhook_port": 2590,
  "webhook_token": "",

  "weather_enabled": true,
  "radarr_enabled": true,
  "sonarr_enabled": true,
  "technitium_enabled": true,
  "uptimekuma_enabled": true,

  "llm_enabled": true,
  "llm_timeout_seconds": 20,
  "llm_max_cpu_percent": 80,
  "llm_ctx_tokens": 6096,
  "llm_gen_tokens": 300,
  "llm_models_priority": "qwen15,phi2,llama32_1b,tinyllama,qwen05,phi3",

  "enable_dude": true,
  "enable_chick": false,
  "enable_nerd": false,
  "enable_rager": false,
  "enable_comedian": false,
  "enable_action": false,
  "enable_jarvis": false,
  "enable_ops": false
}

🧪 Options Explained  
- `smtp_enabled`: enable LAN SMTP intake (default port 2525)  
- `proxy_enabled`: enable Gotify/ntfy HTTP proxy intake (default port 2580)  
- `webhook_enabled`: enable generic webhook intake (default port 2590)  
- `webhook_token`: optional shared secret; if set, must be passed via header X-Webhook-Token or ?token=...  
- `llm_enabled`: turn Neural Core on/off  
- `llm_timeout_seconds`: maximum LLM rewrite time before fallback to Beautifier  
- `llm_max_cpu_percent`: throttle LLM usage  
- `llm_ctx_tokens` / `llm_gen_tokens`: context size and output tokens  
- `enable_*`: toggles for each persona overlay  

🌍 Webhook Access  
POST JSON or text to:  
http://<JARVIS_HOST>:2590/webhook  
or alias:  
http://<JARVIS_HOST>:2590/hook  
http://<JARVIS_HOST>:2590/hook/<any>  

Example:  
curl -X POST http://10.0.0.100:2590/webhook \
  -H "Content-Type: application/json" \
  -d '{"title":"Webhook Check","message":"Hello from webhook","priority":5}'

🔌 Ports  
• 2525/tcp → SMTP intake (if enabled)  
• 2580/tcp → Proxy intake (if enabled)  
• 2581/tcp → Home Assistant Ingress (UI)  
• 2590/tcp → Webhook intake (if enabled)  

📁 File Map  
• /app/bot.py → core brain  
• /app/beautify.py → beautify engine  
• /app/smtp_server.py → smtp intake  
• /app/proxy.py → proxy intake  
• /app/webhook_server.py → webhook intake  
• /app/arr.py → Radarr/Sonarr integration  
• /app/weather.py → Weather forecast  
• /app/technitium.py → DNS  
• /app/uptimekuma.py → Kuma  
• /app/personality.py → personality engine with personas  
• /app/aliases.py → command normalization  
• /app/llm_client.py → local LLM Neural Core  
• /app/storage.py → inbox persistence  
• /app/ui/ → dark-mode web UI assets  
• /data/options.json → configuration  

🧠 Jarvis Prime is your fully flat standalone Notification Orchestrator and AI-driven Notification Server. It unifies every message, powers them with personality, and ensures your home notifications are sleek, reliable, and alive.