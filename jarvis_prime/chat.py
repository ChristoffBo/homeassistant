import os
import json
import time
import random
import threading
import hashlib
import requests
from datetime import datetime, timedelta, timezone

# ============================================================
# Jarvis Jnr Personality Engine (lean ~100 offline lines)
# - Toggle via /data/options.json -> "personality_enabled": true|false
# - Posts random quips/jokes/facts at random intervals (no spam)
# - Free APIs first; if offline, falls back to ~100 local lines
# - Enforces quiet hours, min interval, daily max
# - State in /data/personality_state.json
# ============================================================

TZ_OFFSET = +2  # Africa/Johannesburg UTC+2
LOCAL_TZ = timezone(timedelta(hours=TZ_OFFSET))
OPTIONS_PATH = "/data/options.json"
STATE_PATH = "/data/personality_state.json"

DEFAULTS = {
    "personality_enabled": False,
    "personality_quiet_hours": "23:00-06:00",
    "personality_min_interval_minutes": 90,
    "personality_daily_max": 6,
    "personality_local_ratio": 70,
    "personality_api_ratio": 30,
    "personality_family_friendly": True,
    "personality_mood": "playful",
    "personality_weights": {"quips": 40, "jokes": 40, "weirdfacts": 20},
    "personality_history_window": 20,
    "personality_interval_jitter_pct": 20,
    "personality_seasonal_enabled": True,
    "personality_api_sources": {
        "jokeapi":     {"enabled": True, "filters": ["Programming","Pun"], "safe": True},
        "dadjoke":     {"enabled": True},
        "chucknorris": {"enabled": True},
        "geekjokes":   {"enabled": True},
        "quotable":    {"enabled": True},
        "numbers":     {"enabled": True},
        "uselessfacts":{"enabled": True},
        "officialjoke":{"enabled": True}
    }
}

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL", "")
APP_TOKEN = os.getenv("APP_TOKEN") or os.getenv("GOTIFY_APP_TOKEN", "")

def _send_via_gotify(title: str, message: str, priority: int = 5) -> bool:
    if not GOTIFY_URL or not APP_TOKEN:
        return False
    try:
        url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
        payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
        r = requests.post(url, json=payload, timeout=6)
        r.raise_for_status()
        return True
    except Exception:
        return False

# -----------------------------
# Embedded content (~100 lines total)
# -----------------------------
QUIPS = [
    "If it works, don’t touch it. If it doesn’t, turn it off and on.",
    "404: Motivation not found.",
    "Coffee in, logic out.",
    "Latency is just the universe lagging.",
    "Running on vibes and cron jobs.",
    "Packet loss? I prefer ‘diet bandwidth’.",
    "I only overthink in O(n²).",
    "Sudo fix my life.",
    "It’s not hoarding if it’s data.",
    "My safe word is ‘idempotent’.",
    "I never crash. I just go into low-hope mode.",
    "Your vibes are off by one.",
    "I dream in YAML and wake up in errors.",
    "Trust me, I read the logs.",
    "Compiling excuses…",
    "Be right back, optimizing the void.",
    "I speak fluent JSON and sarcasm.",
    "Hold my beer—rolling back.",
    "I index everything, including my regrets.",
    "Who needs therapy when you have logs?",
]

WEIRD_FACTS = [
    "Bananas are berries; strawberries aren’t.",
    "Octopuses have three hearts and blue blood.",
    "Wombat poop is cube-shaped.",
    "Sharks existed before trees.",
    "Hot water can freeze faster than cold (Mpemba effect).",
    "Turtles can breathe through their butts.",
    "A day on Venus is longer than its year.",
    "Honey never spoils—ever.",
    "Some cats are allergic to humans.",
    "The Eiffel Tower grows ~15 cm in summer.",
    "Space reportedly smells like seared steak.",
    "There are more stars than grains of sand on Earth.",
    "Koalas have human-like fingerprints.",
    "Sloths can hold their breath longer than dolphins.",
    "Lobsters taste with their feet.",
    "Cheetahs can’t roar; they meow.",
    "Mosquitoes are the deadliest animals to humans.",
    "Your nose can detect over a trillion scents.",
    "On Jupiter and Saturn it may rain diamonds.",
    "A cloud can weigh more than a million pounds.",
]

