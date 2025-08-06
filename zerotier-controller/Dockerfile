FROM node:18-alpine

# Install dependencies
RUN apk add --no-cache git curl tar bash jq

# Install ZeroTier One
RUN apk add --no-cache --repository=http://dl-cdn.alpinelinux.org/alpine/v3.17/community zerotier-one && \
    ln -s /usr/sbin/zerotier-one /usr/bin/zerotier-cli

# Enable TUN module
RUN echo "tun" >> /etc/modules && \
    modprobe tun || true

# Install ZeroUI with legacy peer dependencies
RUN git clone https://github.com/dec0dOS/zero-ui.git /app/zero-ui && \
    cd /app/zero-ui && \
    npm install --legacy-peer-deps && \
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