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
import smtplib
from email.mime.text import MIMEText
from typing import List

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

# Optional Gotify config (intake/output only if enabled)
GOTIFY_URL   = os.getenv("GOTIFY_URL", "").rstrip("/")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN", "")
APP_TOKEN    = os.getenv("GOTIFY_APP_TOKEN", "")
APP_NAME     = os.getenv("JARVIS_APP_NAME", "Jarvis")

SILENT_REPOST    = os.getenv("SILENT_REPOST", "true").lower() in ("1","true","yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1","true","yes")

# Feature toggles (env defaults; can be overridden by /data/options.json)
RADARR_ENABLED     = os.getenv("radarr_enabled", "false").lower() in ("1","true","yes")
SONARR_ENABLED     = os.getenv("sonarr_enabled", "false").lower() in ("1","true","yes")
WEATHER_ENABLED    = os.getenv("weather_enabled", "false").lower() in ("1","true","yes")
CHAT_ENABLED_ENV   = os.getenv("chat_enabled", "false").lower() in ("1","true","yes")
DIGEST_ENABLED_ENV = os.getenv("digest_enabled", "false").lower() in ("1","true","yes")
TECHNITIUM_ENABLED = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")
KUMA_ENABLED       = os.getenv("uptimekuma_enabled", "false").lower() in ("1","true","yes")
SMTP_ENABLED       = os.getenv("smtp_enabled", "false").lower() in ("1","true","yes")
PROXY_ENABLED_ENV  = os.getenv("proxy_enabled", "false").lower() in ("1","true","yes")

# Webhook feature toggles
WEBHOOK_ENABLED    = os.getenv("webhook_enabled", "false").lower() in ("1","true","yes")
WEBHOOK_BIND       = os.getenv("webhook_bind", "0.0.0.0")
WEBHOOK_PORT       = int(os.getenv("webhook_port", "2590"))

# Apprise intake toggles (we'll try sidecar first; fallback to in-process)
INTAKE_APPRISE_ENABLED = os.getenv("intake_apprise_enabled", "false").lower() in ("1","true","yes")
INTAKE_APPRISE_TOKEN = os.getenv("intake_apprise_token", "")
INTAKE_APPRISE_ACCEPT_ANY_KEY = os.getenv("intake_apprise_accept_any_key", "true").lower() in ("1","true","yes")
INTAKE_APPRISE_ALLOWED_KEYS = [k for k in os.getenv("intake_apprise_allowed_keys", "").split(",") if k.strip()]
INTAKE_APPRISE_PORT = int(os.getenv("intake_apprise_port", "2591"))
INTAKE_APPRISE_BIND = os.getenv("intake_apprise_bind", "0.0.0.0")

# LLM behavior toggles (rewrite stays OFF unless explicitly enabled)
LLM_REWRITE_ENABLED = os.getenv("LLM_REWRITE_ENABLED", "false").lower() in ("1","true","yes")
BEAUTIFY_LLM_ENABLED_ENV = os.getenv("BEAUTIFY_LLM_ENABLED", "true").lower() in ("1","true","yes")

# ============================
# Load /data/options.json
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

    # Outputs / Inputs from options.json
    PUSH_GOTIFY_ENABLED = bool(merged.get("push_gotify_enabled", True))
    PUSH_NTFY_ENABLED   = bool(merged.get("push_ntfy_enabled", False))
    PUSH_SMTP_ENABLED   = bool(merged.get("push_smtp_enabled", False))
    INGEST_GOTIFY_ENABLED = bool(merged.get("ingest_gotify_enabled", True))
    INGEST_SMTP_ENABLED   = bool(merged.get("ingest_smtp_enabled", True))
    INGEST_APPRISE_ENABLED= bool(merged.get("ingest_apprise_enabled", True))
    INGEST_NTFY_ENABLED   = bool(merged.get("ingest_ntfy_enabled", False))

    # NTFY
    NTFY_URL   = str(merged.get("ntfy_url", options.get("ntfy_url","") if isinstance(options,dict) else ""))
    NTFY_TOPIC = str(merged.get("ntfy_topic", ""))
    NTFY_USER  = str(merged.get("ntfy_user", ""))
    NTFY_PASS  = str(merged.get("ntfy_pass", ""))
    NTFY_TOKEN = str(merged.get("ntfy_token", ""))

    # SMTP Push
    PUSH_SMTP_HOST = str(merged.get("push_smtp_host", ""))
    PUSH_SMTP_PORT = int(merged.get("push_smtp_port", 587))
    PUSH_SMTP_USER = str(merged.get("push_smtp_user", ""))
    PUSH_SMTP_PASS = str(merged.get("push_smtp_pass", ""))
    PUSH_SMTP_TO   = str(merged.get("push_smtp_to", ""))

    # Webhook
    WEBHOOK_ENABLED = bool(merged.get("webhook_enabled", WEBHOOK_ENABLED))
    WEBHOOK_BIND    = str(merged.get("webhook_bind", WEBHOOK_BIND))
    try:
        WEBHOOK_PORT = int(merged.get("webhook_port", WEBHOOK_PORT))
    except Exception:
        pass

    # Apprise intake (we support sidecar or fallback)
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

    # LLM
    LLM_REWRITE_ENABLED = bool(merged.get("llm_rewrite_enabled", LLM_REWRITE_ENABLED))
    _beautify_llm_enabled_opt = merged.get("llm_persona_riffs_enabled", BEAUTIFY_LLM_ENABLED_ENV)
    os.environ["BEAUTIFY_LLM_ENABLED"] = "true" if _beautify_llm_enabled_opt else "false"

    # Gotify details from options if present
    GOTIFY_URL   = str(merged.get("gotify_url", GOTIFY_URL)).rstrip("/")
    CLIENT_TOKEN = str(merged.get("gotify_client_token", CLIENT_TOKEN))
    APP_TOKEN    = str(merged.get("gotify_app_token", APP_TOKEN))
except Exception:
    PROXY_ENABLED = PROXY_ENABLED_ENV
    CHAT_ENABLED_FILE = CHAT_ENABLED_ENV
    DIGEST_ENABLED_FILE = DIGEST_ENABLED_ENV
    PUSH_GOTIFY_ENABLED = True
    PUSH_NTFY_ENABLED = False
    PUSH_SMTP_ENABLED = False
    INGEST_GOTIFY_ENABLED = True
    INGEST_SMTP_ENABLED = True
    INGEST_APPRISE_ENABLED = True
    INGEST_NTFY_ENABLED = False
    NTFY_URL = NTFY_TOPIC = NTFY_USER = NTFY_PASS = NTFY_TOKEN = ""
    PUSH_SMTP_HOST = PUSH_SMTP_USER = PUSH_SMTP_PASS = PUSH_SMTP_TO = ""
    PUSH_SMTP_PORT = 587

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
        print(f"[bot] started sidecar: {label} -> {cmd}")
    except Exception as e:
        print(f"[bot] sidecar {label} start failed: {e}")

def start_sidecars():
    # proxy
    if PROXY_ENABLED:
        if _port_in_use("127.0.0.1", 2580) or _port_in_use("0.0.0.0", 2580):
            print("[bot] proxy.py already running on :2580 — skipping sidecar")
        else:
            _start_sidecar(["python3","/app/proxy.py"], "proxy.py")

    # smtp
    if SMTP_ENABLED:
        if _port_in_use("127.0.0.1", 2525) or _port_in_use("0.0.0.0", 2525):
            print("[bot] smtp_server.py already running on :2525 — skipping sidecar")
        else:
            _start_sidecar(["python3","/app/smtp_server.py"], "smtp_server.py")

    # webhook
    if WEBHOOK_ENABLED:
        if _port_in_use("127.0.0.1", int(WEBHOOK_PORT)) or _port_in_use("0.0.0.0", int(WEBHOOK_PORT)):
            print(f"[bot] webhook_server.py already running on :{WEBHOOK_PORT} — skipping sidecar")
        else:
            env = os.environ.copy()
            env["webhook_bind"] = WEBHOOK_BIND
            env["webhook_port"] = str(WEBHOOK_PORT)
            _start_sidecar(["python3","/app/webhook_server.py"], "webhook_server.py", env=env)

    # apprise sidecar preferred
    if INTAKE_APPRISE_ENABLED:
        env = os.environ.copy()
        env["INTAKE_APPRISE_BIND"] = INTAKE_APPRISE_BIND
        env["INTAKE_APPRISE_PORT"] = str(INTAKE_APPRISE_PORT)
        env["INTAKE_APPRISE_TOKEN"] = INTAKE_APPRISE_TOKEN
        env["INTAKE_APPRISE_ACCEPT_ANY_KEY"] = "1" if INTAKE_APPRISE_ACCEPT_ANY_KEY else "0"
        env["INTAKE_APPRISE_ALLOWED_KEYS"] = ",".join(INTAKE_APPRISE_ALLOWED_KEYS) if INTAKE_APPRISE_ALLOWED_KEYS else ""
        sidecar_path = "/app/intakes/apprise_server.py" if os.path.exists("/app/intakes/apprise_server.py") else "/app/intakes/apprise.py"
        if _port_in_use(INTAKE_APPRISE_BIND, int(INTAKE_APPRISE_PORT)):
            print(f"[bot] apprise intake already listening on {INTAKE_APPRISE_BIND}:{INTAKE_APPRISE_PORT} — skipping spawn")
        else:
            _start_sidecar(["python3", sidecar_path], "apprise_intake", env=env)
            print(f"[bot] apprise intake configured on {INTAKE_APPRISE_BIND}:{INTAKE_APPRISE_PORT}")

