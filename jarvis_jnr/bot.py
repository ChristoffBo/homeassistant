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
    options = _load_json_file("/data/options.json")
    config_fallback = _load_json_file("/data/config.json")
    merged = {**config_fallback, **options}

    RADARR_ENABLED = merged.get("radarr_enabled", RADARR_ENABLED)
    SONARR_ENABLED = merged.get("sonarr_enabled", SONARR_ENABLED)
    WEATHER_ENABLED = merged.get("weather_enabled", WEATHER_ENABLED)

    CHAT_ENABLED_FILE = merged.get("chat_enabled", CHAT_ENABLED_ENV)
    DIGEST_ENABLED_FILE = merged.get("digest_enabled", DIGEST_ENABLED_ENV)

    RADARR_URL = merged.get("radarr_url", "")
    RADARR_API_KEY = merged.get("radarr_api_key", "")
    SONARR_URL = merged.get("sonarr_url", "")
    SONARR_API_KEY = merged.get("sonarr_api_key", "")

    CHAT_MOOD = str(merged.get("personality_mood",
                               merged.get("chat_mood", CHAT_MOOD)))

    AI_CHECKINS_ENABLED = merged.get("ai_checkins_enabled", AI_CHECKINS_ENABLED)
    CACHE_REFRESH_MINUTES = int(merged.get("cache_refresh_minutes", CACHE_REFRESH_MINUTES))

except Exception as e:
    print(f"[{BOT_NAME}] ⚠️ Could not load options/config json: {e}")
    RADARR_URL = ""
    RADARR_API_KEY = ""
    SONARR_URL = ""
    SONARR_API_KEY = ""

jarvis_app_id = None
extra_modules = {}

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
    ]
    return random.choice(greetings)

def _ts(step=None):
    if step is None:
        return datetime.now().strftime("[%H:%M:%S]")
    return f"[00:{step:02d}]"

def _kv(label, value): return f"    {label}: {value}"
def _yesno(flag): return "True" if bool(flag) else "False"

# -----------------------------
# Personality lines
# -----------------------------
PERSONALITY_LINES = {
    "calm": ["Systems nominal — awaiting directives."],
    "playful": ["Woohoo! New movie night incoming! 🍿"],
}
def ai_voice(line: str | None):
    mood = (CHAT_MOOD or "calm").strip().lower()
    base = line.strip() if isinstance(line, str) and line.strip() else PERSONALITY_LINES.get(mood, PERSONALITY_LINES["calm"])[0]
    return f"💡 {base}"

# -----------------------------
# Startup Poster (now shows DNS)
# -----------------------------
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
    dns_enabled: bool = None,
    chat_mood: str = None
) -> str:
    bot_name = bot_name or BOT_NAME
    retention_hours = RETENTION_HOURS if retention_hours is None else retention_hours
    silent_repost = SILENT_REPOST if silent_repost is None else silent_repost
    beautify_enabled = BEAUTIFY_ENABLED if beautify_enabled is None else beautify_enabled
    radarr_enabled = RADARR_ENABLED if radarr_enabled is None else radarr_enabled
    sonarr_enabled = SONARR_ENABLED if sonarr_enabled is None else sonarr_enabled
    weather_enabled = WEATHER_ENABLED if weather_enabled is None else weather_enabled
    chat_enabled = chat_enabled if chat_enabled is not None else False
    digest_enabled = digest_enabled if digest_enabled is not None else False
    dns_enabled = bool(dns_enabled)
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
    lines.append(mod_line("📰", "Digest", digest_enabled))
    lines.append(mod_line("🧬", "DNS (Technitium)", dns_enabled))
    lines.append(f"{_ts(4)} ✅ All systems nominal — Standing by")
    return "\n".join(lines)

# -----------------------------
# Beautifiers (unchanged)
# -----------------------------
def format_beautify_block(title, message, source_app=None, priority=None, tags=None):
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

