ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache \
    bash \
    curl \
    git \
    jq

COPY rootfs /

ENTRYPOINT [ "/init" ]
CMD []
