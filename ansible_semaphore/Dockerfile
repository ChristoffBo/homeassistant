# Home Assistant add-on: Ansible Semaphore (using official upstream image)
FROM semaphoreui/semaphore:latest

# Must be root to create /share content (Supervisor maps /share:rw)
USER root

# Copy startup wrapper; invoke it with /bin/sh to avoid chmod inside image
COPY run.sh /usr/local/bin/run.sh

# Workdir points to the persistent area provided by Supervisor via share:rw
WORKDIR /share/ansible_semaphore

# Start
CMD ["/bin/sh", "/usr/local/bin/run.sh"]