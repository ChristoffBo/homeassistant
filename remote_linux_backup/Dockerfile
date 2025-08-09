FROM debian:bookworm

ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# system packages (no apt gunicorn; we'll use the venv one)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    openssh-client sshpass rsync gzip tar coreutils util-linux fdisk \
    rclone cifs-utils nfs-common curl jq procps ca-certificates cron \
    && rm -rf /var/lib/apt/lists/*

# create app dir
WORKDIR /app
COPY app /app

# create and use virtualenv for Python deps (avoids PEP 668)
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt
ENV PATH="/opt/venv/bin:${PATH}"

# web assets & entrypoint
COPY www /app/www
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8066
CMD ["/run.sh"]