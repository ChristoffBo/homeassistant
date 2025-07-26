ARG BUILD_FROM=2fauth/2fauth:latest
FROM ${BUILD_FROM}

# Use shell that exists
SHELL ["/bin/sh", "-c"]

# Install necessary tools
RUN apk add --no-cache bash docker-cli curl

# Copy your run script
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]