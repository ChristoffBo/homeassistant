# Base image
FROM debian:bullseye-slim

# Install dependencies
RUN apt-get update && \
    apt-get install -y \
      curl \
      bash \
      supervisor \
      npm \
      git

# Install ZeroTier
RUN curl -s https://install.zerotier.com | bash

# Create directories
RUN mkdir -p /var/lib/zerotier-one /app/backend/data /var/log/supervisor

# Install ZeroUI
WORKDIR /opt
RUN git clone https://github.com/dec0dos/zero-ui.git
WORKDIR /opt/zero-ui
RUN npm install --production

# Copy supervisord config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose ports
EXPOSE 9993/udp
EXPOSE 4000/tcp

# Start supervisord
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
