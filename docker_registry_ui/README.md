# 🧩 Docker Registry UI

Self-hosted Docker Registry powered by registry:2 with a built-in dark-mode UI for pulling, updating, and managing images locally.

✅ Based on official Docker registry  
✅ Uses skopeo to pull directly from Docker Hub  
✅ Digest comparison: shows 'Update available'  
✅ Fully dark UI styled for Home Assistant  
✅ Ingress compatible  
✅ Mobile-friendly and responsive  
✅ Persistent local image storage  
✅ CLI-free management

📁 Files:
- /data/registry — local Docker image storage
- /data/options.json — add-on settings
- /www — dark UI frontend
- /app — Flask backend logic

⚙️ Configuration:
```json
{
  "registry_port": 5000,
  "webui_port": 8080,
  "initial_pull_images": [
    "linuxserver/sonarr:latest",
    "nginx:latest"
  ],
  "auto_compare_digest": true
}
```

🧪 Options:
- `registry_port`: port where the registry listens
- `webui_port`: port for the web UI backend
- `initial_pull_images`: list of DockerHub images to pre-load
- `auto_compare_digest`: shows update status if tag digest changes

🌍 Web UI:
Available via Home Assistant Ingress or directly on `http://<host>:8080`  
Pull images by name and tag  
View and update hosted images  
Copy `docker pull` command

🧠 Fully offline-capable once images are cached locally.
