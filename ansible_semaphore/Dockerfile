FROM debian:stable-slim

# Set Semaphore version as build arg for flexibility
ARG SEMAPHORE_VERSION=2.9.34

# Install dependencies in a single layer and clean up
RUN apt-get update && apt-get install -y \
    ca-certificates \
    sqlite3 \
    curl \
    uuid-runtime \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Download arch-specific Semaphore binary with correct names
RUN set -eux; \
    ARCH=$(dpkg --print-architecture); \
    case "$ARCH" in \
        amd64) \
            URL="https://github.com/semaphoreui/semaphore/releases/download/v${SEMAPHORE_VERSION}/semaphore"; \
            ;; \
        arm64) \
            URL="https://github.com/semaphoreui/semaphore/releases/download/v${SEMAPHORE_VERSION}/semaphore_arm64"; \
            ;; \
        *) \
            echo >&2 "Unsupported architecture: $ARCH"; \
            exit 1; \
            ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/semaphore "$URL"; \
    chmod +x /usr/local/bin/semaphore; \
    /usr/local/bin/semaphore version || (echo "Binary verification failed" && exit 1)

# Create semaphore user with specific UID/GID for consistency
RUN groupadd -r -g 1000 semaphore && \
    useradd -r -u 1000 -g semaphore -d /data -s /bin/bash semaphore

# Copy entrypoint script with proper ownership
COPY run.sh /run.sh
RUN chown semaphore:semaphore /run.sh && chmod +x /run.sh

# Switch to semaphore user
USER semaphore
WORKDIR /data

# Add health check on default port 10443
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fk http://localhost:10443/ || exit 1

# Expose default port
EXPOSE 10443

# Set volume
VOLUME ["/data"]

# Use exec form for better signal handling
CMD ["/run.sh"]
