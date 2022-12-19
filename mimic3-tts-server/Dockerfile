ARG BUILD_FROM
FROM ${BUILD_FROM}
ARG BUILD_ARCH

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN \
    mycroft-mimic3-tts="0.2.4" \
    \
    && ARCH="${BUILD_ARCH}" \
    && if [ "${BUILD_ARCH}" = "aarch64" ]; then ARCH="arm64"; fi \
    && if [ "${BUILD_ARCH}" = "armv7" ]; then ARCH="armhf"; fi \
    && if [ "${BUILD_ARCH}" = "amd64" ]; then ARCH="amd64"; fi \
    \
    && curl -J -L -o /tmp/mycroft-mimic3-tts.deb \
        "https://github.com/MycroftAI/mimic3/releases/download/release%2Fv0.2.4/mycroft-mimic3-tts_${mycroft-mimic3-tts}_${ARCH}.deb" \
    \
    apt-get update \
    && apt-get upgrade -y \
    && apt-get install nginx -y \
    && apt-get install curl -y \
    && apt-get install -y libespeak-ng1 python3 python3-pip python3-venv git \
    && apt-get install libatomic1 libgomp1 libatlas-base-dev \
    \   
    && dpkg -i /tmp/mycroft-mimic3-tts.deb \
    && apt-get install -f \
    && rm /tmp/mycroft-mimic3-tts.deb
    
    
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
