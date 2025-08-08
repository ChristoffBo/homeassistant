# 🧩 ZTNCUI Home Assistant Add-on

Self-hosted ZeroTier controller with built-in web UI (ZTNCUI). Allows full network management from a secure HTTPS dashboard.

✅ Uses the official Docker image: keynetworks/ztncui-containerized  
✅ Built-in HTTPS Web UI on port 3443  
✅ ZeroTier controller and UI in one container  
✅ Supports persistent identity and config  
✅ Fully self-hosted, no cloud or account required  
✅ All settings configurable in options.json  

📁 Files:
- /data/options.json — stores add-on settings
- /config/ztncui — persistent ZeroTier identity and network config

⚙️ Configuration:
{
  "admin_user": "admin",
  "admin_password": "changeme123",
  "port": 3443,
  "zt_home": "/config/ztncui",
  "hostname": "localhost",
  "email": "admin@example.com",
  "controller_network_id": ""
}

🧪 Options:
  admin_user — sets the web UI login username  
  admin_password — sets the login password  
  port — HTTPS web UI port (default 3443)  
  zt_home — persistent data path (must be inside /config)  
  hostname — used for links inside the UI  
  email — admin contact email (UI display)  
  controller_network_id — optional default network focus  

🌍 Web UI Access:
Access the interface at: https://[YOUR_HA_IP]:3443  
Login using the username and password from options.json.  
You will be prompted to change the default password on first login.  

🧠 Fully self-hosted. No ZeroTier account or cloud required. Runs independently with full control over your virtual networks.