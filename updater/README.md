# Home Assistant Addons Docker Version Updater

This add-on periodically checks the add-ons in your configured GitHub repository, compares their Docker image versions with the latest available tags on Docker registries, and updates the add-ons’ `config.json` version fields accordingly.

## Configuration Options

| Option                 | Description                           | Default                                     |
|------------------------|-------------------------------------|---------------------------------------------|
| github_repo            | GitHub repository URL to clone/pull | https://github.com/ChristoffBo/homeassistant.git |
| github_username        | GitHub username (for private repos)  | (empty)                                    |
| github_token           | GitHub personal access token          | (empty)                                    |
| update_interval_minutes| How often to check for updates (min) | 60                                         |

## Usage

1. Add this add-on repository to your Home Assistant add-ons.
2. Configure the options as needed (especially GitHub credentials if private).
3. Start the add-on.
4. It will automatically update version numbers of your add-ons to match the latest Docker image tags.

## Notes

- Supports Docker Hub and GitHub Container Registry (ghcr.io) for tag lookups.
- The add-on only updates the `config.json` version fields; deploying updated add-ons is a separate step.
- Docker Hub API has rate limits; consider providing credentials for heavy use.
