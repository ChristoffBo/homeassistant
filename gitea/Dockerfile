ARG BUILD_FROM=ghcr.io/hassio-addons/base:14.0.0
FROM ${BUILD_FROM}

# Install dependencies
RUN apk add --no-cache \
    git \
    openssh \
    sqlite \
    tzdata

# Create gitea user and directories
RUN adduser -D -h /data/gitea -s /bin/bash git && \
    mkdir -p /data/gitea/{conf,data,logs,repositories} && \
    chown -R git:git /data/gitea

# Install Gitea binary
RUN wget -O /usr/local/bin/gitea \
    https://dl.gitea.io/gitea/1.18.0/gitea-1.18.0-linux-${BUILD_ARCH} && \
    chmod +x /usr/local/bin/gitea

# Copy root filesystem
COPY rootfs /

# Build arguments
ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION

# Labels
LABEL \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version=${BUILD_VERSION} \
    org.opencontainers.image.title="${BUILD_NAME}" \
    org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
    org.opencontainers.image.vendor="Home Assistant Add-ons" \
    org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.version=${BUILD_VERSION}