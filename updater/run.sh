#!/usr/bin/env bash
set -e

echo "Starting Home Assistant Addons Updater with configurable repo..."

CONFIG_PATH=/data/options.json

if [ ! -f "$CONFIG_PATH" ]; then
  echo "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

# Read config values using jq
GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
UPDATE_INTERVAL=$(jq -r '.update_interval_minutes' "$CONFIG_PATH")

REPO_DIR=/data/homeassistant

clone_or_update_repo() {
  if [ ! -d "$REPO_DIR" ]; then
    echo "Cloning repository $GITHUB_REPO..."
    if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
      AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
      git clone "$AUTH_REPO" "$REPO_DIR"
    else
      git clone "$GITHUB_REPO" "$REPO_DIR"
    fi
  else
    echo "Pulling latest changes in $REPO_DIR..."
    cd "$REPO_DIR"
    if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
      git pull
    else
      git pull
    fi
  fi
}

while true; do
  clone_or_update_repo
  echo "Waiting $UPDATE_INTERVAL minutes before next check..."
  sleep "${UPDATE_INTERVAL}m"
done
