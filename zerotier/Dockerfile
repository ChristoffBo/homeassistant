# Base image
FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && \
    apt-get install -y \
      wget \
      curl \
      ca-certificates \
      supervisor \
      zerotier-one \
      git \
      build-essential
      
# Install Zerotier Official Repo
RUN curl -s https://install.zerotier.com | bash
      
# Install Node.js for ZeroUI (if required)
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs

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
