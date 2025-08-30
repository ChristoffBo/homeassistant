FROM debian:stable-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    python3 python3-pip curl jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python deps
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Default system prompt (baked into image). Runtime falls back to /share/jarvis_prime/memory if present.
RUN mkdir -p /app/memory
COPY memory/system_prompt.txt /app/memory/system_prompt.txt

# Copy all modules and run script
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
COPY smtp_server.py /app/smtp_server.py
COPY proxy.py /app/proxy.py
COPY beautify.py /app/beautify.py

# New modules for LLM + Memory
COPY llm_client.py /app/llm_client.py
COPY llm_memory.py /app/llm_memory.py
COPY personality_state.py /app/personality_state.py

# NEW: Inbox + API + UI
COPY storage.py /app/storage.py
COPY api_messages.py /app/api_messages.py
COPY ntfy_client.py /app/ntfy_client.py
RUN mkdir -p /app/ui
COPY ui/ /app/ui/

# Optional defaults for LLM behaviour
ENV LLM_MAX_LINES=10

# API/UI env (can be overridden in options.json via add-on env passthrough)
ENV JARVIS_API_BIND=0.0.0.0 \
    JARVIS_API_PORT=2581 \
    JARVIS_DB_PATH=/data/jarvis.db \
    JARVIS_UI_DIR=/app/ui

RUN chmod +x /run.sh

CMD [ "/run.sh" ]
