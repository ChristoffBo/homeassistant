ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install runtime deps (use cronie on Alpine)
RUN apk add --no-cache \
    bash curl jq coreutils pigz pv openssh-client sshpass rsync rclone cronie gzip

# App
WORKDIR /app
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY api.py scheduler.py job_runner.py run.sh /app/
COPY www /app/www

# Log file for cronie jobs (optional)
RUN touch /var/log/remote_linux_backup.log

CMD ["/app/run.sh"]
