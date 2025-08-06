FROM ghcr.io/home-assistant/amd64-base:latest

# Install build dependencies
RUN apk add --no-cache \
    nodejs \
    npm \
    git \
    curl \
    build-base \
    linux-headers \
    clang \
    clang-dev \
    libstdc++-dev \
    openssl-dev

# Install Rust and Cargo
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal && \
    . $HOME/.cargo/env && \
    rustc --version

# Enable TUN module
RUN echo "tun" >> /etc/modules && \
    modprobe tun || true

# Compile ZeroTier One from source
RUN git clone https://github.com/zerotier/ZeroTierOne.git /tmp/ZeroTierOne && \
    cd /tmp/ZeroTierOne && \
    make && \
    make install && \
    mv /usr/sbin/zerotier-* /usr/bin/ && \
    rm -rf /tmp/ZeroTierOne

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