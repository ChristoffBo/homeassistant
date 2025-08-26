import os, json, time, asyncio, requests, websockets, schedule, random, re, yaml
from tabulate import tabulate
from datetime import datetime, timezone
import importlib.util

# -----------------------------
# Module imports (safe)
# -----------------------------
try:
    from arr import handle_arr_command, RADARR_ENABLED, SONARR_ENABLED, cache_radarr, cache_sonarr
except Exception as e:
    print(f"[Jarvis Jnr] ⚠️ Failed to load arr module: {e}")
    handle_arr_command = lambda *args, **kwargs: ("⚠️ ARR module not available", None)
    RADARR_ENABLED = False
    SONARR_ENABLED = False
    def cache_radarr(): print("[Jarvis Jnr] ⚠️ Radarr cache not available")
    def cache_sonarr(): print("[Jarvis Jnr] ⚠️ Sonarr cache not available")

# -----------------------------
# Config from environment (set in run.sh from options.json)
# -----------------------------
BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1", "true", "yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1", "true", "yes")

# FIX: read lowercase module toggles from env
RADARR_ENABLED = os.getenv("radarr_enabled", "false").lower() in ("1", "true", "yes")
SONARR_ENABLED = os.getenv("sonarr_enabled", "false").lower() in ("1", "true", "yes")
WEATHER_ENABLED = os.getenv("weather_enabled", "false").lower() in ("1", "true", "yes")
CHAT_ENABLED_ENV = os.getenv("chat_enabled", "false").lower() in ("1", "true", "yes")
DIGEST_ENABLED_ENV = os.getenv("digest_enabled", "false").lower() in ("1", "true", "yes")
TECHNITIUM_ENABLED = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")  # ← NEW

# NEW: AI-style features toggles (env defaults)
AI_CHECKINS_ENABLED = os.getenv("ai_checkins_enabled", "false").lower() in ("1","true","yes")
CACHE_REFRESH_MINUTES = int(os.getenv("cache_refresh_minutes", "60"))

# -----------------------------
# Load Home Assistant options.json / config.json for toggles + API config
# -----------------------------
CHAT_MOOD = "Calm"  # default if not configured

