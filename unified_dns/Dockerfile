ARG BUILD_FROM=ghcr.io/hassio-addons/debian-base/10.2.3
FROM ${BUILD_FROM}

# Set shell to bash with pipefail for better error handling
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 \
       python3-pip \
       python3-venv \
       python3-dev \
       build-essential \
       curl \
       ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (Flask + CORS support)
RUN pip3 install --no-cache-dir flask flask_cors

# Copy application files
COPY rootfs/ /app/

# Make sure scripts are executable
RUN chmod a+x /app/run.sh

# Expose port (matches config.json listen_port)
EXPOSE 8067

# Entrypoint
CMD ["/app/run.sh"]