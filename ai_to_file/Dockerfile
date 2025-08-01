
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

# Install Python (no venv needed for this approach)
RUN apk add --no-cache python3

WORKDIR /app

# Copy application files
COPY src /app
COPY run.sh /

# Install requirements if they exist
RUN if [ -f /app/requirements.txt ]; then \
    pip install --break-system-packages --no-cache-dir -r /app/requirements.txt; \
    fi

# Set executable permissions
RUN chmod a+x /run.sh

# Proper s6-overlay initialization
ENTRYPOINT ["/init"]
CMD ["/run.sh"]