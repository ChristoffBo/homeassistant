#!/usr/bin/env python3
# /app/bot.py

import os
import json
import time
import re
import atexit
import signal
import socket
import hashlib
import asyncio
import subprocess
from typing import Dict, Any, Optional, List, Tuple

# ---------------------------
# Quiet optional storage
# ---------------------------
try:
    import storage  # /app/storage.py (optional)
    try:
        storage.init_db()
    except Exception:
        storage = None
except Exception:
    storage = None

# ---------------------------
# Config loader
# ---------------------------
def _load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

_cfg_fallback = _load_json("/data/config.json")
_cfg_options  = _load_json("/data/options.json")
cfg: Dict[str, Any] = {**_cfg_fallback, **_cfg_options}

# Basic
BOT_NAME = str(cfg.get("bot_name", "Jarvis Prime"))
BOT_ICON = str(cfg.get("bot_icon", "🧠"))

# LLM & riffs
LLM_ENABLED = bool(cfg.get("llm_enabled", False))
LLM_REWRITE_ENABLED = bool(cfg.get("llm_rewrite_enabled", False))
RIFFS_ENABLED = bool(cfg.get("llm_persona_riffs_enabled", False))
# Beautify expects this env toggle:
os.environ["BEAUTIFY_LLM_ENABLED"] = "true" if (LLM_ENABLED and RIFFS_ENABLED) else "false"

# Outputs (fan-out only)
PUSH_GOTIFY = bool(cfg.get("push_gotify_enabled", False))
PUSH_NTFY   = bool(cfg.get("push_ntfy_enabled", False))
PUSH_SMTP   = bool(cfg.get("push_smtp_enabled", False))

GOTIFY_URL       = str(cfg.get("gotify_url", "")).rstrip("/")
GOTIFY_APP_TOKEN = str(cfg.get("gotify_app_token", ""))
NTFY_URL         = str(cfg.get("ntfy_url", "")).rstrip("/")
NTFY_TOPIC       = str(cfg.get("ntfy_topic", ""))

SMTP_HOST = str(cfg.get("push_smtp_host", ""))
SMTP_PORT = int(cfg.get("push_smtp_port", 587))
SMTP_USER = str(cfg.get("push_smtp_user", ""))
SMTP_PASS = str(cfg.get("push_smtp_pass", ""))
SMTP_TO   = str(cfg.get("push_smtp_to", ""))

# Sidecars (all intakes are sidecars)
SMTP_INTAKE_ENABLED  = bool(cfg.get("smtp_enabled", False))
SMTP_INTAKE_PORT     = int(cfg.get("smtp_port", 2525))
PROXY_ENABLED        = bool(cfg.get("proxy_enabled", False))
PROXY_PORT           = int(cfg.get("proxy_port", 2580))
WEBHOOK_ENABLED      = bool(cfg.get("webhook_enabled", False))
WEBHOOK_BIND         = str(cfg.get("webhook_bind", "0.0.0.0"))
WEBHOOK_PORT         = int(cfg.get("webhook_port", 2590))
APPRISE_ENABLED      = bool(cfg.get("intake_apprise_enabled", False))
APPRISE_BIND         = str(cfg.get("intake_apprise_bind", "0.0.0.0"))
APPRISE_PORT         = int(cfg.get("intake_apprise_port", 2591))
APPRISE_TOKEN        = str(cfg.get("intake_apprise_token", ""))
APPRISE_ACCEPT_ANY   = bool(cfg.get("intake_apprise_accept_any_key", True))
APPRISE_ALLOWED_KEYS = str(cfg.get("intake_apprise_allowed_keys", ""))

# Modules (flags for boot card only; handlers are optional imports)
RADARR_ENABLED     = bool(cfg.get("radarr_enabled", False))
SONARR_ENABLED     = bool(cfg.get("sonarr_enabled", False))
WEATHER_ENABLED    = bool(cfg.get("weather_enabled", False))
DIGEST_ENABLED     = bool(cfg.get("digest_enabled", False))
CHAT_ENABLED       = bool(cfg.get("chat_enabled", False))
KUMA_ENABLED       = bool(cfg.get("uptimekuma_enabled", False))
TECHNITIUM_ENABLED = bool(cfg.get("technitium_enabled", False))

