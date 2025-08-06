ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install core utilities and Python
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        gnupg \
        ca-certificates \
        python3 \
        python3-pip \
        python3-flask \
        python3-flask-cors \
        jq \
        bash

# Add ZeroTier GPG key and repository
RUN curl -s https://download.zerotier.com/contact%40zerotier.com.gpg | \
    gpg --dearmor -o /usr/share/keyrings/zerotier-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/zerotier-archive-keyring.gpg] https://download.zerotier.com/debian/bookworm bookworm main" > \
    /etc/apt/sources.list.d/zerotier.list

# Install zerotier-one
RUN apt-get update && \
    apt-get install -y --no-install-recommends zerotier-one && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy application files
COPY run.sh /run.sh
COPY app /app
COPY www /www

# Permissions and setup
RUN chmod +x /run.sh && \
    mkdir -p /var/lib/zerotier-one && \
    chown -R root:root /app /www

# Expose required ports
EXPOSE 9993 8080

# Start command
CMD [ "/run.sh" ]