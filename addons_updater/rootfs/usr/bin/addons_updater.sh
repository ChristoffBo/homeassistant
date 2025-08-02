#!/bin/sh


set -e




# ------------------------------


# Addons Updater Enhanced


# Automatically update addons with notifications support


# ------------------------------





# Colors for logging (avoid purple)


# ===== COLOR DEFINITIONS =====

RED='\033[0;31m'

GREEN='\033[0;32m'

YELLOW='\033[1;33m'


CYAN='\033[0;36m'

BLUE='\033[0;34m'


NC='\033[0m' # No Color





# Dry run and live colors


DRYRUN_COLOR="${YELLOW}"


LIVE_COLOR="${GREEN}"





# Logging functions


log_info() {


  printf "${LIVE_COLOR}[INFO]${NC} %s\n" "$1"


}


log_warn() {


  printf "${RED}[WARN]${NC} %s\n" "$1"


}


log_dryrun() {


  printf "${DRYRUN_COLOR}[DRYRUN]${NC} %s\n" "$1"


}





# Version comparison (returns true if $1 > $2)


ver_gt() {


  [ "$(printf '%s\n' "$1" "$2" | sort -V | head -n1)" != "$1" ]


}





# Read config options


CONFIG_FILE="/data/options.json"


if [ ! -f "$CONFIG_FILE" ]; then


  log_warn "options.json not found!"


  exit 1


fi





# Load JSON config


GIT_USER=$(jq -r '.gituser // empty' "$CONFIG_FILE")


GIT_MAIL=$(jq -r '.gitmail // empty' "$CONFIG_FILE")


GIT_API_TOKEN=$(jq -r '.gitapi // empty' "$CONFIG_FILE")


REPOSITORY=$(jq -r '.repository // empty' "$CONFIG_FILE")


VERBOSE=$(jq -r '.verbose // false' "$CONFIG_FILE")


DRY_RUN=$(jq -r '.dry_run // true' "$CONFIG_FILE")


ENABLE_NOTIFICATIONS=$(jq -r '.enable_notifications // false' "$CONFIG_FILE")


GOTIFY_URL=$(jq -r '.gotify_url // empty' "$CONFIG_FILE")


GOTIFY_TOKEN=$(jq -r '.gotify_token // empty' "$CONFIG_FILE")


USE_GITEA=$(jq -r '.use_gitea // false' "$CONFIG_FILE")


GITEA_API_URL=$(jq -r '.gitea_api_url // empty' "$CONFIG_FILE")


GITEA_TOKEN=$(jq -r '.gitea_token // empty' "$CONFIG_FILE")





REPO_PATH="/data/$(basename "$REPOSITORY")"





# Print header info


printf "\n-----------------------------------------------------------\n"


printf " Add-on: Addons Updater Enhanced\n Automatically update addons with notifications support\n"


printf "-----------------------------------------------------------\n"


printf " Add-on version: 10.1.1\n"


printf " System: Home Assistant OS (amd64 / qemux86-64)\n"


printf " Repository: %s\n" "$REPOSITORY"


printf " Dry run mode: %s\n" "$( [ "$DRY_RUN" = "true" ] && echo "Enabled" || echo "Disabled" )"


printf " Notifications: %s\n" "$( [ "$ENABLE_NOTIFICATIONS" = "true" ] && echo "Enabled" || echo "Disabled" )"


printf "-----------------------------------------------------------\n\n"





# Setup Git config


export HOME=/tmp


git config --global user.name "$GIT_USER"


git config --global user.email "$GIT_MAIL"





if [ ! -d "$REPO_PATH/.git" ]; then


  log_info "Cloning repository $REPOSITORY..."


  if ! git clone --depth=1 "https://$GIT_API_TOKEN@github.com/$REPOSITORY.git" "$REPO_PATH"; then


    log_warn "Failed to clone repository!"


    exit 1


  fi


CYAN='\033[0;36m'


GRAY='\033[1;30m'


NC='\033[0m'





# ===== START TIMER =====


START_TIME=$(date +%s)





# ===== ENV SETUP =====


TZ=${TZ:-"Africa/Johannesburg"}


export TZ


cd /data || exit 1





# ===== LOGGING UTILS =====


log_info()   { echo "${BLUE}[INFO]${NC} $1"; }


log_warn()   { echo "${YELLOW}[WARN]${NC} $1"; }


log_error()  { echo "${RED}[ERROR]${NC} $1"; }


log_update() { echo "${GREEN}[UPDATE]${NC} $1"; }


log_dryrun() { echo "${CYAN}[DRYRUN]${NC} $1"; }





# ===== LOAD CONFIGURATION =====


OPTIONS_JSON=/data/options.json


REPO=$(jq -r '.repo // empty' "$OPTIONS_JSON")


BRANCH=$(jq -r '.branch // "main"' "$OPTIONS_JSON")


GOTIFY_URL=$(jq -r '.gotify_url // empty' "$OPTIONS_JSON")


GOTIFY_TOKEN=$(jq -r '.gotify_token // empty' "$OPTIONS_JSON")