# Wake-words
WAKE_WORDS = [w.lower().strip() for w in cfg.get("wake_words", ["jarvis", "hey jarvis", "ok jarvis"]) if str(w).strip()]

# Health
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "2598"))

# ---------------------------
# Optional local modules
# ---------------------------
def _load_module(name: str, path: str):
    try:
        import importlib.util as _imp
        spec = _imp.spec_from_file_location(name, path)
        if not spec or not spec.loader:
            return None
        mod = _imp.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None

aliases     = _load_module("aliases", "/app/aliases.py")
personality = _load_module("personality", "/app/personality.py")
pstate      = _load_module("personality_state", "/app/personality_state.py")
beautify    = _load_module("beautify", "/app/beautify.py")
llm_client  = _load_module("llm_client", "/app/llm_client.py")

ACTIVE_PERSONA, PERSONA_TOD = "neutral", ""
if pstate and hasattr(pstate, "get_active_persona"):
    try:
        ACTIVE_PERSONA, PERSONA_TOD = pstate.get_active_persona() or ("neutral", "")
    except Exception:
        ACTIVE_PERSONA, PERSONA_TOD = "neutral", ""

# ---------------------------
# Sidecars control
# ---------------------------
_sidecars: List[subprocess.Popen] = []

def _port_in_use(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.25)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except Exception:
        return False

def _start_sidecar(cmd: List[str], label: str, port: int, extra_env: Optional[Dict[str, str]] = None):
    if _port_in_use(port):
        print(f"[sidecar] {label} already on :{port}")
        return
    try:
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        _sidecars.append(p)
        print(f"[sidecar] started {label}")
    except Exception as e:
        print(f"[sidecar] {label} failed: {e}")

def start_sidecars():
    if PROXY_ENABLED:
        _start_sidecar(["python3", "/app/proxy.py"], "proxy", PROXY_PORT, None)
    if SMTP_INTAKE_ENABLED:
        _start_sidecar(["python3", "/app/smtp_server.py"], "smtp_server", SMTP_INTAKE_PORT, None)
    if WEBHOOK_ENABLED:
        _start_sidecar(
            ["python3", "/app/webhook_server.py"],
            "webhook_server", WEBHOOK_PORT,
            {"webhook_bind": WEBHOOK_BIND, "webhook_port": str(WEBHOOK_PORT)}
        )
    if APPRISE_ENABLED:
        _start_sidecar(
            ["python3", "/app/apprise_server.py"],
            "apprise_server", APPRISE_PORT,
            {
                "APPRISE_BIND": APPRISE_BIND,
                "APPRISE_PORT": str(APPRISE_PORT),
                "APPRISE_TOKEN": APPRISE_TOKEN,
                "APPRISE_ACCEPT_ANY_KEY": "true" if APPRISE_ACCEPT_ANY else "false",
                "APPRISE_ALLOWED_KEYS": APPRISE_ALLOWED_KEYS
            }
        )

def stop_sidecars():
    for p in _sidecars:
        try:
            p.terminate()
        except Exception:
            pass

atexit.register(stop_sidecars)

# ---------------------------
# Storage mirror helper
# ---------------------------
def _mirror(title: str, body: str, source: str, priority: int, extras: Optional[dict] = None):
    if not storage:
        return
    try:
        storage.save_message(
            title=title or "Notification",
            body=body or "",
            source=source,
            priority=int(priority or 5),
            extras=extras or {},
            created_at=int(time.time())
        )
    except Exception:
        pass

