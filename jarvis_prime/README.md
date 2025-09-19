# 🧩 Jarvis Prime — Home Assistant Add-on

Jarvis Prime is your standalone Notification Orchestrator, Chat Assistant, and Server. It centralizes, beautifies, and orchestrates notifications from across your homelab. Raw events come in through multiple intakes (SMTP, Proxy, Webhook, Apprise, Gotify, ntfy), are polished by the Beautify Engine, and are pushed back out through Gotify, ntfy, email, or its own sleek dark-mode Web UI. Every notification arrives consistent, enriched, and alive with personality. In addition, Jarvis now includes a dedicated Chat Lane — ask questions or request explanations, and Jarvis will reply instantly using the local LLM. Chatting does not replace riffs; it gives you direct Q&A on demand.

Features
• Standalone Notification Orchestrator and Chat Assistant  
• Optional review via Gotify or ntfy apps (push notifications, history, filters)  
• Beautify Engine (LLM + formatting pipeline) normalizes events into Jarvis Cards  
• Chat Lane: send a Gotify/ntfy message with title “chat” and text = your question, Jarvis responds with direct answer (no riff preambles)  
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

Chat Lane Setup
• Enabled by default with key “chatbot_enabled”: true in options.json  
• To trigger chat: send Gotify or ntfy notification with title = “chat” or “talk” and body = your question  
• Jarvis responds with direct Q&A, stripped of riff banners and policies  
• History preserved per source (up to N turns, configurable)  
• All parameters configurable in options.json  

Chat Lane Config (options.json example)
{  
  "chatbot_enabled": true,  
  "chatbot_history_turns": 3,  
  "chatbot_max_total_tokens": 1200,  
  "chatbot_reply_max_new_tokens": 256,  
  "chat_system_prompt": "You are Jarvis Prime (call-sign Jarvis), the user’s homelab assistant. Always answer as Jarvis.",  
  "chat_model": ""  
}  

Chat Lane Options Explained
• chatbot_enabled → true/false toggle for chat function  
• chatbot_history_turns → number of turns to keep in memory (default 3)  
• chatbot_max_total_tokens → global budget for context + reply (safe 512–2000)  
• chatbot_reply_max_new_tokens → max length of new answer (default 256, longer = smarter but slower)  
• chat_system_prompt → customize Jarvis’s identity and tone  
• chat_model → optional override if multiple local models are available  

Intake Setup Details
1. SMTP Intake (Mailrise replacement) → configure apps to send SMTP to Jarvis  
2. Webhook Intake → POST text or JSON to http://10.0.0.100:2590/webhook  
3. Apprise Intake → POST to http://10.0.0.100:2591/intake/apprise/notify?token=yourtoken  
4. Gotify Intake (proxy) → forward messages via Gotify app token  
5. ntfy Intake (proxy) → subscribe to topic and push text  

EnviroGuard (Optional)
Jarvis monitors temperature and dynamically adjusts LLM profiles. Supports Open-Meteo API or Home Assistant sensors. Example profiles: hot, normal, boost with CPU %, ctx tokens, timeouts. Jarvis announces state changes: “Ambient 31.2 °C → profile HOT (CPU=50%, ctx=1024, to=12s)”

LLM Defaults
• Context tokens: 2048 (~1500 words memory)  
• Generation tokens: 150 (~110 words rewrite/riff)  
• Riff lines: 30 tokens (~20 words, punchy)  
• Rewrite lines: 50 tokens (~35 words, clear)  
• Persona riffs: 100 tokens (~70 words, multi-line personality quips)  
• Chat Lane replies: default 256 tokens, configurable  

Recommended LLMs
Jarvis Prime is tuned for Phi family models (GGUF via llama.cpp or ollama). Phi-3 Mini (light, fast), Phi-3.5 Mini (improved reasoning), Phi-4 (best phrasing, heavier). Download from Hugging Face.  

Performance Guide
• Intel N100: Phi-3 Q4 ~8–12 tok/s, Phi-3.5 Q4 ~6–10 tok/s  
• i7 desktop: Phi-3.5 Q4 ~15 tok/s, Phi-4 Q4 ~6–8 tok/s  
• With GPU offload: Phi-4 Q5 ~20–30 tok/s  
• Recommended default: Phi-3 Mini Q4  

Web UI Access
Ingress via Home Assistant or direct browser at http://10.0.0.100:PORT. Inbox shows beautified cards with filters, retention, purge, and live updates.  

Chat Lane Usage Example
Send via Gotify or ntfy:  
Title: chat  
Message: When was Windows 11 released?  

Jarvis will respond instantly with something like:  
“Windows 11 was officially released to the general public on October 5, 2021.”  

Self-Hosting Statement
Jarvis Prime is fully self-contained. Gotify or ntfy are optional — use them only if you want mobile push with history. The add-on runs standalone with its own intakes, Beautify Engine, personas, Chat Lane, and dark-mode UI.