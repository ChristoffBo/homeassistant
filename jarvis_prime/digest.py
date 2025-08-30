import os
import json
from datetime import datetime
from typing import Dict, Tuple, Any, List

# -----------------------------
# Safe import helpers
# -----------------------------
def _try_import(name: str):
    try:
        return __import__(name)
    except Exception:
        return None

_arr = _try_import("arr")
_weather = _try_import("weather")

# -----------------------------
# Tiny utils
# -----------------------------
def _bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return default

def _section(title: str, body: str) -> str:
    if not body:
        return ""
    return f"**{title}**\n{body.strip()}\n"

def _bullet_lines(items: List[str], limit: int = 10) -> str:
    out = []
    for it in items[:limit]:
        line = str(it).strip()
        if not line:
            continue
        out.append(f"- {line}" if not line.startswith("- ") else line)
    return "\n".join(out)

# -----------------------------
# ARR: upcoming for *today*
# -----------------------------
def _today_upcoming_movies(options: Dict[str, Any]) -> List[str]:
    if not _arr or not _bool(options.get("radarr_enabled"), False):
        return []
    # Try a few helpers, degrade gracefully
    try:
        if hasattr(_arr, "today_upcoming_movies"):
            return [str(x) for x in (_arr.today_upcoming_movies(options) or [])]
        if hasattr(_arr, "list_upcoming_movies"):
            return [str(x) for x in (_arr.list_upcoming_movies(days=1, limit=20) or [])]
        if hasattr(_arr, "upcoming_movies"):
            # Some builds expose a generic upcoming API taking a window
            return [str(x) for x in (_arr.upcoming_movies(1) or []).splitlines() if x.strip()]
    except Exception:
        pass
    return []

def _today_upcoming_series(options: Dict[str, Any]) -> List[str]:
    if not _arr or not _bool(options.get("sonarr_enabled"), False):
        return []
    try:
        if hasattr(_arr, "today_upcoming_series"):
            return [str(x) for x in (_arr.today_upcoming_series(options) or [])]
        if hasattr(_arr, "list_upcoming_series"):
            return [str(x) for x in (_arr.list_upcoming_series(days=1, limit=20) or [])]
        if hasattr(_arr, "upcoming_series"):
            return [str(x) for x in (_arr.upcoming_series(1) or []).splitlines() if x.strip()]
    except Exception:
        pass
    return []

# -----------------------------
# Weather: compact "today" line
# -----------------------------
_CONDITION_WORDS = (
    "sunny","clear","cloud","rain","showers","storm","thunder","wind","breeze",
    "fog","mist","snow","hail","overcast","drizzle","partly","mostly",
    "humid","dry","cold","hot","warm","cool","gust"
)

def _is_heading_like(line: str) -> bool:
    low = line.lower()
    return (low.startswith("today") or low.startswith("forecast")) and ("—" in line or ":" in line) and not any(ch.isdigit() for ch in line)

def _extract_weather_from_text(text: str) -> str:
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return ""

    range_line = ""
    cond_line = ""

    for l in lines:
        if _is_heading_like(l): continue
        if l.lower().startswith("range:"):
            range_line = l[len("range:"):].strip()
            break

    for l in lines:
        if _is_heading_like(l): continue
        low = l.lower()
        if any(w in low for w in _CONDITION_WORDS) or "°" in l or " now" in low or low.startswith("now:"):
            if not low.startswith("range:"):
                cond_line = l.replace("Now:", "").replace("now:", "").strip()
                break

    if range_line and cond_line:
        return f"Range: {range_line} | {cond_line}"
    if range_line:
        return f"Range: {range_line}"
    if cond_line:
        return cond_line
    for l in lines:
        if not _is_heading_like(l):
            return l
    return ""

def _weather_today_line(options: Dict[str, Any]) -> str:
    if not _weather or not _bool(options.get("weather_enabled"), False):
        return ""
    try:
        # Prefer structured snapshot if your weather module provides it
        if hasattr(_weather, "snapshot"):
            snap = _weather.snapshot(options) or {}
            rng = snap.get("range") or ""
            cond = snap.get("condition") or snap.get("summary") or ""
            wind = snap.get("wind") or ""
            parts = [str(x) for x in (rng and f"Range: {rng}", cond, wind) if x]
            line = " | ".join(parts).strip()
            if line:
                return line
    except Exception:
        pass

    # Fallback to text parser via command handler
    try:
        resp = _weather.handle_weather_command("weather")
        text = ""
        if isinstance(resp, tuple) and resp:
            text = str(resp[0] or "")
        elif isinstance(resp, str):
            text = resp
        parsed = _extract_weather_from_text(text)
        if parsed:
            return parsed
    except Exception:
        pass
    return ""

# -----------------------------
# Public API
# -----------------------------
def build_digest(options: Dict[str, Any]) -> Tuple[str, str, int]:
    """
    Build the daily digest message with exactly three things:
      1) Upcoming movies today
      2) Upcoming series today
      3) Weather today
    Returns: (title, message, priority)
    """
    title = f"📰 Daily Digest — {datetime.now().strftime('%a %d %b %Y')}"

    movies = _today_upcoming_movies(options)
    series = _today_upcoming_series(options)
    weather_line = _weather_today_line(options)

    movies_block = _section("🎬 Movies Today", _bullet_lines(movies, limit=10)) if movies else ""
    series_block = _section("📺 Series Today", _bullet_lines(series, limit=10)) if series else ""
    weather_block = _section("⛅ Weather Today", weather_line) if weather_line else ""

    parts = [movies_block, series_block, weather_block]
    message = "\n".join([p for p in parts if p]).strip()
    if not message:
        message = "_No data for today._"

    # Normal priority digest
    return title, message, 5
