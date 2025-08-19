# Home Assistant add-on Dockerfile for Semaphore
FROM semaphoreui/semaphore:latest

# Copy startup wrapper
COPY run.sh /usr/local/bin/run.sh

# Workdir for persistent storage
WORKDIR /share/ansible_semaphore

# Always call with sh (avoids needing +x bit)
CMD ["sh", "/usr/local/bin/run.sh"]