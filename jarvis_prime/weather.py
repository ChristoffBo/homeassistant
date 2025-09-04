import json, yaml, requests, random
from datetime import datetime, timezone
# No tabulate: sleek AI-style aligned output (no tables)

# -----------------------------
# Load config from /data/options.json
# -----------------------------
try:
    with open("/data/options.json", "r") as f:
        text = f.read()
        try:
            options = json.loads(text)        # try JSON first
        except json.JSONDecodeError:
            options = yaml.safe_load(text)    # fallback to YAML

        ENABLED = options.get("weather_enabled", False)
        LAT = options.get("weather_lat", -26.2041)
        LON = options.get("weather_lon", 28.0473)
        CITY = options.get("weather_city", "Unknown")
except Exception as e:
    print(f"[Weather] ⚠️ Could not load options.json: {e}")
    ENABLED, LAT, LON, CITY = False, -26.2041, 28.0473, "Unknown"

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

    # Sleek aligned block
    lines = []
    lines.append(f"{icon_big} Current Weather — {CITY}")
    lines.append(_kv("🌡 Temperature", f"{temp}°C"))
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

    lines = []
    lines.append(f"{icon0_big} Today — {CITY}")
    lines.append(_kv("Range", f"{tmin0}°C – {tmax0}°C"))
    lines.append(_kv("Outlook", _commentary(tmax0 if isinstance(tmax0, (int, float)) else 0, code0)))

    # Next days
    lines.append("")
    lines.append(f"📅 7-Day Outlook — {CITY}")
    for i in range(0, min(7, len(times))):
        date = times[i]
        tmin = tmins[i] if i < len(tmins) else "?"
        tmax = tmaxs[i] if i < len(tmaxs) else "?"
        code = codes[i] if i < len(codes) else -1
        icon = _icon_for_code(code, big=False)
        # Use bullet, no tabulation
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
