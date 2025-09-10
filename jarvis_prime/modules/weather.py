import json, yaml, requests, random
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any

# -----------------------------
# Load config from /data/options.json (JSON or YAML). Fallback: /data/config.json
# -----------------------------
def _load_options() -> Dict[str, Any]:
    paths = ["/data/options.json", "/data/config.json"]
    merged: Dict[str, Any] = {}
    for p in paths:
        try:
            with open(p, "r") as f:
                text = f.read()
                try:
                    cfg = json.loads(text)        # try JSON first
                except json.JSONDecodeError:
                    cfg = yaml.safe_load(text)    # fallback to YAML
                if isinstance(cfg, dict):
                    merged.update(cfg)
        except Exception:
            continue
    return merged

_options = _load_options()

# Core weather options
ENABLED = bool(_options.get("weather_enabled", False))
LAT = _options.get("weather_lat", -26.2041)
LON = _options.get("weather_lon", 28.0473)
CITY = _options.get("weather_city", "Unknown")

# Optional Home Assistant (for indoor temp line)
# Accept BOTH classic ha_* keys and EnviroGuard llm_enviroguard_ha_* keys.
HA_ENABLED = bool(
    _options.get("ha_enabled", False)
    or _options.get("llm_enviroguard_ha_enabled", False)
    or _options.get("weather_show_indoor", False)
)

HA_BASE_URL = (
    str(
        _options.get("ha_base_url")
        or _options.get("llm_enviroguard_ha_base_url")
        or ""
    ).rstrip("/")
)

HA_TOKEN = str(
    _options.get("ha_token")
    or _options.get("llm_enviroguard_ha_token")
    or ""
).strip()

# allow multiple key names; first non-empty wins (entity can come from either side)
HA_INDOOR_ENTITY = (
    str(_options.get("ha_indoor_temp_entity") or "") or
    str(_options.get("weather_indoor_sensor_entity") or "") or
    str(_options.get("llm_enviroguard_ha_temp_entity") or "") or
    str(_options.get("ha_temp_entity") or "") or
    str(_options.get("ha_temp_entity_id") or "") or
    str(_options.get("weather_ha_temp_entity_id") or "")
).strip()

# -----------------------------
# Helpers
# -----------------------------
def _get_json(url):
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def _icon_for_code(code, big=False):
    mapping = {
        0: "☀️" if big else "☀",
        1: "🌤" if big else "🌤",
        2: "⛅" if big else "⛅",
        3: "☁️" if big else "☁",
        45: "🌫" if big else "🌫",
        48: "🌫" if big else "🌫",
        51: "🌦" if big else "🌦",
        53: "🌦" if big else "🌦",
        55: "🌧" if big else "🌧",
        61: "🌦" if big else "🌦",
        63: "🌧" if big else "🌧",
        65: "⛈" if big else "⛈",
        71: "❄️" if big else "❄",
        73: "❄️" if big else "❄",
        75: "❄️" if big else "❄",
        77: "🌨" if big else "🌨",
        80: "🌦" if big else "🌦",
        81: "🌧" if big else "🌧",
        82: "⛈" if big else "⛈",
        85: "❄️" if big else "❄",
        86: "❄️" if big else "❄",
        95: "⛈" if big else "⛈",
        96: "⛈" if big else "⛈",
        99: "⛈" if big else "⛈"
    }
    return mapping.get(code, "🌍")

