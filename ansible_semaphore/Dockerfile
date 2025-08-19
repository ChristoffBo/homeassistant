# Home Assistant add-on for Ansible Semaphore (official upstream image)
FROM semaphoreui/semaphore:latest

# We need root so we can ensure /share subdirs exist and are writable
USER root

# Wrapper entrypoint (no chmod layer needed; we exec with /bin/sh)
COPY run.sh /usr/local/bin/run.sh

# Convenience only; HA persistence is through /share mount
WORKDIR /share/ansible_semaphore

# Start wrapper
CMD ["/bin/sh", "/usr/local/bin/run.sh"]