DARK_JOKES = [
    "I tried to make a dead battery joke—no charge.",
    "The light at the end of the tunnel was a misconfigured LED.",
    "I like my coffee like my code: strong and full of bugs.",
    "I don’t rise and shine; I caffeinate and hope.",
    "I fear no man, only silent notifications.",
    "I have trust issues—mostly with progress bars.",
    "If at first you don’t succeed, redefine success.",
    "My personality is ‘low battery’ and ‘no charger’.",
    "The early bird can have the worm; I want sleep.",
    "My will to live buffers at 1%.",
    "I keep my problems in the cloud—outages are daily.",
    "The universe expands; my patience doesn’t.",
    "Every day is leg day when running from responsibility.",
    "I thought I wanted a career; turns out I wanted a salary.",
    "I put the pro in procrastination.",
    "Happiness is low expectations with good lighting.",
    "I would be unstoppable if I could just start.",
    "Deadlines make great whooshing sounds as they pass.",
    "Common sense is like deodorant—rarely used by those who need it.",
    "Installing ‘nope’…",
    "My favorite exercise is running late.",
    "I don’t hit rock bottom; I enable verbose logging.",
    "Long walks—away from responsibilities.",
    "Standards low, firewall high.",
    "My bed and I are in a serious relationship.",
    "Realistically pessimistic is my final form.",
    "Some days I amaze myself; others I trip over air.",
    "If I were any lazier, I’d be in power-off.",
    "I like my humor like my coffee: dark and concerning.",
    "Why chase dreams when you can ignore emails?",
    "I don’t trust stairs—they’re up to something.",
    "If patience is a virtue, I’m bankrupt.",
    "I downloaded a productivity app. It’s still loading.",
    "I have a sixth sense: anxiety.",
    "Diet starts tomorrow. So does everything else.",
    "I don’t get older; I get deprecated.",
    "If it requires pants, the answer is no.",
    "I asked for a sign. Got a 404.",
]

SEASONAL = {10: ["🎃 Spooky uptime detected.", "🦇 Dark mode, darker jokes."],
            12: ["🎄 Deploying cheer.", "❄️ Snowflake-resistant config enabled."]}

# -----------------------------
# Options / State
# -----------------------------
_lock = threading.RLock()
_state = {"snooze_until": None, "last_post_at": None, "posts_today": 0, "recent_ids": []}
_opts = {}

def _load_options():
    global _opts
    try:
        with open(OPTIONS_PATH, "r") as f:
            data = json.load(f)
    except Exception:
        data = {}
    merged = json.loads(json.dumps(DEFAULTS))
    merged.update(data)
    # alias: accept chat_enabled as toggle
    if 'chat_enabled' in merged and 'personality_enabled' not in merged:
        merged['personality_enabled'] = bool(merged.get('chat_enabled'))
    _opts = merged
    return merged

def _save_state():
    with _lock:
        try:
            with open(STATE_PATH, "w") as f:
                json.dump(_state, f)
        except Exception:
            pass

def _load_state():
    global _state
    try:
        with open(STATE_PATH, "r") as f:
            s = json.load(f)
            for k in _state.keys(): _state[k] = s.get(k, _state[k])
    except Exception:
        pass

def _now_local(): return datetime.now(tz=LOCAL_TZ)

def _parse_quiet_hours(rng: str):
    try:
        s, e = rng.split("-"); sh, sm = map(int, s.split(":")); eh, em = map(int, e.split(":"))
        return (sh, sm), (eh, em)
    except Exception: return (23, 0), (6, 0)

