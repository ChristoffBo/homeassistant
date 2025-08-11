ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm
FROM ${BUILD_FROM}

# Set environment variables
ENV LANG C.UTF-8

# Install required packages
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

# Install Python dependencies
RUN pip3 install --no-cache-dir flask flask_cors

# Copy application files
COPY app/ /app/

# Make sure scripts are executable
RUN chmod +x /app/run.sh

# Expose port (adjust if needed)
EXPOSE 8099

# Start the app
CMD [ "/app/run.sh" ]