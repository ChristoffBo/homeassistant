FROM debian:bullseye-slim

# Install dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        git \
        tar \
        bash \
        jq \
        ca-certificates \
        nodejs \
        npm && \
    npm install -g yarn && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install ZeroTier One
RUN curl -s https://install.zerotier.com | bash

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