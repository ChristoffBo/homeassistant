

# 🧩 MeTube Home Assistant Add-on

Self-hosted web GUI for downloading videos from YouTube and many other platforms using yt-dlp.

✅ Uses the official Docker image: alexta69/metube  
✅ Works offline once started  
✅ Full Web UI on configurable port  
✅ Persistent storage enabled  
✅ All settings exposed in options.json  
✅ No build needed

📁 Files:  
- /data/options.json — stores add-on settings  
- /share/metube — output directory for downloaded media  
- /config — persistent volume (if needed)

⚙️ Configuration:  
{ "port": 8081 }

🧪 Options:  
  port — sets the MeTube web interface port (default: 8081)

🌍 Web UI access:  
Accessible via Home Assistant Ingress or at `http://<your-ip>:<port>` (e.g., `http://192.168.1.10:8081`)

🧠 Fully self-hosted. No external account required.