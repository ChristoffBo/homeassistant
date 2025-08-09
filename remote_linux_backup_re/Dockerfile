# Debian base from the HA Community Add-ons project
# https://github.com/hassio-addons/addon-debian-base
FROM ghcr.io/hassio-addons/debian-base:7.8.3

ENV DEBIAN_FRONTEND=noninteractive

# Runtime deps:
# - cron: scheduler
# - openssh-client + sshpass: remote cmds & rsync over ssh
# - smbclient + cifs-utils: list & mount SMB/CIFS shares
# - nfs-common: NFS client + showmount
# - rclone: optional cloud copy (Dropbox etc.)
# - Python3 + Flask + Gunicorn: web UI/API
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash curl jq coreutils pigz pv gzip \
      openssh-client sshpass rsync rclone \
      smbclient cifs-utils nfs-common \
      python3 python3-pip gunicorn cron \
    && pip3 install --no-cache-dir flask \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY api.py scheduler.py job_runner.py run.sh /app/
COPY www /app/www

# Ensure run.sh is LF and executable
RUN sed -i 's/\r$//' /app/run.sh && chmod 0755 /app/run.sh

# Optional log file you can tail inside the container
RUN touch /var/log/remote_linux_backup.log

CMD ["/app/run.sh"]
