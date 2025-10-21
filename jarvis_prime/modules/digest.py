#!/usr/bin/env python3
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

# ✅ Multi-host fallback for Home Assistant + Docker
_API_HOSTS = [
    "http://127.0.0.1:2599/api",
    "http://localhost:2599/api",
    "http://jarvis_prime:2599/api"
]

CACHE_PATH = "/data/digest_cache.json"

# ---------------------------------------------------------------------------
# Internal utility functions
# ---------------------------------------------------------------------------

def _log(msg: str):
    """Basic print logger for debugging (optional)."""
    try:
        print(f"[digest] {msg}", flush=True)
    except Exception:
        pass

def _get_json(endpoint: str) -> Dict[str, Any]:
    """Try fetching JSON from multiple possible API base URLs."""
    for base in _API_HOSTS:
        url = f"{base}{endpoint}"
        try:
            r = requests.get(url, timeout=5)
            if r.ok:
                _log(f"Fetched {endpoint} from {base}")
                return r.json()
        except Exception as e:
            _log(f"Failed {base}{endpoint}: {e}")
            continue
    return {}

def _emit_to_jarvis(title: str, message: str, priority: int = 5, tags: List[str] | None = None) -> bool:
    try:
        payload = {
            "source": "digest",
            "title": f"{BOT_ICON} {BOT_NAME}: {title}",
            "message": message,
            "priority": priority,
            "tags": tags or ["digest", "daily", "system"],
            "icon": BOT_ICON,
            "app": BOT_NAME,
        }
        r = requests.post(JARVIS_EMIT_URL, json=payload, timeout=6,
                          headers={"Content-Type": "application/json; charset=utf-8"})
        r.raise_for_status()
        _log(f"Digest emitted successfully to {JARVIS_EMIT_URL}")
        return True
    except Exception as e:
        _log(f"Emit failed: {e}")
        return False

def _section(title: str, body: str) -> str:
    return f"**{title}**\n{body.strip()}\n" if body else ""

def _bulletize(text_or_list, limit: int = 10) -> str:
    if isinstance(text_or_list, str):
        lines = [l.strip() for l in text_or_list.splitlines() if l.strip()]
    else:
        lines = [str(x).strip() for x in (text_or_list or []) if str(x).strip()]
    return "\n".join([("- " + l if not l.startswith("- ") else l) for l in lines[:limit]])

def _load_cache() -> Dict[str, Any]:
    try:
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_cache(data: Dict[str, Any]):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# ARR + Weather
# ---------------------------------------------------------------------------

def _movies_today(opts: Dict[str, Any]) -> str:
    if not _arr or not opts.get("radarr_enabled"):
        return ""
    for fn in ("upcoming_movies", "today_upcoming_movies", "list_upcoming_movies"):
        if hasattr(_arr, fn):
            try:
                res = getattr(_arr, fn)(1) if fn == "upcoming_movies" else getattr(_arr, fn)(opts)
                if isinstance(res, str) and res.strip():
                    return _bulletize(res, 10)
                if isinstance(res, (list, tuple)) and res:
                    return _bulletize(res, 10)
            except Exception:
                pass
    return ""

def _series_today(opts: Dict[str, Any]) -> str:
    if not _arr or not opts.get("sonarr_enabled"):
        return ""
    for fn in ("upcoming_series", "today_upcoming_series", "list_upcoming_series"):
        if hasattr(_arr, fn):
            try:
                res = getattr(_arr, fn)(1) if fn == "upcoming_series" else getattr(_arr, fn)(opts)
                if isinstance(res, str) and res.strip():
                    return _bulletize(res, 10)
                if isinstance(res, (list, tuple)) and res:
                    return _bulletize(res, 10)
            except Exception:
                pass
    return ""

def _weather_today(opts: Dict[str, Any]) -> str:
    if not _weather or not opts.get("weather_enabled"):
        return ""
    try:
        txt = ""
        if hasattr(_weather, "get_current_summary"):
            maybe = _weather.get_current_summary()
            if isinstance(maybe, dict):
                order = ["location", "as_of", "outdoor", "indoor", "wind", "solar", "chance_of_rain", "outlook"]
                parts = [str(maybe.get(k)) for k in order if maybe.get(k)]
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
        wanted_keys = ("Outdoor", "Indoor", "Wind", "Solar", "Chance of rain", "Outlook",
                       "Humidity", "Pressure", "Feels like")
        wanted_emojis_starts = ("🌡", "🏠", "🌬", "💨", "⚡", "☔", "🌧", "🌤", "🌥", "☀")
        metrics = [l for l in lines if any(k in l for k in wanted_keys) or l.startswith(wanted_emojis_starts)]
        parts = [header] if header else []
        parts.extend(metrics[:6])
        if not parts:
            parts = lines[:6]
        return " | ".join(parts)
    except Exception:
        return ""

# ---------------------------------------------------------------------------
# API-based summaries (Analytics, Orchestrator, Sentinel)
# ---------------------------------------------------------------------------

def _analytics_summary() -> str:
    cache = _load_cache()
    data = _get_json("/analytics/health-score")
    if data:
        up = data.get("up_services", 0)
        down = data.get("down_services", 0)
        total = data.get("total_services", 0)
        try:
            health = float(data.get("health_score", 0))
        except Exception:
            health = 0.0
        today_key = datetime.now().strftime("%Y-%m-%d")
        yesterday_health = cache.get("analytics", {}).get("last_health", None)
        delta_str = ""
        if yesterday_health is not None:
            diff = round(health - yesterday_health, 2)
            if abs(diff) >= 0.1:
                arrow = "📈" if diff > 0 else "📉"
                delta_str = f" ({arrow} {diff:+.2f}%)"
        cache["analytics"] = {"last_date": today_key, "last_health": health}
        _save_cache(cache)
        return f"🟢 Up: {up}/{total} | 🔴 Down: {down} | 📈 Health: {health:.2f}%{delta_str}"
    _log("Analytics summary: no data returned.")
    return ""

def _orchestrator_summary() -> str:
    data = _get_json("/orchestrator/history?limit=20")
    jobs = data.get("jobs", [])
    if isinstance(jobs, list):
        total = len(jobs)
        succeeded = sum(1 for j in jobs if j.get("status") == "success")
        failed = sum(1 for j in jobs if j.get("status") == "failed")
        return f"✅ Jobs: {total} | ✅ Success: {succeeded} | ❌ Failed: {failed}"
    _log("Orchestrator summary: no jobs returned.")
    return ""

def _sentinel_summary() -> str:
    data = _get_json("/sentinel/dashboard")
    if data:
        down = data.get("services_down", 0)
        repairs = data.get("repairs_today", 0)
        uptime = data.get("uptime_percent", "N/A")
        try:
            uptime_str = f"{float(uptime):.2f}%"
        except Exception:
            uptime_str = f"{uptime}"
        return f"🛠 Repairs: {repairs} | 🔴 Down: {down} | 📈 Uptime: {uptime_str}"
    _log("Sentinel summary: no data returned.")
    return ""

# ---------------------------------------------------------------------------
# Digest Builder — Combined view
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