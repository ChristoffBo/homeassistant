# syntax=docker/dockerfile:1
#
# Home Assistant add-on wrapper for Tugtainer (Manager-only)
#
FROM ghcr.io/quenary/tugtainer:latest

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
WORKDIR /app

# Copy and mark start script
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]