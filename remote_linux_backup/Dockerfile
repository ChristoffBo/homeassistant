ARG BUILD_FROM=ghcr.io/hassio-addons/base:14.3.2
FROM $BUILD_FROM

# Install required packages
RUN apk add --no-cache \
    python3 py3-pip \
    openssh-client rsync \
    curl bash jq \
    pigz gzip tar \
    rclone coreutils util-linux \
    zfs \
    tzdata \
    dropbear \
    samba-client \
    && pip3 install --no-cache-dir --upgrade pip

# Copy add-on files
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY run.sh /run.sh
COPY api.py /app/api.py
COPY job_runner.py /app/job_runner.py
COPY scheduler.py /app/scheduler.py
COPY index.html /app/index.html
COPY style.css /app/style.css

# Ensure scripts are executable
RUN chmod a+x /run.sh /app/*.py

# Entrypoint
CMD [ "/run.sh" ]
