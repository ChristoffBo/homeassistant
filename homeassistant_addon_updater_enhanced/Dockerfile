# syntax=docker/dockerfile:1.4
ARG BUILD_FROM
FROM $BUILD_FROM

# Set environment
ENV LANG=C.UTF-8 \
    S6_SERVICES_GRACETIME=30000 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0

# Install all dependencies using Alpine packages
RUN apk add --no-cache \
    bash \
    jq \
    curl \
    tzdata

# Copy root filesystem
COPY rootfs /

# Set entrypoint
ENTRYPOINT ["/init"]

# Labels
LABEL \
    io.hass.name="Addon Updater Enhanced" \
    io.hass.description="Enhanced addon update checker with Gotify support" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version=${BUILD_VERSION} \
    maintainer="Your Name <your@email.com>"
