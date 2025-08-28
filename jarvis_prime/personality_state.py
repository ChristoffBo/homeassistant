# /app/personality_state.py - persist mood across reboots
import os, json, datetime, threading

BASE = os.getenv("JARVIS_SHARE_BASE", "/share/jarvis_prime")
STATE_FILE = os.path.join(BASE, "state.json")
_os_lock = threading.RLock()

def save_mood(mood: str):
    os.makedirs(BASE, exist_ok=True)
    with _os_lock:
        st = {"mood": mood, "updated_at": datetime.datetime.utcnow().replace(microsecond=0).isoformat()+"Z"}
        with open(STATE_FILE, "w") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)

def load_mood(default: str):
    try:
        with _os_lock:
            with open(STATE_FILE, "r") as f:
                st = json.load(f)
        return st.get("mood", default) or default
    except Exception:
        return default
