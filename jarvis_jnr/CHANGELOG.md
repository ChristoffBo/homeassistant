## latest (2025-08-25 10:30:00)
- Personality module added: optional chat mode with random jokes, quips, weird facts
- Supports configurable quiet hours, min interval, daily max
- Local stash (~100 lines) + multiple free APIs (JokeAPI, DadJoke, Chuck Norris, Geek Jokes, Quotable, Numbers, Useless Facts, etc.)
- Personality moods supported: playful, sarcastic, serious, sci-fi, hacker-noir
- New options in options.json: personality_enabled, personality_quiet_hours, personality_min_interval_minutes, personality_daily_max, personality_local_ratio, personality_api_ratio, personality_family_friendly, personality_mood, chat_enabled

## 2025-08-24 14:20:00
Alpha release of Jarvis Jnr Home Assistant add-on
- Core Gotify integration: connects with client token, listens via WebSocket, posts back with app token
- Beautifier added: formats Radarr, Sonarr, Watchtower, Semaphore, JSON, YAML, and generic messages into styled cards
- Retention system: deletes old Jarvis messages after retention_hours
- Quiet hours framework added (configurable, not yet strict enforced)
- Weather module (Open-Meteo, coordinate based) implemented: supports commands weather, forecast, temp, temperature, today, now
- Radarr module: supports movie count, reacts to Radarr events with poster and metadata
- Sonarr module: supports series count, upcoming episodes, longest series, reacts to Sonarr events with poster and metadata
- System help matrix available with command help or commands
- Modular design: optional modules load dynamically from /app, toggled via options.json
- options.json configuration fully exposed: bot_name, bot_icon, gotify_url, gotify_client_token, gotify_app_token, jarvis_app_name, retention_hours, beautify_enabled, commands_enabled, quiet_hours_enabled, quiet_hours, weather_enabled, weather_lat, weather_lon, weather_city, weather_time, digest_enabled, digest_time, radarr_enabled, radarr_url, radarr_api_key, radarr_time, sonarr_enabled, sonarr_url, sonarr_api_key, sonarr_time
- Startup summary message shows active modules and bot status
- First-run success tested: add-on starts, connects to Gotify, beautifies, executes wake-word commands