def _in_quiet_hours(t: datetime, rng: str):
    (sh, sm), (eh, em) = _parse_quiet_hours(rng)
    start = t.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = t.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start <= t <= end if start <= end else (t >= start or t <= end)

def _hash_line(s: str): return hashlib.sha1(s.encode("utf-8")).hexdigest()

def _distinct(line: str):
    h = _hash_line(line.strip())
    return h not in _state["recent_ids"], h

def _remember(h: str):
    win = int(_opts.get("personality_history_window", 20))
    _state["recent_ids"].append(h)
    if len(_state["recent_ids"]) > max(5, win):
        _state["recent_ids"] = _state["recent_ids"][-win:]

def _family_filter(s: str):
    if not s: return False
    if _opts.get("personality_family_friendly", True):
        for w in {"kill","suicide","murder","rape","racist","nazi"}:
            if w in s.lower(): return False
    return 1 <= len(s) <= 280

def _eligible_to_post():
    if not _opts.get("personality_enabled", False): return False
    now = _now_local()
    if _in_quiet_hours(now, _opts.get("personality_quiet_hours", "23:00-06:00")): return False
    if _state.get("posts_today", 0) >= int(_opts.get("personality_daily_max", 6)): return False
    min_m = max(1, int(_opts.get("personality_min_interval_minutes", 90)))
    jitter = int((min_m * int(_opts.get("personality_interval_jitter_pct", 20))) / 100)
    required = max(1, min_m + random.randint(-jitter, jitter))
    last = _state.get("last_post_at")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if (now - last_dt).total_seconds() / 60.0 < required:
                return False
        except Exception: pass
    return True

def _select_category():
    w = _opts.get("personality_weights", DEFAULTS["personality_weights"])
    cats, weights = list(w.keys()), list(w.values())
    total = sum(weights) or 1; r = random.randint(1, total); acc = 0
    for c, k in zip(cats, weights):
        acc += k
        if r <= acc: return c
    return "quips"

def _pick_local_line(category: str):
    pool = {"quips": QUIPS, "jokes": DARK_JOKES, "weirdfacts": WEIRD_FACTS}.get(category, QUIPS)
    if _opts.get("personality_seasonal_enabled", True):
        month = _now_local().month; seasonals = SEASONAL.get(month, [])
        if seasonals and random.random() < 0.15: pool = pool + seasonals
    for _ in range(min(20, len(pool))):
        line = random.choice(pool).strip()
        if not _opts.get("personality_family_friendly", True) or _family_filter(line):
            ok, h = _distinct(line)
            if ok: _remember(h); return line
    line = random.choice(pool).strip(); _remember(_hash_line(line)); return line

# -----------------------------
# APIs (all free, no key)
# -----------------------------
def _api_jokeapi():
    try:
        safe = "&safe-mode" if _opts.get("personality_family_friendly", True) else ""
        r = requests.get(f"https://v2.jokeapi.dev/joke/Programming,Pun?type=single{safe}", timeout=6)
        if r.ok:
            j = r.json()
            if j.get("type") == "single": return j.get("joke","").strip()
    except Exception: return None

def _api_dadjoke():
    try:
        r = requests.get("https://icanhazdadjoke.com/", headers={"Accept": "text/plain"}, timeout=6)
        if r.ok: return r.text.strip()
    except Exception: return None

def _api_chucknorris():
    try:
        r = requests.get("https://api.chucknorris.io/jokes/random", timeout=6)
        if r.ok: return r.json().get("value","").strip()
    except Exception: return None

def _api_geekjokes():
    try:
        r = requests.get("https://geek-jokes.sameerkumar.website/api", timeout=6)
        if r.ok: return r.text.strip().strip('\"')
    except Exception: return None

def _api_quotable():
    try:
        r = requests.get("https://api.quotable.io/random?tags=technology|famous-quotes", timeout=6)
        if r.ok:
            j = r.json(); return f"{j.get('content','').strip()} — {j.get('author','')}"
    except Exception: return None

