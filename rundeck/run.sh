#!/bin/bash
set -euo pipefail

OPTIONS_FILE="/data/options.json"
UI_PORT=4440
EXTERNAL_URL=""
EXTRA_JAVA_OPTS=""

if [ -f "$OPTIONS_FILE" ]; then
  UI_PORT="$(jq -r '.ui_port // 4440' "$OPTIONS_FILE")"
  EXTERNAL_URL="$(jq -r '.external_url // ""' "$OPTIONS_FILE")"
  EXTRA_JAVA_OPTS="$(jq -r '.extra_java_opts // ""' "$OPTIONS_FILE")"
fi

# Persistent data (HA add-on /data is persistent)
export RDECK_BASE="/data/rundeck"
mkdir -p "${RDECK_BASE}"
# Ownership fix; ignore if not allowed
chown -R 1000:1000 "${RDECK_BASE}" || true

# Ingress / proxy friendliness
export RUNDECK_SERVER_FORWARDED="true"
if [ -n "${EXTERNAL_URL}" ] && [ "${EXTERNAL_URL}" != "null" ]; then
  export RUNDECK_GRAILS_URL="${EXTERNAL_URL}"
fi

JAVA_OPTS="-Dserver.port=${UI_PORT}"
if [ -n "${EXTRA_JAVA_OPTS}" ] && [ "${EXTRA_JAVA_OPTS}" != "null" ]; then
  JAVA_OPTS="${JAVA_OPTS} ${EXTRA_JAVA_OPTS}"
fi
export JAVA_OPTS

echo "[INFO] RDECK_BASE=${RDECK_BASE}"
echo "[INFO] server.port=${UI_PORT}"
[ -n "${RUNDECK_GRAILS_URL:-}" ] && echo "[INFO] RUNDECK_GRAILS_URL=${RUNDECK_GRAILS_URL}"
echo "[INFO] RUNDECK_SERVER_FORWARDED=${RUNDECK_SERVER_FORWARDED}"

# Hand off to the image's original entrypoint if present; else start the WAR directly
for p in \
  /docker-entrypoint.sh \
  /home/rundeck/docker-entrypoint.sh \
  /home/rundeck/docker-lib/entry.sh \
  /home/rundeck/bin/docker-lib/entry.sh \
  /entrypoint.sh \
  /entry.sh
do
  if [ -x "$p" ]; then
    exec "$p"
  fi
done

echo "[WARN] Could not find Rundeck entrypoint; starting WAR directly."
exec java $JAVA_OPTS -jar /home/rundeck/rundeck.war