def stop_sidecars():
    for p in _sidecars:
        try: p.terminate()
        except Exception: pass
atexit.register(stop_sidecars)

# ============================
# Persona helpers
# ============================
def _persona_line(quip_text: str) -> str:
    who = ACTIVE_PERSONA or "neutral"
    quip_text = (quip_text or "").strip().replace("\n", " ")
    if len(quip_text) > 140:
        quip_text = quip_text[:137] + "..."
    return f"💬 {who} says: {quip_text}" if quip_text else f"💬 {who} says:"

def _quip() -> str:
    try:
        return _personality.quip(ACTIVE_PERSONA) if _personality and hasattr(_personality, "quip") else ""
    except Exception:
        return ""

# ============================
# OUTPUTS (fan-out)
# ============================
def _send_gotify(title, message, priority=5, extras=None):
    if not PUSH_GOTIFY_ENABLED: 
        return False
    if not GOTIFY_URL or not APP_TOKEN:
        return False
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message or "", "priority": int(priority)}
    if extras: payload["extras"] = extras
    try:
        r = requests.post(url, json=payload, timeout=8)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[bot] gotify send error: {e}")
        return False

def _send_ntfy(title, message, priority=5):
    if not PUSH_NTFY_ENABLED: 
        return False
    if not NTFY_URL or not NTFY_TOPIC:
        return False
    url = f"{NTFY_URL.rstrip('/')}/{NTFY_TOPIC}"
    headers = {"Title": f"{BOT_ICON} {BOT_NAME}: {title}", "Priority": str(priority)}
    if NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {NTFY_TOKEN}"
    try:
        auth = (NTFY_USER, NTFY_PASS) if (NTFY_USER and NTFY_PASS) else None
        r = requests.post(url, data=message or "", headers=headers, timeout=8, auth=auth)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[bot] ntfy send error: {e}")
        return False

def _send_smtp(title, message, priority=5):
    if not PUSH_SMTP_ENABLED:
        return False
    if not PUSH_SMTP_HOST or not PUSH_SMTP_TO:
        return False
    msg = MIMEText(message or "", "plain", "utf-8")
    msg["Subject"] = f"{BOT_ICON} {BOT_NAME}: {title}"
    msg["From"] = PUSH_SMTP_USER or "jarvis@localhost"
    msg["To"] = PUSH_SMTP_TO
    try:
        s = smtplib.SMTP(PUSH_SMTP_HOST, PUSH_SMTP_PORT, timeout=10)
        s.starttls()
        if PUSH_SMTP_USER and PUSH_SMTP_PASS:
            s.login(PUSH_SMTP_USER, PUSH_SMTP_PASS)
        s.sendmail(msg["From"], [PUSH_SMTP_TO], msg.as_string())
        s.quit()
        return True
    except Exception as e:
        print(f"[bot] smtp send error: {e}")
        return False

