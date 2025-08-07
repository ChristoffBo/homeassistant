# GitHub Uploader

A Home Assistant add-on to upload ZIP files to GitHub through a dark-mode GUI.

## Features
- Drag & drop or tap to upload ZIP files
- Automatically extracts, initializes Git, commits, and pushes to GitHub
- Uses full repo URL (e.g., https://github.com/YourUser/YourRepo)
- Settings persist through `options.json` or UI

## Configuration
- `github_url`: Full URL of your GitHub repo
- `github_token`: Token with push access

## Notes
- UI will notify if values are already set
- Only GitHub is supported in this version
