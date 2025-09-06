#!/usr/bin/env python3
# /app/bot.py

import os
import json
import asyncio
import requests
import websockets
import re
import subprocess
import atexit
import time
import socket
import hashlib
from typing import List, Optional, Tuple

# ============================
# Inbox storage
# ============================
try:
    import storage  # /app/storage.py
    storage.init_db()
except Exception as _e:
    storage = None
    print(f"[bot] ⚠️ storage init failed: {_e}")

# ============================
# Basic env
# ============================
BOT_NAME  = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON  = os.getenv("BOT_ICON", "🧠")

# Output (Gotify used as one of many outputs; not hardwired as the only intake)
GOTIFY_URL   = os.getenv("GOTIFY_URL", "").rstrip("/")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN", "")
APP_TOKEN    = os.getenv("GOTIFY_APP_TOKEN", "")
APP_NAME     = os.getenv("JARVIS_APP_NAME", "Jarvis")

SILENT_REPOST    = os.getenv("SILENT_REPOST", "true").lower() in ("1","true","yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1","true","yes")

# Feature toggles (env defaults; can be overridden by /data/options.json or /data/config.json)
RADARR_ENABLED     = os.getenv("radarr_enabled", "false").lower() in ("1","true","yes")
SONARR_ENABLED     = os.getenv("sonarr_enabled", "false").lower() in ("1","true","yes")
WEATHER_ENABLED    = os.getenv("weather_enabled", "false").lower() in ("1","true","yes")
CHAT_ENABLED_ENV   = os.getenv("chat_enabled", "false").lower() in ("1","true","yes")
DIGEST_ENABLED_ENV = os.getenv("digest_enabled", "false").lower() in ("1","true","yes")
TECHNITIUM_ENABLED = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")
KUMA_ENABLED       = os.getenv("uptimekuma_enabled", "false").lower() in ("1","true","yes")
SMTP_ENABLED       = os.getenv("smtp_enabled", "false").lower() in ("1","true","yes")
PROXY_ENABLED_ENV  = os.getenv("proxy_enabled", "false").lower() in ("1","true","yes")

# Ingest toggles (which intakes to listen to)
INGEST_GOTIFY_ENABLED  = os.getenv("ingest_gotify_enabled", "true").lower() in ("1","true","yes")
INGEST_APPRISE_ENABLED = os.getenv("ingest_apprise_enabled", "true").lower() in ("1","true","yes")
INGEST_SMTP_ENABLED    = os.getenv("ingest_smtp_enabled", "true").lower() in ("1","true","yes")
INGEST_NTFY_ENABLED    = os.getenv("ingest_ntfy_enabled", "false").lower() in ("1","true","yes")  # handled by proxy sidecar

# Webhook feature toggles
WEBHOOK_ENABLED    = os.getenv("webhook_enabled", "false").lower() in ("1","true","yes")
WEBHOOK_BIND       = os.getenv("webhook_bind", "0.0.0.0")
WEBHOOK_PORT       = int(os.getenv("webhook_port", "2590"))

# Apprise intake sidecar (separate process)
INTAKE_APPRISE_ENABLED = os.getenv("intake_apprise_enabled", "false").lower() in ("1","true","yes")
INTAKE_APPRISE_TOKEN = os.getenv("intake_apprise_token", "")
INTAKE_APPRISE_ACCEPT_ANY_KEY = os.getenv("intake_apprise_accept_any_key", "true").lower() in ("1","true","yes")
INTAKE_APPRISE_ALLOWED_KEYS = [k for k in os.getenv("intake_apprise_allowed_keys", "").split(",") if k.strip()]
INTAKE_APPRISE_PORT = int(os.getenv("intake_apprise_port", "2591"))
INTAKE_APPRISE_BIND = os.getenv("intake_apprise_bind", "0.0.0.0")

# LLM toggles
LLM_REWRITE_ENABLED = os.getenv("LLM_REWRITE_ENABLED", "false").lower() in ("1","true","yes")
BEAUTIFY_LLM_ENABLED_ENV = os.getenv("BEAUTIFY_LLM_ENABLED", "true").lower() in ("1","true","yes")

# Defaults that get finalized after config load
PROXY_ENABLED = PROXY_ENABLED_ENV
CHAT_ENABLED_FILE = CHAT_ENABLED_ENV
DIGEST_ENABLED_FILE = DIGEST_ENABLED_ENV

# ============================
# Load /data/options.json (overrides) + /data/config.json (fallback)
# ============================
def _load_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

