ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

WORKDIR /app

# Install Python only (no pip)
RUN apk add --no-cache python3

# Copy application files
COPY app /app
COPY run.sh /

# Critical permissions
RUN chmod a+x /run.sh && \
    chmod -R 755 /app && \
    chown -R root:root /app

# s6-overlay entrypoint (MUST be /init)
ENTRYPOINT ["/init"]