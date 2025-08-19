FROM debian:stable-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set Semaphore version
ENV SEMAPHORE_VERSION=2.9.34

# Download Semaphore binary directly
RUN curl -L -o /usr/local/bin/semaphore https://github.com/semaphoreui/semaphore/releases/download/v${SEMAPHORE_VERSION}/semaphore \
    && chmod +x /usr/local/bin/semaphore

# Create semaphore user
RUN useradd -m -d /data semaphore

# Copy entrypoint script before dropping privileges
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Switch to semaphore user
USER semaphore
WORKDIR /data

# Persistent storage
VOLUME ["/data"]

CMD ["/run.sh"]
