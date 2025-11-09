# syntax=docker/dockerfile:1
#
# Home Assistant add-on wrapper for Tugtainer (Manager-only)
# Ensures persistent storage by linking /tugtainer -> /data
#

FROM docker.io/quenary/tugtainer:latest

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
WORKDIR /app

# Create /tugtainer if missing and link it to /data (persistent HA volume)
RUN mkdir -p /tugtainer && \
    rm -rf /tugtainer/* && \
    ln -sf /data /tugtainer

# Keep the original entrypoint from upstream image (supervisord)
# No CMD or ENTRYPOINT override required