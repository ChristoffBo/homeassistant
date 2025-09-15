# 🧩 Jarvis Prime — Home Assistant Add-on

Jarvis Prime is your standalone Notification Orchestrator and Server. It centralizes, beautifies, and orchestrates notifications from across your homelab. Raw events come in through multiple intakes (SMTP, Proxy, Webhook, Apprise, Gotify, ntfy), are polished by the Beautify Engine, and are pushed back out through Gotify, ntfy, email, or its own sleek dark-mode Web UI. Every notification arrives consistent, enriched, and alive with personality.

Features
• Standalone Notification Orchestrator and Server.  
• Optional review via Gotify or ntfy apps (push notifications, history, filters)  
• Beautify Engine (LLM + formatting pipeline) normalizes events into Jarvis Cards  
• SMTP Intake: drop-in Mailrise replacement, accepts LAN-only emails with any auth  
• HTTP Proxy Intake: accepts Gotify/ntfy POSTs and beautifies them  
• Webhook Intake: accepts plain text or JSON from scripts, GitHub, health checks, etc.  
• Apprise Intake: accepts Apprise client POSTs with token auth  
• Built-in dark-mode Web UI with inbox, filters, purge, retention, and live updates  
• ARR Module: Radarr/Sonarr posters, episode/movie facts, upcoming releases  
• DNS Module: Technitium DNS block stats, failures, totals  
• Weather Intake: current + multi-day snapshot  
• Uptime Kuma: status without duplicate noise  
• Multiple selectable personas: The Dude, Chick, Nerd, Rager, Comedian, Action, Ops  
• EnviroGuard: adaptive LLM throttle adjusts CPU use based on ambient temperature  
• Purge & Retention: configurable lifecycle for old messages  

Supported Sources
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
• Plain text → Beautified into sleek cards  

Intake Setup Details

1. SMTP Intake (Mailrise replacement)  
• Start Jarvis Prime and note the SMTP port (default 2525).  
• In your app (Duplicati, Proxmox, etc.), set SMTP server to 10.0.0.100 and port 2525.  
• Authentication: any username/password (ignored).  
• Subject = Jarvis Card title, body = Card body.  
• Example: configure Duplicati → Notifications → SMTP → server=10.0.0.100, port=2525.  

2. Webhook Intake  
• URL: http://10.0.0.100:2590/webhook  
• Accepts plain text or JSON.  
• Example plain text:  
  curl -X POST http://10.0.0.100:2590/webhook -H "Content-Type: text/plain" -d 'Backup finished'  
• Example JSON:  
  curl -X POST http://10.0.0.100:2590/webhook -H "Content-Type: application/json" -d '{"title":"Backup Complete","message":"Node 1 finished","priority":7}'  
• Step: Add this URL to any app that can POST webhook notifications (e.g., Uptime Kuma).  

3. Apprise Intake  
• URL: http://10.0.0.100:2591/intake/apprise/notify?token=YOUR_LONG_TOKEN  
• Step 1: Generate a long random token (any string).  
• Step 2: Place token into /data/options.json under "apprise_token".  
• Step 3: From any host with Apprise installed, run:  
  curl -X POST "http://10.0.0.100:2591/intake/apprise/notify?token=yourtoken" -H "Content-Type: application/json" -d '{"title":"Apprise Test","body":"Hello","type":"info"}'  

4. Gotify Intake (proxy)  
• Step 1: Install Gotify server (docker gotify/server) and open its Web UI.  
• Step 2: Login → Settings → Applications → Add Application → Give a name → Create.  
• Step 3: Copy the application token shown.  
• Step 4: Test with:  
  curl -X POST "http://10.0.0.100:2580/message?token=YOUR_GOTIFY_APP_TOKEN" -H "Content-Type: application/json" -d '{"title":"Gotify Direct","message":"Hello from Gotify","priority":5}'  
• In mobile Gotify app: Settings → Add server → URL=http://10.0.0.100:2580 → Token=paste.  

