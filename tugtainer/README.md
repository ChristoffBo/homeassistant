🧩 Tugtainer (Manager Mode)

Tugtainer is a self-hosted web-based Docker update manager. This Home Assistant add-on runs the official image docker.io/quenary/tugtainer:latest in manager-only mode. It provides a central dashboard for monitoring and controlling multiple remote Tugtainer agents running on your other Docker hosts.

✅ Features
- Web UI available via Home Assistant Ingress and external ports (9000 / 8443)
- Manager-only operation — no local Docker socket required
- Connects securely to remote agents
- Shows container status, available updates, and update logs
- Configurable notification integrations (Gotify, ntfy, Discord, Email)
- Stores configuration and agent data under /data

📁 Paths
/data — stores database, settings, agent list, and logs

🌍 Access
Open via Home Assistant sidebar (Ingress)
or directly: http://homeassistant.local:9000
Agents connect to: https://<homeassistant-ip>:8443

⚙️ Configuration
No configuration needed in options.json — all settings and agent connections are added directly in the Tugtainer UI.

🧠 Important Notes
This add-on only acts as a manager. It cannot update Home Assistant add-ons or containers running within the Supervisor environment because it has no access to the Docker socket. All container actions are performed through remote agents running on your external Docker hosts.

📦 Example Docker Compose for Tugtainer Agent
version: "3.9"
services:
  tugtainer-agent:
    image: docker.io/quenary/tugtainer-agent:latest
    container_name: tugtainer-agent
    restart: unless-stopped
    environment:
      - TZ=Africa/Johannesburg
      - AGENT_NAME=Proxmox01
      - MANAGER_URL=https://homeassistant.local:8443
      - MANAGER_TOKEN=<your-agent-token-from-UI>
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/localtime:/etc/localtime:ro
    network_mode: bridge

🧪 Usage
1. Start this add-on and open the Tugtainer dashboard.
2. In the UI, create an Agent entry to generate a connection token.
3. Deploy the above agent-compose on your remote Docker host (Unraid, Debian, etc.).
4. Once connected, the host and its containers will appear in the dashboard.
5. You can check or trigger updates from the manager UI.

🧠 Summary
This add-on acts only as the central controller (Manager). Agents installed on other Docker hosts handle container update operations. Together they provide a full Watchtower-like system with UI visibility, per-container control, and cross-host management.