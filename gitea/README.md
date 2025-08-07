This Home Assistant add-on provides a self-hosted Gitea Git server with a web UI. It is based on the official gitea/gitea Docker image. Gitea is a lightweight alternative to GitHub, GitLab, and Bitbucket offering Git hosting, code review, issue tracking, CI/CD, and more. This version was originally created by Alex Belgium. I maintain it in my own Git repository for personal use and availability.

🌐 Web UI: http://<your-ip>:<port> or https://<your-domain>:<port> if ssl is enabled

⚙️ Configuration options available in options.json:

certfile - default: fullchain.pem. SSL cert file (must be located in /ssl)  
keyfile - default: privkey.pem. SSL key file (must be located in /ssl)  
ssl - true or false. Enables or disables HTTPS  
APP_NAME - Sets a custom app title  
DOMAIN - Public domain name (default: homeassistant.local)  
ROOT_URL - Optional override for the root URL (advanced use only)

📦 Installation steps:

1. Add my Home Assistant add-ons repository  
2. Install the add-on  
3. Edit configuration if needed  
4. Click Save  
5. Start the add-on  
6. Open the Web UI and complete Gitea’s setup  
7. Restart the add-on to apply any config such as ROOT_URL