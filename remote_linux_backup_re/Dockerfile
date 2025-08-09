# ---- Home Assistant Debian base ----
FROM ghcr.io/hassio-addons/debian-base:7.8.3

# ---- System packages ----
# tools: ssh/rsync/rclone/cifs/nfs, pigz/pv, curl/jq, cron, pkill (psmisc)
# python + flask + gunicorn for the API/UI
RUN apt-get update \
 && apt-get upgrade -y || true \
 && apt-get install -y --no-install-recommends \
      bash curl jq coreutils pigz pv gzip \
      openssh-client sshpass rsync rclone \
      smbclient cifs-utils nfs-common rpcbind \
      python3 python3-flask python3-gunicorn gunicorn \
      cron psmisc ca-certificates \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# ---- App files live under /app in the image ----
WORKDIR /app

# copy EVERYTHING from your repo's /app folder (api.py, run.sh, scheduler.py, job_runner.py)
COPY app/ /app/

# copy the web UI
COPY www/ /app/www/

# ensure LF endings and exec bit on run.sh
RUN sed -i 's/\r$//' /app/run.sh && chmod 0755 /app/run.sh

# ---- Entrypoint ----
CMD ["/app/run.sh"]
