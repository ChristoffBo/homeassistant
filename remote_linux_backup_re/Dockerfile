# Debian base from the HA Community Add-ons project
FROM ghcr.io/hassio-addons/debian-base:7.8.3

ENV DEBIAN_FRONTEND=noninteractive

# Runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash curl jq coreutils pigz pv gzip \
      openssh-client sshpass rsync rclone \
      smbclient cifs-utils nfs-common rpcbind \
      python3 python3-flask python3-gunicorn gunicorn cron \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY api.py scheduler.py job_runner.py run.sh /app/
COPY www /app/www

# Ensure LF line endings and executable bit
RUN sed -i 's/\r$//' /app/run.sh && chmod 0755 /app/run.sh

# Optional log file
RUN touch /var/log/remote_linux_backup.log

CMD ["/app/run.sh"]
