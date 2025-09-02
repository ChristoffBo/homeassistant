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
