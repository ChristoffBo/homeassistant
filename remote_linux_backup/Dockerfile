FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    openssh-client sshpass rsync pv jq curl tzdata \
    gzip ca-certificates iproute2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

# App
COPY server.py /app/server.py
COPY www /app/www
COPY run.sh /run.sh

RUN chmod +x /run.sh

EXPOSE 8066
CMD ["/bin/bash", "/run.sh"]
