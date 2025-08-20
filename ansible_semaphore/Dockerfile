FROM semaphoreui/semaphore:latest
USER root

COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

WORKDIR /share/ansible_semaphore

CMD ["/bin/sh", "/usr/local/bin/run.sh"]