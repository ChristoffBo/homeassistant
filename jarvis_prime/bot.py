#!/usr/bin/env python3
# /app/bot.py
#
# Jarvis Prime — Standalone Orchestrator
# FULL REWRITE FROM SCRATCH (Apprise is a real sidecar; no Gotify intake; single choke-point; wake-words everywhere)
#
# Architecture
# ───────────
# INTakes  : Any producer (Apprise sidecar, SMTP sidecar, Webhook sidecar, Proxy sidecar, future intakes)
#            must POST JSON to 127.0.0.1:2599/internal/ingest  →  { title, body/message, priority, extras }
# WAKEWORD : Works from ANY intake (title/body beginning with “jarvis …”), or direct POST to /internal/wake {"text":"jarvis ..."}
# CORE     : ONE choke-point `process_and_send()` → persona quip → (optional) LLM rewrite → (conditional) persona riffs via beautify
# RIFFS    : Fire ONLY when BOTH are true:
#              - "llm_enabled": true
#              - "llm_persona_riffs_enabled": true   (exported to env as BEAUTIFY_LLM_ENABLED="true")
# OUTPUTS  : Fan-out to Gotify, ntfy, SMTP (optional; no loops because there’s no output listener)
# STARTUP  : Clear boot screen/status card
# STABILITY: In-memory dedup ring to prevent storms; no websocket listeners; port-guarded sidecars
#
# Sidecars launched (if enabled & port free):
#   /app/proxy.py
#   /app/smtp_server.py
#   /app/webhook_server.py
#   /app/apprise_server.py   ← Apprise is a REAL SIDECAR (not embedded)
#
# Config precedence: /data/options.json overrides /data/config.json; env provides defaults.

import os
import sys
import json
import asyncio
import re
import subprocess
import atexit
import time
import socket
import hashlib
import signal
from typing import List, Optional, Dict, Any

# ============================
# Optional storage (Inbox mirror)
# ============================
try:
    import storage  # /app/storage.py (optional)
    storage.init_db()
except Exception as _e:
    storage = None
    print(f"[bot] ⚠️ storage init failed: {_e}", flush=True)

# ============================
# Defaults / env
# ============================
BOT_NAME  = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON  = os.getenv("BOT_ICON", "🧠")

# Optional OUTPUTS (fan-out) – no intake is hardwired to these
GOTIFY_URL       = (os.getenv("GOTIFY_URL", "") or "").rstrip("/")
GOTIFY_APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN", "")
NTFY_URL         = (os.getenv("NTFY_URL", "") or "").rstrip("/")
NTFY_TOPIC       = os.getenv("NTFY_TOPIC", "")

# Feature toggles (env defaults; overridable by options/config)
RADARR_ENABLED     = os.getenv("radarr_enabled", "false").lower() in ("1","true","yes")
SONARR_ENABLED     = os.getenv("sonarr_enabled", "false").lower() in ("1","true","yes")
WEATHER_ENABLED    = os.getenv("weather_enabled", "false").lower() in ("1","true","yes")
CHAT_ENABLED_ENV   = os.getenv("chat_enabled", "false").lower() in ("1","true","yes")
DIGEST_ENABLED_ENV = os.getenv("digest_enabled", "false").lower() in ("1","true","yes")
TECHNITIUM_ENABLED = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")
KUMA_ENABLED       = os.getenv("uptimekuma_enabled", "false").lower() in ("1","true","yes")

# Sidecars (external servers that must forward into /internal/ingest)
SMTP_ENABLED_ENV   = os.getenv("smtp_enabled", "false").lower() in ("1","true","yes")
PROXY_ENABLED_ENV  = os.getenv("proxy_enabled", "false").lower() in ("1","true","yes")

WEBHOOK_ENABLED    = os.getenv("webhook_enabled", "false").lower() in ("1","true","yes")
WEBHOOK_BIND       = os.getenv("webhook_bind", "0.0.0.0")
WEBHOOK_PORT       = int(os.getenv("webhook_port", "2590"))

