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
        r = requests.post(
            JARVIS_EMIT_URL,
            json=payload,
            timeout=6,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
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
        txt = ""
        if hasattr(_weather, "get_current_summary"):
            maybe = _weather.get_current_summary()
            if isinstance(maybe, dict):
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
            resp = _weather.handle_weather_command("weather")
            txt = resp[0] if isinstance(resp, tuple) else resp or ""

        lines = [l.strip() for l in (txt or "").splitlines() if l.strip()]
        if not lines:
            return ""

        header = next((l for l in lines[:3] if "Current Weather" in l), None)

        wanted_keys = (
            "Outdoor", "Indoor", "Wind", "Solar", "Chance of rain", "Outlook",
            "Humidity", "Pressure", "Feels like"
        )
        wanted_emojis_starts = ("🌡", "🏠", "🌬", "💨", "⚡", "☔", "🌧", "🌤", "🌥", "☀")

        metrics: List[str] = []
        for l in lines:
            if any(k in l for k in wanted_keys) or l.startswith(wanted_emojis_starts):
                metrics.append(l)

        parts: List[str] = []
        if header:
            parts.append(header)
        parts.extend(metrics[:6])

        if not parts:
            parts = lines[:6]

        return " | ".join(parts)
    except Exception:
        return ""

# ---------------------------------------------------------------------------
# ADDITIVE EXTENSIONS BELOW — Analytics / Orchestrator / Sentinel Summaries
# ---------------------------------------------------------------------------

def _analytics_summary() -> str:
    try:
        import analytics
        if hasattr(analytics, "get_service_summary"):
            res = analytics.get_service_summary()
            if isinstance(res, dict):
                up = res.get("up", 0)
                down = res.get("down", 0)
                degraded = res.get("degraded", 0)
                uptime = res.get("uptime") or res.get("uptime_percent") or None
                summary = f"🟢 Up: {up} | 🔴 Down: {down} | 🟡 Degraded: {degraded}"
                if uptime is not None:
                    try:
                        pct = float(uptime)
                        summary += f" | 📈 Uptime: {pct:.2f}%"
                    except Exception:
                        summary += f" | 📈 Uptime: {uptime}"
                return summary
        elif hasattr(analytics, "get_active_services"):
            active = len(analytics.get_active_services())
            return f"🟢 Active services: {active}"
    except Exception:
        pass
    return ""

def _orchestrator_summary() -> str:
    try:
        import orchestrator
        if hasattr(orchestrator, "get_recent_jobs"):
            jobs = orchestrator.get_recent_jobs(limit=5)
            if isinstance(jobs, list):
                succeeded = [j for j in jobs if j.get("status") == "success"]
                failed = [j for j in jobs if j.get("status") == "failed"]
                return f"✅ Jobs ran: {len(jobs)} | ❌ Failed: {len(failed)} | ✅ Success: {len(succeeded)}"
    except Exception:
        pass
    return ""

def _sentinel_summary() -> str:
    try:
        import sentinel
        if hasattr(sentinel, "get_recent_repairs"):
            repairs = sentinel.get_recent_repairs(limit=5)
            if isinstance(repairs, list) and repairs:
                latest = repairs[0]
                rid = latest.get("id", "?")
                name = latest.get("service") or latest.get("name") or latest.get("description") or "unknown"
                return f"🛠 Repairs today: {len(repairs)} (latest: {rid} — {name})"
    except Exception:
        pass
    return ""

# ---------------------------------------------------------------------------
# Digest Builder — Extended with System Overview Sections
# ---------------------------------------------------------------------------

def build_digest(options: Dict[str, Any]) -> Tuple[str, str, int]:
    title = f"📰 Daily Digest — {datetime.now().strftime('%a %d %b %Y')}"

    movies = _movies_today(options)
    series = _series_today(options)
    weather = _weather_today(options)
    analytics = _analytics_summary()
    orchestrator = _orchestrator_summary()
    sentinel = _sentinel_summary()

    parts = [
        _section("🎬 Movies Today", movies),
        _section("📺 Series Today", series),
        _section("⛅ Weather Today", weather),
        _section("📊 Analytics", analytics),
        _section("⚙️ Orchestrator", orchestrator),
        _section("🛠 Sentinel", sentinel),
    ]

    msg = "\n".join([p for p in parts if p]).strip() or "_No data for today._"
    _emit_to_jarvis(title, msg, 5, ["digest", "daily", "system"])
    return title, msg, 5