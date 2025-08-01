ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

WORKDIR /app

# Install Python and pip
RUN apk add --no-cache python3 py3-pip

# Copy application files
COPY app /app
COPY run.sh /

# Install requirements if they exist
RUN if [ -f /app/requirements.txt ]; then pip install --no-cache-dir -r /app/requirements.txt; fi

# Set executable permissions
RUN chmod a+x /run.sh

# Proper s6-overlay initialization
ENTRYPOINT ["/init"]
CMD ["/run.sh"]