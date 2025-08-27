import os, json, requests
from datetime import datetime

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON = os.getenv("BOT_ICON", "🧠")
GOTIFY_URL = os.getenv("GOTIFY_URL", "")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN", "")

def _send(title, message, priority=5):
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

def run_digest():
    # Minimal daily digest scaffold you can extend later
    now = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"📰 Daily Digest — {now}",
        "• Weather: use `jarvis forecast`",
        "• ARR:   `jarvis movie count`, `jarvis series count`",
        "• Kuma:  `jarvis kuma status`",
    ]
    _send("Daily Digest", "\n".join(lines), priority=5)

# Optional: if you later want scheduled standalone execution:
if __name__ == "__main__":
    run_digest()
