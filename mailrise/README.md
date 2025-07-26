# 📧 Mailrise Home Assistant Add-on

This Home Assistant add-on runs Mailrise — a bridge that turns email (SMTP) into rich push notifications using Apprise.

🔗 Docker image used: [yoryan/mailrise](https://hub.docker.com/r/yoryan/mailrise)

---

## ✅ Features

- Sends notifications via email (SMTP)
- Works with Apprise-compatible services (Gotify, Discord, Telegram, etc.)
- Easily configured through Home Assistant UI

---

## 🛠️ Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
2. Click **⋮ → Repositories**
3. Add:
4. Search for **Mailrise** and install it

---

## ⚙️ Configuration Example

In the add-on **Configuration tab**:

```ini
[email]
port = 8025

[profile:gotify]
urls = gotify://192.168.1.100/ABC123