def beautify_radarr(title, raw):
    try:
        obj = json.loads(raw); movie = obj.get("movie") or {}; rel = obj.get("release") or {}
        name = movie.get("title") or "Unknown Movie"
        year = movie.get("year") or ""
        runtime = (lambda m: f"{m//60}h {m%60}m" if isinstance(m,int) and m>0 else "?")(movie.get("runtime") or 0)
        quality = rel.get("quality") or "Unknown"; size = rel.get("size") or 0
        poster = None
        for i in (movie.get("images") or []):
            if str(i.get("coverType","")).lower() == "poster" and i.get("url"): poster = i["url"]; break
        extras = {"client::notification": {"bigImageUrl": poster}} if poster else None
        return "\n".join([f"🎬 **{name}** ({year})", f"• ⏱ {runtime}   • 🔧 {quality}   • 📦 {size}B"]), extras
    except Exception:
        return raw, None

def beautify_sonarr(title, raw):
    try:
        obj = json.loads(raw); series=obj.get("series") or {}; ep=obj.get("episode") or {}; rel=obj.get("release") or {}
        sname = series.get("title") or "Unknown Series"; ep_t = ep.get("title") or "Unknown Episode"
        season = int(ep.get("seasonNumber") or 0); enum = int(ep.get("episodeNumber") or 0)
        runtime = (lambda m: f"{m//60}h {m%60}m" if isinstance(m,int) and m>0 else "?")(ep.get("runtime") or 0)
        quality = rel.get("quality") or "Unknown"; size = rel.get("size") or 0
        poster=None
        for i in (series.get("images") or []):
            if str(i.get("coverType","")).lower()=="poster" and i.get("url"): poster=i["url"]; break
        extras={"client::notification":{"bigImageUrl":poster}} if poster else None
        return "\n".join([f"📺 **{sname}** • S{season:02}E{enum:02}", f"“{ep_t}” — ⏱ {runtime}   • 🔧 {quality}   • 📦 {size}B"]), extras
    except Exception:
        return raw, None

def beautify_json(title, raw):
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and 0 < len(obj) <= 10:
            bullets = [f"• {k}: {obj[k]}" for k in obj]
            return "🧩 JSON payload\n" + "\n".join(bullets), None
    except Exception:
        pass
    return None, None

def beautify_yaml(title, raw):
    try:
        obj = yaml.safe_load(raw)
        if isinstance(obj, dict) and 0 < len(obj) <= 10:
            bullets = [f"• {k}: {obj[k]}" for k in obj]
            return "🧩 YAML payload\n" + "\n".join(bullets), None
    except Exception:
        pass
    return None, None

def beautify_generic(title, raw):
    if any(tok in raw for tok in ("http://", "https://", "```", "|---", "||")) or raw.count("\n") > 6:
        return raw, None
    return format_beautify_block(title=title, message=raw, source_app=APP_NAME, priority=5, tags=None), None

def beautify_message(title, raw):
    lower = (raw or "").lower()
    if "radarr" in lower: return beautify_radarr(title, raw)
    if "sonarr" in lower: return beautify_sonarr(title, raw)
    j = beautify_json(title, raw)
    if j and j[0]: return j[0], None
    y = beautify_yaml(title, raw)
    if y and y[0]: return y[0], None
    return beautify_generic(title, raw)

# -----------------------------
# Scheduler
# -----------------------------
def run_scheduler():
    schedule.every(5).seconds.do(purge_non_jarvis_apps)
    schedule.every(RETENTION_HOURS).hours.do(purge_all_messages)
    if RADARR_ENABLED and 'cache_radarr' in globals():
        try: schedule.every(CACHE_REFRESH_MINUTES).minutes.do(cache_radarr)
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ Could not schedule cache_radarr: {e}")
    if SONARR_ENABLED and 'cache_sonarr' in globals():
        try: schedule.every(CACHE_REFRESH_MINUTES).minutes.do(cache_sonarr)
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ Could not schedule cache_sonarr: {e}")
    if AI_CHECKINS_ENABLED:
        schedule.every(6).hours.do(send_ai_checkin)
    while True:
        schedule.run_pending(); time.sleep(1)

# -----------------------------
# Listener
# -----------------------------
def send_message(title, message, priority=5, extras=None):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    if extras: data["extras"] = extras
    try:
        r = requests.post(url, json=data, timeout=5); r.raise_for_status()
        print(f"[{BOT_NAME}] ✅ Sent: {title}"); return True
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to send message: {e}"); return False

