# Home Assistant add-on for Ansible Semaphore (official upstream image)
FROM semaphoreui/semaphore:latest

# Ensure we can write to /share
USER root

# Wrapper entrypoint
COPY run.sh /usr/local/bin/run.sh

# Convenience; persistence is via /share at runtime
WORKDIR /share/ansible_semaphore

# Start wrapper
CMD ["/bin/sh", "/usr/local/bin/run.sh"]