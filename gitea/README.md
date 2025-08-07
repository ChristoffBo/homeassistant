# 🧩 Gitea Home Assistant Add-on
Self-hosted lightweight Git server powered by Gitea. Manage repositories, issues, teams, and more in a sleek web interface.

✅ Uses the official Docker image: gitea/gitea
✅ Full web-based Git interface
✅ Built-in user, team, and org management
✅ Persistent storage enabled
✅ All settings exposed in options.json
✅ No build needed

📁 Files:
- /data/options.json — stores add-on settings
- /ssl — where certfile and keyfile must be stored

⚙️ Configuration: { "ssl": false, "certfile": "fullchain.pem", "keyfile": "privkey.pem", "APP_NAME": "", "DOMAIN": "homeassistant.local", "ROOT_URL": "" }

🧪 Options:
ssl — enables HTTPS if true  
certfile — SSL certificate (must exist in /ssl)  
keyfile — SSL private key (must exist in /ssl)  
APP_NAME — sets a custom name for the instance  
DOMAIN — sets the accessible domain name  
ROOT_URL — optional full URL override for advanced use

🌍 The Web UI is available via Home Assistant Ingress or at http://<your-ip>:<port> (or HTTPS if enabled).

🧠 Fully self-hosted. No external GitHub or GitLab account required.