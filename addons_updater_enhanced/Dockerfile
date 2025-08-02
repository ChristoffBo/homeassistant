ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

RUN apk add --no-cache \
    bash \
    curl \
    git \
    jq \
    tzdata

RUN mkdir -p \
    /etc/cont-init.d \
    /etc/services.d/addons-updater \
    /usr/bin \
    /var/log

COPY rootfs/usr/bin/addons-updater /usr/bin/
COPY rootfs/etc/cont-init.d/addons-updater /etc/cont-init.d/
COPY rootfs/etc/services.d/addons-updater/run /etc/services.d/addons-updater/

RUN chmod a+x \
    /usr/bin/addons-updater \
    /etc/cont-init.d/addons-updater \
    /etc/services.d/addons-updater/run && \
    touch /var/log/addons-updater.log && \
    chmod 644 /var/log/addons-updater.log

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s \
    CMD pgrep -f addons-updater || exit 1

WORKDIR /data
ENTRYPOINT ["/init"]
CMD []
