FROM debian:bookworm

ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends     python3 python3-pip python3-venv gunicorn     openssh-client sshpass rsync gzip tar coreutils util-linux fdisk     rclone cifs-utils nfs-common curl jq procps ca-certificates cron     && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app /app
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY www /app/www
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8066
CMD ["/run.sh"]