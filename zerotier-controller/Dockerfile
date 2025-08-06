ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm
FROM ${BUILD_FROM}

# Install required packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        zerotier-one \
        python3 \
        python3-pip \
        curl \
        jq \
        bash && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy source files
COPY run.sh /run.sh
COPY app /app
COPY www /www

# Set permissions
RUN chmod +x /run.sh && \
    mkdir -p /var/lib/zerotier-one && \
    chown -R root:root /app /www

# Install Python dependencies
RUN pip3 install flask flask_cors

# Expose controller and UI ports
EXPOSE 9993 8080

# Entrypoint
CMD [ "/run.sh" ]