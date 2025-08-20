FROM semaphoreui/semaphore:latest
USER root

# Our wrapper
COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

# For persistence & convenience
WORKDIR /share/ansible_semaphore

# Keep upstream entrypoint; only set the default CMD to our run.sh
CMD ["/bin/sh", "/usr/local/bin/run.sh"]