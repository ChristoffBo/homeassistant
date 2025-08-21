# DNSCrypt Proxy (klutchell) — Home Assistant Add-on

This add-on wraps the community image `klutchell/dnscrypt-proxy` and exposes configuration via the Home Assistant Add-on Options UI.

## Features
- Encrypted DNS (DNSCrypt / DoH)
- Anonymized DNS with relays
- DNSSEC enforcement
- Configurable cache, timeouts, fallback
- Listens on 5353 (TCP/UDP) by default

## Default Options
```json
{
  "listen_address": "0.0.0.0",
  "listen_port": 5353,
  "server_names": ["quad9-doh-ip4-port443", "cloudflare", "cisco"],
  "relays": ["anon-cs-de", "anon-cs-fr", "anon-scaleway-nl"],
  "require_dnssec": true,
  "require_nolog": true,
  "require_nofilter": true,
  "cache": true,
  "cache_size": 4096,
  "cache_min_ttl": 240,
  "cache_max_ttl": 86400,
  "timeout_ms": 5000,
  "keepalive_sec": 30,
  "fallback_resolver": "9.9.9.9:53",
  "log_level": 2
}