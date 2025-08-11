# Unified DNS Add-on

- Debian base with best-effort apt-get update/upgrade at build and start (non-fatal if offline).
- Manual-only sync with persistent Primary.
- Dashboard: soft green (Allowed) & soft red (Blocked), KPIs, Top 3 queried/blocked, busiest server, auto-refresh 2/5/10/20s + Update now.
- Sync: forwarders where supported, cache builder list, optional cache prep; unsupported items greyed.
- Settings: manage servers, TLS verify toggle, Gotify, cache lists (global and per-server with override).
- Notifications: Gotify with de-duplication to prevent spam.
- Logs: human-readable.
- Self-Check: API reachability/auth and DNS port reachability per server.

## Endpoints
- /api/config (GET/POST)
- /api/servers (GET/POST/DELETE)
- /api/primary (POST)
- /api/sync (POST)
- /api/clear_stats (POST)
- /api/cachelist (GET/POST)
- /api/cacheprep (POST)
- /api/notify/test (POST)
- /api/selfcheck (GET)
