# Dockerfile for Veil (Debian slim) - ALL ports exposed
FROM debian:slim

ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Africa/Johannesburg

# Install minimal system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ca-certificates curl gnupg dnsutils procps iproute2 iputils-ping \
    build-essential libssl-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# create directories
RUN mkdir -p /app /var/log/veil /config

# copy app + defaults (ensure these exist in build context)
COPY veil_module.py /app/veil_module.py
COPY default_options.json /app/default_options.json
COPY entrypoint.sh /app/entrypoint.sh
COPY ui /app/ui

# install python libs (adjust additions as needed)
RUN pip3 install --no-cache-dir dnspython aiohttp aiodns cryptography || true && \
    pip3 install --no-cache-dir aioquic || true

# Volumes
VOLUME ["/config", "/var/log/veil"]

# EXPOSE - DNS / DHCP / TFTP / NTP / DoT / DoH / DoQ / UI
# DNS
EXPOSE 53/udp
EXPOSE 53/tcp
# DHCP (server listens UDP 67; clients on 68)
EXPOSE 67/udp
EXPOSE 68/udp
# TFTP (optional, bootstrap)
EXPOSE 69/udp
# NTP (if serving NTP to clients)
EXPOSE 123/udp
# DoT (DNS-over-TLS)
EXPOSE 853/tcp
# DoH (HTTP(S) based) - 443, and optional HTTP 80
EXPOSE 443/tcp
EXPOSE 80/tcp
# DoQ (DNS-over-QUIC) - expose UDP 853 and UDP 784 for compatibility
EXPOSE 853/udp
EXPOSE 784/udp
# UI (internal UI port)
EXPOSE 8080/tcp
# metrics / admin (optional)
EXPOSE 9180/tcp
EXPOSE 9090/tcp

# Ensure entrypoint executable
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "/app/veil_module.py"]
