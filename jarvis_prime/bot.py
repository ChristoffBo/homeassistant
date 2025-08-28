#!/usr/bin/env python3
import os, json, time, asyncio, re
from datetime import datetime
from pathlib import Path

import requests
import websockets
import schedule
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

# =============================================================================
# Jarvis Prime - Bot Core (Neural Core edition)
# - Boot banner: ASCII brain + clear subsystem status
# - Startup card: lists Neural Core + model, Memory, and all modules
# - Clean separation: wake-word commands vs normal message rewrite path
# - Optional footer marks engine path: [Neural Core ✓] or [Beautify fallback]
# - Preflight logs show model path, existence, and size
# =============================================================================

# -----------------------------
# Config from env (set in run.sh)
# -----------------------------
BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON = os.getenv("BOT_ICON", "🧠")
GOTIFY_URL = os.getenv("GOTIFY_URL", "")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN", "")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN", "")
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1", "true", "yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1", "true", "yes")
BEAUTIFY_INLINE_IMAGES = os.getenv("BEAUTIFY_INLINE_IMAGES", "false").lower() in ("1", "true", "yes")

# Personality & Neural Core
CHAT_MOOD = os.getenv("CHAT_MOOD", "serious")
PERSONALITY_PERSISTENT = os.getenv("PERSONALITY_PERSISTENT", "true").lower() in ("1","true","yes")
LLM_ENABLED = os.getenv("LLM_ENABLED", "false").lower() in ("1", "true", "yes")
LLM_MEMORY_ENABLED = os.getenv("LLM_MEMORY_ENABLED", "false").lower() in ("1","true","yes")
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "5"))
LLM_MAX_CPU_PERCENT = int(os.getenv("LLM_MAX_CPU_PERCENT", "70"))
LLM_MODEL_PATH = os.getenv("LLM_MODEL_PATH", "")
LLM_MODELS_PRIORITY = [p.strip() for p in os.getenv("LLM_MODELS_PRIORITY", "").split(",") if p.strip()]
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "")
ENGINE_FOOTER_DISABLED = os.getenv("ENGINE_FOOTER_DISABLED", "false").lower() in ("1","true","yes")

# Misc toggles that may get overridden by /data/options.json
RADARR_ENABLED = os.getenv("radarr_enabled", "false").lower() in ("1","true","yes")
SONARR_ENABLED = os.getenv("sonarr_enabled", "false").lower() in ("1","true","yes")
WEATHER_ENABLED = os.getenv("weather_enabled", "false").lower() in ("1","true","yes")
TECHNITIUM_ENABLED = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")
KUMA_ENABLED = os.getenv("uptimekuma_enabled", "false").lower() in ("1","true","yes")
SMTP_ENABLED = os.getenv("smtp_enabled", "false").lower() in ("1","true","yes")
PROXY_ENABLED_ENV = os.getenv("proxy_enabled", "false").lower() in ("1","true","yes")
CHAT_ENABLED_ENV = os.getenv("chat_enabled", "false").lower() in ("1","true","yes")
DIGEST_ENABLED_ENV = os.getenv("digest_enabled", "false").lower() in ("1","true","yes")

AI_CHECKINS_ENABLED = os.getenv("ai_checkins_enabled", "false").lower() in ("1","true","yes")
CACHE_REFRESH_MINUTES = int(os.getenv("cache_refresh_minutes", "60"))

BOOT_TIME = datetime.now()
HEARTBEAT_ENABLED = False
HEARTBEAT_INTERVAL_MIN = 120
HEARTBEAT_START = "06:00"
HEARTBEAT_END = "20:00"

jarvis_app_id = None
extra_modules = {}

# -----------------------------
# Load /data/options.json (overrides)
# -----------------------------
def _load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

