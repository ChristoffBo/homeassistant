# Always track the latest Semaphore release
FROM semaphoreui/semaphore:latest

# Copy wrapper script (make sure it has +x permissions locally before build)
COPY run.sh /run.sh

# Workdir for config/db
WORKDIR /data

# Entrypoint for HA wrapper
ENTRYPOINT ["/run.sh"]