# Apprise sidecar (REAL sidecar)
INTAKE_APPRISE_ENABLED = os.getenv("intake_apprise_enabled", "false").lower() in ("1","true","yes")
INTAKE_APPRISE_TOKEN = os.getenv("intake_apprise_token", "")
INTAKE_APPRISE_ACCEPT_ANY_KEY = os.getenv("intake_apprise_accept_any_key", "true").lower() in ("1","true","yes")
INTAKE_APPRISE_ALLOWED_KEYS = [k for k in os.getenv("intake_apprise_allowed_keys", "").split(",") if k.strip()]
INTAKE_APPRISE_PORT = int(os.getenv("intake_apprise_port", "2591"))
INTAKE_APPRISE_BIND = os.getenv("intake_apprise_bind", "0.0.0.0")

# LLM / Riffs toggles
LLM_REWRITE_ENABLED = os.getenv("LLM_REWRITE_ENABLED", "false").lower() in ("1","true","yes")
BEAUTIFY_LLM_ENABLED_ENV = os.getenv("BEAUTIFY_LLM_ENABLED", "true").lower() in ("1","true","yes")  # will be finalised by options

# Health/TCP
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "2598"))

# ============================
# Load options/config
# ============================
def _load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

merged: Dict[str, Any] = {}
try:
    options = _load_json("/data/options.json")
    fallback = _load_json("/data/config.json")
    merged = {**fallback, **options}

    # Outputs toggles/creds
    PUSH_GOTIFY_ENABLED = bool(merged.get("push_gotify_enabled", False))
    PUSH_NTFY_ENABLED   = bool(merged.get("push_ntfy_enabled", False))
    PUSH_SMTP_ENABLED   = bool(merged.get("push_smtp_enabled", False))

    GOTIFY_URL       = str(merged.get("gotify_url", GOTIFY_URL or "")).rstrip("/")
    GOTIFY_APP_TOKEN = str(merged.get("gotify_app_token", GOTIFY_APP_TOKEN or ""))
    NTFY_URL         = str(merged.get("ntfy_url", NTFY_URL or "")).rstrip("/")
    NTFY_TOPIC       = str(merged.get("ntfy_topic", NTFY_TOPIC or ""))

    SMTP_HOST = str(merged.get("push_smtp_host", ""))
    SMTP_PORT = int(merged.get("push_smtp_port", 587))
    SMTP_USER = str(merged.get("push_smtp_user", ""))
    SMTP_PASS = str(merged.get("push_smtp_pass", ""))
    SMTP_TO   = str(merged.get("push_smtp_to", ""))

    # Modules
    RADARR_ENABLED  = bool(merged.get("radarr_enabled", RADARR_ENABLED))
    SONARR_ENABLED  = bool(merged.get("sonarr_enabled", SONARR_ENABLED))
    WEATHER_ENABLED = bool(merged.get("weather_enabled", WEATHER_ENABLED))
    TECHNITIUM_ENABLED = bool(merged.get("technitium_enabled", TECHNITIUM_ENABLED))
    KUMA_ENABLED    = bool(merged.get("uptimekuma_enabled", KUMA_ENABLED))
    CHAT_ENABLED_FILE   = bool(merged.get("chat_enabled", CHAT_ENABLED_ENV))
    DIGEST_ENABLED_FILE = bool(merged.get("digest_enabled", DIGEST_ENABLED_ENV))

    # Sidecars
    SMTP_ENABLED  = bool(merged.get("smtp_enabled", SMTP_ENABLED_ENV))
    PROXY_ENABLED = bool(merged.get("proxy_enabled", PROXY_ENABLED_ENV))

    # Webhook
    WEBHOOK_ENABLED = bool(merged.get("webhook_enabled", WEBHOOK_ENABLED))
    WEBHOOK_BIND    = str(merged.get("webhook_bind", WEBHOOK_BIND))
    try:
        WEBHOOK_PORT = int(merged.get("webhook_port", WEBHOOK_PORT))
    except Exception:
        pass

    # Apprise sidecar controls
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

    # LLM riffs control (export as env for beautify)
    LLM_REWRITE_ENABLED = bool(merged.get("llm_rewrite_enabled", LLM_REWRITE_ENABLED))
    _persona_riffs_enabled = merged.get("llm_persona_riffs_enabled", BEAUTIFY_LLM_ENABLED_ENV)
    os.environ["BEAUTIFY_LLM_ENABLED"] = "true" if _persona_riffs_enabled else "false"

