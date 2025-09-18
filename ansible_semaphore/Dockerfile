FROM semaphoreui/semaphore:latest
USER root

COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

# Completely replace upstream entrypoint
ENTRYPOINT ["/usr/local/bin/run.sh"]