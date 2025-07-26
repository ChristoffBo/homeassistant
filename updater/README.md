# Home Assistant Addons Docker Version Updater

This add-on automatically checks your Home Assistant add-ons repository for updated Docker image versions and updates the add-ons' version numbers accordingly. It keeps your add-ons in sync with the latest Docker tags and logs all updates for easy tracking.

---

## Features

- Automatically clones or updates your add-ons GitHub repository.
- Checks the latest Docker image tags for each add-on.
- Updates `updater.json` and the add-on’s `config.json` with the new Docker image version.
- Appends a simple update entry in `CHANGELOG.md`.
- Logs current and latest versions along with update status.
- Runs an initial update check on add-on startup.
- Runs daily scheduled checks at a configurable time.

---

## Configuration

The add-on options (set in the Supervisor UI):

| Option          | Description                                  | Example                                   |
|-----------------|----------------------------------------------|-------------------------------------------|
| `github_repo`     | URL to your add-ons GitHub repository         | `https://github.com/YourUsername/homeassistant.git` |
| `github_username` | (Optional) GitHub username for private repos  | `myusername`                              |
| `github_token`    | (Optional) GitHub token for private repos     | `ghp_xxx...`                             |
| `check_time`      | Daily time to run update checks (`HH:MM` 24h) | `"03:00"` (3 AM daily)                    |

---

## Usage

- When the add-on starts, it runs an immediate update check.
- Then, it runs daily at the configured `check_time`.
- All update actions and version info are logged in the add-on logs.
- Each add-on’s `CHANGELOG.md` will be appended with a line like:


---

## Add-on Folder Setup

Each add-on in your repository must include an `updater.json` file to enable the updater script to track Docker image versions.

---

### Example `updater.json`

```json
{
"slug": "example_addon",
"upstream_repo": "your-dockerhub-username/example_addon",
"upstream_version": "1.0.0",
"last_update": "01-01-2025"
}
Explanation:

    slug: Unique identifier, usually the add-on folder name.

    upstream_repo: Docker Hub repo name (e.g., username/repository).

    upstream_version: Current Docker tag version.

    last_update: Last update date (DD-MM-YYYY), auto-updated by the script.

Example Add-on Folder Structure

example_addon/
├── config.json
├── updater.json
├── CHANGELOG.md
└── other addon files...
Logging

You can view detailed logs from the Supervisor UI. Logs show:

    Add-on slug.

    Current Docker image version.

    Latest Docker image version.

    Current version in config.json (GitHub).

    Whether an update was performed.

    Changelog updates.
Notes

    For private GitHub repositories, set github_username and github_token.

    The add-on assumes your Docker images are hosted on Docker Hub.

    The script fetches only the latest Docker tag based on last updated time.

    If CHANGELOG.md does not exist, it will be created automatically.
