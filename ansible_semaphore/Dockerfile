# Home Assistant add-on: Ansible Semaphore (official upstream image)
FROM semaphoreui/semaphore:latest

# Use root so we can create /share/ansible_semaphore (Supervisor maps /share:rw)
USER root

# Copy startup wrapper; we will invoke it via /bin/sh (no chmod inside image needed)
COPY run.sh /usr/local/bin/run.sh

# Persistent working directory (mounted via "map": ["share:rw"] in config.json)
WORKDIR /share/ansible_semaphore

# Always call with sh to avoid needing the executable bit from GitHub
CMD ["/bin/sh", "/usr/local/bin/run.sh"]