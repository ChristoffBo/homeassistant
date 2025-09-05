# 🔔 ntfy Server – Home Assistant Add-on (Official image)

> Self‑hosted **ntfy** server with **Ingress** and **persistent storage**. Built **FROM the official Docker image** and tailored for Home Assistant.

## Features
- ✅ Uses the **official** Docker image (`binwiederhier/ntfy`) as the base
- ✅ **Ingress** support (no extra ports required)
- ✅ **/data** persistence (database, cache & attachments survive updates)
- ✅ Optional **Auth** (provision an admin on first start)
- ✅ Attachment cache size/file limits & expiry

## How it works
- Supervisor builds this add-on (`Dockerfile`) which is **FROM binwiederhier/ntfy**.
- An entrypoint script (`run.sh`) reads `/data/options.json`, generates `/data/server.yml`, then runs `ntfy serve`.
- The web UI & API are exposed to Home Assistant via **Ingress** (and optionally a host port if you set one).

## Install (Local add-on)
1. Extract the `ntfy` folder into your HA host at `/addons/ntfy` (or use the provided ZIP).
2. Go to **Settings → Add-ons → Add-on Store → ⋮ → Repositories →** Add your local folder.
3. Open the add-on → **Install** → **Start** → **Open Web UI**.

## Configuration (Options)
```yaml
listen_port: 8008             # Internal container port for ntfy (Ingress uses this)
base_url: ""                  # Optional external URL; set if you expose ntfy outside HA
behind_proxy: true            # Keep true for HA Ingress/reverse proxy

attachments:
  enabled: true
  dir: /data/attachments
  file_size_limit: "15M"      # e.g. "300k", "2M", "100M"
  total_size_limit: "5G"      # e.g. "1G", "20G"
  expiry: "3h"                # e.g. "20h", "7d"

cache:
  file: /data/cache.db

auth:
  enabled: false
  default_access: read-write  # read-write | read-only | write-only | deny-all
  admin_user: ""              # optional (used only at first boot when a password is set)
  admin_password: ""          # optional; plaintext is hashed with `ntfy user hash`
```

### Ports
- Ingress: **enabled by default**.
- Optional direct access: set a **Host port** for `8008/tcp` in the add-on UI.
- The add-on listens on `0.0.0.0:<listen_port>` inside the container.

## Data locations
- Config generated at: `/data/server.yml`
- Cache DB: `/data/cache.db`
- Attachments: `/data/attachments`
- Auth DB: `/data/user.db` (when auth is enabled)

## Notes
- The first admin user (if provided) is **provisioned** via config on startup using the built‑in CLI.
- Replace `icon.png` and `logo.png` with the **official ntfy logo assets** if you have them (these are simple placeholders).

## Upstream Docs & References
- ntfy configuration & Docker examples: https://ntfy.sh/docs/config/  
- ntfy install & image details: https://docs.ntfy.sh/install/  
- Home Assistant add-on Ingress: https://developers.home-assistant.io/docs/add-ons/configuration/
```

