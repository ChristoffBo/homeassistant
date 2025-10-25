# syntax=docker/dockerfile:1
#
# Jarvis Prime — Add-on image (updated with llama-cpp-python 0.3.16 for Phi-4 support)
#
FROM debian:stable-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# ----------------------------
# System deps
# ----------------------------
RUN apt-get update && apt-get install -y \
    python3 python3-pip curl jq ca-certificates tzdata pkg-config \
    build-essential cmake libopenblas-dev \
    ansible sshpass \
    iputils-ping \
    # >>> Added for Registry Hub <<<
    nfs-common cifs-utils \
 && rm -rf /var/lib/apt/lists/*

# ----------------------------
# Install official Ookla Speedtest CLI
# ----------------------------
RUN apt-get update && apt-get install -y curl gnupg \
 && curl -fsSL https://packagecloud.io/ookla/speedtest-cli/gpgkey | gpg --dearmor -o /usr/share/keyrings/ookla.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/ookla.gpg] https://packagecloud.io/ookla/speedtest-cli/debian/ bookworm main" > /etc/apt/sources.list.d/ookla.list \
 && apt-get update && apt-get install -y speedtest \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ----------------------------
# Python deps
# ----------------------------
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt

# Apprise intake server deps
RUN pip3 install --no-cache-dir --break-system-packages flask waitress

# >>> Added for Registry Hub support <<<
RUN pip3 install --no-cache-dir --break-system-packages requests

# NumPy + modern llama-cpp-python (build from source, K-quants enabled)
ENV CMAKE_ARGS="-DLLAMA_NATIVE=ON -DGGML_BLAS=ON -DGGML_BLAS_VENDOR=OpenBLAS"
RUN pip3 install --no-cache-dir --break-system-packages --upgrade numpy \
 && pip3 install --no-cache-dir --break-system-packages --no-binary=:all: \
      "llama-cpp-python==0.3.16"

# EXTRA: ddgs (for chatbot web search, replaces old duckduckgo-search)
RUN pip3 install --no-cache-dir --break-system-packages ddgs requests

# ----------------------------
# App content
# ----------------------------
RUN mkdir -p /app/memory
COPY memory/system_prompt.txt /app/memory/system_prompt.txt

# Core & modules
COPY run.sh /run.sh
COPY /core/bot.py /app/bot.py
COPY /core/backup.py /app/backup.py
COPY /core/auth.py /app/auth.py
COPY /personality/chat.py /app/chat.py
COPY /modules/arr.py /app/arr.py
COPY /modules/weather.py /app/weather.py
COPY /modules/technitium.py /app/technitium.py
COPY /modules/digest.py /app/digest.py
COPY /modules/uptimekuma.py /app/uptimekuma.py
COPY /modules/aliases.py /app/aliases.py
COPY /personality/personality.py /app/personality.py
COPY /intakes/smtp_server.py /app/smtp_server.py
COPY /intakes/proxy.py /app/proxy.py
COPY /modules/beautify.py /app/beautify.py
COPY /modules/enviroguard.py /app/enviroguard.py
COPY /modules/sentinel.py /app/sentinel.py
COPY /modules/atlas.py /app/atlas.py
COPY /modules/registry_hub.py /app/registry_hub.py

# LLM + memory
COPY /llm/llm_client.py /app/llm_client.py
COPY /llm/llm_memory.py /app/llm_memory.py
COPY /personality/personality_state.py /app/personality_state.py
COPY /memory/system_prompt.txt /app/system_prompt.txt
COPY /modules/chatbot.py /app/chatbot.py
COPY /llm/rag.py /app/rag.py
COPY /llm/rag_facts.json /app/rag_facts.json

# Inbox server + UI + storage + fan-out clients
COPY /core/api_messages.py /app/api_messages.py
COPY /modules/storage.py      /app/storage.py
COPY /intakes/ntfy_client.py  /app/ntfy_client.py
COPY /intakes/smtp_client.py  /app/smtp_client.py
COPY ui/ /app/ui/
COPY /intakes/webhook_server.py  /app/webhook_server.py
COPY /intakes/websocket.py  /app/websocket.py
COPY /intakes/apprise.py  /app/apprise.py
COPY /modules/heartbeat.py  /app/heartbeat.py
COPY /modules/orchestrator.py  /app/orchestrator.py
COPY /modules/analytics.py  /app/analytics.py


# Place intake blueprint at the path bot.py expects
RUN mkdir -p /app/intakes
COPY /intakes/apprise.py /app/intakes/apprise.py

# ----------------------------
# Permissions
# ----------------------------
RUN chmod +x /run.sh

# ----------------------------
# Networking
# ----------------------------
EXPOSE 2525/tcp 2580/tcp 2581/tcp 2591/tcp
# >>> Added ports for Registry Hub <<<
EXPOSE 5001/tcp 8000/tcp

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
  CMD curl -fsS http://127.0.0.1:2581/api/messages?limit=1 || exit 1

# Entrypoint
CMD [ "/run.sh" ]

# Defaults (can be overridden via options.json -> env)
ENV BOT_INPUT_SSE=true BOT_INPUT_GOTIFY=true BOT_INPUT_NTFY=false \
    JARVIS_BASE=http://127.0.0.1:2581 DEDUPE_TTL_SECONDS=120 WORKERS=2
