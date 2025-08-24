Jarvis Jnr is a Home Assistant add-on that connects to your Gotify server, watches incoming messages, beautifies them, reposts the formatted version, and can execute simple commands (wake-word style). It also enforces message retention and supports optional modules (Weather, Radarr, Sonarr). This is an alpha build. Features and modules may change in future versions.

✅ Features
Beautifies messages (delete + repost formatted)

Radarr events → poster, title, year, runtime, quality, size

Sonarr events → poster, SxxEyy, title, runtime, quality, size

Watchtower & Semaphore payloads → labeled cards

Generic JSON/YAML payloads → parsed tables

Everything else → neat “General Message” card

Retention cleanup

Keeps Jarvis messages for retention_hours, then purges them

Clears older/non-Jarvis messages to keep the board tidy

Wake-word commands

Wake word is Jarvis (case-insensitive)

Send a Gotify notification with Title: Jarvis and Message: your command

Supported commands:
• Weather module (Open-Meteo, no API key): weather, forecast, temp, temperature
• Radarr: movie count
• Sonarr: series count, upcoming series, longest series
• System: help or commands shows the command matrix

Optional Quiet Hours (config flags exist)

Modules may be expanded in future builds.

📁 Files
/data/options.json — add-on settings
/app/bot.py — main bot
/app/arr.py — Radarr and Sonarr integration
/app/weather.py — Weather module (Open-Meteo)
/app/*.py — optional modules auto-loaded when enabled

⚙️ Configuration (/data/options.json)
{
"bot_name": "Jarvis Jnr",
"bot_icon": "🤖",
"gotify_url": "http://YOUR_GOTIFY_HOST:8091",
"gotify_client_token": "CLIENT_TOKEN_FOR_STREAMING",
"gotify_app_token": "APP_TOKEN_FOR_POSTING",
"jarvis_app_name": "Jarvis",
"retention_hours": 24,
"beautify_enabled": true,
"commands_enabled": true,
"quiet_hours_enabled": true,
"quiet_hours": "22:00-06:00",
"weather_enabled": true,
"weather_lat": -26.2041,
"weather_lon": 28.0473,
"weather_city": "Your City",
"weather_time": "07:00",
"digest_enabled": true,
"digest_time": "08:00",
"radarr_enabled": true,
"radarr_url": "http://RADARR_HOST:7878",
"radarr_api_key": "YOUR_RADARR_API_KEY",
"radarr_time": "07:30",
"sonarr_enabled": true,
"sonarr_url": "http://SONARR_HOST:8989",
"sonarr_api_key": "YOUR_SONARR_API_KEY",
"sonarr_time": "07:30"
}

🧪 Options
bot_name — bot display name
bot_icon — emoji or text shown in notifications
gotify_url — base URL of Gotify server
gotify_client_token — client token used to listen to Gotify’s WebSocket stream
gotify_app_token — app token used by Jarvis to post replies
jarvis_app_name — Gotify app name to prevent Jarvis looping on its own messages
retention_hours — how long Jarvis messages are kept before purge
beautify_enabled — enable or disable beautification
commands_enabled — enable or disable wake-word command handling
quiet_hours_enabled — enable or disable quiet hours
quiet_hours — timeframe when Jarvis will stay silent
weather_enabled — enable or disable weather module
weather_lat — latitude used for weather lookup
weather_lon — longitude used for weather lookup
weather_city — label shown in weather cards (cosmetic only)
weather_time — reserved for scheduled reports
digest_enabled — toggle digest module (future use)
digest_time — reserved for digest scheduling
radarr_enabled — enable or disable Radarr module
radarr_url — Radarr base URL
radarr_api_key — Radarr API key
radarr_time — reserved for scheduled Radarr reports
sonarr_enabled — enable or disable Sonarr module
sonarr_url — Sonarr base URL
sonarr_api_key — Sonarr API key
sonarr_time — reserved for scheduled Sonarr reports

🌍 Usage

Create in Gotify: a Client token (for listening) and an App token (for Jarvis to post).

Configure /data/options.json with both tokens and your preferences.

Start the add-on in Home Assistant.

Send a Gotify message: Title: Jarvis, Message: your command.
Jarvis will reply back into the Jarvis app feed with a formatted card.

🧠 Notes
This is an alpha build. Modules and configuration may change. Keep your tokens, URLs, and API keys private.
