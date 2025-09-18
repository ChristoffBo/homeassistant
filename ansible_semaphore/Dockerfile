FROM semaphoreui/semaphore:latest
USER root

COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

# Override ENTRYPOINT so upstream setup never runs
ENTRYPOINT ["/usr/local/bin/run.sh"]