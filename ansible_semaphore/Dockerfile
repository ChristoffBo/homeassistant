# Home Assistant add-on: Ansible Semaphore
ARG BUILD_FROM
FROM $BUILD_FROM

# Run as root so we can create persistent directories under mapped volumes
USER root

# Copy startup script with correct permissions (avoids chmod failures)
COPY --chmod=0755 run.sh /usr/local/bin/run.sh

# Workdir not strictly required; we use absolute paths in run.sh
WORKDIR /

# Start
ENTRYPOINT ["/usr/local/bin/run.sh"]