

# 🧩 Heimdall Home Assistant Add-on

Self-hosted application dashboard and web bookmark manager with a sleek interface.

✅ Uses the official Docker image: linuxserver/heimdall  
✅ Works offline once started  
✅ Full Web UI on configurable port  
✅ Persistent storage enabled  
✅ All settings exposed in options.json  
✅ No build needed

📁 Files:  
- /data/options.json — stores add-on settings  
- /config — persistent volume for Heimdall data

⚙️ Configuration:  
{ "port": 82 }

🧪 Options:  
  port — sets the Heimdall web interface port (default: 82)

🌍 Web UI access:  
Accessible at `http://<your-ip>:<port>` (e.g., `http://192.168.1.10:82`)

🧠 Fully self-hosted. No external account required.