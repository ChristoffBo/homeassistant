ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

# Install only Python (no pip)
RUN apk add --no-cache python3

WORKDIR /app

# Copy ONLY what's needed
COPY app /app
COPY run.sh /

# Set CORRECT permissions (critical fix)
RUN chmod a+x /run.sh && \
    chmod -R 755 /app && \
    chown -R root:root /app

# Use s6's init system properly
ENTRYPOINT ["/init"]