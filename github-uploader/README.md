# GitHub Uploader Add-on for Home Assistant

This Home Assistant add-on provides a secure, dark-mode web interface to upload `.zip` files directly to a GitHub repository.

---

## 🧰 Features

- Upload `.zip` files from browser (mobile or desktop)
- Extracts and commits files to any GitHub repository
- Customizable:
  - GitHub Token
  - Repository name (e.g., `ChristoffBo/homeassistant`)
  - Target folder (e.g., `zerotier-controller-ui`)
  - Commit message
- Works via Home Assistant Ingress (no open ports needed)
- 100% local and private

---

## 📦 Options (config.json schema)

No user-configurable options via Supervisor UI. All settings are provided in the web form at runtime.

---

## 🌐 Web Interface Fields

| Field             | Description                             |
|------------------|-----------------------------------------|
| ZIP File         | Upload `.zip` containing add-on files   |
| GitHub Token     | PAT with `repo` scope                   |
| Repository Name  | e.g., `ChristoffBo/homeassistant`       |
| Target Folder    | Subfolder to commit files into          |
| Commit Message   | Description for GitHub commit           |

---

## 🔒 Security

- GitHub token is never logged or stored on disk
- File uploads are processed in memory and deleted after commit
- HTTPS is enforced via Home Assistant ingress proxy

---

## 🚀 How to Use

1. Install the add-on via Supervisor
2. Start it and open via Ingress
3. Fill in the form and upload your `.zip`
4. Click **Upload** — files are pushed to your GitHub repo

---

## 📁 Repo Structure After Commit

If you upload `zerotier-controller-ui.zip`, and set folder to `zerotier-controller-ui`, your GitHub repo will receive:
