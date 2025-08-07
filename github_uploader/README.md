# GitHub Uploader Add-on for Home Assistant

This Home Assistant add-on allows you to upload `.zip` files to a GitHub repository via a sleek web UI.  
The contents of the ZIP are extracted and pushed into a new folder (named after the ZIP) inside the target repository.

---

## ✅ Features

- Drag-and-drop or file picker upload
- Auto-extracts ZIP and uploads folder to GitHub
- Supports custom commit message
- Supports private and public repos
- Uses GitHub token authentication
- Auto-detects or overrides branch
- Fully tested and working in **Chrome**

---

## ⚙️ Configuration (`options.json`)

| Option           | Type   | Required | Description                                                                 |
|------------------|--------|----------|-----------------------------------------------------------------------------|
| `github_token`   | string | ✅ Yes   | GitHub personal access token with `repo` scope                             |
| `github_repo`    | string | ✅ Yes   | Full GitHub repo URL (e.g. `https://github.com/YourUser/your-repo`)        |
| `github_path`    | string | ❌ No    | Subfolder inside repo (unused for ZIP mode – reserved for future)          |
| `commit_message` | string | ❌ No    | Commit message for file upload (default: `Uploaded via GitHub Uploader`)   |
| `github_branch`  | string | ❌ No    | Branch to push to (default: auto-detect from GitHub API, fallback: `main`) |

---

## 🌐 Web UI

- Available via Ingress or direct port (default: 8080)
- Upload area supports drag-and-drop or file picker
- UI tested and verified working in **Google Chrome Desktop + Android**

---

## 📁 Upload Behavior

- If you upload `project.zip`, the add-on:
  - Extracts contents
  - Creates folder `project/` in the GitHub repo
  - Uploads all extracted files and folders to that path
- Overwrites files if already present (with `sha` logic)
- Upload is atomic per file, with detailed success/failure count

---

## 🧪 Tested Browsers

| Browser         | Version | Status  |
|-----------------|---------|---------|
| Chrome (Desktop)| ✅ Tested and Working |
| Chrome (Android)| ✅ Tested and Working |
| Firefox         | ⚠️ Not tested |
| Safari          | ⚠️ Not tested |

---

## 🚨 Requirements

- GitHub token must be valid and have write access to the repository
- Repository URL must be the **full HTTPS URL**
- Internet access from container is required for GitHub API calls

---

## 🛠️ Troubleshooting

- ❌ `404: Not Found` → Check `github_repo` format and branch exists
- ❌ `No file selected` → Ensure you selected a `.zip` file before clicking Upload
- ❌ `Upload failed: Bad credentials` → Check `github_token`

---