except Exception as _opt_e:
    SMTP_ENABLED = SMTP_ENABLED_ENV
    PROXY_ENABLED = PROXY_ENABLED_ENV
    PUSH_GOTIFY_ENABLED = False
    PUSH_NTFY_ENABLED = False
    PUSH_SMTP_ENABLED = False
    SMTP_HOST = SMTP_USER = SMTP_PASS = SMTP_TO = ""
    SMTP_PORT = 587

# ============================
# Optional modules
# ============================
def _load_module(name, path):
    try:
        import importlib.util as _imp
        spec = _imp.spec_from_file_location(name, path)
        if spec and spec.loader:
            mod = _imp.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    except Exception:
        pass
    return None

_aliases = _load_module("aliases", "/app/aliases.py")
_personality = _load_module("personality", "/app/personality.py")
_pstate = _load_module("personality_state", "/app/personality_state.py")
_beautify = _load_module("beautify", "/app/beautify.py")
_llm = _load_module("llm_client", "/app/llm_client.py")

ACTIVE_PERSONA, PERSONA_TOD = "neutral", ""
if _pstate and hasattr(_pstate, "get_active_persona"):
    try:
        ACTIVE_PERSONA, PERSONA_TOD = _pstate.get_active_persona()
    except Exception:
        pass

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
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env or os.environ.copy())
        _sidecars.append(p)
        print(f"[bot] started {label}", flush=True)
    except Exception as e:
        print(f"[bot] sidecar {label} start failed: {e}", flush=True)

def start_sidecars():
    # proxy
    if PROXY_ENABLED:
        if _port_in_use("127.0.0.1", 2580) or _port_in_use("0.0.0.0", 2580):
            print("[bot] proxy.py already running on :2580 — skipping sidecar", flush=True)
        else:
            _start_sidecar(["python3","/app/proxy.py"], "proxy.py")

    # smtp intake
    if SMTP_ENABLED:
        if _port_in_use("127.0.0.1", 2525) or _port_in_use("0.0.0.0", 2525):
            print("[bot] smtp_server.py already running on :2525 — skipping sidecar", flush=True)
        else:
            _start_sidecar(["python3","/app/smtp_server.py"], "smtp_server.py")

    # webhook intake
    if WEBHOOK_ENABLED:
        if _port_in_use("127.0.0.1", int(WEBHOOK_PORT)) or _port_in_use("0.0.0.0", int(WEBHOOK_PORT)):
            print(f"[bot] webhook_server.py already running on :{WEBHOOK_PORT} — skipping sidecar", flush=True)
        else:
            env = os.environ.copy()
            env["webhook_bind"] = WEBHOOK_BIND
            env["webhook_port"] = str(WEBHOOK_PORT)
            _start_sidecar(["python3","/app/webhook_server.py"], "webhook_server.py", env=env)

    # apprise intake (REAL sidecar)
    if INTAKE_APPRISE_ENABLED:
        env = os.environ.copy()
        env["APPRISE_BIND"] = INTAKE_APPRISE_BIND or "0.0.0.0"
        env["APPRISE_PORT"] = str(INTAKE_APPRISE_PORT)
        env["APPRISE_TOKEN"] = INTAKE_APPRISE_TOKEN or ""
        env["APPRISE_ACCEPT_ANY_KEY"] = "true" if INTAKE_APPRISE_ACCEPT_ANY_KEY else "false"
        env["APPRISE_ALLOWED_KEYS"] = ",".join(INTAKE_APPRISE_ALLOWED_KEYS or [])
        if _port_in_use("127.0.0.1", int(INTAKE_APPRISE_PORT)) or _port_in_use("0.0.0.0", int(INTAKE_APPRISE_PORT)):
            print(f"[bot] apprise_server.py already running on :{INTAKE_APPRISE_PORT} — skipping sidecar", flush=True)
        else:
            _start_sidecar(["python3","/app/apprise_server.py"], "apprise_server.py", env=env)

