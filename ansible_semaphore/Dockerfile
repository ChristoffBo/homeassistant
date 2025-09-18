# Home Assistant add-on using official Semaphore image
FROM semaphoreui/semaphore:latest

# Set working dir for mounted /share
WORKDIR /share/ansible_semaphore

# Copy wrapper
COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

CMD ["/usr/local/bin/run.sh"]