def force_refresh():
    try:
        url = f"{GOTIFY_URL}/message?since=0"; headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5)
        if r.ok: print(f"[{BOT_NAME}] 🔄 Forced Gotify client refresh")
        else:    print(f"[{BOT_NAME}] ⚠️ Refresh request failed: {r.status_code}")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error forcing Gotify refresh: {e}")

def purge_app_messages(appid, appname=""):
    if not appid: return False
    url = f"{GOTIFY_URL}/application/{appid}/message"; headers = {"X-Gotify-Key": CLIENT_TOKEN}
    try:
        r = requests.delete(url, headers=headers, timeout=10)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] 🗑 Purged messages from app '{appname}' (id={appid})"); force_refresh(); return True
        else:
            print(f"[{BOT_NAME}] ❌ Purge failed for '{appname}' (id={appid}): {r.status_code}"); return False
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error purging app {appid}: {e}"); return False

def purge_non_jarvis_apps():
    global jarvis_app_id
    if not jarvis_app_id:
        print(f"[{BOT_NAME}] ⚠️ Jarvis app_id not resolved"); return
    try:
        url = f"{GOTIFY_URL}/application"; headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5); r.raise_for_status(); apps = r.json()
        for app in apps:
            appid = app.get("id"); name = app.get("name")
            if appid != jarvis_app_id: purge_app_messages(appid, name)
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error purging non-Jarvis apps: {e}")

def purge_all_messages():
    global jarvis_app_id
    if not jarvis_app_id: return
    try:
        url = f"{GOTIFY_URL}/application/{jarvis_app_id}/message"; headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.delete(url, headers=headers, timeout=10)
        if r.status_code == 200: print(f"[{BOT_NAME}] 🗑 Purged ALL messages (retention {RETENTION_HOURS}h)")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error purging Jarvis messages: {e}")

def resolve_app_id():
    global jarvis_app_id
    print(f"[{BOT_NAME}] Resolving app ID for '{APP_NAME}'")
    try:
        url = f"{GOTIFY_URL}/application"; headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5); r.raise_for_status(); apps = r.json()
        for app in apps:
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id"); print(f"[{BOT_NAME}] ✅ Found '{APP_NAME}' id={jarvis_app_id}"); return
        print(f"[{BOT_NAME}] ❌ Could not find app '{APP_NAME}'")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to resolve app id: {e}")

# -----------------------------
# Listener (routes + Help shows DNS commands)
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://","ws://").replace("https://","wss://") + f"/stream?token={CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] Connecting {ws_url}")
    try:
        async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
            print(f"[{BOT_NAME}] ✅ Connected")
            async for msg in ws:
                try:
                    data = json.loads(msg); appid = data.get("appid")
                    if appid == jarvis_app_id: continue
                    title = data.get("title",""); message = data.get("message","")

                    if title.lower().startswith("jarvis") or message.lower().startswith("jarvis"):
                        if title.lower().startswith("jarvis"):
                            tmp = title.lower().replace("jarvis","",1).strip()
                            cmd = tmp if tmp else message.lower().replace("jarvis","",1).strip()
                        else:
                            cmd = message.lower().replace("jarvis","",1).strip()

                        # Help
                        if cmd in ["help", "commands"]:
                            help_lines = []
                            help_lines.append("🤖 **Jarvis Jnr — Active Modules & Commands**")
                            help_lines.append("")
                            if "weather" in extra_modules and WEATHER_ENABLED:
                                help_lines.append("🌦 Weather  (wake: `Jarvis weather ...`)")
                                help_lines.append("   • `weather` → current snapshot")
                                help_lines.append("   • `forecast` → 7-day outlook")
                                help_lines.append("")
                            if "technitium" in extra_modules:
                                help_lines.append("🧬 DNS (Technitium)  (wake: `Jarvis dns ...`)")
                                help_lines.append("   • `dns status` → totals, blocked, allowed, cache")
                                help_lines.append("   • `dns flush`  → flush resolver cache")
                                help_lines.append("")
                            if RADARR_ENABLED:
                                help_lines.append("🎬 Radarr  (wake: `Jarvis ...`)")
                                help_lines.append("   • `movie count`")
                                help_lines.append("   • `upcoming movies`")
                                help_lines.append("   • `longest movie`")
                                help_lines.append("")
                            if SONARR_ENABLED:
                                help_lines.append("📺 Sonarr  (wake: `Jarvis ...`)")
                                help_lines.append("   • `series count`")
                                help_lines.append("   • `upcoming series`")
                                help_lines.append("   • `longest series`")
                                help_lines.append("")
                            help_lines.append("⚙️ Wake word rule: **title must begin with `Jarvis`**.")
                            send_message("Help", "\n".join(help_lines))
                            continue

                        # Weather
                        if any(word in cmd for word in ["weather", "forecast", "temperature", "temp"]):
                            if "weather" in extra_modules:
                                response, extras = extra_modules["weather"].handle_weather_command(cmd)
                                if response: send_message("Weather", response, extras=extras); continue

                        # DNS
                        if "technitium" in extra_modules:
                            t_resp = extra_modules["technitium"].handle_dns_command(cmd)
                            if isinstance(t_resp, tuple) and t_resp[0]: send_message("DNS", t_resp[0], extras=t_resp[1]); continue
                            if isinstance(t_resp, str) and t_resp:     send_message("DNS", t_resp); continue

                        # ARR
                        response, extras = handle_arr_command(title, message)
                        if response: send_message("Jarvis", response, extras=extras); continue

                    final, extras = beautify_message(title, message) if BEAUTIFY_ENABLED else (message, None)
                    send_message(title, final, priority=5, extras=extras)
                except Exception as e:
                    print(f"[{BOT_NAME}] Error processing: {e}")
    except Exception as e:
        print(f"[{BOT_NAME}] WS fail: {e}")
        await asyncio.sleep(10); await listen()