merged = {}
try:
    options = _load_json_file("/data/options.json")
    config_fallback = _load_json_file("/data/config.json")
    merged = {**config_fallback, **options}

    # Module toggles
    RADARR_ENABLED = bool(merged.get("radarr_enabled", RADARR_ENABLED))
    SONARR_ENABLED = bool(merged.get("sonarr_enabled", SONARR_ENABLED))
    WEATHER_ENABLED = bool(merged.get("weather_enabled", WEATHER_ENABLED))
    TECHNITIUM_ENABLED = bool(merged.get("technitium_enabled", TECHNITIUM_ENABLED))
    KUMA_ENABLED = bool(merged.get("uptimekuma_enabled", KUMA_ENABLED))
    SMTP_ENABLED = bool(merged.get("smtp_enabled", SMTP_ENABLED))
    PROXY_ENABLED = bool(merged.get("proxy_enabled", PROXY_ENABLED_ENV))

    # Personality / Heartbeat
    CHAT_MOOD = str(merged.get("personality_mood", merged.get("chat_mood", CHAT_MOOD)))
    HEARTBEAT_ENABLED = bool(merged.get("heartbeat_enabled", HEARTBEAT_ENABLED))
    HEARTBEAT_INTERVAL_MIN = int(merged.get("heartbeat_interval_minutes", HEARTBEAT_INTERVAL_MIN))
    HEARTBEAT_START = str(merged.get("heartbeat_start", HEARTBEAT_START))
    HEARTBEAT_END = str(merged.get("heartbeat_end", HEARTBEAT_END))

    BEAUTIFY_INLINE_IMAGES = bool(merged.get("beautify_inline_images", BEAUTIFY_INLINE_IMAGES))

    # Neural Core overrides
    LLM_ENABLED = bool(merged.get("llm_enabled", LLM_ENABLED))
    LLM_MEMORY_ENABLED = bool(merged.get("llm_memory_enabled", LLM_MEMORY_ENABLED))
    LLM_TIMEOUT_SECONDS = int(merged.get("llm_timeout_seconds", LLM_TIMEOUT_SECONDS))
    LLM_MAX_CPU_PERCENT = int(merged.get("llm_max_cpu_percent", LLM_MAX_CPU_PERCENT))
    LLM_MODEL_PATH = str(merged.get("llm_model_path", LLM_MODEL_PATH))
    PERSONALITY_PERSISTENT = bool(merged.get("personality_persistent", PERSONALITY_PERSISTENT))

    # Chat/Digest toggles (file may be source of truth)
    CHAT_ENABLED_FILE = bool(merged.get("chat_enabled", CHAT_ENABLED_ENV))
    DIGEST_ENABLED_FILE = bool(merged.get("digest_enabled", DIGEST_ENABLED_ENV))
except Exception as e:
    print(f"[{BOT_NAME}] ⚠️ Could not load options/config json: {e}")
    PROXY_ENABLED = PROXY_ENABLED_ENV
    CHAT_ENABLED_FILE = CHAT_ENABLED_ENV
    DIGEST_ENABLED_FILE = DIGEST_ENABLED_ENV

# -----------------------------
# Optional dynamic modules
# -----------------------------
def _load_optional(name, path):
    try:
        import importlib.util as _imp
        spec = _imp.spec_from_file_location(name, path)
        if spec and spec.loader:
            mod = _imp.module_from_spec(spec)
            spec.loader.exec_module(mod)
            print(f"[Jarvis Prime] ✅ {name} loaded")
            return mod
    except Exception as e:
        print(f"[Jarvis Prime] ⚠️ {name} not loaded: {e}")
    return None

_alias_mod  = _load_optional("aliases", "/app/aliases.py")
_personality= _load_optional("personality", "/app/personality.py")
_beautify   = _load_optional("beautify", "/app/beautify.py")
_llm        = _load_optional("llm_client", "/app/llm_client.py")
_llm_mem    = _load_optional("llm_memory", "/app/llm_memory.py")
_pstate     = _load_optional("personality_state", "/app/personality_state.py")

# reload persisted mood if present
try:
    if PERSONALITY_PERSISTENT and _pstate and hasattr(_pstate, "load_mood"):
        prev = _pstate.load_mood()
        if prev:
            CHAT_MOOD = prev