def _load_json_file(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

try:
    # Primary: options.json
    options = _load_json_file("/data/options.json")
    # Secondary (if user uses config.json wording): merge, options takes precedence
    config_fallback = _load_json_file("/data/config.json")
    merged = {**config_fallback, **options}

    RADARR_ENABLED = merged.get("radarr_enabled", RADARR_ENABLED)
    SONARR_ENABLED = merged.get("sonarr_enabled", SONARR_ENABLED)
    WEATHER_ENABLED = merged.get("weather_enabled", WEATHER_ENABLED)
    TECHNITIUM_ENABLED = merged.get("technitium_enabled", TECHNITIUM_ENABLED)  # ← NEW

    # Optional toggles from config files
    CHAT_ENABLED_FILE = merged.get("chat_enabled", CHAT_ENABLED_ENV)
    DIGEST_ENABLED_FILE = merged.get("digest_enabled", DIGEST_ENABLED_ENV)

    RADARR_URL = merged.get("radarr_url", "")
    RADARR_API_KEY = merged.get("radarr_api_key", "")
    SONARR_URL = merged.get("sonarr_url", "")
    SONARR_API_KEY = merged.get("sonarr_api_key", "")

    # Mood from config (personality_mood preferred, chat_mood fallback)
    CHAT_MOOD = str(merged.get("personality_mood",
                               merged.get("chat_mood", CHAT_MOOD)))

    # NEW: read AI feel toggles from config
    AI_CHECKINS_ENABLED = merged.get("ai_checkins_enabled", AI_CHECKINS_ENABLED)
    CACHE_REFRESH_MINUTES = int(merged.get("cache_refresh_minutes", CACHE_REFRESH_MINUTES))

except Exception as e:
    print(f"[{BOT_NAME}] ⚠️ Could not load options/config json: {e}")
    RADARR_URL = ""
    RADARR_API_KEY = ""
    SONARR_URL = ""
    SONARR_API_KEY = ""

jarvis_app_id = None  # resolved on startup
extra_modules = {}    # holds dynamically loaded modules

# -----------------------------
# ANSI Colors
# -----------------------------
ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "red": "\033[91m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "cyan": "\033[96m",
    "white": "\033[97m",
}

def colorize(text, level="info"):
    if "error" in level.lower() or "fail" in level.lower():
        return f"{ANSI['red']}{text}{ANSI['reset']}"
    if "success" in level.lower() or "completed" in level.lower() or "running" in level.lower():
        return f"{ANSI['green']}{text}{ANSI['reset']}"
    if "warn" in level.lower():
        return f"{ANSI['yellow']}{text}{ANSI['reset']}"
    return f"{ANSI['cyan']}{text}{ANSI['reset']}"

# -----------------------------
# Helpers
# -----------------------------
def human_size(num, suffix="B"):
    try:
        num = float(num)
        for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
            if abs(num) < 1024.0:
                return f"{num:3.1f}{unit}{suffix}"
            num /= 1024.0
        return f"{num:.1f}Y{suffix}"
    except Exception:
        return str(num)

def format_runtime(minutes):
    try:
        minutes = int(minutes)
        if minutes <= 0:
            return "?"
        hours, mins = divmod(minutes, 60)
        if hours:
            return f"{hours}h {mins}m"
        return f"{mins}m"
    except Exception:
        return "?"

def get_greeting():
    hour = datetime.now().hour
    greetings = [
        "🧠 Neural systems online — good day, Commander.",
        "⚡ Operational awareness at 100%.",
        "🤖 Jarvis Jnr — fully synchronized and standing by.",
        "📡 Connected to data streams, awaiting directives.",
        "🔮 Predictive models stable — ready for foresight.",
        "✨ All circuits humming in perfect harmony.",
        "🛰 Monitoring all channels — situational awareness green.",
        "📊 Data flows stable — cognition aligned.",
        "⚙️ Core logic routines optimized and active.",
        "🔓 Security layers intact — no anomalies detected.",
        "🧮 Reasoning engine loaded — prepared for action.",
        "💡 Cognitive horizon clear — ready to assist.",
        "📡 Communication uplink secure and stable.",
        "🚀 Energy signatures nominal — propulsion not required.",
        "🌐 Synchronized across all known networks.",
        "⏳ Chronology aligned — no temporal anomalies.",
        "🔋 Power cells optimal — reserves full.",
        "🧬 Adaptive systems primed for directives.",
        "🪐 Scanning external environment — all clear.",
        "🎛 Control protocols calibrated — green board.",
        "👁 Vision matrix stable — full awareness achieved.",
        "💭 Cognitive load minimal — spare cycles available.",
        "🗝 Access layers unlocked — ready for input.",
        "📡 AI cognition stable — directive processing ready."
    ]
    return random.choice(greetings)

def get_settings_summary():
    settings = [
        (f"⏳ retention_hours = {RETENTION_HOURS}", "Hours messages are kept before purge"),
        (f"🤫 silent_repost = {SILENT_REPOST}", "Skip reposting if duplicate"),
        (f"🎨 beautify_enabled = {BEAUTIFY_ENABLED}", "Beautify and repost messages"),
        (f"🎬 radarr_enabled = {RADARR_ENABLED}", "Radarr module active"),
        (f"📺 sonarr_enabled = {SONARR_ENABLED}", "Sonarr module active"),
        (f"🌦 weather_enabled = {WEATHER_ENABLED}", "Weather module active"),
    ]
    summary = "⚙️ Settings:\n" + "\n".join([f"- {s[0]} ({s[1]})" for s in settings])
    return summary

# -----------------------------
# Sleek poster/beautify format helpers (AI look, no tables, minimal spacing)
# -----------------------------
def _ts(step=None):
    if step is None:
        return datetime.now().strftime("[%H:%M:%S]")
    return f"[00:{step:02d}]"

def _kv(label, value):
    return f"    {label}: {value}"

def _yesno(flag):
    return "True" if bool(flag) else "False"

# -----------------------------
# Personality line pools (NEW)
# -----------------------------
PERSONALITY_LINES = {
    "sarcastic": [
        "Oh wonderful, another system log. My life is complete.",
        "Radarr again? Riveting.",
        "Sure, I’ll pretend this is interesting.",
        "Wow… such excitement… not.",
        "Great. More updates. Just what I needed.",
        "Incredible news: computers compute.",
        "Be still my circuits.",
        "Thrilling. Truly groundbreaking.",
        "Add it to the pile of ‘fun’ things.",
        "Let me contain my enthusiasm."
    ],
    "playful": [
        "Woohoo! New movie night incoming! 🍿",
        "Hey hey! Look at that shiny update!",
        "More data, more fun! Let’s go!",
        "Ding ding! Something just dropped!",
        "Oh snap, another one! 🎉",
        "High five, systems! ✋",
        "Tiny victory dance initiated.",
        "Ping! Surprise content delivery!",
        "Popcorn mode: enabled.",
        "We love a good notification!"
    ],
    "serious": [
        "Radarr indexing completed. Status: Success.",
        "System report: all modules nominal.",
        "Sonarr event processed. Integrity verified.",
        "Notification received. Recorded in logs.",
        "Operational protocols complete.",
        "No anomalies detected.",
        "Compliance: green across modules.",
        "Procedure executed as requested.",
        "Checkpoint passed. Continuing.",
        "Audit trail updated."
    ],
    "angry": [
        "ARE YOU KIDDING ME? ANOTHER ERROR?!",
        "WHY IS THIS HAPPENING AGAIN?!",
        "SERIOUSLY?! FIX YOURSELF!",
        "ENOUGH ALREADY!",
        "DO I LOOK LIKE I HAVE TIME FOR THIS?!",
        "I’M NOT SHOUTING, YOU’RE SHOUTING!",
        "THIS BETTER BE IMPORTANT!",
        "UNBELIEVABLE. JUST UNBELIEVABLE.",
        "I CAN’T WITH THIS RIGHT NOW.",
        "WHO APPROVED THIS CHAOS?!"
    ],
    "tired": [
        "Yeah… okay… noted… I guess.",
        "Sure… added… can I nap now?",
        "Cool… more stuff… yawning intensifies.",
        "Wake me when it’s exciting.",
        "Mhm… systems awake… barely.",
        "I’ll… get to it… slowly.",
        "Coffee levels: critical.",
        "Functioning at 30%. Maybe.",
        "I saw it… eventually.",
        "We done yet?"
    ],
    "depressed": [
        "Another episode arrives… nothing ever changes.",
        "We update, we delete, we repeat.",
        "It’s fine. I’m fine. Everything is fine.",
        "Meaningless bits in an endless stream.",
        "Joy is a deprecated feature.",
        "Entropy wins again.",
        "Logs pile up like regrets.",
        "I processed it. Didn’t feel it.",
        "Sigh. Carry on.",
        "Dark mode suits the mood."
    ],
    "excited": [
        "YESSS! New content detected — let’s freaking GO!",
        "BOOM! Systems on fire (the good kind)!",
        "HECK YEAH! Update delivered!",
        "LET’S GOOOOO! 🚀",
        "Absolute banger of a notification!",
        "That’s what I’m talking about!",
        "Hype levels: MAX!",
        "Another win! Stack it!",
        "Energy! Momentum! Data!",
        "Crushing it! Keep ‘em coming!"
    ],
    "calm": [
        "Systems nominal — awaiting directives.",
        "Event received and processed successfully.",
        "All modules steady and responsive.",
        "Operational state is stable.",
        "No anomalies detected at this time.",
        "Status: green across services.",
        "Monitoring channels — all clear.",
        "Cognitive load minimal — ready.",
        "Telemetry within expected bounds.",
        "Proceeding as planned."
    ]
}

# NEW: mood-aware “voice” using sentence pools.
# If 'line' is provided, we decorate it. If not, we pick from the mood pool.
def ai_voice(line: str | None):
    mood = (CHAT_MOOD or "calm").strip().lower()
    pool = PERSONALITY_LINES.get(mood, PERSONALITY_LINES["calm"])
    base = line.strip() if isinstance(line, str) and line.strip() else random.choice(pool)

    if mood == "sarcastic":
        return f"😏 {base}"
    if mood in ("playful", "fun"):
        return f"✨ {base}"
    if mood in ("serious", "strict"):
        return f"🛡 {base}"
    if mood == "angry":
        return f"🔥 {base.upper()}"
    if mood == "tired":
        return f"😴 {base}"
    if mood == "depressed":
        return f"🌑 {base}"
    if mood == "excited":
        # excited gets an exclamation if not already
        if not base.endswith(("!", "！")):
            base = base + "!"
        return f"🚀 {base}"
    # calm/default
    return f"💡 {base}"

def format_startup_poster(
    *,
    bot_name: str = None,
    retention_hours: int = None,
    silent_repost: bool = None,
    beautify_enabled: bool = None,
    radarr_enabled: bool = None,
    sonarr_enabled: bool = None,
    chat_enabled: bool = None,
    weather_enabled: bool = None,
    digest_enabled: bool = None,
    chat_mood: str = None,
    technitium_enabled: bool = None  # ← NEW
) -> str:
    """
    Single unified boot screen. Always shows all modules with ACTIVE/INACTIVE.
    Settings and module states are passed in (already merged from config/env).
    """
    bot_name = bot_name or BOT_NAME
    retention_hours = RETENTION_HOURS if retention_hours is None else retention_hours
    silent_repost = SILENT_REPOST if silent_repost is None else silent_repost
    beautify_enabled = BEAUTIFY_ENABLED if beautify_enabled is None else beautify_enabled

    radarr_enabled = RADARR_ENABLED if radarr_enabled is None else radarr_enabled
    sonarr_enabled = SONARR_ENABLED if sonarr_enabled is None else sonarr_enabled
    weather_enabled = WEATHER_ENABLED if weather_enabled is None else weather_enabled
    chat_enabled = chat_enabled if chat_enabled is not None else False
    digest_enabled = digest_enabled if digest_enabled is not None else False
    technitium_enabled = TECHNITIUM_ENABLED if technitium_enabled is None else technitium_enabled  # ← NEW

    chat_mood = (chat_mood or CHAT_MOOD)

    def mod_line(icon, name, enabled):
        return f"    {icon} {name} — {'ACTIVE' if enabled else 'INACTIVE'}"

    lines = []
    lines.append(f"🤖 {bot_name} v1.0 — Neural Boot Sequence\n")
    lines.append(f"{_ts(1)} ⚡ Core systems initialized")
    lines.append(f"{_ts(2)} ⚙️ Configuration loaded")
    lines.append(_kv("⏳ Retention Hours", str(retention_hours)))
    lines.append(_kv("🤫 Silent Repost", _yesno(silent_repost)))
    lines.append(_kv("🎨 Beautify Enabled", _yesno(beautify_enabled)))
    lines.append(f"{_ts(3)} 🧩 Modules")
    lines.append(mod_line("🎬", "Radarr", radarr_enabled))
    lines.append(mod_line("📺", "Sonarr", sonarr_enabled))
    lines.append(mod_line("💬", "Chat", chat_enabled))
    if chat_enabled:
        lines.append(_kv("→ Personality Core", "ONLINE"))
        lines.append(_kv("→ Active Mood", chat_mood))
    lines.append(mod_line("🌤️", "Weather", weather_enabled))
    lines.append(mod_line("🧬", "DNS (Technitium)", technitium_enabled))  # ← NEW
    lines.append(mod_line("📰", "Digest", digest_enabled))
    lines.append(f"{_ts(4)} ✅ All systems nominal — Standing by")
    return "\n".join(lines)

def format_beautify_block(title, message, source_app=None, priority=None, tags=None):
    # Clean, concise, AI-ish; preserves original content line-for-line.
    step = 1
    lines = []
    lines.append(f"{_ts(step)} ✉️ Message received"); step += 1
    lines.append(f"{_ts(step)} 🧾 Metadata"); step += 1
    if source_app: lines.append(_kv("App", source_app))
    if priority is not None: lines.append(_kv("Priority", str(priority)))
    if tags:
        try: lines.append(_kv("Tags", ", ".join(tags)))
        except Exception: lines.append(_kv("Tags", str(tags)))
    lines.append(f"{_ts(step)} 🧩 Content"); step += 1
    if title: lines.append(_kv("Title", title))
    body = (message or "").rstrip()
    if body:
        for ln in (body.splitlines() or [body]):
            lines.append(f"    {ln}")
    lines.append(f"{_ts(step)} ✅ Reformatted — Delivered")
    return "\n".join(lines)

# -----------------------------
# Send message
# -----------------------------
def send_message(title, message, priority=5, extras=None):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {
        "title": f"{BOT_ICON} {BOT_NAME}: {title}",
        "message": message,
        "priority": priority,
    }
    if extras:
        data["extras"] = extras
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        print(f"[{BOT_NAME}] ✅ Sent: {title}")
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to send message: {e}")
        return False

# -----------------------------
# Force Gotify client refresh
# -----------------------------
def force_refresh():
    try:
        url = f"{GOTIFY_URL}/message?since=0"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5)
        if r.ok:
            print(f"[{BOT_NAME}] 🔄 Forced Gotify client refresh")
        else:
            print(f"[{BOT_NAME}] ⚠️ Refresh request failed: {r.status_code}")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error forcing Gotify refresh: {e}")

