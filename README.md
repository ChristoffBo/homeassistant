Home Assistant Addons Repository

Welcome to the ChristoffBo Home Assistant Addons repository! 🎉

This repository contains a curated collection of custom Home Assistant addons designed to enhance and extend your Home Assistant experience. These addons are containerized and can be managed easily with this repo.

    Note: This repository was originally created for private use but is shared here for reference and community benefit.

What’s Inside

    🚀 Custom Home Assistant addons, including:

        Mailrise — Mail server notification addon

        Gotify — Push notification server addon

        Heimdall — Application dashboard addon

        Technitium DNS — The best DNS and DHCP server with ingress!

        Update Checker — Automated addon update management

    Scripts and helpers to automate addon updates and management.

    Configuration and Docker-related files for building and deploying addons.

Features & Benefits

    Easy to add to your Home Assistant instance via the addon store or manual installation.

    Automated update checks that keep your addons running the latest Docker images.

    Support for multiple registries like Docker Hub, LinuxServer.io, and GHCR.

    Secure with support for private GitHub repositories and authenticated DockerHub API calls.

    Detailed changelogs and version tracking for each addon.

    Clear logs with color coding and emojis to improve readability.

Getting Started
Installation

    Add the repository to Home Assistant

        Go to Supervisor > Add-on Store > Repositories

        Enter the URL: https://github.com/ChristoffBo/homeassistant

        Add the repository and wait for addons to appear.

    Install an addon

        Choose an addon from the list and click Install

        Configure addon options as needed (refer to each addon’s documentation).

    Run and configure

        Start the addon and check logs for proper startup.

        Customize your addon settings via the Home Assistant UI.

Configuration & Usage

    Each addon contains its own config.json and optionally build.json files.

    Update scheduling and Docker image version management are handled by the updater script included in the repo.

    You can customize update intervals and authentication tokens in the updater’s options.

Supported Docker Registries

    Docker Hub (including LinuxServer.io)

    GitHub Container Registry (GHCR)

Contributing

Contributions are very welcome! 🙌

    Feel free to submit issues for bugs or feature requests.

    Open pull requests with improvements, bug fixes, or new addons.

    Follow conventional commit messages to keep the repo history clean.

License

This repository is licensed under the MIT License.
© 2026 Christoff Bothma

See the LICENSE file for details.
Support & Contact

If you need help or have questions, feel free to open an issue or contact me through GitHub.
Roadmap (Planned Features)

    Add more custom addons for popular Home Assistant integrations.

    Implement more robust CI/CD pipelines for automated testing and publishing.

    Enhance documentation with examples and tutorials.

    Add GitHub Pages or wiki for expanded user guides.

Thanks for checking out the repo — happy automating! 🤖✨
