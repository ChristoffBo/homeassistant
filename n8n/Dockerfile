ARG BUILD_FROM=ghcr.io/hassio-addons/base:latest
FROM $BUILD_FROM

# Install dependencies
RUN apk add --no-cache nodejs npm python3 make g++

# Install n8n globally
RUN npm install -g n8n

# Expose default n8n port
EXPOSE 5678

# Start n8n
CMD ["n8n"]