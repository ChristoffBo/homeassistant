import json, yaml, requests, random, os, io
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

# Optional Home Assistant (for indoor temp line only)
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
HA_INDOOR_ENTITY = (
    str(_options.get("ha_indoor_temp_entity") or "") or
    str(_options.get("weather_indoor_sensor_entity") or "") or
    str(_options.get("llm_enviroguard_ha_temp_entity") or "") or
    str(_options.get("ha_temp_entity") or "") or
    str(_options.get("ha_temp_entity_id") or "") or
    str(_options.get("weather_ha_temp_entity_id") or "")
).strip()

# -----------------------------
# Solar thresholds & helpers
# -----------------------------
RADIATION_LOW  = 10.0  # MJ/m²/day
RADIATION_HIGH = 20.0  # MJ/m²/day
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

def _solar_compact_label(rad: Optional[float], cloud_pct: Optional[float]) -> str:
    try:
        if rad is not None:
            v = float(rad)
            if v <= 0:
                return "⚡ Night"
            return f"⚡ {_solar_class_from_radiation(v)}"
    except Exception:
        pass
    try:
        if cloud_pct is not None:
            return f"⚡ {_solar_class_from_cloudcover(float(cloud_pct))}"
    except Exception:
        pass
    return "⚡ —"

def _solar_line_from_values(label: str, *, rad: Optional[float], cloud_pct: Optional[float]) -> str:
    try:
        if rad is not None:
            v = float(rad)
            return _kv(label, f"{_solar_class_from_radiation(v)} ⚡ ({v:.1f} MJ/m²)")
    except Exception:
        pass
    try:
        if cloud_pct is not None:
            c = float(cloud_pct)
            return _kv(label, f"{_solar_class_from_cloudcover(c)} ⚡ (cloud {c:.0f}%)")
    except Exception:
        pass
    return _kv(label, "—")

# -----------------------------
# HTTP helpers
# -----------------------------
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

def _get_json(url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

# -----------------------------
# Secondary free sources + blending
# -----------------------------
def _get_metno_daily(lat: float, lon: float) -> Dict[str, Optional[float]]:
    try:
        url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}"
        headers = {"User-Agent": "JarvisPrime/1.0"}
        data = _get_json(url, headers=headers)
        ts = (data.get("properties", {}) or {}).get("timeseries", [])[:24]
        temps, pops = [], []
        for p in ts:
            inst = (p.get("data", {}).get("instant", {}).get("details", {}) or {})
            if "air_temperature" in inst:
                temps.append(float(inst["air_temperature"]))
            for nxt in ("next_1_hours", "next_6_hours"):
                d = (p.get("data", {}).get(nxt, {}).get("details", {}) or {})
                if "probability_of_precipitation" in d:
                    pops.append(float(d["probability_of_precipitation"]))
        return {
            "tmax": max(temps) if temps else None,
            "tmin": min(temps) if temps else None,
            "pop": max(pops) if pops else None,
        }
    except Exception:
        return {}

def _get_openmeteo_model(lat: float, lon: float, model: str) -> Dict[str, Optional[float]]:
    try:
        params = {
            "latitude": lat, "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto", "temperature_unit": "celsius",
            "models": model
        }
        data = _get_json(OPEN_METEO, params)
        d = data.get("daily", {}) if data else {}
        return {
            "tmax": (d.get("temperature_2m_max") or [None])[0],
            "tmin": (d.get("temperature_2m_min") or [None])[0],
            "pop": (d.get("precipitation_probability_max") or [None])[0],
        }
    except Exception:
        return {}

def _blend_vals(vals, mode="median") -> Optional[float]:
    nums = [float(x) for x in vals if isinstance(x, (int, float))]
    if not nums: return None
    if mode == "max": return max(nums)
    if mode == "min": return min(nums)
    nums.sort()
    n = len(nums)
    mid = n // 2
    return nums[mid] if n % 2 else (nums[mid-1] + nums[mid]) / 2.0
