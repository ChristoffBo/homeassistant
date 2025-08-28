
import json, yaml, requests, random
from datetime import datetime, timezone

# =============================
# Config
# =============================
def _load_options():
    try:
        with open("/data/options.json", "r") as f:
            text = f.read()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return yaml.safe_load(text)
    except Exception as e:
        print(f"[Weather] ⚠️ Could not load options.json: {e}")
        return {}

_opts = _load_options()
ENABLED   = bool(_opts.get("weather_enabled", _opts.get("weather", True)))
LAT       = float(_opts.get("weather_lat",  _opts.get("lat",  -26.2041)))
LON       = float(_opts.get("weather_lon",  _opts.get("lon",   28.0473)))
TIMEZONE  = _opts.get("weather_timezone",   _opts.get("timezone", "Africa/Johannesburg"))
UNITS     = (_opts.get("weather_units") or "metric").lower()  # metric|imperial

# =============================
# Helpers
# =============================
def _icon_for_code(code: int, big: bool = False) -> str:
    # https://open-meteo.com/en/docs#weathervariables - weathercode mapping
    table = {
        0: "☀️" if big else "☀",
        1: "🌤" if big else "🌤",
        2: "⛅" if big else "⛅",
        3: "☁️" if big else "☁",
        45: "🌫" if big else "🌫",
        48: "🌫" if big else "🌫",
        51: "🌦" if big else "🌦",
        53: "🌦" if big else "🌦",
        55: "🌧" if big else "🌧",
        56: "🌧" if big else "🌧",
        57: "🌧" if big else "🌧",
        61: "🌦" if big else "🌦",
        63: "🌧" if big else "🌧",
        65: "🌧" if big else "🌧",
        66: "🌧" if big else "🌧",
        67: "🌧" if big else "🌧",
        71: "🌨" if big else "🌨",
        73: "🌨" if big else "🌨",
        75: "❄️" if big else "❄",
        77: "❄️" if big else "❄",
        80: "🌧" if big else "🌧",
        81: "🌧" if big else "🌧",
        82: "🌧" if big else "🌧",
        85: "🌨" if big else "🌨",
        86: "❄️" if big else "❄",
        95: "⛈️" if big else "⛈",
        96: "⛈️" if big else "⛈",
        99: "⛈️" if big else "⛈",
    }
    return table.get(int(code or 0), "⛅")

def _unit_temp(v: float) -> str:
    if UNITS == "imperial":
        return f"{round(v * 9/5 + 32)}°F"
    return f"{round(v)}°C"

# =============================
# API calls (Open‑Meteo – free, no key)
# =============================
def _get_current():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m"
        f"&timezone={TIMEZONE}"
    )
    r = requests.get(url, timeout=8)
    r.raise_for_status()
    return r.json()

def _get_daily(days: int = 7):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum"
        f"&forecast_days={days}&timezone={TIMEZONE}"
    )
    r = requests.get(url, timeout=8)
    r.raise_for_status()
    return r.json()

# =============================
# Renderers
# =============================
def current_weather():
    if not ENABLED:
        return "⚠️ Weather is disabled.", None
    try:
        j = _get_current()
        cur = j.get("current", {})
        t  = cur.get("temperature_2m")
        ta = cur.get("apparent_temperature")
        rh = cur.get("relative_humidity_2m")
        w  = cur.get("wind_speed_10m")
        wc = cur.get("weather_code")
        icon = _icon_for_code(wc, big=True)
        parts = []
        if t is not None:  parts.append(f"{icon} {_unit_temp(t)}")
        if ta is not None: parts.append(f"feels {_unit_temp(ta)}")
        if rh is not None: parts.append(f"💧{int(rh)}%")
        if w is not None:  parts.append(f"💨 {round(float(w),1)} m/s")
        return " ".join(parts) or "No current data", None
    except Exception as e:
        return f"⚠️ Weather failed: {e}", None

def forecast_weather(days: int = 7):
    if not ENABLED:
        return "⚠️ Weather is disabled.", None
    try:
        j = _get_daily(days=days)
        d = j.get("daily", {})
        dates = d.get("time", []) or []
        tmin  = d.get("temperature_2m_min", []) or []
        tmax  = d.get("temperature_2m_max", []) or []
        code  = d.get("weather_code", []) or []
        out = []
        out.append("📅 7‑Day Forecast")
        for i in range(min(days, len(dates))):
            dt = dates[i]
            icon = _icon_for_code((code[i] if i < len(code) else 0) or 0)
            lo = _unit_temp(tmin[i] if i < len(tmin) else 0)
            hi = _unit_temp(tmax[i] if i < len(tmax) else 0)
            out.append(f"• {dt}: {lo} → {hi} {icon}")
        return "\n".join(out), None
    except Exception as e:
        return f"⚠️ Forecast failed: {e}", None

# =============================
# Command entry
# =============================
def handle_weather_command(command: str, *_):
    c = (command or '').strip().lower()
    if any(k in c for k in ("forecast", "week", "7", "seven")):
        return forecast_weather()
    if any(k in c for k in ("weather", "temp", "today", "now")) or c == "":
        return current_weather()
    return "⚠️ Unknown weather command", None
