ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install system and Python dependencies
RUN apk add --no-cache \
    git \
    jq \
    bash \
    openssh-client \
    curl \
    python3 \
    py3-pip \
    build-base \
    libffi-dev \
    openssl-dev

# Install Python packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    requests \
    lastversion

# Copy application files
COPY updater.py /updater.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /data
CMD ["/run.sh"]
