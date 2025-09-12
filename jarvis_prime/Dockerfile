# syntax=docker/dockerfile:1
FROM debian:stable-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Base system deps
RUN apt-get update && apt-get install -y \
    python3 python3-pip curl jq ca-certificates tzdata pkg-config \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- Python deps (your existing app deps) ----
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt

# Apprise intake deps (unchanged)
RUN pip3 install --no-cache-dir --break-system-packages flask waitress

# ---- Build deps + BLAS (split for HA builder stability) ----
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake libopenblas-dev \
 && rm -rf /var/lib/apt/lists/*

# NumPy first (wheels), pip upgrade
RUN pip3 install --no-cache-dir --break-system-packages --upgrade pip numpy

# ---- Modern llama-cpp-python from source (Phi-4 tokenizer + K-quants) ----
# Native CPU paths and OpenBLAS enabled
ENV CMAKE_ARGS="-DLLAMA_NATIVE=ON -DGGML_BLAS=ON -DGGML_BLAS_VENDOR=OpenBLAS"
# Use a 0.3.x build new enough for 'gpt-4o' pretokenizer support
RUN pip3 install --no-cache-dir --break-system-packages --no-binary=:all: \
      "llama-cpp-python>=0.3.20"

# ---- App content (unchanged) ----
RUN mkdir -p /app/memory
COPY memory/system_prompt.txt /app/memory/system_prompt.txt

COPY run.sh /run.sh
COPY /core/bot.py /app/bot.py
COPY /personality/chat.py /app/chat.py
COPY /modules/arr.py /app/arr.py
COPY /modules/weather.py /app/weather.py
COPY /modules/technitium.py /app/technitium.py
COPY /modules/digest.py /app/digest.py
COPY /modules/uptimekuma.py /app/uptimekuma.py
COPY /modules/aliases.py /app/aliases.py
COPY /personality/personality.py /app/personality.py
COPY /personality/personality_tappit.py /app/personality_tappit.py
COPY /intakes/smtp_server.py /app/smtp_server.py
COPY /intakes/proxy.py /app/proxy.py
COPY /modules/beautify.py /app/beautify.py
COPY /modules/enviroguard.py /app/enviroguard.py

COPY /llm/llm_client.py /app/llm_client.py
COPY /llm/llm_memory.py /app/llm_memory.py
COPY /personality/personality_state.py /app/personality_state.py
COPY /memory/system_prompt.txt /app/system_prompt.txt

COPY /intakes/api_messages.py /app/api_messages.py
COPY /modules/storage.py      /app/storage.py
COPY /intakes/ntfy_client.py  /app/ntfy_client.py
COPY /intakes/smtp_client.py  /app/smtp_client.py
COPY ui/ /app/ui/
COPY /intakes/webhook_server.py  /app/webhook_server.py
COPY /intakes/apprise.py  /app/apprise.py
COPY /modules/heartbeat.py  /app/heartbeat.py

RUN mkdir -p /app/intakes
COPY /intakes/apprise.py /app/intakes/apprise.py

RUN chmod +x /run.sh

EXPOSE 2525/tcp 2580/tcp 2581/tcp 2591/tcp

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
  CMD curl -fsS http://127.0.0.1:2581/api/messages?limit=1 || exit 1

CMD [ "/run.sh" ]

ENV BOT_INPUT_SSE=true BOT_INPUT_GOTIFY=true BOT_INPUT_NTFY=false \
    JARVIS_BASE=http://127.0.0.1:2581 DEDUPE_TTL_SECONDS=120 WORKERS=2