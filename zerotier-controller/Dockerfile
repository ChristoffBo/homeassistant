ARG BUILD_FROM
FROM ${BUILD_FROM}

# Add labels
LABEL maintainer="ChristoffBo"
LABEL org.opencontainers.image.source="https://github.com/ChristoffBo/homeassistant"

# Set environment variables
ENV LANG C.UTF-8

# Install dependencies
RUN apt-get update && \
    apt-get install -y curl gnupg iproute2 iptables ca-certificates && \
    curl -s https://install.zerotier.com | bash && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Expose common ZeroTier ports
EXPOSE 9993/udp

# Copy run script and set permissions
COPY run.sh /run.sh
RUN chmod a+x /run.sh

# Use bash as shell
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Run as root
USER root

# Set default command
CMD [ "/run.sh" ]