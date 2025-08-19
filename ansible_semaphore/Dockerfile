# Home Assistant add-on: Semaphore UI
# Uses official Semaphore image as base
FROM semaphoreui/semaphore:v2.16.17

USER root

# Install jq and tzdata for option parsing and timezone
RUN apk add --no-cache jq tzdata

# Copy wrapper
COPY ha-wrapper.sh /usr/local/bin/ha-wrapper.sh
RUN chmod +x /usr/local/bin/ha-wrapper.sh

EXPOSE 3000

ENTRYPOINT ["/usr/local/bin/ha-wrapper.sh"]