# Use official Semaphore image
FROM semaphoreui/semaphore:latest

# Build as root to install entrypoint
USER root

COPY run.sh /usr/local/bin/run.sh
RUN chmod 0755 /usr/local/bin/run.sh

WORKDIR /data
ENTRYPOINT ["/usr/local/bin/run.sh"]