ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install runtime deps (Alpine)
# cronie provides crond; flask/gunicorn from repos
RUN apk add --no-cache \
    bash curl jq coreutils pigz pv openssh-client sshpass rsync rclone \
    python3 py3-flask py3-gunicorn cronie gzip

# App
WORKDIR /app

# Copy application files
COPY api.py scheduler.py job_runner.py run.sh /app/
COPY www /app/www

# Ensure Unix LF endings and exec bit on run.sh (fixes "Permission denied")
RUN sed -i 's/\r$//' /app/run.sh && chmod 0755 /app/run.sh

# Log file for cronie jobs (optional)
RUN touch /var/log/remote_linux_backup.log

# Entrypoint
CMD ["/app/run.sh"]
