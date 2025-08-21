#!/usr/bin/env sh
set -eu
OPTS="/data/options.json"
get_str() { grep -oE "\"$1\"\\s*:\\s*\"[^\"]*\"" "$OPTS" 2>/dev/null | sed -E 's/.*:\s*"([^"]*)".*/\1/' || true; }
get_int() { grep -oE "\"$1\"\\s*:\\s*[0-9]+" "$OPTS" 2>/dev/null | sed -E 's/.*:\s*([0-9]+).*/\1/' || true; }
get_bool(){ grep -oE "\"$1\"\\s*:\\s*(true|false)" "$OPTS" 2>/dev/null | sed -E 's/.*:\s*(true|false).*/\1/' || true; }
get_list(){ grep -oE "\"$1\"\\s*:\\s*\\[[^\\]]*\\]" "$OPTS" 2>/dev/null | sed -E 's/.*\[(.*)\].*/\1/' | tr -d '\"' | tr -d ' ' || true; }
TAG_RULES_RAW="$(grep -oE '"tag_rules"\s*:\s*\[[^]]*\]' "$OPTS" 2>/dev/null | sed -E 's/.*\[(.*)\].*/[\1]/')"
export GY_URL="$(get_str gotify_url)"
export GY_TOKEN="$(get_str gotify_app_token)"
export GY_USER_TOKEN="$(get_str gotify_user_token)"
export QUIET_HOURS="$(get_str quiet_hours)"
export QUIET_MIN_PRIORITY="$(get_int quiet_min_priority)"
export DEDUP_WINDOW_SEC="$(get_int dedup_window_sec)"
export SUPPRESS_REGEX="$(get_list suppress_regex)"
export PRIORITY_RAISE_REGEX="$(get_list priority_raise_regex)"
export PRIORITY_LOWER_REGEX="$(get_list priority_lower_regex)"
export TAG_RULES_JSON="${TAG_RULES_RAW:-[]}"
export RETENTION_ENABLED="$(get_bool retention_enabled)"
export RETENTION_INTERVAL_SEC="$(get_int retention_interval_sec)"
export RETENTION_MAX_AGE_HOURS="$(get_int retention_max_age_hours)"
export RETENTION_MIN_PRIORITY_KEEP="$(get_int retention_min_priority_keep)"
export RETENTION_KEEP_APPS="$(get_list retention_keep_apps)"
export RETENTION_DRY_RUN="$(get_bool retention_dry_run)"
export ENABLE_ARCHIVING="$(get_bool enable_archiving)"
export ARCHIVE_MAX_MB="$(get_int archive_max_mb)"
export ARCHIVE_TTL_HOURS_DEFAULT="$(get_int archive_ttl_hours_default)"
export ARCHIVE_TTL_HOURS_HIGH="$(get_int archive_ttl_hours_high)"
export ARCHIVE_TTL_HOURS_KEEP_APPS="$(get_int archive_ttl_hours_keep_apps)"
export ARCHIVE_KEEP_APPS="$(get_list archive_keep_apps)"
export ARCHIVE_PRUNE_INTERVAL_SEC="$(get_int archive_prune_interval_sec)"
export LOG_LEVEL="$(get_str log_level)"
export HEALTHCHECK_ENABLED="$(get_bool healthcheck_enabled)"
export FAIL_OPEN="$(get_bool fail_open)"
export JSON_LOGS="$(get_bool json_logs)"
export DELETE_AFTER_REPOST="$(get_bool delete_original_after_repost)"
export POST_AS_APP_TOKEN="$(get_str post_as_app_token)"
export SELF_TEST_ON_START="$(get_bool self_test_on_start)"
export SELF_TEST_MESSAGE="$(get_str self_test_message)"
export SELF_TEST_PRIORITY="$(get_int self_test_priority)"
export SELF_TEST_TARGET="$(get_str self_test_target)"
# Proxy
export PROXY_ENABLED="$(get_bool proxy_enabled)"
export PROXY_LISTEN_PORT="$(get_int proxy_listen_port)"
export PROXY_FORWARD_BASE_URL="$(get_str proxy_forward_base_url)"
export PROXY_LOG_BODIES="$(get_bool proxy_log_bodies)"
mkdir -p /data
exec python /app/bot.py