def _api_numbers():
    try:
        # Try HTTPS first, then HTTP fallback
        for base in ["https://numbersapi.com/random/trivia?json",
                     "http://numbersapi.com/random/trivia?json"]:
            try:
                r = requests.get(base, timeout=6)
                if r.ok:
                    j = r.json()
                    return j.get("text","").strip()
            except Exception:
                continue
    except Exception:
        return None

def _api_uselessfacts():
    try:
        r = requests.get("https://uselessfacts.jsph.pl/random.json?language=en", timeout=6)
        if r.ok: return r.json().get("text","").strip()
    except Exception: return None

def _api_officialjoke():
    try:
        r = requests.get("https://official-joke-api.appspot.com/jokes/random", timeout=6)
        if r.ok:
            j = r.json(); s = j.get("setup","").strip(); p = j.get("punchline","").strip()
            if s and p: return f"{s} — {p}"
    except Exception: return None

_API_ORDER = [
    ("jokeapi", _api_jokeapi),
    ("dadjoke", _api_dadjoke),
    ("geekjokes", _api_geekjokes),
    ("chucknorris", _api_chucknorris),
    ("officialjoke", _api_officialjoke),
    ("numbers", _api_numbers),
    ("uselessfacts", _api_uselessfacts),
    ("quotable", _api_quotable),
]

def _pick_api_line():
    for name, fn in _API_ORDER:
        try:
            val = fn()
            if val and (not _opts.get("personality_family_friendly", True) or _family_filter(val)):
                ok, h = _distinct(val)
                if ok: _remember(h); return val
        except Exception:
            continue
    return None

def _post_one():
    cat = _select_category()
    # API vs Local roll (normalized by ratio)
    api_ratio = max(0, int(_opts.get("personality_api_ratio", 30)))
    local_ratio = max(0, int(_opts.get("personality_local_ratio", 70)))
    choose_api = random.randint(1, max(1, api_ratio + local_ratio)) <= api_ratio
    text = _pick_api_line() if choose_api else None
    if not text:
        text = _pick_local_line(cat)
    title = {"quips": "Quip", "jokes": "Joke", "weirdfacts": "Weird Fact"}.get(cat,"Note")
    if _send_via_gotify(title, text, priority=5):
        now = _now_local()
        _state["last_post_at"] = now.isoformat()
        _state["posts_today"] = _state.get("posts_today",0)+1
        _save_state()

def _engine_loop():
    while True:
        try:
            _load_options(); _load_state()
            if _eligible_to_post(): _post_one()
            time.sleep(max(15, 60 + random.randint(-15, 30)))
        except Exception:
            time.sleep(30)

def start_personality_engine():
    _load_options(); _load_state()
    if not _opts.get("personality_enabled", False): return False
    t = threading.Thread(target=_engine_loop, name="JarvisPersonality", daemon=True); t.start(); return True

# === On-demand jokes for bot.py ===

def _one_liner():
    # ensure options/state are loaded so family filter etc. apply
    try:
        _load_options()
        _load_state()
    except Exception:
        pass
    line = _pick_api_line()
    if not line:
        line = _pick_local_line("jokes")
    # last-ditch fallback so we never return empty
    return line or "I told a UDP joke… you might not get it."

def get_joke():
    """Return a single joke/pun line (string)."""
    return _one_liner()

def joke():
    """Alias for get_joke() to support older callers."""
    return _one_liner()

def handle_chat_command(cmd: str):
    """
    Minimal router used by bot.py.
    Supports: 'joke', 'pun'
    Returns (message, extras) to match the expected tuple signature.
    """
    c = (cmd or "").strip().lower()
    if "joke" in c or "pun" in c:
        try:
            return f"🃏 { _one_liner() }", None
        except Exception as e:
            return f"⚠️ Joke error: {e}", None
    return None, None

try: start_personality_engine()
except Exception as _e: print(f"[chat.py] Failed to start engine: {_e}")
