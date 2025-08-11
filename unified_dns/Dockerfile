ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm
FROM ${BUILD_FROM}

# Environment
ENV LANG C.UTF-8

# Install dependencies
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

# Install Python packages
RUN pip3 install --no-cache-dir flask flask_cors

# Copy application files
COPY app/ /app/

# Ensure scripts are executable
RUN chmod +x /app/*.sh || true

# Expose port (change if needed)
EXPOSE 8066

# Start script
CMD [ "python3", "/app/server.py" ]