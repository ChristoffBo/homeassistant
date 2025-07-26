# 🚀 ZeroTier Controller Home Assistant Add-on

A self-hosted ZeroTier Controller + PostgreSQL + ZTNet UI all-in-one container for Home Assistant.

## 🧩 Components

- **PostgreSQL**: backend database
- **ZeroTier-One**: software-defined networking
- **ZTNet**: UI for managing ZeroTier networks

## 🌐 Ports

| Port  | Purpose         |
|-------|-----------------|
| 5432  | PostgreSQL DB   |
| 9993  | ZeroTier UDP    |
| 3000  | ZTNet Web UI    |

## 📦 Installation

1. Add repo:  
   `https://github.com/ChristoffBo/homeassistant`

2. Install `zerotiercontroller` from Add-on Store.

3. Start the add-on and go to:  
   `http://homeassistant.local:3000`

## 🔐 Default Credentials

- **Username:** cbothma  
- **Email:** notify@bothmainc.co.za  
- **Password:** Lilly@057!

## 🛠 Paths

- `/data/postgres` – PostgreSQL data
- `/data/zerotier-one` – ZT identity/config

## 🧠 Notes

- Change secrets after setup!
- Port `9993/udp` must be open for ZeroTier to function.

---

🎨 Icon: [ZTNet](https://github.com/sinamics/ztnet)