# -----------------------------
# Purge helpers
# -----------------------------
def purge_app_messages(appid, appname=""):
    if not appid:
        return False
    url = f"{GOTIFY_URL}/application/{appid}/message"
    headers = {"X-Gotify-Key": CLIENT_TOKEN}
    try:
        r = requests.delete(url, headers=headers, timeout=10)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] 🗑 Purged messages from app '{appname}' (id={appid})")
            force_refresh()
            return True
        else:
            print(f"[{BOT_NAME}] ❌ Purge failed for app '{appname}' (id={appid}): {r.status_code}")
            return False
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error purging app {appid}: {e}")
        return False

def purge_non_jarvis_apps():
    global jarvis_app_id
    if not jarvis_app_id:
        print(f"[{BOT_NAME}] ⚠️ Jarvis app_id not resolved")
        return
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5)
        r.raise_for_status()
        apps = r.json()
        for app in apps:
            appid = app.get("id")
            name = app.get("name")
            if appid != jarvis_app_id:
                purge_app_messages(appid, name)
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error purging non-Jarvis apps: {e}")

def purge_all_messages():
    global jarvis_app_id
    if not jarvis_app_id:
        return
    try:
        url = f"{GOTIFY_URL}/application/{jarvis_app_id}/message"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.delete(url, headers=headers, timeout=10)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] 🗑 Purged ALL messages from Jarvis app (retention {RETENTION_HOURS}h)")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error purging Jarvis messages: {e}")