merged = {}
try:
    options = _load_json("/data/options.json")
    fallback = _load_json("/data/config.json")
    merged = {**fallback, **options}

    RADARR_ENABLED  = bool(merged.get("radarr_enabled", RADARR_ENABLED))
    SONARR_ENABLED  = bool(merged.get("sonarr_enabled", SONARR_ENABLED))
    WEATHER_ENABLED = bool(merged.get("weather_enabled", WEATHER_ENABLED))
    TECHNITIUM_ENABLED = bool(merged.get("technitium_enabled", TECHNITIUM_ENABLED))
    KUMA_ENABLED    = bool(merged.get("uptimekuma_enabled", KUMA_ENABLED))
    SMTP_ENABLED    = bool(merged.get("smtp_enabled", SMTP_ENABLED))
    PROXY_ENABLED   = bool(merged.get("proxy_enabled", PROXY_ENABLED_ENV))
    CHAT_ENABLED_FILE   = bool(merged.get("chat_enabled", CHAT_ENABLED_ENV))
    DIGEST_ENABLED_FILE = bool(merged.get("digest_enabled", DIGEST_ENABLED_ENV))

    # Ingest toggles from config file if present
    INGEST_GOTIFY_ENABLED  = bool(merged.get("ingest_gotify_enabled", INGEST_GOTIFY_ENABLED))
    INGEST_APPRISE_ENABLED = bool(merged.get("intake_apprise_enabled", INTAKE_APPRISE_ENABLED)) and bool(merged.get("ingest_apprise_enabled", INGEST_APPRISE_ENABLED))
    INGEST_SMTP_ENABLED    = bool(merged.get("ingest_smtp_enabled", INGEST_SMTP_ENABLED))
    INGEST_NTFY_ENABLED    = bool(merged.get("ingest_ntfy_enabled", INGEST_NTFY_ENABLED))

    # Webhook
    WEBHOOK_ENABLED = bool(merged.get("webhook_enabled", WEBHOOK_ENABLED))
    WEBHOOK_BIND    = str(merged.get("webhook_bind", WEBHOOK_BIND))
    try:
        WEBHOOK_PORT = int(merged.get("webhook_port", WEBHOOK_PORT))
    except Exception:
        pass

    # Apprise sidecar
    INTAKE_APPRISE_ENABLED = bool(merged.get("intake_apprise_enabled", INTAKE_APPRISE_ENABLED))
    INTAKE_APPRISE_TOKEN = str(merged.get("intake_apprise_token", INTAKE_APPRISE_TOKEN or ""))
    INTAKE_APPRISE_ACCEPT_ANY_KEY = bool(merged.get("intake_apprise_accept_any_key", INTAKE_APPRISE_ACCEPT_ANY_KEY))
    INTAKE_APPRISE_PORT = int(merged.get("intake_apprise_port", INTAKE_APPRISE_PORT))
    INTAKE_APPRISE_BIND = str(merged.get("intake_apprise_bind", INTAKE_APPRISE_BIND or "0.0.0.0"))
    _allowed = merged.get("intake_apprise_allowed_keys", INTAKE_APPRISE_ALLOWED_KEYS)
    if isinstance(_allowed, list):
        INTAKE_APPRISE_ALLOWED_KEYS = [str(x) for x in _allowed]
    elif isinstance(_allowed, str) and _allowed.strip():
        INTAKE_APPRISE_ALLOWED_KEYS = [s.strip() for s in _allowed.split(",")]
    else:
        INTAKE_APPRISE_ALLOWED_KEYS = []

    # LLM + riffs linkup:
    # Riffs fire only when BOTH llm_enabled==True AND llm_persona_riffs_enabled==True
    LLM_REWRITE_ENABLED = bool(merged.get("llm_rewrite_enabled", LLM_REWRITE_ENABLED))
    _beautify_llm_enabled_opt = bool(merged.get("llm_persona_riffs_enabled", BEAUTIFY_LLM_ENABLED_ENV))
    os.environ["BEAUTIFY_LLM_ENABLED"] = "true" if _beautify_llm_enabled_opt else "false"

except Exception:
    PROXY_ENABLED = PROXY_ENABLED_ENV
    CHAT_ENABLED_FILE = CHAT_ENABLED_ENV
    DIGEST_ENABLED_FILE = DIGEST_ENABLED_ENV

# ============================
# Load optional modules
# ============================
def _load_module(name, path):
    try:
        import importlib.util as _imp
        spec = _imp.spec_from_file_location(name, path)
        if spec and spec.loader:
            mod = _imp.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    except Exception as e:
        print(f"[bot] module load failed {name}: {e}")
    return None

_aliases = _load_module("aliases", "/app/aliases.py")
_personality = _load_module("personality", "/app/personality.py")
_pstate = _load_module("personality_state", "/app/personality_state.py")
_beautify = _load_module("beautify", "/app/beautify.py")
_llm = _load_module("llm_client", "/app/llm_client.py")
_heartbeat = _load_module("heartbeat", "/app/heartbeat.py")  # <— NEW: wire heartbeat

# === EnviroGuard (INLINE — no extra file) ===
ENVGUARD = {
    "enabled": bool(merged.get("llm_enviroguard_enabled", False)),
    "poll_minutes": int(merged.get("llm_enviroguard_poll_minutes", 30)),
    "max_stale_minutes": int(merged.get("llm_enviroguard_max_stale_minutes", 120)),
    "hot_c": int(merged.get("llm_enviroguard_hot_c", 30)),
    "cold_c": int(merged.get("llm_enviroguard_cold_c", 10)),
    "hyst_c": int(merged.get("llm_enviroguard_hysteresis_c", 2)),
    "profiles": merged.get("llm_enviroguard_profiles", {
        "manual": { "cpu_percent": 80, "ctx_tokens": 4096, "timeout_seconds": 20 },
        "hot":    { "cpu_percent": 50, "ctx_tokens": 2048, "timeout_seconds": 15 },
        "normal": { "cpu_percent": 80, "ctx_tokens": 4096, "timeout_seconds": 20 },
        "boost":  { "cpu_percent": 95, "ctx_tokens": 8192, "timeout_seconds": 25 },
        "cold":   { "cpu_percent": 85, "ctx_tokens": 6144, "timeout_seconds": 25 }
    }),
    "profile": "normal",
    "temp_c": None,
    "last_ts": 0,
    "source": "open-meteo"
}

# Normalize profiles if user provided a JSON string in options
if isinstance(ENVGUARD["profiles"], str):
    try:
        ENVGUARD["profiles"] = json.loads(ENVGUARD["profiles"])
    except Exception:
        ENVGUARD["profiles"] = {
            "manual": { "cpu_percent": 80, "ctx_tokens": 4096, "timeout_seconds": 20 },
            "hot":    { "cpu_percent": 50, "ctx_tokens": 2048, "timeout_seconds": 15 },
            "normal": { "cpu_percent": 80, "ctx_tokens": 4096, "timeout_seconds": 20 },
            "boost":  { "cpu_percent": 95, "ctx_tokens": 8192, "timeout_seconds": 25 },
            "cold":   { "cpu_percent": 85, "ctx_tokens": 6144, "timeout_seconds": 25 }
        }

ACTIVE_PERSONA, PERSONA_TOD = "neutral", ""
if _pstate and hasattr(_pstate, "get_active_persona"):
    try:
        ACTIVE_PERSONA, PERSONA_TOD = _pstate.get_active_persona()
    except Exception:
        pass

# ============================
# LLM model path resolver / autodetect
# ============================
def _fs_safe(path: str) -> bool:
    try:
        return bool(path and os.path.exists(path))
    except Exception:
        return False

