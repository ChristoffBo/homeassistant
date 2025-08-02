# ==============================================
# Enhanced version of alexbelgium's addon-updater
# Now with GitHub/Gitea choice + Gotify support
# ==============================================

ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

# Set core dependencies with explicit versions
RUN apk add --no-cache --update \
    bash=5.2.21-r0 \
    curl=8.4.0-r0 \
    git=2.40.1-r0 \
    jq=1.7.1-r0 \
    tzdata=2023c-r1 \
    && rm -rf /var/cache/apk/*

# Create directory structure
RUN mkdir -p \
    /etc/services.d/addons-updater \
    /etc/cont-init.d \
    /usr/bin \
    /var/log

# Copy entire rootfs
COPY rootfs /

# Set strict permissions
RUN find /usr/bin -type f -exec chmod 755 {} \; \
    && chmod 644 /var/log/addons-updater.log \
    && chown root:root \
        /etc/cont-init.d/00-addons-updater \
        /etc/services.d/addons-updater/run

# Health check configuration
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s \
    CMD pgrep -f addons-updater || exit 1

WORKDIR /data
ENTRYPOINT ["/init"]
