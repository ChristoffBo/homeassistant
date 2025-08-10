# Home Assistant add-on: Remote Linux Backup (RLB)
FROM debian:bookworm-slim

ENV PYTHONUNBUFFERED=1     PIP_DISABLE_PIP_VERSION_CHECK=1     PATH="/opt/venv/bin:$PATH"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends     python3 python3-venv openssh-client sshpass rsync pv jq curl tzdata     smbclient cifs-utils nfs-common iproute2 procps ca-certificates     && rm -rf /var/lib/apt/lists/*

# Python venv
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir flask

WORKDIR /app
COPY server.py /app/server.py
COPY run.sh /app/run.sh
COPY www /app/www

EXPOSE 8066
ENTRYPOINT ["/app/run.sh"]
