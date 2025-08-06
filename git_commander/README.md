# Git Commander Add-on

Git Commander is a Home Assistant add-on that enables you to:

- Upload ZIP files via a web UI and automatically commit and push to GitHub or Gitea repositories.
- Manage Git repositories with commands like pull, status, reset, stash, and commit via a user-friendly interface.
- Backup and restore your repository files.
- Configure all settings through a simple UI or `options.json`.

## Features

- ZIP Upload → Extract → Commit → Push to GitHub/Gitea
- Git Toolkit with pull, status, reset, stash, commit commands
- Backup current repo as ZIP
- Restore from backup ZIP
- Dark mode, mobile-friendly UI with tabs
- Supports GitHub and Gitea with token authentication
- Fully configurable via `options.json`

## Configuration

Set your GitHub or Gitea repository URLs and tokens in `options.json` or via the UI:

```json
{
  "github_url": "https://github.com/YourUser/YourRepo",
  "github_token": "your_github_token",
  "gitea_url": "https://gitea.local/YourUser/YourRepo",
  "gitea_token": "your_gitea_token",
  "repository": "uploads",
  "commit_message": "Uploaded via Git Commander",
  "branch_name": "main",
  "author_name": "Git Commander",
  "author_email": "git@example.com",
  "git_target": "github",
  "use_https": true
}
