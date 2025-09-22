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
    if not _weather or not opts.get("weather_enabled"):
        return ""
    try:
        # Prefer a dedicated summary if the weather module provides one
        txt = ""
        if hasattr(_weather, "get_current_summary"):
            maybe = _weather.get_current_summary()
            if isinstance(maybe, dict):
                # Convert simple dict summaries to a single line
                order = ["location","as_of","outdoor","indoor","wind","solar","chance_of_rain","outlook"]
                parts = []
                for k in order:
                    v = maybe.get(k)
                    if v:
                        parts.append(str(v))
                return " | ".join(parts)
            elif isinstance(maybe, str):
                txt = maybe

        if not txt and hasattr(_weather, "handle_weather_command"):
            # Fallback: ask the module for the full weather text
            resp = _weather.handle_weather_command("weather")
            txt = resp[0] if isinstance(resp, tuple) else resp or ""

        lines = [l.strip() for l in (txt or "").splitlines() if l.strip()]
        if not lines:
            return ""

        # Try to keep a short header like "Current Weather — <place>"
        header = next((l for l in lines[:3] if "Current Weather" in l), None)

        # Pick key metric lines by keywords / emoji seen in your full weather push
        wanted_keys = (
            "Outdoor", "Indoor", "Wind", "Solar", "Chance of rain", "Outlook",
            "Humidity", "Pressure", "Feels like"
        )
        wanted_emojis_starts = ("🌡", "🏠", "🌬", "💨", "⚡", "☔", "🌧", "🌤", "🌥", "☀")

        metrics: List[str] = []
        for l in lines:
            if any(k in l for k in wanted_keys) or l.startswith(wanted_emojis_starts):
                metrics.append(l)

        # Build a concise single-line summary
        parts: List[str] = []
        if header:
            parts.append(header)
        parts.extend(metrics[:6])  # keep it tight

        if not parts:
            # Last resort: don’t truncate to 2 lines anymore—take up to 6 lines
            parts = lines[:6]

        return " | ".join(parts)
    except Exception:
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