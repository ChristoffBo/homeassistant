# Home Assistant Add-on: Ansible Semaphore
FROM semaphoreui/semaphore:latest

# Copy our startup script
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Work in /data which HA persists
WORKDIR /data

# Entrypoint
CMD ["/run.sh"]