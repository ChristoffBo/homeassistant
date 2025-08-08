# 🧩 2FAuth — Home Assistant Add-on

Self-hosted web app to manage Two-Factor Authentication (2FA) accounts using TOTP. This add-on runs the official Docker image of 2FAuth in Home Assistant.

✅ Uses the official Docker image: 2fauth/2fauth
✅ Web UI available on configurable port (default: 8001)
✅ Supports email notifications
✅ Secure environment variable configuration
✅ Full persistent settings via options.json

📁 Files:
/data/options.json — stores add-on settings and environment variables

⚙️ Configuration:
{
  "APP_URL": "https://auth.something.com",
  "MAIL_ENCRYPTION": false,
  "MAIL_FROM_ADDRESS": "2fa@notifications.co.za",
  "MAIL_FROM_NAME": "2Fauth",
  "MAIL_HOST": "0.0.0.0",
  "MAIL_MAILER": "smtp",
  "MAIL_PORT": 8025,
  "PGID": 0,
  "PUID": 0,
  "TZ": "Africa/Johannesburg",
  "port": 8001
}

🧪 Options:
APP_URL — full URL to access the 2FAuth Web UI
MAIL_ENCRYPTION — true/false for TLS encryption on mail
MAIL_FROM_ADDRESS — email address shown in outbound emails
MAIL_FROM_NAME — sender name for emails
MAIL_HOST — mail server host
MAIL_MAILER — mail driver (usually smtp)
MAIL_PORT — mail server port
PGID/PUID — user/group ID for file access control
TZ — timezone for the container
port — web UI port (default: 8001)

🌍 Web UI access:
https://<your-homeassistant-ip>:8001 or via configured APP_URL

🧠 Important security note:
You must reverse proxy this service via HTTPS to ensure secure 2FA data transfer. Never expose over plain HTTP. Use NGINX, Traefik, or Home Assistant proxy with TLS enabled.

👤 Author:
Christoff — https://github.com/ChristoffBo

🧾 Sources:
2FAuth GitHub — https://github.com/bubka/2fauth
Docker Image — https://hub.docker.com/r/2fauth/2fauth