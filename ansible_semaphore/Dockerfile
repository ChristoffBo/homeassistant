# Home Assistant add-on for Ansible Semaphore (official upstream image)
FROM semaphoreui/semaphore:latest

# Run as root so we can write to /share
USER root

# Add wrapper entrypoint
COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

# Set working dir to your HA share path
WORKDIR /share/ansible_semaphore

# Force start via wrapper (no upstream auto-setup)
ENTRYPOINT ["/usr/local/bin/run.sh"]