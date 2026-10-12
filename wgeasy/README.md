# 🧩 WireGuard Easy (wg-easy 15)

WireGuard VPN with a web UI to add clients, show QR codes and download configs. Based on the official image ghcr.io/wg-easy/wg-easy:15.

✅ WireGuard VPN + web UI in one  
✅ Add, edit, enable, disable and remove clients  
✅ QR code and config download per client  
✅ Live connection and traffic stats  
✅ Persistent storage: everything is kept in the add-on's /data  

🌍 Web UI:  
Open it from the add-on page (**Open Web UI**) or at `http://<home-assistant-ip>:51821`.  
The first visit runs the setup wizard: create the admin user, then enter the host name or public IP and the port clients connect to.

📡 Router:  
Forward **UDP 51820** from your router to your Home Assistant IP.  
Do not expose the web UI (51821) to the internet.

⚙️ Options:  
- `insecure` (default `true`): allow the web UI over plain http. Leave it on unless you put the UI behind HTTPS.  
- `disable_ipv6` (default `false`): turn off IPv6 for the VPN, if your network has no IPv6.

📝 Upgrading from the old version 14 add-on:  
wg-easy 15 is a complete rewrite and stores its data differently, so v14 clients are not carried over. Run the setup wizard and add the clients again (new QR codes).

🧩 Credits  
wg-easy (https://github.com/wg-easy/wg-easy). The original add-on was by jdeath (https://github.com/jdeath/homeassistant-addons), now archived.