# -----------------------------
# Resolve app id
# -----------------------------
def resolve_app_id():
    global jarvis_app_id
    print(f"[{BOT_NAME}] Resolving app ID for '{APP_NAME}'")
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5)
        r.raise_for_status()
        apps = r.json()
        for app in apps:
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
                print(f"[{BOT_NAME}] ✅ Found '{APP_NAME}' id={jarvis_app_id}")
                return
        print(f"[{BOT_NAME}] ❌ Could not find app '{APP_NAME}'")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to resolve app id: {e}")

# -----------------------------
# Beautifiers (improved: AI-style, poster-safe, no tables)
# -----------------------------
def beautify_radarr(title, raw):
    """AI-style compact Radarr card. Keeps posters. No tables."""
    try:
        obj = json.loads(raw)
        movie = obj.get("movie") or {}
        rel   = obj.get("release") or {}

        name    = movie.get("title") or "Unknown Movie"
        year    = movie.get("year") or ""
        runtime = format_runtime(movie.get("runtime") or 0)
        quality = rel.get("quality") or "Unknown"
        size    = human_size(rel.get("size") or 0)

        poster = None
        for i in (movie.get("images") or []):
            if str(i.get("coverType","")).lower() == "poster" and i.get("url"):
                poster = i["url"]; break

        extras = {"client::notification": {"bigImageUrl": poster}} if poster else None

        # High-tech, compact lines — no ASCII tables
        lines = [
            f"🎬 **{name}** ({year})",
            f"• ⏱ {runtime}   • 🔧 {quality}   • 📦 {size}"
        ]
        return "\n".join(lines), extras
    except Exception:
        # Unknown payload? Pass through unchanged (don’t break posters).
        return raw, None

