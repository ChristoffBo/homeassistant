# Home Assistant add-on: Ansible Semaphore (official image, no package installs)
FROM semaphoreui/semaphore:latest

# Copy startup wrapper (no chmod inside container; we invoke with /bin/sh)
COPY run.sh /usr/local/bin/run.sh

# Persistent working directory (mounted via "map": ["share:rw"])
WORKDIR /share/ansible_semaphore

# Always call with sh to avoid executable-bit requirements
CMD ["/bin/sh", "/usr/local/bin/run.sh"]