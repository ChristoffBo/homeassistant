import os, json, time, asyncio, requests, websockets, schedule, random, re, yaml
from datetime import datetime, timezone

# -----------------------------
# Dynamic modules dict
# -----------------------------
extra_modules = {}

# -----------------------------
# Config from env (set in run.sh)
# -----------------------------
BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON = os.getenv("BOT_ICON", "🧠")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1","true","yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1","true","yes")

# Feature toggles
RADARR_ENABLED = os.getenv("radarr_enabled", "false").lower() in ("1","true","yes")
SONARR_ENABLED = os.getenv("sonarr_enabled", "false").lower() in ("1","true","yes")
WEATHER_ENABLED = os.getenv("weather_enabled", "false").lower() in ("1","true","yes")
CHAT_ENABLED_ENV = os.getenv("chat_enabled", "false").lower() in ("1","true","yes")
DIGEST_ENABLED_ENV = os.getenv("digest_enabled", "false").lower() in ("1","true","yes")
TECHNITIUM_ENABLED = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")
KUMA_ENABLED = os.getenv("uptimekuma_enabled", "false").lower() in ("1","true","yes")

AI_CHECKINS_ENABLED = os.getenv("ai_checkins_enabled", "false").lower() in ("1","true","yes")
CACHE_REFRESH_MINUTES = int(os.getenv("cache_refresh_minutes", "60"))

# Mood
CHAT_MOOD = "serious"

# Uptime tracking
BOOT_TIME = datetime.now()

# Heartbeat config
HEARTBEAT_ENABLED = False
HEARTBEAT_INTERVAL_MIN = 120
HEARTBEAT_START = "06:00"
HEARTBEAT_END = "20:00"

# -----------------------------
# Load /data/options.json overrides
# -----------------------------
def _load_json_file(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

merged = {}
try:
    options = _load_json_file("/data/options.json")
    config_fallback = _load_json_file("/data/config.json")
    merged = {**config_fallback, **options}

    RADARR_ENABLED = merged.get("radarr_enabled", RADARR_ENABLED)
    SONARR_ENABLED = merged.get("sonarr_enabled", SONARR_ENABLED)
    WEATHER_ENABLED = merged.get("weather_enabled", WEATHER_ENABLED)
    TECHNITIUM_ENABLED = merged.get("technitium_enabled", TECHNITIUM_ENABLED)
    KUMA_ENABLED = merged.get("uptimekuma_enabled", KUMA_ENABLED)

    CHAT_ENABLED_FILE = merged.get("chat_enabled", CHAT_ENABLED_ENV)
    DIGEST_ENABLED_FILE = merged.get("digest_enabled", DIGEST_ENABLED_ENV)

    CHAT_MOOD = str(merged.get("personality_mood", merged.get("chat_mood", CHAT_MOOD)))

    HEARTBEAT_ENABLED = bool(merged.get("heartbeat_enabled", HEARTBEAT_ENABLED))
    HEARTBEAT_INTERVAL_MIN = int(merged.get("heartbeat_interval_minutes", HEARTBEAT_INTERVAL_MIN))
    HEARTBEAT_START = str(merged.get("heartbeat_start", HEARTBEAT_START))
    HEARTBEAT_END = str(merged.get("heartbeat_end", HEARTBEAT_END))

except Exception as e:
    print(f"[{BOT_NAME}] ⚠️ Could not load options/config json: {e}")

jarvis_app_id = None

# -----------------------------
# Optional alias module
# -----------------------------
_alias_mod = None
try:
    import importlib.util as _imp
    _alias_spec = _imp.spec_from_file_location("alias", "/app/alias.py")
    if _alias_spec and _alias_spec.loader:
        _alias_mod = _imp.module_from_spec(_alias_spec)
        _alias_spec.loader.exec_module(_alias_mod)
        print("[Jarvis Prime] ✅ alias.py loaded")
except Exception as _e:
    print(f"[Jarvis Prime] ⚠️ alias.py not loaded: {_e}")

# -----------------------------
# Personality
# -----------------------------
_personality = None
try:
    import importlib.util as _imp
    _pspec = _imp.spec_from_file_location("personality", "/app/personality.py")
    if _pspec and _pspec.loader:
        _personality = _imp.module_from_spec(_pspec)
        _pspec.loader.exec_module(_personality)
        print("[Jarvis Prime] ✅ personality.py loaded")
except Exception as _e:
    print(f"[Jarvis Prime] ⚠️ personality.py not loaded: {_e}")

# -----------------------------
# Utils
# -----------------------------
def send_message(title, message, priority=5, extras=None):
    if _personality:
        title, message = _personality.decorate(title, message, CHAT_MOOD, chance=1.0)
        priority = _personality.apply_priority(priority, CHAT_MOOD)
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    if extras: data["extras"] = extras
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        print(f"[{BOT_NAME}] ✅ Sent: {title}")
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to send message: {e}")
        return False

def resolve_app_id():
    global jarvis_app_id
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5)
        r.raise_for_status()
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id"); return
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to resolve app id: {e}")

