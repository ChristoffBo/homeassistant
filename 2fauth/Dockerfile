ARG BUILD_FROM=ghcr.io/hassio-addons/base:alpine3.19
FROM ${BUILD_FROM}

SHELL ["/bin/sh", "-c"]

# Install required packages
RUN apk add --no-cache bash docker-cli curl

# Copy your run script
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]