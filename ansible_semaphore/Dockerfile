# Home Assistant add-on for Ansible Semaphore
# Base: official upstream image
FROM semaphoreui/semaphore:latest

USER root

# Copy wrapper; we'll execute it with /bin/sh, so no chmod needed
COPY run.sh /usr/local/bin/run.sh

# Where we keep persistent data (mounted by HA Supervisor via "map": ["share:rw"])
WORKDIR /share/ansible_semaphore

# Start wrapper
CMD ["/bin/sh", "/usr/local/bin/run.sh"]