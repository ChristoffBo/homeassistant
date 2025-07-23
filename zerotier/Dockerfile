# Base image
FROM alpine:3.19

# Install dependencies
RUN apk update && \
    apk add --no-cache \
      curl \
      bash \
      supervisor \
      npm \
      git

# Download ZeroTier static binary
WORKDIR /usr/sbin
RUN curl -L -o zerotier-one.tar.gz https://download.zerotier.com/RELEASES/1.10.6/dist/zerotier-one-x86_64-linux-musl.tar.gz && \
    tar xzf zerotier-one.tar.gz && \
    chmod +x zerotier-one zerotier-cli zerotier-idtool && \
    rm zerotier-one.tar.gz

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