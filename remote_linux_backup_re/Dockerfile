# ===== Remote Linux Backup (Debian-base) =====
# Works with: https://github.com/hassio-addons/addon-debian-base
ARG BUILD_FROM=ghcr.io/hassio-addons/debian-base:7.8.3
FROM ${BUILD_FROM}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Core tools:
# - ssh/sshpass/rsync/rclone/pigz/pv for backup flows
# - cifs-utils/smbclient/nfs-common/rpcbind for NAS mounts
# - curl/jq/coreutils for helpers
# - python3 + gunicorn + flask (from Debian packages)
# - psmisc (for pkill used by scheduler)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      bash curl jq coreutils pigz pv gzip \
      openssh-client sshpass rsync rclone \
      smbclient cifs-utils nfs-common rpcbind \
      python3 python3-pip python3-gunicorn \
      gunicorn cron psmisc && \
    python3 -m pip install --no-cache-dir --break-system-packages flask && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# App
WORKDIR /app

# Copy application files
COPY api.py scheduler.py job_runner.py run.sh /app/
COPY www /app/www

# Ensure run.sh is executable and has LF endings
RUN sed -i 's/\r$//' /app/run.sh && chmod 0755 /app/run.sh

# Persist log for cron (optional)
RUN touch /var/log/remote_linux_backup.log

# Entrypoint
CMD ["/app/run.sh"]
