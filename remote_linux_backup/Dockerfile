FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
  python3 python3-pip python3-venv python3-dev build-essential gcc \
  openssh-client sshpass rsync pv jq curl tzdata smbclient cifs-utils nfs-common gzip ca-certificates iproute2 \
  libffi-dev libssl-dev pkg-config \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies
COPY requirements.txt /app/requirements.txt

# Create isolated venv (PEP 668 compliant) and install deps
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
 && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

ENV PATH="/opt/venv/bin:$PATH"
ENV TZ=Africa/Johannesburg

# App
COPY . /app

# Runtime script
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8066
CMD ["/bin/bash", "/run.sh"]
