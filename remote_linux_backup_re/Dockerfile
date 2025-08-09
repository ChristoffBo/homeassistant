# Remote Linux Backup – Debian base
FROM ghcr.io/hassio-addons/debian-base:7.8.3

# Tools:
# - backup: rsync, pigz, pv, rclone
# - ssh: openssh-client, sshpass
# - NAS: smbclient, cifs-utils, nfs-common, rpcbind
# - python web: python3, python3-flask, python3-gunicorn, gunicorn
# - cron + pkill: cron, psmisc
# - certs: ca-certificates
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
      bash curl jq coreutils pigz pv gzip \
      openssh-client sshpass rsync rclone \
      smbclient cifs-utils nfs-common rpcbind \
      python3 python3-flask python3-gunicorn gunicorn \
      cron psmisc ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# App
WORKDIR /app
COPY api.py scheduler.py job_runner.py run.sh /app/
COPY www /app/www

# Ensure LF endings + exec on run.sh; create common dirs; prepare log
RUN sed -i 's/\r$//' /app/run.sh && chmod 0755 /app/run.sh && \
    mkdir -p /backup /mnt/nas /mnt/mounts && \
    touch /var/log/remote_linux_backup.log

# Runtime env
ENV PYTHONUNBUFFERED=1 \
    FLASK_ENV=production

# Entrypoint
CMD ["/app/run.sh"]
