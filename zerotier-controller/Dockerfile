FROM debian:bullseye-slim

LABEL maintainer="ChristoffBo"
LABEL org.opencontainers.image.source="https://github.com/ChristoffBo/homeassistant"

ENV LANG=C.UTF-8

# Install required packages and ZeroTier
RUN apt-get update && \
    apt-get install -y \
        curl \
        gnupg \
        iproute2 \
        iptables \
        ca-certificates \
        nodejs \
        npm \
        git \
        jq \
        openssl \
        kmod \
    && curl -s https://install.zerotier.com | bash \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create working dir
RUN mkdir -p /app

# Copy all files from local context to container
COPY . /app/

# Set permission on scripts
RUN chmod +x /app/init.sh /app/run.sh

# Expose ZeroTier UDP port
EXPOSE 9993/udp

# Use root (ZeroTier requires NET_ADMIN and module loading)
USER root

# Entry point
CMD ["/app/run.sh"]