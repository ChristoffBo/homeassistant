# Home Assistant Addon Updater Enhanced

![Addon Icon](icon.png)

## Features

✔ **Dual Repository Support** - GitHub + Gitea  
✔ **Detailed Gotify Notifications**  
✔ **Strict Version Comparison**  
✔ **Home Assistant Validated**  
✔ **Error-Resistant Implementation**

## Compatibility

✅ Tested with Home Assistant Core 2023.12+  
✅ Works with supervised/container installations  
✅ Verified on all supported architectures

## Configuration Example

```yaml
gotify_url: "https://gotify.example.com"
gotify_token: "your_token"
check_interval: 7200

github_repos:
  - name: "My Addons"
    owner: "youruser"
    repo: "hassio-addons"
    token: "ghp_..."

gitea_instances:
  - name: "Local Gitea"
    url: "http://192.168.1.100:3000"
    owner: "hass"
    token: "gta_..."
