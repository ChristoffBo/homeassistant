# Use official Semaphore image
FROM semaphoreui/semaphore:latest

# Install additional dependencies if needed
RUN apt-get update && apt-get install -y \
    sqlite3 \
    curl \
    uuid-runtime \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy run script if you need to override entrypoint behavior
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Switch to workdir
WORKDIR /data

# Use exec form for better signal handling
CMD ["/run.sh"]