# ---------------------------
# Outputs (fan-out only)
# ---------------------------
def _send_gotify(title: str, message: str, priority: int = 5, extras: Optional[dict] = None) -> bool:
    if not (PUSH_GOTIFY and GOTIFY_URL and GOTIFY_APP_TOKEN):
        return False
    try:
        import requests
        url = f"{GOTIFY_URL}/message?token={GOTIFY_APP_TOKEN}"
        payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message or "", "priority": int(priority or 5)}
        if extras: payload["extras"] = extras
        r = requests.post(url, json=payload, timeout=8)
        r.raise_for_status()
        _mirror(title, message, "gotify", priority, {"status": r.status_code, "extras": extras or {}})
        return True
    except Exception as e:
        _mirror(title, message, "gotify", priority, {"status": 0, "error": str(e), "extras": extras or {}})
        return False

def _send_ntfy(title: str, message: str, priority: int = 5, extras: Optional[dict] = None) -> bool:
    if not (PUSH_NTFY and NTFY_URL and NTFY_TOPIC):
        return False
    try:
        import requests
        url = f"{NTFY_URL}/{NTFY_TOPIC}".rstrip("/")
        headers = {"Title": f"{BOT_ICON} {BOT_NAME}: {title}", "Priority": str(int(priority or 5))}
        r = requests.post(url, data=(message or "").encode("utf-8"), headers=headers, timeout=8)
        r.raise_for_status()
        _mirror(title, message, "ntfy", priority, {"status": r.status_code, "extras": extras or {}})
        return True
    except Exception as e:
        _mirror(title, message, "ntfy", priority, {"status": 0, "error": str(e), "extras": extras or {}})
        return False

def _send_smtp(title: str, message: str, priority: int = 5, extras: Optional[dict] = None) -> bool:
    if not PUSH_SMTP:
        return False
    try:
        import smtplib
        from email.mime.text import MIMEText
        body = message or ""
        msg = MIMEText(body, "html" if cfg.get("smtp_allow_html", True) else "plain", "utf-8")
        msg["Subject"] = f"{BOT_ICON} {BOT_NAME}: {title}"
        msg["From"] = SMTP_USER or "jarvis@localhost"
        msg["To"] = SMTP_TO or (SMTP_USER or "root@localhost")
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=12) as s:
            try:
                s.starttls()
            except Exception:
                pass
            if SMTP_USER and SMTP_PASS:
                try:
                    s.login(SMTP_USER, SMTP_PASS)
                except Exception:
                    pass
            s.send_message(msg)
        _mirror(title, message, "smtp", priority, {"status": 250, "extras": extras or {}})
        return True
    except Exception as e:
        _mirror(title, message, "smtp", priority, {"status": 0, "error": str(e), "extras": extras or {}})
        return False

def send_outputs(title: str, message: str, priority: int = 5, extras: Optional[dict] = None):
    ok = False
    try:
        if _send_gotify(title, message, priority, extras): ok = True
    except Exception:
        pass
    try:
        if _send_ntfy(title, message, priority, extras): ok = True
    except Exception:
        pass
    try:
        if _send_smtp(title, message, priority, extras): ok = True
    except Exception:
        pass
    if not ok:
        _mirror(title, message, "mirror-only", priority, extras or {})

# ---------------------------
# Persona/LLM pipeline
# ---------------------------
def _persona_line(quip_text: str) -> str:
    who = ACTIVE_PERSONA or "neutral"
    qt = (quip_text or "").replace("\n", " ").strip()
    if len(qt) > 140:
        qt = qt[:137] + "..."
    return f"💬 {who} says: {qt}" if qt else f"💬 {who} says:"

def _footer(used_llm: bool, used_beautify: bool) -> str:
    parts = []
    if used_llm: parts.append("Neural Core ✓")
    if used_beautify: parts.append("Aesthetic Engine ✓")
    if not parts: parts.append("Relay Path")
    return "— " + " · ".join(parts)

