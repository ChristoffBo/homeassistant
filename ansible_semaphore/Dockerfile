FROM debian:stable-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    sqlite3 \
    curl \
    tar \
    && rm -rf /var/lib/apt/lists/*

# Set Semaphore version
ENV SEMAPHORE_VERSION=2.9.34

# Download and extract Semaphore binary
RUN curl -L -o /tmp/semaphore.tar.gz https://github.com/semaphoreui/semaphore/releases/download/v${SEMAPHORE_VERSION}/semaphore_${SEMAPHORE_VERSION}_linux_amd64.tar.gz \
    && tar -xzf /tmp/semaphore.tar.gz -C /usr/local/bin semaphore \
    && rm /tmp/semaphore.tar.gz \
    && chmod +x /usr/local/bin/semaphore

# Create semaphore user
RUN useradd -m -d /data semaphore
USER semaphore
WORKDIR /data

# Persistent storage
VOLUME ["/data"]

# Entrypoint
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