# -----------------------------
# Dynamic module loader
# -----------------------------
def try_load_module(modname, label):
    path = f"/app/{modname}.py"
    if modname == "arr": enabled = True
    else:
        enabled = os.getenv(f"{modname}_enabled", "false").lower() in ("1","true","yes")
        if not enabled:
            try:
                with open("/data/options.json", "r") as f:
                    enabled = json.load(f).get(f"{modname}_enabled", False)
            except Exception: enabled = False
    if not os.path.exists(path) or not enabled:
        print(f"[{BOT_NAME}] ↩️ Skipping module {modname}"); return False
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(modname, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        extra_modules[modname] = module
        print(f"[{BOT_NAME}] ✅ Loaded module: {modname}")
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Failed to load {modname}: {e}"); return False

# -----------------------------
# Startup poster
# -----------------------------
def startup_poster():
    def mod_line(icon, name, enabled): return f"    {icon} {name} – {'ACTIVE' if enabled else 'INACTIVE'}"
    lines = ["🧠 Jarvis Prime – Prime Neural Boot\n", f"Mood: {CHAT_MOOD}", "Modules:"]
    lines.append(mod_line("🎬", "Radarr", RADARR_ENABLED))
    lines.append(mod_line("📺", "Sonarr", SONARR_ENABLED))
    lines.append(mod_line("🌤", "Weather", WEATHER_ENABLED))
    lines.append(mod_line("📰", "Digest", DIGEST_ENABLED_ENV or DIGEST_ENABLED_FILE))
    lines.append(mod_line("💬", "Chat", CHAT_ENABLED_ENV or CHAT_ENABLED_FILE))
    lines.append(mod_line("📡", "Uptime Kuma", KUMA_ENABLED))
    lines.append(mod_line("🧬", "DNS (Technitium)", TECHNITIUM_ENABLED))
    lines.append("\nStatus: All systems nominal")
    return "\n".join(lines)

# -----------------------------
# Heartbeat
# -----------------------------
def _parse_hhmm(s): 
    try: hh, mm = s.split(":"); return int(hh)*60+int(mm)
    except: return 0
def _in_window(now, start,end):
    mins=now.hour*60+now.minute;a=_parse_hhmm(start);b=_parse_hhmm(end)
    if a==b:return True
    if a<b:return a<=mins<=b
    return mins>=a or mins<=b
def _fmt_uptime():
    d=datetime.now()-BOOT_TIME;total=int(d.total_seconds()//60);h,m=divmod(total,60);d,h=divmod(h,24)
    return " ".join([f"{d}d" if d else ""][0:1]+[f"{h}h" if h else ""][0:1]+[f"{m}m"])
def send_heartbeat_if_window():
    try:
        if not HEARTBEAT_ENABLED: return
        now=datetime.now()
        if not _in_window(now,HEARTBEAT_START,HEARTBEAT_END): return
        lines=["🫀 Heartbeat — Jarvis Prime alive",f"Time: {now.strftime('%Y-%m-%d %H:%M')}",f"Uptime: {_fmt_uptime()}",""]
        if "arr" in extra_modules:
            try:
                mv=extra_modules["arr"].list_upcoming_movies(days=1,limit=3)
                if mv: lines+=["🎬 Today’s Movies:"]+[f"- {x}" for x in mv]
                tv=extra_modules["arr"].list_upcoming_series(days=1,limit=5)
                if tv: lines+=["","📺 Today’s Episodes:"]+[f"- {x}" for x in tv]
            except: pass
        if _personality: lines.append(""); lines.append(_personality.quip(CHAT_MOOD))
        send_message("Heartbeat","\n".join(lines),priority=3)
    except Exception as e: print(f"[{BOT_NAME}] Heartbeat error: {e}")

# -----------------------------
# Digest
# -----------------------------
def job_daily_digest():
    try:
        dmod=extra_modules.get("digest")
        if not dmod or not hasattr(dmod,"build_digest"): return
        title,msg,prio=dmod.build_digest(merged)
        if _personality: msg += f"\n\n{_personality.quip(CHAT_MOOD)}"
        send_message(title,msg,priority=prio)
    except Exception as e: print(f"[{BOT_NAME}] Digest error: {e}")

# -----------------------------
# Normalization
# -----------------------------
def _clean(s): return re.sub(r"\s+"," ",s.lower().strip())
def normalize_cmd(cmd): 
    if _alias_mod and hasattr(_alias_mod,"normalize_cmd"): return _alias_mod.normalize_cmd(cmd)
    return _clean(cmd)

# -----------------------------
# Listener
# -----------------------------
async def listen():
    ws_url=GOTIFY_URL.replace("http://","ws://").replace("https://","wss://")+f"/stream?token={CLIENT_TOKEN}"
    async with websockets.connect(ws_url,ping_interval=30,ping_timeout=10) as ws:
        async for msg in ws:
            try:
                data=json.loads(msg);appid=data.get("appid")
                if appid==jarvis_app_id: continue
                title,message=data.get("title",""),data.get("message","")
                tlow,mlow=title.lower(),message.lower()
                if tlow.startswith("jarvis") or mlow.startswith("jarvis"):
                    cmd=(tlow if tlow.startswith("jarvis") else mlow).replace("jarvis","",1).strip()
                    ncmd=normalize_cmd(cmd)
                    if ncmd in ("help","commands"):
                        send_message("Help","🤖 Commands: dns, weather, forecast, movie/series count, upcoming, longest, joke, digest");continue
                    if ncmd in ("digest","daily digest","summary"): job_daily_digest();continue
                    if "technitium" in extra_modules and re.search(r"\bdns\b",ncmd):
                        out=extra_modules["technitium"].handle_dns_command(ncmd)
                        if isinstance(out,(tuple,list)) and out and out[0]: send_message("DNS",out[0]);continue
                        if isinstance(out,str) and out: send_message("DNS",out);continue
                    if "weather" in extra_modules and any(w in ncmd for w in ("weather","forecast","temp","now","today","current")):
                        w=extra_modules["weather"].handle_weather_command(ncmd)
                        if isinstance(w,(tuple,list)) and w and w[0]:
                            msg=w[0]; 
                            if _personality: msg=f"{msg}\n\n{_personality.quip(CHAT_MOOD)}"
                            send_message("Weather",msg); continue
                        if isinstance(w,str) and w:
                            msg=w
                            if _personality: msg=f"{msg}\n\n{_personality.quip(CHAT_MOOD)}"
                            send_message("Weather",msg); continue
                    if "chat" in extra_modules and ("joke" in ncmd or "pun" in ncmd):
                        c=extra_modules["chat"].handle_chat_command("joke"); send_message("Joke",c[0] if isinstance(c,tuple) else str(c));continue
                    if "arr" in extra_modules and hasattr(extra_modules["arr"],"handle_arr_command"):
                        r=extra_modules["arr"].handle_arr_command(title,message)
                        if isinstance(r,(tuple,list)) and r and r[0]: send_message("Jarvis",r[0]);continue
                        if isinstance(r,str) and r: send_message("Jarvis",r);continue
                    if _personality: send_message("Jarvis",_personality.unknown_command_response(cmd,CHAT_MOOD));continue
                    send_message("Jarvis",f"Unknown command: {cmd}");continue
                send_message(title,message)
            except Exception as e: print(f"[{BOT_NAME}] Listener error: {e}")

# -----------------------------
# Scheduler
# -----------------------------
def run_scheduler():
    schedule.every(RETENTION_HOURS).hours.do(lambda:None)
    if HEARTBEAT_ENABLED and HEARTBEAT_INTERVAL_MIN>0: schedule.every(HEARTBEAT_INTERVAL_MIN).minutes.do(send_heartbeat_if_window)
    if bool(merged.get("digest_enabled",False)):
        dtime=str(merged.get("digest_time","08:00")).strip()
        schedule.every().day.at(dtime).do(job_daily_digest)
    while True: schedule.run_pending(); time.sleep(1)

# -----------------------------
# Main
# -----------------------------
if __name__=="__main__":
    print(f"[{BOT_NAME}] Starting add-on…")
    resolve_app_id()
    try_load_module("arr","ARR"); try_load_module("chat","Chat"); try_load_module("weather","Weather")
    try_load_module("technitium","DNS"); try_load_module("digest","Digest")
    send_message("Startup",startup_poster(),priority=5)
    loop=asyncio.new_event_loop();asyncio.set_event_loop(loop)
    loop.create_task(listen());loop.run_in_executor(None,run_scheduler);loop.run_forever()