def _commentary(temp_max, code):
    hot_lines = [
        "🔥 Scorching hot today — stay hydrated and find some shade!",
        "☀️ Sun’s blazing, don’t forget sunscreen.",
        "🥵 The heat is on — perfect excuse for ice cream.",
        "🌞 Hot day ahead, keep your energy cool.",
        "🔥 Expect high temps, slow down and take it easy."
    ]
    warm_lines = [
        "😎 Beautiful warm weather — enjoy it while it lasts.",
        "🌤 Great day to be outdoors.",
        "😊 Pleasant temps — perfect for a walk.",
        "☀️ Warm and cozy, nothing extreme.",
        "🌼 Feels like a proper summer’s day."
    ]
    mild_lines = [
        "🙂 A mild day — comfortable all around.",
        "🌤 Not too hot, not too cold — just right.",
        "🍃 Balanced weather, easy on the body.",
        "☁️ Calm and moderate day ahead.",
        "👍 Perfectly tolerable conditions."
    ]
    cold_lines = [
        "❄️ Brrr — chilly day, layer up!",
        "🥶 Cold weather incoming, wear something thick.",
        "🌬 Wind chill will make it feel colder.",
        "🧥 Jacket weather, no doubt.",
        "🔥 Good day for a hot drink inside."
    ]
    rain_lines = [
        "🌧 Showers expected — keep an umbrella handy.",
        "☔ Rain on the way, don’t get caught off guard.",
        "🌦 Cloudbursts could surprise you.",
        "🌧 Wet weather day, roads may be slippery.",
        "⛈ Storm risk — drive safe."
    ]
    snow_lines = [
        "❄️ Snow incoming — magical but cold.",
        "☃️ Bundle up, it’s snow time.",
        "🌨 Expect flakes in the air today.",
        "❄️ Slippery conditions possible.",
        "🏔 Winter wonderland vibes."
    ]
    storm_lines = [
        "⚡ Thunderstorm risk — stay indoors if possible.",
        "⛈ Lightning expected, unplug sensitive gear.",
        "🌪 Severe weather — caution advised.",
        "💨 Strong winds could cause disruptions.",
        "⛔ Avoid unnecessary travel if storm worsens."
    ]

    if code in [61,63,65,80,81,82]:
        return random.choice(rain_lines)
    if code in [71,73,75,85,86]:
        return random.choice(snow_lines)
    if code in [95,96,99]:
        return random.choice(storm_lines)

    if isinstance(temp_max, (int, float)):
        if temp_max >= 30:
            return random.choice(hot_lines)
        elif 20 <= temp_max < 30:
            return random.choice(warm_lines)
        elif 10 <= temp_max < 20:
            return random.choice(mild_lines)
        elif temp_max < 10:
            return random.choice(cold_lines)

    return "🌤 Looks like a balanced day ahead."

def _kv(label, value):
    return f"    {label}: {value}"

# -----------------------------
# Home Assistant: optional indoor temperature fetch
# -----------------------------
def _ha_get_state(entity_id: str) -> Optional[Dict[str, Any]]:
    if not (HA_ENABLED and HA_BASE_URL and HA_TOKEN and entity_id):
        return None
    try:
        url = f"{HA_BASE_URL}/api/states/{entity_id}"
        headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
        r = requests.get(url, headers=headers, timeout=8)
        if not r.ok:
            return None
        return r.json()
    except Exception:
        return None

def _get_ha_indoor_temp_c() -> Optional[float]:
    st = _ha_get_state(HA_INDOOR_ENTITY) if HA_INDOOR_ENTITY else None
    if not st:
        return None
    # Prefer numeric state, else attribute 'temperature'
    cand = st.get("state")
    try:
        v = float(cand)
        return v
    except Exception:
        pass
    attrs = st.get("attributes") or {}
    for k in ("temperature", "current_temperature", "temp", "value"):
        if k in attrs:
            try:
                return float(attrs[k])
            except Exception:
                continue
    return None

# -----------------------------
# ADDITIVE: lightweight probe for controllers (EnviroGuard, etc.)
# -----------------------------
def get_current_snapshot() -> Dict[str, Any]:
    """
    Lightweight current-weather probe for controllers.
    Returns: {
        "enabled": bool,
        "city": str,
        "temp_c": Optional[float],
        "code": Optional[int],
        "time": Optional[str],
        "lat": float,
        "lon": float,
        "source": "open-meteo"
    }
    """
    if not ENABLED:
        return {
            "enabled": False, "city": CITY, "temp_c": None, "code": None,
            "time": None, "lat": LAT, "lon": LON, "source": "open-meteo"
        }
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={LAT}&longitude={LON}"
        f"&current_weather=true"
        f"&temperature_unit=celsius&windspeed_unit=kmh"
    )
    data = _get_json(url)
    cw = (data or {}).get("current_weather", {}) if isinstance(data, dict) else {}
    temp = cw.get("temperature", None)
    code = cw.get("weathercode", None)
    ts   = cw.get("time", None)
    try:
        temp = float(temp) if temp is not None else None
    except Exception:
        temp = None
    return {
        "enabled": True, "city": CITY, "temp_c": temp, "code": code,
        "time": ts, "lat": LAT, "lon": LON, "source": "open-meteo"
    }

