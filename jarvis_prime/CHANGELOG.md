## latest (2025-11-07 15:21:00)
All tested seems fine. Jarvis Completed. V1.0.0
## latest (2025-10-31 5:21:00)
Added Backup Module
## latest (2025-10-21 14:21:00)
Fixed issue with smtp and ntfy fanouts.
## latest (2025-10-18 14:21:00)
Fixed issue with Analytics, and while busy add network monitoring to analytics
## latest (2025-10-16 14:21:00)
Atlas Added.
Moved all settings to UI.
## latest (2025-10-13 14:21:00)
Removed Nasty Sentinal dedup glitch.
## latest (2025-10-11 14:21:00)
Sentinel Added tested working.
Few more niggles then Jarvis goes Docker.
## latest (2025-10-10 14:21:00)
Started work on last Module, sentinel auto Healing
## latest (2025-10-10 14:21:00)
Updated Lexicons, made them more context aware and fixed a nasty no Riff bug.
Updated Core, Jarvis now uses threading, UI should not become inactive while LLM runs anymore.
## latest (2025-10-8 14:21:00)
Added retries and flap protection to the Analytics.
## latest (2025-10-5 14:21:00)
Added settings into ui and backup.
backup currently inactive.
## latest (2025-10-5 8:21:00)
Updated UI again, fixed dark mode.
Added QOL changes to orhcestrator, upload download playbooks naming schedules.
Aware if the ui stop when llm runs, seems unavoidable for performance.
## latest (2025-10-3 11:00:00)
Updated UI.
Added a Dashboard.
## latest (2025-10-2 11:00:00)
Added Analytycs, think uptime monitor.
## latest (2025-10-1 11:00:00)
Ansible bugs squashed.
## latest (2025-10-1 7:00:00)
Added Ansible
Need to fix the Ansible Schedule Error and the No Notify flag.
## latest (2025-09-30 12:00:00)
Added Websocket Intake.
Improved Apprise and other intake handeling, all intakes should now look more uniform.
## latest (2025-09-29 12:00:00)
UI Updated, still working on llm chat
## latest (2025-09-28 12:00:00)
Removed Internet search.
Fixed Enviroguard 
## latest (2025-09-23 12:00:00)
Added Rag aswell, if homeasstiant is added in the options.json token and url llm wil now be aware of your homeasstiant entities.
Please Note internet search and Rag is experamental.
## latest (2025-09-22 12:00:00)
Finally Added Chat, if llm is enabled chat is enabled. Wake word Talk or Chat.
## latest (2025-09-22 12:00:00)
Updated the Weather Integration, now pulls from 3 API's should be more accurate.
## latest (2025-09-17 12:00:00)
Hopefully fixed the Multiple Jokes bug.
Extended the Apprise Timeout, so connection test shold now work.
## latest (2025-09-16 21:00:00)
Added CTX overflow protection for riffs and Rewrites
## latest (2025-09-14 21:00:00)
Riffs now use less CPU alot less.
Fallsback to Lexicon riffs if it fails.
Top messages from persona is now Lexicon Only.
## latest (2025-09-12 22:00:00)
Bumped llama-cpp-python==0.2.90 to 0.3.16
## latest (2025-09-10 08:00:00)
- Fine tuned LLM rewrites and Riffs
## latest (2025-09-09 06:42:00)
- Persona can now be set via Wakeword
## latest (2025-09-08 14:40:00)
- Added Lexi-driven persona headers in bot.py
- Integrated persona_header() into personality.py for dynamic message intros
## latest (2025-09-08 14:00:00)
- Replaced the LLM's with the Phi3 family llms' they just run better. Also be aware that the uncesored LLM is not very nice.
## latest (2025-09-07 14:00:00)
- EnviroGuard settings kept, schema cleaned for consistency
## 1.1.4 (2025-09-04 19:00:00)
- Jarvis is now fully self-contained: all intakes (SMTP, Proxy, Webhook, Apprise) forward into /internal/emit
- Removed all hardcoded Gotify posting from sidecars — Jarvis is no longer dependent on Gotify as a server
- Centralized pipeline ensures all messages are beautified and riffed before any outputs
- Riffs now applied consistently across SMTP, Proxy, and Webhook modules
- Duplicate message issue resolved (no more double-post from sidecars)
- Boot screen updated to show Jarvis as standalone Notification Server
- Options.json simplified: output toggles (Gotify, ntfy, SMTP out, etc.) now only apply at Jarvis core
- **New:** EnviroGuard — adaptive LLM throttle system  
  EnviroGuard monitors ambient temperature (via Open-Meteo) and dynamically adjusts Jarvis’s LLM performance profile.  
  • Toggle with `llm_enviroguard_enabled: true` in options.json  
  • Poll interval controlled by `llm_enviroguard_poll_minutes` (default 30 minutes)  
  • Profiles:  
    – hot → reduced CPU (50%), smaller context (2048), faster timeouts (15s)  
    – normal → balanced (80%, 4096 ctx, 20s)  
    – cold (optional) → higher performance when cooler  
    – boost → maximum power (95%, 8192 ctx, 25s)  
  • Thresholds: `llm_enviroguard_hot_c`, `llm_enviroguard_cold_c`, and `llm_enviroguard_hysteresis_c`  
  • Profile changes send a Jarvis notification with details:  
    “Ambient 31.2 °C → profile HOT (CPU=50%, ctx=2048, to=15s)”  
  • Boot card now shows EnviroGuard ON/OFF, current profile, and detected temperature  
  → In short: EnviroGuard keeps Jarvis’s brain cool in the heat, boosts it when safe, and tells you whenever it shifts modes.
