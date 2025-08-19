ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install Semaphore
RUN apk add --no-cache curl ca-certificates sqlite bash && \
    curl -L https://github.com/semaphoreui/semaphore/releases/download/v2.16.17/semaphore_linux_amd64 \
      -o /usr/local/bin/semaphore && \
    chmod +x /usr/local/bin/semaphore

# Copy startup script
COPY run.sh /usr/local/bin/run.sh
RUN chmod 0755 /usr/local/bin/run.sh

WORKDIR /data

ENTRYPOINT [ "/usr/local/bin/run.sh" ]