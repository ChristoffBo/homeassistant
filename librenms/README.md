# 🧩 LibreNMS

✅ Self-hosted network monitoring with alerts and maps  
✅ Uses official LinuxServer Docker image  
✅ Works with Home Assistant add-on updater  
✅ Ingress WebUI support  

📁 Data is stored under /config/librenms for persistence.  

⚙️ Configuration example:
{
  "PUID": 1000,
  "PGID": 1000,
  "TZ": "Africa/Johannesburg",
  "DB_PASS": "librenms"
}

🧪 Options:
- PUID / PGID → file permissions
- TZ → timezone
- DB_PASS → database password

🌍 Access:
- Ingress panel inside HA
- Or direct: http://homeassistant:8000

🧠 LibreNMS is a single pane of glass for your network, with discovery, maps, alerts, and long-term graphs.