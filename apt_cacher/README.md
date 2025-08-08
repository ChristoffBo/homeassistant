# 🧩 APT Cacher NG — Home Assistant Add-on

Run a caching proxy for Debian/Ubuntu APT repositories inside Home Assistant. Caches .deb packages and metadata to reduce bandwidth usage and speed up package installations across your local network.

✅ Uses the official Docker image: sameersbn/apt-cacher-ng
✅ Speeds up updates for Debian/Ubuntu systems
✅ Persistent cache across restarts
✅ All settings exposed in options.json
✅ Works offline once packages are cached
✅ Host network support included

📁 Files:
/data/options.json — stores add-on settings
/var/cache/apt-cacher-ng — persistent APT package cache

⚙️ Configuration: { "port": 3142 }

🧪 Options:
port — the port used by apt-cacher-ng (default: 3142)

🌍 Web UI access:
Access the status and cache report at http://<your-ip>:3142/acng-report.html
(Add-on does not support Ingress — use host network access only)

🧠 Fully self-hosted. No external account required.

🧪 Client Setup:
To connect a Debian/Ubuntu/Kali/Mint/RPi system to this cache:
echo 'Acquire::http::Proxy "http://<HOME_ASSISTANT_IP>:3142";' | sudo tee /etc/apt/apt.conf.d/01proxy

Example:
echo 'Acquire::http::Proxy "http://192.168.1.100:3142";' | sudo tee /etc/apt/apt.conf.d/01proxy

Then run:
sudo apt update

The first machine downloads from the internet. All others pull instantly from the cache.

🧾 Logs will show connections like:
[INFO] 192.168.x.x -> http://archive.ubuntu.com/...

Compatible with: Debian, Ubuntu, Kali, Linux Mint, Raspberry Pi OS, and any APT-based Linux system.