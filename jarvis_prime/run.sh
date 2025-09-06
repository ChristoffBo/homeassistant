#!/usr/bin/env bash
set -euo pipefail
CONFIG_PATH=/data/options.json

banner() {
  echo "──────────────────────────────────────────────"
  echo "🧠 $(jq -r '.bot_name' "$CONFIG_PATH") $(jq -r '.bot_icon' "$CONFIG_PATH")"
  echo "⚡ Boot sequence initiated..."
  echo "   → Personalities loaded"
  echo "   → Memory core mounted"
  echo "   → Network bridges linked"
  echo "   → LLM: $1"
  echo "   → Engine: $2"
  echo "   → Model path: $3"
  echo "🚀 Systems online — Jarvis is awake!"
  echo "──────────────────────────────────────────────"
}

py_download() {
python3 - "$1" "$2" <<'PY'
import sys, os, urllib.request, shutil, pathlib
url, dst = sys.argv[1], sys.argv[2]
p = pathlib.Path(dst); p.parent.mkdir(parents=True, exist_ok=True)
tmp = str(p)+".part"
try:
    with urllib.request.urlopen(url) as r, open(tmp,"wb") as f:
        shutil.copyfileobj(r,f,1024*1024)
    os.replace(tmp, dst)
    print("[Downloader] Fetched ->", dst)
except Exception as e:
    try:
        if os.path.exists(tmp): os.remove(tmp)
    except: pass
    print("[Downloader] Failed:", e); sys.exit(1)
PY
}

# ===== Core options -> env =====
export BOT_NAME=$(jq -r '.bot_name' "$CONFIG_PATH")
export BOT_ICON=$(jq -r '.bot_icon' "$CONFIG_PATH")
export GOTIFY_URL=$(jq -r '.gotify_url' "$CONFIG_PATH")
export GOTIFY_CLIENT_TOKEN=$(jq -r '.gotify_client_token' "$CONFIG_PATH")
export GOTIFY_APP_TOKEN=$(jq -r '.gotify_app_token' "$CONFIG_PATH")
export JARVIS_APP_NAME=$(jq -r '.jarvis_app_name' "$CONFIG_PATH")
export RETENTION_HOURS=$(jq -r '.retention_hours' "$CONFIG_PATH")
export BEAUTIFY_ENABLED=$(jq -r '.beautify_enabled' "$CONFIG_PATH")
export SILENT_REPOST=$(jq -r '.silent_repost // "true"' "$CONFIG_PATH")
export INBOX_RETENTION_DAYS=$(jq -r '.retention_days // 30' "$CONFIG_PATH")
export AUTO_PURGE_POLICY=$(jq -r '.auto_purge_policy // "off"' "$CONFIG_PATH")

# Weather
export weather_enabled=$(jq -r '.weather_enabled // false' "$CONFIG_PATH")
export weather_lat=$(jq -r '.weather_lat // 0' "$CONFIG_PATH")
export weather_lon=$(jq -r '.weather_lon // 0' "$CONFIG_PATH")
export weather_city=$(jq -r '.weather_city // ""' "$CONFIG_PATH")
export weather_time=$(jq -r '.weather_time // "07:00"' "$CONFIG_PATH")

# Digest
export digest_enabled=$(jq -r '.digest_enabled // false' "$CONFIG_PATH")
export digest_time=$(jq -r '.digest_time // "08:00"' "$CONFIG_PATH")

# Radarr/Sonarr
export radarr_enabled=$(jq -r '.radarr_enabled // false' "$CONFIG_PATH")
export radarr_url=$(jq -r '.radarr_url // ""' "$CONFIG_PATH")
export radarr_api_key=$(jq -r '.radarr_api_key // ""' "$CONFIG_PATH")
export radarr_time=$(jq -r '.radarr_time // "07:30"' "$CONFIG_PATH")
export sonarr_enabled=$(jq -r '.sonarr_enabled // false' "$CONFIG_PATH")
export sonarr_url=$(jq -r '.sonarr_url // ""' "$CONFIG_PATH")
export sonarr_api_key=$(jq -r '.sonarr_api_key // ""' "$CONFIG_PATH")
export sonarr_time=$(jq -r '.sonarr_time // "07:30"' "$CONFIG_PATH")

