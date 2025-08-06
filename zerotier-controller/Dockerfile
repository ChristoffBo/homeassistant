ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install base packages and tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        gnupg \
        ca-certificates \
        python3 \
        python3-pip \
        jq \
        bash

# Add ZeroTier official APT repo
RUN curl -s https://download.zerotier.com/contact%40zerotier.com.gpg | gpg --dearmor -o /usr/share/keyrings/zerotier-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/zerotier-archive-keyring.gpg] https://download.zerotier.com/debian/bookworm bookworm main" > /etc/apt/sources.list.d/zerotier.list

# Install zerotier-one
RUN apt-get update && \
    apt-get install -y --no-install-recommends zerotier-one && \
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

EXPOSE 9993 8080

CMD [ "/run.sh" ]