# Use official Semaphore image
FROM semaphoreui/semaphore:latest

# Build as root so we can install our entrypoint
USER root

# Install run.sh and make it executable
COPY run.sh /usr/local/bin/run.sh
RUN chmod 0755 /usr/local/bin/run.sh

# Workdir may be used by Semaphore (we still export explicit paths in run.sh)
WORKDIR /data

# Ensure our entrypoint runs (so the image never tries to write to /config or /share)
ENTRYPOINT ["/usr/local/bin/run.sh"]