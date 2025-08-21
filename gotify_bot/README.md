# 🧩 Gotify Bot — Home Assistant Add-on

This add-on runs a lightweight Gotify companion service inside Home Assistant.  
It connects to your Gotify server, listens for messages, applies rules (quiet hours, deduplication, beautify, tagging), and can optionally act as a reverse proxy for Gotify.  

It exposes a small help/health web server on port **8080**.  
It requires valid Gotify credentials (Basic Auth or App Token).  

## What it is and what it is used for

Gotify Bot extends your Gotify setup with smart filtering and message processing.  
It can:

- Beautify incoming messages (add tags, raise/lower priority).  
- Suppress noisy or duplicate alerts.  
- Apply YAML-defined rules for advanced matching.  
- Enforce quiet hours.  
- Retain or auto-delete messages.  
- Archive messages locally.  
- Act as a proxy to forward old Gotify endpoints to a new Gotify server (useful if you move Gotify and don’t want to reconfigure 30+ clients).  

Running Gotify Bot in Home Assistant makes sense because Home Assistant already centralizes automation and alerting. The bot lets you fine-tune the flood of Gotify notifications, without editing each app.

## Features

- Beautify and tag messages  
- Quiet hours and suppression  
- Deduplication window  
- Retention and auto-cleanup  
- Optional archiving to disk  
- Optional proxy forwarder  
- Health check endpoint on port **8080**  
- Based on `python:3.12-slim`

## Paths

- **Rules (YAML)**: `/app/rules.yaml`  
- **Archive (if enabled)**: `/share/gotify_bot/archive`  
- **Logs**: visible in Home Assistant Supervisor logs  

## Options

All options are set in the add-on GUI.

| Option | Description |
|--------|-------------|
| `gotify_url` | Full URL of your Gotify server (http/https). |
| `gotify_username` | Gotify user for Basic Auth. |
| `gotify_password` | Password for above. |
| `post_as_app_token` | App token to repost beautified messages. |
| `quiet_hours` | e.g. `22-07` (suppress low priority messages overnight). |
| `quiet_min_priority` | Priority required to bypass quiet hours. |
| `dedup_window_sec` | Suppress duplicate messages seen in this timeframe. |
| `suppress_regex` | Comma-separated regex patterns to block messages. |
| `priority_raise_regex` | Regex to force priority high. |
| `priority_lower_regex` | Regex to force priority low. |
| `tag_rules_json` | JSON list of `{ "match": "text", "tag": "[TAG]" }`. |
| `delete_after_repost` | Delete original after repost. |
| `retention_enabled` | Enable periodic deletion of old messages. |
| `retention_max_age_hours` | Age in hours before old messages are removed. |
| `retention_min_priority_keep` | Priority to always keep. |
| `enable_archiving` | Archive all messages to `/share/gotify_bot/archive`. |
| `archive_max_mb` | Max archive size before pruning. |
| `proxy_enabled` | Enable proxy forwarder. |
| `proxy_listen_port` | Local port to listen for legacy Gotify apps. |
| `proxy_forward_base_url` | Target Gotify base URL to forward requests. |

## First-Time Setup (required)

1. Create a Gotify user and password (or App Token).  
2. Enter credentials in the add-on Options panel.  
3. (Optional) Add a `rules.yaml` in `/share/gotify_bot/rules.yaml` for advanced matching.  

## Default Behavior

- On boot, the add-on connects to Gotify using Basic Auth.  
- It starts the rule processor and a `/health` endpoint on **8080**.  
- If enabled, it also starts the proxy forwarder.  

## Force Fresh First Boot

To reset the bot (clear state and archive):

```bash
rm -rf /share/gotify_bot/*