except Exception:
    pass

# -----------------------------
# Gotify helpers
# -----------------------------
def send_message(title, message, priority=5, extras=None):
    if _personality:
        try:
            title, message = _personality.decorate(title, message, CHAT_MOOD, chance=1.0)
            priority = _personality.apply_priority(priority, CHAT_MOOD)
        except Exception:
            pass
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    if extras:
        payload["extras"] = extras
    try:
        r = requests.post(url, json=payload, timeout=8)
        r.raise_for_status()
        print(f"[{BOT_NAME}] ✅ Sent: {title}")
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to send message: {e}")
        return False

def delete_original_message(msg_id: int):
    try:
        if not msg_id:
            return
        url = f"{GOTIFY_URL}/message/{msg_id}"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.delete(url, headers=headers, timeout=8)
        if r.status_code in (200, 204):
            print(f"[{BOT_NAME}] 🧹 Purged original message id={msg_id}")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Purge error: {e}")

def resolve_app_id():
    global jarvis_app_id
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=8)
        r.raise_for_status()
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
                print(f"[{BOT_NAME}] 🆔 Resolved app id = {jarvis_app_id}")
                return
        print(f"[{BOT_NAME}] ⚠️ App '{APP_NAME}' not found when resolving app id")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to resolve app id: {e}")

def _is_our_post(data: dict) -> bool:
    try:
        if data.get("appid") == jarvis_app_id:
            return True
        t = data.get("title", "") or ""
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

# -----------------------------
# Memory helpers
# -----------------------------
def mem_log_event(kind: str, source: str, title: str, body: str, meta=None):
    if not (_llm_mem and LLM_MEMORY_ENABLED):
        return
    try:
        if hasattr(_llm_mem, "log_event"):
            try:
                _llm_mem.log_event(kind=kind, source=source, title=title, body=body, meta=meta or {})
            except TypeError:
                try:
                    _llm_mem.log_event(source=source, title=title, body=body, tags=[kind])
                except TypeError:
                    _llm_mem.log_event(source, title, body, [kind])
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Memory log failed: {e}")

def mem_summarize_today(kind_filter=None) -> str:
    if not (_llm_mem and LLM_MEMORY_ENABLED):
        return ""
    try:
        if hasattr(_llm_mem, "what_broke_today") and kind_filter:
            return _llm_mem.what_broke_today()
        if hasattr(_llm_mem, "summarize_today"):
            return _llm_mem.summarize_today()
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Memory summarize failed: {e}")
    try:
        if hasattr(_llm_mem, "query_today"):
            rows = _llm_mem.query_today(keyword_any=kind_filter or [])
            if not rows:
                return "No notable events logged in the last 24h."
            out = []
            for r in rows[-20:]:
                ts = datetime.fromtimestamp(int(r.get("ts", 0))).strftime("%H:%M")
                out.append(f"- {ts} • {r.get('title','(no title)')} — {r.get('source','')}")
            return "Today’s Events:\n" + "\n".join(out)
    except Exception:
        pass
    return ""

