FROM debian:stable-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Add Semaphore binary from official image
ADD https://github.com/semaphoreui/semaphore/releases/download/v2.9.34/semaphore_linux_amd64 /usr/local/bin/semaphore
RUN chmod +x /usr/local/bin/semaphore

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
