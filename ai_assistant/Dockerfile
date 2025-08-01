ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

# Install Python only (no pip)
RUN apk add --no-cache python3

WORKDIR /app

# Copy minimal required files
COPY app /app
COPY run.sh /

# Set critical permissions
RUN chmod a+x /run.sh && \
    chmod -R 755 /app && \
    chown -R root:root /app

# s6-overlay entrypoint (must be /init)
ENTRYPOINT ["/init"]