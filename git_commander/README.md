Git Commander Home Assistant Add-on

Git Commander is a Home Assistant add-on that enables you to:





Upload ZIP files via a web UI and automatically commit and push to GitHub or Gitea repositories.



Manage Git repositories with commands like pull, status, reset, stash, and commit via a user-friendly interface.



Backup and restore your repository files.



Configure all settings through a simple UI or options.json.

Features





ZIP Upload → Extract → Commit → Push to GitHub/Gitea



Git Toolkit with pull, status, reset, stash, commit commands



Backup current repo as ZIP



Restore from backup ZIP



Dark mode, mobile-friendly UI with tabs



Supports GitHub and Gitea with token authentication



Fully configurable via options.json

Installation





Add this repository to your Home Assistant Add-on Store:





Go to Supervisor -> Add-on Store -> Add new repository



Enter https://github.com/youruser/git-commander-addon



Install the Git Commander add-on.



Configure the add-on via the UI or by editing options.json in the add-on's configuration directory.

Configuration

Set your GitHub or Gitea repository URLs and tokens in options.json or via the UI:

{
  "github_url": "https://github.com/YourUser/YourRepo",
  "github_token": "your_github_token",
  "gitea_url": "https://gitea.local/YourUser/YourRepo",
  "gitea_token": "your_gitea_token",
  "repository": "Uploads",
  "commit_message": "Uploaded via Git Commander",
  "branch_name": "main",
  "author_name": "Git Commander",
  "author_email": "git@example.com",
  "git_target": "github",
  "use_https": true
}

Usage





Upload: Upload a ZIP file via the web UI, which will be extracted, committed, and pushed to the configured repository.



Git Commands: Execute pull, status, reset, stash, or commit from the Git Commands tab.



Backup: Create a ZIP backup of the repository, downloadable via the UI.



Restore: Upload a backup ZIP to restore the repository.



Config: Update repository settings via the Configuration tab.

Development

To build and test locally:





Clone this repository: git clone https://github.com/youruser/git-commander-addon



Build the Docker image: docker build -t git-commander .



Run the add-on: docker run -p 5000:5000 -v /path/to/data:/data -v /path/to/share:/share git-commander

Contributing

Contributions are welcome! Please open an issue or pull request on GitHub.

License

MIT License