# -----------------------------
# Icons & commentary
# -----------------------------
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
    hot_lines = ["🔥 Scorching hot today — stay hydrated and find some shade!","☀️ Sun’s blazing, don’t forget sunscreen.","🥵 The heat is on — perfect excuse for ice cream.","🌞 Hot day ahead, keep your energy cool.","🔥 Expect high temps, slow down and take it easy."]
    warm_lines = ["😎 Beautiful warm weather — enjoy it while it lasts.","🌤 Great day to be outdoors.","😊 Pleasant temps — perfect for a walk.","☀️ Warm and cozy, nothing extreme.","🌼 Feels like a proper summer’s day."]
    mild_lines = ["🙂 A mild day — comfortable all around.","🌤 Not too hot, not too cold — just right.","🍃 Balanced weather, easy on the body.","☁️ Calm and moderate day ahead.","👍 Perfectly tolerable conditions."]
    cold_lines = ["❄️ Brrr — chilly day, layer up!","🥶 Cold weather incoming, wear something thick.","🌬 Wind chill will make it feel colder.","🧥 Jacket weather, no doubt.","🔥 Good day for a hot drink inside."]
    rain_lines = ["🌧 Showers expected — keep an umbrella handy.","☔ Rain on the way, don’t get caught off guard.","🌦 Cloudbursts could surprise you.","🌧 Wet weather day, roads may be slippery.","⛈ Storm risk — drive safe."]
    snow_lines = ["❄️ Snow incoming — magical but cold.","☃️ Bundle up, it’s snow time.","🌨 Expect flakes in the air today.","❄️ Slippery conditions possible.","🏔 Winter wonderland vibes."]
    storm_lines = ["⚡ Thunderstorm risk — stay indoors if possible.","⛈ Lightning expected, unplug sensitive gear.","🌪 Severe weather — caution advised.","💨 Strong winds could cause disruptions.","⛔ Avoid unnecessary travel if storm worsens."]

    if code in [61,63,65,80,81,82]:
        return random.choice(rain_lines)
    if code in [71,73,75,85,86]:
        return random.choice(snow_lines)
    if code in [95,96,99]:
        return random.choice(storm_lines)

    if isinstance(temp_max, (int, float)):
        if temp_max >= 30: return random.choice(hot_lines)
        elif 20 <= temp_max < 30: return random.choice(warm_lines)
        elif 10 <= temp_max < 20: return random.choice(mild_lines)
        elif temp_max < 10: return random.choice(cold_lines)
    return "🌤 Looks like a balanced day ahead."

def _kv(label, value):
    return f"    {label}: {value}"

# -----------------------------
# Home Assistant: optional indoor temperature
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
    if not st: return None
    cand = st.get("state")
    try:
        return float(cand)
    except Exception:
        pass
    attrs = st.get("attributes") or {}
    for k in ("temperature","current_temperature","temp","value"):
        if k in attrs:
            try: return float(attrs[k])
            except Exception: continue
    return None

# -----------------------------
# One-time daily alert cache + notify bus
# -----------------------------
ALERTS_PATH = "/data/jarvis_alerts.json"

