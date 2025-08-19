# Dockerfile – Home Assistant Ansible Semaphore Add-on
ARG BUILD_FROM
FROM $BUILD_FROM

# Copy startup script
COPY run.sh /usr/local/bin/run.sh
RUN chmod 0755 /usr/local/bin/run.sh

# Workdir for persistent data
WORKDIR /data

# Start
ENTRYPOINT ["/usr/local/bin/run.sh"]