def _choose_existing_model_on_disk() -> Optional[str]:
    try:
        models_dir = str(merged.get("llm_models_dir", "/share/jarvis_prime/models")).rstrip("/")
        os.makedirs(models_dir, exist_ok=True)

        p = str(merged.get("llm_model_path", "")).strip()
        if p and _fs_safe(p) and os.path.isfile(p):
            return p

        if p and os.path.isdir(p):
            for n in os.listdir(p):
                if n.lower().endswith(".gguf"):
                    return os.path.join(p, n)

        phi3_path = str(merged.get("llm_phi3_path", "")).strip()
        if phi3_path and _fs_safe(phi3_path) and os.path.isfile(phi3_path):
            return phi3_path
        tiny_path = str(merged.get("llm_tinyllama_path", "")).strip()
        if tiny_path and _fs_safe(tiny_path) and os.path.isfile(tiny_path):
            return tiny_path
        qwen_path = str(merged.get("llm_qwen05_path", "")).strip()
        if qwen_path and _fs_safe(qwen_path) and os.path.isfile(qwen_path):
            return qwen_path

        for n in os.listdir(models_dir):
            if n.lower().endswith(".gguf"):
                return os.path.join(models_dir, n)
    except Exception as e:
        print(f"[llm] autodetect error: {e}")
    return None

def _llm_inputs_for_client() -> dict:
    kwargs = {
        "text": None,
        "mood": ACTIVE_PERSONA,
        "timeout": int(merged.get("llm_timeout_seconds", 20)),
        "cpu_limit": int(merged.get("llm_max_cpu_percent", 80)),
        "models_priority": merged.get("llm_models_priority", []),
        "base_url": merged.get("llm_ollama_base_url", ""),
        "model_url": merged.get("llm_model_url", ""),
        "model_path": merged.get("llm_model_path", ""),
        "model_sha256": merged.get("llm_model_sha256", ""),
        "allow_profanity": bool(merged.get("personality_allow_profanity", False)),
        "ctx_tokens": int(merged.get("llm_ctx_tokens", 4096)),
        "gen_tokens": int(merged.get("llm_gen_tokens", 300)),
        "max_lines": int(merged.get("llm_max_lines", 30)),
    }

    local_file = _choose_existing_model_on_disk()
    if local_file:
        kwargs["model_path"] = local_file
        kwargs["model_url"] = ""
    return kwargs

# ============================
# Sidecars (with port guards)
# ============================
_sidecars: List[subprocess.Popen] = []

def _port_in_use(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False

def _start_sidecar(cmd, label, env=None):
    try:
        # Inherit stdout/stderr so logs show if it crashes immediately
        p = subprocess.Popen(cmd, stdout=None, stderr=None, env=env or os.environ.copy())
        _sidecars.append(p)
        print(f"[bot] started sidecar: {label} -> {cmd}")
    except Exception as e:
        print(f"[bot] sidecar {label} start failed: {e}")

def _apprise_env() -> dict:
    env = os.environ.copy()
    env["INTAKE_APPRISE_BIND"] = INTAKE_APPRISE_BIND
    env["INTAKE_APPRISE_PORT"] = str(INTAKE_APPRISE_PORT)
    env["INTAKE_APPRISE_TOKEN"] = INTAKE_APPRISE_TOKEN
    env["INTAKE_APPRISE_ACCEPT_ANY_KEY"] = "true" if INTAKE_APPRISE_ACCEPT_ANY_KEY else "false"
    env["INTAKE_APPRISE_ALLOWED_KEYS"] = ",".join(INTAKE_APPRISE_ALLOWED_KEYS)
    env["JARVIS_INTERNAL_EMIT_URL"] = "http://127.0.0.1:2599/internal/emit"
    return env

# NEW: ensure smtp_server.py and proxy.py also forward into the core beautifier/LLM
def _forward_env(extra: Optional[dict] = None) -> dict:
    env = os.environ.copy()
    # route all intakes through the core so riffs/LLM apply uniformly
    env["JARVIS_INTERNAL_EMIT_URL"] = "http://127.0.0.1:2599/internal/emit"
    # propagate persona/LLM flags
    env["BEAUTIFY_LLM_ENABLED"] = os.getenv("BEAUTIFY_LLM_ENABLED", "true")
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env

def start_sidecars():
    # proxy
    if PROXY_ENABLED:
        if _port_in_use("127.0.0.1", 2580) or _port_in_use("0.0.0.0", 2580):
            print("[bot] proxy.py already running on :2580 — skipping sidecar")
        else:
            _start_sidecar(["python3", "/app/proxy.py"], "proxy.py", env=_forward_env())

    # smtp
    if SMTP_ENABLED and INGEST_SMTP_ENABLED:
        if _port_in_use("127.0.0.1", 2525) or _port_in_use("0.0.0.0", 2525):
            print("[bot] smtp_server.py already running on :2525 — skipping sidecar")
        else:
            _start_sidecar(["python3", "/app/smtp_server.py"], "smtp_server.py", env=_forward_env())

    # webhook
    if WEBHOOK_ENABLED:
        if _port_in_use("127.0.0.1", int(WEBHOOK_PORT)) or _port_in_use("0.0.0.0", int(WEBHOOK_PORT)):
            print(f"[bot] webhook_server.py already running on :{WEBHOOK_PORT} — skipping sidecar")
        else:
            env = _forward_env({"webhook_bind": WEBHOOK_BIND, "webhook_port": str(WEBHOOK_PORT)})
            _start_sidecar(["python3", "/app/webhook_server.py"], "webhook_server.py", env=env)

    # apprise
    if INTAKE_APPRISE_ENABLED and INGEST_APPRISE_ENABLED:
        if _port_in_use("127.0.0.1", int(INTAKE_APPRISE_PORT)) or _port_in_use("0.0.0.0", int(INTAKE_APPRISE_PORT)):
            print(f"[bot] apprise intake already running on :{INTAKE_APPRISE_PORT} — skipping sidecar")
        else:
            # ensure internal is up before starting
            if not _port_in_use("127.0.0.1", 2599):
                print("[bot] deferring apprise sidecar until internal server is up on :2599")
            else:
                env = _apprise_env()
                safe_env_print = {
                    "INTAKE_APPRISE_BIND": env.get("INTAKE_APPRISE_BIND"),
                    "INTAKE_APPRISE_PORT": env.get("INTAKE_APPRISE_PORT"),
                    "INTAKE_APPRISE_ACCEPT_ANY_KEY": env.get("INTAKE_APPRISE_ACCEPT_ANY_KEY"),
                    "INTAKE_APPRISE_ALLOWED_KEYS": env.get("INTAKE_APPRISE_ALLOWED_KEYS"),
                    "JARVIS_INTERNAL_EMIT_URL": env.get("JARVIS_INTERNAL_EMIT_URL")
                }
                print(f"[bot] starting apprise sidecar with env: {safe_env_print}")
                _start_sidecar(["python3", "/app/apprise.py"], "apprise.py", env=env)
                print(f"[bot] apprise intake configured on {INTAKE_APPRISE_BIND}:{INTAKE_APPRISE_PORT}")

def stop_sidecars():
    for p in _sidecars:
        try:
            p.terminate()
        except Exception:
            pass
atexit.register(stop_sidecars)
# ============================
# Gotify helpers (output)
# ============================
jarvis_app_id = None

def _persona_line(quip_text: str) -> str:
    who = ACTIVE_PERSONA or "neutral"
    quip_text = (quip_text or "").strip().replace("\n", " ")
    if len(quip_text) > 140:
        quip_text = quip_text[:137] + "..."
    return f"💬 {who} says: {quip_text}" if quip_text else f"💬 {who} says:"

def send_message(title, message, priority=5, extras=None, decorate=True):
    orig_title = title
    try:
        if decorate and _personality and hasattr(_personality, "decorate_by_persona"):
            title, message = _personality.decorate_by_persona(title, message, ACTIVE_PERSONA, PERSONA_TOD, chance=1.0)
            title = orig_title
        elif decorate and _personality and hasattr(_personality, "decorate"):
            title, message = _personality.decorate(title, message, ACTIVE_PERSONA, chance=1.0)
            title = orig_title
    except Exception:
        title, message = orig_title, message

    try:
        quip_text = _personality.quip(ACTIVE_PERSONA) if _personality and hasattr(_personality, "quip") else ""
    except Exception:
        quip_text = ""
    header = _persona_line(quip_text)
    message = (header + ("\n" + (message or ""))) if header else (message or "")

    if _personality and hasattr(_personality, "apply_priority"):
        try:
            priority = _personality.apply_priority(priority, ACTIVE_PERSONA)
        except Exception:
            pass

    if GOTIFY_URL and APP_TOKEN:
        url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
        payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message or "", "priority": priority}
        if extras:
            payload["extras"] = extras
        try:
            r = requests.post(url, json=payload, timeout=8)
            r.raise_for_status()
            status = r.status_code
        except Exception as e:
            status = 0
            print(f"[bot] send_message error: {e}")
    else:
        status = -1

    if storage:
        try:
            storage.save_message(
                title=orig_title or "Notification",
                body=message or "",
                source="jarvis_out",
                priority=int(priority),
                extras={"extras": extras or {}, "status": status},
                created_at=int(time.time())
            )
        except Exception as e:
            print(f"[bot] storage save failed: {e}")

    return True

