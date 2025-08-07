# 🧩 Apprise Home Assistant Add-on

Self-hosted notification gateway powered by Apprise. Supports over 50+ services like Telegram, Discord, Gotify, Slack, Email, Webhooks, and more.

✅ Uses the official Docker image: caronc/apprise  
✅ Works offline once started  
✅ Full REST API and Web UI on port 8000  
✅ Ingress compatible  
✅ Persistent storage enabled  
✅ All settings exposed in options.json  
✅ No build needed

📁 Files:
- /data/options.json — stores add-on settings
- /web — reserved for future static files (optional)

⚙️ Configuration:
{
  "port": 8000,
  "cli_args": "",
  "image_override": "caronc/apprise"
}

🧪 Options:
port — sets web API/UI port  
cli_args — any extra flags for apprise-api  
image_override — lets you specify alternate Docker image (default is caronc/apprise)

🔁 The add-on runs continuously.  
📤 The REST API and Web UI are available via Home Assistant Ingress or on the configured port.

🧠 Fully self-hosted. No external account required.  
