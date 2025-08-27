import os
import json
from datetime import datetime
from typing import Dict, Tuple, Any, List

# The digest builder is defensive: it will try to use optional modules if present.
# Nothing here will crash the bot if a module/section is unavailable.

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
def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

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
    for i, it in enumerate(items[:limit]):
        line = str(it).strip()
        if not line:
            continue
        if line.startswith("- "):
            out.append(line)
        else:
            out.append(f"- {line}")
    return "\n".join(out)

# -----------------------------
# ARR section
# -----------------------------
def _arr_counts(options: Dict[str, Any]) -> Tuple[str, str]:
    """
    Returns (summary_line, detail_block)
    """
    if not _arr or (not _bool(options.get("radarr_enabled"), False) and not _bool(options.get("sonarr_enabled"), False)):
        return ("", "")

    movies_count = None
    series_count = None
    try:
        if hasattr(_arr, "get_counts"):
            counts = _arr.get_counts(options)  # expected: {"movies": N, "series": M}
            movies_count = counts.get("movies")
            series_count = counts.get("series")
    except Exception:
        pass

    left = f"Series: {series_count if isinstance(series_count, int) else '?'}"
    right = f"Movies: {movies_count if isinstance(movies_count, int) else '?'}"
    summary = f"{left} | {right}"

    upcoming_lines: List[str] = []
    try:
        if hasattr(_arr, "get_upcoming"):
            ups = _arr.get_upcoming(options, limit=5)  # list[str]
            upcoming_lines = [str(x) for x in (ups or [])]
        elif hasattr(_arr, "safe_today_upcoming"):
            ups = _arr.safe_today_upcoming(options, limit=5)  # list[str]
            upcoming_lines = [str(x) for x in (ups or [])]
    except Exception:
        pass

    details = ""
    if upcoming_lines:
        details = _bullet_lines(upcoming_lines, limit=5)

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
# Weather section
# -----------------------------
def _weather_snapshot(options: Dict[str, Any]) -> str:
    if not _weather or not _bool(options.get("weather_enabled"), False):
        return ""
    try:
        if hasattr(_weather, "brief"):
            return str(_weather.brief(options)).strip()
        if hasattr(_weather, "current_summary"):
            return str(_weather.current_summary(options)).strip()
    except Exception:
        pass
    return ""

# -----------------------------
# Technitium section (Total | Blocked | Server Failure)
# -----------------------------
def _dns_note(options: Dict[str, Any]) -> str:
    if not _tech or not _bool(options.get("technitium_enabled"), False):
        return ""
    try:
        # Prefer explicit helpers we added in technitium.py
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
    title = f"🗞️ Daily Digest — {datetime.now().strftime('%a %d %b %Y')}"

    # ARR
    arr_summary, arr_details = _arr_counts(options)
    arr_block = ""
    if arr_summary or arr_details:
        body = arr_summary
        if arr_details:
            body = f"{arr_summary}\n{arr_details}"
        arr_block = _section("🎬 Media", body)

    # Kuma
    kuma_line = _kuma_summary(options)
    kuma_block = _section("🩺 Uptime Kuma", kuma_line) if kuma_line else ""

    # DNS (Technitium)
    dns_line = _dns_note(options)
    dns_block = _section("🧠 Technitium DNS", dns_line) if dns_line else ""

    # Weather
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
