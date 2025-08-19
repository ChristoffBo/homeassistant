# Use official Semaphore image
FROM semaphoreui/semaphore:latest

# Switch to root to modify filesystem during build
USER root

# Install our entrypoint
COPY run.sh /usr/local/bin/run.sh
RUN chmod 0755 /usr/local/bin/run.sh

WORKDIR /data
ENTRYPOINT ["/usr/local/bin/run.sh"]