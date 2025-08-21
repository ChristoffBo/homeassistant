# 🧩 DNSCrypt Proxy — Home Assistant Add-on
This add-on runs **dnscrypt-proxy** inside Home Assistant. It exposes a DNS listener on **UDP/TCP 5353** (no ingress/web UI). It fetches official resolver/relay lists, applies your **Options** to generate `dnscrypt-proxy.toml`, and starts encrypted DNS (DoH/DNSCrypt) for upstream queries from your LAN DNS (e.g., Technitium).

## What it is and what it is used for
**dnscrypt-proxy** encrypts DNS (DoH/DNSCrypt), enforces resolver policies (DNSSEC, no-logs, (no)-filter), and can use **anonymized relays** to unlink your IP from the resolver you query.  
Running it in **Home Assistant** lets you keep your local blocker (e.g., Technitium) and still send upstream queries over encrypted, privacy-respecting transports.

## Features
- Encrypted DNS (**DoH/DNSCrypt**) on **:5353/udp,tcp**
- **No-logs / DNSSEC / (no)-filter** resolver requirements
- **Anonymized DNS** via relays (optional)
- Uses official resolver & relay lists (signed)
- Caching & timeouts configurable via **Options**
- Defaults include **Cloudflare, Quad9, AdGuard, OpenDNS, Mullvad**

## First-Time Setup (required)
No filesystem prep is required. Install the add-on, open **Configuration**, review **Options**, then **Start**.

Optional maintenance/reset (only when troubleshooting lists or config):
rm -f /config/public-resolvers.md /config/relays.md /config/dnscrypt-proxy.toml

## Why dnscrypt-proxy?
- **Privacy & integrity** — encrypts DNS, supports DNSSEC, optional **anonymized** routing.  
- **Flexible policy** — choose resolvers by no-logs/(no)-filter/latency.  
- **Lightweight & reliable** — minimal footprint; fits HA’s add-on model cleanly.

## Default First User
Not applicable — **no web UI or user accounts**. DNS runs as a service on port **5353**.

## SECURITY WARNING
If you enable filtering resolvers (e.g., Quad9/AdGuard), understand they **block categories** by design. Keep `"require_nofilter": false` only if you explicitly want that behavior. Review your resolver choices and policies before production use.

## Force Fresh First Boot
To fully reset state and regenerate everything on next start:
rm -f /config/public-resolvers.md /config/relays.md /config/dnscrypt-proxy.toml

## Access
- **DNS listener**: udp/tcp://<home-assistant>:5353  
- **How to use**: point your upstream DNS (e.g., Technitium → Settings → Upstream DNS) to the HA host’s IP on **5353**.  
  - Example: 127.0.0.1:5353 if co-located, or <HA_HOST_IP>:5353 over the network.