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

# --- ADDITIVE: import for persona switching ---
from personality_state import set_active_persona
# --- end additive ---

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
_enviroguard = _load_module("enviroguard", "/app/enviroguard.py")  # <— NEW: external EnviroGuard

ACTIVE_PERSONA, PERSONA_TOD = "neutral", ""
if _pstate and hasattr(_pstate, "get_active_persona"):
    try:
        ACTIVE_PERSONA, PERSONA_TOD = _pstate.get_active_persona()
    except Exception:
        pass

# --- ADDITIVE: persona wakeword detection ---
def _detect_wakeword(msg: str) -> Optional[str]:
    m = (msg or "").lower()
    if "jarvis tappit" in m or "jarvis welkom" in m or "fok" in m:
        return "tappit"
    if "jarvis nerd" in m:
        return "nerd"
    if "jarvis dude" in m:
        return "dude"
    if "jarvis chick" in m:
        return "chick"
    if "jarvis rager" in m:
        return "rager"
    if "jarvis comedian" in m:
        return "comedian"
    if "jarvis action" in m:
        return "action"
    if "jarvis default" in m or "jarvis ops" in m:
        return "ops"
    return None
# --- end additive ---

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

# --- ADDITIVE: bypass list + helper for chat.py payloads ---
_CHAT_BYPASS_TITLES = {"Joke", "Quip", "Weird Fact"}
def _should_bypass_decor(title: str, extras=None) -> bool:
    try:
        if title in _CHAT_BYPASS_TITLES:
            return True
        if isinstance(extras, dict) and extras.get("bypass_beautify") is True:
            return True
    except Exception:
        pass
    return False
# --- end additive ---

def _persona_line(quip_text: str) -> str:
    who = ACTIVE_PERSONA or "neutral"
    quip_text = (quip_text or "").strip().replace("\n", " ")
    if len(quip_text) > 140:
        quip_text = quip_text[:137] + "..."
    return f"💬 {who} says: {quip_text}" if quip_text else f"💬 {who} says:"

def send_message(title, message, priority=5, extras=None, decorate=True):
    orig_title = title

    # --- ADDITIVE: auto-bypass for chat.py jokes/quip/weirdfacts ---
    _bypass = _should_bypass_decor(orig_title, extras)
    if _bypass:
        decorate = False
    # --- end additive ---

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

    # --- PATCH: build dynamic persona header using Lexi via personality.persona_header() ---
    try:
        if _personality and hasattr(_personality, "persona_header"):
            header = _personality.persona_header(ACTIVE_PERSONA)
        else:
            header = _persona_line(quip_text)
    except Exception:
        header = _persona_line(quip_text)
    # --- end patch ---

    # --- ADDITIVE: don't prepend persona header when bypassing ---
    if not _bypass:
        message = (header + ("\n" + (message or ""))) if header else (message or "")
    else:
        message = message or ""
    # --- end additive ---

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

    # --- ADDITIVE: bypass beautifier entirely for chat.py payloads by title ---
    if title in _CHAT_BYPASS_TITLES:
        final = message or ""
        extras = None
        used_beautify = False
        # No footer either; return as-is
        return final, extras, used_llm, used_beautify
    # --- end additive ---

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

def _env_status_line() -> str:
    """Builds a single-line EnviroGuard status for the boot card."""
    try:
        if not bool(merged.get("llm_enviroguard_enabled", False)):
            return "🌡️ EnviroGuard — OFF"
        prof = ""
        temp_s = ""
        if _enviroguard:
            # Try common getters; fall back to attributes
            if hasattr(_enviroguard, "get_current_profile"):
                try: prof = _enviroguard.get_current_profile() or ""
                except Exception: prof = ""
            elif hasattr(_enviroguard, "state"):
                try: prof = ((_enviroguard.state or {}) if isinstance(_enviroguard.state, dict) else {}).get("profile","")
                except Exception: prof = ""
            if hasattr(_enviroguard, "get_last_temperature_c"):
                try:
                    t = _enviroguard.get_last_temperature_c()
                    if isinstance(t, (int, float)):
                        temp_s = f", {float(t):.1f} °C"
                except Exception:
                    temp_s = ""
        return f"🌡️ EnviroGuard — ACTIVE" + (f" (profile={prof}{temp_s})" if prof else "")
    except Exception:
        return "🌡️ EnviroGuard — ACTIVE"

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
        _env_status_line(),
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

# … command handlers are above (digest, dns, kuma, weather, jokes, etc.) …

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
    # wakeword handling … (unchanged) …
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
# Internal HTTP server (wake + emit)
# ============================
try:
    from aiohttp import web
except Exception:
    web = None

async def _internal_wake(request):
    # … unchanged …
    return web.json_response({"ok": bool(ok)})

async def _internal_emit(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    title = str(data.get("title") or "Notification")
    # --- FIX: accept both body and message keys ---
    body  = str(data.get("body") or data.get("message") or "")
    prio  = int(data.get("priority", 5))
    source = str(data.get("source") or "internal")
    oid = str(data.get("id") or "")
    # --- FIX: dedup anti-burst guard for chat.py categories ---
    if title in _CHAT_BYPASS_TITLES and _seen_recent(title, body, source, oid):
        return web.json_response({"ok": True, "deduped": True})
    try:
        _process_incoming(title, body, source=source, original_id=oid, priority=prio)
        return web.json_response({"ok": True})
    except Exception as e:
        print(f"[bot] internal emit error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

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
    # --- FIX: prevent double personality/joke loops ---
    if not merged.get("personality_enabled", False):
        asyncio.create_task(_joke_scheduler_loop())
    asyncio.create_task(_heartbeat_scheduler_loop())
    # EnviroGuard background startup …
    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    main()