#!/usr/bin/env bash
set -e

echo "Starting Home Assistant Addons Updater with configurable repo..."

CONFIG_PATH=/data/options.json

if [ ! -f "$CONFIG_PATH" ]; then
  echo "ERROR: Config file $CONFIG_PATH not found!"
  exit 1
fi

GITHUB_REPO=$(jq -r '.github_repo' "$CONFIG_PATH")
GITHUB_USERNAME=$(jq -r '.github_username' "$CONFIG_PATH")
GITHUB_TOKEN=$(jq -r '.github_token' "$CONFIG_PATH")
UPDATE_INTERVAL=$(jq -r '.update_interval_minutes' "$CONFIG_PATH")

REPO_DIR=/data/homeassistant

clone_or_update_repo() {
  echo "Checking repository: $GITHUB_REPO"
  if [ ! -d "$REPO_DIR" ]; then
    echo "Repository not found locally. Cloning..."
    if [ -n "$GITHUB_USERNAME" ] && [ -n "$GITHUB_TOKEN" ]; then
      AUTH_REPO=$(echo "$GITHUB_REPO" | sed -E "s#https://#https://$GITHUB_USERNAME:$GITHUB_TOKEN@#")
      git clone "$AUTH_REPO" "$REPO_DIR"
      echo "Repository cloned successfully."
    else
      git clone "$GITHUB_REPO" "$REPO_DIR"
      echo "Repository cloned successfully."
    fi
  else
    echo "Repository found. Pulling latest changes..."
    cd "$REPO_DIR"
    # Capture git pull output
    PULL_OUTPUT=$(git pull)

    if echo "$PULL_OUTPUT" | grep -q "Already up to date."; then
      echo "Repository is already up to date."
    else
      echo "Repository updated with changes:"
      echo "$PULL_OUTPUT"
    fi
  fi
}

while true; do
  clone_or_update_repo
  echo "Waiting $UPDATE_INTERVAL minutes before next check..."
  sleep "${UPDATE_INTERVAL}m"
done
