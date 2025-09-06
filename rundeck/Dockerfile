# syntax=docker/dockerfile:1
# Rundeck Home Assistant add-on — wraps the official Rundeck image (amd64 only).
FROM rundeck/rundeck:SNAPSHOT
# or pin: FROM rundeck/rundeck:5.15.0-20250902

# Use root to install jq and to read /data/options.json at runtime
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends jq \
 && rm -rf /var/lib/apt/lists/*

# Add launcher with correct permissions
COPY --chmod=0755 run.sh /usr/local/bin/ha-run.sh

# Ensure our launcher is the process PID 1; clear base CMD by overriding it
ENTRYPOINT ["/usr/local/bin/ha-run.sh"]
CMD []