# Technitium DNS (export BOTH cases so modules find what they expect)
export TECHNITIUM_ENABLED=$(jq -r '.technitium_enabled // false' "$CONFIG_PATH")
export TECHNITIUM_URL=$(jq -r '.technitium_url // ""' "$CONFIG_PATH")
export TECHNITIUM_API_KEY=$(jq -r '.technitium_api_key // ""' "$CONFIG_PATH")
export TECHNITIUM_USER=$(jq -r '.technitium_user // ""' "$CONFIG_PATH")
export TECHNITIUM_PASS=$(jq -r '.technitium_pass // ""' "$CONFIG_PATH")
export technitium_enabled="$TECHNITIUM_ENABLED"
export technitium_url="$TECHNITIUM_URL"
export technitium_api_key="$TECHNITIUM_API_KEY"
export technitium_user="$TECHNITIUM_USER"
export technitium_pass="$TECHNITIUM_PASS"

# Uptime Kuma (export BOTH cases)
export UPTIMEKUMA_ENABLED=$(jq -r '.uptimekuma_enabled // false' "$CONFIG_PATH")
export UPTIMEKUMA_URL=$(jq -r '.uptimekuma_url // ""' "$CONFIG_PATH")
export UPTIMEKUMA_API_KEY=$(jq -r '.uptimekuma_api_key // ""' "$CONFIG_PATH")
export UPTIMEKUMA_STATUS_SLUG=$(jq -r '.uptimekuma_status_slug // ""' "$CONFIG_PATH")
export uptimekuma_enabled="$UPTIMEKUMA_ENABLED"
export uptimekuma_url="$UPTIMEKUMA_URL"
export uptimekuma_api_key="$UPTIMEKUMA_API_KEY"
export uptimekuma_status_slug="$UPTIMEKUMA_STATUS_SLUG"

# SMTP intake
export SMTP_ENABLED=$(jq -r '.smtp_enabled // false' "$CONFIG_PATH")
export SMTP_BIND=$(jq -r '.smtp_bind // "0.0.0.0"' "$CONFIG_PATH")
export SMTP_PORT=$(jq -r '.smtp_port // 2525' "$CONFIG_PATH")
export SMTP_MAX_BYTES=$(jq -r '.smtp_max_bytes // 262144' "$CONFIG_PATH")
export SMTP_DUMMY_RCPT=$(jq -r '.smtp_dummy_rcpt // "alerts@jarvis.local"' "$CONFIG_PATH")
export SMTP_ACCEPT_ANY_AUTH=$(jq -r '.smtp_accept_any_auth // true' "$CONFIG_PATH")
export SMTP_REWRITE_TITLE_PREFIX=$(jq -r '.smtp_rewrite_title_prefix // "[SMTP]"' "$CONFIG_PATH")
export SMTP_ALLOW_HTML=$(jq -r '.smtp_allow_html // false' "$CONFIG_PATH")
export SMTP_PRIORITY_DEFAULT=$(jq -r '.smtp_priority_default // 5' "$CONFIG_PATH")
export SMTP_PRIORITY_MAP=$(jq -r '.smtp_priority_map // "{}"' "$CONFIG_PATH")

# Proxy
export PROXY_ENABLED=$(jq -r '.proxy_enabled // false' "$CONFIG_PATH")
export PROXY_BIND=$(jq -r '.proxy_bind // "0.0.0.0"' "$CONFIG_PATH")
export PROXY_PORT=$(jq -r '.proxy_port // 2580' "$CONFIG_PATH")
export PROXY_GOTIFY_URL=$(jq -r '.proxy_gotify_url // ""' "$CONFIG_PATH")
export PROXY_NTFY_URL=$(jq -r '.proxy_ntfy_url // ""' "$CONFIG_PATH")

# ntfy (inbox mirror + push)
export NTFY_URL=$(jq -r '.ntfy_url // ""' "$CONFIG_PATH")
export NTFY_TOPIC=$(jq -r '.ntfy_topic // ""' "$CONFIG_PATH")
export NTFY_USER=$(jq -r '.ntfy_user // ""' "$CONFIG_PATH")
export NTFY_PASS=$(jq -r '.ntfy_pass // ""' "$CONFIG_PATH")
export NTFY_TOKEN=$(jq -r '.ntfy_token // ""' "$CONFIG_PATH")
# Push gating toggles
export push_gotify_enabled=$(jq -r '.push_gotify_enabled // false' "$CONFIG_PATH")
export push_ntfy_enabled=$(jq -r '.push_ntfy_enabled // false' "$CONFIG_PATH")

echo "[launcher] toggles: push_gotify_enabled=$push_gotify_enabled, push_ntfy_enabled=$push_ntfy_enabled"

