# GitHub Uploader Add-on

This Home Assistant add-on allows you to upload files to a GitHub repository using a drag-and-drop Web UI.

## Features

- Upload ZIP or individual files
- Specify GitHub token, target repo URL, path, and commit message
- Supports Ingress in Home Assistant
- Fully mobile-friendly with dark mode

## Configuration

Configure via the add-on's UI or edit `options.json`:

```yaml
github_token: "ghp_xxxxxxxxxxxxxxxxxxxxxxxx"
repository_url: "https://github.com/YourUser/YourRepo"
target_path: "uploads/"
commit_message: "Upload via GitHub Uploader"
```

## Notes

- Token must have `repo` scope.
- The repository must already exist.
