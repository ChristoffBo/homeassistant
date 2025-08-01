ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

# Set up Python environment
RUN apk add --no-cache python3 py3-pip && \
    python3 -m pip install --upgrade pip

WORKDIR /app

# Copy application files
COPY app /app
COPY run.sh /

# Install requirements directly (no venv needed for Home Assistant add-ons)
RUN if [ -f /app/requirements.txt ]; then pip install --no-cache-dir -r /app/requirements.txt; fi

# Set proper permissions
RUN chmod a+x /run.sh

# Use s6-overlay's init system
ENTRYPOINT ["/init"]
CMD ["/run.sh"]