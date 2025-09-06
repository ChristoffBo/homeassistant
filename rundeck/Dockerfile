# Use official Rundeck image
FROM rundeck/rundeck:latest

# Ensure Debian-based add-on compatibility with HA
RUN apt-get update && apt-get upgrade -y || true \
 && rm -rf /var/lib/apt/lists/*

# Home Assistant add-on runs via s6-overlay
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
