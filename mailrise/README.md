# 🧩 Mailrise — Home Assistant Add-on

Run Mailrise inside Home Assistant to bridge email (SMTP) into rich push notifications using Apprise. Accepts plain emails and delivers them to Gotify, Discord, Telegram, Slack, ntfy, Pushover, and many more services.

✅ Uses the official Docker image: yoryan/mailrise  
✅ Converts SMTP email into Apprise push notifications  
✅ Supports multiple Apprise profiles  
✅ Persistent configuration across restarts  
✅ All settings exposed in options.json  
✅ Fully self-hosted — no external account required  

📁 Files:  
/data/options.json — stores add-on settings  
/config — persistent Mailrise data  

⚙️ Configuration: {"port": 8025, "profiles": {"gotify": "gotify://192.168.1.100/ABC123"}}  

🧪 Options:  
port — SMTP port Mailrise listens on (default: 8025)  
profiles — Apprise notification profiles with service URLs  

🌍 Web UI access:  
No UI — Mailrise runs headless. Configure via options.json.  
Send email to Mailrise SMTP port, it will forward to configured Apprise profiles.  

🧠 Fully self-hosted. Works with any service that can send email.  

🧾 Logs will show incoming SMTP connections and Apprise forwards.