# 🧩 Uptime Kuma

Self-hosted monitoring add-on powered by the official louislam/uptime-kuma image. Provides modern dashboards, multiple check types, rich alerting, SSL monitoring, and Home Assistant integration — all with a beautiful dark-mode UI.

✅ Features  
• Monitor HTTP(S), TCP, Ping, DNS, keywords, Push, Steam game servers  
• Fast, reactive web UI with dark/light themes and graphs  
• SSL certificate monitoring with expiry alerts  
• Multiple status pages with custom domains  
• Notifications via Email (SMTP), Telegram, Discord, Slack, Pushover, and more  
• Short monitoring intervals (as low as 20 seconds)  
• Proxy support, 2FA, multi-language UI  
• Works with Home Assistant’s native Uptime Kuma integration  

📁 Key paths  
• /config/uptime-kuma — persistent data (SQLite DB and configuration)  

⚙️ Configuration (flat JSON example)  
{"port":3001,"data_dir":"/config/uptime-kuma"}  

🧪 Options  
• port — host port for direct access (default: 3001; configurable in Add-on Network panel)  
• data_dir — data directory inside the container (default: /config/uptime-kuma; avoid remote/NFS paths without proper locking)  

🌍 Web UI  
• Ingress via Home Assistant sidebar  
• Direct access at http://[HOME_ASSISTANT_HOST]:[PORT]  
• First-run wizard prompts you to create an admin account  

🧠 Notes  
• Uses official image: louislam/uptime-kuma  
• Data is persisted under /config/uptime-kuma via the DATA_DIR env variable  
• Restart the add-on if you change the port  
• For Home Assistant integration: Settings → Devices & Services → Add “Uptime Kuma”