def delete_original_message(msg_id: int):
    try:
        if not (msg_id and GOTIFY_URL and CLIENT_TOKEN):
            return
        url = f"{GOTIFY_URL}/message/{msg_id}"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        requests.delete(url, headers=headers, timeout=6)
    except Exception:
        pass

def resolve_app_id():
    global jarvis_app_id
    jarvis_app_id = None
    if not (GOTIFY_URL and CLIENT_TOKEN):
        return
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=8)
        r.raise_for_status()
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
                break
    except Exception:
        pass

def _is_our_post(data: dict) -> bool:
    try:
        if jarvis_app_id and data.get("appid") == jarvis_app_id:
            return True
        t = data.get("title") or ""
        return t.startswith(f"{BOT_ICON} {BOT_NAME}:")
    except Exception:
        return False

def _should_purge() -> bool:
    try:
        return bool(merged.get("silent_repost", SILENT_REPOST))
    except Exception:
        return SILENT_REPOST

def _purge_after(msg_id: int):
    if _should_purge():
        delete_original_message(msg_id)

def _footer(used_llm: bool, used_beautify: bool) -> str:
    tags = []
    if used_llm: tags.append("Neural Core ✓")
    if used_beautify: tags.append("Aesthetic Engine ✓")
    if not tags: tags.append("Relay Path")
    return "— " + " · ".join(tags)

def _llm_then_beautify(title: str, message: str):
    # Reflect LLM state in footer tag
    used_llm = bool(merged.get("llm_enabled")) or bool(merged.get("llm_rewrite_enabled")) or LLM_REWRITE_ENABLED
    used_beautify = True if _beautify else False
    final = message or ""
    extras = None

    try:
        if _beautify and hasattr(_beautify, "beautify_message"):
            final, extras = _beautify.beautify_message(
                title,
                final,
                mood=ACTIVE_PERSONA,
                persona=ACTIVE_PERSONA,
                persona_quip=True  # <— enable persona riffs for all intakes
            )
    except Exception as e:
        print(f"[bot] Beautify failed: {e}")

    foot = _footer(used_llm, used_beautify)
    if final and not final.rstrip().endswith(foot):
        final = f"{final.rstrip()}\n\n{foot}"
    return final, extras, used_llm, used_beautify