def send_message(title, message, priority=5, extras=None, decorate=True, source_hint="core"):
    """
    Stand-alone fan-out sender:
    - Persona header always added.
    - Optional personality.decorate on body (when decorate=True).
    - Sends to all enabled outputs (Gotify/Ntfy/SMTP).
    - Mirrors once to storage (source='fanout' or source_hint).
    """
    orig_title = title
    body = message or ""

    # optional decoration
    if decorate and _personality and hasattr(_personality, "decorate_by_persona"):
        try:
            _t, body = _personality.decorate_by_persona(title, body, ACTIVE_PERSONA, PERSONA_TOD, chance=1.0)
        except Exception:
            pass
    elif decorate and _personality and hasattr(_personality, "decorate"):
        try:
            _t, body = _personality.decorate(title, body, ACTIVE_PERSONA, chance=1.0)
        except Exception:
            pass

    # persona speaking header
    try:
        quip_text = _quip()
    except Exception:
        quip_text = ""
    header = _persona_line(quip_text)
    body = (header + ("\n" + (body or ""))) if header else (body or "")

    # priority adjustment if persona supports it
    if _personality and hasattr(_personality, "apply_priority"):
        try:
            priority = _personality.apply_priority(priority, ACTIVE_PERSONA)
        except Exception:
            pass

    ok1 = _send_gotify(orig_title, body, priority=priority, extras=extras)
    ok2 = _send_ntfy(orig_title, body, priority=priority)
    ok3 = _send_smtp(orig_title, body, priority=priority)

    # Mirror to Inbox DB (single row)
    if storage:
        try:
            storage.save_message(
                title=orig_title or "Notification",
                body=body or "",
                source=source_hint or "fanout",
                priority=int(priority),
                extras={"extras": extras or {}, "sent": {"gotify": ok1, "ntfy": ok2, "smtp": ok3}},
                created_at=int(time.time())
            )
        except Exception as e:
            print(f"[bot] storage save failed: {e}")

    return True

# ============================
# Purge helpers (only used if Gotify intake is active)
# ============================
def delete_original_message(msg_id: int):
    try:
        if not msg_id: return
        if not GOTIFY_URL or not CLIENT_TOKEN: return
        url = f"{GOTIFY_URL}/message/{msg_id}"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        requests.delete(url, headers=headers, timeout=6)
    except Exception:
        pass

def _should_purge() -> bool:
    try: return bool(merged.get("silent_repost", SILENT_REPOST))
    except Exception: return SILENT_REPOST

def _purge_after(msg_id: int):
    if _should_purge(): delete_original_message(msg_id)

# ============================
# LLM + Beautify (RIFF CORE)
# ============================
def _footer(used_llm: bool, used_beautify: bool) -> str:
    tags = []
    if used_llm: tags.append("Neural Core ✓")
    if used_beautify: tags.append("Aesthetic Engine ✓")
    if not tags: tags.append("Relay Path")
    return "— " + " · ".join(tags)

