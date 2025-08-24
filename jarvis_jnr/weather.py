import json, requests, datetime
from tabulate import tabulate

# -----------------------------
# Load config from /data/options.json
# -----------------------------
try:
    with open("/data/options.json", "r") as f:
        options = json.load(f)
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
        0: "☀️" if big else "☀",  # clear
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
    if temp_max >= 30:
        return "🔥 It’s going to be very hot today — stay cool and hydrated!"
    elif temp_max <= 10:
        return "❄️ Cold day ahead — wear something warm!"
    elif code in [61,63,65,80,81,82,95,96,99]:
        return "🌧 Don’t forget your umbrella, rain is expected."
    elif code in [71,73,75,85,86]:
        return "❄️ Snow is coming — watch your step!"
    else:
        return "🌤 Looks like a pleasant day ahead."

# -----------------------------
# Current Weather
# -----------------------------
def current_weather():
    if not ENABLED:
        return "⚠️ Weather module not enabled", None
    url = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&current_weather=true"
    data = _get_json(url)
    if "error" in data:
        return f"⚠️ Weather API error: {data['error']}", None
    cw = data.get("current_weather", {})
    temp = cw.get("temperature")
    wind = cw.get("windspeed")
    code = cw.get("weathercode")
    desc = _icon_for_code(code, big=True)
    return f"{desc} Current Weather in {CITY}\n🌡 {temp}°C | 🌬 {wind} km/h", None

# -----------------------------
# Forecast (7 days with today highlighted)
# -----------------------------
def forecast_weather():
    if not ENABLED:
        return "⚠️ Weather module not enabled", None
    url = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&daily=temperature_2m_max,temperature_2m_min,weathercode&timezone=auto"
    data = _get_json(url)
    if "error" in data:
        return f"⚠️ Weather API error: {data['error']}", None
    daily = data.get("daily", {})
    rows = []
    today_text = ""
    for i in range(min(7, len(daily.get("time", [])))):
        date = daily["time"][i]
        tmin = daily["temperature_2m_min"][i]
        tmax = daily["temperature_2m_max"][i]
        code = daily["weathercode"][i]
        icon = _icon_for_code(code)
        desc = _icon_for_code(code, big=True)

        if i == 0:  # Today highlight
            today_text = f"{desc} Today in {CITY}\n🌡 {tmin}°C - {tmax}°C\n{_commentary(tmax, code)}"
        else:
            rows.append([date, f"{tmin}°C", f"{tmax}°C", icon])

    table = tabulate(rows, headers=["Date","Min","Max","Condition"], tablefmt="github")
    return f"{today_text}\n\n📅 7-Day Forecast for {CITY}\n{table}", None

# -----------------------------
# Command Router
# -----------------------------
def handle_weather_command(command: str):
    cmd = command.lower().strip()
    if "forecast" in cmd:
        return forecast_weather()
    return current_weather()
