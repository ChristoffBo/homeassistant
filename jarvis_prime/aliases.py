"""
Central alias registry for Jarvis Prime command normalization.
Drop this file as /app/aliases.py (same folder as bot.py).
You can add/modify aliases here without touching bot.py.
"""

# Exact phrase → intent (bot makes everything case-insensitive)
EXACT = {
    # DNS / Technitium
    "dns": "dns",
    "dns status": "dns",
    "dns stats": "dns",
    "technitium": "dns",
    "tech dns": "dns",
    "tdns": "dns",

    # Uptime Kuma
    "kuma": "kuma",
    "uptime": "kuma",
    "uptime kuma": "kuma",
    "status": "kuma",
    "monitors": "kuma",
    "monitor status": "kuma",

    # Weather
    "weather": "weather",
    "temp": "weather",
    "temps": "weather",
    "temperature": "weather",
    "now": "weather",
    "today": "weather",
    "current": "weather",
    "forecast": "forecast",
    "weekly": "forecast",
    "7day": "forecast",
    "7-day": "forecast",

    # Fun
    "joke": "joke",
    "pun": "joke",
}