def _llm_then_beautify(title: str, message: str):
    used_llm = False
    used_beautify = False
    final = message or ""
    extras = None

    # Optional rewrite (OFF by default)
    if LLM_REWRITE_ENABLED and merged.get("llm_enabled") and _llm and hasattr(_llm, "rewrite"):
        try:
            final2 = _llm.rewrite(
                text=final,
                mood=ACTIVE_PERSONA,
                timeout=int(merged.get("llm_timeout_seconds",12)),
                cpu_limit=int(merged.get("llm_max_cpu_percent",70)),
                models_priority=merged.get("llm_models_priority", []),
                base_url=merged.get("llm_ollama_base_url",""),
                model_url=merged.get("llm_model_url",""),
                model_path=merged.get("llm_model_path",""),
                model_sha256=merged.get("llm_model_sha256",""),
                allow_profanity=bool(merged.get("personality_allow_profanity", False))
            )
            if final2:
                final = final2
                used_llm = True
        except Exception as e:
            print(f"[bot] LLM rewrite failed (disabled by default): {e}")

    # Always beautify; pass persona so overlay + bottom riffs work
    if _beautify and hasattr(_beautify, "beautify_message") and os.getenv("BEAUTIFY_LLM_ENABLED","true").lower() in ("1","true","yes") and merged.get("llm_enabled"):
        try:
            final, extras = _beautify.beautify_message(
                title, final,
                mood=ACTIVE_PERSONA,
                persona=ACTIVE_PERSONA,
                persona_quip=True
            )
            used_beautify = True
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
    s = re.sub(r"[^\w\s]", " ", s)  # strip punctuation
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
        f"✉️ SMTP Intake — {'ACTIVE' if SMTP_ENABLED else 'OFF'}",
        f"🔀 Proxy Intake — {'ACTIVE' if PROXY_ENABLED else 'OFF'}",
        f"🧠 DNS (Technitium) — {'ACTIVE' if TECHNITIUM_ENABLED else 'OFF'}",
        f"🔗 Webhook Intake — {'ACTIVE' if WEBHOOK_ENABLED else 'OFF'}",
        f"📮 Apprise Intake — {'ACTIVE' if INTAKE_APPRISE_ENABLED else 'OFF'}",
        "",
        f"LLM rewrite: {'ON' if LLM_REWRITE_ENABLED else 'OFF'}",
        f"Persona riffs: {'ON' if os.getenv('BEAUTIFY_LLM_ENABLED','true').lower() in ('1','true','yes') else 'OFF'}",
        "Status: All systems nominal",
    ]
    send_message("Startup", "\n".join(lines), priority=4, decorate=False, source_hint="startup")

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
        send_message("Help", "dns | kuma | weather | forecast | digest | joke\nARR: upcoming movies/series, counts, longest ...", source_hint="help")
        return True

    if ncmd in ("digest", "daily digest", "summary"):
        if m_digest and hasattr(m_digest, "build_digest"):
            title2, msg2, pr = m_digest.build_digest(merged)
            try:
                if _personality and hasattr(_personality, "quip"):
                    msg2 += f"\n\n{_personality.quip(ACTIVE_PERSONA)}"
            except Exception:
                pass
            send_message("Digest", msg2, priority=pr, source_hint="digest")
        else:
            send_message("Digest", "Digest module unavailable.", source_hint="digest")
        return True

    if ncmd in ("dns",):
        text, _ = _try_call(m_tech, "handle_dns_command", "dns")
        send_message("DNS Status", text or "No data.", source_hint="dns")
        return True

    if ncmd in ("kuma", "uptime", "monitor"):
        text, _ = _try_call(m_kuma, "handle_kuma_command", "kuma")
        send_message("Uptime Kuma", text or "No data.", source_hint="kuma")
        return True

    if ncmd in ("weather", "now", "today", "temp", "temps"):
        text = ""
        if m_weather and hasattr(m_weather, "handle_weather_command"):
            try:
                text = m_weather.handle_weather_command("weather")
                if isinstance(text, tuple): text = text[0]
            except Exception as e:
                text = f"⚠️ Weather failed: {e}"
        send_message("Weather", text or "No data.", source_hint="weather")
        return True

    if ncmd in ("forecast", "weekly", "7day", "7-day", "7 day"):
        text = ""
        if m_weather and hasattr(m_weather, "handle_weather_command"):
            try:
                text = m_weather.handle_weather_command("forecast")
                if isinstance(text, tuple): text = text[0]
            except Exception as e:
                text = f"⚠️ Forecast failed: {e}"
        send_message("Forecast", text or "No data.", source_hint="forecast")
        return True

    # Jokes / chat
    if ncmd in ("joke", "pun", "tell me a joke", "make me laugh", "chat"):
        if m_chat and hasattr(m_chat, "handle_chat_command"):
            try:
                msg, _ = m_chat.handle_chat_command("joke")
            except Exception as e:
                msg = f"⚠️ Chat error: {e}"
            send_message("Joke", msg or "No joke available right now.", source_hint="chat")
        else:
            send_message("Joke", "Chat engine unavailable.", source_hint="chat")
        return True

    # ARR
    if ncmd in ("upcoming movies", "upcoming films", "movies upcoming", "films upcoming"):
        msg, _ = _try_call(m_arr, "upcoming_movies", 7)
        send_message("Upcoming Movies", msg or "No data.", source_hint="arr")
        return True
    if ncmd in ("upcoming series", "upcoming shows", "series upcoming", "shows upcoming"):
        msg, _ = _try_call(m_arr, "upcoming_series", 7)
        send_message("Upcoming Episodes", msg or "No data.", source_hint="arr")
        return True
    if ncmd in ("movie count", "film count"):
        msg, _ = _try_call(m_arr, "movie_count")
        send_message("Movie Count", msg or "No data.", source_hint="arr")
        return True
    if ncmd in ("series count", "show count"):
        msg, _ = _try_call(m_arr, "series_count")
        send_message("Series Count", msg or "No data.", source_hint="arr")
        return True
    if ncmd in ("longest movie", "longest film"):
        msg, _ = _try_call(m_arr, "longest_movie")
        send_message("Longest Movie", msg or "No data.", source_hint="arr")
        return True
    if ncmd in ("longest series", "longest show"):
        msg, _ = _try_call(m_arr, "longest_series")
        send_message("Longest Series", msg or "No data.", source_hint="arr")
        return True

    return False

