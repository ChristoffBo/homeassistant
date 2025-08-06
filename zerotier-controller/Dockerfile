FROM debian:bullseye-slim

LABEL maintainer="ChristoffBo"
LABEL org.opencontainers.image.source="https://github.com/ChristoffBo/homeassistant"

# Set environment
ENV LANG=C.UTF-8

# Install dependencies and ZeroTier
RUN apt-get update && \
    apt-get install -y \
        curl \
        gnupg \
        iproute2 \
        iptables \
        ca-certificates \
        nodejs \
        npm \
        git && \
    curl -s https://install.zerotier.com | bash && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Create app working dir
RUN mkdir -p /app

# Copy all local files into /app
COPY . /app/

# Make startup scripts executable
RUN chmod +x /app/run.sh /app/init.sh

# Expose ZeroTier port
EXPOSE 9993/udp

# Use root user (required for network privileges)
USER root

# Set the default command