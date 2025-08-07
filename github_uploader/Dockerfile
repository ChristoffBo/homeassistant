ARG BUILD_FROM
FROM debian:bullseye-slim

# Set environment
ENV LANG C.UTF-8

# Install dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    git \
    curl \
    unzip \
    ca-certificates && \
    pip3 install flask requests && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create necessary folders
RUN mkdir -p /app /www /data

# Copy application code
COPY uploader.py /app/uploader.py
COPY frontend /www

# Set permissions
RUN chmod +x /app/uploader.py

# Entrypoint
CMD [ "python3", "/app/uploader.py" ]