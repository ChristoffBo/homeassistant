FROM ghcr.io/home-assistant/amd64-base:latest

# Install dependencies
RUN apk add --no-cache nodejs npm git curl

# Install ZeroTier for Alpine Linux
RUN apk add --no-cache zerotier-one

# Install ZeroUI
RUN git clone https://github.com/dec0dOS/zero-ui.git /app/zero-ui && \
    cd /app/zero-ui && \
    npm install && \
    npm run build

# Copy add-on files
COPY run.sh /app/
COPY init.sh /app/
COPY zero-ui-config.yaml /app/zero-ui/config.yaml
COPY www /app/zero-ui/www/

# Set permissions
RUN chmod a+x /app/run.sh /app/init.sh

# Set working directory
WORKDIR /app

# Add required capabilities for ZeroTier
CMD ["/app/run.sh"]