def stop_sidecars():
    for p in _sidecars:
        try:
            p.terminate()
        except Exception:
            pass
atexit.register(stop_sidecars)

# ============================
# Outputs (fan-out) + mirror
# ============================
def _mirror_to_storage(title: str, message: str, source: str, priority: int, extras: Optional[dict] = None):
    if not storage:
        return
    try:
        storage.save_message(
            title=title or "Notification",
            body=message or "",
            source=source,
            priority=int(priority or 5),
            extras=extras or {},
            created_at=int(time.time())
        )
    except Exception as e:
        print(f"[bot] storage save failed: {e}", flush=True)

def _send_via_gotify(title: str, message: str, priority: int = 5, extras: Optional[dict] = None) -> bool:
    if not (PUSH_GOTIFY_ENABLED and GOTIFY_URL and GOTIFY_APP_TOKEN):
        return False
    import requests
    url = f"{GOTIFY_URL}/message?token={GOTIFY_APP_TOKEN}"
    payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message or "", "priority": int(priority or 5)}
    if extras: payload["extras"] = extras
    try:
        r = requests.post(url, json=payload, timeout=8)
        r.raise_for_status()
        _mirror_to_storage(title, message, "gotify", priority, {"extras": extras or {}, "status": r.status_code})
        return True
    except Exception as e:
        print(f"[bot] gotify send error: {e}", flush=True)
        _mirror_to_storage(title, message, "gotify", priority, {"extras": extras or {}, "status": 0, "error": str(e)})
        return False

def _send_via_ntfy(title: str, message: str, priority: int = 5, extras: Optional[dict] = None) -> bool:
    if not (PUSH_NTFY_ENABLED and NTFY_URL and NTFY_TOPIC):
        return False
    import requests
    url = f"{NTFY_URL}/{NTFY_TOPIC}".rstrip("/")
    headers = {"Title": f"{BOT_ICON} {BOT_NAME}: {title}", "Priority": str(int(priority or 5))}
    try:
        r = requests.post(url, data=(message or "").encode("utf-8"), headers=headers, timeout=8)
        r.raise_for_status()
        _mirror_to_storage(title, message, "ntfy", priority, {"extras": extras or {}, "status": r.status_code})
        return True
    except Exception as e:
        print(f"[bot] ntfy send error: {e}", flush=True)
        _mirror_to_storage(title, message, "ntfy", priority, {"extras": extras or {}, "status": 0, "error": str(e)})
        return False

def _send_via_smtp(title: str, message: str, priority: int = 5, extras: Optional[dict] = None) -> bool:
    if not (PUSH_SMTP_ENABLED):
        return False
    import smtplib
    from email.mime.text import MIMEText
    try:
        body = message or ""
        msg = MIMEText(body, "html" if merged.get("smtp_allow_html", True) else "plain", "utf-8")
        msg["Subject"] = f"{BOT_ICON} {BOT_NAME}: {title}"
        msg["From"] = SMTP_USER or "jarvis@localhost"
        msg["To"] = SMTP_TO or (SMTP_USER or "root@localhost")
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=12) as s:
            s.starttls()
            if SMTP_USER and SMTP_PASS:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        _mirror_to_storage(title, message, "smtp", priority, {"extras": extras or {}, "status": 250})
        return True
    except Exception as e:
        print(f"[bot] smtp send error: {e}", flush=True)
        _mirror_to_storage(title, message, "smtp", priority, {"extras": extras or {}, "status": 0, "error": str(e)})
        return False

