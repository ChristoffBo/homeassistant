ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install dependencies
RUN apk add --no-cache \
    bash \
    curl \
    git \
    jq \
    tzdata

# Create directories first
RUN mkdir -p \
    /etc/cont-init.d \
    /etc/services.d/addons-updater \
    /usr/bin \
    /var/log

# Copy files individually to ensure proper placement
COPY rootfs/usr/bin/addons-updater /usr/bin/addons-updater
COPY rootfs/etc/cont-init.d/addons-updater /etc/cont-init.d/
COPY rootfs/etc/services.d/addons-updater/run /etc/services.d/addons-updater/

# Verify files were copied
RUN ls -la /usr/bin/addons-updater && \
    ls -la /etc/cont-init.d/addons-updater && \
    ls -la /etc/services.d/addons-updater/run

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