# Hard-off pushes by blanking env if disabled
if [ "$push_gotify_enabled" != "true" ] && [ "$push_gotify_enabled" != "1" ]; then
  export GOTIFY_URL=""
  export GOTIFY_CLIENT_TOKEN=""
  export GOTIFY_APP_TOKEN=""
  echo "[launcher] hard-off: Gotify pushes disabled (env blanked)"
fi

if [ "$push_ntfy_enabled" != "true" ] && [ "$push_ntfy_enabled" != "1" ]; then
  export NTFY_URL=""
  export NTFY_TOPIC=""
  echo "[launcher] hard-off: ntfy pushes disabled (env blanked)"
fi


# Personalities
export CHAT_MOOD=$(jq -r '.personality_mood // "serious"' "$CONFIG_PATH")

# LLM controls
LLM_ENABLED=$(jq -r '.llm_enabled // false' "$CONFIG_PATH")
CLEANUP=$(jq -r '.llm_cleanup_on_disable // true' "$CONFIG_PATH")
MODELS_DIR=$(jq -r '.llm_models_dir // "/share/jarvis_prime/models"' "$CONFIG_PATH"); mkdir -p "$MODELS_DIR" || true
export LLM_TIMEOUT_SECONDS=$(jq -r '.llm_timeout_seconds // 8' "$CONFIG_PATH")
export LLM_MAX_CPU_PERCENT=$(jq -r '.llm_max_cpu_percent // 70' "$CONFIG_PATH")

PHI_ON=$(jq -r '.llm_phi3_enabled // false' "$CONFIG_PATH")
TINY_ON=$(jq -r '.llm_tinyllama_enabled // false' "$CONFIG_PATH")
QWEN_ON=$(jq -r '.llm_qwen05_enabled // false' "$CONFIG_PATH")
PHI_URL=$(jq -r '.llm_phi3_url // ""' "$CONFIG_PATH");  PHI_PATH=$(jq -r '.llm_phi3_path // ""' "$CONFIG_PATH")
TINY_URL=$(jq -r '.llm_tinyllama_url // ""' "$CONFIG_PATH"); TINY_PATH=$(jq -r '.llm_tinyllama_path // ""' "$CONFIG_PATH")
QWEN_URL=$(jq -r '.llm_qwen05_url // ""' "$CONFIG_PATH");  QWEN_PATH=$(jq -r '.llm_qwen05_path // ""' "$CONFIG_PATH")

export LLM_MODEL_PATH=""; export LLM_MODEL_URLS=""; export LLM_MODEL_URL=""; export LLM_ENABLED; export LLM_STATUS="Disabled"
if [ "$CLEANUP" = "true" ]; then
  if [ "$LLM_ENABLED" = "false" ]; then rm -f "$PHI_PATH" "$TINY_PATH" "$QWEN_PATH" || true
  else
    [ "$PHI_ON"  = "false" ] && [ -f "$PHI_PATH" ]  && rm -f "$PHI_PATH"  || true
    [ "$TINY_ON" = "false" ] && [ -f "$TINY_PATH" ] && rm -f "$TINY_PATH" || true
    [ "$QWEN_ON" = "false" ] && [ -f "$QWEN_PATH" ] && rm -f "$QWEN_PATH" || true
  fi
fi
ENGINE="disabled"; ACTIVE_PATH=""; ACTIVE_URL=""
if [ "$LLM_ENABLED" = "true" ]; then
  if   [ "$PHI_ON"  = "true" ]; then ENGINE="phi3";      ACTIVE_PATH="$PHI_PATH";  ACTIVE_URL="$PHI_URL";  LLM_STATUS="Phi-3";
  elif [ "$TINY_ON" = "true" ]; then ENGINE="tinyllama"; ACTIVE_PATH="$TINY_PATH"; ACTIVE_URL="$TINY_URL"; LLM_STATUS="TinyLlama";
  elif [ "$QWEN_ON" = "true" ]; then ENGINE="qwen05";    ACTIVE_PATH="$QWEN_PATH"; ACTIVE_URL="$QWEN_URL"; LLM_STATUS="Qwen-0.5b";
  else ENGINE="none-selected"; LLM_STATUS="Disabled"; fi
  if [ -n "$ACTIVE_URL" ] && [ -n "$ACTIVE_PATH" ]; then
    if [ ! -s "$ACTIVE_PATH" ]; then echo "[Jarvis Prime] 🔮 Downloading model ($ENGINE)…"; py_download "$ACTIVE_URL" "$ACTIVE_PATH"; fi
    if [ -s "$ACTIVE_PATH" ]; then export LLM_MODEL_PATH="$ACTIVE_PATH"; export LLM_MODEL_URL="$ACTIVE_URL"; export LLM_MODEL_URLS="$ACTIVE_URL"; fi
  fi