def _llm_riff_or_rewrite(title: str, text: str) -> Tuple[str, bool]:
    if not LLM_ENABLED:
        return text, False
    if not RIFFS_ENABLED:
        return text, False
    if not llm_client:
        return text, False

    # Prefer dedicated riff() if available
    try:
        if hasattr(llm_client, "riff"):
            t2 = llm_client.riff(
                title=title,
                text=text,
                persona=ACTIVE_PERSONA,
                timeout=int(cfg.get("llm_timeout_seconds", 12)),
                cpu_limit=int(cfg.get("llm_max_cpu_percent", 70)),
                models_priority=cfg.get("llm_models_priority", []),
                base_url=cfg.get("llm_ollama_base_url", ""),
                model_url=cfg.get("llm_model_url", ""),
                model_path=cfg.get("llm_model_path", ""),
                model_sha256=cfg.get("llm_model_sha256", ""),
                allow_profanity=bool(cfg.get("personality_allow_profanity", False))
            )
            if t2:
                return t2, True
    except Exception:
        pass

    # Fallback to rewrite() only if explicitly enabled
    if LLM_REWRITE_ENABLED and hasattr(llm_client, "rewrite"):
        try:
            t3 = llm_client.rewrite(
                text=text,
                mood=ACTIVE_PERSONA,
                timeout=int(cfg.get("llm_timeout_seconds", 12)),
                cpu_limit=int(cfg.get("llm_max_cpu_percent", 70)),
                models_priority=cfg.get("llm_models_priority", []),
                base_url=cfg.get("llm_ollama_base_url", ""),
                model_url=cfg.get("llm_model_url", ""),
                model_path=cfg.get("llm_model_path", ""),
                model_sha256=cfg.get("llm_model_sha256", ""),
                allow_profanity=bool(cfg.get("personality_allow_profanity", False))
            )
            if t3:
                return t3, True
        except Exception:
            pass

    return text, False

def _beautify_overlay(title: str, text: str) -> Tuple[str, Optional[dict], bool]:
    used = False
    extras = None
    # Persona overlays/riffs happen in beautify when BEAUTIFY_LLM_ENABLED=true
    if beautify and hasattr(beautify, "beautify_message") and os.getenv("BEAUTIFY_LLM_ENABLED","false").lower() in ("1","true","yes"):
        try:
            text, extras = beautify.beautify_message(
                title, text,
                mood=ACTIVE_PERSONA,
                persona=ACTIVE_PERSONA,
                persona_quip=True
            )
            used = True
        except Exception:
            pass
    return text, extras, used

def process_and_send(title: str, body: str, priority: int = 5, extras: Optional[dict] = None):
    # Persona quip header (safe even if personality missing)
    try:
        quip = personality.quip(ACTIVE_PERSONA) if (personality and hasattr(personality, "quip")) else ""
    except Exception:
        quip = ""
    header = _persona_line(quip)
    working = (header + ("\n" + (body or ""))) if header else (body or "")

    # LLM path
    text = working
    used_llm = False
    text, used_llm = _llm_riff_or_rewrite(title, text)

    # Beautify overlay
    used_beautify = False
    text, extras2, used_beautify = _beautify_overlay(title, text)

    # Footer
    foot = _footer(used_llm, used_beautify)
    if text and not text.rstrip().endswith(foot):
        text = f"{text.rstrip()}\n\n{foot}"

    final_extras = extras2 if isinstance(extras2, dict) else (extras or {})
    send_outputs(title or "Notification", text, priority=int(priority or 5), extras=final_extras)

