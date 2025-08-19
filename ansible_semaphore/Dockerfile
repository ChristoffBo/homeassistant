# Use official Semaphore image
FROM semaphoreui/semaphore:latest

# Provide our entrypoint so Supervisor can build and control it
COPY run.sh /run.sh
RUN chmod +x /run.sh

WORKDIR /data
CMD ["/run.sh"]