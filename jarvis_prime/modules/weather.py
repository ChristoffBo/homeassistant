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
# ADDITIVE: Solar thresholds & helpers (radiation-first, cloudcover fallback)
# -----------------------------
# Radiation thresholds (no new settings; keep it simple)
RADIATION_LOW  = 10.0  # MJ/m²/day
RADIATION_HIGH = 20.0  # MJ/m²/day
# Cloud-cover thresholds for fallback
SOLAR_THRESHOLDS = {"high_max_cloud": 30, "med_max_cloud": 70}

def _solar_class_from_radiation(mj_per_m2: float) -> str:
    try:
        v = float(mj_per_m2)
    except Exception:
        return "UNKNOWN"
    if v > RADIATION_HIGH:
        return "HIGH"
    if v >= RADIATION_LOW:
        return "MED"
    return "LOW"

def _solar_class_from_cloudcover(pct: float) -> str:
    try:
        p = float(pct)
    except Exception:
        return "UNKNOWN"
    if p < SOLAR_THRESHOLDS["high_max_cloud"]:
        return "HIGH"
    if p <= SOLAR_THRESHOLDS["med_max_cloud"]:
        return "MED"
    return "LOW"

def _solar_line_from_values(label: str, *, rad: Optional[float], cloud_pct: Optional[float]) -> str:
    if rad is not None:
        try:
            v = float(rad)
            return _kv(label, f"{_solar_class_from_radiation(v)} ⚡ ({v:.1f} MJ/m²)")
        except Exception:
            pass
    if cloud_pct is not None:
        try:
            c = float(cloud_pct)
            return _kv(label, f"{_solar_class_from_cloudcover(c)} ⚡ (cloud {c:.0f}%)")
        except Exception:
            pass
    return _kv(label, "—")

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
# Current Weather (temp command shows today's solar/rain/hail too)
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
    code_now = cw.get("weathercode", -1)
    icon_big = _icon_for_code(code_now, big=True)

    indoor_c = _get_ha_indoor_temp_c()

    lines = []
    lines.append(f"{icon_big} Current Weather — {CITY}")
    lines.append(_kv("🌡 Outdoor", f"{temp}°C"))
    if indoor_c is not None:
        lines.append(_kv("🏠 Indoor", f"{indoor_c:.1f}°C"))
    lines.append(_kv("🌬 Wind", f"{wind} km/h"))
    ts = cw.get("time")
    if ts:
        lines.append(_kv("🕒 As of", ts))

    # Today's solar/rain/hail (radiation first, fallback to cloudcover)
    fc_url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={LAT}&longitude={LON}"
        f"&daily=cloudcover,shortwave_radiation_sum,precipitation_probability_max,weathercode"
        f"&timezone=auto"
    )
    fc = _get_json(fc_url)
    daily_fc = (fc or {}).get("daily") or {}
    cloud_today = (daily_fc.get("cloudcover") or [None])[0]
    rad_today   = (daily_fc.get("shortwave_radiation_sum") or [None])[0]
    prob_today  = (daily_fc.get("precipitation_probability_max") or [None])[0]
    code_today  = (daily_fc.get("weathercode") or [None])[0]

    lines.append(_solar_line_from_values("⚡ Solar (today)", rad=rad_today, cloud_pct=cloud_today))
    if isinstance(prob_today, (int, float)) and prob_today > 0:
        label = "☔ Chance of rain" if prob_today < 60 else "⚠️ High chance of rain"
        lines.append(_kv(label, f"{prob_today}%"))
    # Hail risk for the day
    if code_today in (95, 96, 99):
        lines.append("⚠️ Severe storm risk — hail possible.")

    return "\n".join(lines), None

# -----------------------------
# Forecast (always starts at Today; bullets show only HIGH/MED/LOW)
# -----------------------------
def forecast_weather():
    if not ENABLED:
        return "⚠️ Weather module not enabled", None
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={LAT}&longitude={LON}"
        f"&daily=temperature_2m_max,temperature_2m_min,weathercode,cloudcover,shortwave_radiation_sum,precipitation_probability_max"
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
    clouds = daily.get("cloudcover", []) or []
    rads   = daily.get("shortwave_radiation_sum", []) or []
    probs  = daily.get("precipitation_probability_max", []) or []

    if not times:
        return "⚠️ No forecast data returned", None

    # Always start at Today
    start_idx = 0

    # Header block (Today)
    idx = start_idx
    tmin0 = tmins[idx] if len(tmins) > idx else "?"
    tmax0 = tmaxs[idx] if len(tmaxs) > idx else "?"
    code0 = codes[idx] if len(codes) > idx else -1
    cloud0 = clouds[idx] if len(clouds) > idx else None
    rad0 = rads[idx] if len(rads) > idx else None
    prob0 = probs[idx] if len(probs) > idx else None
    icon0_big = _icon_for_code(code0, big=True)

    indoor_c = _get_ha_indoor_temp_c()

    lines = []
    lines.append(f"{icon0_big} Today — {CITY}")
    lines.append(_kv("Range", f"{tmin0}°C – {tmax0}°C"))
    if indoor_c is not None:
        lines.append(_kv("🏠 Indoor", f"{indoor_c:.1f}°C"))
    try:
        tmax0_f = float(tmax0)
    except Exception:
        tmax0_f = None
    lines.append(_kv("Outlook", _commentary(tmax0_f, code0)))
    # Detailed solar for the header is kept (can remove if you want)
    lines.append(_solar_line_from_values("⚡ Solar", rad=rad0, cloud_pct=cloud0))
    if isinstance(prob0, (int, float)) and prob0 > 0:
        label = "☔ Chance of rain" if prob0 < 60 else "⚠️ High chance of rain"
        lines.append(_kv(label, f"{prob0}%"))
    if code0 in (95,96,99):
        lines.append("⚠️ Severe storm risk — hail possible.")

    # 7-day list starting at Today (only HIGH/MED/LOW for solar)
    lines.append("")
    lines.append(f"📅 7-Day Outlook — {CITY}")
    for i in range(start_idx, min(start_idx + 7, len(times))):
        date = times[i]
        tmin = tmins[i] if i < len(tmins) else "?"
        tmax = tmaxs[i] if i < len(tmaxs) else "?"
        code = codes[i] if i < len(codes) else -1
        icon = _icon_for_code(code, big=False)
        cloud = clouds[i] if i < len(clouds) else None
        rad = rads[i] if i < len(rads) else None
        prob = probs[i] if i < len(probs) else None

        # Only show HIGH/MED/LOW (no units)
        if rad is not None:
            solar_str = f"⚡ {_solar_class_from_radiation(rad)}"
        elif cloud is not None:
            solar_str = f"⚡ {_solar_class_from_cloudcover(cloud)}"
        else:
            solar_str = "⚡ —"

        rain_str = f" · ☔ {prob}%" if isinstance(prob, (int, float)) and prob > 0 else ""
        prefix = "• Today" if i == 0 else f"• {date}"

        lines.append(f"{prefix} — {tmin}°C to {tmax}°C {icon}  ·  {solar_str}{rain_str}")
        if code in (95,96,99):
            lines.append("    ⚠️ Severe storm risk — hail possible.")

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
    if "solar" in cmd:
        return forecast_weather()
    return "⚠️ Unknown weather command", None