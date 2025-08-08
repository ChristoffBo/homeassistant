# 🧩 AdGuard DNS Home Assistant Add-on
Self-hosted DNS server with powerful ad-blocking powered by AdGuard Home.

✅ Uses the official Docker image: adguard/adguardhome
✅ Persistent DNS and UI configuration
✅ Supports DNS over TCP and UDP
✅ Initial setup and main UI ports handled correctly
✅ All ports are user-configurable
✅ No build step required

📁 Files:
- config.json — defines port mappings, image, ingress, and architecture
- options.json — stores user-defined port overrides for DNS, Setup UI, and Web UI

⚙️ Configuration:
{ "dns_port": 53, "setup_port": 3000, "web_port": 80 }

🧪 Options:
dns_port — port to expose DNS TCP+UDP (default: 53)
setup_port — port for the initial AdGuard setup UI (default: 3000)
web_port — port for the main Web UI after setup is complete (default: 80)

🌍 Web UI access:
- First run: http://[HOST]:3000 (Setup Interface)
- After setup: http://[HOST]:80 (Main Dashboard)
- Ingress will automatically forward based on current active UI

🧠 Fully self-hosted. No external accounts required. Configuration persists across reboots.
