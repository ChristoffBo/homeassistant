#!/usr/bin/env bash
set -e
echo "[INFO] Starting 2FAuth..."

docker run -d \
  --name=2fauth \
  -e APP_URL="${APP_URL}" \
  -e MAIL_ENCRYPTION="${MAIL_ENCRYPTION}" \
  -e MAIL_FROM_ADDRESS="${MAIL_FROM_ADDRESS}" \
  -e MAIL_FROM_NAME="${MAIL_FROM_NAME}" \
  -e MAIL_HOST="${MAIL_HOST}" \
  -e MAIL_MAILER="${MAIL_MAILER}" \
  -e MAIL_PORT="${MAIL_PORT}" \
  -e PGID="${PGID}" \
  -e PUID="${PUID}" \
  -e TZ="${TZ}" \
  -p 8001:8000 \
  -v /data:/2fauth \
  --privileged \
  --restart unless-stopped \
  2fauth/2fauth:latest