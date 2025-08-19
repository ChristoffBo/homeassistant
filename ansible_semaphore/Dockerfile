# Home Assistant add-on Dockerfile for Semaphore
ARG BUILD_FROM
FROM $BUILD_FROM

USER root

# Copy startup script with permissions
COPY --chmod=0755 run.sh /usr/local/bin/run.sh

# Make sure jq is installed (needed by HA add-ons)
RUN apk add --no-cache bash jq

WORKDIR /config/ansible_semaphore

ENTRYPOINT ["/usr/local/bin/run.sh"]