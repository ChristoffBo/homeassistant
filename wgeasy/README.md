# 🧩 WireGuard Easy  
Created by **jdeath**, rebuilt for Home Assistant in the locked dark-mode style — the easiest way to install and manage WireGuard VPN directly inside Home Assistant.  

✅ All-in-one VPN + Web UI  
✅ Full Ingress support  
✅ Simple client management  
✅ Auto-generated QR codes & configs  
✅ Real-time stats and Tx/Rx charts  
✅ Persistent config storage  
✅ Gravatar avatar support  

📁 Key paths and files  
/ssl/wgeasy → Default config storage  
/share/wgeasy → Optional custom storage  

⚙️ Configuration (flat JSON example)  
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

🧪 Options explained  
- PASSWORD_HASH – Optional login password hash for the Web UI (docker run -it ghcr.io/wg-easy/wg-easy wgpw YOUR_PASSWORD).  
- WG_HOST – Your public hostname or external IP.  
- WG_PORT – UDP port your router forwards to Home Assistant.  
- WG_CONFIG_PORT – UDP port used internally by the add-on.  
- WG_DEVICE – Ethernet device for traffic forwarding (usually eth0).  
- WG_PATH – Persistent config directory (/ssl/wgeasy or /share/wgeasy).  
- WG_PERSISTENT_KEEPALIVE – Optional keepalive interval (seconds).  
- WG_DEFAULT_ADDRESS – Client subnet (default 10.8.0.x).  
- WG_DEFAULT_DNS – DNS servers clients will use.  
- WG_ALLOWED_IPS – IP ranges allowed through the VPN.  
- WG_POST_UP / WG_POST_DOWN – Leave blank or "" if add-on fails to start.  

🌍 Web UI Access  
The UI opens directly via Home Assistant Ingress — no manual port required.  
For direct access, forward WG_PORT (default 51820) from your router to your Home Assistant IP.  
⚠️ Do not expose the UI directly to the internet unless you fully understand the risk.  

🧠 Notes  
- Ensure /ssl/wgeasy exists before first start.  
- To use AdGuard Home with WireGuard, set WG_DEFAULT_DNS to 172.30.32.1.  
- If the add-on refuses to start, clear WG_POST_UP and WG_POST_DOWN.  
- Rebuilding automatically pulls the latest WireGuard version but not custom UI changes from upstream.  

✅ Features  
- Full Ingress support  
- Add, edit, delete, enable/disable clients  
- QR code and config download per client  
- Real-time client stats and charts  
- Built-in password protection (optional)  
- Seamless HA integration  

🧩 Credits  
Originally created by **jdeath** (https://github.com/jdeath/homeassistant-addons), adapted to this format for Home Assistant users.