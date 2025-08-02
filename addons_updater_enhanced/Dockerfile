ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

# Install core dependencies with version pinning
RUN apk add --no-cache \
    bash=5.2.21-r0 \
    curl=8.4.0-r0 \
    git=2.40.1-r0 \
    jq=1.7.1-r0 \
    tzdata=2023c-r1

# Create directory structure
RUN mkdir -p \
    /etc/services.d/addons-updater \
    /etc/cont-init.d \
    /usr/bin \
    /var/log

# Copy root filesystem
COPY rootfs /

# Set permissions
RUN chmod a+x \
    /usr/bin/addons-updater \
    /etc/cont-init.d/00-addons-updater \
    /etc/services.d/addons-updater/run \
    && chmod 644 /var/log/addons-updater.log

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s \
    CMD pgrep -f addons-updater || exit 1

WORKDIR /data
ENTRYPOINT ["/init"]
CMD []
