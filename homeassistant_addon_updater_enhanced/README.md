# Home Assistant Addon Updater Enhanced

![Addon Icon](icon.png)

> Enhanced version with GitHub/Gitea support and Gotify notifications

## Features

- **Dual Repository Support**: Checks GitHub and self-hosted Gitea
- **Semantic Versioning**: Proper version comparison (1.2.0 → 1.3.0)
- **Always Notifies**: Reports even when no updates available
- **Detailed Reports**: Shows exact version changes
- **SSL Options**: Configurable SSL verification for Gitea

## Configuration

```yaml
gotify_url: "http://gotify.example.com"
gotify_token: "your_token"
check_interval: 7200  # in seconds
verbose_logging: true

github_repos:
  - name: "My Addons"
    owner: "myuser"
    repo: "hass-addons"
    token: "ghp_..."

gitea_instances:
  - name: "Local Gitea"
    url: "https://gitea.example.com"
    owner: "hass"
    token: "gta_..."
    verify_ssl: false
