import os
import json
from datetime import datetime
from typing import Dict, Tuple, Any, List

def _try_import(name: str):
    try:
        return __import__(name)
    except Exception:
        return None

_arr = _try_import("arr")
_kuma = _try_import("uptimekuma")
_weather = _try_import("weather")
_tech = _try_import("technitium")

def _bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return default

def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default

def _section(title: str, body: str) -> str:
    if not body:
        return ""
    return f"**{title}**\n{body.strip()}\n"

def _bullet_lines(items: List[str], limit: int = 5) -> str:
    out = []
    for it in items[:limit]:
        line = str(it).strip()
        if not line:
            continue
        out.append(f"- {line}" if not line.startswith("- ") else line)
    return "\n".join(out)

# -----------------------------
# ARR section
# -----------------------------
def _arr_counts(options: Dict[str, Any]) -> Tuple[str, str]:
    if not _arr or (not _bool(options.get("radarr_enabled"), False) and not _bool(options.get("sonarr_enabled"), False)):
        return ("", "")

    movies_count = None
    series_count = None

    try:
        if hasattr(_arr, "get_counts"):
            counts = _arr.get_counts(options)  # expected: {"movies": N, "series": M}
            movies_count = counts.get("movies")
            series_count = counts.get("series")
        else:
            if hasattr(_arr, "movies_count"):
                movies_count = _arr.movies_count(options)
            if hasattr(_arr, "series_count"):
                series_count = _arr.series_count(options)
    except Exception:
        pass

    summary_parts = []
    if isinstance(series_count, int):
        summary_parts.append(f"Series: {series_count}")
    if isinstance(movies_count, int):
        summary_parts.append(f"Movies: {movies_count}")
    summary = " | ".join(summary_parts)

    upcoming_lines: List[str] = []
    try:
        if hasattr(_arr, "get_upcoming"):
            ups = _arr.get_upcoming(options, limit=5)  # list[str]
            upcoming_lines = [str(x) for x in (ups or [])]
        elif hasattr(_arr, "safe_today_upcoming"):
            ups = _arr.safe_today_upcoming(options, limit=5)
            upcoming_lines = [str(x) for x in (ups or [])]
        elif hasattr(_arr, "list_upcoming_series") or hasattr(_arr, "list_upcoming_movies"):
            ups = []
            if hasattr(_arr, "list_upcoming_series"):
                ups += (_arr.list_upcoming_series(days=1, limit=3) or [])
            if hasattr(_arr, "list_upcoming_movies"):
                ups += (_arr.list_upcoming_movies(days=1, limit=2) or [])
            upcoming_lines = [str(x) for x in ups]
    except Exception:
        pass

    if upcoming_lines:
        details = _bullet_lines(upcoming_lines, limit=5)
    else:
        details = ""  # no filler text, just empty

    return (summary, details)

# -----------------------------
# Uptime Kuma section
# -----------------------------
def _kuma_summary(options: Dict[str, Any]) -> str:
    if not _kuma or not _bool(options.get("uptimekuma_enabled"), False):
        return ""
    try:
        if hasattr(_kuma, "get_summary"):
            s = _kuma.get_summary(options)
            up = _int(s.get("up"), 0)
            down = _int(s.get("down"), 0)
        else:
            up = 0
            down = 0
            if hasattr(_kuma, "list_monitors"):
                mons = _kuma.list_monitors(options) or []
                for m in mons:
                    status = str(m.get("status", "")).lower()
                    if status == "up":
                        up += 1
                    elif status == "down":
                        down += 1
        return "All green ✅" if down == 0 else f"Up: {up} | Down: {down} ❗"
    except Exception:
        return ""

# -----------------------------
# Weather section
# -----------------------------
def _weather_snapshot(options: Dict[str, Any]) -> str:
    if not _weather or not _bool(options.get("weather_enabled"), False):
        return ""
    try:
        # If weather module has richer snapshot
        if hasattr(_weather, "snapshot"):
            snap = _weather.snapshot(options) or {}
            # try to combine temp range + condition + wind
            rng = snap.get("range") or ""
            cond = snap.get("condition") or snap.get("summary") or ""
            wind = snap.get("wind") or ""
            parts = [str(x) for x in (rng, cond, wind) if x]
            return " | ".join(parts)
        # fallbacks
        if hasattr(_weather, "brief"):
            return str(_weather.brief(options)).strip()
        if hasattr(_weather, "current_summary"):
            return str(_weather.current_summary(options)).strip()
    except Exception:
        pass
    return ""

# -----------------------------
# DNS section
# -----------------------------
def _dns_note(options: Dict[str, Any]) -> str:
    if not _tech or not _bool(options.get("technitium_enabled"), False):
        return ""
    try:
        if hasattr(_tech, "brief"):
            return str(_tech.brief(options)).strip()
        if hasattr(_tech, "stats"):
            st = _tech.stats(options) or {}
            def fmt_i(v):
                try:
                    return f"{int(v):,}"
                except Exception:
                    return str(v)
            total = fmt_i(st.get("total_queries", 0))
            blocked = fmt_i(st.get("blocked_total", 0))
            servfail = fmt_i(st.get("server_failure_total", 0))
            return f"Total: {total} | Blocked: {blocked} | Server Failure: {servfail}"
    except Exception:
        pass
    return ""

# -----------------------------
# Public API
# -----------------------------
def build_digest(options: Dict[str, Any]) -> Tuple[str, str, int]:
    title = f"📰 Daily Digest — {datetime.now().strftime('%a %d %b %Y')}"

    arr_summary, arr_details = _arr_counts(options)
    arr_block = ""
    if arr_summary or arr_details:
        body = arr_summary
        if arr_details:
            body = f"{arr_summary}\n{arr_details}" if arr_summary else arr_details
        arr_block = _section("🎬 Media", body)

    kuma_line = _kuma_summary(options)
    kuma_block = _section("🩺 Uptime Kuma", kuma_line) if kuma_line else ""

    dns_line = _dns_note(options)
    dns_block = _section("🧠 Technitium DNS", dns_line) if dns_line else ""

    weather_line = _weather_snapshot(options)
    weather_block = _section("⛅ Weather", weather_line) if weather_line else ""

    parts = [arr_block, kuma_block, dns_block, weather_block]
    message = "\n".join([p for p in parts if p]).strip()
    if not message:
        message = "_No modules provided data for the digest today._"

    priority = 5
    if kuma_line and ("down" in kuma_line.lower() or "❗" in kuma_line):
        priority = 7

    return title, message, priority
