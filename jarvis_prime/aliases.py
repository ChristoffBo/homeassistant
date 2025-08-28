# aliases.py — Canonical command normalization for Jarvis Prime
# Place at: /app/aliases.py

import json
import re

# Canonical intents routed by bot.py. Keep these strings exact.
CANON = {
    "dns",
    "kuma",
    "weather",
    "forecast",
    "upcoming_movies",
    "upcoming_series",
    "movie_count",
    "series_count",
    "longest_movie",
    "longest_series",
    "digest",
    "joke",
}

# Base aliases → canonical intent
BASE_ALIASES = {
    # Infra
    "dns": "dns",
    "technitium": "dns",

    "kuma": "kuma",
    "uptime": "kuma",
    "monitor": "kuma",

    # Weather
    "weather": "weather",
    "temp": "weather",
    "temps": "weather",
    "temperature": "weather",
    "now": "weather",
    "today": "weather",
    "current": "weather",

    "forecast": "forecast",
    "weekly": "forecast",
    "7day": "forecast",
    "7-day": "forecast",
    "7 day": "forecast",

    # Digest
    "digest": "digest",
    "daily digest": "digest",
    "summary": "digest",

    # ARR media
    "upcoming movies": "upcoming_movies",
    "upcoming films": "upcoming_movies",
    "movies upcoming": "upcoming_movies",
    "films upcoming": "upcoming_movies",

    "upcoming series": "upcoming_series",
    "upcoming shows": "upcoming_series",
    "series upcoming": "upcoming_series",
    "shows upcoming": "upcoming_series",

    "movie count": "movie_count",
    "film count": "movie_count",
    "series count": "series_count",
    "show count": "series_count",

    "longest movie": "longest_movie",
    "longest film": "longest_movie",
    "longest series": "longest_series",
    "longest show": "longest_series",

    # Fun
    "joke": "joke",
    "pun": "joke",
}

def _load_custom_aliases() -> dict:
    """
    Read user custom aliases from /data/options.json (key: custom_aliases),
    which can be either a JSON object or a JSON string of an object.
    """
    try:
        with open("/data/options.json", "r") as f:
            opts = json.load(f)
    except Exception:
        opts = {}
    raw = opts.get("custom_aliases", {})
    if isinstance(raw, dict):
        return {str(k).strip().lower(): str(v).strip() for k, v in raw.items()}
    if isinstance(raw, str):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return {str(k).strip().lower(): str(v).strip() for k, v in obj.items()}
        except Exception:
            pass
    return {}

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _keyword_rules(text: str) -> str | None:
    """
    Fallback keyword detection when no direct alias matches.
    Returns one of CANON or None.
    """
    c = text

    # Counts
    if "count" in c and ("movie" in c or "film" in c):
        return "movie_count"
    if "count" in c and ("series" in c or "show" in c or "tv" in c):
        return "series_count"

    # Upcoming
    if ("up" in c or "upcoming" in c) and ("movie" in c or "film" in c):
        return "upcoming_movies"
    if ("up" in c or "upcoming" in c) and ("series" in c or "show" in c or "tv" in c):
        return "upcoming_series"

    # Longest
    if "longest" in c and ("movie" in c or "film" in c):
        return "longest_movie"
    if "longest" in c and ("series" in c or "show" in c or "tv" in c):
        return "longest_series"

    # Weather / forecast
    if "forecast" in c or "7 day" in c or "week" in c:
        return "forecast"
    if any(w in c for w in ("weather", "temp", "temps", "temperature", "now", "today", "current")):
        return "weather"

    # Digest
    if "digest" in c or "summary" in c:
        return "digest"

    # Fun
    if "joke" in c or "pun" in c:
        return "joke"

    # Infra
    if "dns" in c or "technitium" in c:
        return "dns"
    if "kuma" in c or "uptime" in c or "monitor" in c:
        return "kuma"

    return None

def normalize_cmd(raw: str) -> str:
    """
    Turn a free-form utterance (after wake word) into a canonical intent.
    Priority:
      1) Custom aliases
      2) Base aliases
      3) Single-word shorthand
      4) Keyword rules
    """
    s = _clean(raw)
    if not s:
        return ""

    # 1) Custom user-defined aliases
    custom = _load_custom_aliases()
    if s in custom:
        target = _clean(custom[s])
        return target if target in CANON else ""

    # 2) Multi-word base aliases
    if s in BASE_ALIASES:
        return BASE_ALIASES[s]

    # 3) Single-word shorthand
    word = s.split(" ", 1)[0]
    if word in BASE_ALIASES:
        return BASE_ALIASES[word]

    # 4) Keyword fallback
    k = _keyword_rules(s)
    return k if k in CANON else ""
