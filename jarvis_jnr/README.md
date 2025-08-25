# 🧩 Jarvis Jnr — Home Assistant Add-on
This add-on runs a smart notification bot inside Home Assistant that connects to your **Gotify** server. Jarvis Jnr watches incoming messages, beautifies them into clean cards, reposts them, and can execute simple wake-word commands. It also enforces retention rules, supports integrations like **Radarr, Sonarr, Weather**, and includes a **toggleable Chat Personality** that posts random jokes, quips, or weird facts at controlled intervals.

## What it is and what it is used for
**Jarvis Jnr** is a Gotify-aware assistant. It listens to notifications in real time and can:
- Beautify Radarr/Sonarr events into rich cards with posters, runtime, quality, etc.
- Format JSON, YAML, Watchtower, and Semaphore payloads.
- Auto-clean up Gotify feeds based on retention.
- Respond to wake-word commands like `Jarvis help`, `Jarvis weather`, or `Jarvis series count`.
- Optionally run in **personality mode**, dropping random jokes, puns, weird facts, or API-fetched quips to make the bot feel alive.

Running Jarvis Jnr in **Home Assistant** makes sense if you already use Gotify for notifications. It centralizes formatting, command handling, and adds personality to your notifications.

## Features
- Beautifies incoming Gotify messages into clean cards.
- Radarr event parsing → Poster, title, year, runtime, quality, size.
- Sonarr event parsing → Poster, SxxEyy, title, runtime, quality, size.
- Watchtower & Semaphore payloads → Labeled update reports.
- JSON/YAML payloads → Parsed tables.
- General messages → Generic card.
- Retention cleanup → Purges Jarvis or non-Jarvis messages after configured hours.
- Wake-word commands → Weather, Radarr, Sonarr, System help.
- **Chat Personality** → Optional “weirdo mode” that posts random jokes, facts, or quotes at safe intervals.

## Paths
- **Config**: `/data/options.json` — add-on settings  
- **Bot core**: `/app/bot.py`  
- **Radarr/Sonarr**: `/app/arr.py`  
- **Weather module**: `/app/weather.py`  
- **Chat Personality**: `/app/chat.py`  
- **Personality state**: `/data/personality_state.json`  

## First-Time Setup (required)
1. On your Gotify server, create:
   - A **Client token** (for listening to WebSocket stream).
   - An **App token** (for Jarvis to post replies).
2. Place both tokens into the add-on’s options.
3. Set URLs for Radarr/Sonarr if you want those modules active.
4. Enable `personality_enabled` if you want the bot to post random jokes/facts.

## Configuration Example
```json
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
  "sonarr_time": "07:30",
  "personality_enabled": true,
  "personality_quiet_hours": "23:00-06:00",
  "personality_min_interval_minutes": 60,
  "personality_daily_max": 24,
  "personality_local_ratio": 60,
  "personality_api_ratio": 40,
  "personality_family_friendly": false,
  "personality_mood": "sarcastic",
  "chat_enabled": true
}