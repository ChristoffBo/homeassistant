# ===== Remote Linux Backup (Debian-base) =====
# Works with: https://github.com/hassio-addons/addon-debian-base
ARG BUILD_FROM=ghcr.io/hassio-addons/debian-base:7.8.3
FROM ${BUILD_FROM}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# Core tools:
# - ssh/sshpass/rsync/rclone/pigz/pv for backup flows
# - cifs-utils/smbclient/nfs-common/rpcbind for NAS mounts
# - curl/jq/coreutils for helpers
# - python3 + gunicorn + flask (from Debian packages)
# - psmisc (pkill), cron
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
      bash curl jq coreutils pigz pv gzip \
      openssh-client sshpass rsync rclone \
      smbclient cifs-utils nfs-common rpcbind \
      python3 python3-flask python3-gunicorn gunicorn \
      cron psmisc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY api.py scheduler.py job_runner.py run.sh /app/
COPY www /app/www

# Ensure run.sh is executable and LF
RUN sed -i 's/\r$//' /app/run.sh && chmod 0755 /app/run.sh

# Optional log for cron
RUN touch /var/log/remote_linux_backup.log

CMD ["/app/run.sh"]