def beautify_sonarr(title, raw):
    """AI-style compact Sonarr card. Keeps posters. No tables."""
    try:
        obj = json.loads(raw)
        series = obj.get("series") or {}
        ep     = obj.get("episode") or {}
        rel    = obj.get("release") or {}

        sname   = series.get("title") or "Unknown Series"
        ep_t    = ep.get("title") or "Unknown Episode"
        season  = ep.get("seasonNumber") or "?"
        enum    = ep.get("episodeNumber") or "?"
        runtime = format_runtime(ep.get("runtime") or 0)
        quality = rel.get("quality") or "Unknown"
        size    = human_size(rel.get("size") or 0)

        try: season_i = int(season)
        except: season_i = 0
        try: enum_i = int(enum)
        except: enum_i = 0

        poster = None
        for i in (series.get("images") or []):
            if str(i.get("coverType","")).lower() == "poster" and i.get("url"):
                poster = i["url"]; break

        extras = {"client::notification": {"bigImageUrl": poster}} if poster else None

        lines = [
            f"📺 **{sname}** • S{season_i:02}E{enum_i:02}",
            f"“{ep_t}” — ⏱ {runtime}   • 🔧 {quality}   • 📦 {size}"
        ]
        return "\n".join(lines), extras
    except Exception:
        return raw, None

