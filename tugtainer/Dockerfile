# syntax=docker/dockerfile:1
#
# Home Assistant add-on wrapper for Tugtainer (Manager-only)
# Uses the official Docker Hub image as the base.
#

FROM quenary/tugtainer:latest

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
WORKDIR /app

# Copy the startup script
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Use the wrapper as entrypoint
CMD ["/run.sh"]