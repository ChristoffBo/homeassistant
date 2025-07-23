
# syntax=docker/dockerfile:1

# Base image
FROM debian:bullseye-slim

# Build arguments
ARG BUILD_ARCH
ARG BUILD_VERSION

# Environment
ENV LANG C.UTF-8

# Install dependencies
RUN apt-get update && \
    apt-get install -y \
        curl \
        bash \
        supervisor \
        git \
        gnupg \
        iproute2 \
        iptables && \
    rm -rf /var/lib/apt/lists/*

# Install ZeroTier
RUN curl -s https://install.zerotier.com | bash

# Install Node.js v20 and Yarn
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g yarn

# Create required directories
RUN mkdir -p /var/lib/zerotier-one /opt/zero-ui /app/backend/data /var/log/supervisor

# Clone Zero-UI
WORKDIR /opt
RUN git clone https://github.com/dec0dos/zero-ui.git

# Build Zero-UI
WORKDIR /opt/zero-ui
RUN npm install --legacy-peer-deps && \
    npm run build

# Copy Supervisor configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose ports
EXPOSE 3000 9993

# Start Supervisor
CMD ["/usr/bin/supervisord", "-n"]