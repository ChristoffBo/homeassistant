# syntax=docker/dockerfile:1.4
ARG BUILD_FROM
FROM $BUILD_FROM

# Set environment
ENV LANG=C.UTF-8 \
    S6_SERVICES_GRACETIME=30000 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0

# Install core dependencies
RUN apk add --no-cache \
    bash \
    jq \
    curl \
    python3 \
    tzdata

# Create virtual environment
RUN python3 -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Install Python dependencies in virtual environment
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

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
