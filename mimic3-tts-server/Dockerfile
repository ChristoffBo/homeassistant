
ARG BUILD_FROM=ghcr.io/hassio-addons/debian-base/amd64:6.1.2

FROM $BUILD_FROM

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG BUILD_ARCH=amd64
RUN \
    apt-get update \
    && apt-get upgrade -y \
    && apt-get install curl -y \
    && apt-get install -y libespeak-ng1 python3 python3-pip python3-venv git \
    && apt-get install libatomic1 libgomp1 libatlas-base-dev \
    \   
    && curl -J -L -o /tmp/mycroft-mimic3-tts_0.2.3_amd64.deb \
        "https://github.com/MycroftAI/mimic3/releases/download/release%2Fv0.2.3/mycroft-mimic3-tts_0.2.3_amd64.deb" \
    && dpkg -i /tmp/mycroft-mimic3-tts_0.2.3_amd64.deb \
    && apt-get install -f
   
   
    
COPY run.sh /
RUN chmod a+x /run.sh
CMD [ "./run.sh" ]       


EXPOSE 59125


# Build arguments
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
    maintainer="Christoffbo" \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    org.opencontainers.image.vendor="Home Assistant Community Add-ons" \
    org.opencontainers.image.authors="Franck Nijhof <frenck@addons.community>" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.url="https://addons.community" \
    org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.documentation="https://github.com/${BUILD_REPOSITORY}/blob/main/README.md" \
    org.opencontainers.image.created=${BUILD_DATE} \
    org.opencontainers.image.revision=${BUILD_REF} \
    org.opencontainers.image.version=${BUILD_VERSION}