# ============================
# Commands
# ============================
def _clean(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def normalize_cmd(cmd: str) -> str:
    try:
        if _aliases and hasattr(_aliases, "normalize_cmd"):
            return _aliases.normalize_cmd(cmd)
    except Exception:
        pass
    return _clean(cmd)

def extract_command_from(title: str, message: str) -> str:
    tlow, mlow = (title or "").lower(), (message or "").lower()
    if tlow.startswith("jarvis"):
        rest = tlow.replace("jarvis","",1).strip()
        return rest or (mlow.replace("jarvis","",1).strip() if mlow.startswith("jarvis") else mlow.strip())
    if mlow.startswith("jarvis"): return mlow.replace("jarvis","",1).strip()
    return ""

def post_startup_card():
    lines = [
        "🧬 Prime Neural Boot",
        f"🛰️ Engine: Neural Core — {'ONLINE' if merged.get('llm_enabled') else 'OFFLINE'}",
        f"🧠 LLM: {'Enabled' if merged.get('llm_enabled') else 'Disabled'}",
        f"🗣️ Persona speaking: {ACTIVE_PERSONA} ({PERSONA_TOD})",
        "",
        "Modules:",
        f"🎬 Radarr — {'ACTIVE' if RADARR_ENABLED else 'OFF'}",
        f"📺 Sonarr — {'ACTIVE' if SONARR_ENABLED else 'OFF'}",
        f"🌤️ Weather — {'ACTIVE' if WEATHER_ENABLED else 'OFF'}",
        f"🧾 Digest — {'ACTIVE' if DIGEST_ENABLED_FILE else 'OFF'}",
        f"💬 Chat — {'ACTIVE' if CHAT_ENABLED_FILE else 'OFF'}",
        f"📈 Uptime Kuma — {'ACTIVE' if KUMA_ENABLED else 'OFF'}",
        f"✉️ SMTP Intake — {'ACTIVE' if (SMTP_ENABLED and INGEST_SMTP_ENABLED) else 'OFF'}",
        f"🔀 Proxy Intake — {'ACTIVE' if PROXY_ENABLED else 'OFF'}",
        f"🧠 DNS (Technitium) — {'ACTIVE' if TECHNITIUM_ENABLED else 'OFF'}",
        f"🔗 Webhook Intake — {'ACTIVE' if WEBHOOK_ENABLED else 'OFF'}",
        f"📮 Apprise Intake — {'ACTIVE' if (INTAKE_APPRISE_ENABLED and INGEST_APPRISE_ENABLED) else 'OFF'}",
        (f"🌡️ EnviroGuard — {'ACTIVE' if ENVGUARD.get('enabled') else 'OFF'}"
         + (f" (profile={ENVGUARD.get('profile')}, {ENVGUARD.get('temp_c')} °C)" if ENVGUARD.get('temp_c') is not None else "")),
        "",
        f"LLM rewrite: {'ON' if LLM_REWRITE_ENABLED else 'OFF'}",
        f"Persona riffs: {'ON' if os.getenv('BEAUTIFY_LLM_ENABLED','true').lower() in ('1','true','yes') else 'OFF'}",
        "Status: All systems nominal",
    ]
    send_message("Startup", "\n".join(lines), priority=4, decorate=False)

def _try_call(module, fn_name, *args, **kwargs):
    try:
        if module and hasattr(module, fn_name):
            return getattr(module, fn_name)(*args, **kwargs)
    except Exception as e:
        return f"⚠️ {fn_name} failed: {e}", None
    return None, None

def _handle_command(ncmd: str) -> bool:
    # --- Manual EnviroGuard override: "jarvis env hot|normal|cold|boost" or "jarvis profile X"
    toks = ncmd.split()
    if toks and toks[0] in ("env", "profile"):
        if len(toks) >= 2:
            want = toks[1].lower()
            if want in (ENVGUARD.get("profiles") or {}):
                ENVGUARD["profile"] = want
                _enviroguard_apply(want)
                try:
                    send_message(
                        "EnviroGuard",
                        f"Manual override → profile **{want.upper()}** (CPU={merged.get('llm_max_cpu_percent')}%, ctx={merged.get('llm_ctx_tokens')}, to={merged.get('llm_timeout_seconds')}s)",
                        priority=4,
                        decorate=False
                    )
                except Exception:
                    pass
                return True
            else:
                send_message("EnviroGuard", f"Unknown profile '{want}'. Valid: {', '.join((ENVGUARD.get('profiles') or {}).keys())}", priority=3, decorate=False)
                return True

    m_arr = m_weather = m_kuma = m_tech = m_digest = m_chat = None
    try: m_arr = __import__("arr")
    except Exception: pass
    try: m_weather = __import__("weather")
    except Exception: pass
    try: m_kuma = __import__("uptimekuma")
    except Exception: pass
    try: m_tech = __import__("technitium")
    except Exception: pass
    try: m_digest = __import__("digest")
    except Exception: pass
    try: m_chat = __import__("chat")
    except Exception: pass

    if ncmd in ("help", "commands"):
        send_message("Help", "dns | kuma | weather | forecast | digest | joke\nARR: upcoming movies/series, counts, longest ...\nEnv: env <hot|normal|cold|boost>",)
        return True

    if ncmd in ("digest", "daily digest", "summary"):
        if m_digest and hasattr(m_digest, "build_digest"):
            title2, msg2, pr = m_digest.build_digest(merged)
            try:
                if _personality and hasattr(_personality, "quip"):
                    msg2 += f"\n\n{_personality.quip(ACTIVE_PERSONA)}"
            except Exception:
                pass
            send_message("Digest", msg2, priority=pr)
        else:
            send_message("Digest", "Digest module unavailable.")
        return True

    if ncmd in ("dns",):
        text, _ = _try_call(m_tech, "handle_dns_command", "dns")
        send_message("DNS Status", text or "No data.")
        return True

    if ncmd in ("kuma", "uptime", "monitor"):
        text, _ = _try_call(m_kuma, "handle_kuma_command", "kuma")
        send_message("Uptime Kuma", text or "No data.")
        return True

    if ncmd in ("weather", "now", "today", "temp", "temps"):
        text = ""
        if m_weather and hasattr(m_weather, "handle_weather_command"):
            try:
                text = m_weather.handle_weather_command("weather")
                if isinstance(text, tuple): text = text[0]
            except Exception as e:
                text = f"⚠️ Weather failed: {e}"
        send_message("Weather", text or "No data.")
        return True

    if ncmd in ("forecast", "weekly", "7day", "7-day", "7 day"):
        text = ""
        if m_weather and hasattr(m_weather, "handle_weather_command"):
            try:
                text = m_weather.handle_weather_command("forecast")
                if isinstance(text, tuple): text = text[0]
            except Exception as e:
                text = f"⚠️ Forecast failed: {e}"
        send_message("Forecast", text or "No data.")
        return True

    if ncmd in ("joke", "pun", "tell me a joke", "make me laugh", "chat"):
        if m_chat and hasattr(m_chat, "handle_chat_command"):
            try:
                msg, _ = m_chat.handle_chat_command("joke")
            except Exception as e:
                msg = f"⚠️ Chat error: {e}"
            send_message("Joke", msg or "No joke available right now.")
        else:
            send_message("Joke", "Chat engine unavailable.")
        return True

    if ncmd in ("upcoming movies", "upcoming films", "movies upcoming", "films upcoming"):
        msg, _ = _try_call(m_arr, "upcoming_movies", 7)
        send_message("Upcoming Movies", msg or "No data.")
        return True
    if ncmd in ("upcoming series", "upcoming shows", "series upcoming", "shows upcoming"):
        msg, _ = _try_call(m_arr, "upcoming_series", 7)
        send_message("Upcoming Episodes", msg or "No data.")
        return True
    if ncmd in ("movie count", "film count"):
        msg, _ = _try_call(m_arr, "movie_count")
        send_message("Movie Count", msg or "No data.")
        return True
    if ncmd in ("series count", "show count"):
        msg, _ = _try_call(m_arr, "series_count")
        send_message("Series Count", msg or "No data.")
        return True
    if ncmd in ("longest movie", "longest film"):
        msg, _ = _try_call(m_arr, "longest_movie")
        send_message("Longest Movie", msg or "No data.")
        return True
    if ncmd in ("longest series", "longest show"):
        msg, _ = _try_call(m_arr, "longest_series")
        send_message("Longest Series", msg or "No data.")
        return True

    return False

# ============================
# Dedup + intake fan-in
# ============================
_recent_hashes: dict = {}
_RECENT_TTL = 90

def _gc_recent():
    now = time.time()
    for k, exp in list(_recent_hashes.items()):
        if exp <= now:
            _recent_hashes.pop(k, None)

def _seen_recent(title: str, body: str, source: str, orig_id: Optional[str]) -> bool:
    _gc_recent()
    h = hashlib.sha256(f"{source}|{orig_id}|{title}|{body}".encode("utf-8")).hexdigest()
    if h in _recent_hashes:
        return True
    _recent_hashes[h] = time.time() + _RECENT_TTL
    return False

def _process_incoming(title: str, body: str, source: str = "intake", original_id: Optional[str] = None, priority: int = 5):
    if _seen_recent(title or "", body or "", source, original_id or ""):
        return

    ncmd = normalize_cmd(extract_command_from(title, body))
    if ncmd and _handle_command(ncmd):
        try:
            if source == "gotify" and original_id:
                _purge_after(int(original_id))
        except Exception:
            pass
        return

    final, extras, used_llm, used_beautify = _llm_then_beautify(title or "Notification", body or "")
    send_message(title or "Notification", final, priority=priority, extras=extras)

    try:
        if source == "gotify" and original_id:
            _purge_after(int(original_id))
    except Exception:
        pass
# ============================
# Gotify WebSocket intake
# ============================
async def listen_gotify():
    if not (INGEST_GOTIFY_ENABLED and GOTIFY_URL and CLIENT_TOKEN):
        print("[bot] Gotify intake disabled or not configured")
        return
    ws_url = GOTIFY_URL.replace("http://","ws://").replace("https://","wss://") + f"/stream?token={CLIENT_TOKEN}"
    print(f"[bot] Gotify intake connecting to {ws_url}")
    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10, close_timeout=5) as ws:
                async for raw in ws:
                    try:
                        data = json.loads(raw)
                        if _is_our_post(data):
                            continue
                        msg_id = data.get("id")
                        title = data.get("title") or ""
                        message = data.get("message") or ""
                        _process_incoming(title, message, source="gotify", original_id=str(msg_id), priority=int(data.get("priority", 5)))
                    except Exception as ie:
                        print(f"[bot] gotify intake msg err: {ie}")
        except Exception as e:
            print(f"[bot] gotify listen loop err: {e}")
            await asyncio.sleep(3)