def get_today_peak_c() -> Optional[float]:
    """
    Returns today's forecasted max temperature in °C (if available), else None.
    """
    if not ENABLED:
        return None
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={LAT}&longitude={LON}"
        f"&daily=temperature_2m_max"
        f"&timezone=auto&temperature_unit=celsius"
    )
    data = _get_json(url)
    daily = (data or {}).get("daily", {}) if isinstance(data, dict) else {}
    arr = daily.get("temperature_2m_max") or []
    if not arr:
        return None
    try:
        return float(arr[0])
    except Exception:
        return None

# -----------------------------
# Current Weather
# -----------------------------
def current_weather():
    if not ENABLED:
        return "⚠️ Weather module not enabled", None
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={LAT}&longitude={LON}"
        f"&current_weather=true"
        f"&temperature_unit=celsius&windspeed_unit=kmh"
    )
    data = _get_json(url)
    if "error" in data:
        return f"⚠️ Weather API error: {data['error']}", None
    cw = data.get("current_weather", {})
    if not cw:
        return "⚠️ No current weather data returned", None

    temp = cw.get("temperature", "?")
    wind = cw.get("windspeed", "?")
    code = cw.get("weathercode", -1)
    icon_big = _icon_for_code(code, big=True)

    # Optional: Home Assistant indoor temperature
    indoor_c = _get_ha_indoor_temp_c()

    # Sleek aligned block
    lines = []
    lines.append(f"{icon_big} Current Weather — {CITY}")
    lines.append(_kv("🌡 Outdoor", f"{temp}°C"))
    if indoor_c is not None:
        lines.append(_kv("🏠 Indoor", f"{indoor_c:.1f}°C"))
    lines.append(_kv("🌬 Wind", f"{wind} km/h"))
    ts = cw.get("time")
    if ts:
        lines.append(_kv("🕒 As of", ts))
    return "\n".join(lines), None

# -----------------------------
# Forecast (7 days, sleek aligned list — no tables)
# -----------------------------
def forecast_weather():
    if not ENABLED:
        return "⚠️ Weather module not enabled", None
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={LAT}&longitude={LON}"
        f"&daily=temperature_2m_max,temperature_2m_min,weathercode"
        f"&timezone=auto&temperature_unit=celsius"
    )
    data = _get_json(url)
    if "error" in data:
        return f"⚠️ Weather API error: {data['error']}", None

    daily = data.get("daily", {})
    times = daily.get("time", []) or []
    tmins = daily.get("temperature_2m_min", []) or []
    tmaxs = daily.get("temperature_2m_max", []) or []
    codes = daily.get("weathercode", []) or []

    if not times:
        return "⚠️ No forecast data returned", None

    # Today (index 0)
    tmin0 = tmins[0] if len(tmins) > 0 else "?"
    tmax0 = tmaxs[0] if len(tmaxs) > 0 else "?"
    code0 = codes[0] if len(codes) > 0 else -1
    icon0_big = _icon_for_code(code0, big=True)

    # Optional: Home Assistant indoor temperature (include alongside today's range)
    indoor_c = _get_ha_indoor_temp_c()

    lines = []
    lines.append(f"{icon0_big} Today — {CITY}")
    lines.append(_kv("Range", f"{tmin0}°C – {tmax0}°C"))
    if indoor_c is not None:
        lines.append(_kv("🏠 Indoor", f"{indoor_c:.1f}°C"))
    # cast tmax0 to float for commentary if possible
    try:
        tmax0_f = float(tmax0)
    except Exception:
        tmax0_f = None
    lines.append(_kv("Outlook", _commentary(tmax0_f, code0)))

    # Next days
    lines.append("")
    lines.append(f"📅 7-Day Outlook — {CITY}")
    for i in range(0, min(7, len(times))):
        date = times[i]
        tmin = tmins[i] if i < len(tmins) else "?"
        tmax = tmaxs[i] if i < len(tmaxs) else "?"
        code = codes[i] if i < len(codes) else -1
        icon = _icon_for_code(code, big=False)
        prefix = "• Today" if i == 0 else f"• {date}"
        lines.append(f"{prefix} — {tmin}°C to {tmax}°C {icon}")

    return "\n".join(lines), None

# -----------------------------
# Command Router
# -----------------------------
def handle_weather_command(command: str):
    cmd = command.lower().strip()
    if "forecast" in cmd:
        return forecast_weather()
    if any(word in cmd for word in ["weather", "temperature", "temp", "now", "today"]):
        return current_weather()
    return "⚠️ Unknown weather command", None
