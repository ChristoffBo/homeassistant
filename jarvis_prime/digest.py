import os
import json
import requests
from datetime import datetime
from typing import Dict, Tuple, Any, List

def _try_import(name: str):
    try:
        return __import__(name)
    except Exception:
        return None

_arr = _try_import("arr")
_weather = _try_import("weather")

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON = os.getenv("BOT_ICON", "🧠")
JARVIS_EMIT_URL = os.getenv("JARVIS_INTERNAL_EMIT_URL", "http://127.0.0.1:2599/internal/emit")

def _emit_to_jarvis(title: str, message: str, priority: int = 5, tags: List[str] | None = None) -> bool:
    try:
        payload = {
            "source": "digest",
            "title": f"{BOT_ICON} {BOT_NAME}: {title}",
            "message": message,
            "priority": priority,
            "tags": tags or ["digest", "daily"],
            "icon": BOT_ICON,
            "app": BOT_NAME,
        }
        r = requests.post(JARVIS_EMIT_URL, json=payload, timeout=6)
        r.raise_for_status()
        return True
    except Exception:
        return False

def _section(title: str, body: str) -> str:
    return f"**{title}**\n{body.strip()}\n" if body else ""

def _bulletize(text_or_list, limit: int = 10) -> str:
    if isinstance(text_or_list, str):
        lines = [l.strip() for l in text_or_list.splitlines() if l.strip()]
    else:
        lines = [str(x).strip() for x in (text_or_list or []) if str(x).strip()]
    return "\n".join([("- " + l if not l.startswith("- ") else l) for l in lines[:limit]])

def _movies_today(opts: Dict[str,Any]) -> str:
    if not _arr or not opts.get("radarr_enabled"): return ""
    for fn in ("upcoming_movies","today_upcoming_movies","list_upcoming_movies"):
        if hasattr(_arr, fn):
            try:
                res = getattr(_arr, fn)(1) if fn=="upcoming_movies" else getattr(_arr, fn)(opts)
                if isinstance(res, str) and res.strip():
                    return _bulletize(res, 10)
                if isinstance(res, (list,tuple)) and res:
                    return _bulletize(res, 10)
            except Exception:
                pass
    return ""

def _series_today(opts: Dict[str,Any]) -> str:
    if not _arr or not opts.get("sonarr_enabled"): return ""
    for fn in ("upcoming_series","today_upcoming_series","list_upcoming_series"):
        if hasattr(_arr, fn):
            try:
                res = getattr(_arr, fn)(1) if fn=="upcoming_series" else getattr(_arr, fn)(opts)
                if isinstance(res, str) and res.strip():
                    return _bulletize(res, 10)
                if isinstance(res, (list,tuple)) and res:
                    return _bulletize(res, 10)
            except Exception:
                pass
    return ""

def _weather_today(opts: Dict[str,Any]) -> str:
    if not _weather or not opts.get("weather_enabled"): return ""
    try:
        if hasattr(_weather, "handle_weather_command"):
            resp = _weather.handle_weather_command("weather")
            txt = resp[0] if isinstance(resp, tuple) else resp
            txt = txt or ""
            lines = [l.strip() for l in txt.splitlines() if l.strip()]
            return " | ".join(lines[:2])
    except Exception:
        pass
    return ""

def build_digest(options: Dict[str, Any]) -> Tuple[str, str, int]:
    title = f"📰 Daily Digest — {datetime.now().strftime('%a %d %b %Y')}"
    movies = _movies_today(options)
    series = _series_today(options)
    weather = _weather_today(options)

    parts = [
        _section("🎬 Movies Today", movies),
        _section("📺 Series Today", series),
        _section("⛅ Weather Today", weather),
    ]
    msg = "\n".join([p for p in parts if p]).strip() or "_No data for today._"

    # Auto-post to Jarvis internal emitter, and still return the tuple
    _emit_to_jarvis(title, msg, 5, ["digest", "daily"])
    return title, msg, 5