# ============================
# Schedulers
# ============================
_last_digest_date = None
_last_joke_ts = 0
_joke_day = None
_joke_daily_count = 0

def _within_quiet_hours(now_hm: str, quiet: str) -> bool:
    # quiet like "23:00-06:00" (overnight window supported)
    try:
        start, end = [s.strip() for s in quiet.split("-", 1)]
        if start <= end:
            return start <= now_hm <= end
        # overnight wrap
        return (now_hm >= start) or (now_hm <= end)
    except Exception:
        return False

def _jittered_interval(base_min: int, pct: int) -> int:
    import random
    if pct <= 0: return base_min * 60
    jitter = int(base_min * pct / 100)
    return (base_min + random.randint(-jitter, jitter)) * 60

async def _digest_scheduler_loop():
    global _last_digest_date
    from datetime import datetime
    while True:
        try:
            if merged.get("digest_enabled"):
                target = str(merged.get("digest_time", "08:00")).strip()
                now = datetime.now()
                if now.strftime("%H:%M") == target and _last_digest_date != now.date():
                    try:
                        import digest as _digest_mod
                        if hasattr(_digest_mod, "build_digest"):
                            title, msg, pr = _digest_mod.build_digest(merged)
                            send_message("Digest", msg, priority=pr)
                        _last_digest_date = now.date()
                    except Exception as e:
                        print(f"[Scheduler] digest error: {e}")
                        _last_digest_date = now.date()
        except Exception as e:
            print(f"[Scheduler] loop error: {e}")
        await asyncio.sleep(60)