fi

# Require Gotify core settings ONLY if push_gotify_enabled is true
if [ "${push_gotify_enabled}" = "true" ] || [ "${push_gotify_enabled}" = "1" ]; then
  if [ -z "${GOTIFY_URL:-}" ] || [ -z "${GOTIFY_CLIENT_TOKEN:-}" ]; then
    echo "[Jarvis Prime] ❌ Missing gotify_url or gotify_client_token — aborting."; exit 1
  fi
fi

# ===== Inbox service (API + UI) =====
export JARVIS_API_BIND="0.0.0.0"; export JARVIS_API_PORT="2581"
export JARVIS_DB_PATH="/data/jarvis.db"
if [ -d "/share/jarvis_prime/ui" ]; then
  export JARVIS_UI_DIR="/share/jarvis_prime/ui"
else
  export JARVIS_UI_DIR="/app/ui"
fi
mkdir -p "$JARVIS_UI_DIR" || true

BANNER_LLM="$( [ "$LLM_ENABLED" = "true" ] && echo "$LLM_STATUS" || echo "Disabled" )"
banner "$BANNER_LLM" "$ENGINE" "${LLM_MODEL_PATH:-}"

echo "[launcher] URLs: gotify=$GOTIFY_URL ntfy=${NTFY_URL:-}"
echo "[launcher] starting inbox server (api_messages.py) on :$JARVIS_API_PORT"
python3 /app/api_messages.py &
API_PID=$!

# ===== SMTP intake =====
if [[ "${SMTP_ENABLED}" == "true" ]]; then
  echo "[launcher] starting SMTP intake (smtp_server.py) on ${SMTP_BIND}:${SMTP_PORT}"
  python3 /app/smtp_server.py &
  SMTP_PID=$! || true
else
  echo "[launcher] SMTP disabled"
fi

# ===== Proxy + Bot =====
if [[ "${PROXY_ENABLED}" == "true" ]]; then
  echo "[launcher] starting proxy (proxy.py)"; python3 /app/proxy.py & PROXY_PID=$! || true
  echo "[launcher] starting bot (bot.py)";    python3 /app/bot.py    & BOT_PID=$!   || true
else
  echo "[launcher] proxy disabled"
fi

# ===== AegisOps bootstrap (additive, idempotent) =====
AEGIS_APP="/app/aegisops"
AEGISOPS_BASE="/share/jarvis_prime/aegisops"

# copy-from-image ONLY if file missing in /share (preserve user edits)
if [ -d "$AEGIS_APP" ]; then
  mkdir -p "$AEGISOPS_BASE"
  (cd "$AEGIS_APP" && find . -type f | while read -r f; do
    mkdir -p "$AEGISOPS_BASE/$(dirname "$f")"
    [ -f "$AEGISOPS_BASE/$f" ] || cp -a "$AEGIS_APP/$f" "$AEGISOPS_BASE/$f"
  done)
fi

# ensure base folders
mkdir -p \
  "${AEGISOPS_BASE}/db" \
  "${AEGISOPS_BASE}/playbooks" \
  "${AEGISOPS_BASE}/helpers" \
  "${AEGISOPS_BASE}/callback_plugins" || true

# seed files if empty/missing (plain heredocs)
if [ ! -s "${AEGISOPS_BASE}/schedules.json" ]; then
  echo "[aegisops] seeding schedules.json"
  cat > "${AEGISOPS_BASE}/schedules.json" <<'JSON_EOF'
[
  {
    "id": "uptime-5m",
    "playbook": "check_services.yml",
    "servers": ["all"],
    "every": "5m",
    "forks": 1,
    "notify": {
      "on_success": false,
      "on_fail": true,
      "only_on_state_change": true,
      "cooldown_min": 30,
      "quiet_hours": "22:00-06:00",
      "target_key": "uptime"
    }
  }
]
JSON_EOF
fi

if [ ! -s "${AEGISOPS_BASE}/ansible.cfg" ]; then
  echo "[aegisops] seeding ansible.cfg"
  cat > "${AEGISOPS_BASE}/ansible.cfg" <<'CFG_EOF'
