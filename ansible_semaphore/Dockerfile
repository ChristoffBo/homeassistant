# Use official Semaphore image
FROM semaphoreui/semaphore:latest

# No run.sh override needed — but if you want Supervisor to control entrypoint, copy it in:
COPY run.sh /run.sh
RUN chmod +x /run.sh

WORKDIR /data
CMD ["/run.sh"]