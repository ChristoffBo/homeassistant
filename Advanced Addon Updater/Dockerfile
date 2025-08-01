ARG BUILD_FROM=python:3.9-alpine
FROM ${BUILD_FROM}

# Install system dependencies
RUN apk add --no-cache \
    git \
    jq \
    bash \
    openssh-client \
    curl \
    build-base \
    libffi-dev \
    openssl-dev

# Install Python dependencies
RUN pip install --no-cache-dir \
    requests \
    lastversion

# Copy application files
COPY updater.py /updater.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /data
CMD [ "/run.sh" ]
