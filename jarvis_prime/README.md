# 🧩 Jarvis Prime — Home Assistant Add-on

Jarvis Prime is your standalone Notification Orchestrator and Server. It can run fully self-contained, or side-by-side with Gotify or ntfy for mobile review. It centralizes, beautifies, and orchestrates notifications from across your homelab, turning raw events into sleek, unified cards with personality. Jarvis listens to multiple intakes (SMTP, Proxy, Webhook, Apprise, Gotify, ntfy), rewrites and beautifies messages, and pushes them back out through Gotify, ntfy, email, or its own dark-mode web UI.

Jarvis is not just a bridge — it is the core. It centralizes formatting, command handling, and orchestration of messages across your home systems. Every notification you throw at it arrives polished, consistent, and alive with personality.

Features
• Standalone Notification Orchestrator and Server (no Gotify required)  
• Optional review via Gotify or ntfy apps (mobile push, history, filters)  
• Beautify Engine (LLM + Aesthetic pipeline) to normalize and render events  
• SMTP Intake (Mailrise replacement): LAN-only, accepts any auth, subject/body → beautified  
• HTTP Proxy Intake (Gotify/ntfy): POST → beautified and optionally forwarded  
• Webhook Intake: POST /webhook, parses JSON or raw text (GitHub, health checks, generic)  
• Apprise Intake: POST /intake/apprise/notify?token=...  
• Built-in dark-mode Web UI: inbox, filters, live updates, purge, retention, wakeword push  
• ARR module: Radarr/Sonarr counts, posters, upcoming events  
• Technitium DNS: totals, blocked, failures, live stats  
• Weather forecast: current and multi-day snapshot  
• Uptime Kuma: on-demand status (no duplicate alerts)  
• Multiple selectable personalities (The Dude, Chick, Nerd, Rager, Comedian, Action, Ops)  
• Purge & Retention: configurable lifecycle for messages  
• **EnviroGuard**: adaptive LLM throttle system that auto-adjusts Jarvis’s performance profile based on ambient temperature  

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
• Apprise → POST events using Apprise clients  
• Generic text → framed as Jarvis Cards  

Unified Intake URLs & Examples
SMTP: smtp://10.0.0.100:2525

Webhook (plain text):
curl -X POST http://10.0.0.100:2590/webhook \
  -H "Content-Type: text/plain" \
  -d 'Hello Jarvis, something happened on my server.'

Webhook (JSON):
curl -X POST http://10.0.0.100:2590/webhook \
  -H "Content-Type: application/json" \
  -d '{"title":"Backup Complete","message":"Proxmox node 1 finished nightly backup.","priority":7}'

Apprise:
curl -X POST "http://10.0.0.100:2591/intake/apprise/notify?token=change-me-very-long" \
  -H "Content-Type: application/json" \
  -d '{"title":"Apprise Test","body":"Hello from Apprise","type":"info","tag":"all"}'

Gotify (direct):
curl -X POST "http://10.0.0.100:2580/message?token=YOUR_GOTIFY_APP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Gotify Direct","message":"Hello from Gotify","priority":5}'

ntfy (direct):
curl -X POST "http://10.0.0.100:2580/jarvis" \
  -H "Content-Type: text/plain" \
  -d 'Hello from ntfy direct push'

EnviroGuard
EnviroGuard monitors the outside temperature (via Open-Meteo) and dynamically adjusts Jarvis’s LLM performance profile to keep it efficient and safe.  
Enable it by adding to /data/options.json:  
{
  "llm_enviroguard_enabled": true,
  "llm_enviroguard_poll_minutes": 30,
  "llm_enviroguard_hot_c": 30,
  "llm_enviroguard_cold_c": 10,
  "llm_enviroguard_hysteresis_c": 2,
  "llm_enviroguard_profiles": {
    "manual": { "cpu_percent": 80, "ctx_tokens": 4096, "timeout_seconds": 20 },
    "hot":    { "cpu_percent": 50, "ctx_tokens": 2048, "timeout_seconds": 15 },
    "normal": { "cpu_percent": 80, "ctx_tokens": 4096, "timeout_seconds": 20 },
    "boost":  { "cpu_percent": 95, "ctx_tokens": 8192, "timeout_seconds": 25 }
  }
}
When active, the boot card shows EnviroGuard’s state, profile, and current temperature.  
Whenever EnviroGuard shifts profile (e.g. from normal → hot), Jarvis notifies you:  
“Ambient 31.2 °C → profile HOT (CPU=50%, ctx=2048, to=15s)”