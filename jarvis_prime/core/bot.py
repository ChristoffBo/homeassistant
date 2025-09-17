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

import re as _re_local, time as _time_local

_JUNK_LINE_RE = _re_local.compile(
    r'^\s*(Tone:|Context\s*\(|No\s+lists|No\s+numbers|No\s+JSON|No\s+labels)\b',
    _re_local.I
)

def _clean_payload(_s: str) -> str:
    if not _s:
        return ""
    s = _s.replace("\r", "").strip()
    # remove instruction/meta lines
    s = "\n".join(ln for ln in s.split("\n") if not _JUNK_LINE_RE.search(ln))
    # remove raw [poster](http...) lines (these should render as images separately if needed)
    s = "\n".join(ln for ln in s.split("\n") if not _re_local.search(r'\[poster\]\(https?://', ln, _re_local.I))
    # fix stray **http(s):** markdown artifacts
    s = _re_local.sub(r'\*+(https?://)', r'\1', s)
    # collapse excessive blank lines
    s = _re_local.sub(r'\n{3,}', '\n\n', s)
    return s.strip()

def _sanitize_riff(txt: str) -> str:
    """Keep riffs short and free of instruction lines; never let them pollute payload."""
    if not txt:
        return ""
    # strip instruction-ish lines and trim to 3 lines / 360 chars
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip() and not _JUNK_LINE_RE.search(ln)]
    out = "\n".join(lines[:3])[:360].rstrip()
    return out

def _append_riff_safe(base: str, context: str, timeout_s: int = 12) -> str:
    """
    Calls llm_client.riff_once(context, timeout_s) and appends as a quoted block
    only if a valid short riff is returned. If it fails/times out, returns base unchanged.
    """
    try:
        from llm_client import riff_once  # must return str|None
    except Exception:
        return base
    try:
        cand = riff_once(context=context or "", timeout_s=timeout_s)
        riff = _sanitize_riff(cand or "")
        if riff:
            return f"{base}\n\n> " + riff.replace("\n", "\n> ")
    except Exception:
        pass
    return base
# === /ADDITIVE ===


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

def send_message(title: str, message: str, priority: int = 1, decorate: bool = True, extras=None):
    global jarvis_app_id
    try:
        if not GOTIFY_URL or not CLIENT_TOKEN:
            print(f"[bot] no GOTIFY_URL/CLIENT_TOKEN set, cannot send {title}")
            return

        # --- ADDITIVE: skip decorate for chat.py payloads ---
        if _should_bypass_decor(title, extras):
            decorate = False
        # --- end additive ---

        final_msg = message
        if decorate and _beautify and hasattr(_beautify, "beautify_message"):
            try:
                final_msg = _beautify.beautify_message(title, message, persona=ACTIVE_PERSONA)
            except Exception as e:
                print(f"[bot] beautify failed: {e}")

        headers = {"X-Gotify-Key": CLIENT_TOKEN, "Content-Type": "application/json"}
        payload = {
            "title": f"{BOT_ICON} {BOT_NAME}: {title}",
            "message": final_msg,
            "priority": priority
        }
        if extras:
            payload.update(extras)

        r = requests.post(f"{GOTIFY_URL}/message", headers=headers, data=json.dumps(payload), timeout=10)
        if r.status_code != 200:
            print(f"[bot] gotify send failed: {r.status_code} {r.text}")
    except Exception as e:
        print(f"[bot] send_message exception: {e}")

def _send_digest_card(items: List[dict]):
    if not items:
        return
    try:
        lines = []
        for it in items:
            lines.append(f"• {it.get('title','?')} @ {it.get('ts','')}")
        msg = "\n".join(lines)
        send_message("Digest", msg, priority=3)
    except Exception as e:
        print(f"[bot] digest send failed: {e}")
# ============================
# Schedulers
# ============================
async def _heartbeat_scheduler_loop():
    """Heartbeat scheduler: runs build_heartbeat on interval."""
    try:
        interval_min = int(merged.get("heartbeat_interval_minutes", 120))
    except Exception:
        interval_min = 120
    if interval_min < 1: interval_min = 1

    while True:
        try:
            if bool(merged.get("heartbeat_enabled", False)):
                if _heartbeat and hasattr(_heartbeat, "build_heartbeat"):
                    title, msg = _heartbeat.build_heartbeat(merged)
                    send_message(title, msg, priority=3, decorate=False)
        except Exception as e:
            print(f"[bot] heartbeat loop error: {e}")
        await asyncio.sleep(interval_min * 60)
async def _joke_scheduler_loop():
    """Personality/Joke/Fact scheduler."""
    try:
        min_m = int(merged.get("personality_min_interval_minutes", 90))
    except Exception:
        min_m = 90
    if min_m < 1:
        min_m = 1

    jitter = int((min_m * int(merged.get("personality_interval_jitter_pct", 20))) / 100)
    if jitter < 0: jitter = 0

    while True:
        try:
            if merged.get("personality_enabled", False):
                # === PATCHED ===
                # Previously: could trigger multiple categories back-to-back
                # Now: _personality._post_one() enforces one line per interval
                if _personality and hasattr(_personality, "_post_one"):
                    _personality._post_one()
        except Exception as e:
            print(f"[bot] joke loop error: {e}")

        wait_m = max(1, min_m + random.randint(-jitter, jitter))
        await asyncio.sleep(wait_m * 60)

async def _digest_scheduler_loop():
    """Digest scheduler: periodically flushes buffered items."""
    try:
        interval_min = int(merged.get("digest_interval_minutes", 180))
    except Exception:
        interval_min = 180
    if interval_min < 1: interval_min = 1

    while True:
        try:
            if merged.get("digest_enabled", False):
                if _digest and hasattr(_digest, "flush_digest"):
                    items = _digest.flush_digest()
                    if items:
                        _send_digest_card(items)
        except Exception as e:
            print(f"[bot] digest loop error: {e}")
        await asyncio.sleep(interval_min * 60)

# ============================
# Main Entrypoint
# ============================
async def main():
    global merged
    merged = load_options()

    tasks = []

    # Heartbeat
    if merged.get("heartbeat_enabled", False):
        tasks.append(asyncio.create_task(_heartbeat_scheduler_loop()))

    # Personality/Jokes
    if merged.get("personality_enabled", False):
        tasks.append(asyncio.create_task(_joke_scheduler_loop()))

    # Digest
    if merged.get("digest_enabled", False):
        tasks.append(asyncio.create_task(_digest_scheduler_loop()))

    # Main loop never exits
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[bot] stopped by user")