# 🧩 Gotify Home Assistant Add-on

Self-hosted push notification server for sending messages to your devices. Great for scripts, automations, and alerts.

✅ Uses the official Docker image: gotify/server  
✅ Works offline once started  
✅ Full Web UI on configurable port  
✅ Persistent storage enabled  
✅ All settings exposed in options.json  
✅ No build needed

📁 Files:  
- /data/options.json — stores add-on settings  
- /config — persistent volume for Gotify data

⚙️ Configuration:  
{ "port": 8091 }

🧪 Options:  
  port — sets the Gotify web interface port (default: 8091)

🌍 Web UI access:  
Accessible via Home Assistant Ingress or at `http://<your-ip>:<port>` (e.g., `http://192.168.1.10:8091`)

🧠 Fully self-hosted. No external account required.