# ============================
# Gotify intake (optional, stand-alone friendly)
# ============================
_processed_sigs = set()

def _sig(source: str, title: str, message: str, ext_id: str = "") -> str:
    h = hashlib.sha256()
    h.update((source or "").encode("utf-8"))
    h.update((ext_id or "").encode("utf-8"))
    h.update((title or "").encode("utf-8"))
    h.update((message or "").encode("utf-8"))
    return h.hexdigest()

async def listen_gotify():
    if not INGEST_GOTIFY_ENABLED or not GOTIFY_URL or not CLIENT_TOKEN:
        print("[bot] Gotify intake disabled or not configured")
        return
    ws_url = GOTIFY_URL.replace("http://","ws://").replace("https://","wss://") + f"/stream?token={CLIENT_TOKEN}"
    print(f"[bot] Gotify intake connecting to {ws_url}")
    async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
        async for raw in ws:
            try:
                data = json.loads(raw); msg_id = data.get("id")
                title = data.get("title") or ""
                message = data.get("message") or ""

                # wake-word first so commands work even if posted via same app
                ncmd = normalize_cmd(extract_command_from(title, message))
                if ncmd and _handle_command(ncmd):
                    _purge_after(msg_id)
                    continue

                sig = _sig("gotify", title, message, str(msg_id))
                if sig in _processed_sigs:
                    continue
                _processed_sigs.add(sig)
                if len(_processed_sigs) > 1000:
                    _processed_sigs.clear()

                final, extras, _, _ = _llm_then_beautify(title, message)
                send_message(title or "Notification", final, priority=5, extras=extras, source_hint="gotify")
                _purge_after(msg_id)
            except Exception as e:
                print(f"[bot] gotify listen loop err: {e}")

# ============================
# Daily scheduler (digest)
# ============================
_last_digest_date = None

async def _digest_scheduler_loop():
    # Check once a minute; when local time == digest_time and enabled, post digest once per day.
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
                            send_message("Digest", msg, priority=pr, source_hint="digest")
                            _last_digest_date = now.date()
                        else:
                            _last_digest_date = now.date()
                    except Exception as e:
                        print(f"[Scheduler] digest error: {e}")
                        _last_digest_date = now.date()
        except Exception as e:
            print(f"[Scheduler] loop error: {e}")
        await asyncio.sleep(60)

# ============================
# Internal HTTP server (wake + generic intake)
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
    # Normalize typical prefixes like "jarvis ..."
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
            send_message("Wake Error", f"{e}", priority=5, source_hint="wake")
        except Exception:
            pass
    return web.json_response({"ok": bool(ok)})

async def _internal_emit(request):
    """
    Generic local intake for any sidecar:
    POST /internal/emit  JSON { "title": "...", "body": "...", "priority": 5, "source": "smtp" }
    """
    try:
        data = await request.json()
    except Exception:
        data = {}
    title = str(data.get("title") or "Notification")
    body  = str(data.get("body") or "")
    prio  = int(data.get("priority", 5))
    source = str(data.get("source") or "intake")
    try:
        # wake-word pass-through first
        ncmd = normalize_cmd(extract_command_from(title, body))
        if ncmd and _handle_command(ncmd):
            return web.json_response({"ok": True, "handled":"command"})
        # riff + beautify
        final, extras, _, _ = _llm_then_beautify(title, body)
        send_message(title, final, priority=prio, extras=extras, source_hint=source)
        return web.json_response({"ok": True})
    except Exception as e:
        print(f"[intake] emit error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def _start_internal_server():
    if web is None:
        print("[bot] aiohttp not available; internal HTTP disabled")
        return
    try:
        app = web.Application()
        app.router.add_post("/internal/wake", _internal_wake)
        app.router.add_post("/internal/emit", _internal_emit)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 2599)
        await site.start()
        print("[bot] internal server listening on 127.0.0.1:2599 (/internal/wake, /internal/emit)")
    except Exception as e:
        print(f"[bot] failed to start internal server: {e}")

