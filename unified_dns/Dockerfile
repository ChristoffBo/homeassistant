ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm
FROM ${BUILD_FROM}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Debian base + venv to avoid PEP 668; keep apt best-effort
RUN (apt-get update || true) && (apt-get -y upgrade || true) && \
    apt-get install -y --no-install-recommends python3 python3-venv python3-pip curl ca-certificates jq && \
    python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir flask requests waitress dnspython && \
    apt-get autoremove -y && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app
COPY server.py /app/server.py
COPY www /app/www
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8067
ENTRYPOINT []
CMD ["/run.sh"]