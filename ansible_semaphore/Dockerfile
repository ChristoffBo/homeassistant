# Use official Semaphore image
FROM semaphoreui/semaphore:latest

# Copy Home Assistant wrapper script
COPY run.sh /run.sh
RUN chmod +x /run.sh

WORKDIR /data

# Start with HA wrapper
CMD ["/run.sh"]
