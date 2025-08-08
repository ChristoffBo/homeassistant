# 🧩 Portainer Home Assistant Add-on
Self-hosted Docker management UI powered by Portainer CE. Easily manage containers, images, networks, and volumes.

✅ Uses the official Docker image: portainer/portainer-ce
✅ Web UI available via Ingress or port 9000
✅ Fully persistent configuration and data storage
✅ Lightweight and fast
✅ Drag-and-drop Docker image uploads (via Portainer UI)

📁 Files:
- /data/options.json — stores add-on settings
- /data/portainer — persistent data volume

⚙️ Configuration:
{ "port": 9000, "cli_args": "", "image_override": "portainer/portainer-ce" }

🧪 Options:
  port — sets the exposed Web UI port (default 9000)
  cli_args — any additional arguments passed to the container
  image_override — optionally use an alternate image

🌍 Web UI accessible via Ingress or http://[HOST]:[PORT:9000]
🧠 Fully self-hosted. No external account required.
