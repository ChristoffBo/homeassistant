ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

WORKDIR /app

# Install Python and create virtual environment
RUN apk add --no-cache python3 py3-pip && \
    python3 -m venv /venv && \
    /venv/bin/pip install --no-cache-dir --upgrade pip

# Install requirements
COPY requirements.txt .
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app /app
COPY run.sh /

# Set permissions
RUN chmod a+x /run.sh && \
    chmod -R 755 /app && \
    chown -R root:root /app

ENTRYPOINT ["/init"]