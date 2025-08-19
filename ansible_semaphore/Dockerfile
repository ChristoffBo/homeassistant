# Home Assistant add-on Dockerfile for Semaphore

# Supervisor injects the base from build.json
ARG BUILD_FROM
FROM $BUILD_FROM

# Workdir for persistent storage
WORKDIR /data

# Copy startup script with correct permissions
COPY --chmod=0755 run.sh /usr/local/bin/run.sh

# Entrypoint
ENTRYPOINT ["/usr/local/bin/run.sh"]