def send_outputs(title: str, message: str, priority: int = 5, extras: Optional[dict] = None):
    ok_any = False
    try:
        if _send_via_gotify(title, message, priority, extras): ok_any = True
    except Exception as e:
        print(f"[bot] gotify path failed: {e}", flush=True)
    try:
        if _send_via_ntfy(title, message, priority, extras): ok_any = True
    except Exception as e:
        print(f"[bot] ntfy path failed: {e}", flush=True)
    try:
        if _send_via_smtp(title, message, priority, extras): ok_any = True
    except Exception as e:
        print(f"[bot] smtp path failed: {e}", flush=True)

    if not ok_any:
        _mirror_to_storage(title, message, "mirror-only", priority, extras or {})

# ============================
# Persona + LLM / Riffs pipeline
# ============================
def _persona_line(quip_text: str) -> str:
    who = ACTIVE_PERSONA or "neutral"
    quip_text = (quip_text or "").strip().replace("\n", " ")
    if len(quip_text) > 140:
        quip_text = quip_text[:137] + "..."
    return f"💬 {who} says: {quip_text}" if quip_text else f"💬 {who} says:"

def _footer(used_llm: bool, used_beautify: bool) -> str:
    tags = []
    if used_llm: tags.append("Neural Core ✓")
    if used_beautify: tags.append("Aesthetic Engine ✓")
    if not tags: tags.append("Relay Path")
    return "— " + " · ".join(tags)

def _llm_then_beautify(title: str, message: str):
    """Optional LLM rewrite + conditional persona riffs via beautify."""
    used_llm = False
    used_beautify = False
    final = message or ""
    extras = None

    # Optional LLM rewrite path (independent switch)
    if LLM_REWRITE_ENABLED and merged.get("llm_enabled") and _llm and hasattr(_llm, "rewrite"):
        try:
            final2 = _llm.rewrite(
                text=final,
                mood=ACTIVE_PERSONA,
                timeout=int(merged.get("llm_timeout_seconds", 12)),
                cpu_limit=int(merged.get("llm_max_cpu_percent", 70)),
                models_priority=merged.get("llm_models_priority", []),
                base_url=merged.get("llm_ollama_base_url", ""),
                model_url=merged.get("llm_model_url", ""),
                model_path=merged.get("llm_model_path", ""),
                model_sha256=merged.get("llm_model_sha256", ""),
                allow_profanity=bool(merged.get("personality_allow_profanity", False))
            )
            if final2:
                final = final2
                used_llm = True
        except Exception as e:
            print(f"[bot] LLM rewrite failed (optional): {e}", flush=True)

    # Persona riffs via beautify — ONLY if llm_enabled && llm_persona_riffs_enabled
    persona_riffs_on = bool(merged.get("llm_enabled")) and str(os.getenv("BEAUTIFY_LLM_ENABLED","true")).lower() in ("1","true","yes")
    if _beautify and hasattr(_beautify, "beautify_message") and persona_riffs_on:
        try:
            final, extras = _beautify.beautify_message(
                title, final,
                mood=ACTIVE_PERSONA,
                persona=ACTIVE_PERSONA,
                persona_quip=True  # give beautify room to place overlays / riffs
            )
            used_beautify = True
        except Exception as e:
            print(f"[bot] Beautify failed: {e}", flush=True)

    # Footer tag
    foot = _footer(used_llm, used_beautify)
    if final and not final.rstrip().endswith(foot):
        final = f"{final.rstrip()}\n\n{foot}"

    return final, extras, used_llm, used_beautify

def process_and_send(title: str, message: str, priority: int = 5, extras: Optional[dict] = None):
    """Single choke-point for ALL messages."""
    # Persona quip header (always)
    try:
        quip_text = _personality.quip(ACTIVE_PERSONA) if _personality and hasattr(_personality, "quip") else ""
    except Exception:
        quip_text = ""
    header = _persona_line(quip_text)
    working = (header + ("\n" + (message or ""))) if header else (message or "")

    final, extras2, _used_llm, _used_beautify = _llm_then_beautify(title, working)
    merged_extras = extras2 if extras2 is not None else (extras or {})
    send_outputs(title or "Notification", final, priority=int(priority or 5), extras=merged_extras)

