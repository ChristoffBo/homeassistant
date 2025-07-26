# Use the official Home Assistant add-on base image
ARG BUILD_FROM= 2fauth/2fauth:latest
FROM ${BUILD_FROM}

# Set shell options
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install required tools (minimal, since 2FAuth is run via Docker inside the add-on)
RUN apk add --no-cache docker-cli curl

# Copy run script into the container
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Entrypoint
CMD [ "/run.sh" ]