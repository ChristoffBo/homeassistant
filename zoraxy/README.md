# 🧩 Zoraxy — Home Assistant Add-on

Run Zoraxy inside Home Assistant — a general-purpose HTTP reverse proxy & forwarding tool (written in Go). Ideal for managing multiple web services, SSL certificates, access control, and more from a homelab.

✅ Uses the official Docker image: tobychui/zoraxy (or zoraxydocker/zoraxy) 0  
✅ Reverse proxy with HTTP/2, virtual directories, alias hostnames 1  
✅ Automatic WebSocket proxying (no manual setup) 2  
✅ TLS/SSL with ACME support, SNI & Let’s Encrypt integration 3  
✅ Blacklist/whitelist support (IP, CIDR, wildcard) 4  
✅ Stream proxy (TCP & UDP) plus utilities & monitoring tools like web SSH, uptime monitor, etc. 5  
✅ Fully self-hosted. No external account required.  

📁 Files:  
/data/options.json — stores add-on settings  
/config/zoraxy — persistent web proxy configuration, certificates, rules, logs  

⚙️ Configuration: {"port":8000, "args":"-noauth=false"}  

🧪 Options:  
port — web UI / management port (default: 8000)  
args — extra startup args (e.g. “-noauth=false”, TLS/ACME settings etc.)  

🌍 Web UI access:  
Accessible via Home Assistant Ingress or direct at `http://<your-ip>:<port>`  
Manage hosts, SSL/TLS, alias names, redirects, stream proxies etc via the UI  

🧠 Fully self-hosted. Designed for homelabs & small clusters.  

🧾 Logs will show proxy routing, SSL certificate issuance, access control decisions, and connection info.