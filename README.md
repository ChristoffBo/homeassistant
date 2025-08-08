# 🧩 Home Assistant Add-ons Repository by ChristoffBo

A curated collection of custom Home Assistant add-ons designed to extend your setup with powerful tools, dashboards, proxies, and automation utilities.

✅ All add-ons run official or hardened Docker images  
✅ Flat config with full `options.json` support  
✅ Persistent storage and port mapping on every add-on  
✅ Supports Docker Hub, lscr.io, and GHCR registries  
✅ Includes scripts to automate update checks and changelogs  

📁 Contents:  
- Fully working add-ons like:  
  - Gotify — Push notifications server  
  - Heimdall — App dashboard UI  
  - Mailrise — Mail-to-notification bridge  
  - Technitium DNS — DNS server with GUI + ingress  
  - Update Checker — Auto Docker tag puller + changelog  
- Automation scripts and update helpers  
- All add-ons include full UI, readme, and icon/logo assets  

⚙️ Installation:  
1. Go to Home Assistant ➜ Settings ➜ Add-ons ➜ Add-on Store  
2. Click "Repositories"  
3. Add: https://github.com/ChristoffBo/homeassistant  
4. All add-ons will now appear for installation  

🧪 Features:  
- Automatic update script (run.sh) checks tags and pushes commits  
- Full GitHub and Gitea support  
- Notification integration via Gotify, Apprise, Mailrise  
- Color-coded logs with full status indicators  
- Works offline after first setup (for self-hosted stacks)  

🧠 Configuration:  
Each add-on uses a flat `options.json` file for all settings  
All ports, tokens, and CLI args are configurable per add-on  

📦 Supported Docker Registries:  
- Docker Hub (default)  
- lscr.io (LinuxServer.io)  
- ghcr.io (GitHub Container Registry)  

🔐 Security:  
- Add-ons are sandboxed using HA container framework  
- Secure token storage via Supervisor options  
- No external tracking or cloud dependencies  

📄 License:  
MIT License — © 2026 Christoff Bothma  
https://github.com/ChristoffBo/homeassistant/blob/main/LICENSE  

🚫 No support is provided. Use as-is. Issues, pull requests, and help are not guaranteed to be addressed.