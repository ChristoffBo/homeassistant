# syntax=docker/dockerfile:1
# Rundeck Home Assistant add-on — wraps the official Rundeck image (amd64 only).
FROM rundeck/rundeck:SNAPSHOT
# or pin a fixed version instead:
# FROM rundeck/rundeck:5.15.0-20250902

# Install jq to read /data/options.json
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends jq \
 && rm -rf /var/lib/apt/lists/*
USER rundeck

# Launcher that reads HA options then execs the official entrypoint
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
