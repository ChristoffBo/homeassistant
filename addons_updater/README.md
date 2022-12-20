# Home assistant add-on: addons updater


## About

This script allows to automatically update addons based on upstream new releases. This is only an helper tool for developers. End users don’t need that to update their addons - they are automatically alerted by HA when an update is available

## Installation

The installation of this add-on is pretty straightforward and not different in
comparison to installing any other Hass.io add-on.

1. [Add my Hass.io add-ons repository][repository] to your Hass.io instance.
1. Install this add-on.
1. Configure the add-on to your preferences, see below
1. Click the `Save` button to store your configuration.
1. Start the add-on.
1. Check the logs of the add-on to see if everything went well.

## Configuration

No webUI. Configuration is set in 2 ways.

### Updater.json

In the addon folder of your repository (where is located you config.json), create a "updater.json" file.
This file will be used by the addon to fetch the addon upstream informations.
Only addons with an updater.json file will be updated.
Here is [an example](https://github.com/alexbelgium/hassio-addons/blob/master/arpspoof/updater.json).

You can add the following tags in the file :

- fulltag: true is for example "v3.0.1-ls67" false is "3.0.1"
- github_beta: true/false ; should it look only for releases or prereleases ok
- github_havingasset : true if there is a requirement that a release has binaries and not just source
- github_tagfilter: filter a text in the release name
- last_update: automatically populated, date of last upstream update
- repository: 'name/repo' coming from github
- paused: true # Pauses the updates
- slug: the slug name from your addon
- source: dockerhub/github,gitlab,bitbucket,pip,hg,sf,website-feed,local,helm_chart,wiki,system,wp
- upstream_repo: name/repo, example is 'linuxserver/docker-emby'
- upstream_version: automatically populated, corresponds to the current upstream version referenced in the addon
- dockerhub_by_date: in dockerhub, uses the last_update date instead of the version
- dockerhub_list_size: in dockerhub, how many containers to consider for latest version

### Addon configuration

Here you define the values that will allow the addon to connect to your repository.

```yaml
repository: 'name/repo' coming from github
gituser: your github username
gitpass: your github password
gitmail: your github email
verbose: 'false'
gitapi: optional, it is the API key from your github repo
```

Example:

```yaml
repository: alexbelgium/hassio-addons
gituser: your github username
gitpass: your github password
gitmail: your github email
verbose: "false"
```

[repository]: https://github.com/alexbelgium/hassio-addons
