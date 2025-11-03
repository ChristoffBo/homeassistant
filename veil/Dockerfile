FROM debian:stable-slim

ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Africa/Johannesburg \
    PATH="/venv/bin:$PATH"

# ----------------------------------------------------
# System dependencies (comprehensive, additive)
# ----------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip python3-dev \
    ca-certificates curl wget gnupg dnsutils iproute2 iputils-ping \
    build-essential libssl-dev libffi-dev libc-ares-dev \
    libnss3 libgnutls30 libidn2-0 tzdata \
    openssl libpcre3 libpcre3-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ----------------------------------------------------
# Copy application files
# ----------------------------------------------------
COPY veil_module.py /app/veil_module.py
COPY entrypoint.sh /app/entrypoint.sh
COPY options.json /app/options.json
COPY logo.png /app/logo.png
COPY icon.png /app/icon.png
COPY ui /app/ui

# ----------------------------------------------------
# Python dependencies (inside isolated venv)
# ----------------------------------------------------
RUN python3 -m venv /venv && \
    /venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel && \
    /venv/bin/pip install --no-cache-dir \
        dnspython \
        aiohttp \
        aiodns \
        cryptography \
        aioquic \
        orjson \
        uvloop \
        aiologger \
        certifi \
        pyOpenSSL \
        service-identity \
        pylsqpack \
        cffi \
        idna \
        h2 \
        hpack

# ----------------------------------------------------
# Permissions and runtime setup
# ----------------------------------------------------
RUN chmod +x /app/entrypoint.sh

VOLUME ["/config", "/var/log/veil"]

# ----------------------------------------------------
# Exposed network ports
# ----------------------------------------------------
EXPOSE 53/udp
EXPOSE 53/tcp
EXPOSE 67/udp
EXPOSE 68/udp
EXPOSE 69/udp
EXPOSE 123/udp
EXPOSE 853/tcp
EXPOSE 853/udp
EXPOSE 784/udp
EXPOSE 443/tcp
EXPOSE 80/tcp
EXPOSE 8080/tcp
EXPOSE 9090/tcp
EXPOSE 9180/tcp

# ----------------------------------------------------
# Entrypoint and command
# ----------------------------------------------------
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "/app/veil_module.py"]