# -----------------------------
# Dynamic Module Loader
# -----------------------------
def try_load_module(modname, label, icon="🧩"):
    path = f"/app/{modname}.py"
    enabled = os.getenv(f"{modname}_enabled", "false").lower() in ("1", "true", "yes")
    if not enabled:
        try:
            with open("/data/options.json", "r") as f:
                opts = json.load(f); enabled = opts.get(f"{modname}_enabled", False)
        except: enabled = False
    if not os.path.exists(path) or not enabled: return None
    try:
        spec = importlib.util.spec_from_file_location(modname, path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        extra_modules[modname] = module
        print(f"[{BOT_NAME}] ✅ Loaded module: {modname}")
        return f"{icon} {label}"
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Failed to load module {modname}: {e}")
        return None

# -----------------------------
# AI check-in
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
        parts.append(_kv("DNS", "ACTIVE" if ("technitium" in extra_modules) else "INACTIVE"))
        parts.append(_kv("Digest", "ACTIVE" if ('digest' in extra_modules) else "INACTIVE"))
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

    # Warm caches
    if RADARR_ENABLED:
        try: cache_radarr()
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ Radarr cache failed {e}")
    if SONARR_ENABLED:
        try: cache_sonarr()
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ Sonarr cache failed {e}")

    # Dynamic modules
    chat_loaded = False; digest_loaded = False; dns_loaded = False
    for mod, label, icon in [
        ("chat", "Chat", "💬"),
        ("weather", "Weather", "🌦"),
        ("digest", "Digest", "📰"),
        ("technitium", "DNS", "🧬"),
    ]:
        loaded = try_load_module(mod, label, icon)
        if loaded:
            if mod == "chat": chat_loaded = True
            if mod == "digest": digest_loaded = True
            if mod == "technitium": dns_loaded = True

    chat_enabled_flag = chat_loaded or CHAT_ENABLED_ENV or locals().get("CHAT_ENABLED_FILE", False)
    digest_enabled_flag = digest_loaded or DIGEST_ENABLED_ENV or locals().get("DIGEST_ENABLED_FILE", False)

    # Startup poster (now includes DNS)
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
        dns_enabled=dns_loaded,
        chat_mood=CHAT_MOOD
    )
    startup_poster = startup_poster + f"\n{_ts(5)} {ai_voice(None)}"
    send_message("Startup", startup_poster, priority=5)

    # Runtime
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    loop.create_task(listen()); loop.run_in_executor(None, run_scheduler); loop.run_forever()
