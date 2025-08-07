# 🧩 Apprise Home Assistant Add-on

Self-hosted notification gateway powered by Apprise. Works fully offline and supports over 50+ notification services including Telegram, Discord, Gotify, email, and more.

✅ Features: Sends notifications to multiple services from one API. Based on official apprise-api Docker backend. Web UI available via Ingress or direct port. CLI arguments can be passed via config. Auto-start on Home Assistant boot.

📁 Files: /data/options.json - Configuration file. /etc/cont-init.d/run.sh - Entrypoint script. /web - Reserved for future static assets.

⚙️ Configuration Example:
{
  "port": 8000,
  "cli_args": ""
}

🧪 Optional Fields:
port — default is 8000  
cli_args — additional arguments for apprise-api  

🚀 How it Works:  
1. Starts container  
2. Runs apprise-api on configured port  
3. Accepts notification POSTs via REST API  
4. Exposes web UI at /web (Ingress compatible)  

✅ Works with:  
Telegram, Gotify, Discord, Matrix, Email (SMTP), Webhooks, Slack, and more  

🔁 Add-on runs continuously. Restart required if options change.

✅ Built from: caronc/apprise-api  
No external accounts required. Self-hosted.  
Runs entirely inside Home Assistant environment.
