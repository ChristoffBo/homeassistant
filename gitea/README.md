This Home Assistant add-on runs a self-hosted instance of Gitea, a lightweight, all-in-one Git server alternative to GitHub, Bitbucket, or GitLab. Gitea provides source control, code review, CI/CD, package registry, and more in a simple web interface. This add-on uses the official gitea/gitea Docker image. It was originally created by Alex Belgium. This version is hosted and maintained on my own Git repository for integration with my environment. Source: https://github.com/alexbelgium/hassio-addons

The web interface can be accessed at http://<your-ip>:<port> unless HTTPS is enabled. If SSL is enabled, access via https://<your-domain>:<port>.

Configuration options available via options.json:

certfile - SSL certificate file (default: fullchain.pem). Must be located in /ssl  
keyfile - SSL key file (default: privkey.pem). Must be located in /ssl  
ssl - true or false. Enables or disables HTTPS  
APP_NAME - Custom name for the Gitea instance  
DOMAIN - Public domain to access the instance (default: homeassistant.local)  
ROOT_URL - Optional override for root URL, used only for advanced setups  

Installation instructions:

1. Add my Home Assistant add-ons repository to your instance.  
2. Install the Gitea add-on.  
3. Configure options as needed.  
4. Click Save to store your configuration.  
5. Start the add-on.  
6. Access the web UI and complete the Gitea setup.  
7. Restart the add-on to apply configuration changes (especially ROOT_URL and APP_NAME).