[defaults]
inventory = /share/jarvis_prime/aegisops/inventory.ini
callback_plugins = /share/jarvis_prime/aegisops/callback_plugins
callbacks_enabled = aegisops_notify
retry_files_enabled = False
stdout_callback = yaml
host_key_checking = False
CFG_EOF
fi

if [ ! -s "${AEGISOPS_BASE}/inventory.ini" ]; then
  echo "[aegisops] seeding inventory.ini"
  cat > "${AEGISOPS_BASE}/inventory.ini" <<'INV_EOF'
[all]
localhost ansible_host=127.0.0.1 ansible_user=root
INV_EOF
fi

if [ ! -s "${AEGISOPS_BASE}/uptime_targets.yml" ]; then
  echo "[aegisops] seeding uptime_targets.yml"
  cat > "${AEGISOPS_BASE}/uptime_targets.yml" <<'YAML_EOF'
checks:
  - { name: jarvis ui http, target: localhost, mode: http, url: "http://127.0.0.1:2581/api/health", expect: [200,204] }
YAML_EOF
fi

# --- Seed playbook, helper, and callback plugin if missing/empty ---
if [ ! -s "${AEGISOPS_BASE}/helpers/_do_check.yml" ]; then
  echo "[aegisops] seeding helpers/_do_check.yml"
  mkdir -p "${AEGISOPS_BASE}/helpers"
  cat > "${AEGISOPS_BASE}/helpers/_do_check.yml" <<'YAML_EOF'
---
# helper to execute one check item (ping|tcp|http) and append normalized result to hostvars._results
# expects `item` with fields:
#   name, mode: ping|tcp|http
#   target (host/IP), port (for tcp), timeout_s (optional)
#   url, expect (list of acceptable status codes) for http
- name: ensure result bucket exists
  set_fact:
    _results: "{{ _results | default([]) }}"

- name: ping check
  when: item.mode | lower == 'ping'
  block:
    - name: ansible ping
      ansible.builtin.ping:
      register: _chk
      ignore_errors: yes
    - name: append ping result
      set_fact:
        _results: "{{ _results + [ {
          'ts': lookup('pipe','date +%Y-%m-%dT%H:%M:%S'),
          'name': item.name | default('ping'),
          'mode': 'ping',
          'target': item.target | default(inventory_hostname),
          'status': ('ok' if (_chk is defined and _chk.ping is defined and _chk.ping == 'pong') else 'fail'),
          'detail': (_chk | to_nice_json)
        } ] }}"

- name: tcp check
  when: item.mode | lower == 'tcp'
  block:
    - name: wait for tcp port
      ansible.builtin.wait_for:
        host: "{{ item.target | default(inventory_hostname) }}"
        port: "{{ item.port | int }}"
        state: started
        timeout: "{{ (item.timeout_s | default(5)) | int }}"
      register: _chk
      ignore_errors: yes
    - name: append tcp result
      set_fact:
        _results: "{{ _results + [ {
          'ts': lookup('pipe','date +%Y-%m-%dT%H:%M:%S'),
          'name': item.name | default('tcp'),
          'mode': 'tcp',
          'target': item.target | default(inventory_hostname),
          'status': ('ok' if (_chk is defined and (_chk.failed | default(false)) == false) else 'fail'),
          'detail': (_chk | to_nice_json)
        } ] }}"

- name: http check
  when: item.mode | lower == 'http'
  block:
    - name: GET url
      ansible.builtin.uri:
        url: "{{ item.url }}"
        method: GET
        status_code: "{{ item.expect | default([200,204]) }}"
        timeout: "{{ (item.timeout_s | default(5)) | int }}"
        validate_certs: false
      register: _chk
      ignore_errors: yes
    - name: append http result
      set_fact:
        _results: "{{ _results + [ {
          'ts': lookup('pipe','date +%Y-%m-%dT%H:%M:%S'),
          'name': item.name | default('http'),
          'mode': 'http',
          'target': item.url | default(''),
          'status': ('ok' if (_chk is defined and (_chk.failed | default(false)) == false) else 'fail'),
          'detail': (_chk | combine({'status': _chk.status | default(0)}, recursive=True) | to_nice_json)
        } ] }}"
YAML_EOF
fi

if [ ! -s "${AEGISOPS_BASE}/playbooks/check_services.yml" ]; then
  echo "[aegisops] seeding playbooks/check_services.yml"
  mkdir -p "${AEGISOPS_BASE}/playbooks"
  cat > "${AEGISOPS_BASE}/playbooks/check_services.yml" <<'YAML_EOF'
