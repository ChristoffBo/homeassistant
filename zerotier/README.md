# ZeroTier Controller with ZeroUI Add-on

This Home Assistant add-on combines:

- **ZeroTier Controller**: Manage your ZeroTier networks privately.
- **ZeroUI**: Web interface for managing ZeroTier nodes and networks.

## ⚠️ Features

✅ ZeroTier controller running locally  
✅ ZeroUI accessible on port **4000**  
✅ Single container deployment with **supervisord**

---

## 🔧 Configuration

No user configuration required by default. Access:

- **ZeroUI Web UI**: `http://<home_assistant_ip>:4000`

Default credentials:

- **Username:** admin
- **Password:** zero-ui

---

## 🚀 Installation

1. Clone this repository into your Home Assistant add-ons folder.
2. Build the add-on or publish to your Docker registry.
3. Install via Home Assistant Supervisor > Add-ons.

---

## 📝 Notes

- Ensure `NET_ADMIN` privilege is allowed.
- Adjust environment variables in `supervisord.conf` if needed for your deployment.
- For external HTTPS access, consider a separate reverse proxy (NGINX Proxy Manager or Caddy).

---

## 📚 References

- [ZeroTier GitHub](https://github.com/zerotier/ZeroTierOne)
- [ZeroUI GitHub](https://github.com/dec0dos/zero-ui)

---

**Maintained by Christoff for personal and lab deployments.**