# 🧩 Technitium DNS Add-on

Self-hosted, open-source DNS server based on the official **technitium/dns-server** image. Offers authoritative & recursive DNS, encrypted DNS protocols, blocklists, logging, and a full web UI, all managed locally with no external accounts required.  

✅ Features  
• Recursive & authoritative DNS server — serve zones locally *and* resolve external domains. 0  
• Support for DNS-over-HTTPS, DNS-over-TLS, DNS-over-QUIC protocols for privacy & security. 1  
• Blocklists: block ads, malware etc via block list URLs, with automatic updates. 2  
• Advanced caching: serve stale entries, prefetching, persistent cache on disk. 3  
• DNSSEC validation & signing for enhanced security. 4  
• Web console & HTTP API; full UI for managing zones, forwarders, security settings, logging. 5  
• IPv6 support, proxy support (HTTP/SOCKS5), and multiple platform support including Docker. 6  

📁 Key paths  
• /data/options.json — add-on settings/configuration  
• /config — persistent volume for Technitium DNS data (zones, logs, cache)  

⚙️ Configuration example (flat JSON)  
{"port":5380,"data_dir":"/config/technitium-dns"}  

🧪 Options  
• port — port for the web UI / web console (default: 5380)  
• data_dir — where DNS server stores its data (zones/logs/cache) — default is under /config; ensure proper persistence  

🌍 Web UI access  
• Browse to `http://<your-host-ip>:<port>`  
• The web console allows full control: zones, forwarders, security, blocklists, logs  

🧠 Notes  
• Uses the official Technitium DNS Server image: technitium/dns-server 7  
• Supports out-of-the-box functionality — minimal setup needed  
• If you change the port or data_dir, apply and restart the add-on  
• Best to avoid using remote/NFS paths without ensuring file locking & performance  
• All settings exposed via options.json and via the web API/console