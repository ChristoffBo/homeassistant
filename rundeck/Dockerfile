# syntax=docker/dockerfile:1
# Rundeck Home Assistant add-on — wraps the official Rundeck image.

# Give BUILD_FROM a real default so local builds work even if the builder
# doesn’t inject it. Only amd64 is supported by upstream images.
ARG BUILD_FROM=rundeck/rundeck:SNAPSHOT
FROM ${BUILD_FROM}

# Install jq to read /data/options.json (run as root, then drop back)
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends jq \
 && rm -rf /var/lib/apt/lists/*
USER rundeck

# Add the launcher that reads HA options and execs the official entrypoint
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Start
CMD ["/run.sh"]
