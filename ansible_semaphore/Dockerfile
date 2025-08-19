# Home Assistant add-on for Ansible Semaphore (official upstream image)
FROM semaphoreui/semaphore:latest

# Ensure we can write to /share
USER root

# Wrapper entrypoint (we call with /bin/sh so no chmod layer needed)
COPY run.sh /usr/local/bin/run.sh

# Workdir only for convenience; HA persistence is via /share mount
WORKDIR /share/ansible_semaphore

# Start wrapper
CMD ["/bin/sh", "/usr/local/bin/run.sh"]