DRY_RUN=$(jq -r '.dry_run // true' "$OPTIONS_JSON")





# ===== CLONE OR PULL REPO =====


if [ ! -d repo ]; then


  git clone --depth=1 --branch "$BRANCH" "$REPO" repo

else


  log_info "Repository exists, updating..."


  cd "$REPO_PATH"


  git fetch origin main


  git reset --hard origin/main


  cd repo || exit 1


  git pull


  cd ..

fi


cd repo || exit 1




CHANGELOG=""


UPDATES_OCCURRED=false





# Update version in JSON file helper


update_json_version() {


  local addon_dir=$1


  local version=$2


  local file=$3


git config user.name "AddonUpdater"


git config user.email "addon-updater@local"




  local json_file="$REPO_PATH/$addon_dir/$file"


  if [ -f "$json_file" ]; then


    jq --arg v "$version" '.version=$v' "$json_file" > "${json_file}.tmp" && mv "${json_file}.tmp" "$json_file"


    log_info "$addon_dir: $file version updated to $version."


    CHANGELOG="${CHANGELOG}\n$addon_dir: Version updated to $version"


  else


    log_warn "$addon_dir: $file not found, skipping update."


  fi


}


[ "$DRY_RUN" = true ] && log_dryrun "===== ADDON UPDATER STARTED (Dry Run) =====" || log_update "===== ADDON UPDATER STARTED (Live Mode) ====="




# Get current addon version by checking config.json, build.json, updater.json (priority order)


get_current_version() {


  local addon_dir=$1


  for file in config.json build.json updater.json; do


    local jf="$REPO_PATH/$addon_dir/$file"


    if [ -f "$jf" ]; then


      local ver


      ver=$(jq -r '.version // empty' "$jf")


      if [ -n "$ver" ] && [ "$ver" != "null" ]; then


        echo "$ver"


        return


      fi


    fi


  done


  echo "unknown"


}


# ===== FUNCTIONS =====