async def _joke_scheduler_loop():
    # Random riffs with anti-spam + quiet hours + daily cap
    global _last_joke_ts, _joke_day, _joke_daily_count
    from datetime import datetime
    while True:
        try:
            if not merged.get("chat_enabled", False):
                await asyncio.sleep(60); continue

            try:
                m_chat = __import__("chat")
            except Exception:
                m_chat = None

            if not (m_chat and hasattr(m_chat, "handle_chat_command")):
                await asyncio.sleep(60); continue

            now = time.time()
            nowdt = datetime.now()
            hm = nowdt.strftime("%H:%M")

            qh = str(merged.get("personality_quiet_hours", "23:00-06:00")).strip()
            if _within_quiet_hours(hm, qh):
                await asyncio.sleep(60); continue

            base_min = int(merged.get("personality_min_interval_minutes", 90))
            pct = int(merged.get("personality_interval_jitter_pct", 20))
            min_gap = _jittered_interval(base_min, pct)

            # daily cap
            day = nowdt.strftime("%Y-%m-%d")
            if _joke_day != day:
                _joke_day = day
                _joke_daily_count = 0
            daily_max = int(merged.get("personality_daily_max", 6))
            if _joke_daily_count >= daily_max:
                await asyncio.sleep(60); continue

            if (now - _last_joke_ts) >= min_gap:
                try:
                    msg, _ = m_chat.handle_chat_command("joke")
                except Exception as e:
                    msg = f"⚠️ Chat error: {e}"
                send_message("Joke", msg or "No joke available right now.")
                _last_joke_ts = now
                _joke_daily_count += 1
        except Exception as e:
            print(f"[Scheduler] joke error: {e}")
        await asyncio.sleep(30)

async def _heartbeat_scheduler_loop():
    # Fires on interval and within allowed time window
    from datetime import datetime
    last_sent = 0
    while True:
        try:
            if not merged.get("heartbeat_enabled", False):
                await asyncio.sleep(60); continue

            interval_s = int(merged.get("heartbeat_interval_minutes", 120)) * 60
            start_hm = str(merged.get("heartbeat_start", "06:00")).strip()
            end_hm   = str(merged.get("heartbeat_end",   "20:00")).strip()

            now = time.time()
            dt = datetime.now()
            hm = dt.strftime("%H:%M")

            # Only send within the inclusive window [start, end]
            def _within_window(hm, start, end):
                if start <= end:
                    return start <= hm <= end
                return (hm >= start) or (hm <= end)

            if (now - last_sent) >= interval_s and _within_window(hm, start_hm, end_hm):
                title, msg = ("Heartbeat", "Still alive ✅")
                if _heartbeat and hasattr(_heartbeat, "build_heartbeat"):
                    try:
                        title, msg = _heartbeat.build_heartbeat(merged)
                    except Exception as e:
                        print(f"[Heartbeat] build error: {e}")
                send_message(title, msg, priority=3, decorate=False)
                last_sent = now
        except Exception as e:
            print(f"[Scheduler] heartbeat error: {e}")
        await asyncio.sleep(30)

# ============================
# Internal HTTP server (wake + emit)
# ============================
try:
    from aiohttp import web
except Exception:
    web = None

