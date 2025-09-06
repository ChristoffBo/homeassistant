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

# Add launcher with correct permissions in one layer
COPY --chmod=0755 run.sh /usr/local/bin/ha-run.sh

# Drop back to the rundeck user (uid 1000 in upstream image)
USER rundeck

# Make our launcher the entrypoint so Java doesn't treat it as a class arg
ENTRYPOINT ["/usr/local/bin/ha-run.sh"]
