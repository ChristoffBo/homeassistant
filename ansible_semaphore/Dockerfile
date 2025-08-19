# Home Assistant add-on: Ansible Semaphore (official upstream image)
FROM semaphoreui/semaphore:latest

USER root

# Copy startup wrapper; invoke with /bin/sh (no chmod in image needed)
COPY run.sh /usr/local/bin/run.sh

# Persistent area (Supervisor maps /share:rw)
WORKDIR /share/ansible_semaphore

CMD ["/bin/sh", "/usr/local/bin/run.sh"]