# ============================
# Commands + Wake-words
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

def _try_call(module, fn_name, *args, **kwargs):
    try:
        if module and hasattr(module, fn_name):
            return getattr(module, fn_name)(*args, **kwargs)
    except Exception as e:
        return f"⚠️ {fn_name} failed: {e}", None
    return None, None

def _handle_command(ncmd: str) -> bool:
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
        process_and_send("Help", "dns | kuma | weather | forecast | digest | joke\nARR: upcoming movies/series, counts, longest ...")
        return True

    if ncmd in ("digest", "daily digest", "summary"):
        if m_digest and hasattr(m_digest, "build_digest"):
            title2, msg2, pr = m_digest.build_digest(merged)
            try:
                if _personality and hasattr(_personality, "quip"):
                    msg2 += f"\n\n{_personality.quip(ACTIVE_PERSONA)}"
            except Exception:
                pass
            process_and_send("Digest", msg2, priority=pr)
        else:
            process_and_send("Digest", "Digest module unavailable.")
        return True

    if ncmd in ("dns",):
        text, _ = _try_call(m_tech, "handle_dns_command", "dns")
        process_and_send("DNS Status", text or "No data.")
        return True

    if ncmd in ("kuma", "uptime", "monitor"):
        text, _ = _try_call(m_kuma, "handle_kuma_command", "kuma")
        process_and_send("Uptime Kuma", text or "No data.")
        return True

    if ncmd in ("weather", "now", "today", "temp", "temps"):
        text = ""
        if m_weather and hasattr(m_weather, "handle_weather_command"):
            try:
                text = m_weather.handle_weather_command("weather")
                if isinstance(text, tuple): text = text[0]
            except Exception as e:
                text = f"⚠️ Weather failed: {e}"
        process_and_send("Weather", text or "No data.")
        return True

    if ncmd in ("forecast", "weekly", "7day", "7-day", "7 day"):
        text = ""
        if m_weather and hasattr(m_weather, "handle_weather_command"):
            try:
                text = m_weather.handle_weather_command("forecast")
                if isinstance(text, tuple): text = text[0]
            except Exception as e:
                text = f"⚠️ Forecast failed: {e}"
        process_and_send("Forecast", text or "No data.")
        return True

    if ncmd in ("joke", "pun", "tell me a joke", "make me laugh", "chat"):
        if m_chat and hasattr(m_chat, "handle_chat_command"):
            try:
                msg, _ = m_chat.handle_chat_command("joke")
            except Exception as e:
                msg = f"⚠️ Chat error: {e}"
            process_and_send("Joke", msg or "No joke available right now.")
        else:
            process_and_send("Joke", "Chat engine unavailable.")
        return True

    # ARR helpers
    if ncmd in ("upcoming movies", "upcoming films", "movies upcoming", "films upcoming"):
        msg, _ = _try_call(m_arr, "upcoming_movies", 7)
        process_and_send("Upcoming Movies", msg or "No data.")
        return True
    if ncmd in ("upcoming series", "upcoming shows", "series upcoming", "shows upcoming"):
        msg, _ = _try_call(m_arr, "upcoming_series", 7)
        process_and_send("Upcoming Episodes", msg or "No data.")
        return True
    if ncmd in ("movie count", "film count"):
        msg, _ = _try_call(m_arr, "movie_count")
        process_and_send("Movie Count", msg or "No data.")
        return True
    if ncmd in ("series count", "show count"):
        msg, _ = _try_call(m_arr, "series_count")
        process_and_send("Series Count", msg or "No data.")
        return True
    if ncmd in ("longest movie", "longest film"):
        msg, _ = _try_call(m_arr, "longest_movie")
        process_and_send("Longest Movie", msg or "No data.")
        return True
    if ncmd in ("longest series", "longest show"):
        msg, _ = _try_call(m_arr, "longest_series")
        process_and_send("Longest Series", msg or "No data.")
        return True

    return False