# -----------------------------
# Dynamic module loader
# -----------------------------
def try_load_module(modname):
    path = f"/app/{modname}.py"
    enabled = True if modname == "arr" else bool(merged.get(f"{modname}_enabled", os.getenv(f"{modname}_enabled", "false").lower() in ("1","true","yes")))
    if not os.path.exists(path) or not enabled:
        print(f"[{BOT_NAME}] ↩️ Skipping module {modname}: file_exists={os.path.exists(path)} enabled={enabled}")
        return False
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(modname, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        extra_modules[modname] = module
        print(f"[{BOT_NAME}] ✅ Loaded module: {modname}")
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Failed to load {modname}: {e}")
        return False

# -----------------------------
# Fancy boot banner (console)
# -----------------------------
def fancy_boot_banner():
    brain = r"""
      ____          _           _      ____            _
     |__  |  __ _  | |__   __ _| |_   |  _ \ _ __ ___ | |__  _ __   ___
       / /  / _` | | '_ \ / _` | __|  | |_) | '__/ _ \| '_ \| '_ \ / _ \
      / /_ | (_| | | |_) | (_| | |_   |  __/| | | (_) | |_) | | | |  __/
     |____| \__,_| |_.__/ \__,_|\__|  |_|   |_|  \___/|_.__/|_| |_|\___|
    """
    core  = "ENABLED"  if LLM_ENABLED else "DISABLED"
    mem   = "ENABLED"  if LLM_MEMORY_ENABLED else "DISABLED"
    model = Path(LLM_MODEL_PATH.strip()).name if LLM_MODEL_PATH else "(auto)"
    print("─" * 60)
    print(brain)
    print(f"🧠 {BOT_NAME}")
    print("⚡ Boot sequence initiated...")
    print("   → Personalities loaded")
    print("   → Memory core mounted")
    print("   → Network bridges linked")
    print(f"   → Neural Core: {core}")
    print(f"   → Model file: {model}")
    print(f"   → Memory: {mem}")
    # Preflight: path + size
    if LLM_ENABLED:
        p = Path(os.path.expandvars(LLM_MODEL_PATH.strip()))
        ok = p.exists()
        size = (p.stat().st_size if ok else 0)
        print(f"   • Preflight: path='{p}' exists={ok} size={size}")
    print("🚀 Systems online — Jarvis is awake!")
    print("─" * 60)

# -----------------------------
# Startup poster (Gotify card)
# -----------------------------
def _first_model_fallback() -> str:
    base = Path("/share/jarvis_prime/models")
    if base.exists():
        ggufs = sorted([q.name for q in base.glob("*.gguf")])
        return ggufs[0] if ggufs else ""
    return ""

def _present(path:str) -> str:
    if not path:
        alt = _first_model_fallback()
        return f"auto{(' → ' + alt) if alt else ''}"
    p = Path(os.path.expandvars(path.strip()))
    if p.exists():
        return p.name
    # show fallback if available
    alt = _first_model_fallback()
    return f"{p.name} ({'using ' + alt if alt else 'missing'})"

def startup_poster():
    def line(icon, name, enabled):
        return f"{icon} {name} — **{'ACTIVE' if enabled else 'INACTIVE'}**"
    lines = []
    lines.append("🧠 **Prime Neural Boot**")
    lines.append(f"**Mood:** `{CHAT_MOOD}`")
    lines.append("")
    lines.append("### Subsystems")
    lines.append(f"- 🧩 Neural Core — **{'ACTIVE' if LLM_ENABLED else 'DISABLED'}**")
    lines.append(f"  - Model: `{_present(LLM_MODEL_PATH)}`")
    lines.append(f"  - Memory: **{'ACTIVE' if LLM_MEMORY_ENABLED else 'DISABLED'}**")
    lines.append("")
    lines.append("### Modules")
    lines.append(f"- {line('🎬', 'Radarr', RADARR_ENABLED)}")
    lines.append(f"- {line('📺', 'Sonarr', SONARR_ENABLED)}")
    lines.append(f"- {line('🌤', 'Weather', WEATHER_ENABLED)}")
    lines.append(f"- {line('📰', 'Digest', DIGEST_ENABLED_FILE)}")
    lines.append(f"- {line('💬', 'Chat', CHAT_ENABLED_FILE)}")
    lines.append(f"- {line('📡', 'Uptime Kuma', KUMA_ENABLED)}")
    lines.append(f"- {line('✉️', 'SMTP Intake', SMTP_ENABLED)}")
    lines.append(f"- {line('🔀', 'Proxy (Gotify/ntfy)', merged.get('proxy_enabled', PROXY_ENABLED_ENV))}")
    lines.append(f"- {line('🧬', 'DNS (Technitium)', TECHNITIUM_ENABLED)}")
    lines.append("")
    lines.append("_Status: All systems nominal_")
    return "\n".join(lines)

# -----------------------------
# Heartbeat / Digest
# -----------------------------
def _parse_hhmm(s):
    try:
        hh, mm = s.split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return 0

def _in_window(now, start, end):
    mins = now.hour * 60 + now.minute
    a = _parse_hhmm(start); b = _parse_hhmm(end)
    if a == b:
        return True
    if a < b:
        return a <= mins <= b
    return mins >= a or mins <= b

def _fmt_uptime():
    d = datetime.now() - BOOT_TIME
    total = int(d.total_seconds() // 60)
    h, m = divmod(total, 60)
    days, h = divmod(h, 24)
    parts = []
    if days: parts.append(f"{days}d")
    if h: parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts)

def send_heartbeat_if_window():
    try:
        if not HEARTBEAT_ENABLED:
            return
        now = datetime.now()
        if not _in_window(now, HEARTBEAT_START, HEARTBEAT_END):
            return
        lines = [
            "🫀 Heartbeat — Jarvis Prime alive",
            f"Time: {now.strftime('%Y-%m-%d %H:%M')}",
            f"Uptime: {_fmt_uptime()}",
        ]
        if _personality:
            lines.append("")
            lines.append(_personality.quip(CHAT_MOOD))
        send_message("Heartbeat", "\n".join(lines), priority=3)
    except Exception as e:
        print(f"[{BOT_NAME}] Heartbeat error: {e}")

def job_daily_digest():
    try:
        dmod = extra_modules.get("digest")
        if not dmod or not hasattr(dmod, "build_digest"):
            return
        title, msg, prio = dmod.build_digest(merged)
        if _personality:
            msg += f"\n\n{_personality.quip(CHAT_MOOD)}"
        send_message(title, msg, priority=prio)
    except Exception as e:
        print(f"[{BOT_NAME}] Digest error: {e}")

# -----------------------------
# Normalization + command extraction
# -----------------------------
def _clean(s):
    return re.sub(r"\s+", " ", s.lower().strip())

def normalize_cmd(cmd: str) -> str:
    if _alias_mod and hasattr(_alias_mod, "normalize_cmd"):
        try:
            return _alias_mod.normalize_cmd(cmd)
        except Exception:
            pass
    return _clean(cmd)

def extract_command_from(title: str, message: str) -> str:
    tlow, mlow = (title or "").lower(), (message or "").lower()
    if tlow.startswith("jarvis"):
        tcmd = tlow.replace("jarvis", "", 1).strip()
        return tcmd or (mlow.replace("jarvis", "", 1).strip() if mlow.startswith("jarvis") else mlow.strip())
    if mlow.startswith("jarvis"):
        return mlow.replace("jarvis", "", 1).strip()
    return ""

# -----------------------------
# Listener
# -----------------------------
def _llm_rewrite_blocking(input_text: str, mood: str):
    """Call _llm.rewrite_with_info() (if present) and return (text, used_llm: bool)."""
    if not (LLM_ENABLED and _llm and (hasattr(_llm, "rewrite_with_info") or hasattr(_llm, "rewrite"))):
        raise RuntimeError("LLM path unavailable")
    if hasattr(_llm, "rewrite_with_info"):
        return _llm.rewrite_with_info(
            text=input_text,
            mood=mood,
            timeout=LLM_TIMEOUT_SECONDS,
            cpu_limit=LLM_MAX_CPU_PERCENT,
            models_priority=LLM_MODELS_PRIORITY,
            base_url=OLLAMA_BASE_URL,
            model_path=LLM_MODEL_PATH,
        )
    else:
        _out = _llm.rewrite(
            text=input_text,
            mood=mood,
            timeout=LLM_TIMEOUT_SECONDS,
            cpu_limit=LLM_MAX_CPU_PERCENT,
            models_priority=LLM_MODELS_PRIORITY,
            base_url=OLLAMA_BASE_URL,
            model_path=LLM_MODEL_PATH,
        )
        return _out, True

async def listen():
    ws_url = GOTIFY_URL.replace("http://", "ws://").replace("https://", "wss://") + f"/stream?token={CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] Connecting {ws_url}")
    async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
        print(f"[{BOT_NAME}] ✅ Connected")
        async for msg in ws:
            try:
                data = json.loads(msg)
                msg_id = data.get("id")

                if _is_our_post(data):
                    continue

                title = data.get("title", "") or ""
                message = data.get("message", "") or ""
                appname = (data.get("app", {}) or {}).get("name") or str(data.get("appid") or "gotify")

                # Wake-word?
                ncmd = normalize_cmd(extract_command_from(title, message))
                if ncmd:
                    handled = False

                    if ncmd in ("help", "commands"):
                        help_text = (
                            "🤖 Jarvis Prime — Commands\n"
                            f"Mood: {CHAT_MOOD}\n\n"
                            "Core:\n"
                            "  • dns — Technitium DNS summary\n"
                            "  • kuma — Uptime Kuma status\n"
                            "  • weather / forecast\n"
                            "  • digest — Daily digest now\n"
                            "  • joke — One short joke\n\n"
                            "Media:\n"
                            "  • upcoming movies / upcoming series\n"
                            "  • movie count / series count\n"
                            "  • longest movie / longest series\n"
                        )
                        send_message("Help", help_text); handled = True

                    elif ncmd in ("digest", "daily digest", "summary"):
                        job_daily_digest(); handled = True

                    elif TECHNITIUM_ENABLED and "technitium" in extra_modules and re.search(r"\bdns\b|technitium", ncmd):
                        out = extra_modules["technitium"].handle_dns_command(ncmd)
                        if isinstance(out, tuple):
                            send_message("DNS", out[0], extras=(out[1] if len(out) > 1 else None))
                        elif isinstance(out, str) and out:
                            send_message("DNS", out)
                        handled = True

                    elif KUMA_ENABLED and "uptimekuma" in extra_modules and re.search(r"\bkuma\b|\buptime\b|\bmonitor", ncmd):
                        out = extra_modules["uptimekuma"].handle_kuma_command(ncmd)
                        if isinstance(out, tuple):
                            send_message("Kuma", out[0], extras=(out[1] if len(out) > 1 else None))
                        elif isinstance(out, str) and out:
                            send_message("Kuma", out)
                        handled = True

                    elif WEATHER_ENABLED and "weather" in extra_modules and any(w in ncmd for w in ("weather","forecast","temperature","temp","now","today","current","weekly","7day","7-day","7 day")):
                        w = extra_modules["weather"].handle_weather_command(ncmd)
                        if isinstance(w, tuple) and w and w[0]:
                            msg_text = w[0]; extras = (w[1] if len(w) > 1 else None)
                            if _personality: msg_text = f"{msg_text}\n\n{_personality.quip(CHAT_MOOD)}"
                            send_message("Weather", msg_text, extras=extras)
                        elif isinstance(w, str) and w:
                            msg_text = w
                            if _personality: msg_text = f"{msg_text}\n\n{_personality.quip(CHAT_MOOD)}"
                            send_message("Weather", msg_text)
                        handled = True

                    elif (merged.get("chat_enabled", CHAT_ENABLED_ENV)) and "chat" in extra_modules and ("joke" in ncmd or "pun" in ncmd):
                        c = extra_modules["chat"].handle_chat_command("joke")
                        if isinstance(c, tuple):
                            send_message("Joke", c[0], extras=(c[1] if len(c) > 1 else None))
                        else:
                            send_message("Joke", str(c))
                        handled = True

                    elif "arr" in extra_modules and hasattr(extra_modules["arr"], "handle_arr_command"):
                        r = extra_modules["arr"].handle_arr_command(title, message)
                        if isinstance(r, tuple) and r and r[0]:
                            extras = r[1] if len(r) > 1 else None
                            msg_text = r[0]
                            if _personality: msg_text = f"{msg_text}\n\n{_personality.quip(CHAT_MOOD)}"
                            send_message("Jarvis", msg_text, extras=extras)
                        elif isinstance(r, str) and r:
                            msg_text = r
                            if _personality: msg_text = f"{msg_text}\n\n{_personality.quip(CHAT_MOOD)}"
                            send_message("Jarvis", msg_text)
                        handled = True

                    elif LLM_MEMORY_ENABLED and re.search(r"\bwhat\s+happened\s+today\b", ncmd):
                        out = mem_summarize_today([])
                        send_message("Today", out or "No notable events in the last 24h."); handled = True

                    elif LLM_MEMORY_ENABLED and re.search(r"\bwhat\s+broke\s+today\b", ncmd):
                        out = mem_summarize_today(["error","down","failed","alert"])
                        send_message("Issues", out or "No issues detected in the last 24h."); handled = True

                    elif re.search(r"\bmood\s+(serious|sarcastic|playful|hacker-noir|angry)\b", ncmd):
                        newm = re.search(r"\bmood\s+(serious|sarcastic|playful|hacker-noir|angry)\b", ncmd).group(1)
                        globals()["CHAT_MOOD"] = newm
                        if PERSONALITY_PERSISTENT and _pstate and hasattr(_pstate, "save_mood"):
                            try: _pstate.save_mood(newm)
                            except Exception as _e: print(f"[{BOT_NAME}] ⚠️ Mood save failed: {_e}")
                        send_message("Mood", f"Personality set to **{CHAT_MOOD}**"); handled = True

                    else:
                        if _personality and hasattr(_personality, "unknown_command_response"):
                            resp = _personality.unknown_command_response(ncmd, CHAT_MOOD)
                        else:
                            resp = f"Unknown command: {ncmd}"
                        send_message("Jarvis", resp); handled = True

                    if handled:
                        _purge_after(msg_id)
                        continue  # handled wake-word; next WS msg

                # ---------- Non wake-word path: rewrite + beautify ----------
                engine_used = "Beautify fallback"
                transformed = message
                extras = None

                # Build richer context for the LLM
                llm_input = (title or "").strip()
                if message.strip():
                    llm_input = (llm_input + "\n\n" + message.strip()).strip()

                if LLM_ENABLED and _llm and hasattr(_llm, "rewrite"):
                    print(f"[{BOT_NAME}] 🔧 Neural Core attempt (mood={CHAT_MOOD}, timeout={LLM_TIMEOUT_SECONDS}s)")
                    def _call():
                        return _llm_rewrite_blocking(llm_input, CHAT_MOOD)

                    try:
                        with ThreadPoolExecutor(max_workers=1) as ex:
                            fut = ex.submit(_call)
                            transformed, used = fut.result(timeout=max(1, LLM_TIMEOUT_SECONDS))
                            engine_used = "Neural Core ✓" if used else "Beautify fallback"
                            print(f"[{BOT_NAME}] 🧠 Neural Core rewrite OK")
                    except FuturesTimeout:
                        print(f"[{BOT_NAME}] ⏱️ Neural Core timeout after {LLM_TIMEOUT_SECONDS}s → fallback")
                    except Exception as _e:
                        print(f"[{BOT_NAME}] ⚠️ Neural Core error: {_e}")

                final = transformed if engine_used == "Neural Core ✓" else message

                try:
                    if BEAUTIFY_ENABLED and _beautify and hasattr(_beautify, "beautify_message"):
                        source_for_beautify = transformed if engine_used == "Neural Core ✓" else message
                        final, extras = _beautify.beautify_message(title, source_for_beautify, mood=CHAT_MOOD)
                except Exception as _e:
                    print(f"[{BOT_NAME}] ⚠️ Beautify failed: {_e}")

                if not ENGINE_FOOTER_DISABLED:
                    final = f"{final}\n\n`[{engine_used}]`"

                try:
                    mem_log_event(kind=appname.lower(), source=appname, title=(title or "Message"), body=final, meta={"id": msg_id})
                except Exception as _e:
                    print(f"[{BOT_NAME}] ⚠️ Memory log error: {_e}")

                try:
                    if BEAUTIFY_INLINE_IMAGES and extras and extras.get("client::notification", {}).get("bigImageUrl"):
                        img = extras["client::notification"]["bigImageUrl"]
                        final = f"![image]({img})\n\n{final}"
                except Exception:
                    pass

                try:
                    if _personality:
                        q = _personality.quip(CHAT_MOOD)
                        if q:
                            final = f"{final}\n\n— {q}"
                except Exception:
                    pass

                send_message(title, final, extras=extras)
                _purge_after(msg_id)

            except Exception as e:
                print(f"[{BOT_NAME}] Listener error: {e}")

