FROM debian:bullseye-slim

# Install dependencies
RUN apt-get update && \
    apt-get install -y curl bash supervisor git gnupg && \
    rm -rf /var/lib/apt/lists/*

# Install ZeroTier
RUN curl -s https://install.zerotier.com | bash

# Install Node.js v20 (for Zero-UI)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs

# Create necessary directories
RUN mkdir -p /var/lib/zerotier-one /opt/zero-ui /app/backend/data /var/log/supervisor

# Clone Zero-UI
WORKDIR /opt
RUN git clone https://github.com/dec0dos/zero-ui.git

WORKDIR /opt/zero-ui

# Install Zero-UI dependencies and build
RUN npm install --legacy-peer-deps && \
    npm run build

# Copy Supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose ports (adjust as needed)
EXPOSE 3000 9993

# Start Supervisor
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
