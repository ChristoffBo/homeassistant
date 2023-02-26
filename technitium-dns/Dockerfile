ARG BUILD_FROM
FROM ${BUILD_FROM}
ARG BUILD_ARCH

RUN apt update; apt install curl -y; \
curl https://packages.microsoft.com/config/debian/11/packages-microsoft-prod.deb --output packages-microsoft-prod.deb; \
dpkg -i packages-microsoft-prod.deb; \
rm packages-microsoft-prod.deb

RUN apt update; apt install libmsquic -y; apt clean -y;

COPY run.sh /
RUN chmod a+x /run.sh
ENTRYPOINT [ "/run.sh" ]



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