async def _internal_wake(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    text = str(data.get("text") or "").strip()
    cmd = text
    for kw in ("jarvis", "hey jarvis", "ok jarvis"):
        if cmd.lower().startswith(kw):
            cmd = cmd[len(kw):].strip()
            break
    ok = False
    try:
        ok = bool(_handle_command(cmd))
    except Exception as e:
        try:
            send_message("Wake Error", f"{e}", priority=5)
        except Exception:
            pass
    return web.json_response({"ok": bool(ok)})

async def _internal_emit(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    title = str(data.get("title") or "Notification")
    body  = str(data.get("body") or "")
    prio  = int(data.get("priority", 5))
    source = str(data.get("source") or "internal")
    oid = str(data.get("id") or "")
    try:
        _process_incoming(title, body, source=source, original_id=oid, priority=prio)
        return web.json_response({"ok": True})
    except Exception as e:
        print(f"[bot] internal emit error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

# ---- AegisOps inbox bridge (new) ----
async def _internal_aegisops(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    title = str(data.get("title") or "AegisOps")
    message = str(data.get("message") or "")
    prio = int(data.get("priority", 5))
    status = str(data.get("status") or "")
    target = str(data.get("target") or "")
    # Compose a simple body that includes status/target if provided
    body_lines = []
    if status:
        body_lines.append(f"status: {status}")
    if target:
        body_lines.append(f"target: {target}")
    if message:
        body_lines.append(message)
    body_text = "\n".join(body_lines) if body_lines else ""
    try:
        # decorate=False so we preserve raw content for inbox
        send_message(title, body_text, priority=prio, decorate=False)
        return web.json_response({"ok": True})
    except Exception as e:
        print(f"[bot] internal aegisops error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def _start_internal_server():
    if web is None:
        print("[bot] aiohttp not available; internal server disabled")
        return
    try:
        app = web.Application()
        app.router.add_post("/internal/wake", _internal_wake)
        app.router.add_post("/internal/emit", _internal_emit)
        app.router.add_post("/internal/aegisops", _internal_aegisops)  # NEW route for AegisOps notifications
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 2599)
        await site.start()
        print("[bot] internal server listening on 127.0.0.1:2599 (/internal/wake, /internal/emit)")
        print("[bot] AegisOps endpoint active at /internal/aegisops")  # additive info line
    except Exception as e:
        print(f"[bot] failed to start internal server: {e}")

# ============================
# Apprise watchdog (sidecar must bind :2591)
# ============================
async def _apprise_watchdog():
    if not (INTAKE_APPRISE_ENABLED and INGEST_APPRISE_ENABLED):
        return
    # wait for internal server to be ready first
    for _ in range(100):
        if _port_in_use("127.0.0.1", 2599):
            break
        await asyncio.sleep(0.1)
    attempt = 0
    while True:
        try:
            if _port_in_use("127.0.0.1", int(INTAKE_APPRISE_PORT)) or _port_in_use("0.0.0.0", int(INTAKE_APPRISE_PORT)):
                # healthy
                await asyncio.sleep(5)
                continue
            attempt += 1
            env = _apprise_env()
            safe_env_print = {
                "INTAKE_APPRISE_BIND": env.get("INTAKE_APPRISE_BIND"),
                "INTAKE_APPRISE_PORT": env.get("INTAKE_APPRISE_PORT"),
                "INTAKE_APPRISE_ACCEPT_ANY_KEY": env.get("INTAKE_APPRISE_ACCEPT_ANY_KEY"),
                "INTAKE_APPRISE_ALLOWED_KEYS": env.get("INTAKE_APPRISE_ALLOWED_KEYS"),
                "JARVIS_INTERNAL_EMIT_URL": env.get("JARVIS_INTERNAL_EMIT_URL")
            }
            print(f"[bot] apprise watchdog: port {INTAKE_APPRISE_PORT} not listening, restart #{attempt} with env {safe_env_print}")
            _start_sidecar(["python3", "/app/apprise.py"], "apprise.py", env=env)
            # Give it a short grace to bind
            for _ in range(30):
                if _port_in_use("127.0.0.1", int(INTAKE_APPRISE_PORT)) or _port_in_use("0.0.0.0", int(INTAKE_APPRISE_PORT)):
                    print(f"[bot] apprise watchdog: sidecar is now listening on {INTAKE_APPRISE_BIND}:{INTAKE_APPRISE_PORT}")
                    break
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"[bot] apprise watchdog error: {e}")
        await asyncio.sleep(5)

# ============================
# EnviroGuard (inline): poll ambient temp (Open-Meteo) and adjust LLM profile
# ============================
def _enviroguard_profile_for(temp_c: float, last_profile: str) -> str:
    hot = int(ENVGUARD["hot_c"]); cold = int(ENVGUARD["cold_c"]); hyst = int(ENVGUARD["hyst_c"])
    lp = (last_profile or "normal").lower()
    # Hysteresis bands
    if lp == "hot":
        if temp_c <= hot - hyst: return "normal"
        return "hot"
    if lp == "cold":
        if temp_c >= cold + hyst: return "normal"
        return "cold"
    # normal baseline
    if temp_c >= hot: return "hot"
    if temp_c <= cold: return "cold"
    # allow manual override via options at any time
    if "manual" in (ENVGUARD.get("profiles") or {}):
        pass
    return "normal"

def _enviroguard_apply(profile: str) -> None:
    """Apply profile to merged LLM knobs so the rest of the app sees them immediately."""
    p = (ENVGUARD.get("profiles") or {}).get(profile) or {}
    cpu = int(p.get("cpu_percent", merged.get("llm_max_cpu_percent", 80)))
    ctx = int(p.get("ctx_tokens",  merged.get("llm_ctx_tokens", 4096)))
    tout= int(p.get("timeout_seconds", merged.get("llm_timeout_seconds", 20)))
    merged["llm_max_cpu_percent"] = cpu
    merged["llm_ctx_tokens"] = ctx
    merged["llm_timeout_seconds"] = tout
    # also reflect env for sidecars that consult it
    os.environ["LLM_MAX_CPU_PERCENT"] = str(cpu)
    os.environ["LLM_CTX_TOKENS"] = str(ctx)
    os.environ["LLM_TIMEOUT_SECONDS"] = str(tout)

def _enviroguard_get_temp() -> Optional[float]:
    """Use Open-Meteo like weather.py (no new deps)."""
    if not bool(merged.get("weather_enabled", True)):
        return None
    lat = merged.get("weather_lat", -26.2041)
    lon = merged.get("weather_lon", 28.0473)
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current_weather=true&temperature_unit=celsius"
        )
        r = requests.get(url, timeout=8)
        if not r.ok:
            return None
        j = r.json() or {}
        cw = j.get("current_weather") or {}
        t = cw.get("temperature")
        if isinstance(t, (int, float)):
            return float(t)
    except Exception:
        return None
    return None

async def _enviroguard_loop():
    """Periodic poll → compute profile → apply (with change notifications)."""
    if not ENVGUARD.get("enabled"):
        return
    # initial apply from whatever profile is set
    _enviroguard_apply(ENVGUARD.get("profile","normal"))
    poll = max(1, int(ENVGUARD.get("poll_minutes", 30)))
    while True:
        try:
            t = _enviroguard_get_temp()
            if t is not None:
                last = ENVGUARD.get("profile","normal")
                prof = _enviroguard_profile_for(t, last)
                changed = (prof != last)
                ENVGUARD.update({"temp_c": round(float(t), 1), "profile": prof, "last_ts": int(time.time())})
                if changed:
                    _enviroguard_apply(prof)
                    try:
                        send_message(
                            "EnviroGuard",
                            f"Ambient {t:.1f}°C → profile **{prof.upper()}** (CPU={merged.get('llm_max_cpu_percent')}%, ctx={merged.get('llm_ctx_tokens')}, to={merged.get('llm_timeout_seconds')}s)",
                            priority=4,
                            decorate=False
                        )
                    except Exception:
                        pass
            # else: keep last profile
        except Exception as e:
            print(f"[EnviroGuard] loop error: {e}")
        await asyncio.sleep(poll * 60)

# ============================
# Main / loop
# ============================
def main():
    resolve_app_id()
    try:
        start_sidecars()
        post_startup_card()
    except Exception as e:
        print(f"[bot] startup err: {e}")
    asyncio.run(_run_forever())

async def _run_forever():
    try:
        asyncio.create_task(_start_internal_server())
    except Exception:
        pass
    asyncio.create_task(_digest_scheduler_loop())
    asyncio.create_task(listen_gotify())
    asyncio.create_task(_apprise_watchdog())
    asyncio.create_task(_joke_scheduler_loop())       # <— NEW
    asyncio.create_task(_heartbeat_scheduler_loop())  # <— NEW
    # EnviroGuard background loop (only runs if enabled)
    asyncio.create_task(_enviroguard_loop())
    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    main()
