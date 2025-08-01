ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

# Install Python (no pip - we'll use venv)
RUN apk add --no-cache python3

# Create virtual environment
RUN python3 -m venv /venv && \
    /venv/bin/pip install --upgrade pip

WORKDIR /app

# Install requirements in venv
COPY requirements.txt .
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app /app
COPY run.sh /

# Set permissions
RUN chmod a+x /run.sh && \
    chown -R root:root /app && \
    chmod -R 755 /app

# s6-overlay entrypoint
ENTRYPOINT ["/init"]