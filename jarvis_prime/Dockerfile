# syntax=docker/dockerfile:1.7
#
# Jarvis Prime — Debian-based add-on image
# - Ingest: Gotify/ntfy/SMTP
# - Inbox API/UI with Ingress (port 2581 inside)
# - Fan-out: Gotify/ntfy/SMTP (Gmail/relay)
# - Keeps LLM, Beautifier, wake-words, and other modules intact
#
FROM debian:bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Africa/Johannesburg \
    DEBIAN_FRONTEND=noninteractive

# Base OS deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        ca-certificates tzdata curl dumb-init && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps first for better layer caching
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

# App files
# Copy everything (bot, modules, inbox API/UI, run.sh, etc.).
COPY . /app/

# Ensure launcher is executable
RUN chmod +x /app/run.sh

# Expose service ports (SMTP intake, proxy if used, Inbox API/UI)
EXPOSE 2525/tcp 2580/tcp 2581/tcp

# Simple healthcheck: Inbox API responds
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://127.0.0.1:2581/api/messages?limit=1 || exit 1

# Use dumb-init to reap zombies and forward signals cleanly
ENTRYPOINT ["/usr/bin/dumb-init","--"]
CMD ["/app/run.sh"]
