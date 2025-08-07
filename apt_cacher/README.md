# APT Cacher NG — Home Assistant Add-on

APT Cacher NG is a caching proxy for Debian/Ubuntu APT repositories. It reduces bandwidth usage and speeds up package installation by caching .deb packages and metadata downloaded via apt on your local network.

This add-on allows you to run a full-featured apt-cacher-ng server inside Home Assistant, accessible to all Debian/Ubuntu clients on your network.

## What It Does

- Caches APT packages and metadata requested by Debian/Ubuntu clients
- Speeds up software installation and updates across multiple systems
- Reduces external internet usage
- Stores cache in persistent container storage
- Automatically listens on your configured port (default: 3142)

## How It Works

APT clients (e.g. on Debian, Ubuntu, Kali, etc.) are configured to use your Home Assistant server as a proxy. When a client downloads a package, the add-on:

1. Checks if the package exists in its local cache.
2. If yes → delivers it from local storage.
3. If no → downloads it from the internet, stores it, and delivers it to the client.

Future requests for the same package (from any device) are then served instantly from cache.

## Configuration

Open the add-on configuration in Home Assistant and set your desired port (default: 3142):

{
  "port": 3142
}

Make sure host_network is enabled. Restart the add-on after changing the port.

## Connecting a Linux Client

To use the cache from any Debian or Ubuntu-based machine on your network:

1. Open a terminal on the target machine.
2. Replace <HOME_ASSISTANT_IP> with your actual Home Assistant server IP.
3. Run:

echo 'Acquire::http::Proxy "http://<HOME_ASSISTANT_IP>:3142";' | sudo tee /etc/apt/apt.conf.d/01proxy

Example:

echo 'Acquire::http::Proxy "http://192.168.1.100:3142";' | sudo tee /etc/apt/apt.conf.d/01proxy

4. You’re done. Test it with:

sudo apt update

The first request downloads the package. All subsequent requests (from any machine) are served from the cache.

## Verifying It Works

Check the Home Assistant add-on logs. You should see lines like:

[INFO] Starting apt-cacher-ng on port 3142
...
192.168.x.x -> http://archive.ubuntu.com/...

This means a client connected and fetched a package.

## Cache Location

The APT cache is stored in:

/var/cache/apt-cacher-ng

This location is persistent inside the container and survives restarts.

## Troubleshooting

- Add-on not starting: Make sure the configured port is free and host_network is true.
- Clients not connecting: Ensure your HA IP is correct and reachable.
- Nothing cached: Confirm the client is using the proxy via /etc/apt/apt.conf.d/01proxy.

## Supported Client OS

- Debian
- Ubuntu
- Kali
- Linux Mint
- Raspberry Pi OS (Debian-based)

Any Linux distribution using APT can connect to this cache.

## Why Use This?

- Reduces internet bandwidth usage
- Speeds up repeated installs or updates
- Useful in labs, test rigs, VMs, or slow networks
- Works offline once packages are cached

## Resources

- Project: https://www.unix-ag.uni-kl.de/~bloch/acng/
- Docker image: https://hub.docker.com/r/sameersbn/apt-cacher-ng
- Add-on author: https://github.com/ChristoffBo
