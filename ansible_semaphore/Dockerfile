# Use official Semaphore image
FROM semaphoreui/semaphore:2.9.34

# Copy wrapper script (make sure it is chmod +x locally before build)
COPY run.sh /run.sh

# Set working directory
WORKDIR /data

# Override entrypoint with our wrapper
ENTRYPOINT ["/run.sh"]
