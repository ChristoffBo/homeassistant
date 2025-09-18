FROM semaphoreui/semaphore:latest
USER root
RUN apt-get update && apt-get install -y jq && rm -rf /var/lib/apt/lists/*
COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh
ENTRYPOINT ["/usr/local/bin/run.sh"]