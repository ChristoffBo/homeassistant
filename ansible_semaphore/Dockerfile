FROM debian:stable-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    sqlite3 \
    curl \
    uuid-runtime \
    && rm -rf /var/lib/apt/lists/*

# Set Semaphore version
ENV SEMAPHORE_VERSION=2.9.34

# Download arch-specific Semaphore binary
RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then \
      URL=https://github.com/semaphoreui/semaphore/releases/download/v${SEMAPHORE_VERSION}/semaphore_${SEMAPHORE_VERSION}_linux_amd64 ; \
    elif [ "$ARCH" = "arm64" ]; then \
      URL=https://github.com/semaphoreui/semaphore/releases/download/v${SEMAPHORE_VERSION}/semaphore_${SEMAPHORE_VERSION}_linux_arm64 ; \
    else \
      echo "Unsupported architecture: $ARCH" && exit 1 ; \
    fi && \
    curl -L -o /usr/local/bin/semaphore $URL && \
    chmod +x /usr/local/bin/semaphore

# Create semaphore user
RUN useradd -m -d /data semaphore

# Copy entrypoint before switching user
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Switch to semaphore user
USER semaphore
WORKDIR /data

VOLUME ["/data"]

CMD ["/run.sh"]
