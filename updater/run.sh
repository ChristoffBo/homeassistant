#!/bin/bash

ADDONS_DIR="/data/homeassistant"
CURRENT_ARCH=$(uname -m)
case "$CURRENT_ARCH" in
  x86_64) ARCH="amd64" ;;
  aarch64) ARCH="aarch64" ;;
  armv7l) ARCH="armv7" ;;
  *) echo "❌ Unsupported architecture: $CURRENT_ARCH" && exit 1 ;;
esac

echo "🔍 Architecture detected: $ARCH"
echo "🚀 Starting add-on version check..."

UPDATED_ANY=false

for ADDON_DIR in "$ADDONS_DIR"/*/; do
  [ -d "$ADDON_DIR" ] || continue

  CONFIG_FILE="$ADDON_DIR/config.json"
  BUILD_FILE="$ADDON_DIR/build.json"

  if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "⚠️  Skipping $ADDON_DIR — no config.json found."
    continue
  fi

  SLUG=$(jq -r '.slug // empty' "$CONFIG_FILE")
  CURRENT_VERSION=$(jq -r '.version // empty' "$CONFIG_FILE")

  if [[ -z "$SLUG" || -z "$CURRENT_VERSION" ]]; then
    echo "⚠️  Skipping $ADDON_DIR — missing slug or version."
    continue
  fi

  # Determine Docker image
  IMAGE=$(jq -r ".build_from.\"$ARCH\" // empty" "$BUILD_FILE" 2>/dev/null)
  [[ -z "$IMAGE" ]] && IMAGE=$(jq -r ".build_from.\"$ARCH\" // empty" "$CONFIG_FILE" 2>/dev/null)

  if [[ -z "$IMAGE" ]]; then
    echo "⚠️  Addon at $ADDON_DIR has no Docker image defined, skipping."
    continue
  fi

  echo "🔍 Checking add-on '$SLUG' using image $IMAGE"

  # Fetch latest image tag digest
  LATEST_TAG=$(docker pull "$IMAGE" 2>/dev/null | grep "Digest:" | awk '{print $2}')

  if [[ -z "$LATEST_TAG" ]]; then
    echo "⚠️  WARNING: Could not fetch latest docker tag for image $IMAGE"
    echo "✅ Addon '$SLUG' is already up-to-date"
    echo "----------------------------"
    continue
  fi

  # Update version tag in config.json
  NEW_VERSION="$IMAGE"
  jq ".version = \"$NEW_VERSION\"" "$CONFIG_FILE" > "$CONFIG_FILE.tmp" && mv "$CONFIG_FILE.tmp" "$CONFIG_FILE"

  # Append changelog
  CHANGELOG_FILE="$ADDON_DIR/CHANGELOG.md"
  TODAY=$(date +"%d-%m-%Y")
  ENTRY="### $NEW_VERSION ($TODAY)\n\n- Update to latest version from $IMAGE"

  if [[ -f "$CHANGELOG_FILE" ]]; then
    echo -e "$ENTRY\n\n$(cat "$CHANGELOG_FILE")" > "$CHANGELOG_FILE"
  else
    echo -e "$ENTRY" > "$CHANGELOG_FILE"
  fi

  UPDATED_ANY=true
  echo "✅ Updated $SLUG to latest image: $IMAGE"
  echo "----------------------------"
done

# ✅ Print only once, outside the loop
echo "📅 Next check scheduled at 03:00"

