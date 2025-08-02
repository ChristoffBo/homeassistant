ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install core dependencies
RUN apk add --no-cache \
    bash \
    curl \
    git \
    jq \
    tzdata

# Create directory structure
RUN mkdir -p \
    /etc/cont-init.d \
    /etc/services.d/addons-updater \
    /usr/bin \
    /var/log

# Copy root filesystem
COPY rootfs /

# Set permissions
RUN chmod a+x \
    /usr/bin/addons-updater \
    /etc/cont-init.d/addons-updater \
    /etc/services.d/addons-updater/run && \
    chmod 644 /var/log/addons-updater.log

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s \
    CMD pgrep -f addons-updater || exit 1

WORKDIR /data
ENTRYPOINT ["/init"]
CMD []