5. ntfy Intake (proxy)  
• Step 1: Install ntfy app from Play Store or App Store.  
• Step 2: In the app, add a subscription topic: "jarvis".  
• Step 3: Test with:  
  curl -X POST "http://10.0.0.100:2580/jarvis" -H "Content-Type: text/plain" -d 'Hello from ntfy direct push'  
• Notifications will appear in the ntfy app subscribed to topic "jarvis".  

EnviroGuard (Optional)  
• Jarvis monitors temperature and dynamically adjusts LLM profiles.  
• Two modes are supported:  
  1. **Open-Meteo API** → uses outside temperature based on configured lat/lon.  
  2. **Home Assistant sensors** → reads local temperature from any HA entity (e.g., `sensor.living_room_temperature`). Configure entity IDs in `/data/options.json`.  
• Example config with HA sensors:  
  {  
    "llm_enviroguard_enabled": true,  
    "llm_enviroguard_use_homeassistant": true,  
    "llm_enviroguard_sensors": ["sensor.living_room_temperature","sensor.server_rack_temp"],  
    "llm_enviroguard_hot_c": 30,  
    "llm_enviroguard_cold_c": 10,  
    "llm_enviroguard_profiles": {  
      "manual": { "cpu_percent": 80, "ctx_tokens": 2048, "timeout_seconds": 15 },  
      "hot":    { "cpu_percent": 50, "ctx_tokens": 1024, "timeout_seconds": 12 },  
      "normal": { "cpu_percent": 80, "ctx_tokens": 2048, "timeout_seconds": 15 },  
      "boost":  { "cpu_percent": 90, "ctx_tokens": 4096, "timeout_seconds": 20 }  
    }  
  }  
• Jarvis announces state changes: “Ambient 31.2 °C → profile HOT (CPU=50%, ctx=1024, to=12s)”  

LLM Defaults  
• Context tokens: 2048 (~1500 words memory)  
• Generation tokens: 150 (~110 words rewrite/riff)  
• Riff lines: 30 tokens (≈20 words, punchy)  
• Rewrite lines: 50 tokens (≈35 words, clear)  
• Persona riffs: 100 tokens (≈70 words, multi-line personality quips)  

Recommended LLMs  
Jarvis Prime is tuned for **Phi family models**. Use GGUF quantized builds with llama.cpp or ollama.  

1. **Phi-3 Mini (3.8B)**  
• Fast, light, excellent for rewrites and riffs.  
• Best option for Intel N100, N5105, or similar CPUs.  
• Download: https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf  

2. **Phi-3.5 Mini (3.8B)**  
• Improved reasoning and stability over Phi-3.  
• Runs fine on mid-range CPUs (i7, Ryzen) at Q4_K_M or Q5_K_M.  
• Download: https://huggingface.co/microsoft/Phi-3.5-mini-instruct-gguf  

3. **Phi-4 (14B)**  
• Strongest reasoning, natural phrasing.  
• Heavy — requires desktop-grade CPU or GPU offload.  
• Good for users who want maximum polish in rewrites.  
• Download: https://huggingface.co/microsoft/Phi-4-mini-instruct-gguf  

Performance Guide  
• Intel N100: Phi-3 Q4 ~8–12 tok/s, Phi-3.5 Q4 ~6–10 tok/s.  
• i7 desktop: Phi-3.5 Q4 ~15 tok/s, Phi-4 Q4 ~6–8 tok/s.  
• With GPU offload: Phi-4 Q5 can reach ~20–30 tok/s.  
• Recommended default: Phi-3 Mini (Q4) for balance of speed and polish.  

Web UI Access  
• Ingress via Home Assistant → Add-on → Jarvis Prime → OPEN WEB UI.  
• Or direct browser: http://10.0.0.100:PORT (Ingress base path is auto-handled).  
• Inbox view shows beautified cards with filters, retention, purge, and live updates.  

Self-Hosting Statement  
Jarvis Prime is fully self-contained. Gotify or ntfy are optional — use them only if you want mobile push with history. The add-on runs standalone with its own intakes, Beautify Engine, personas, and dark-mode UI.