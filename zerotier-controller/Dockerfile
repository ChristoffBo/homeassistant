FROM debian:bullseye-slim

LABEL maintainer="ChristoffBo"
LABEL org.opencontainers.image.source="https://github.com/ChristoffBo/homeassistant"

ENV LANG=C.UTF-8

# Install required tools and ZeroTier
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

# Create application directory
RUN mkdir -p /app

# Copy all local files into container
COPY . /app/

# Set script permissions
RUN chmod +x /app/run.sh /app/init.sh

# Expose ZeroTier UDP port
EXPOSE 9993/udp

# Run as root
USER root

# Start command
CMD ["/app/run.sh"]