#!/usr/bin/env bash
set -euo pipefail

echo "──────────────────────────────────────────────"
echo "🧠 Jarvis Prime — Universal Notify Orchestrator"
echo "⚙️  Booting services..."
echo "──────────────────────────────────────────────"

OPTIONS_FILE="/data/options.json"

# Parse /data/options.json safely using Python (jq not guaranteed)
export_envs=$(python3 - <<'PY'
import json, sys, os, pathlib
p=pathlib.Path("/data/options.json")
d={}
if p.exists():
    try:
        d=json.loads(p.read_text())
    except Exception as e:
        print(f"# options.json parse error: {e}")
def env_bool(key, default):
    v = d.get(key, default)
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, str):  return "true" if v.lower() in ("1","true","yes","on") else "false"
    return "true" if v else "false"
def env_int(key, default):
    try: return str(int(d.get(key, default)))
    except: return str(default)
def env_str(key, default=""):
    v = d.get(key, default)
    return str(v)

out = {}
# Ingest toggles
out["INGEST_GOTIFY_ENABLED"] = env_bool("ingest_gotify_enabled", True)
out["INGEST_NTFY_ENABLED"]   = env_bool("ingest_ntfy_enabled", False)
out["INGEST_SMTP_ENABLED"]   = env_bool("ingest_smtp_enabled", True)
# Gotify
out["GOTIFY_URL"]            = env_str("gotify_url", "")
out["GOTIFY_CLIENT_TOKEN"]   = env_str("gotify_client_token", "")
out["GOTIFY_APP_TOKEN"]      = env_str("gotify_app_token", "")
# ntfy
out["NTFY_URL"]              = env_str("ntfy_url", "")
out["NTFY_TOPIC"]            = env_str("ntfy_topic", "jarvis")
out["NTFY_USER"]             = env_str("ntfy_user", "")
out["NTFY_PASS"]             = env_str("ntfy_pass", "")
out["NTFY_TOKEN"]            = env_str("ntfy_token", "")
# Inbound SMTP
out["INTAKE_SMTP_HOST"]      = env_str("smtp_host","0.0.0.0")
out["INTAKE_SMTP_PORT"]      = env_int("smtp_port",2525)
# Fan-out toggles
out["PUSH_GOTIFY_ENABLED"]   = env_bool("push_gotify_enabled", True)
out["PUSH_NTFY_ENABLED"]     = env_bool("push_ntfy_enabled", False)
out["PUSH_SMTP_ENABLED"]     = env_bool("push_smtp_enabled", False)
# Outbound SMTP
out["OUT_SMTP_HOST"]         = env_str("push_smtp_host","smtp.gmail.com")
out["OUT_SMTP_PORT"]         = env_int("push_smtp_port",587)
out["OUT_SMTP_USER"]         = env_str("push_smtp_user","")
out["OUT_SMTP_PASS"]         = env_str("push_smtp_pass","")
out["OUT_SMTP_TO"]           = env_str("push_smtp_to","")
# Inbox retention
out["RETENTION_DAYS"]        = env_int("retention_days",30)
out["AUTO_PURGE_POLICY"]     = env_str("auto_purge_policy","off")
for k,v in out.items():
    print(f'export {k}="{v}"')
PY
)

# shellcheck disable=SC2086
eval "${export_envs}"

# Show boot card
echo "   → Ingest: gotify=${INGEST_GOTIFY_ENABLED} ntfy=${INGEST_NTFY_ENABLED} smtp=${INGEST_SMTP_ENABLED}"
echo "   → Push:   gotify=${PUSH_GOTIFY_ENABLED} ntfy=${PUSH_NTFY_ENABLED} smtp=${PUSH_SMTP_ENABLED}"
echo "   → Inbox:  retention_days=${RETENTION_DAYS} policy=${AUTO_PURGE_POLICY}"
echo "   → URLs:   gotify=${GOTIFY_URL:-unset} ntfy=${NTFY_URL:-unset}"

# Start Inbox API/UI
echo "[launcher] starting inbox server (api_messages.py) on :2581"
python3 -u /app/api_messages.py &
PID_INBOX=$!

# Start SMTP intake if enabled
if [ "${INGEST_SMTP_ENABLED}" = "true" ]; then
  echo "[launcher] starting SMTP intake (smtp_server.py) on ${INTAKE_SMTP_HOST}:${INTAKE_SMTP_PORT}"
  python3 -u /app/smtp_server.py &
  PID_SMTP=$!
else
  PID_SMTP=
fi

# Start proxy (optional, ignore errors if not present)
if [ -f /app/proxy.py ]; then
  echo "[launcher] starting proxy (proxy.py)"
  python3 -u /app/proxy.py &
  PID_PROXY=$! || true
fi

# Finally start bot
echo "[launcher] starting bot (bot.py)"
exec python3 -u /app/bot.py
