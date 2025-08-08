# 🧩 Technitium DNS Home Assistant Add-on

Self-hosted DNS server powered by Technitium. Offers DNS-over-HTTPS, DNS-over-TLS, logging, and blocklist support.

✅ Uses the official Docker image: technitium/dns-server  
✅ Works offline once started  
✅ Full Web UI on configurable port  
✅ Persistent storage enabled  
✅ All settings exposed in options.json  
✅ No build needed

📁 Files:  
- /data/options.json — stores add-on settings  
- /config — persistent volume for DNS data

⚙️ Configuration:  
{ "port": 5380 }

🧪 Options:  
  port — sets the Technitium web interface port (default: 5380)

🌍 Web UI access:  
Accessible at `http://<your-ip>:<port>` (e.g., `http://192.168.1.10:5380`)

🧠 Fully self-hosted. No external account required.