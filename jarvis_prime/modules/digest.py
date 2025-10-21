#!/usr/bin/env python3
import os, json, time, socket, requests
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

# Web API runs on :2581 not :2599
_API_HOSTS = [
    "http://127.0.0.1:2581/api",
    "http://localhost:2581/api"
]

CACHE_PATH = "/data/digest_cache.json"

# ---------------------------------------------------------------------------
# Logging + Port Wait Helpers
# ---------------------------------------------------------------------------

def _log(msg: str):
    try:
        print(f"[digest] {msg}", flush=True)
    except Exception:
        pass


def _wait_for_port(host: str, port: int, timeout: int = 20) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=2):
                _log(f"[wait] Port {port} open on {host}")
                return True
        except OSError:
            time.sleep(1)
    _log(f"[wait] Port {port} not open after {timeout}s")
    return False


def _get_json(endpoint: str) -> Dict[str, Any]:
    """Wait for API to respond with valid JSON before giving up."""
    _wait_for_port("127.0.0.1", 2581)
    start = time.time()
    while time.time() - start < 25:
        for base in _API_HOSTS:
            url = f"{base}{endpoint}"
            try:
                r = requests.get(url, timeout=5)
                if r.ok:
                    try:
                        data = r.json()
                        _log(f"[api] {endpoint} → OK via {base}")
                        return data
                    except Exception:
                        _log(f"[api] {endpoint} → invalid JSON from {base}")
                else:
                    _log(f"[api] {endpoint} → HTTP {r.status_code}")
            except Exception as e:
                if "Connection refused" in str(e) or "timed out" in str(e):
                    time.sleep(1)
                    continue
                _log(f"[api] {endpoint} → {type(e).__name__}: {e}")
        time.sleep(2)
    _log(f"[api] {endpoint} → failed after retries")
    return {}

# ---------------------------------------------------------------------------
# Emitter + Cache helpers
# ---------------------------------------------------------------------------

def _emit_to_jarvis(title: str, message: str, priority: int = 5, tags: List[str] | None = None) -> bool:
    try:
        _wait_for_port("127.0.0.1", 2599)
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
        _log(f"[emit] Digest sent → {JARVIS_EMIT_URL}")
        return True
    except Exception as e:
        _log(f"[emit] Failed: {e}")
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
# API-Based Sections
# ---------------------------------------------------------------------------

def _analytics_summary() -> str:
    cache = _load_cache()
    data = _get_json("/analytics/health-score")
    if data:
        up = data.get("up_services", 0)
        down = data.get("down_services", 0)
        total = data.get("total_services", 0)
        health = float(data.get("health_score", 0))
        today_key = datetime.now().strftime("%Y-%m-%d")
        yesterday = cache.get("analytics", {}).get("last_health")
        delta = ""
        if yesterday is not None:
            diff = round(health - yesterday, 2)
            if abs(diff) >= 0.1:
                delta = f" ({'📈' if diff > 0 else '📉'} {diff:+.2f}%)"
        cache["analytics"] = {"last_date": today_key, "last_health": health}
        _save_cache(cache)
        return f"🟢 Up: {up}/{total} | 🔴 Down: {down} | 📈 Health: {health:.2f}%{delta}"
    _log("[analytics] summary: no data returned.")
    return ""

def _orchestrator_summary() -> str:
    data = _get_json("/orchestrator/history?limit=20")
    jobs = data.get("jobs", [])
    if isinstance(jobs, list):
        total = len(jobs)
        success = sum(1 for j in jobs if j.get("status") == "success")
        failed = sum(1 for j in jobs if j.get("status") == "failed")
        return f"✅ Jobs: {total} | ✅ Success: {success} | ❌ Failed: {failed}"
    _log("[orchestrator] summary: no data returned.")
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
            uptime_str = str(uptime)
        return f"🛠 Repairs: {repairs} | 🔴 Down: {down} | 📈 Uptime: {uptime_str}"
    _log("[sentinel] summary: no data returned.")
    return ""

# ---------------------------------------------------------------------------
# Digest Builder
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