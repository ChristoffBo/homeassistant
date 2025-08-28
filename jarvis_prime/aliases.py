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
        return {str(k).strip().lowe