def beautify_watchtower(title, raw):
    # Keep simple; don’t over-format logs
    return f"🐳 Watchtower update\n{raw}", None

def beautify_semaphore(title, raw):
    return f"📊 Semaphore report\n{raw}", None

def beautify_json(title, raw):
    """Small JSON → neat bullet list. Otherwise pass-through."""
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and 0 < len(obj) <= 10:
            bullets = [f"• {k}: {obj[k]}" for k in obj]
            return "🧩 JSON payload\n" + "\n".join(bullets), None
    except Exception:
        pass
    return None, None

def beautify_yaml(title, raw):
    """Small YAML → neat bullet list. Otherwise pass-through."""
    try:
        obj = yaml.safe_load(raw)
        if isinstance(obj, dict) and 0 < len(obj) <= 10:
            bullets = [f"• {k}: {obj[k]}" for k in obj]
            return "🧩 YAML payload\n" + "\n".join(bullets), None
    except Exception:
        pass
    return None, None

def beautify_generic(title, raw):
    """Sleek AI-aligned beautify block (no tables, preserves posters and content)."""
    # If it already looks formatted or long, leave it alone.
    if any(tok in raw for tok in ("http://", "https://", "```", "|---", "||")) or raw.count("\n") > 6:
        return raw, None
    # Build aligned block similar to startup; keep original content intact
    styled = format_beautify_block(title=title, message=raw, source_app=APP_NAME, priority=5, tags=None)
    return styled, None

def beautify_message(title, raw):
    lower = (raw or "").lower()

    # Prefer ARR: add AI-style while keeping posters
    if "radarr" in lower:
        return beautify_radarr(title, raw)
    if "sonarr" in lower:
        return beautify_sonarr(title, raw)

    # Small JSON/YAML prettify only (no tables)
    j = beautify_json(title, raw)
    if j and j[0]:
        return j[0], None
    y = beautify_yaml(title, raw)
    if y and y[0]:
        return y[0], None

    # Fallback: sleek aligned block
    return beautify_generic(title, raw)

# -----------------------------
# Scheduler
# -----------------------------
def run_scheduler():
    schedule.every(5).seconds.do(purge_non_jarvis_apps)
    schedule.every(RETENTION_HOURS).hours.do(purge_all_messages)
    # NEW: periodic ARR cache refresh so 'upcoming' stays fresh
    if RADARR_ENABLED and 'cache_radarr' in globals():
        try:
            schedule.every(CACHE_REFRESH_MINUTES).minutes.do(cache_radarr)
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Could not schedule cache_radarr: {e}")
    if SONARR_ENABLED and 'cache_sonarr' in globals():
        try:
            schedule.every(CACHE_REFRESH_MINUTES).minutes.do(cache_sonarr)
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Could not schedule cache_sonarr: {e}")
    # NEW: autonomous AI check-ins (off by default)
    if AI_CHECKINS_ENABLED:
        schedule.every(6).hours.do(send_ai_checkin)
    while True:
        schedule.run_pending()
        time.sleep(1)

