# Addons Updater Enhanced

![Version](https://img.shields.io/badge/version-4.0.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> Enhanced version of [alexbelgium's addon-updater](https://github.com/alexbelgium/hassio-addons) with additional features

## Key Enhancements
- **Dual Repository Support**: Choose between GitHub or self-hosted Gitea
- **Optional Notifications**: Gotify integration (disabled by default)
- **Improved Safety**: File locking, input validation, and dry-run mode
- **Better Logging**: Detailed logs at `/var/log/addons-updater.log`

## Quick Configuration
```yaml
repo_source: github  # or "gitea"
enable_gotify: false
repo_path: /config/addons
addon_paths:
  - addons
  - community
