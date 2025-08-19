# Home Assistant add-on Dockerfile for Semaphore
FROM semaphoreui/semaphore:latest

# Copy startup wrapper
COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

# Workdir for persistent storage
WORKDIR /share/ansible_semaphore

# Entrypoint
CMD ["/usr/local/bin/run.sh"]