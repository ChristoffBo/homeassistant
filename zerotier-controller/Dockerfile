FROM ghcr.io/home-assistant/amd64-base:latest

# Install dependencies
RUN apk add --no-cache nodejs npm git curl tar

# Install ZeroTier One using pre-built binary
RUN curl -sL https://github.com/zerotier/ZeroTierOne/releases/download/1.14.0/zerotier-one_1.14.0_x86_64.tar.gz -o /tmp/zerotier-one.tar.gz && \
    tar -xzf /tmp/zerotier-one.tar.gz -C /usr/bin/ && \
    mv /usr/bin/zerotier-one /usr/bin/zerotier-cli && \
    ln -s /usr/bin/zerotier-cli /usr/bin/zerotier-one && \
    rm /tmp/zerotier-one.tar.gz

# Enable TUN module
RUN echo "tun" >> /etc/modules && \
    modprobe tun || true

# Install ZeroUI
RUN git clone https://github.com/dec0dOS/zero-ui.git /app/zero-ui && \
    cd /app/zero-ui && \
    npm install && \
    npm run build

# Copy add-on files
COPY run.sh /app/
COPY init.sh /app/
COPY zero-ui-config.yaml /app/zero-ui/config.yaml
COPY www /app/zero-ui/www/

# Set permissions
RUN chmod a+x /app/run.sh /app/init.sh

# Set working directory
WORKDIR /app

CMD ["/app/run.sh"]