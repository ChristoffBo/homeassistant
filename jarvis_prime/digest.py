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
_kuma = _try_import("uptimekuma")
_weather = _try_import("weather")
_tech = _try_import("technitium")

# -----------------------------
# Tiny utils
# -----------------------------
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
    """
    Returns (summary_line, detail_block). If counts are unavailable, we omit them.
    """
    if not _arr or (not _bool(options.get("radarr_enabled"), False) and not _bool(options.get("sonarr_enabled"), False)):
        return ("", "")

    movies_count = None
    series_count = None

    # Try several helpers for counts
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

    # Upcoming (today/top)
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

    details = _bullet_lines(upcoming_lines, limit=5) if upcoming_lines else ""
    return (summary, details)

# -----------------------------
# Uptime Kuma section
# -----------------------------
def _kuma_summary(options: Dict[str, Any]) -> str:
    if not _kuma or not _bool(options.get("uptimekuma_enabled"), False):
        return ""
    try:
        if hasattr(_kuma, "get_summary"):
            s = _kuma.get_summary(options)  # expected: {"up": N, "down": M}
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
# Weather section (robust parser)
# -----------------------------
_CONDITION_WORDS = (
    "sunny","clear","cloud","rain","showers","storm","thunder","wind","breeze",
    "fog","mist","snow","hail","overcast","drizzle","partly","mostly",
    "humid","dry","cold","hot","warm","cool","gust"
)

def _is_heading_like(line: str) -> bool:
    low = line.lower()
    # e.g., "Today — City", "Today: City"
    return (low.startswith("today") or low.startswith("forecast")) and ("—" in line or ":" in line) and not any(ch.isdigit() for ch in line)

def _extract_weather_from_text(text: str) -> str:
    """
    Parse free-text from weather.handle_weather_command(...) into a compact line:
    "Range: 12.4°C–25.1°C | Mostly sunny, light breeze"
    """
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return ""

    range_line = ""
    cond_line = ""

    # Pass 1: find a "Range:" line
    for l in lines:
        if _is_heading_like(l):
            continue
        if l.lower().startswith("range:"):
            range_line = l[len("range:"):].strip().lstrip()
            break

    # Pass 2: find a condition/wind line
    for l in lines:
        if _is_heading_like(l):
            continue
        low = l.lower()
        if any(w in low for w in _CONDITION_WORDS) or "°" in l or " now" in low or low.startswith("now:"):
            # avoid choosing the plain range again
            if not low.startswith("range:"):
                cond_line = l.replace("Now:", "").replace("now:", "").strip()
                break

    if range_line and cond_line:
        return f"Range: {range_line} | {cond_line}"
    if range_line:
        return f"Range: {range_line}"
    if cond_line:
        return cond_line
    # fallback to first non-heading line
    for l in lines:
        if not _is_heading_like(l):
            return l
    return ""

def _weather_snapshot(options: Dict[str, Any]) -> str:
    if not _weather or not _bool(options.get("weather_enabled"), False):
        return ""
    # Preferred structured helpers if your module has them
    try:
        if hasattr(_weather, "snapshot"):
            snap = _weather.snapshot(options) or {}
            rng = snap.get("range") or ""
            cond = snap.get("condition") or snap.get("summary") or ""
            wind = snap.get("wind") or ""
            parts = [str(x) for x in (rng and f"Range: {rng}", cond, wind) if x]
            line = " | ".join(parts).strip()
            if line:
                return line
        if hasattr(_weather, "brief"):
            s = str(_weather.brief(options)).strip()
            if s:
                parsed = _extract_weather_from_text(s)
                if parsed:
                    return parsed
        if hasattr(_weather, "current_summary"):
            s = str(_weather.current_summary(options)).strip()
            if s:
                parsed = _extract_weather_from_text(s)
                if parsed:
                    return parsed
    except Exception:
        pass
    # Robust text fallbacks using existing command handler
    try:
        if hasattr(_weather, "handle_weather_command"):
            for cmd in ("forecast today", "weather", "forecast"):
                resp = _weather.handle_weather_command(cmd)
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
    """
    Build the daily digest message.
    Returns: (title, message, priority)
    Priority: 5 normal; bump to 7 if Kuma shows any DOWN.
    """
    title = f"📰 Daily Digest — {datetime.now().strftime('%a %d %b %Y')}"

    # ARR
    arr_summary, arr_details = _arr_counts(options)
    arr_block = ""
    if arr_summary or arr_details:
        body = arr_summary
        if arr_details:
            body = f"{arr_summary}\n{arr_details}" if arr_summary else arr_details
        arr_block = _section("🎬 Media", body)

    # Kuma
    kuma_line = _kuma_summary(options)
    kuma_block = _section("🩺 Uptime Kuma", kuma_line) if kuma_line else ""

    # DNS
    dns_line = _dns_note(options)
    dns_block = _section("🧠 Technitium DNS", dns_line) if dns_line else ""

    # Weather — show only if we have meaningful text
    weather_line = _weather_snapshot(options)
    weather_block = _section("⛅ Weather", weather_line) if weather_line else ""

    # Compose
    parts = [arr_block, kuma_block, dns_block, weather_block]
    message = "\n".join([p for p in parts if p]).strip()
    if not message:
        message = "_No modules provided data for the digest today._"

    # Priority bump if any DOWN detected
    priority = 5
    if kuma_line and ("down" in kuma_line.lower() or "❗" in kuma_line):
        priority = 7

    return title, message, priority
