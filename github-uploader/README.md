# GitHub Uploader Add-on for Home Assistant

This Home Assistant add-on provides a secure, dark-mode web interface to upload `.zip` files directly into your GitHub repository — with automatic folder creation, overwrite support, and detailed results.

---

## 🧰 Features

- Upload `.zip` files via web GUI
- Automatically extracts and uploads all contents
- If a file exists, it is **updated**
- If a file is new, it is **created**
- Auto-generates folder name from ZIP filename if left blank
- GitHub token and repository can be saved permanently
- Real-time results shown after upload
- Works over Ingress — secure and internal

---

## 🧾 Options (Supervisor UI → Configuration)

You can store your token and repo for reuse:

```json
{
  "github_token": "ghp_xxx",
  "github_repo": "ChristoffBo/homeassistant"
}