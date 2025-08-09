ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install runtime deps
RUN apk add --no-cache     bash curl jq coreutils pigz pv openssh-client sshpass rsync rclone cron gzip

# Copy app
WORKDIR /app
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir -r /app/requirements.txt
COPY api.py scheduler.py job_runner.py run.sh /app/
COPY www /app/www

# Cron log file
RUN touch /var/log/remote_linux_backup.log

# Entrypoint
CMD ["/app/run.sh"]
