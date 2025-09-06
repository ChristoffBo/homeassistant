# 🧩 ntfy Server Home Assistant Add-on

Self-hosted ntfy server for publishing and subscribing to notifications.  

✅ Uses the official Docker image: binwiederhier/ntfy  
✅ Full Web UI on configurable port  
✅ Persistent storage enabled (/data)  
✅ All settings exposed in options.json  
✅ No ingress — for browser notifications you must put it behind HTTPS (reverse proxy or self-signed)  

📁 Files:  
- /data/options.json — stores add-on settings  
- /data/cache.db — SQLite cache database  
- /data/attachments — directory for cached attachments  
- /data/user.db — auth database (created if auth enabled)  

⚙️ Configuration:  
{  
  "listen_port": 8008,  
  "base_url": "http://10.0.0.100",  
  "behind_proxy": false,  
  "attachments": {  
    "enabled": true,  
    "dir": "/data/attachments",  
    "file_size_limit": "15M",  
    "total_size_limit": "5G",  
    "expiry": "3h"  
  },  
  "cache": {  
    "file": "/data/cache.db"  
  },  
  "auth": {  
    "enabled": false,  
    "default_access": "read-write",  
    "admin_user": "",  
    "admin_password": ""  
  }  
}  

🧪 Options:  
listen_port — port ntfy listens on inside the container (default: 8008)  
base_url — must be a plain origin (e.g., https://ntfy.example.com if proxied); required for attachments and browser notifications  
behind_proxy — true if you use a reverse proxy that sets X-Forwarded-* headers  
attachments.enabled — enable/disable attachment cache  
attachments.dir — directory where attachments are stored  
attachments.file_size_limit — maximum size per file  
attachments.total_size_limit — total cache size limit  
attachments.expiry — expiry duration for cached files  
cache.file — path to ntfy cache db  
auth.enabled — enable authentication  
auth.default_access — access policy for unauthenticated users  
auth.admin_user — optional admin user created on first boot if a password is set  
auth.admin_password — optional admin password (hashed internally on first boot)  

🌍 Web UI access:  
Accessible at http://<your-ip>:<port> (e.g., http://10.0.0.100:8008). For browser push notifications to work, ntfy must be served over HTTPS — set up a reverse proxy (Zoraxy, NGINX, Traefik, Caddy) and point a domain like https://ntfy.mydomain.com at the add-on.  

🧠 Fully self-hosted. No external account required.