def _maybe_handle_wakewords(title: str, body: str) -> bool:
    cmd = extract_command_from(title or "", body or "")
    if not cmd:
        return False
    try:
        if _handle_command(normalize_cmd(cmd)):
            return True
    except Exception as e:
        try:
            process_and_send("Wake Error", f"{e}", priority=5)
        except Exception:
            pass
    return False

# ============================
# Boot screen / status card
# ============================
def post_startup_card():
    lines = [
        "🧬 Prime Neural Boot v2 — Standalone Mode",
        f"🧠 LLM: {'Enabled' if merged.get('llm_enabled') else 'Disabled'} "
        f"• Persona riffs: {'ON' if os.getenv('BEAUTIFY_LLM_ENABLED','true').lower() in ('1','true','yes') else 'OFF'} "
        f"• LLM rewrite: {'ON' if LLM_REWRITE_ENABLED else 'OFF'}",
        f"🗣️ Active Persona: {ACTIVE_PERSONA} ({PERSONA_TOD})",
        "",
        "Intakes (sidecars):",
        f"  ▸ SMTP:    {'ACTIVE' if merged.get('smtp_enabled') else 'OFF'} (2525)",
        f"  ▸ Webhook: {'ACTIVE' if merged.get('webhook_enabled') else 'OFF'} ({WEBHOOK_BIND}:{WEBHOOK_PORT})",
        f"  ▸ Proxy:   {'ACTIVE' if merged.get('proxy_enabled') else 'OFF'} (2580)",
        f"  ▸ Apprise: {'ACTIVE' if merged.get('intake_apprise_enabled') else 'OFF'} ({INTAKE_APPRISE_BIND}:{INTAKE_APPRISE_PORT})",
        "",
        "Outputs:",
        f"  ▸ Gotify: {'ON' if merged.get('push_gotify_enabled') else 'OFF'}",
        f"  ▸ ntfy:   {'ON' if merged.get('push_ntfy_enabled') else 'OFF'}",
        f"  ▸ SMTP:   {'ON' if merged.get('push_smtp_enabled') else 'OFF'}",
        "",
        "Modules:",
        f"  ▸ Radarr:       {'ACTIVE' if RADARR_ENABLED else 'OFF'}",
        f"  ▸ Sonarr:       {'ACTIVE' if SONARR_ENABLED else 'OFF'}",
        f"  ▸ Weather:      {'ACTIVE' if WEATHER_ENABLED else 'OFF'}",
        f"  ▸ Digest:       {'ACTIVE' if DIGEST_ENABLED_FILE else 'OFF'}",
        f"  ▸ Chat:         {'ACTIVE' if CHAT_ENABLED_FILE else 'OFF'}",
        f"  ▸ Uptime Kuma:  {'ACTIVE' if KUMA_ENABLED else 'OFF'}",
        f"  ▸ Technitium:   {'ACTIVE' if TECHNITIUM_ENABLED else 'OFF'}",
        "",
        "Health:",
        "  ▸ Internal API: 127.0.0.1:2599 (/internal/ingest, /internal/wake, /health)",
        f"  ▸ TCP Health:    127.0.0.1:{HEALTH_PORT}",
        "",
        "Wake-words: ENABLED everywhere (title/body starting with 'jarvis ...')",
        "Status: All systems nominal ✅",
    ]
    process_and_send("Startup", "\n".join(lines), priority=4, extras=None)

# ============================
# Internal HTTP (wake + ingest + health)
# ============================
try:
    from aiohttp import web
except Exception:
    web = None

_recent_hashes: List[str] = []

def _dedup_key(title: str, body: str, prio: int) -> str:
    raw = f"{title}\n{body}\n{prio}".encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()

