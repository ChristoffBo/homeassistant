

# Gitea Add-on for Home Assistant

![Gitea Logo](https://gitea.io/images/gitea.png)

One-click installation of a fully self-hosted Git service.

## 🌟 Features
- 100% automated setup
- Persistent storage
- SSH and HTTP access
- Lightweight and fast

## 📥 Installation
1. **Add this repository** to Home Assistant
2. **Install** the "Gitea" add-on
3. **Start** the add-on
4. **Access** via: `http://[YOUR_HA_IP]:3000`

> 💡 Replace `[YOUR_HA_IP]` with your Home Assistant's local IP address (e.g., `http://192.168.1.100:3000`)

## 🔧 First Run Setup
1. Complete the web installer at the URL above
2. Create your **admin account**
3. Configure your first repository

## ⚙️ Default Ports
| Service | Port | Access URL Example |
|---------|------|---------------------|
| Web UI  | 3000 | `http://localhost:3000` |
| SSH     | 2222 | `ssh://git@localhost:2222` |

## 💾 Data Location
All data persists in `/data/gitea` including:
- Git repositories
- User accounts
- Configuration files

## 🔄 Backup Recommendation
```bash
# Backup command example:
ha backups new --name gitea_backup --addons gitea
```

## ❓ Support
For issues, check logs via:
```bash
ha logs gitea
```
