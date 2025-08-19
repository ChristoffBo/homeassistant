# Use official Semaphore image
FROM semaphoreui/semaphore:latest

# Install optional utilities
RUN apt-get update && apt-get install -y \
    sqlite3 \
    curl \
    uuid-runtime \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy HA wrapper script
COPY run.sh /run.sh
RUN chmod +x /run.sh

WORKDIR /data

# Home Assistant Supervisor will map port via config.json
CMD ["/run.sh"]
