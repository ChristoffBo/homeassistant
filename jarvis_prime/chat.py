
import random, requests, time

FALLBACK_JOKES = [
    "I told my computer I needed a break, and it said: 'No problem, I’ll go to sleep.'",
    "Why do Java developers wear glasses? Because they can’t C#.",
    "There are 10 kinds of people: those who understand binary and those who don’t.",
    "I would tell you a UDP joke, but you might not get it.",
    "Git commit: fix bug. Git push: broke everything.",
]

def _online_joke(timeout=5):
    try:
        r = requests.get("https://v2.jokeapi.dev/joke/Programming?type=single",
                         timeout=timeout)
        if r.ok:
            j = r.json()
            if isinstance(j, dict) and j.get("type") == "single":
                return j.get("joke")
    except Exception:
        pass
    return None

def handle_chat_command(cmd: str, *_):
    c = (cmd or "").strip().lower()
    if "joke" in c or c == "jarvis":
        joke = _online_joke() or random.choice(FALLBACK_JOKES)
        return f"• {joke}", None
    # Generic echo fallback for 'chat' module (kept simple)
    return f"• {cmd}", None