def _seen_recent(h: str) -> bool:
    return h in _recent_hashes

def _remember(h: str):
    _recent_hashes.append(h)
    if len(_recent_hashes) > 32:
        del _recent_hashes[:len(_recent_hashes)-32]

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
        process_and_send("Wake Error", f"{e}", priority=5)
    return web.json_response({"ok": bool(ok)})

async def _ingest(request):
    """
    POST /internal/ingest
    JSON: { "title": "...", "body" or "message": "...", "priority": 5, "extras": {...} }
    """
    try:
        data = await request.json()
    except Exception:
        data = {}
    title  = str(data.get("title") or "Notification")
    body   = str(data.get("message") or data.get("body") or "")
    prio   = int(data.get("priority") or 5)
    extras = data.get("extras") or {}

    # Dedup to stop storms
    k = _dedup_key(title, body, prio)
    if _seen_recent(k):
        return web.json_response({"ok": True, "skipped": "duplicate"})
    _remember(k)

    # Wake-words
    try:
        if _maybe_handle_wakewords(title, body):
            return web.json_response({"ok": True, "handled": "wake"})
    except Exception:
        pass

    try:
        process_and_send(title, body, priority=prio, extras=extras)
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def _health(request):
    return web.json_response({"ok": True, "service": "jarvis_prime", "ts": int(time.time())})

async def _start_internal_http_server():
    if web is None:
        print("[bot] aiohttp not available; internal HTTP disabled", flush=True)
        return
    try:
        app = web.Application()
        app.router.add_post("/internal/wake", _internal_wake)
        app.router.add_post("/internal/ingest", _ingest)
        app.router.add_get("/health", _health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 2599)
        await site.start()
        print("[bot] internal HTTP listening on 127.0.0.1:2599 (/internal/wake, /internal/ingest, /health)", flush=True)
    except Exception as e:
        print(f"[bot] failed to start internal HTTP server: {e}", flush=True)

# Optional TCP “OK” health
async def _start_tcp_health():
    async def handle(reader, writer):
        try:
            writer.write(b"OK\n")
            await writer.drain()
        finally:
            writer.close()
    try:
        server = await asyncio.start_server(handle, "127.0.0.1", HEALTH_PORT)
        print(f"[bot] tcp health listening on 127.0.0.1:{HEALTH_PORT}", flush=True)
        async with server:
            await server.serve_forever()
    except Exception as e:
        print(f"[bot] tcp health failed: {e}", flush=True)

# ============================
# Digest scheduler
# ============================
_last_digest_date = None

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
                            process_and_send("Digest", msg, priority=pr)
                            _last_digest_date = now.date()
                        else:
                            _last_digest_date = now.date()
                    except Exception as e:
                        print(f"[Scheduler] digest error: {e}", flush=True)
                        _last_digest_date = now.date()
        except Exception as e:
            print(f"[Scheduler] loop error: {e}", flush=True)
        await asyncio.sleep(60)

# ============================
# Signals & main loop
# ============================
_stop_event = asyncio.Event()

def _handle_sigterm(*_):
    try:
        print("[bot] SIGTERM/SIGINT received — shutting down.", flush=True)
        loop = asyncio.get_event_loop()
        loop.call_soon_threadsafe(_stop_event.set)
    except Exception:
        pass

signal.signal(signal.SIGTERM, _handle_sigterm)
if hasattr(signal, "SIGINT"):
    signal.signal(signal.SIGINT, _handle_sigterm)

def main():
    try:
        start_sidecars()
        post_startup_card()
    except Exception:
        pass
    asyncio.run(_run_forever())

async def _run_forever():
    try:
        asyncio.create_task(_start_internal_http_server())
        asyncio.create_task(_start_tcp_health())
    except Exception:
        pass
    asyncio.create_task(_digest_scheduler_loop())

    while not _stop_event.is_set():
        await asyncio.sleep(60)

    stop_sidecars()
    await asyncio.sleep(0.1)

if __name__ == "__main__":
    main()