def _read_alerts_cache() -> Dict[str, Any]:
    try:
        with open(ALERTS_PATH, "r") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _write_alerts_cache(cache: Dict[str, Any]) -> None:
    try:
        with open(ALERTS_PATH, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass

def _today_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")

def _notify_inbox(title: str, message: str, tag: str) -> bool:
    try:
        path = "/data/inbox.ndjson"
        rec = {
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "title": title, "message": message,
            "priority": "max", "tags": ["weather", "alert", tag]
        }
        with open(path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        return True
    except Exception:
        return False
def _notify_gotify(title: str, message: str) -> bool:
    url = os.getenv("GOTIFY_URL")
    token = os.getenv("GOTIFY_TOKEN")
    if not (url and token):
        return False
    try:
        endpoint = url.rstrip("/") + "/message"
        headers = {"X-Gotify-Key": token}
        data = {"title": title, "message": message, "priority": 10}
        r = requests.post(endpoint, headers=headers, data=data, timeout=8)
        return r.ok
    except Exception:
        return False

def _notify_ntfy(title: str, message: str) -> bool:
    base = os.getenv("NTFY_URL")
    topic = os.getenv("NTFY_TOPIC")
    if not (base and topic):
        return False
    try:
        endpoint = base.rstrip("/") + "/" + topic
        headers = {"Title": title, "Priority": "urgent", "Tags": "warning,cloud,thunderstorm"}
        r = requests.post(endpoint, headers=headers, data=message.encode("utf-8"), timeout=8)
        return r.ok
    except Exception:
        return False

def _notify_smtp(title: str, message: str) -> bool:
    bridge = os.getenv("SMTP_BRIDGE_URL")
    if not bridge:
        return False
    try:
        r = requests.post(bridge, json={"subject": title, "body": message, "priority": "high"}, timeout=8)
        return r.ok
    except Exception:
        return False

def _notify_bus(title: str, message: str, tag: str) -> bool:
    sent_any = False
    try:
        try:
            from jarvis_notify import send as jarvis_send  # type: ignore
            jarvis_send(title=title, body=message, priority="max", tags=["weather", "alert", tag])
            sent_any = True
        except Exception:
            pass

        if _notify_gotify(title, message): sent_any = True
        if _notify_ntfy(title, message):   sent_any = True
        if _notify_smtp(title, message):   sent_any = True
    finally:
        _notify_inbox(title, message, tag)  # always persist locally
    return sent_any

def _notify_once_daily(tag: str, title: str, message: str) -> bool:
    cache = _read_alerts_cache()
    key = f"{_today_str()}:{tag}"
    if cache.get(key):
        return False
    _notify_bus(title, message, tag)
    cache[key] = True
    _write_alerts_cache(cache)
    return True

# -----------------------------
# Small helpers
# -----------------------------
def _is_local_night(ts: Optional[str]) -> bool:
    """Heuristic: if local 'As of' hour <06 or >=18 treat as night."""
    if not ts or "T" not in ts:
        return False
    try:
        hh = int(ts.split("T", 1)[1][0:2])
        return (hh < 6) or (hh >= 18)
    except Exception:
        return False

# -----------------------------
# ADDITIVE: lightweight probe for controllers
# -----------------------------
def get_current_snapshot() -> Dict[str, Any]:
    if not ENABLED:
        return {
            "enabled": False, "city": CITY, "temp_c": None, "code": None,
            "time": None, "lat": LAT, "lon": LON, "source": "open-meteo"
        }
    params = {
        "latitude": LAT, "longitude": LON,
        "current_weather": True,
        "temperature_unit": "celsius", "windspeed_unit": "kmh",
    }
    data = _get_json(OPEN_METEO, params)
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

def get_today_peak_c():
    if not ENABLED:
        return None
    params = {
        "latitude": LAT, "longitude": LON,
        "daily": "temperature_2m_max",
        "timezone": "auto", "temperature_unit": "celsius",
    }
    data = _get_json(OPEN_METEO, params)
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

    # current snapshot (Open-Meteo)
    params_now = {
        "latitude": LAT, "longitude": LON,
        "current_weather": True,
        "temperature_unit": "celsius", "windspeed_unit": "kmh",
    }
    data_now = _get_json(OPEN_METEO, params_now) or {}
    cw = data_now.get("current_weather", {}) if isinstance(data_now, dict) else {}
    if not cw:
        return "⚠️ No current weather data returned", None

    temp = cw.get("temperature", "?")
    wind = cw.get("windspeed", "?")
    code_now = cw.get("weathercode", -1)
    icon_big = _icon_for_code(code_now, big=True)
    ts = cw.get("time")
    indoor_c = _get_ha_indoor_temp_c()

    lines = []
    lines.append(f"{icon_big} Current Weather — {CITY}")
    if ts: lines.append(_kv("🕒 As of", ts))
    lines.append(_kv("🌡 Outdoor", f"{temp}°C"))
    if indoor_c is not None: lines.append(_kv("🏠 Indoor", f"{indoor_c:.1f}°C"))
    lines.append(_kv("🌬 Wind", f"{wind} km/h"))

    # Today's daily values (Open-Meteo primary) — add tmax for blending
    params_day = {
        "latitude": LAT, "longitude": LON,
        "daily": "cloudcover_mean,shortwave_radiation_sum,precipitation_probability_max,weathercode,temperature_2m_max",
        "timezone": "auto",
        "temperature_unit": "celsius",
    }
    fc = _get_json(OPEN_METEO, params_day) or {}
    daily_fc = (fc.get("daily") or {}) if isinstance(fc, dict) else {}
    cloud_today = (daily_fc.get("cloudcover_mean") or [None])[0]
    rad_today   = (daily_fc.get("shortwave_radiation_sum") or [None])[0]
    prob_today  = (daily_fc.get("precipitation_probability_max") or [None])[0]
    code_today  = (daily_fc.get("weathercode") or [None])[0]
    tmax_today  = (daily_fc.get("temperature_2m_max") or [None])[0]
    try:
        tmax_today = float(tmax_today) if tmax_today is not None else None
    except Exception:
        tmax_today = None

    # ---- mini-ensemble blending (silent fail) ----
    met = _get_metno_daily(LAT, LON)                         # MET Norway (no key)
    gfs = _get_openmeteo_daily_model(LAT, LON, model="gfs")  # Open-Meteo pinned model

    blended_tmax = _blend_vals([tmax_today, met.get("tmax"), gfs.get("tmax")], mode="median")
    blended_pop  = _blend_vals([prob_today, met.get("pop"),  gfs.get("pop")],  mode="max")

    # Compact Solar label (HIGH/MED/LOW or Night)
    solar_label = _solar_compact_label(rad_today, cloud_today)
    if solar_label == "⚡ —" and _is_local_night(ts):
        solar_label = "⚡ Night"
    lines.append(_kv("⚡ Solar (today)", solar_label[2:]))

    # Chance of rain — use blended if available
    final_pop = blended_pop if isinstance(blended_pop, (int, float)) else prob_today
    if isinstance(final_pop, (int, float)) and final_pop > 0:
        label = "☔ Chance of rain" if final_pop < 60 else "⚠️ High chance of rain"
        lines.append(_kv(label, f"{int(round(final_pop))}%"))

    # Hail/severe-storm note (show only if risky codes)
    if code_today in (95,96,99):
        lines.append("⚠️ Severe storm risk — hail possible.")

    # ---- High-priority alerts (once per day via notify bus) ----
    heavy_rain = isinstance(final_pop, (int, float)) and final_pop >= 70
    thunder = code_today in (95, 96, 99)
    hail = code_today in (96, 99)

    if thunder:
        _notify_once_daily("thunder", f"⛈ Thunderstorm risk — {CITY}",
                           "Thunderstorms forecast for today. High priority.")
    elif hail:
        _notify_once_daily("hail", f"🧊 Hail risk — {CITY}",
                           "Hail possible today. Move vehicles under cover.")
    elif heavy_rain:
        _notify_once_daily("heavy_rain", f"🌧 Heavy rain risk — {CITY}",
                           f"High chance of rain today ({int(final_pop)}%). Watch for flooding.")

    # Replace/ensure the outlook commentary uses blended tmax if available
    comment_temp = blended_tmax if isinstance(blended_tmax, (int, float)) else tmax_today
    if comment_temp is not None:
        lines.append(_kv("Outlook", _commentary(comment_temp, code_today)))

    return "\n".join(lines), None
# -----------------------------
# Forecast (header uses compact solar; bullets are HIGH/MED/LOW)
# -----------------------------
def forecast_weather():
    if not ENABLED:
        return "⚠️ Weather module not enabled", None

    # Primary: Open-Meteo daily; silent fail already handled by _get_json
    params = {
        "latitude": LAT, "longitude": LON,
        "daily": "temperature_2m_max,temperature_2m_min,weathercode,cloudcover_mean,shortwave_radiation_sum,precipitation_probability_max",
        "timezone": "auto",
        "temperature_unit": "celsius",
    }
    data = _get_json(OPEN_METEO, params)
    if not isinstance(data, dict) or "daily" not in data:
        return "⚠️ No forecast data returned", None

    daily = data["daily"]
    times = daily.get("time", []) or []
    tmins = daily.get("temperature_2m_min", []) or []
    tmaxs = daily.get("temperature_2m_max", []) or []
    codes = daily.get("weathercode", []) or []
    clouds = daily.get("cloudcover_mean", []) or []
    rads   = daily.get("shortwave_radiation_sum", []) or []
    probs  = daily.get("precipitation_probability_max", []) or []

    if not times:
        return "⚠️ No forecast data returned", None

    # Today header
    tmin0 = tmins[0] if len(tmins) > 0 else "?"
    tmax0 = tmaxs[0] if len(tmaxs) > 0 else "?"
    code0 = codes[0] if len(codes) > 0 else -1
    cloud0 = clouds[0] if len(clouds) > 0 else None
    rad0 = rads[0] if len(rads) > 0 else None
    prob0 = probs[0] if len(probs) > 0 else None
    icon0_big = _icon_for_code(code0, big=True)

    indoor_c = _get_ha_indoor_temp_c()

    lines = []
    lines.append(f"{icon0_big} Today — {CITY}")
    lines.append(_kv("Range", f"{tmin0}°C – {tmax0}°C"))
    if indoor_c is not None: lines.append(_kv("🏠 Indoor", f"{indoor_c:.1f}°C"))
    try:
        tmax0_f = float(tmax0)
    except Exception:
        tmax0_f = None

    # Blend today's commentary temp and rain chance with extra sources (silent fail)
    met_today = _get_metno_daily(LAT, LON)
    gfs_today = _get_openmeteo_daily_model(LAT, LON, model="gfs")
    blended_tmax0 = _blend_vals([tmax0_f, met_today.get("tmax"), gfs_today.get("tmax")], mode="median")
    blended_prob0 = _blend_vals([prob0,  met_today.get("pop"),  gfs_today.get("pop")],  mode="max")

    lines.append(_kv("Outlook", _commentary(blended_tmax0 if blended_tmax0 is not None else tmax0_f, code0)))
    lines.append(_kv("⚡ Solar", _solar_compact_label(rad0, cloud0)[2:]))
    if isinstance(blended_prob0, (int, float)) and blended_prob0 > 0:
        label = "☔ Chance of rain" if blended_prob0 < 60 else "⚠️ High chance of rain"
        lines.append(_kv(label, f"{int(round(blended_prob0))}%"))
    elif isinstance(prob0, (int, float)) and prob0 > 0:
        label = "☔ Chance of rain" if prob0 < 60 else "⚠️ High chance of rain"
        lines.append(_kv(label, f"{prob0}%"))
    if code0 in (95,96,99):
        lines.append("⚠️ Severe storm risk — hail possible.")

    # Optional: also trigger alerts from forecast view (idempotent via cache)
    heavy_rain0 = isinstance(blended_prob0, (int, float)) and blended_prob0 >= 70
    thunder0 = code0 in (95, 96, 99)
    hail0 = code0 in (96, 99)
    if thunder0:
        _notify_once_daily("thunder", f"⛈ Thunderstorm risk — {CITY}",
                           "Thunderstorms forecast for today. High priority.")
    elif hail0:
        _notify_once_daily("hail", f"🧊 Hail risk — {CITY}",
                           "Hail possible today. Move vehicles under cover.")
    elif heavy_rain0:
        _notify_once_daily("heavy_rain", f"🌧 Heavy rain risk — {CITY}",
                           f"High chance of rain today ({int(blended_prob0)}%). Watch for flooding.")

    # 7-day list (solar: HIGH/MED/LOW; hide rain% if 0)
    lines.append("")
    lines.append(f"📅 7-Day Outlook — {CITY}")
    for i in range(0, min(7, len(times))):
        date = times[i]
        tmin = tmins[i] if i < len(tmins) else "?"
        tmax = tmaxs[i] if i < len(tmaxs) else "?"
        code = codes[i] if i < len(codes) else -1
        icon = _icon_for_code(code, big=False)
        cloud = clouds[i] if i < len(clouds) else None
        rad = rads[i] if i < len(rads) else None
        prob = probs[i] if i < len(probs) else None

        # For "today" line, keep using blended probability; other days leave as Open-Meteo
        if i == 0 and isinstance(blended_prob0, (int, float)):
            prob = blended_prob0

        solar_str = _solar_compact_label(rad, cloud)[2:]
        rain_str = f" · ☔ {int(round(prob))}%" if isinstance(prob, (int, float)) and prob > 0 else ""
        prefix = "• Today" if i == 0 else f"• {date}"

        lines.append(f"{prefix} — {tmin}°C to {tmax}°C {icon}  ·  ⚡ {solar_str}{rain_str}")
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
    if any(w in cmd for w in ["weather","temperature","temp","now","today"]):
        return current_weather()
    if "solar" in cmd:
        return forecast_weather()
    return "⚠️ Unknown weather command", None