- **New:** Riffs explained — a "riff" is a short persona-driven remark or embellishment added to each message by Jarvis’s LLM + Beautify engine.  
  Example: a plain "Backup complete" message becomes "📦 Backup complete — mission accomplished, Captain!" depending on the active persona.
- **Personality Engine:** deep build-out & tuning  
  • ~100 quips per persona with tighter characterization (Dude, Chick, Nerd, Rager, Comedian, Action, Jarvis, Ops)  
  • Chick refreshed with Elle-style smart-glam; Comedian expanded with Deadpool-style meta; Jarvis blended with a subtle HAL-like calm  
  • Rager now **always uncensored** (no soft-censor path)  
  • Time-aware daypart flavor + intensity amplifier for quips (subtle, non-breaking)  
  • Riff prompts use **style descriptors only** (no actor/brand names) to avoid quote-parroting
- **Beautify Engine:** refined  
  • Stronger persona style descriptors and safer formatting rules  
  • Unified profanity handling (Rager exempt; others respect `PERSONALITY_ALLOW_PROFANITY`)  
  • Cleaner post-processing: ≤140 chars, dedupe, no meta/system leakage  
  • More consistent emoji and punctuation polish tied to intensity

## 1.1.3 (2025-09-02 21:30:00)
- Added Webhook intake server with token support (POST /webhook)
- Webhook pushes now beautified via LLM → Beautify pipeline
- Boot screen shows Webhook module state
- Config options added: webhook_enabled, webhook_bind, webhook_port, webhook_token
- Added webhook_server.py with aiohttp support
- All intake/output modules configurable from options.json (Gotify, ntfy, SMTP, Proxy, Webhook)
- LLM pipeline now respects llm_timeout_seconds, llm_gen_tokens, llm_ctx_tokens, llm_max_cpu_percent
- Footers updated to show Neural Core ✓ and Aesthetic Engine ✓
- Personas expanded with more lines, deeper characterization (Dude, Chick, Nerd, Rager, Comedian, Action, Jarvis, Ops)
- Rager persona now explicit potty-mouth violent tone
- Chick persona sassier, playful, flirtatious
- Comedian persona updated with more Leslie Nielsen dry humor
- Beautify no longer uses 7-layer description — simplified to unified Beautify Engine
- Readme updated with webhook instructions, ntfy/Gotify app integration, and future roadmap (DNS, DHCP, Ansible, new WebUI)

## 1.1.2 (2025-09-01 18:00:00)
- Added LLM integration (GGUF models supported, Ollama removed)
- LLM fallback to Beautify if timeout exceeded
- Configurable CPU cap and token limits
- Boot card updated with LLM engine status
- Messages now tagged with Neural Core ✓ / Aesthetic Engine ✓

## 1.1.1 (2025-08-30 12:00:00)
- Added Persona Engine with 8 selectable personas
- Added quip banks (Dude, Chick, Nerd, Rager, Comedian, Action, Jarvis, Ops)
- Persona overlays added to messages
- Persona line added to notification headers

## 1.1.0 (2025-08-28 09:00:00)
- Core refactor to standalone Notification Orchestrator
- SMTP intake (Mailrise replacement)
- Proxy intake for Gotify and ntfy
- Web UI enabled with Ingress
- ARR integration (Radarr, Sonarr)
- Weather module
- Technitium DNS stats
- Uptime Kuma integration
- Retention, purge policies
- Personality quiet hours + greetings