# ---------------------------
# Commands / wake-words
# ---------------------------
def _clean(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _normalize_cmd(cmd: str) -> str:
    try:
        if aliases and hasattr(aliases, "normalize_cmd"):
            return aliases.normalize_cmd(cmd)
    except Exception:
        pass
    return _clean(cmd)

def _extract_command_from(title: str, message: str) -> str:
    tlow, mlow = (title or "").lower(), (message or "").lower()
    for kw in WAKE_WORDS:
        if tlow.startswith(kw):
            rest = tlow[len(kw):].strip()
            return rest or (mlow[len(kw):].strip() if mlow.startswith(kw) else mlow.strip())
        if mlow.startswith(kw):
            return mlow[len(kw):].strip()
    # legacy fallback
    if tlow.startswith("jarvis"): return tlow[6:].strip()
    if mlow.startswith("jarvis"): return mlow[6:].strip()
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
            title2, msg2, pr = m_digest.build_digest(cfg)
            try:
                if personality and hasattr(personality, "quip"):
                    msg2 += f"\n\n{personality.quip(ACTIVE_PERSONA)}"
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
    cmd = _extract_command_from(title or "", body or "")
    if not cmd:
        return False
    try:
        if _handle_command(_normalize_cmd(cmd)):
            return True
    except Exception as e:
        try:
            process_and_send("Wake Error", f"{e}", priority=5)
        except Exception:
            pass
    return False

# ---------------------------
# Boot card
# ---------------------------
def post_startup_card():
    try:
        lines = [
            "🧬 Prime Neural Boot — Standalone",
            f"🧠 LLM: {'Enabled' if LLM_ENABLED else 'Disabled'} • Persona riffs: {'ON' if (LLM_ENABLED and RIFFS_ENABLED) else 'OFF'} • LLM rewrite: {'ON' if LLM_REWRITE_ENABLED else 'OFF'}",
            f"🗣️ Active Persona: {ACTIVE_PERSONA} ({PERSONA_TOD})",
            "",
            "Intakes:",
            f"  ▸ SMTP:    {'ACTIVE' if SMTP_INTAKE_ENABLED else 'OFF'} (:{SMTP_INTAKE_PORT})",
            f"  ▸ Webhook: {'ACTIVE' if WEBHOOK_ENABLED else 'OFF'} ({WEBHOOK_BIND}:{WEBHOOK_PORT})",
            f"  ▸ Proxy:   {'ACTIVE' if PROXY_ENABLED else 'OFF'} (:{PROXY_PORT})",
            f"  ▸ Apprise: {'ACTIVE' if APPRISE_ENABLED else 'OFF'} ({APPRISE_BIND}:{APPRISE_PORT})",
            "",
            "Outputs:",
            f"  ▸ Gotify: {'ON' if PUSH_GOTIFY else 'OFF'}",
            f"  ▸ ntfy:   {'ON' if PUSH_NTFY else 'OFF'}",
            f"  ▸ SMTP:   {'ON' if PUSH_SMTP else 'OFF'}",
            "",
            "Modules:",
            f"  ▸ Radarr:       {'ACTIVE' if RADARR_ENABLED else 'OFF'}",
            f"  ▸ Sonarr:       {'ACTIVE' if SONARR_ENABLED else 'OFF'}",
            f"  ▸ Weather:      {'ACTIVE' if WEATHER_ENABLED else 'OFF'}",
            f"  ▸ Digest:       {'ACTIVE' if DIGEST_ENABLED else 'OFF'}",
            f"  ▸ Chat:         {'ACTIVE' if CHAT_ENABLED else 'OFF'}",
            f"  ▸ Uptime Kuma:  {'ACTIVE' if KUMA_ENABLED else 'OFF'}",
            f"  ▸ Technitium:   {'ACTIVE' if TECHNITIUM_ENABLED else 'OFF'}",
            "",
            "Internal API: 127.0.0.1:2599 (/internal/ingest, /internal/wake, /health)",
            f"TCP Health:    127.0.0.1:{HEALTH_PORT}",
            "Wake-words: enabled on every intake",
        ]
        process_and_send("Startup", "\n".join(lines), priority=4, extras=None)
    except Exception:
        print("[boot] startup card skipped")

# ---------------------------
# HTTP server (aiohttp)
# ---------------------------
try:
    from aiohttp import web
except Exception:
    web = None

_recent_hashes: List[str] = []

def _dedup_key(title: str, body: str, prio: int) -> str:
    raw = f"{title}\n{body}\n{prio}".encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()

def _remember(h: str):
    _recent_hashes.append(h)
    if len(_recent_hashes) > 64:
        del _recent_hashes[:len(_recent_hashes)-64]

def _seen(h: str) -> bool:
    return h in _recent_hashes

async def _ingest(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    title  = str(data.get("title") or "Notification")
    body   = str(data.get("message") or data.get("body") or "")
    prio   = int(data.get("priority") or 5)
    extras = data.get("extras") or {}

    k = _dedup_key(title, body, prio)
    if _seen(k):
        return web.json_response({"ok": True, "skipped": "duplicate"})
    _remember(k)

    if _maybe_handle_wakewords(title, body):
        return web.json_response({"ok": True, "handled": "wake"})

    try:
        process_and_send(title, body, priority=prio, extras=extras)
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def _wake(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    text = str(data.get("text") or "").strip()
    cmd = text
    for kw in WAKE_WORDS + ["jarvis"]:
        if cmd.lower().startswith(kw):
            cmd = cmd[len(kw):].strip()
            break
    ok = False
    try:
        ok = bool(_handle_command(_normalize_cmd(cmd)))
    except Exception as e:
        process_and_send("Wake Error", f"{e}", priority=5)
    return web.json_response({"ok": bool(ok)})

async def _health(request):
    return web.json_response({"ok": True, "service": "jarvis_prime", "ts": int(time.time())})

async def _start_http():
    if web is None:
        print("[http] aiohttp missing; HTTP disabled")
        return
    app = web.Application()
    app.router.add_post("/internal/ingest", _ingest)
    app.router.add_post("/internal/wake", _wake)
    app.router.add_get("/health", _health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 2599)
    await site.start()
    print("[http] listening on 127.0.0.1:2599")

# ---------------------------
# TCP health
# ---------------------------
async def _start_tcp_health():
    async def handle(reader, writer):
        try:
            writer.write(b"OK\n")
            await writer.drain()
        finally:
            try:
                writer.close()
            except Exception:
                pass
    try:
        server = await asyncio.start_server(handle, "127.0.0.1", HEALTH_PORT)
        print(f"[health] tcp on 127.0.0.1:{HEALTH_PORT}")
        async with server:
            await server.serve_forever()
    except Exception as e:
        print(f"[health] tcp failed: {e}")

# ---------------------------
# Digest scheduler
# ---------------------------
_last_digest_date = None
async def _digest_scheduler():
    global _last_digest_date
    from datetime import datetime
    while True:
        try:
            if DIGEST_ENABLED:
                target = str(cfg.get("digest_time", "08:00")).strip()
                now = datetime.now()
                if now.strftime("%H:%M") == target and _last_digest_date != now.date():
                    try:
                        import digest as _digest_mod
                        if hasattr(_digest_mod, "build_digest"):
                            title2, msg2, pr = _digest_mod.build_digest(cfg)
                            process_and_send("Digest", msg2, priority=pr)
                    except Exception:
                        pass
                    _last_digest_date = now.date()
        except Exception:
            pass
        await asyncio.sleep(60)

# ---------------------------
# Main
# ---------------------------
_stop_evt = asyncio.Event()

def _on_signal(*_):
    try:
        loop = asyncio.get_event_loop()
        loop.call_soon_threadsafe(_stop_evt.set)
    except Exception:
        pass

def main():
    try:
        start_sidecars()
        post_startup_card()
    except Exception:
        pass
    asyncio.run(_run())

async def _run():
    try:
        asyncio.create_task(_start_http())
        asyncio.create_task(_start_tcp_health())
    except Exception:
        pass
    asyncio.create_task(_digest_scheduler())
    await _stop_evt.wait()
    stop_sidecars()
    await asyncio.sleep(0.1)

if __name__ == "__main__":
    try:
        signal.signal(signal.SIGTERM, _on_signal)
        if hasattr(signal, "SIGINT"):
            signal.signal(signal.SIGINT, _on_signal)
    except Exception:
        pass
    main()