# 🧩 WireGuard Easy
Created by jdeath and adapted for Home Assistant. This add-on provides a full WireGuard VPN with integrated Web UI directly inside Home Assistant for secure and simple remote access.

✅ All-in-one WireGuard VPN + Web UI  
✅ Ingress supported  
✅ Create, edit, enable, disable, and remove clients  
✅ QR code and config download per client  
✅ Real-time connection and traffic stats  
✅ Persistent configuration storage  
✅ Simple installation and management  

📁 Paths  
/ssl/wgeasy → Default persistent storage  
/share/wgeasy → Optional alternate storage path  

⚙️ Configuration  
{
  "PASSWORD_HASH": "",
  "WG_HOST": "vpn.myserver.com",
  "WG_PORT": 51820,
  "WG_CONFIG_PORT": 51820,
  "WG_DEVICE": "eth0",
  "WG_PATH": "/ssl/wgeasy",
  "WG_PERSISTENT_KEEPALIVE": 0,
  "WG_DEFAULT_ADDRESS": "10.8.0.x",
  "WG_DEFAULT_DNS": "1.1.1.1",
  "WG_ALLOWED_IPS": "0.0.0.0/0, ::/0",
  "WG_POST_UP": "",
  "WG_POST_DOWN": ""
}

🧪 Options  
PASSWORD_HASH – Optional Web UI password hash (docker run -it ghcr.io/wg-easy/wg-easy wgpw YOUR_PASSWORD)  
WG_HOST – Public hostname or external IP of your VPN server  
WG_PORT – UDP port forwarded to Home Assistant (default 51820)  
WG_CONFIG_PORT – Internal WireGuard config port  
WG_DEVICE – Network interface used for forwarding (usually eth0)  
WG_PATH – Config directory for WireGuard data  
WG_PERSISTENT_KEEPALIVE – Optional keepalive interval in seconds  
WG_DEFAULT_ADDRESS – IP range for clients (default 10.8.0.x)  
WG_DEFAULT_DNS – DNS server(s) clients use  
WG_ALLOWED_IPS – IP ranges routed through VPN  
WG_POST_UP / WG_POST_DOWN – Leave blank or "" if add-on fails to start  

🌍 Access  
UI loads via Home Assistant Ingress automatically.  
To use externally, forward UDP port 51820 from your router to your Home Assistant IP.  
Do not expose the UI directly to the internet unless you know what you are doing.  

🧠 Notes  
Ensure /ssl/wgeasy exists before starting.  
To use with AdGuard Home, set WG_DEFAULT_DNS to 172.30.32.1.  
If the add-on refuses to start, clear WG_POST_UP and WG_POST_DOWN.  
Rebuilding pulls the latest WireGuard version but not UI changes from upstream.  

✅ Features  
Ingress-ready interface  
Add, edit, delete, and manage clients easily  
Generate QR codes and download configs  
View live connection and bandwidth stats  
Secure password-protected Web UI (optional)  
Automatic persistent configuration  

🧩 Credits  
Originally created by jdeath (https://github.com/jdeath/homeassistant-addons).