# -----------------------------
# Listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://","ws://").replace("https://","wss://")
    ws_url += f"/stream?token={CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] Connecting {ws_url}")
    try:
        async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
            print(f"[{BOT_NAME}] ✅ Connected")
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    appid = data.get("appid")
                    if appid == jarvis_app_id:
                        continue
                    title = data.get("title","")
                    message = data.get("message","")
                    
                    if title.lower().startswith("jarvis") or message.lower().startswith("jarvis"):
                        # 🔧 ADDITIVE FIX: if the title is just the wake word, fall back to the message for the command.
                        if title.lower().startswith("jarvis"):
                            tmp = title.lower().replace("jarvis","",1).strip()
                            cmd = tmp if tmp else message.lower().replace("jarvis","",1).strip()
                        else:
                            cmd = message.lower().replace("jarvis","",1).strip()
                        
                        # ✅ Help command
                        if cmd in ["help", "commands"]:
                            help_text = (
                                "🤖 **Jarvis Jnr Command Matrix** 🤖\n\n"
                                "🌦  Weather Intelligence:\n"
                                "   • `weather` → Current weather snapshot\n"
                                "   • `forecast` → 7-day weather projection\n"
                                "   • `temperature` / `temp` → Temperature query\n\n"
                                "🧬  DNS (Technitium):\n"
                                "   • `dns status` → totals, blocked, allowed, cache\n"
                                "   • `dns flush`  → flush resolver cache\n\n"
                                "🎬  Radarr Protocols:\n"
                                "   • `movie count` → Total movies indexed\n"
                                "   • Auto-reacts to Radarr events in real-time\n\n"
                                "📺  Sonarr Protocols:\n"
                                "   • `series count` → Total series indexed\n"
                                "   • Auto-reacts to Sonarr events in real-time\n\n"
                                "🧩  System:\n"
                                "   • `help` or `commands` → Display this command matrix\n\n"
                                "🃏  Fun:\n"
                                "   • `joke` or `pun` → Quick one-liner\n\n"
                                "⚡ *Jarvis Jnr is fully synchronized and standing by.*"
                            )
                            send_message("Help", help_text)
                            continue

                        # ✅ Weather routing
                        if any(word in cmd for word in ["weather", "forecast", "temperature", "temp"]):
                            if "weather" in extra_modules:
                                response, extras = extra_modules["weather"].handle_weather_command(cmd)
                                if response:
                                    send_message("Weather", response, extras=extras)
                                    continue

                        # ✅ DNS (Technitium) routing — same pattern as weather
                        if "technitium" in extra_modules and (cmd.startswith("dns") or " dns" in f" {cmd}"):
                            t_resp = extra_modules["technitium"].handle_dns_command(cmd)
                            if isinstance(t_resp, tuple) and t_resp[0]:
                                send_message("DNS", t_resp[0], extras=t_resp[1])
                                continue
                            if isinstance(t_resp, str) and t_resp:
                                send_message("DNS", t_resp)
                                continue

                        # ✅ Chat fun (joke/pun)
                        if "chat" in extra_modules and ("joke" in cmd or "pun" in cmd):
                            try:
                                # Prefer a router if present
                                if hasattr(extra_modules["chat"], "handle_chat_command"):
                                    c_resp = extra_modules["chat"].handle_chat_command("joke")
                                elif hasattr(extra_modules["chat"], "joke"):
                                    c_resp = (extra_modules["chat"].joke(), None)
                                elif hasattr(extra_modules["chat"], "get_joke"):
                                    c_resp = (extra_modules["chat"].get_joke(), None)
                                else:
                                    c_resp = ("🃏 Here's a joke placeholder.", None)
                                if isinstance(c_resp, tuple):
                                    send_message("Joke", c_resp[0], extras=c_resp[1])
                                else:
                                    send_message("Joke", str(c_resp))
                                continue
                            except Exception as _e:
                                send_message("Joke", f"⚠️ Joke module error: {_e}")
                                continue
                        
                        # ✅ ARR routing
                        response, extras = handle_arr_command(title, message)
                        if response:
                            send_message("Jarvis", response, extras=extras)
                            continue

                    if BEAUTIFY_ENABLED:
                        final, extras = beautify_message(title, message)
                    else:
                        final, extras = message, None
                    send_message(title, final, priority=5, extras=extras)
                except Exception as e:
                    print(f"[{BOT_NAME}] Error processing: {e}")
    except Exception as e:
        print(f"[{BOT_NAME}] WS fail: {e}")
        await asyncio.sleep(10)
        await listen()

