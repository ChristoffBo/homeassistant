ARG BUILD_FROM
ARG BUILD_VERSION
FROM ${BUILD_FROM}

ENV S6_CMD_WAIT_FOR_SERVICES=1 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0 \
    S6_SERVICES_GRACETIME=0
    
 ARG CONFIGLOCATION="/config"

 RUN \
    # Avoid custom-init.d duplications
    for file in $(grep -sril 'Potential tampering with custom' /etc/cont-init.d /etc/services.d /etc/s6-overlay/s6-rc.d); do rm -f $file; done \
    \
    # Create new config folder if needed
    && for file in $(grep -srl "PUID" /etc/cont-init.d /etc/s6-overlay/s6-rc.d); do sed -i "1a mkdir -p $CONFIGLOCATION" $file; done \
    \
    # Allow UID and GID setting
    && for file in $(grep -srl "PUID" /etc/cont-init.d /etc/s6-overlay/s6-rc.d); do sed -i 's/bash/bashio/g' $file && sed -i '1a PUID="$(if bashio::config.has_value "PUID"; then bashio::config "PUID"; else echo "0"; fi)"' $file && sed -i '1a PGID="$(if bashio::config.has_value "PGID"; then bashio::config "PGID"; else echo "0"; fi)"' $file; done \
    \
    # Correct config location
    && for file in $(grep -Esril "/config[ '\"/]|/config\$" /etc /defaults); do sed -Ei "s=(/config)+(/| |$|\"|\')=$CONFIGLOCATION\2=g" $file; done \
    \
    # Avoid chmod /config
    && for file in /etc/services.d/*/* /etc/cont-init.d/* /etc/s6-overlay/s6-rc.d/*/*;do if [ -f $files ] && [[ ! -z $(awk '/chown.*abc:abc.*\\/,/.*\/config( |$)/{print FILENAME}' $file) ]] ; then sed -i "s|/config$|/data|g" $file; fi ;done \
    \
    # Docker mods addition
    && if [ -f /docker-mods ]; then sed -i 's|bash|bashio|g' /docker-mods && sed -i "1a if bashio::config.has_value \"DOCKER_MODS\"; then DOCKER_MODS=\$(bashio::config \"DOCKER_MODS\"); fi" /docker-mods; fi \
    \
    # Replace lsiown if not found
    && if [ ! -f /usr/bin/lsiown ]; then sed -i "s|lsiown|chown|g" /etc/s6-overlay/s6-rc.d/*/run; fi
    
    
    
    
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
    maintainer="alexbelgium (https://github.com/alexbelgium)" \
    org.opencontainers.image.title="${BUILD_NAME}" \
    org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
    org.opencontainers.image.vendor="Home Assistant Add-ons" \
    org.opencontainers.image.authors="alexbelgium (https://github.com/alexbelgium)" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.url="https://github.com/alexbelgium" \
    org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.documentation="https://github.com/${BUILD_REPOSITORY}/blob/main/README.md" \
    org.opencontainers.image.created=${BUILD_DATE} \
    org.opencontainers.image.revision=${BUILD_REF} \
    org.opencontainers.image.version=${BUILD_VERSION}

    