# Jarvis Jnr

Jarvis Jnr is a Gotify Smart Bot Home Assistant add-on. It connects to your Gotify server with a client token, watches for messages, beautifies them, deletes raw versions, enforces retention, and can respond to simple commands.

✅ Features
- Beautify messages (delete + repost formatted)
- Retention cleanup (delete old messages)
- Commands: clean, summarize, stats, last, help
- Optional quiet hours
- Optional weather reports from OpenWeatherMap
- Optional Radarr/Sonarr daily releases

⚙️ Configuration (options.json)
{
  "bot_name": "Jarvis Jnr",
  "bot_icon": "🤖",
  "gotify_url": "http://10.0.0.99:8091",
  "gotify_token": "YOUR_CLIENT_TOKEN",
  "retention_hours": 24,
  "beautify_enabled": true,
  "commands_enabled": true,
  "quiet_hours_enabled": true,
  "quiet_hours": "22:00-06:00",
  "weather_enabled": true,
  "weather_api": "openweathermap",
  "weather_api_key": "",
  "weather_city": "Johannesburg",
  "weather_time": "07:00",
  "digest_enabled": true,
  "digest_time": "08:00",
  "radarr_enabled": false,
  "radarr_url": "",
  "radarr_api_key": "",
  "radarr_time": "07:30",
  "sonarr_enabled": false,
  "sonarr_url": "",
  "sonarr_api_key": "",
  "sonarr_time": "07:30"
}

📌 Setup
1. Create a dedicated Gotify user called jarvis_jnr
2. Create a Gotify App with the same name (Jarvis Jnr) so its messages show separately
3. Go to your Gotify admin user → Clients → Create Client and generate a Client Token
4. Put the Gotify URL and Client Token into options.json
5. Start the add-on in Home Assistant
6. Jarvis Jnr will now beautify and manage your Gotify messages

🧠 Notes
- Requires a Gotify client token (not app token)
- Scheduled features run at configured times
- All extra features (weather, Radarr, Sonarr) can be disabled
