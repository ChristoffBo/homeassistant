ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

# Install Python and create virtual environment
RUN apk add --no-cache python3 py3-pip && \
    python3 -m venv /venv && \
    /venv/bin/pip install --no-cache-dir --upgrade pip

WORKDIR /app

# Install requirements
COPY app/requirements.txt .
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app /app
COPY run.sh /

# Set permissions (critical for s6)
RUN chmod a+x /run.sh && \
    chmod -R a+rX /app && \
    chown -R root:root /app

# s6-overlay entrypoint (MUST be /init)
ENTRYPOINT ["/init"]