# -----------------------------
# Scheduler
# -----------------------------
def run_scheduler():
    schedule.every(RETENTION_HOURS).hours.do(lambda: None)

    if HEARTBEAT_ENABLED and HEARTBEAT_INTERVAL_MIN > 0:
        schedule.every(HEARTBEAT_INTERVAL_MIN).minutes.do(send_heartbeat_if_window)

    try:
        if DIGEST_ENABLED_FILE:
            dtime = str(merged.get("digest_time", "08:00")).strip()
            if re.match(r"^\d{2}:\d{2}(:\d{2})?$", dtime):
                schedule.every().day.at(dtime).do(job_daily_digest)
                print(f"[{BOT_NAME}] [Digest] scheduled @ {dtime}")
            else:
                print(f"[{BOT_NAME}] [Digest] ⚠️ Invalid time '{dtime}' → skipping")
    except Exception as e:
        print(f"[{BOT_NAME}] [Digest] schedule error: {e}")

    while True:
        schedule.run_pending()
        time.sleep(1)

# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    # Ensure share dirs exist
    try:
        Path("/share/jarvis_prime/memory").mkdir(parents=True, exist_ok=True)
        Path("/share/jarvis_prime/models").mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    fancy_boot_banner()
    resolve_app_id()

    # Load modules
    try_load_module("arr")
    try_load_module("chat")
    try_load_module("weather")
    try_load_module("technitium")
    try_load_module("uptimekuma")
    try_load_module("digest")

    # Start SMTP
    try:
        if SMTP_ENABLED and bool(merged.get("smtp_enabled", SMTP_ENABLED)):
            import importlib.util as _imp
            _sspec = _imp.spec_from_file_location("smtp_server", "/app/smtp_server.py")
            if _sspec and _sspec.loader:
                _smtp_mod = _imp.module_from_spec(_sspec)
                _sspec.loader.exec_module(_smtp_mod)
                _smtp_mod.start_smtp(merged, send_message)
                print("[Jarvis Prime] ✅ SMTP intake started")
            else:
                print("[Jarvis Prime] ⚠️ smtp_server.py not found")
    except Exception as e:
        print(f"[Jarvis Prime] ⚠️ SMTP start error: {e}")

    # Start Proxy
    try:
        if bool(merged.get("proxy_enabled", PROXY_ENABLED_ENV)):
            import importlib.util as _imp
            _pxspec = _imp.spec_from_file_location("proxy", "/app/proxy.py")
            if _pxspec and _pxspec.loader:
                _proxy_mod = _imp.module_from_spec(_pxspec)
                _pxspec.loader.exec_module(_proxy_mod)
                _proxy_mod.start_proxy(merged, send_message)
                print("[Jarvis Prime] ✅ Proxy started")
            else:
                print("[Jarvis Prime] ⚠️ proxy.py not found")
    except Exception as e:
        print(f"[Jarvis Prime] ⚠️ Proxy start error: {e}")

    # Startup card
    send_message("Startup", startup_poster(), priority=5)

    # Seed memory with boot
    try:
        mem_log_event("system", "system", "Jarvis boot", "Startup sequence completed", meta={"version": "boot"})
    except Exception:
        pass

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
