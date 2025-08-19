FROM debian:stable-slim

ARG SEMAPHORE_VERSION=2.9.34

# Install essential dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    sqlite3 \
    curl \
    tar \
    uuid-runtime \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Download and unpack Semaphore binary
RUN set -eux; \
    ARCH=$(dpkg --print-architecture); \
    case "$ARCH" in \
        amd64) FILE="semaphore_v${SEMAPHORE_VERSION}_linux_amd64.tar.gz"; ;; \
        arm64) FILE="semaphore_v${SEMAPHORE_VERSION}_linux_arm64.tar.gz"; ;; \
        armhf|armv7l) FILE="semaphore_v${SEMAPHORE_VERSION}_linux_armv7.tar.gz"; ;; \
        *) echo >&2 "Unsupported arch: $ARCH"; exit 1 ;; \
    esac; \
    URL="https://github.com/semaphoreui/semaphore/releases/download/v${SEMAPHORE_VERSION}/${FILE}"; \
    curl -fsSL -o /tmp/semaphore.tar.gz "$URL"; \
    tar -xzf /tmp/semaphore.tar.gz -C /usr/local/bin semaphore; \
    rm /tmp/semaphore.tar.gz; \
    chmod +x /usr/local/bin/semaphore; \
    /usr/local/bin/semaphore version || (echo "Binary check failed" && exit 1)

# Create unprivileged user
RUN groupadd -r -g 1000 semaphore && \
    useradd -r -u 1000 -g semaphore -d /data -s /bin/bash semaphore

# Copy entrypoint and set permissions
COPY run.sh /run.sh
RUN chown semaphore:semaphore /run.sh && chmod +x /run.sh

# Run as non-root
USER semaphore
WORKDIR /data

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fk http://localhost:10443/ || exit 1

EXPOSE 10443
VOLUME ["/data"]

CMD ["/run.sh"]
