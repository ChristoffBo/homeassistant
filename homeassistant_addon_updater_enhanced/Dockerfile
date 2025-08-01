# syntax=docker/dockerfile:1.4
ARG BUILD_FROM
FROM $BUILD_FROM

# Set environment variables
ENV LANG=C.UTF-8 \
    S6_SERVICES_GRACETIME=30000 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0

# Install base dependencies
RUN apk add --no-cache \
    bash=5.2.15-r5 \
    jq=1.6-r3 \
    curl=7.83.1-r4 \
    python3=3.10.12-r0 \
    py3-pip=22.3.1-r1 \
    tzdata=2023c-r0

# Install Python dependencies
COPY requirements.txt /tmp/
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# Copy root filesystem
COPY rootfs /

# Set entrypoint
ENTRYPOINT ["/init"]

# Health check
HEALTHCHECK --interval=30s --timeout=10s \
    CMD curl -f http://localhost/health || exit 1

# Labels
LABEL \
    io.hass.name="Addon Updater Enhanced" \
    io.hass.description="Enhanced addon update checker with Gotify support" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version=${BUILD_VERSION} \
    maintainer="Your Name <your@email.com>"
