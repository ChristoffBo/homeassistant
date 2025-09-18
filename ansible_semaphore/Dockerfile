FROM semaphoreui/semaphore:latest
USER root

# Install jq on Alpine
RUN apk add --no-cache jq

COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

ENTRYPOINT ["/usr/local/bin/run.sh"]