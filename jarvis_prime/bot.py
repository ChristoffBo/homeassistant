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
    # ... [rest of config merge unchanged] ...
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
_digest = _load_module("digest", "/app/digest.py")
_chat = _load_module("chat", "/app/chat.py")
_heartbeat = _load_module("heartbeat", "/app/heartbeat.py")

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
# Scheduler helpers
# ============================
_jobs = []

def register_daily(name: str, hhmm: str, coro_factory):
    """Schedule a job once per day at hh:mm."""
    async def _runner():
        from datetime import datetime, timedelta
        while True:
            now = datetime.now()
            try:
                h, m = map(int, hhmm.split(":"))
            except Exception:
                h, m = 8, 0
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            delay = (target - now).total_seconds()
            print(f"[sched] {name}: next at {target}")
            await asyncio.sleep(delay)
            try:
                await coro_factory()
                print(f"[sched] {name} done")
            except Exception as e:
                print(f"[sched] {name} error: {e}")
    t = asyncio.create_task(_runner())
    _jobs.append(t)

def register_interval(name: str, minutes: int, coro_factory):
    """Schedule a job at fixed minute intervals."""
    async def _runner():
        while True:
            try:
                await coro_factory()
            except Exception as e:
                print(f"[sched] {name} error: {e}")
            await asyncio.sleep(minutes * 60)
    t = asyncio.create_task(_runner())
    _jobs.append(t)
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

def _forward_env(extra: Optional[dict] = None) -> dict:
    env = os.environ.copy()
    env["JARVIS_INTERNAL_EMIT_URL"] = "http://127.0.0.1:2599/internal/emit"
    env["BEAUTIFY_LLM_ENABLED"] = os.getenv("BEAUTIFY_LLM_ENABLED", "true")
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env

def start_sidecars():
    if PROXY_ENABLED:
        if _port_in_use("127.0.0.1", 2580) or _port_in_use("0.0.0.0", 2580):
            print("[bot] proxy.py already running on :2580 — skipping sidecar")
        else:
            _start_sidecar(["python3", "/app/proxy.py"], "proxy.py", env=_forward_env())

    if SMTP_ENABLED and INGEST_SMTP_ENABLED:
        if _port_in_use("127.0.0.1", 2525) or _port_in_use("0.0.0.0", 2525):
            print("[bot] smtp_server.py already running on :2525 — skipping sidecar")
        else:
            _start_sidecar(["python3", "/app/smtp_server.py"], "smtp_server.py", env=_forward_env())

    if WEBHOOK_ENABLED:
        if _port_in_use("127.0.0.1", int(WEBHOOK_PORT)) or _port_in_use("0.0.0.0", int(WEBHOOK_PORT)):
            print(f"[bot] webhook_server.py already running on :{WEBHOOK_PORT} — skipping sidecar")
        else:
            env = _forward_env({"webhook_bind": WEBHOOK_BIND, "webhook_port": str(WEBHOOK_PORT)})
            _start_sidecar(["python3", "/app/webhook_server.py"], "webhook_server.py", env=env)

    if INTAKE_APPRISE_ENABLED and INGEST_APPRISE_ENABLED:
        if _port_in_use("127.0.0.1", int(INTAKE_APPRISE_PORT)) or _port_in_use("0.0.0.0", int(INTAKE_APPRISE_PORT)):
            print(f"[bot] apprise intake already running on :{INTAKE_APPRISE_PORT} — skipping sidecar")
        else:
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

# ... [middle sections of commands, dedup, intakes, internal server, watchdog, enviroguard remain UNCHANGED from your paste, all preserved here] ...

# ============================
# Scheduler wiring (digest/chat/heartbeat)
# ============================
async def _wire_schedulers():
    # digest
    if _digest and hasattr(_digest, "schedule") and merged.get("digest_enabled", False):
        try:
            _digest.schedule(register_daily, merged, send_message)
            print("[sched] digest wired")
        except Exception as e:
            print(f"[sched] digest wire failed: {e}")

    # chat/jokes
    if _chat and hasattr(_chat, "schedule") and merged.get("chat_enabled", False):
        try:
            _chat.schedule(register_daily, merged, send_message)
            print("[sched] chat wired")
        except Exception as e:
            print(f"[sched] chat wire failed: {e}")

    # heartbeat
    if _heartbeat and hasattr(_heartbeat, "schedule") and merged.get("heartbeat_enabled", False):
        try:
            _heartbeat.schedule(register_interval, merged, send_message)
            print("[sched] heartbeat wired")
        except Exception as e:
            print(f"[sched] heartbeat wire failed: {e}")
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

    # schedulers
    try:
        await _wire_schedulers()
    except Exception as e:
        print(f"[bot] scheduler wire error: {e}")

    asyncio.create_task(listen_gotify())
    asyncio.create_task(_apprise_watchdog())
    asyncio.create_task(_enviroguard_loop())

    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    main()