---
- name: AegisOps Uptime-lite
  hosts: all
  gather_facts: false
  vars:
    _uptime: "{{ lookup('file', '/share/jarvis_prime/aegisops/uptime_targets.yml') | from_yaml }}"
    checks: "{{ _uptime.checks | default([]) }}"
  tasks:
    - name: collect checks for this host
      set_fact:
        my_checks: "{{ checks }}"

    - name: skip host with no checks
      meta: end_play
      when: my_checks | length == 0

    - name: run checks
      include_tasks: /share/jarvis_prime/aegisops/helpers/_do_check.yml
      loop: "{{ my_checks }}"
      loop_control:
        loop_var: item

    - name: expose results to callback
      ansible.builtin.set_stats:
        data:
          _results: "{{ _results | default([]) }}"
YAML_EOF
fi

if [ ! -s "${AEGISOPS_BASE}/callback_plugins/aegisops_notify.py" ]; then
  echo "[aegisops] seeding callback_plugins/aegisops_notify.py"
  mkdir -p "${AEGISOPS_BASE}/callback_plugins"
  cat > "${AEGISOPS_BASE}/callback_plugins/aegisops_notify.py" <<'PY_EOF'
# minimal, best-effort AegisOps callback
from __future__ import annotations
import os, sqlite3, time
from ansible.plugins.callback import CallbackBase

CALLBACK_VERSION = 2.0
CALLBACK_TYPE = 'notification'
CALLBACK_NAME = 'aegisops_notify'
CALLBACK_NEEDS_WHITELIST = False

DB_PATH = "/share/jarvis_prime/aegisops/db/aegisops.db"

def _safe_connect():
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        return sqlite3.connect(DB_PATH)
    except Exception:
        return None

def _init(conn):
    try:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS ansible_runs (
          id INTEGER PRIMARY KEY,
          ts DATETIME DEFAULT CURRENT_TIMESTAMP,
          playbook TEXT,
          status TEXT,
          ok_count INTEGER,
          changed_count INTEGER,
          fail_count INTEGER,
          unreachable_count INTEGER,
          target_key TEXT
        );""")
        conn.commit()
    except Exception:
        pass

class CallbackModule(CallbackBase):
    def v2_playbook_on_stats(self, stats):
        try:
            pb = os.environ.get('ANSIBLE_PLAYBOOK_NAME','')
        except Exception:
            pb = ''
        try:
            s = {
              "ok": sum(stats.ok.values()),
              "changed": sum(stats.changed.values()),
              "failures": sum(stats.failures.values()),
              "unreachable": sum(stats.unreachable.values())
            }
        except Exception:
            s = {"ok":0,"changed":0,"failures":0,"unreachable":0}
        status = "ok" if s["failures"]==0 and s["unreachable"]==0 else "fail"
        tkey = os.environ.get("J_TARGET_KEY","")
        conn = _safe_connect()
        if conn:
            try:
                _init(conn)
                cur = conn.cursor()
                cur.execute(
                  "INSERT INTO ansible_runs(playbook,status,ok_count,changed_count,fail_count,unreachable_count,target_key) VALUES (?,?,?,?,?,?,?)",
                  (pb or "", status, s["ok"], s["changed"], s["failures"], s["unreachable"], tkey)
                )
                conn.commit()
            except Exception:
                pass
            finally:
                try: conn.close()
                except: pass
PY_EOF
fi

# make sure a db file exists (SQLite will create if not present)
: > "${AEGISOPS_BASE}/db/aegisops.db"

# ===== AegisOps Runner (prefer /share; fall back to /app) =====
if [ "${AEGISOPS_ENABLED:-true}" = "true" ]; then
  if [ -f "${AEGISOPS_BASE}/runner.py" ]; then
    echo "[launcher] starting AegisOps runner (runner.py)"
    python3 "${AEGISOPS_BASE}/runner.py" &
    AEGISOPS_PID=$! || true
  elif [ -f "/app/aegisops/runner.py" ]; then
    echo "[launcher] starting AegisOps runner from image (/app/aegisops/runner.py)"
    python3 "/app/aegisops/runner.py" &
    AEGISOPS_PID=$! || true
  else
    echo "[launcher] ⚠️ AegisOps runner.py not found in /share or /app"
  fi
else
  echo "[launcher] AegisOps disabled"
fi

wait "$API_PID"
