FROM semaphoreui/semaphore:latest

COPY run.sh /usr/local/bin/run.sh

USER root
RUN chmod 0755 /usr/local/bin/run.sh
USER 1001

WORKDIR /config/semaphore

ENTRYPOINT ["/usr/local/bin/run.sh"]