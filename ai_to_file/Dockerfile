ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

WORKDIR /app

# Install Python and dependencies
RUN apk add --no-cache python3 py3-pip nginx

# Copy all files
COPY app /app
COPY run.sh /
COPY requirements.txt /app/

# Install Python packages
RUN pip install --break-system-packages --no-cache-dir -r /app/requirements.txt

# Set permissions
RUN chmod a+x /run.sh

# Start via s6-overlay
ENTRYPOINT ["/init"]
CMD ["/run.sh"]