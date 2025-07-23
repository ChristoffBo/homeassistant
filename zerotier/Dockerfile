FROM debian:bullseye-slim

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive

# Install base dependencies
RUN apt-get update && \
    apt-get install -y \
        curl \
        bash \
        supervisor \
        git \
        gnupg && \
    rm -rf /var/lib/apt/lists/*

# Install updated Node.js v16 from NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_16.x | bash - && \
    apt-get install -y nodejs

# Install ZeroTier
RUN curl -s https://install.zerotier.com | bash

# Create required directories
RUN mkdir -p /var/lib/zerotier-one /app/backend/data /var/log/supervisor

# Clone ZeroUI
WORKDIR /opt
RUN git clone https://github.com/dec0dos/zero-ui.git

# Set working directory
WORKDIR /opt/zero-ui

# Install npm dependencies
RUN npm install --production --legacy-peer-deps

# Disable husky postinstall if not needed in production to avoid build failure
RUN npm set-script postinstall ""

# Copy supervisord config (adjust path if needed)
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose ZeroUI default port (adjust if different)
EXPOSE 4000

# Start supervisord
CMD ["/usr/bin/supervisord"]
