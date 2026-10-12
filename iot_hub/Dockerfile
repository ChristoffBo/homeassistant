# Supervisor 2026.04+ no longer passes BUILD_FROM, so it gets a default here;
# older Supervisors that still pass it (from build.json) behave the same.
ARG BUILD_FROM=cbothma/iot-hub:latest
FROM ${BUILD_FROM}
ARG BUILD_ARCH

# The IOT Hub image already starts the hub (node src/index.js in /app) and
# keeps everything in /data, which the Supervisor persists. Nothing to add
# here except the add-on labels; the image's own command is kept.

ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION

LABEL \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version=${BUILD_VERSION} \
    maintainer="christoffbo (https://github.com/ChristoffBo)" \
    org.opencontainers.image.title="${BUILD_NAME}" \
    org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
    org.opencontainers.image.vendor="Home Assistant Add-ons" \
    org.opencontainers.image.authors="christoffbo (https://github.com/ChristoffBo)" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.url="https://github.com/ChristoffBo" \
    org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.documentation="https://github.com/${BUILD_REPOSITORY}/blob/main/README.md" \
    org.opencontainers.image.created=${BUILD_DATE} \
    org.opencontainers.image.revision=${BUILD_REF} \
    org.opencontainers.image.version=${BUILD_VERSION}
