# Gotify Bot — Home Assistant Add-on

Smart filter/sidecar for [Gotify](https://gotify.net): quiet hours, escalation, deduplication, optional immediate delete of the raw message after beautified repost, JSON logs, and a built-in **Help** page and **Self-Test**.

## Install

1. Place this folder in your repo, e.g. `homeassistant/addons/gotify-bot/`.
2. In Home Assistant: Settings → Add-ons → Add-on Store → (three dots) → Reload.
3. Install **Gotify Bot** → Configure → Start.
4. Open Web UI → `/help` shows all options with current values.
5. Logs show `ws_connected`, `self_test_ok`, and actions taken.

## Key Options (GUI)

- **Connectivity**
  - `gotify_url` (e.g. `http://192.168.1.10:8091`)
  - `gotify_app_token` (Application token; required)
  - `gotify_user_token` (User token; required for delete/retention)
- **Beautify & Dedupe**
  - `tag_rules` (list of `{match, tag}`), `priority_raise_regex`, `priority_lower_regex`
  - `dedup_window_sec`, `suppress_regex`
- **Quiet Hours**
  - `quiet_hours` (e.g. `22-06`), `quiet_min_priority`
- **Avoid Duplicates**
  - `delete_original_after_repost` = `true` (requires `gotify_user_token`)
  - `post_as_app_token` (optional second Application token for a Clean Feed app)
- **Retention (optional)**
  - `retention_enabled`, `retention_*`
- **Logging/Health**
  - `json_logs`, `log_level`, `healthcheck_enabled`
- **Self-Test**
  - `self_test_on_start`, `self_test_message`, `self_test_priority`, `self_test_target` (`raw` or `clean`)

## Notes

- Gotify has no “edit” API. The add-on **reposts** beautified messages and can **delete** the raw original immediately if allowed.
- Loop guard prevents the bot from reprocessing its own reposts.
- If archiving is disabled, dedup still works via in-memory guard.