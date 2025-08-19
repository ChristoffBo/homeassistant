# Use official Semaphore image
FROM semaphoreui/semaphore:latest

# Copy wrapper startup script
COPY run.sh /usr/local/bin/run.sh

# Make sure it’s executable
USER root
RUN chmod 0755 /usr/local/bin/run.sh
USER 1001

# Persistent working directory
WORKDIR /data

ENTRYPOINT ["/usr/local/bin/run.sh"]