# ============================
# Apprise (fallback in-process if sidecar not available)
# ============================
try:
    import threading
except Exception:
    threading = None

def _emit_from_apprise_intake(msg: dict):
    """
    Normalize and fan out using the same beautify/persona pipeline.
    """
    try:
        title = str(msg.get("title") or "Notification")
        body  = str(msg.get("body") or "")
        final, extras, _, _ = _llm_then_beautify(title, body)
        send_message(title, final, priority=5, extras=extras, source_hint="apprise")
    except Exception as e:
        print(f"[bot] apprise emit failed: {e}")

def _start_apprise_flask_fallback():
    if not INTAKE_APPRISE_ENABLED:
        print("[bot] Apprise intake disabled via options")
        return
    if threading is None:
        print("[bot] threading unavailable; Apprise fallback disabled")
        return
    try:
        # Try package import first, then file loader
        try:
            import intakes.apprise as apprise_intake  # requires /app/intakes/__init__.py
            print("[bot] loaded apprise intake via package import (intakes.apprise)")
        except Exception as _e_pkg:
            print(f"[bot] package import failed ({_e_pkg}); trying file loader for /app/intakes/apprise.py")
            apprise_intake = _load_module("intake_apprise", "/app/intakes/apprise.py")
            if apprise_intake is None:
                print("[bot] failed to load /app/intakes/apprise.py")
                return

        from flask import Flask
        app = Flask("jarvis_apprise_intake")

        # Register blueprint with your configured gates
        allowed = INTAKE_APPRISE_ALLOWED_KEYS[:] if INTAKE_APPRISE_ALLOWED_KEYS else None
        apprise_intake.register(
            app,
            emit=_emit_from_apprise_intake,
            token=INTAKE_APPRISE_TOKEN,
            accept_any_key=INTAKE_APPRISE_ACCEPT_ANY_KEY,
            allowed_keys=allowed
        )

        def _serve():
            try:
                from waitress import serve
                serve(app, host=INTAKE_APPRISE_BIND or "0.0.0.0", port=int(INTAKE_APPRISE_PORT))
            except Exception as e:
                print(f"[bot] waitress unavailable or failed ({e}); falling back to Flask.run on port {INTAKE_APPRISE_PORT}")
                try:
                    app.run(host=INTAKE_APPRISE_BIND or "0.0.0.0", port=int(INTAKE_APPRISE_PORT))
                except Exception as ee:
                    print(f"[bot] Flask.run failed: {ee}")

        t = threading.Thread(target=_serve, name="apprise-intake", daemon=True)
        t.start()
        print(f"[bot] Apprise fallback Flask server listening on {INTAKE_APPRISE_BIND}:{INTAKE_APPRISE_PORT} (token required)")
    except Exception as e:
        print(f"[bot] failed to start Apprise fallback server: {e}")

# ============================
# Main / loop
# ============================
def main():
    try:
        start_sidecars()
        post_startup_card()
    except Exception as e:
        print(f"[bot] startup error: {e}")
    asyncio.run(_run_forever())

async def _run_forever():
    # internal API
    try:
        asyncio.create_task(_start_internal_server())
    except Exception: 
        pass

    # If apprise sidecar couldn’t be started externally, fallback in-process
    if INTAKE_APPRISE_ENABLED and not _port_in_use(INTAKE_APPRISE_BIND, int(INTAKE_APPRISE_PORT)):
        _start_apprise_flask_fallback()

    # schedulers
    asyncio.create_task(_digest_scheduler_loop())

    # optional gotify intake
    if INGEST_GOTIFY_ENABLED and GOTIFY_URL and CLIENT_TOKEN:
        asyncio.create_task(listen_gotify())
    else:
        print("[bot] Gotify intake not active")

    while True:
        try:
            await asyncio.sleep(3600)
        except Exception:
            await asyncio.sleep(3)

if __name__ == "__main__":
    main()