get_latest_tag() {


  local image=$1


  local registry="docker"


  case "$image" in


    lscr.io/*) registry="linuxserver";;


  esac




# Fetch latest version depending on source (GitHub or Gitea) or DockerHub fallback


get_latest_version() {


  local addon=$1





  if [ "$USE_GITEA" = "true" ]; then


    # Gitea API version fetching


    # Example call: curl -s -H "Authorization: token $GITEA_TOKEN" "$GITEA_API_URL/repos/youruser/$addon/releases/latest"


    latest=$(curl -s -H "Authorization: token $GITEA_TOKEN" "$GITEA_API_URL/repos/$GIT_USER/$addon/releases/latest" | jq -r '.tag_name // empty')


  if [ "$registry" = "linuxserver" ]; then


    local repo_name=${image#lscr.io/}


    tags=$(curl -fsSL "https://hub.docker.com/v2/repositories/linuxserver/${repo_name}/tags?page_size=100" | jq -r '.results[].name') || return 1

  else


    # GitHub API version fetching


    latest=$(curl -s -H "Authorization: token $GIT_API_TOKEN" "https://api.github.com/repos/$GIT_USER/$addon/releases/latest" | jq -r '.tag_name // empty')


  fi





  # If no tag_name found, fallback to DockerHub or default 'latest'


  if [ -z "$latest" ]; then


    # Here you could implement DockerHub tag fetch fallback if needed


    latest="latest"


    tags=$(curl -fsSL "https://hub.docker.com/v2/repositories/${image}/tags?page_size=100" | jq -r '.results[].name') || return 1

  fi




  # Strip any leading 'v' to standardize version format


  latest="${latest#v}"


  echo "$latest"


  echo "$tags" | grep -Ev 'latest|rc|dev|test' | sort -Vr | head -n 1

}




# Iterate addons excluding .git folder


for addon_dir in $(find "$REPO_PATH" -mindepth 1 -maxdepth 1 -type d ! -name ".git" | xargs -n1 basename); do





  current_version=$(get_current_version "$addon_dir")


  latest_version=$(get_latest_version "$addon_dir")





  if [ "$latest_version" = "latest" ] || [ -z "$latest_version" ]; then


    latest_version="$current_version"


  fi


send_gotify() {


  local title=$1


  local message=$2


  local priority=${3:-5}


  [ -z "$GOTIFY_URL" ] && return


  curl -s -X POST "$GOTIFY_URL/message?token=$GOTIFY_TOKEN" \


    -F "title=$title" \


    -F "message=$message" \


    -F "priority=$priority" >/dev/null || log_warn "Failed to send Gotify notification."


}




  if ver_gt "$latest_version" "$current_version"; then


    log_info "$addon_dir: Update available: $current_version -> $latest_version"


    if [ "$DRY_RUN" = "true" ]; then


      log_dryrun "$addon_dir: Update simulated from $current_version to $latest_version"


# ===== MAIN LOOP =====


NOTES=""


for addon in */config.json; do


  dir=$(dirname "$addon")


  [ "$dir" = ".git" ] && continue





  name=$(jq -r '.name // empty' "$addon")


  image=$(jq -r '.image // empty' "$addon")


  [ -z "$image" ] && image=$(jq -r '.build.image // empty' "$dir/build.json")


  [ -z "$image" ] && continue





  latest=$(get_latest_tag "$image")


  [ -z "$latest" ] && log_warn "$dir: Failed to get latest tag" && continue





  current=$(jq -r '.version // empty' "$addon")


  [ -z "$current" ] && current=$(jq -r '.version // empty' "$dir/build.json")


  [ -z "$current" ] && current=$(jq -r '.version // empty' "$dir/updater.json")


  [ -z "$current" ] && current="unknown"





  if [ "$latest" != "$current" ]; then


    if [ "$DRY_RUN" = true ]; then


      log_dryrun "$dir: Simulated update from $current to $latest"


      NOTES="$NOTES\n🧪 $name: $current → $latest"

    else


      # Update all JSON version files if present


      update_json_version "$addon_dir" "$latest_version" "config.json"


      update_json_version "$addon_dir" "$latest_version" "build.json"


      update_json_version "$addon_dir" "$latest_version" "updater.json"


      log_update "$dir: Updating from $current to $latest"


      jq --arg ver "$latest" '.version=$ver' "$addon" > tmp && mv tmp "$addon"


      jq --arg ver "$latest" '.version=$ver' "$dir/build.json" > tmp && mv tmp "$dir/build.json"


      jq --arg ver "$latest" '.version=$ver' "$dir/updater.json" > tmp && mv tmp "$dir/updater.json"




      cd "$REPO_PATH"


      git add .


      git commit -m "Update $addon_dir version to $latest_version"


      git push origin main


      [ ! -f "$dir/CHANGELOG.md" ] && echo "# Changelog" > "$dir/CHANGELOG.md"


      echo -e "\n## $latest - $(date '+%Y-%m-%d')\nUpdated from $current to $latest\nSource: https://hub.docker.com/r/$image/tags" >> "$dir/CHANGELOG.md"




      log_info "$addon_dir: Updated to $latest_version and pushed."


      git add "$dir/"*


      git commit -m "$dir: update from $current to $latest"


      NOTES="$NOTES\n✅ $name: $current → $latest"

    fi


    CHANGELOG="${CHANGELOG}${addon_dir}: Updated from $current_version to $latest_version\n"


    UPDATES_OCCURRED=true

  else


    log_info "$addon_dir: You are running the latest version: $current_version"


    CHANGELOG="${CHANGELOG}${addon_dir}: Already at latest version: $current_version\n"


    log_info "$dir: No update needed, version is $current"


    NOTES="$NOTES\nℹ️ $name: $current (up to date)"

  fi


done




# Prepare notification message


NOTIFY_MSG="Addons Updater Report:\n\n$CHANGELOG"





if [ "$ENABLE_NOTIFICATIONS" = "true" ]; then


  TITLE="Addon Updater - $( [ "$DRY_RUN" = "true" ] && echo "Dry Run" || echo "Live Run" )"


  # Green for live run, Orange for dry run


  COLOR=$( [ "$DRY_RUN" = "true" ] && echo "#FFA500" || echo "#008000")





  # Prepare Gotify message with colored lines for updated addons


  # Highlight updated lines in green


  GOTIFY_MSG=""


  while IFS= read -r line; do


    if echo "$line" | grep -q "Updated from"; then


      # Green color for updates


      GOTIFY_MSG="${GOTIFY_MSG}<font color=\"green\">${line}</font><br>"


    else


      GOTIFY_MSG="${GOTIFY_MSG}${line}<br>"


    fi


  done <<EOF


$(echo "$NOTIFY_MSG" | sed 's/^/ /')


EOF





  # Build JSON payload for Gotify


  PAYLOAD="{\"title\":\"$TITLE\",\"message\":\"$GOTIFY_MSG\",\"priority\":5,\"extras\":{\"notification\":{\"color\":\"$COLOR\"}}}"





  GOTIFY_ENDPOINT="$GOTIFY_URL/message?token=$GOTIFY_TOKEN"





  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "$PAYLOAD" "$GOTIFY_ENDPOINT")


done




  if [ "$HTTP_STATUS" = "200" ]; then


    log_info "Gotify notification sent."


  else


    log_warn "Failed to send Gotify notification. HTTP status: $HTTP_STATUS"


  fi


if [ "$DRY_RUN" != true ]; then


  git push origin "$BRANCH"

fi




[ -n "$GOTIFY_URL" ] && {


  TITLE="Addon Updater Report [$(date '+%Y-%m-%d')]"


  MSG="$(echo -e "$NOTES")"


  send_gotify "$TITLE" "$MSG"


}




log_info "===== ADDON UPDATER FINISHED ====="





# ===== END TIMER =====


END_TIME=$(date +%s)


ELAPSED=$((END_TIME - START_TIME))


log_info "Completed in ${ELAPSED}s"
