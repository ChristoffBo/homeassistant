# 📧 Mailrise Home Assistant Add-on

This add-on provides [Mailrise](https://github.com/strasharo/mailrise) — an SMTP gateway to send email-based notifications to multiple services using [Apprise](https://github.com/caronc/apprise). It allows integration of simple email-to-notification functionality directly within Home Assistant.

---

## 📦 Features

- Uses the official `strasharo/mailrise` Docker image
- Easily configurable via Home Assistant GUI
- Sends email alerts to Gotify, Discord, Telegram, Pushover, and more
- Lightweight and efficient SMTP-to-Apprise bridge

---

## 🚀 Installation

1. Open **Home Assistant** and go to **Settings → Add-ons → Add-on Store**.
2. Click the **three-dot menu (⋮)** and select **Repositories**.
3. Add the following custom repository:

## ⚙️ Configuration

The add-on provides a single configuration option: the full content of `mailrise.conf`.

You can edit the configuration in **Home Assistant → Add-ons → Mailrise → Configuration** tab.

Example:

```ini
[email]
port = 8025

[profile:gotify]
urls = gotify://192.168.1.100:80/A1B2C3D4E5F6G7H8

[profile:discord]
urls = discord://TOKEN/GUILD/CHANNEL
