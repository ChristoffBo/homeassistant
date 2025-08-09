# Remote Linux Backup – Debian base
FROM ghcr.io/hassio-addons/debian-base:7.8.3

# Packages:
# - backup tools: rsync, pigz, pv, rclone
# - ssh: openssh-client, sshpass
# - NAS: smbclient, cifs-utils, nfs-common, rpcbind
# - python web: python3, python3-flask, python3-gunicorn, gunicorn
# - cron + pkill: cron, psmisc
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
      bash curl jq coreutils pigz pv gzip \
      openssh-client sshpass rsync rclone \
      smbclient cifs-utils nfs-common rpcbind \
      python3 python3-flask python3-gunicorn gunicorn \
      cron psmisc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# App
WORKDIR /app
COPY api.py scheduler.py job_runner.py run.sh /app/
COPY www /app/www

# Ensure LF endings + exec
RUN sed -i 's/\r$//' /app/run.sh && chmod 0755 /app/run.sh

# Optional log file path used by cron jobs
RUN touch /var/log/remote_linux_backup.log

# Environment (optional but good defaults)
ENV PYTHONUNBUFFERED=1 \
    FLASK_ENV=production

# Entrypoint
CMD ["/app/run.sh"]
