ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest  
FROM ${BUILD_FROM}  

RUN apk add --no-cache \  
    git \  
    jq \  
    curl  

COPY rootfs/ /  

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
    maintainer="Your Name <your@email.com>" \  
    org.opencontainers.image.title="${BUILD_NAME}" \  
    org.opencontainers.image.description="${BUILD_DESCRIPTION}" \  
    org.opencontainers.image.vendor="Home Assistant Add-ons" \  
    org.opencontainers.image.authors="Your Name <your@email.com>" \  
    org.opencontainers.image.licenses="MIT" \  
    org.opencontainers.image.url="https://github.com/yourusername" \  
    org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \  
    org.opencontainers.image.documentation="https://github.com/${BUILD_REPOSITORY}/blob/main/README.md" \  
    org.opencontainers.image.created=${BUILD_DATE} \  
    org.opencontainers.image.revision=${BUILD_REF} \  
    org.opencontainers.image.version=${BUILD_VERSION}  
