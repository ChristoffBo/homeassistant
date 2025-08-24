import os, json, requests, datetime
from tabulate import tabulate

# -----------------------------
# Config
# -----------------------------
try:
    with open("/data/options.json", "r") as f:
        options = json.load(f)
        LAT = options.get("weather_lat", -26.2041)
        LON = options.get("weather_lon", 28.0473)
        CITY = options.get("weather_city", "Johannesburg")
except Exception as e:
    print(f"[Weather] ⚠️ Could not load options.json: {e}")
    LAT, LON, CITY = -26.2041, 28.0473, "Johannesburg"

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

def _icon_for_code(code):
    # Open-Meteo weathercode meanings
    mapping = {
        0: "☀️ Clear sky",
        1: "🌤 Mainly clear",
        2: "⛅ Partly cloudy",
        3: "☁️ Overcast",
        45: "🌫 Fog",
        48: "🌫 Depositing rime fog",
        51: "🌦 Light drizzle",
        53: "🌦 Moderate drizzle",
        55: "🌧 Heavy drizzle",
        61: "🌦 Light rain",
        63: "🌧 Moderate rain",
        65: "⛈ Heavy rain",
        71: "❄️ Light snow fall",
        73: "❄️ Moderate snow fall",
        75: "❄️ Heavy snow fall",
        77: "🌨 Snow grains",
        80: "🌦 Rain showers",
        81: "🌧 Rain showers",
        82: "⛈ Violent rain showers",
        85: "❄️ Snow showers",
        86: "❄️ Heavy snow showers",
        95: "⛈ Thunderstorm",
        96: "⛈ Thunderstorm with hail",
        99: "⛈ Severe thunderstorm with hail"
    }
    return mapping.get(code, f"🌍 Code {code}")

# -----------------------------
# Current Weather
# -----------------------------
def current_weather():
    url = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&current_weather=true"
    data = _get_json(url)
    if "error" in data:
        return f"⚠️ Weather API error: {data['error']}", None
    cw = data.get("current_weather", {})
    temp = cw.get("temperature")
    wind = cw.get("windspeed")
    code = cw.get("weathercode")
    desc = _icon_for_code(code)
    return f"🌦 Current Weather in {CITY}\n{desc}\n🌡 {temp}°C | 🌬 {wind} km/h", None

# -----------------------------
# Forecast (next 5 days daily)
# -----------------------------
def forecast_weather():
    url = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&daily=temperature_2m_max,temperature_2m_min,weathercode&timezone=auto"
    data = _get_json(url)
    if "error" in data:
        return f"⚠️ Weather API error: {data['error']}", None
    daily = data.get("daily", {})
    rows = []
    for i in range(min(5, len(daily.get("time", [])))):
        date = daily["time"][i]
        tmin = daily["temperature_2m_min"][i]
        tmax = daily["temperature_2m_max"][i]
        code = daily["weathercode"][i]
        desc = _icon_for_code(code)
        rows.append([date, f"{tmin}°C", f"{tmax}°C", desc])
    table = tabulate(rows, headers=["Date","Min","Max","Condition"], tablefmt="github")
    return f"📅 5-Day Forecast for {CITY}\n{table}", None

# -----------------------------
# Command Router
# -----------------------------
def handle_weather_command(command: str):
    cmd = command.lower().strip()
    if "forecast" in cmd:
        return forecast_weather()
    return current_weather()
