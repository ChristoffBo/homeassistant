ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Runtime deps:
# - cronie: cron scheduler
# - openssh-client + sshpass: remote commands & rsync over ssh
# - samba-client: smbclient for SMB share listing/browsing
# - nfs-utils: showmount and NFS mount support
# - rclone: optional cloud copy (Dropbox etc.)
# - Flask + Gunicorn: web UI/API
RUN apk add --no-cache \
    bash curl jq coreutils pigz pv gzip \
    openssh-client sshpass rsync rclone \
    samba-client nfs-utils \
    python3 py3-flask py3-gunicorn cronie

WORKDIR /app

COPY api.py scheduler.py job_runner.py run.sh /app/
COPY www /app/www

# Ensure run.sh is LF and executable
RUN sed -i 's/\r$//' /app/run.sh && chmod 0755 /app/run.sh

# Optional log
RUN touch /var/log/remote_linux_backup.log

CMD ["/app/run.sh"]
