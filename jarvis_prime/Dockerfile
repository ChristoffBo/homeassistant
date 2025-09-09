# syntax=docker/dockerfile:1
#
# Jarvis Prime — Add-on image (matches your original base + Inbox/UI wiring)
#
FROM debian:stable-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# System deps
RUN apt-get update && apt-get install -y \
    python3 python3-pip curl jq ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- Python deps ----
# requirements.txt must include: aiohttp, requests, aiosmtpd, websockets
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt

# ---- NEW (additive): Apprise intake server deps ----
# We install flask (required by /app/intakes/apprise.py) and waitress (optional, used if present).
RUN pip3 install --no-cache-dir --break-system-packages flask waitress

# ---- NEW (additive): Minimal build deps + llama-cpp-python for local GGUF ----
# Build deps are small and only for compiling wheels if prebuilt not available.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake libopenblas-dev \
  && rm -rf /var/lib/apt/lists/* \
  && pip3 install --no-cache-dir --break-system-packages \
      numpy \
      llama-cpp-python==0.2.90

# ---- App content (keep your original layout) ----
# Default system prompt (baked into image). Runtime falls back to /share/jarvis_prime/memory if present.
RUN mkdir -p /app/memory
COPY memory/system_prompt.txt /app/memory/system_prompt.txt

# Core & modules (your originals)
COPY run.sh /run.sh
COPY bot.py /app/bot.py
COPY chat.py /app/chat.py
COPY arr.py /app/arr.py
COPY weather.py /app/weather.py
COPY technitium.py /app/technitium.py
COPY digest.py /app/digest.py
COPY uptimekuma.py /app/uptimekuma.py
COPY aliases.py /app/aliases.py
COPY personality.py /app/personality.py
COPY personality_tappit.py /app/personality_tappit.py
COPY smtp_server.py /app/smtp_server.py
COPY proxy.py /app/proxy.py
COPY beautify.py /app/beautify.py
COPY enviroguard.py /app/enviroguard.py

# LLM + memory
COPY llm_client.py /app/llm_client.py
COPY llm_memory.py /app/llm_memory.py
COPY personality_state.py /app/personality_state.py


# ---- NEW: Inbox server + UI + storage + fan-out clients ----
COPY api_messages.py /app/api_messages.py
COPY storage.py      /app/storage.py
COPY ntfy_client.py  /app/ntfy_client.py
COPY smtp_client.py  /app/smtp_client.py
COPY ui/ /app/ui/
COPY webhook_server.py  /app/webhook_server.py
COPY apprise.py  /app/apprise.py
COPY heartbeat.py  /app/heartbeat.py

# ---- NEW (additive): place intake blueprint at the path bot.py expects ----
RUN mkdir -p /app/intakes
COPY apprise.py /app/intakes/apprise.py

# Permissions
RUN chmod +x /run.sh

# ---- Networking ----
# 2525 = SMTP intake, 2580 = HTTP proxy (if used), 2581 = Inbox API/UI (LAN access)
# NEW (additive): 2591 = Apprise intake Flask server
EXPOSE 2525/tcp 2580/tcp 2581/tcp 2591/tcp

# Simple healthcheck: Inbox API responds
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
  CMD curl -fsS http://127.0.0.1:2581/api/messages?limit=1 || exit 1

# Entrypoint
CMD [ "/run.sh" ]

# Standalone mode defaults (can be overridden via options.json -> env)
ENV BOT_INPUT_SSE=true BOT_INPUT_GOTIFY=true BOT_INPUT_NTFY=false \
    JARVIS_BASE=http://127.0.0.1:2581 DEDUPE_TTL_SECONDS=120 WORKERS=2