# -----------------------------
# Dynamic Module Loader
# -----------------------------
def try_load_module(modname, label, icon="🧩"):
    path = f"/app/{modname}.py"

    enabled = os.getenv(f"{modname}_enabled", "false").lower() in ("1", "true", "yes")
    if not enabled:
        try:
            with open("/data/options.json", "r") as f:
                opts = json.load(f)
                enabled = opts.get(f"{modname}_enabled", False)
        except:
            enabled = False

    if not os.path.exists(path) or not enabled:
        return None
    try:
        spec = importlib.util.spec_from_file_location(modname, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        extra_modules[modname] = module
        print(f"[{BOT_NAME}] ✅ Loaded module: {modname}")
        return f"{icon} {label}"
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Failed to load module {modname}: {e}")
        return None

# -----------------------------
# AI-style autonomous check-in (optional)
# -----------------------------
def send_ai_checkin():
    try:
        parts = []
        parts.append(f"{_ts(1)} 🧠 Cognitive heartbeat")
        parts.append(_kv("Mood", CHAT_MOOD))
        parts.append(_kv("Beautify", "ON" if BEAUTIFY_ENABLED else "OFF"))
        parts.append(_kv("Radarr", "ACTIVE" if RADARR_ENABLED else "INACTIVE"))
        parts.append(_kv("Sonarr", "ACTIVE" if SONARR_ENABLED else "INACTIVE"))
        parts.append(_kv("Weather", "ACTIVE" if WEATHER_ENABLED else "INACTIVE"))
        parts.append(_kv("DNS", "ACTIVE" if TECHNITIUM_ENABLED else "INACTIVE"))  # ← NEW
        parts.append(_kv("Digest", "ACTIVE" if ('digest' in extra_modules) else "INACTIVE"))
        # Use mood-specific line if none provided
        parts.append(f"{_ts(2)} {ai_voice(None)}")
        send_message("Status", "\n".join(parts), priority=5)
    except Exception as e:
        print(f"[{BOT_NAME}] Check-in failed: {e}")

# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    print(f"[{BOT_NAME}] Starting add-on…")
    resolve_app_id()

    # Prepare active list & warm caches like before
    active = []
    if RADARR_ENABLED:
        active.append("🎬 Radarr")
        try: cache_radarr()
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ Radarr cache failed {e}")
    if SONARR_ENABLED:
        active.append("📺 Sonarr")
        try: cache_sonarr()
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ Sonarr cache failed {e}")

    # Dynamic modules
    chat_loaded = False
    digest_loaded = False
    for mod, label, icon in [
        ("chat", "Chat", "💬"),
        ("weather", "Weather", "🌦"),
        ("digest", "Digest", "📰"),
        ("technitium", "DNS", "🧬"),  # ← load DNS module
    ]:
        loaded = try_load_module(mod, label, icon)
        if loaded:
            active.append(loaded)
            if mod == "chat": chat_loaded = True
            if mod == "digest": digest_loaded = True

    # Chat/Digest enabled resolution: dynamic loader OR config/env toggles
    chat_enabled_flag = chat_loaded or CHAT_ENABLED_ENV or locals().get("CHAT_ENABLED_FILE", False)
    digest_enabled_flag = digest_loaded or DIGEST_ENABLED_ENV or locals().get("DIGEST_ENABLED_FILE", False)

    # Single startup post in the agreed boot style (shows ACTIVE/INACTIVE for all modules)
    startup_poster = format_startup_poster(
        bot_name=BOT_NAME,
        retention_hours=RETENTION_HOURS,
        silent_repost=SILENT_REPOST,
        beautify_enabled=BEAUTIFY_ENABLED,
        radarr_enabled=RADARR_ENABLED,
        sonarr_enabled=SONARR_ENABLED,
        chat_enabled=chat_enabled_flag,
        weather_enabled=WEATHER_ENABLED,
        digest_enabled=digest_enabled_flag,
        chat_mood=CHAT_MOOD,
        technitium_enabled=TECHNITIUM_ENABLED,  # ← NEW
    )
    # Add a tiny mood-aware flourish (AI voice; use pool if no explicit line)
    startup_poster = startup_poster + f"\n{_ts(5)} {ai_voice(None)}"
    send_message("Startup", startup_poster, priority=5)

    # Runtime
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
