FROM debian:bullseye-slim

LABEL maintainer="ChristoffBo"
LABEL org.opencontainers.image.source="https://github.com/ChristoffBo/homeassistant"

ENV LANG=C.UTF-8

# Install dependencies
RUN apt-get update && \
    apt-get install -y curl gnupg iproute2 iptables ca-certificates nodejs npm git && \
    curl -s https://install.zerotier.com | bash && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Create working dir
RUN mkdir -p /app

# Copy all your source files
COPY rootfs/ /

# Permissions
RUN chmod +x /run.sh /app/init.sh

# Expose ZeroTier
EXPOSE 9993/udp

# Run as root (ZeroTier needs net perms)
USER root

CMD ["/run.sh"]