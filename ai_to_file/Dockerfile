ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

# Install Python and create virtual environment
RUN apk add --no-cache python3 && \
    python3 -m venv /venv

WORKDIR /app

# Copy application files
COPY app /app
COPY run.sh /

# Install requirements in venv if they exist
RUN if [ -f /app/requirements.txt ]; then \
    /venv/bin/pip install --no-cache-dir -r /app/requirements.txt; \
    fi

# Set executable permissions
RUN chmod a+x /run.sh

# Proper s6-overlay initialization
ENTRYPOINT ["/init"]
CMD ["/run.sh"]