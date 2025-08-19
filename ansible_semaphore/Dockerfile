# Use official Semaphore image as base
ARG BUILD_FROM
FROM $BUILD_FROM

# Ensure working directory
WORKDIR /data

# Copy startup script with correct permissions
COPY --chmod=0755 run.sh /usr/local/bin/run.sh

# Entrypoint
ENTRYPOINT ["/usr/local/bin/run.sh"]