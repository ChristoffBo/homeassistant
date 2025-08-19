# Dockerfile for Home Assistant Ansible Semaphore add-on
FROM semaphoreui/semaphore:latest

# Copy startup wrapper
COPY run.sh /usr/local/bin/run.sh
USER root
RUN chmod 0755 /usr/local/bin/run.sh

# Workdir for persistent storage
WORKDIR /share/ansible_semaphore

ENTRYPOINT ["/usr/local/bin/run.sh"]