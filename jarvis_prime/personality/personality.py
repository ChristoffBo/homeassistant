#!/usr/bin/env python3
# /app/personality.py — TRULY MASSIVE with 1000+ unique phrases per persona
# Makes Lexi indistinguishable from LLM output

import random, os, importlib, re, time
from typing import List, Dict, Optional, Tuple

_TRANSPORT_TAG_RE = re.compile(
    r'^(?:\s*\[(?:smtp|proxy|gotify|apprise|email|poster|webhook|imap|ntfy|pushover|telegram)\]\s*)+',
    flags=re.IGNORECASE
)
def strip_transport_tags(text: str) -> str:
    if not text:
        return ""
    try:
        t = _TRANSPORT_TAG_RE.sub("", text)
        t = re.sub(r'\s*\[(?:smtp|proxy|gotify|apprise|email|poster|webhook|imap|ntfy|pushover|telegram)\]\s*', ' ', t, flags=re.I)
        return re.sub(r'\s{2,}', ' ', t).strip()
    except:
        return text

def _daypart(now_ts: Optional[float] = None) -> str:
    try:
        t = time.localtime(now_ts or time.time())
        h = t.tm_hour
        if 0 <= h < 5:
            return "early_morning"
        if 5 <= h < 11:
            return "morning"
        if 11 <= h < 17:
            return "afternoon"
        if 17 <= h < 21:
            return "evening"
        return "late_night"
    except:
        return "afternoon"

def _intensity() -> float:
    try:
        v = float(os.getenv("PERSONALITY_INTENSITY", "1.0"))
        return max(0.6, min(2.0, v))
    except Exception:
        return 1.0

PERSONAS = ["dude", "chick", "nerd", "rager", "comedian", "action", "jarvis", "ops", "tappit"]

ALIASES: Dict[str, str] = {
    "the dude":"dude","lebowski":"dude","bill":"dude","ted":"dude","dude":"dude",
    "paris":"chick","paris hilton":"chick","chick":"chick","glam":"chick","elle":"chick","elle woods":"chick",
    "nerd":"nerd","sheldon":"nerd","sheldon cooper":"nerd","cooper":"nerd","moss":"nerd","it crowd":"nerd",
    "rager":"rager","angry":"rager","rage":"rager","sam":"rager","joe":"rager","pesci":"rager","jackson":"rager",
    "comedian":"comedian","leslie":"comedian","deadpan":"comedian","nielsen":"comedian","meta":"comedian",
    "action":"action","sly":"action","arnie":"action","arnold":"action","schwarzenegger":"action","willis":"action",
    "jarvis":"jarvis","ai":"jarvis","majordomo":"jarvis","hal":"jarvis","hal 9000":"jarvis",
    "ops":"ops","neutral":"ops","no persona":"ops",
    "tappit":"tappit","tapit":"tappit","rev":"tappit","ref":"tappit","ref-ref":"tappit"
}

EMOJIS = {
    "dude": ["🌴","🕶️","🍹","🎳","🧘","🤙"],
    "chick":["💅","✨","💖","💛","🛍️","💋"],
    "nerd":["🤓","🔬","🧪","🧠","⌨️","📚"],
    "rager":["🤬","🔥","💥","🗯️","⚡","🚨"],
    "comedian":["😑","😂","🎭","🙃","🃏","🥸"],
    "action":["💪","🧨","🛡️","🚁","🏹","🗡️"],
    "jarvis":["🤖","🧠","🎩","🪄","📊","🛰️"],
    "ops":["⚙️","📊","🧰","✅","🔎","🗂️"],
    "tappit":["🏴","🛠️","🚗","🔧","🛞","🇿🇦"]
}

def _maybe_emoji(key: str, with_emoji: bool) -> str:
    if not with_emoji:
        return ""
    try:
        bank = EMOJIS.get(key) or []
        return f" {random.choice(bank)}" if bank else ""
    except:
        return ""

def _canon(name: str) -> str:
    try:
        n = (name or "").strip().lower()
        key = ALIASES.get(n, n)
        return key if key in PERSONAS else "ops"
    except:
        return "ops"

def _extract_smart_context(subject: str = "", body: str = "") -> Dict:
    """Extract context from message with enhanced intelligence"""
    try:
        text = f"{subject} {body}".lower()
        
        services = {
            # Media automation (*arr stack)
            "sonarr": "sonarr" in text,
            "radarr": "radarr" in text,
            "lidarr": "lidarr" in text,
            "bazarr": "bazarr" in text,
            "prowlarr": "prowlarr" in text,
            "readarr": "readarr" in text,
            "whisparr": "whisparr" in text,
            "cleanuperr": "cleanuperr" in text,
            "huntarr": "huntarr" in text,
            "overseerr": "overseerr" in text or "jellyseerr" in text,
            "requestrr": "requestrr" in text,
            "tautulli": "tautulli" in text,
            
            # Media servers & players
            "plex": "plex" in text,
            "emby": "emby" in text,
            "jellyfin": "jellyfin" in text,
            "kodi": "kodi" in text,
            
            # Download clients
            "qbittorrent": "qbittorrent" in text or "qbit" in text,
            "deluge": "deluge" in text,
            "transmission": "transmission" in text,
            "rtorrent": "rtorrent" in text or "rutorrent" in text,
            "sabnzbd": "sabnzbd" in text or "sabnzb" in text or "sab" in text,
            "nzbget": "nzbget" in text,
            
            # Reverse proxies & web servers
            "nginx": "nginx" in text,
            "traefik": "traefik" in text,
            "caddy": "caddy" in text,
            "haproxy": "haproxy" in text,
            "apache": "apache" in text or "httpd" in text,
            "swag": "swag" in text or "nginx proxy manager" in text or "npm" in text,
            
            # Dashboards & management
            "homepage": "homepage" in text,
            "homarr": "homarr" in text,
            "heimdall": "heimdall" in text,
            "organizr": "organizr" in text,
            "flame": "flame" in text,
            "dashy": "dashy" in text,
            "portainer": "portainer" in text,
            "yacht": "yacht" in text,
            "dockge": "dockge" in text,
            "cockpit": "cockpit" in text,
            
            # DNS & network
            "pihole": "pihole" in text or "pi-hole" in text,
            "adguard": "adguard" in text,
            "unbound": "unbound" in text,
            "technitium": "technitium" in text,
            "cloudflared": "cloudflared" in text or "cloudflare tunnel" in text,
            
            # VPN & remote access
            "wireguard": "wireguard" in text or "wg-easy" in text,
            "openvpn": "openvpn" in text,
            "tailscale": "tailscale" in text,
            "zerotier": "zerotier" in text,
            "netbird": "netbird" in text,
            "guacamole": "guacamole" in text,
            "meshcentral": "meshcentral" in text,
            
            # Monitoring & observability
            "grafana": "grafana" in text,
            "prometheus": "prometheus" in text,
            "uptime-kuma": "uptime kuma" in text or "kuma" in text or "uptime-kuma" in text,
            "netdata": "netdata" in text,
            "glances": "glances" in text,
            "scrutiny": "scrutiny" in text,
            "healthchecks": "healthchecks" in text or "healthcheck" in text,
            "changedetection": "changedetection" in text or "change detection" in text,
            "speedtest-tracker": "speedtest tracker" in text or "speedtest-tracker" in text,
            
            # Notifications
            "gotify": "gotify" in text,
            "ntfy": "ntfy" in text,
            "pushover": "pushover" in text,
            "apprise": "apprise" in text,
            
            # Git & code
            "gitea": "gitea" in text,
            "forgejo": "forgejo" in text,
            "gitlab": "gitlab" in text,
            "gogs": "gogs" in text,
            "code-server": "code-server" in text or "vscode server" in text,
            
            # CI/CD
            "drone": "drone" in text,
            "woodpecker": "woodpecker" in text,
            "jenkins": "jenkins" in text,
            "semaphore": "semaphore" in text,
            
            # Databases
            "postgresql": "postgresql" in text or "postgres" in text,
            "mysql": "mysql" in text or "mariadb" in text,
            "mongodb": "mongodb" in text or "mongo" in text,
            "redis": "redis" in text,
            "influxdb": "influxdb" in text or "influx" in text,
            
            # Password managers
            "vaultwarden": "vaultwarden" in text or "bitwarden" in text,
            "passbolt": "passbolt" in text,
            "psono": "psono" in text,
            
            # File sync & storage
            "nextcloud": "nextcloud" in text,
            "syncthing": "syncthing" in text,
            "seafile": "seafile" in text,
            "filebrowser": "filebrowser" in text or "file browser" in text,
            "miniserve": "miniserve" in text,
            "alist": "alist" in text,
            
            # Photos
            "immich": "immich" in text,
            "photoprism": "photoprism" in text,
            "lychee": "lychee" in text,
            "piwigo": "piwigo" in text,
            
            # Documents & notes
            "paperless": "paperless" in text or "paperless-ngx" in text,
            "bookstack": "bookstack" in text,
            "outline": "outline" in text,
            "trilium": "trilium" in text,
            "hedgedoc": "hedgedoc" in text or "codimd" in text,
            "joplin": "joplin" in text,
            "obsidian": "obsidian" in text,
            
            # RSS & reading
            "freshrss": "freshrss" in text or "fresh rss" in text,
            "miniflux": "miniflux" in text,
            "tt-rss": "tt-rss" in text or "tiny tiny rss" in text,
            "wallabag": "wallabag" in text,
            "linkwarden": "linkwarden" in text,
            
            # Bookmarks
            "linkding": "linkding" in text,
            "shiori": "shiori" in text,
            "shlink": "shlink" in text,
            
            # Home automation
            "homeassistant": "home assistant" in text or "homeassistant" in text or "hass" in text,
            "nodered": "node-red" in text or "nodered" in text,
            "zigbee2mqtt": "zigbee2mqtt" in text or "z2m" in text,
            "mosquitto": "mosquitto" in text or "mqtt" in text,
            
            # Infrastructure
            "docker": "docker" in text or "container" in text or "compose" in text,
            "kubernetes": "kubernetes" in text or "k8s" in text or "k3s" in text,
            "proxmox": "proxmox" in text or "pve" in text or "qemu" in text or "kvm" in text,
            "unraid": "unraid" in text or "array" in text or "parity" in text or "godzilla" in text,
            "lxc": "lxc" in text or "lxd" in text or "incus" in text,
            "truenas": "truenas" in text,
            
            # Testing
            "speedtest": "speedtest" in text or "speed test" in text or "bandwidth test" in text,
            
            # Generic categories
            "database": any(db in text for db in ["sql", "database"]),
            "backup": "backup" in text or "snapshot" in text or "archive" in text or "restic" in text or "borg" in text or "duplicati" in text,
            "network": "network" in text or "dns" in text or "proxy" in text or "firewall" in text,
            "storage": any(stor in text for stor in ["disk", "storage", "mount", "volume", "raid", "zfs", "btrfs", "nfs", "smb", "cifs"]),
            "monitoring": "monitor" in text or "health" in text or "check" in text or "analytics" in text,
            "certificate": "certificate" in text or "cert" in text or "ssl" in text or "tls" in text or "acme" in text or "letsencrypt" in text,
            "email": any(e in text for e in ["email", "smtp", "imap", "mail", "postfix", "sendmail"]),
            "notification": "notification" in text or "alert" in text,
            "vpn": "vpn" in text,
            "media": any(m in text for m in ["media", "movie", "tv", "episode", "download", "torrent", "usenet", "music", "album", "artist", "subtitle"]),
            "automation": any(a in text for a in ["automation", "script", "cron", "scheduled", "workflow", "ansible", "apt", "update", "upgrade", "patch", "yum", "dnf", "pacman"]),
            "security": any(s in text for s in ["security", "auth", "oauth", "ldap", "fail2ban", "crowdsec", "authelia", "authentik"]),
            
            # Jarvis modules
            "orchestrator": "orchestrator" in text or "playbook" in text,
            "sentinel": "sentinel" in text or "service monitor" in text or "watchdog" in text,
            "jarvis": "jarvis" in text or "llm" in text or "ai" in text,
        }
        active_services = [k for k, v in services.items() if v]
        
        actions = {
            "completed": any(w in text for w in ["completed", "finished", "done", "success", "passed", "ok", "resolved", "fixed", "downloaded", "grabbed", "imported", "renamed"]),
            "started": any(w in text for w in ["started", "beginning", "initiated", "launching", "starting", "deploying"]),
            "failed": any(w in text for w in ["failed", "error", "failure", "crashed", "down", "broken", "dead"]),
            "warning": any(w in text for w in ["warning", "caution", "degraded", "slow", "timeout", "latency"]),
            "updated": any(w in text for w in ["updated", "upgraded", "patched", "modified", "changed", "new version"]),
            "restarted": any(w in text for w in ["restarted", "rebooted", "cycled", "restart", "reload"]),
            "connected": any(w in text for w in ["connected", "online", "up", "available", "responding", "alive"]),
            "disconnected": any(w in text for w in ["disconnected", "offline", "down", "unavailable", "unreachable", "dead"]),
            "stopped": any(w in text for w in ["stopped", "halted", "terminated", "killed", "shutdown"]),
            "scaling": any(w in text for w in ["scaling", "scaled", "replicas", "instances", "capacity"]),
            "migrating": any(w in text for w in ["migrating", "migration", "moving", "transferring"]),
        }
        active_action = next((k for k, v in actions.items() if v), "status")
        
        urgency = 0
        if any(w in text for w in ["critical", "emergency", "urgent", "immediate", "sev1", "p1"]):
            urgency = 8
        elif any(w in text for w in ["down", "offline", "failed", "error", "crash", "dead"]):
            urgency = 6
        elif any(w in text for w in ["warning", "degraded", "slow", "timeout", "latency"]):
            urgency = 3
        elif any(w in text for w in ["info", "notice", "update", "completed", "success"]):
            urgency = 1
        
        return {
            "services": active_services,
            "primary_service": active_services[0] if active_services else None,
            "action": active_action,
            "urgency": urgency,
            "daypart": _daypart(),
            "has_numbers": bool(re.search(r'\d+', text)),
            "has_percentage": "%" in text or "percent" in text,
            "time_sensitive": any(w in text for w in ["now", "asap", "urgent", "immediate", "critical"]),
        }
    except:
        return {
            "services": [], "primary_service": None, "action": "status",
            "urgency": 0, "daypart": "afternoon", "has_numbers": False,
            "has_percentage": False, "time_sensitive": False
        }


# MASSIVE GREETING BANKS - 30+ per persona per daypart - MORE NATURAL AND VARIED
_GREETINGS = {
    "early_morning": {
        "jarvis": [
            "Early morning dispatch", "Pre-dawn operations brief", "Night watch concluding", "First light protocols engaged",
            "Dawn service commencing", "Early hours coordination active", "Morning preparation sequence", "Pre-dawn briefing ready",
            "Early service protocols", "Dawn operations underway", "Night shift transition", "Morning protocols initiating",
            "Early coordination active", "Pre-dawn status update", "First light operations", "Dawn briefing prepared",
            "Early morning brief", "Night watch complete", "Morning service beginning", "Pre-dawn ready status",
            "Early hours report", "Dawn transition active", "Morning readiness confirmed", "Pre-dawn systems check",
            "Early operations brief", "Dawn protocols engaged", "Morning coordination starting", "Pre-dawn situation report",
            "Early status update", "Dawn service active", "Morning operations commencing"
        ],
        "dude": [
            "Early vibes man", "Dawn patrol checking in", "Morning brew time", "Sunrise session starting", "Early flow going",
            "Pre-dawn cruise mode", "Morning mellow vibes", "Dawn chill activated", "Early zen happening", "Sunrise mode engaged",
            "Morning easy vibes", "Pre-dawn flowing", "Early morning flow", "Dawn surfing time", "Morning cosmic vibes",
            "Sunrise rolling in", "Early cruise mode", "Pre-dawn mellow", "Morning waves coming", "Dawn peaceful vibes",
            "Early morning groove", "Dawn easy mode", "Morning serenity", "Pre-dawn smooth sailing", "Early vibes flowing",
            "Dawn tranquility", "Morning calm waters", "Pre-dawn relaxation", "Early morning peace", "Dawn meditation mode",
            "Morning flow state"
        ],
        "chick": [
            "Rise and shine gorgeous", "Early bird mode activated", "Morning glow starting", "Dawn glamour time", "Early sparkle happening",
            "First light fabulous", "Morning fresh vibes", "Dawn beauty mode", "Early elegance", "Sunrise gorgeous",
            "Morning radiance", "Pre-dawn stunning", "Early morning glam", "Dawn sophistication", "Morning chicness",
            "Sunrise elegance", "Early morning fab", "Pre-dawn beauty", "Morning grace", "Dawn perfection",
            "Early sparkle time", "Morning glamour mode", "Pre-dawn gorgeous", "Early elegance vibes", "Dawn beauty time",
            "Morning sophistication", "Pre-dawn chicness", "Early morning stunning", "Dawn radiance", "Morning perfection mode",
            "Early glow time"
        ],
        "nerd": [
            "Early morning data check", "Pre-dawn diagnostics running", "Night cycle analysis complete", "First light metrics compiled",
            "Dawn telemetry active", "Early system validation", "Morning parameter review", "Pre-dawn calculations ready",
            "Early analysis phase", "Dawn data processing", "Morning algorithm check", "Pre-dawn verification complete",
            "Early morning metrics", "Dawn system analysis", "Morning diagnostic sweep", "Pre-dawn data compilation",
            "Early telemetry review", "Dawn parameter validation", "Morning system audit", "Pre-dawn metrics analysis",
            "Early diagnostic phase", "Dawn verification protocols", "Morning data integrity check", "Pre-dawn system validation",
            "Early morning analysis", "Dawn computational review", "Morning metrics compiled", "Pre-dawn algorithm check",
            "Early data synthesis", "Dawn system verification", "Morning diagnostic complete"
        ],
        "rager": [
            "Early morning shit", "Too damn early", "Dawn bullshit alert", "Sunrise annoyance", "Early fucking hours",
            "Pre-dawn goddamn updates", "Morning crap incoming", "Dawn irritation mode", "Early morning hell",
            "Sunrise clusterfuck potential", "Morning horseshit", "Pre-dawn nonsense", "Early goddamn updates",
            "Dawn fucking report", "Morning pain incoming", "Pre-dawn aggravation", "Early morning bullshit",
            "Dawn disaster watch", "Morning fucking chaos", "Pre-dawn headache", "Early goddamn problems",
            "Dawn clusterfuck watch", "Morning shit show potential", "Pre-dawn annoyance", "Early fucking nonsense",
            "Dawn bullshit incoming", "Morning goddamn updates", "Pre-dawn irritation", "Early shit alert",
            "Dawn pain report", "Morning hell incoming"
        ],
        "comedian": [
            "Unreasonably early update", "Dawn approaches reluctantly", "Morning arrives uninvited", "Sunrise happening allegedly",
            "Early hours protest", "Pre-dawn comedy hour", "Morning confusion begins", "Dawn bewilderment active",
            "Early morning absurdity", "Sunrise irony detected", "Morning sarcasm mode", "Pre-dawn wit engaged",
            "Early hours comedy", "Dawn satire active", "Morning deadpan ready", "Pre-dawn humor engaged",
            "Early morning irony", "Dawn comedy protocols", "Morning wit activated", "Pre-dawn sarcasm",
            "Early absurdity alert", "Dawn humor mode", "Morning deadpan engaged", "Pre-dawn comedy",
            "Early satire active", "Dawn wit protocols", "Morning irony detected", "Pre-dawn absurdity",
            "Early comedy hour", "Dawn sarcasm mode", "Morning humor engaged"
        ],
        "action": [
            "Early morning recon", "Pre-dawn mission brief", "Night ops concluding", "First light sitrep",
            "Dawn patrol active", "Early tactical update", "Morning combat readiness", "Pre-dawn field report",
            "Early mission status", "Dawn operations brief", "Morning tactical sitrep", "Pre-dawn readiness check",
            "Early combat status", "Dawn field report", "Morning mission brief", "Pre-dawn tactical update",
            "Early operations sitrep", "Dawn readiness status", "Morning field brief", "Pre-dawn mission status",
            "Early tactical report", "Dawn combat brief", "Morning operations sitrep", "Pre-dawn field status",
            "Early mission update", "Dawn tactical brief", "Morning combat sitrep", "Pre-dawn operations",
            "Early field report", "Dawn mission status", "Morning tactical readiness"
        ],
        "ops": [
            "Early morning status", "Pre-dawn operational brief", "Night shift handover", "First light update",
            "Dawn operations report", "Early system status", "Morning ops brief", "Pre-dawn status check",
            "Early operational update", "Dawn system report", "Morning status brief", "Pre-dawn ops update",
            "Early system brief", "Dawn operational status", "Morning ops update", "Pre-dawn system check",
            "Early status report", "Dawn ops brief", "Morning operational update", "Pre-dawn status report",
            "Early ops check", "Dawn system brief", "Morning status update", "Pre-dawn operational report",
            "Early system update", "Dawn status brief", "Morning ops report", "Pre-dawn system status",
            "Early operational brief", "Dawn status update", "Morning system report"
        ],
        "tappit": [
            "Vroeg more bru", "Dawn shift boet", "Early morning howzit", "Pre-dawn lekker time", "Morning sharp sharp",
            "Early vibes né", "Dawn checking in hey", "Morning sorted boet", "Pre-dawn all good", "Early lekker vibes",
            "Dawn sharp time", "Morning howzit bru", "Pre-dawn checking in", "Early sorted hey", "Dawn lekker mode",
            "Morning sharp boet", "Pre-dawn vibes né", "Early howzit time", "Dawn all good bru", "Morning lekker sharp",
            "Pre-dawn sorted", "Early sharp vibes", "Dawn howzit hey", "Morning lekker time", "Pre-dawn sharp bru",
            "Early all good", "Dawn sorted né", "Morning vibes boet", "Pre-dawn lekker", "Early sharp sharp"
        ]
    },
    "morning": {
        "jarvis": [
            "Good morning brief", "Morning operations underway", "AM protocols active", "Morning coordination ready",
            "Daylight operations commenced", "Morning service active", "AM briefing prepared", "Morning status update",
            "Morning operations brief", "AM coordination active", "Daylight protocols engaged", "Morning readiness confirmed",
            "AM operations underway", "Morning service protocols", "Daylight briefing ready", "Morning coordination brief",
            "AM status update", "Morning operations ready", "Daylight service active", "Morning protocols engaged",
            "AM briefing underway", "Morning coordination status", "Daylight operations brief", "Morning service ready",
            "AM protocols prepared", "Morning operations status", "Daylight coordination active", "Morning briefing complete",
            "AM service underway", "Morning readiness brief", "Daylight protocols ready", "Morning operations engaged"
        ],
        "dude": [
            "Morning vibes flowing", "Good morning groove", "AM chill mode", "Morning easy vibes", "Day starting smooth",
            "Morning mellow time", "AM flow active", "Good morning zen", "Morning cruise mode", "Day beginning easy",
            "Morning peaceful vibes", "AM smooth sailing", "Good morning flow", "Morning relaxed mode", "Day starting chill",
            "Morning tranquil vibes", "AM easy mode", "Good morning mellow", "Morning serene time", "Day flowing smooth",
            "Morning cosmic vibes", "AM zen mode", "Good morning peaceful", "Morning calm waters", "Day cruising easy",
            "Morning harmonious vibes", "AM chill time", "Good morning smooth", "Morning balanced mode", "Day starting zen",
            "Morning laid back vibes", "AM flow time", "Good morning relaxed", "Morning easy sailing"
        ],
        "chick": [
            "Good morning gorgeous", "Morning glam time", "AM fabulous mode", "Morning sparkle active", "Day looking stunning",
            "Morning elegance vibes", "AM beauty time", "Good morning fab", "Morning radiant mode", "Day starting gorgeous",
            "Morning sophisticated vibes", "AM glam mode", "Good morning elegant", "Morning chic time", "Day beginning fab",
            "Morning stunning vibes", "AM sparkle mode", "Good morning radiant", "Morning graceful time", "Day looking elegant",
            "Morning beautiful vibes", "AM fab time", "Good morning chic", "Morning lovely mode", "Day starting radiant",
            "Morning glamorous vibes", "AM elegant time", "Good morning stunning", "Morning gorgeous mode", "Day beginning beautiful",
            "Morning exquisite vibes", "AM radiant time", "Good morning lovely", "Morning fabulous mode"
        ],
        "nerd": [
            "Morning data compiled", "AM diagnostics complete", "Good morning analysis ready", "Morning metrics validated",
            "Day systems optimal", "Morning parameters checked", "AM calculations ready", "Good morning diagnostics", "Morning telemetry active",
            "Day optimization running", "Morning algorithms verified", "AM data processed", "Good morning metrics", "Morning validation complete",
            "Day analysis underway", "Morning systems verified", "AM parameters ready", "Good morning telemetry", "Morning diagnostics validated",
            "Day metrics compiled", "Morning data verified", "AM analysis complete", "Good morning systems", "Morning parameters optimal",
            "Day calculations ready", "Morning verification done", "AM diagnostics ready", "Good morning data", "Morning metrics processed",
            "Day telemetry active", "Morning algorithms ready", "AM validation complete", "Good morning analysis"
        ],
        "rager": [
            "Morning goddamn updates", "AM bullshit incoming", "Good morning clusterfuck", "Morning shit show", "Day problems starting",
            "Morning fucking chaos", "AM disaster watch", "Good morning pain", "Morning goddamn issues", "Day horseshit active",
            "Morning nonsense alert", "AM crap incoming", "Good morning hell", "Morning pain train", "Day bullshit detected",
            "Morning fucking problems", "AM chaos mode", "Good morning disaster", "Morning goddamn mess", "Day shit incoming",
            "Morning headache alert", "AM bullshit mode", "Good morning clusterfuck", "Morning fucking issues", "Day pain starting",
            "Morning disaster watch", "AM goddamn problems", "Good morning chaos", "Morning shit alert", "Day hell incoming",
            "Morning clusterfuck mode", "AM pain train", "Good morning bullshit", "Morning goddamn chaos"
        ],
        "comedian": [
            "Morning arrives punctually", "AM comedy engaged", "Good morning absurdity", "Morning irony detected", "Day satire active",
            "Morning wit protocols", "AM humor mode", "Good morning deadpan", "Morning sarcasm ready", "Day comedy time",
            "Morning absurdity alert", "AM irony active", "Good morning satire", "Morning deadpan mode", "Day wit engaged",
            "Morning comedy protocols", "AM sarcasm ready", "Good morning humor", "Morning wit active", "Day irony detected",
            "Morning satire mode", "AM deadpan engaged", "Good morning comedy", "Morning humor protocols", "Day absurdity alert",
            "Morning irony mode", "AM wit active", "Good morning sarcasm", "Morning comedy ready", "Day deadpan time",
            "Morning humor engaged", "AM satire mode", "Good morning wit", "Morning absurdity protocols"
        ],
        "action": [
            "Morning sitrep ready", "AM tactical brief", "Good morning recon", "Morning mission status", "Day operations active",
            "Morning combat readiness", "AM field report", "Good morning tactical", "Morning ops brief", "Day mission underway",
            "Morning readiness check", "AM combat status", "Good morning field", "Morning tactical update", "Day operations brief",
            "Morning mission ready", "AM ops status", "Good morning combat", "Morning field brief", "Day tactical ready",
            "Morning operations sitrep", "AM mission brief", "Good morning readiness", "Morning combat brief", "Day field status",
            "Morning tactical sitrep", "AM readiness check", "Good morning ops", "Morning mission brief", "Day combat ready",
            "Morning field sitrep", "AM tactical status", "Good morning mission", "Morning ops ready"
        ],
        "ops": [
            "Morning status update", "AM operational brief", "Good morning systems", "Morning ops report", "Day operations ready",
            "Morning system status", "AM ops brief", "Good morning operational", "Morning status check", "Day systems active",
            "Morning operational update", "AM system brief", "Good morning ops", "Morning status report", "Day operational ready",
            "Morning system brief", "AM status update", "Good morning system", "Morning ops update", "Day status active",
            "Morning operational brief", "AM ops report", "Good morning status", "Morning system update", "Day ops ready",
            "Morning status brief", "AM operational report", "Good morning ops brief", "Morning system report", "Day status ready",
            "Morning ops status", "AM system update", "Good morning operational brief", "Morning status ready"
        ],
        "tappit": [
            "Morning howzit bru", "AM lekker time", "Good morning boet", "Morning sharp sharp", "Day sorted né",
            "Morning all good hey", "AM vibes bru", "Good morning sharp", "Morning lekker vibes", "Day howzit time",
            "Morning sorted boet", "AM sharp time", "Good morning lekker", "Morning howzit né", "Day vibes bru",
            "Morning all good bru", "AM lekker sharp", "Good morning sorted", "Morning sharp boet", "Day lekker time",
            "Morning vibes né", "AM howzit bru", "Good morning all good", "Morning lekker hey", "Day sharp sharp",
            "Morning sharp né", "AM sorted bru", "Good morning howzit", "Morning vibes boet", "Day lekker vibes",
            "Morning all sorted", "AM sharp boet", "Good morning vibes", "Morning howzit sharp"
        ]
    },
    "afternoon": {
        "jarvis": [
            "Afternoon dispatch", "PM operations brief", "Midday coordination", "Afternoon status update", "PM protocols active",
            "Afternoon service brief", "Midday operations ready", "PM coordination underway", "Afternoon briefing prepared", "Midday status active",
            "PM service protocols", "Afternoon operations status", "Midday briefing ready", "PM coordination brief", "Afternoon readiness confirmed",
            "Midday service active", "PM operations update", "Afternoon coordination status", "Midday protocols engaged", "PM briefing underway",
            "Afternoon service ready", "Midday coordination active", "PM status update", "Afternoon operations brief", "Midday readiness status",
            "PM service underway", "Afternoon briefing complete", "Midday operations engaged", "PM coordination ready", "Afternoon protocols prepared",
            "Midday service brief", "PM readiness confirmed", "Afternoon status ready", "Midday operations brief"
        ],
        "dude": [
            "Afternoon vibes", "PM chill time", "Midday flow", "Afternoon easy mode", "PM smooth sailing",
            "Midday mellow vibes", "Afternoon cruise", "PM zen time", "Midday peaceful", "Afternoon relaxed vibes",
            "PM flow mode", "Midday easy vibes", "Afternoon smooth time", "PM mellow mode", "Midday chill vibes",
            "Afternoon zen mode", "PM peaceful time", "Midday cruise vibes", "Afternoon easy sailing", "PM relaxed mode",
            "Midday smooth vibes", "Afternoon flow time", "PM chill mode", "Midday zen vibes", "Afternoon mellow time",
            "PM easy vibes", "Midday peaceful mode", "Afternoon cruise time", "PM smooth vibes", "Midday relaxed mode",
            "Afternoon chill time", "PM zen vibes", "Midday flow mode", "Afternoon peaceful vibes"
        ],
        "chick": [
            "Afternoon gorgeous", "PM glam time", "Midday fabulous", "Afternoon sparkle", "PM elegant mode",
            "Midday stunning vibes", "Afternoon beauty time", "PM radiant mode", "Midday chic vibes", "Afternoon fab time",
            "PM gorgeous mode", "Midday elegant vibes", "Afternoon radiant time", "PM fabulous mode", "Midday sparkle vibes",
            "Afternoon chic time", "PM stunning mode", "Midday gorgeous vibes", "Afternoon elegant vibes", "PM radiant time",
            "Midday fab mode", "Afternoon sparkle time", "PM chic vibes", "Midday radiant mode", "Afternoon gorgeous time",
            "PM elegant vibes", "Midday fabulous mode", "Afternoon stunning time", "PM sparkle mode", "Midday chic time",
            "Afternoon radiant vibes", "PM gorgeous time", "Midday elegant mode", "Afternoon fab vibes"
        ],
        "nerd": [
            "Afternoon diagnostics", "PM data analysis", "Midday metrics", "Afternoon telemetry", "PM systems check",
            "Midday validation", "Afternoon parameters", "PM calculations", "Midday diagnostics", "Afternoon data compiled",
            "PM metrics ready", "Midday analysis complete", "Afternoon verification", "PM telemetry active", "Midday systems optimal",
            "Afternoon algorithms", "PM parameters checked", "Midday data processed", "Afternoon metrics validated", "PM diagnostics complete",
            "Midday verification done", "Afternoon systems verified", "PM analysis ready", "Midday telemetry processed", "Afternoon data verified",
            "PM validation complete", "Midday metrics compiled", "Afternoon diagnostics ready", "PM systems verified", "Midday parameters optimal",
            "Afternoon telemetry active", "PM data processed", "Midday algorithms ready", "Afternoon verification complete"
        ],
        "rager": [
            "Afternoon bullshit", "PM goddamn updates", "Midday clusterfuck", "Afternoon shit show", "PM fucking chaos",
            "Midday disaster", "Afternoon pain train", "PM horseshit", "Midday goddamn problems", "Afternoon hell incoming",
            "PM bullshit mode", "Midday fucking issues", "Afternoon chaos alert", "PM disaster watch", "Midday pain incoming",
            "Afternoon goddamn mess", "PM clusterfuck mode", "Midday shit alert", "Afternoon fucking problems", "PM hell mode",
            "Midday bullshit detected", "Afternoon disaster mode", "PM goddamn chaos", "Midday clusterfuck alert", "Afternoon shit incoming",
            "PM pain mode", "Midday fucking chaos", "Afternoon bullshit watch", "PM goddamn problems", "Midday disaster incoming",
            "Afternoon hell mode", "PM clusterfuck alert", "Midday pain train", "Afternoon goddamn bullshit"
        ],
        "comedian": [
            "Afternoon irony", "PM comedy hour", "Midday absurdity", "Afternoon satire", "PM deadpan mode",
            "Midday wit active", "Afternoon humor", "PM sarcasm ready", "Midday comedy protocols", "Afternoon deadpan time",
            "PM irony detected", "Midday satire mode", "Afternoon wit engaged", "PM absurdity alert", "Midday humor active",
            "Afternoon sarcasm mode", "PM comedy protocols", "Midday deadpan engaged", "Afternoon irony active", "PM satire ready",
            "Midday wit mode", "Afternoon comedy engaged", "PM humor protocols", "Midday absurdity mode", "Afternoon deadpan ready",
            "PM irony mode", "Midday sarcasm active", "Afternoon satire engaged", "PM wit protocols", "Midday comedy ready",
            "Afternoon humor mode", "PM deadpan time", "Midday irony engaged", "Afternoon absurdity protocols"
        ],
        "action": [
            "Afternoon sitrep", "PM tactical brief", "Midday mission status", "Afternoon combat ready", "PM field report",
            "Midday operations brief", "Afternoon readiness check", "PM tactical update", "Midday combat status", "Afternoon mission brief",
            "PM ops sitrep", "Midday readiness status", "Afternoon field brief", "PM combat brief", "Midday tactical sitrep",
            "Afternoon ops status", "PM mission update", "Midday field status", "Afternoon tactical brief", "PM readiness sitrep",
            "Midday combat brief", "Afternoon mission sitrep", "PM field update", "Midday ops status", "Afternoon combat sitrep",
            "PM tactical sitrep", "Midday mission brief", "Afternoon readiness status", "PM ops brief", "Midday tactical status",
            "Afternoon field sitrep", "PM combat status", "Midday readiness brief", "Afternoon tactical status"
        ],
        "ops": [
            "Afternoon status", "PM operational brief", "Midday systems check", "Afternoon ops update", "PM status report",
            "Midday operational status", "Afternoon system brief", "PM ops brief", "Midday status update", "Afternoon operational report",
            "PM system status", "Midday ops update", "Afternoon status brief", "PM operational update", "Midday system brief",
            "Afternoon ops report", "PM status update", "Midday operational brief", "Afternoon system update", "PM ops status",
            "Midday status report", "Afternoon operational status", "PM system brief", "Midday ops brief", "Afternoon status update",
            "PM operational report", "Midday system status", "Afternoon ops status", "PM status brief", "Midday operational update",
            "Afternoon system report", "PM ops update", "Midday status brief", "Afternoon operational brief"
        ],
        "tappit": [
            "Afternoon howzit", "PM lekker bru", "Midday sharp time", "Afternoon sorted", "PM vibes né",
            "Midday all good boet", "Afternoon lekker vibes", "PM sharp sharp", "Midday howzit bru", "Afternoon all sorted",
            "PM lekker time", "Midday sharp boet", "Afternoon vibes né", "PM howzit hey", "Midday sorted bru",
            "Afternoon sharp time", "PM all good né", "Midday lekker sharp", "Afternoon howzit boet", "PM sorted time",
            "Midday vibes bru", "Afternoon lekker sharp", "PM sharp né", "Midday all good", "Afternoon howzit sharp",
            "PM vibes boet", "Midday lekker time", "Afternoon sorted né", "PM sharp bru", "Midday howzit sharp",
            "Afternoon all good bru", "PM lekker né", "Midday sharp time", "Afternoon vibes boet"
        ]
    },
    "evening": {
        "jarvis": [
            "Evening dispatch", "Evening operations brief", "PM coordination active", "Evening status update", "Evening protocols engaged",
            "Evening service brief", "PM operations ready", "Evening coordination status", "PM briefing prepared", "Evening readiness confirmed",
            "PM service protocols", "Evening operations status", "PM briefing ready", "Evening coordination brief", "PM readiness active",
            "Evening service ready", "PM coordination underway", "Evening status brief", "PM operations update", "Evening briefing complete",
            "PM service underway", "Evening coordination ready", "PM status update", "Evening operations brief", "PM readiness status",
            "Evening service active", "PM briefing underway", "Evening readiness brief", "PM coordination status", "Evening protocols ready",
            "PM operations engaged", "Evening service protocols", "PM readiness confirmed", "Evening status ready"
        ],
        "dude": [
            "Evening vibes", "Evening chill time", "PM flow mode", "Evening easy vibes", "Evening mellow time",
            "PM smooth sailing", "Evening zen mode", "PM peaceful vibes", "Evening relaxed time", "PM chill mode",
            "Evening flow vibes", "PM easy mode", "Evening smooth time", "PM mellow vibes", "Evening peaceful mode",
            "PM zen vibes", "Evening cruise time", "PM relaxed mode", "Evening easy sailing", "PM flow time",
            "Evening mellow vibes", "PM smooth time", "Evening chill mode", "PM peaceful mode", "Evening zen vibes",
            "PM easy vibes", "Evening relaxed vibes", "PM cruise mode", "Evening smooth vibes", "PM mellow time",
            "Evening peaceful vibes", "PM zen time", "Evening flow mode", "PM chill vibes"
        ],
        "chick": [
            "Evening gorgeous", "Evening glam time", "PM fabulous mode", "Evening sparkle", "Evening elegant vibes",
            "PM stunning time", "Evening radiant mode", "PM chic vibes", "Evening beauty time", "PM gorgeous mode",
            "Evening fab vibes", "PM elegant time", "Evening radiant vibes", "PM fabulous mode", "Evening chic time",
            "PM sparkle mode", "Evening stunning vibes", "PM radiant time", "Evening gorgeous time", "PM elegant vibes",
            "Evening fabulous vibes", "PM chic mode", "Evening sparkle time", "PM gorgeous vibes", "Evening elegant time",
            "PM radiant mode", "Evening chic vibes", "PM fabulous time", "Evening stunning time", "PM sparkle vibes",
            "Evening radiant time", "PM gorgeous time", "Evening elegant mode", "PM fab vibes"
        ],
        "nerd": [
            "Evening diagnostics", "Evening data analysis", "PM metrics compiled", "Evening telemetry", "Evening systems check",
            "PM validation complete", "Evening parameters ready", "PM calculations done", "Evening diagnostics ready", "PM data verified",
            "Evening metrics validated", "PM analysis complete", "Evening verification done", "PM telemetry active", "Evening systems optimal",
            "PM algorithms ready", "Evening parameters checked", "PM data processed", "Evening metrics ready", "PM diagnostics complete",
            "Evening verification ready", "PM systems verified", "Evening analysis ready", "PM telemetry processed", "Evening data compiled",
            "PM validation done", "Evening metrics processed", "PM diagnostics ready", "Evening systems verified", "PM parameters optimal",
            "Evening telemetry ready", "PM data complete", "Evening algorithms verified", "PM verification complete"
        ],
        "rager": [
            "Evening bullshit", "Evening goddamn updates", "PM clusterfuck", "Evening shit show", "Evening fucking chaos",
            "PM disaster mode", "Evening pain train", "PM horseshit incoming", "Evening goddamn problems", "PM hell mode",
            "Evening bullshit alert", "PM fucking issues", "Evening chaos mode", "PM disaster watch", "Evening pain incoming",
            "PM goddamn mess", "Evening clusterfuck mode", "PM shit alert", "Evening fucking problems", "PM hell incoming",
            "Evening bullshit mode", "PM clusterfuck alert", "Evening disaster mode", "PM goddamn chaos", "Evening shit incoming",
            "PM pain mode", "Evening fucking chaos", "PM bullshit watch", "Evening goddamn bullshit", "PM disaster incoming",
            "Evening hell alert", "PM clusterfuck mode", "Evening pain mode", "PM goddamn problems"
        ],
        "comedian": [
            "Evening irony", "Evening comedy hour", "PM absurdity", "Evening satire mode", "Evening deadpan time",
            "PM wit active", "Evening humor engaged", "PM sarcasm ready", "Evening comedy protocols", "PM deadpan mode",
            "Evening irony detected", "PM satire active", "Evening wit engaged", "PM absurdity alert", "Evening humor active",
            "PM sarcasm mode", "Evening comedy ready", "PM deadpan engaged", "Evening irony active", "PM satire ready",
            "Evening wit mode", "PM comedy engaged", "Evening humor protocols", "PM absurdity mode", "Evening deadpan ready",
            "PM irony mode", "Evening sarcasm active", "PM satire engaged", "Evening wit protocols", "PM comedy ready",
            "Evening humor mode", "PM deadpan time", "Evening irony engaged", "PM absurdity protocols"
        ],
        "action": [
            "Evening sitrep", "Evening tactical brief", "PM mission status", "Evening combat ready", "Evening field report",
            "PM operations brief", "Evening readiness check", "PM tactical update", "Evening combat status", "PM mission brief",
            "Evening ops sitrep", "PM readiness status", "Evening field brief", "PM combat brief", "Evening tactical sitrep",
            "PM ops status", "Evening mission update", "PM field status", "Evening tactical brief", "PM readiness sitrep",
            "Evening combat brief", "PM mission sitrep", "Evening field update", "PM ops status", "Evening combat sitrep",
            "PM tactical sitrep", "Evening mission brief", "PM readiness status", "Evening ops brief", "PM tactical status",
            "Evening field sitrep", "PM combat status", "Evening readiness brief", "PM tactical brief"
        ],
        "ops": [
            "Evening status", "Evening operational brief", "PM systems check", "Evening ops update", "Evening status report",
            "PM operational status", "Evening system brief", "PM ops brief", "Evening status update", "PM operational report",
            "Evening system status", "PM ops update", "Evening status brief", "PM operational update", "Evening system brief",
            "PM ops report", "Evening status update", "PM operational brief", "Evening system update", "PM ops status",
            "Evening status report", "PM operational status", "Evening system brief", "PM ops brief", "Evening status update",
            "PM operational report", "Evening system status", "PM ops status", "Evening operational status", "PM status brief",
            "Evening operational update", "PM system report", "Evening ops update", "PM status update"
        ],
        "tappit": [
            "Evening howzit", "Evening lekker bru", "PM sharp time", "Evening sorted", "Evening vibes né",
            "PM all good boet", "Evening lekker vibes", "PM sharp sharp", "Evening howzit bru", "PM all sorted",
            "Evening lekker time", "PM sharp boet", "Evening vibes né", "PM howzit hey", "Evening sorted bru",
            "PM sharp time", "Evening all good né", "PM lekker sharp", "Evening howzit boet", "PM sorted time",
            "Evening vibes bru", "PM lekker sharp", "Evening sharp né", "PM all good", "Evening howzit sharp",
            "PM vibes boet", "Evening lekker time", "PM sorted né", "Evening sharp bru", "PM howzit sharp",
            "Evening all good bru", "PM lekker né", "Evening sharp time", "PM vibes boet"
        ]
    },
    "late_night": {
        "jarvis": [
            "Late night dispatch", "Night operations brief", "Late hour coordination", "Night status update", "Late protocols active",
            "Night service brief", "Late operations ready", "Night coordination status", "Late briefing prepared", "Night readiness confirmed",
            "Late service protocols", "Night operations status", "Late briefing ready", "Night coordination brief", "Late readiness active",
            "Night service ready", "Late coordination underway", "Night status brief", "Late operations update", "Night briefing complete",
            "Late service underway", "Night coordination ready", "Late status update", "Night operations brief", "Late readiness status",
            "Night service active", "Late briefing underway", "Night readiness brief", "Late coordination status", "Night protocols ready",
            "Late operations engaged", "Night service protocols", "Late readiness confirmed", "Night status ready"
        ],
        "dude": [
            "Late night vibes", "Night chill time", "Late flow mode", "Night easy vibes", "Late mellow time",
            "Night smooth sailing", "Late zen mode", "Night peaceful vibes", "Late relaxed time", "Night chill mode",
            "Late flow vibes", "Night easy mode", "Late smooth time", "Night mellow vibes", "Late peaceful mode",
            "Night zen vibes", "Late cruise time", "Night relaxed mode", "Late easy sailing", "Night flow time",
            "Late mellow vibes", "Night smooth time", "Late chill mode", "Night peaceful mode", "Late zen vibes",
            "Night easy vibes", "Late relaxed vibes", "Night cruise mode", "Late smooth vibes", "Night mellow time",
            "Late peaceful vibes", "Night zen time", "Late flow mode", "Night chill vibes"
        ],
        "chick": [
            "Late night gorgeous", "Night glam time", "Late fabulous mode", "Night sparkle", "Late elegant vibes",
            "Night stunning time", "Late radiant mode", "Night chic vibes", "Late beauty time", "Night gorgeous mode",
            "Late fab vibes", "Night elegant time", "Late radiant vibes", "Night fabulous mode", "Late chic time",
            "Night sparkle mode", "Late stunning vibes", "Night radiant time", "Late gorgeous time", "Night elegant vibes",
            "Late fabulous vibes", "Night chic mode", "Late sparkle time", "Night gorgeous vibes", "Late elegant time",
            "Night radiant mode", "Late chic vibes", "Night fabulous time", "Late stunning time", "Night sparkle vibes",
            "Late radiant time", "Night gorgeous time", "Late elegant mode", "Night fab vibes"
        ],
        "nerd": [
            "Late night diagnostics", "Night data analysis", "Late metrics compiled", "Night telemetry", "Late systems check",
            "Night validation complete", "Late parameters ready", "Night calculations done", "Late diagnostics ready", "Night data verified",
            "Late metrics validated", "Night analysis complete", "Late verification done", "Night telemetry active", "Late systems optimal",
            "Night algorithms ready", "Late parameters checked", "Night data processed", "Late metrics ready", "Night diagnostics complete",
            "Late verification ready", "Night systems verified", "Late analysis ready", "Night telemetry processed", "Late data compiled",
            "Night validation done", "Late metrics processed", "Night diagnostics ready", "Late systems verified", "Night parameters optimal",
            "Late telemetry ready", "Night data complete", "Late algorithms verified", "Night verification complete"
        ],
        "rager": [
            "Late night bullshit", "Night goddamn updates", "Late clusterfuck", "Night shit show", "Late fucking chaos",
            "Night disaster mode", "Late pain train", "Night horseshit incoming", "Late goddamn problems", "Night hell mode",
            "Late bullshit alert", "Night fucking issues", "Late chaos mode", "Night disaster watch", "Late pain incoming",
            "Night goddamn mess", "Late clusterfuck mode", "Night shit alert", "Late fucking problems", "Night hell incoming",
            "Late bullshit mode", "Night clusterfuck alert", "Late disaster mode", "Night goddamn chaos", "Late shit incoming",
            "Night pain mode", "Late fucking chaos", "Night bullshit watch", "Late goddamn bullshit", "Night disaster incoming",
            "Late hell alert", "Night clusterfuck mode", "Late pain mode", "Night goddamn problems"
        ],
        "comedian": [
            "Late night irony", "Night comedy hour", "Late absurdity", "Night satire mode", "Late deadpan time",
            "Night wit active", "Late humor engaged", "Night sarcasm ready", "Late comedy protocols", "Night deadpan mode",
            "Late irony detected", "Night satire active", "Late wit engaged", "Night absurdity alert", "Late humor active",
            "Night sarcasm mode", "Late comedy ready", "Night deadpan engaged", "Late irony active", "Night satire ready",
            "Late wit mode", "Night comedy engaged", "Late humor protocols", "Night absurdity mode", "Late deadpan ready",
            "Night irony mode", "Late sarcasm active", "Night satire engaged", "Late wit protocols", "Night comedy ready",
            "Late humor mode", "Night deadpan time", "Late irony engaged", "Night absurdity protocols"
        ],
        "action": [
            "Late night sitrep", "Night tactical brief", "Late mission status", "Night combat ready", "Late field report",
            "Night operations brief", "Late readiness check", "Night tactical update", "Late combat status", "Night mission brief",
            "Late ops sitrep", "Night readiness status", "Late field brief", "Night combat brief", "Late tactical sitrep",
            "Night ops status", "Late mission update", "Night field status", "Late tactical brief", "Night readiness sitrep",
            "Late combat brief", "Night mission sitrep", "Late field update", "Night ops status", "Late combat sitrep",
            "Night tactical sitrep", "Late mission brief", "Night readiness status", "Late ops brief", "Night tactical status",
            "Late field sitrep", "Night combat status", "Late readiness brief", "Night tactical brief"
        ],
        "ops": [
            "Late night status", "Night operational brief", "Late systems check", "Night ops update", "Late status report",
            "Night operational status", "Late system brief", "Night ops brief", "Late status update", "Night operational report",
            "Late system status", "Night ops update", "Late status brief", "Night operational update", "Late system brief",
            "Night ops report", "Late status update", "Night operational brief", "Late system update", "Night ops status",
            "Late status report", "Night operational status", "Late system brief", "Night ops brief", "Late status update",
            "Night operational report", "Late system status", "Night ops status", "Late operational status", "Night status brief",
            "Late operational update", "Night system report", "Late ops update", "Night status update"
        ],
        "tappit": [
            "Late night howzit", "Night lekker bru", "Late sharp time", "Night sorted", "Late vibes né",
            "Night all good boet", "Late lekker vibes", "Night sharp sharp", "Late howzit bru", "Night all sorted",
            "Late lekker time", "Night sharp boet", "Late vibes né", "Night howzit hey", "Late sorted bru",
            "Night sharp time", "Late all good né", "Night lekker sharp", "Late howzit boet", "Night sorted time",
            "Late vibes bru", "Night lekker sharp", "Late sharp né", "Night all good", "Late howzit sharp",
            "Night vibes boet", "Late lekker time", "Night sorted né", "Late sharp bru", "Night howzit sharp",
            "Late all good bru", "Night lekker né", "Late sharp time", "Night vibes boet"
        ]
    }
}

# MASSIVE SERVICE-SPECIFIC RESPONSE BANKS - Context-aware and intelligent
_SERVICE_RESPONSES = {
    # Docker responses
    ("docker", "completed"): {
        "jarvis": ["Container deployment successful", "Docker orchestration complete", "Container stack operational", "Image deployment finalized"],
        "dude": ["Container's cruising smooth", "Docker stack flowing nice", "Containers vibing well", "Stack deployed easy"],
        "chick": ["Container deployed beautifully", "Docker looking fabulous", "Stack running gorgeously", "Containers performing perfectly"],
        "nerd": ["Container runtime nominal", "Docker daemon stable", "Stack metrics optimal", "Image layers verified"],
        "rager": ["Container finally fucking works", "Docker shit deployed", "Stack running goddammit", "Containers up finally"],
        "ops": ["Container operational", "Docker stack deployed", "Container status green", "Image running"],
        "tappit": ["Container lekker bru", "Docker sorted hey", "Stack running sharp", "Containers all good né"],
        "comedian": ["Container surprisingly functional", "Docker unexpectedly stable", "Stack shockingly operational", "Containers defying expectations"],
        "action": ["Container secured", "Docker mission complete", "Stack operational status", "Container deployment successful"],
    },
    ("docker", "failed"): {
        "jarvis": ["Container deployment failed", "Docker orchestration error", "Container stack compromised", "Image deployment unsuccessful"],
        "dude": ["Container hit a snag", "Docker stack having issues", "Containers not vibing", "Stack deployment rough"],
        "chick": ["Container needs attention", "Docker not looking good", "Stack having problems", "Containers struggling"],
        "nerd": ["Container runtime failure", "Docker daemon error", "Stack initialization failed", "Image corruption detected"],
        "rager": ["Container is fucked", "Docker shit broke", "Stack totally screwed", "Containers dead as hell"],
        "ops": ["Container failed", "Docker stack down", "Container error", "Image deployment failed"],
        "tappit": ["Container is kak bru", "Docker broken hey", "Stack not lekker", "Containers kaput né"],
        "comedian": ["Container dramatically failed", "Docker predictably broken", "Stack ironically down", "Containers quit unexpectedly"],
        "action": ["Container compromised", "Docker threat detected", "Stack mission failed", "Container breach detected"],
    },
    ("docker", "restarted"): {
        "jarvis": ["Container orchestration reset", "Docker services cycled", "Container stack reinitialized", "Image runtime refreshed"],
        "dude": ["Containers getting fresh start", "Docker reset flowing", "Stack rebooting smooth", "Containers cycling easy"],
        "chick": ["Containers refreshing beautifully", "Docker reboot looking good", "Stack resetting gracefully", "Containers restarting perfectly"],
        "nerd": ["Container runtime reinitialized", "Docker daemon restarted", "Stack services cycled", "Image cache cleared"],
        "rager": ["Containers restarted again", "Docker cycling goddammit", "Stack reset fucking again", "Containers bouncing"],
        "ops": ["Container restarted", "Docker services cycled", "Stack reset", "Container reboot complete"],
        "tappit": ["Containers reset bru", "Docker cycling sharp", "Stack rebooted né", "Containers fresh hey"],
        "comedian": ["Containers reluctantly restarted", "Docker begrudgingly cycled", "Stack unwillingly reset", "Containers reboot ritual complete"],
        "action": ["Container tactical reset", "Docker systems cycled", "Stack redeployment complete", "Container recovery initiated"],
    },
    
    # Plex/Media responses
    ("plex", "completed"): {
        "jarvis": ["Media server operations complete", "Plex library scan finished", "Streaming services operational", "Media index updated"],
        "dude": ["Plex cruising smooth", "Media flowing nice", "Library scan vibing", "Streaming easy mode"],
        "chick": ["Plex looking gorgeous", "Media library fabulous", "Streaming beautifully", "Library scan perfect"],
        "nerd": ["Plex database synchronized", "Media library indexed", "Transcode operations nominal", "Metadata refresh complete"],
        "rager": ["Plex scan finally done", "Media library updated", "Streaming working now", "Library scan finished"],
        "ops": ["Plex operational", "Media server ready", "Library scan complete", "Streaming active"],
        "tappit": ["Plex lekker bru", "Media sorted hey", "Library scanned sharp", "Streaming good né"],
        "comedian": ["Plex surprisingly functional", "Media library unexpectedly updated", "Streaming shockingly stable", "Library scan miraculously complete"],
        "action": ["Plex mission complete", "Media server secured", "Library operations successful", "Streaming operational"],
    },
    ("plex", "failed"): {
        "jarvis": ["Media server error detected", "Plex operations disrupted", "Streaming services interrupted", "Media index failure"],
        "dude": ["Plex hit a bump", "Media not flowing", "Library scan stuck", "Streaming having issues"],
        "chick": ["Plex needs attention", "Media library struggling", "Streaming problems detected", "Library scan failed"],
        "nerd": ["Plex database corruption", "Media transcoding failure", "Streaming buffer overflow", "Metadata sync error"],
        "rager": ["Plex is fucked", "Media server broken", "Streaming shit the bed", "Library scan failed hard"],
        "ops": ["Plex error", "Media server down", "Library scan failed", "Streaming offline"],
        "tappit": ["Plex broken bru", "Media kak hey", "Library scan failed né", "Streaming down"],
        "comedian": ["Plex dramatically crashed", "Media server plot twist", "Streaming unexpectedly dead", "Library scan gave up"],
        "action": ["Plex compromised", "Media server threat", "Streaming mission failed", "Library breach detected"],
    },
    
    # Sonarr/Radarr responses  
    ("sonarr", "completed"): {
        "jarvis": ["Episode acquisition complete", "TV series download finished", "Media automation successful", "Show library updated"],
        "dude": ["Episode grabbed smooth", "Show downloaded easy", "Series flowing nice", "TV library vibing"],
        "chick": ["Episode acquired perfectly", "Show downloaded beautifully", "Series looking fab", "TV library gorgeous"],
        "nerd": ["Episode parsed successfully", "Torrent acquisition nominal", "Quality profile matched", "Series metadata updated"],
        "rager": ["Episode finally grabbed", "Show downloaded", "Series got it done", "TV library updated"],
        "ops": ["Episode downloaded", "Series acquired", "Show library updated", "Download complete"],
        "tappit": ["Episode grabbed bru", "Show sorted hey", "Series lekker né", "TV library sharp"],
        "comedian": ["Episode surprisingly acquired", "Show unexpectedly downloaded", "Series miraculously grabbed", "TV library updated shockingly"],
        "action": ["Episode secured", "Series acquisition complete", "Show mission successful", "TV library operational"],
    },
    ("radarr", "completed"): {
        "jarvis": ["Film acquisition complete", "Movie download finished", "Cinema automation successful", "Film library updated"],
        "dude": ["Movie grabbed smooth", "Film downloaded easy", "Cinema flowing nice", "Movie library vibing"],
        "chick": ["Film acquired perfectly", "Movie downloaded beautifully", "Cinema looking fab", "Film library gorgeous"],
        "nerd": ["Movie parsed successfully", "Torrent acquisition nominal", "Quality profile matched", "Film metadata updated"],
        "rager": ["Movie finally grabbed", "Film downloaded", "Cinema got it done", "Movie library updated"],
        "ops": ["Movie downloaded", "Film acquired", "Cinema library updated", "Download complete"],
        "tappit": ["Movie grabbed bru", "Film sorted hey", "Cinema lekker né", "Movie library sharp"],
        "comedian": ["Film surprisingly acquired", "Movie unexpectedly downloaded", "Cinema miraculously grabbed", "Film library updated shockingly"],
        "action": ["Film secured", "Movie acquisition complete", "Cinema mission successful", "Film library operational"],
    },
    
    # Database responses
    ("database", "completed"): {
        "jarvis": ["Database operations complete", "Query execution successful", "Data synchronization finished", "Database index updated"],
        "dude": ["Database cruising smooth", "Queries flowing nice", "Data syncing easy", "DB vibing well"],
        "chick": ["Database running beautifully", "Queries performing perfectly", "Data looking fabulous", "DB gorgeously optimized"],
        "nerd": ["Query optimizer efficient", "Database integrity verified", "Transaction logs clean", "Index fragmentation minimal"],
        "rager": ["Database queries done", "Data synced finally", "DB working now", "Queries completed"],
        "ops": ["Database operational", "Queries complete", "Data synchronized", "DB status green"],
        "tappit": ["Database lekker bru", "Queries sorted hey", "Data synced sharp", "DB all good né"],
        "comedian": ["Database surprisingly stable", "Queries unexpectedly fast", "Data shockingly consistent", "DB miraculously optimized"],
        "action": ["Database secured", "Query mission complete", "Data operations successful", "DB tactical status green"],
    },
    ("database", "failed"): {
        "jarvis": ["Database error detected", "Query execution failed", "Data synchronization interrupted", "Database connection lost"],
        "dude": ["Database hit issues", "Queries not flowing", "Data sync stuck", "DB having problems"],
        "chick": ["Database needs attention", "Queries struggling", "Data sync failed", "DB not looking good"],
        "nerd": ["Database deadlock detected", "Query timeout exceeded", "Connection pool exhausted", "Transaction rollback triggered"],
        "rager": ["Database is fucked", "Queries shit the bed", "Data sync broken", "DB totally screwed"],
        "ops": ["Database error", "Query failed", "Data sync failure", "DB connection down"],
        "tappit": ["Database kak bru", "Queries broken hey", "Data sync failed né", "DB not lekker"],
        "comedian": ["Database dramatically failed", "Queries gave up entirely", "Data sync plot twist", "DB unexpectedly dead"],
        "action": ["Database compromised", "Query threat detected", "Data breach alert", "DB mission critical"],
    },
    
    # Network responses
    ("network", "connected"): {
        "jarvis": ["Network connectivity established", "Connection protocols active", "Network services online", "Link status operational"],
        "dude": ["Network vibing smooth", "Connection flowing nice", "Link cruising easy", "Network all good"],
        "chick": ["Network connected beautifully", "Link looking perfect", "Connection gorgeous", "Network running fab"],
        "nerd": ["Network handshake complete", "TCP connection established", "Routing tables updated", "DNS resolution active"],
        "rager": ["Network finally connected", "Link is up", "Connection working now", "Network online"],
        "ops": ["Network connected", "Link established", "Connection active", "Network operational"],
        "tappit": ["Network connected bru", "Link lekker hey", "Connection sharp né", "Network sorted"],
        "comedian": ["Network surprisingly online", "Connection unexpectedly stable", "Link shockingly active", "Network miraculously working"],
        "action": ["Network secured", "Connection established", "Link operational", "Network tactical status green"],
    },
    ("network", "disconnected"): {
        "jarvis": ["Network connectivity lost", "Connection protocols failed", "Network services offline", "Link status down"],
        "dude": ["Network down man", "Connection dropped", "Link lost flow", "Network having issues"],
        "chick": ["Network needs attention", "Connection lost", "Link down", "Network struggling"],
        "nerd": ["Network timeout exceeded", "Connection refused", "Routing failure detected", "DNS resolution failed"],
        "rager": ["Network is fucked", "Connection dead", "Link broken", "Network shit the bed"],
        "ops": ["Network disconnected", "Link down", "Connection lost", "Network offline"],
        "tappit": ["Network down bru", "Connection kak hey", "Link broken né", "Network offline"],
        "comedian": ["Network dramatically offline", "Connection plot twist", "Link unexpectedly dead", "Network gave up"],
        "action": ["Network compromised", "Connection breach", "Link mission failed", "Network threat detected"],
    },
    
    # Backup responses
    ("backup", "completed"): {
        "jarvis": ["Backup operation complete", "Data archival successful", "Snapshot creation finished", "Backup verification passed"],
        "dude": ["Backup cruising done", "Data archived smooth", "Snapshot vibing good", "Backup flowing easy"],
        "chick": ["Backup completed beautifully", "Data archived perfectly", "Snapshot gorgeous", "Backup running fab"],
        "nerd": ["Backup checksums verified", "Data integrity confirmed", "Snapshot differential optimal", "Backup compression efficient"],
        "rager": ["Backup finally done", "Data archived", "Snapshot completed", "Backup finished"],
        "ops": ["Backup complete", "Data archived", "Snapshot created", "Backup verified"],
        "tappit": ["Backup done bru", "Data sorted hey", "Snapshot lekker né", "Backup sharp"],
        "comedian": ["Backup surprisingly successful", "Data unexpectedly archived", "Snapshot miraculously complete", "Backup shockingly worked"],
        "action": ["Backup secured", "Data extraction complete", "Snapshot mission successful", "Backup operational"],
    },
    ("backup", "failed"): {
        "jarvis": ["Backup operation failed", "Data archival interrupted", "Snapshot creation error", "Backup verification failed"],
        "dude": ["Backup hit issues", "Data archive stuck", "Snapshot problems", "Backup not flowing"],
        "chick": ["Backup needs attention", "Data archive failed", "Snapshot struggling", "Backup not working"],
        "nerd": ["Backup checksum mismatch", "Data integrity compromised", "Snapshot corruption detected", "Backup storage full"],
        "rager": ["Backup is fucked", "Data archive broken", "Snapshot failed hard", "Backup shit the bed"],
        "ops": ["Backup failed", "Data archive error", "Snapshot failed", "Backup incomplete"],
        "tappit": ["Backup kak bru", "Data archive broken hey", "Snapshot failed né", "Backup not lekker"],
        "comedian": ["Backup dramatically failed", "Data archive plot twist", "Snapshot gave up", "Backup unexpectedly dead"],
        "action": ["Backup compromised", "Data extraction failed", "Snapshot mission critical", "Backup breach detected"],
    },
    
    # Home Assistant responses
    ("homeassistant", "completed"): {
        "jarvis": ["Home automation task complete", "Smart device coordination successful", "Automation sequence finished", "Home system updated"],
        "dude": ["Home automation cruising", "Smart devices vibing", "Automation flowing smooth", "Home system easy"],
        "chick": ["Home automation perfect", "Smart devices gorgeous", "Automation beautifully done", "Home system fab"],
        "nerd": ["Automation state machine complete", "Entity synchronization nominal", "Sensor data validated", "Integration API successful"],
        "rager": ["Home automation done", "Smart devices working", "Automation completed", "Home system updated"],
        "ops": ["Home automation complete", "Device coordination done", "Automation executed", "System updated"],
        "tappit": ["Home automation lekker", "Smart devices sorted bru", "Automation sharp hey", "Home system good né"],
        "comedian": ["Home automation surprisingly worked", "Smart devices unexpectedly responsive", "Automation miraculously complete", "Home system shockingly stable"],
        "action": ["Home secured", "Device coordination complete", "Automation mission successful", "System operational"],
    },
    
    # VPN responses
    ("vpn", "connected"): {
        "jarvis": ["VPN tunnel established", "Secure connection active", "Encrypted link operational", "VPN protocols engaged"],
        "dude": ["VPN cruising secure", "Tunnel flowing smooth", "Connection vibing safe", "VPN all good"],
        "chick": ["VPN connected beautifully", "Tunnel looking perfect", "Connection gorgeously secure", "VPN fab"],
        "nerd": ["VPN handshake complete", "Encryption protocols active", "Tunnel routing verified", "IPsec established"],
        "rager": ["VPN finally connected", "Tunnel is up", "Connection working", "VPN online"],
        "ops": ["VPN connected", "Tunnel established", "Secure connection active", "VPN operational"],
        "tappit": ["VPN connected bru", "Tunnel lekker hey", "Connection sharp né", "VPN sorted"],
        "comedian": ["VPN surprisingly secure", "Tunnel unexpectedly stable", "Connection shockingly private", "VPN miraculously working"],
        "action": ["VPN secured", "Tunnel operational", "Connection encrypted", "VPN tactical status green"],
    },
    ("vpn", "disconnected"): {
        "jarvis": ["VPN tunnel terminated", "Secure connection lost", "Encrypted link down", "VPN protocols inactive"],
        "dude": ["VPN dropped man", "Tunnel down", "Connection lost flow", "VPN having issues"],
        "chick": ["VPN needs attention", "Tunnel disconnected", "Connection lost", "VPN struggling"],
        "nerd": ["VPN timeout exceeded", "Tunnel handshake failed", "Encryption key expired", "Connection refused"],
        "rager": ["VPN is fucked", "Tunnel dead", "Connection broken", "VPN shit out"],
        "ops": ["VPN disconnected", "Tunnel down", "Connection lost", "VPN offline"],
        "tappit": ["VPN down bru", "Tunnel kak hey", "Connection broken né", "VPN offline"],
        "comedian": ["VPN dramatically offline", "Tunnel plot twist", "Connection unexpectedly insecure", "VPN gave up"],
        "action": ["VPN compromised", "Tunnel breach", "Connection lost", "VPN threat detected"],
    },
    
    # Monitoring responses
    ("monitoring", "warning"): {
        "jarvis": ["Monitoring threshold exceeded", "Alert condition detected", "Performance degradation noted", "Health check warning"],
        "dude": ["Monitoring seeing issues", "Alerts coming in", "Performance slowing", "Health check concerned"],
        "chick": ["Monitoring needs attention", "Alerts detected", "Performance not ideal", "Health check warning"],
        "nerd": ["Monitoring threshold breach", "Metric anomaly detected", "Performance deviation significant", "Statistical outlier identified"],
        "rager": ["Monitoring showing problems", "Alerts fucking everywhere", "Performance degraded", "Health check warnings"],
        "ops": ["Monitoring alert", "Threshold exceeded", "Performance warning", "Health check degraded"],
        "tappit": ["Monitoring warning bru", "Alerts coming hey", "Performance not lekker", "Health check concerned né"],
        "comedian": ["Monitoring dramatically alarmed", "Alerts unexpectedly numerous", "Performance ironically degraded", "Health check surprisingly worried"],
        "action": ["Monitoring threat detected", "Alert condition active", "Performance degradation confirmed", "Health check warning issued"],
    },
    
    # Certificate responses
    ("certificate", "updated"): {
        "jarvis": ["Certificate renewal complete", "SSL/TLS updated successfully", "Security certificate refreshed", "Certificate validation passed"],
        "dude": ["Certificate renewed smooth", "SSL updated easy", "Cert flowing fresh", "Security vibing good"],
        "chick": ["Certificate renewed beautifully", "SSL updated perfectly", "Cert looking gorgeous", "Security fab"],
        "nerd": ["Certificate chain validated", "Public key infrastructure updated", "X.509 renewal successful", "Certificate authority verified"],
        "rager": ["Certificate renewed finally", "SSL updated", "Cert refreshed", "Security updated"],
        "ops": ["Certificate renewed", "SSL updated", "Cert refreshed", "Security current"],
        "tappit": ["Certificate renewed bru", "SSL sorted hey", "Cert fresh né", "Security lekker"],
        "comedian": ["Certificate surprisingly renewed", "SSL unexpectedly current", "Cert miraculously valid", "Security shockingly updated"],
        "action": ["Certificate secured", "SSL encryption updated", "Cert mission complete", "Security operational"],
    },
    ("certificate", "failed"): {
        "jarvis": ["Certificate renewal failed", "SSL/TLS update error", "Security certificate invalid", "Certificate validation failed"],
        "dude": ["Certificate issues man", "SSL update stuck", "Cert problems", "Security not flowing"],
        "chick": ["Certificate needs attention", "SSL update failed", "Cert struggling", "Security concerns"],
        "nerd": ["Certificate validation error", "Chain of trust broken", "ACME challenge failed", "Certificate authority unreachable"],
        "rager": ["Certificate is fucked", "SSL broken", "Cert failed hard", "Security shit the bed"],
        "ops": ["Certificate failed", "SSL error", "Cert invalid", "Security warning"],
        "tappit": ["Certificate kak bru", "SSL broken hey", "Cert failed né", "Security not lekker"],
        "comedian": ["Certificate dramatically expired", "SSL plot twist", "Cert unexpectedly invalid", "Security ironically insecure"],
        "action": ["Certificate compromised", "SSL breach detected", "Cert mission failed", "Security threat active"],
    },
    
    # Media/Radarr/Sonarr responses
    ("media", "completed"): {
        "jarvis": ["Media acquisition complete", "Download successfully archived", "Content delivery finished", "Media file processed"],
        "dude": ["Download cruising done", "Media vibing smooth", "Content flowing in nice", "Download all good"],
        "chick": ["Download completed beautifully", "Media looking perfect", "Content arrived gorgeously", "Download fab"],
        "nerd": ["Download checksum verified", "Media codec validated", "File integrity confirmed", "Metadata parsed successfully"],
        "rager": ["Download finally done", "Media downloaded", "Content arrived", "Download finished"],
        "ops": ["Download complete", "Media acquired", "Content delivered", "File received"],
        "tappit": ["Download done bru", "Media sorted hey", "Content lekker né", "Download sharp"],
        "comedian": ["Download surprisingly successful", "Media unexpectedly arrived", "Content miraculously complete", "Download shockingly worked"],
        "action": ["Media secured", "Download mission complete", "Content acquisition successful", "File extracted"],
    },
    ("radarr", "completed"): {
        "jarvis": ["Movie acquisition complete", "Film download successful", "Cinema content delivered", "Movie file archived"],
        "dude": ["Movie downloaded smooth", "Film vibing in nice", "Cinema content flowing", "Movie all good"],
        "chick": ["Movie downloaded beautifully", "Film arrived perfectly", "Cinema content gorgeous", "Movie fab"],
        "nerd": ["Movie metadata parsed", "Film quality verified", "Video codec validated", "Movie file integrity confirmed"],
        "rager": ["Movie finally downloaded", "Film arrived", "Cinema content done", "Movie downloaded"],
        "ops": ["Movie download complete", "Film acquired", "Cinema content delivered", "Movie received"],
        "tappit": ["Movie downloaded bru", "Film sorted hey", "Cinema content lekker", "Movie sharp né"],
        "comedian": ["Movie surprisingly downloaded", "Film unexpectedly arrived", "Cinema content miraculously complete", "Movie shockingly successful"],
        "action": ["Movie secured", "Film acquisition complete", "Cinema content mission successful", "Movie extracted"],
    },
    ("sonarr", "completed"): {
        "jarvis": ["Episode acquisition complete", "TV download successful", "Series content delivered", "Episode file archived"],
        "dude": ["Episode downloaded smooth", "TV vibing in nice", "Series content flowing", "Episode all good"],
        "chick": ["Episode downloaded beautifully", "TV arrived perfectly", "Series content gorgeous", "Episode fab"],
        "nerd": ["Episode metadata parsed", "TV quality verified", "Video codec validated", "Episode file integrity confirmed"],
        "rager": ["Episode finally downloaded", "TV arrived", "Series content done", "Episode downloaded"],
        "ops": ["Episode download complete", "TV acquired", "Series content delivered", "Episode received"],
        "tappit": ["Episode downloaded bru", "TV sorted hey", "Series content lekker", "Episode sharp né"],
        "comedian": ["Episode surprisingly downloaded", "TV unexpectedly arrived", "Series content miraculously complete", "Episode shockingly successful"],
        "action": ["Episode secured", "TV acquisition complete", "Series content mission successful", "Episode extracted"],
    },
    ("lidarr", "completed"): {
        "jarvis": ["Music acquisition complete", "Album download successful", "Audio content delivered", "Track file archived"],
        "dude": ["Album downloaded smooth", "Music vibing in nice", "Tracks flowing good", "Album all set"],
        "chick": ["Album downloaded beautifully", "Music arrived perfectly", "Tracks gorgeous", "Album fab"],
        "nerd": ["Music metadata parsed", "Audio codec validated", "Track integrity confirmed", "Album checksum verified"],
        "rager": ["Album finally downloaded", "Music arrived", "Tracks done", "Album downloaded"],
        "ops": ["Album download complete", "Music acquired", "Audio delivered", "Track received"],
        "tappit": ["Album downloaded bru", "Music sorted hey", "Tracks lekker né", "Album sharp"],
        "comedian": ["Album surprisingly downloaded", "Music unexpectedly arrived", "Tracks miraculously complete", "Album shockingly successful"],
        "action": ["Album secured", "Music acquisition complete", "Audio mission successful", "Track extracted"],
    },
    ("orchestrator", "completed"): {
        "jarvis": ["Orchestration task complete", "Playbook execution successful", "Automation workflow finished", "Job sequence completed"],
        "dude": ["Playbook ran smooth", "Automation flowing nice", "Job done easy", "Workflow cruising complete"],
        "chick": ["Playbook ran beautifully", "Automation executed perfectly", "Job finished gorgeously", "Workflow completed fab"],
        "nerd": ["Playbook state convergence achieved", "Ansible execution nominal", "Task dependency resolved", "Job exit code zero"],
        "rager": ["Playbook finally done", "Automation finished", "Job completed", "Workflow done"],
        "ops": ["Playbook complete", "Automation executed", "Job finished", "Workflow done"],
        "tappit": ["Playbook done bru", "Automation sorted hey", "Job lekker né", "Workflow sharp"],
        "comedian": ["Playbook surprisingly successful", "Automation unexpectedly worked", "Job miraculously complete", "Workflow shockingly finished"],
        "action": ["Playbook mission complete", "Automation deployed", "Job executed", "Workflow secured"],
    },
    ("orchestrator", "failed"): {
        "jarvis": ["Orchestration task failed", "Playbook execution error", "Automation workflow interrupted", "Job sequence failed"],
        "dude": ["Playbook hit issues", "Automation stuck", "Job failed", "Workflow problems"],
        "chick": ["Playbook needs attention", "Automation failed", "Job struggling", "Workflow not working"],
        "nerd": ["Playbook state divergence", "Ansible execution error", "Task dependency failed", "Job non-zero exit"],
        "rager": ["Playbook is fucked", "Automation broken", "Job failed hard", "Workflow shit the bed"],
        "ops": ["Playbook failed", "Automation error", "Job failed", "Workflow incomplete"],
        "tappit": ["Playbook kak bru", "Automation broken hey", "Job failed né", "Workflow not lekker"],
        "comedian": ["Playbook dramatically failed", "Automation plot twist", "Job gave up", "Workflow unexpectedly dead"],
        "action": ["Playbook compromised", "Automation failed", "Job mission critical", "Workflow breach"],
    },
    ("sentinel", "warning"): {
        "jarvis": ["Service health degraded", "Monitoring alert triggered", "Watchdog concern detected", "Service status warning"],
        "dude": ["Service health concerning", "Monitor seeing issues", "Watchdog worried", "Service not flowing"],
        "chick": ["Service needs attention", "Monitor alerting", "Watchdog concerned", "Service struggling"],
        "nerd": ["Service health metric deviation", "Monitoring threshold exceeded", "Watchdog condition triggered", "Service anomaly detected"],
        "rager": ["Service health problems", "Monitor showing shit", "Watchdog alerts", "Service degraded"],
        "ops": ["Service warning", "Monitor alert", "Watchdog triggered", "Service degraded"],
        "tappit": ["Service warning bru", "Monitor alert hey", "Watchdog concerned né", "Service not lekker"],
        "comedian": ["Service dramatically concerning", "Monitor unexpectedly alarmed", "Watchdog surprisingly worried", "Service ironically degraded"],
        "action": ["Service threat detected", "Monitor alert issued", "Watchdog condition active", "Service warning status"],
    },
    ("sentinel", "failed"): {
        "jarvis": ["Service failure detected", "Critical monitoring alert", "Watchdog service down", "Service offline"],
        "dude": ["Service down man", "Monitor seeing failure", "Watchdog detected outage", "Service offline"],
        "chick": ["Service needs immediate attention", "Monitor critical alert", "Watchdog service down", "Service offline"],
        "nerd": ["Service health check failed", "Monitoring critical threshold", "Watchdog timeout exceeded", "Service process terminated"],
        "rager": ["Service is fucked", "Monitor critical failure", "Watchdog service dead", "Service down"],
        "ops": ["Service failed", "Monitor critical", "Watchdog service down", "Service offline"],
        "tappit": ["Service down bru", "Monitor critical hey", "Watchdog failed né", "Service kak"],
        "comedian": ["Service dramatically failed", "Monitor critically concerned", "Watchdog unexpectedly panicked", "Service ironically dead"],
        "action": ["Service threat critical", "Monitor breach detected", "Watchdog failure confirmed", "Service down"],
    },
    ("sentinel", "completed"): {
        "jarvis": ["Service recovery complete", "Health check restored", "Watchdog service operational", "Service monitoring resumed"],
        "dude": ["Service back up smooth", "Health check flowing", "Watchdog happy", "Service vibing again"],
        "chick": ["Service restored beautifully", "Health check perfect", "Watchdog happy", "Service running fab"],
        "nerd": ["Service health nominal", "Monitoring metrics restored", "Watchdog condition cleared", "Service process healthy"],
        "rager": ["Service back up finally", "Health check ok", "Watchdog cleared", "Service running"],
        "ops": ["Service restored", "Health check passed", "Watchdog operational", "Service online"],
        "tappit": ["Service back bru", "Health check lekker", "Watchdog sorted hey", "Service sharp né"],
        "comedian": ["Service surprisingly recovered", "Health check unexpectedly passed", "Watchdog miraculously calm", "Service shockingly operational"],
        "action": ["Service secured", "Health check green", "Watchdog operational", "Service mission complete"],
    },
    ("jarvis", "completed"): {
        "jarvis": ["AI processing complete", "LLM generation successful", "Intelligence task finished", "Analysis complete"],
        "dude": ["AI processing smooth", "LLM generated nice", "Intelligence task easy", "Analysis flowing done"],
        "chick": ["AI processed beautifully", "LLM generated perfectly", "Intelligence task gorgeous", "Analysis fab"],
        "nerd": ["LLM inference complete", "Token generation nominal", "Model execution successful", "Neural processing done"],
        "rager": ["AI finally done", "LLM generated", "Intelligence task finished", "Analysis complete"],
        "ops": ["AI complete", "LLM generated", "Intelligence done", "Analysis finished"],
        "tappit": ["AI done bru", "LLM sorted hey", "Intelligence lekker", "Analysis sharp né"],
        "comedian": ["AI surprisingly intelligent", "LLM unexpectedly coherent", "Intelligence miraculously complete", "Analysis shockingly useful"],
        "action": ["AI mission complete", "LLM deployed", "Intelligence secured", "Analysis operational"],
    },
    ("jarvis", "failed"): {
        "jarvis": ["AI processing error", "LLM generation failed", "Intelligence task interrupted", "Analysis error"],
        "dude": ["AI hit issues", "LLM generation stuck", "Intelligence task problems", "Analysis failed"],
        "chick": ["AI needs attention", "LLM generation failed", "Intelligence task struggling", "Analysis not working"],
        "nerd": ["LLM inference timeout", "Token generation error", "Model execution failed", "Neural processing crashed"],
        "rager": ["AI is fucked", "LLM generation broken", "Intelligence task failed", "Analysis shit"],
        "ops": ["AI failed", "LLM error", "Intelligence incomplete", "Analysis failed"],
        "tappit": ["AI kak bru", "LLM broken hey", "Intelligence failed né", "Analysis not lekker"],
        "comedian": ["AI dramatically failed", "LLM plot twist", "Intelligence ironically stupid", "Analysis unexpectedly useless"],
        "action": ["AI compromised", "LLM breach", "Intelligence mission failed", "Analysis critical"],
    },
    
    # Storage responses
    ("storage", "completed"): {
        "jarvis": ["Storage operations complete", "Volume management successful", "Disk operations finished", "Storage pool synchronized"],
        "dude": ["Storage cruising smooth", "Volumes flowing nice", "Disks all good", "Storage vibing well"],
        "chick": ["Storage running beautifully", "Volumes looking perfect", "Disks gorgeous", "Storage fab"],
        "nerd": ["Filesystem mounted successfully", "RAID array synchronized", "Volume integrity verified", "Disk I/O nominal"],
        "rager": ["Storage finally done", "Volumes working", "Disks operational", "Storage complete"],
        "ops": ["Storage operational", "Volumes mounted", "Disk operations complete", "Storage ready"],
        "tappit": ["Storage lekker bru", "Volumes sorted hey", "Disks sharp né", "Storage all good"],
        "comedian": ["Storage surprisingly functional", "Volumes unexpectedly stable", "Disks shockingly reliable", "Storage miraculously working"],
        "action": ["Storage secured", "Volume mission complete", "Disk operations successful", "Storage tactical green"],
    },
    ("storage", "warning"): {
        "jarvis": ["Storage capacity warning", "Disk space threshold exceeded", "Volume usage high", "Storage degradation detected"],
        "dude": ["Storage getting tight", "Disk space low man", "Volumes filling up", "Storage concerning"],
        "chick": ["Storage needs attention", "Disk space running low", "Volumes getting full", "Storage warning"],
        "nerd": ["Filesystem utilization high", "RAID degradation detected", "Disk SMART warning", "Storage threshold breach"],
        "rager": ["Storage filling up", "Disk space low", "Volumes getting full", "Storage problems"],
        "ops": ["Storage warning", "Disk space low", "Volume usage high", "Storage threshold exceeded"],
        "tappit": ["Storage warning bru", "Disk space low hey", "Volumes filling né", "Storage concerning"],
        "comedian": ["Storage dramatically filling", "Disk space ironically limited", "Volumes surprisingly full", "Storage predictably concerning"],
        "action": ["Storage threat detected", "Disk capacity warning", "Volume alert issued", "Storage caution advised"],
    },
    ("storage", "failed"): {
        "jarvis": ["Storage failure detected", "Volume mount error", "Disk operation failed", "Storage pool offline"],
        "dude": ["Storage hit issues", "Volume mount problems", "Disks not flowing", "Storage down"],
        "chick": ["Storage needs immediate attention", "Volume failed", "Disks struggling", "Storage critical"],
        "nerd": ["Filesystem corruption detected", "RAID array failed", "Disk hardware failure", "Mount point unavailable"],
        "rager": ["Storage is fucked", "Volume mount broken", "Disks dead", "Storage shit the bed"],
        "ops": ["Storage failed", "Volume error", "Disk failure", "Storage offline"],
        "tappit": ["Storage kak bru", "Volume broken hey", "Disks failed né", "Storage down"],
        "comedian": ["Storage dramatically failed", "Volume plot twist", "Disks unexpectedly dead", "Storage ironically unavailable"],
        "action": ["Storage compromised", "Volume breach", "Disk mission critical", "Storage threat active"],
    },
    
    # System update/apt responses
    ("automation", "updated"): {
        "jarvis": ["System updates installed", "Package upgrades complete", "Security patches applied", "System refresh finished"],
        "dude": ["System updated smooth", "Packages upgraded easy", "Updates flowing done", "System refreshed nice"],
        "chick": ["System updated beautifully", "Packages upgraded perfectly", "Updates gorgeous", "System refreshed fab"],
        "nerd": ["APT cache updated", "Package dependencies resolved", "System kernel patched", "Repository metadata synced"],
        "rager": ["System finally updated", "Packages upgraded", "Updates done", "System patched"],
        "ops": ["System updated", "Packages upgraded", "Updates applied", "System current"],
        "tappit": ["System updated bru", "Packages sorted hey", "Updates lekker né", "System fresh"],
        "comedian": ["System surprisingly updated", "Packages unexpectedly current", "Updates miraculously applied", "System shockingly patched"],
        "action": ["System secured", "Packages deployed", "Updates executed", "System hardened"],
    },
    
    # Proxmox responses
    ("proxmox", "completed"): {
        "jarvis": ["Proxmox operations complete", "Hypervisor tasks finished", "VM management successful", "Cluster operations nominal"],
        "dude": ["Proxmox cruising smooth", "VMs vibing nice", "Hypervisor flowing easy", "Cluster all good"],
        "chick": ["Proxmox running beautifully", "VMs looking perfect", "Hypervisor gorgeous", "Cluster fab"],
        "nerd": ["VM state synchronized", "QEMU processes nominal", "Cluster quorum achieved", "ZFS pool healthy"],
        "rager": ["Proxmox finally done", "VMs working", "Hypervisor operational", "Cluster running"],
        "ops": ["Proxmox operational", "VMs running", "Hypervisor active", "Cluster stable"],
        "tappit": ["Proxmox lekker bru", "VMs sorted hey", "Hypervisor sharp né", "Cluster good"],
        "comedian": ["Proxmox surprisingly functional", "VMs unexpectedly stable", "Hypervisor shockingly working", "Cluster miraculously synchronized"],
        "action": ["Proxmox secured", "VM mission complete", "Hypervisor operational", "Cluster tactical green"],
    },
    ("proxmox", "failed"): {
        "jarvis": ["Proxmox error detected", "Hypervisor failure", "VM management error", "Cluster node offline"],
        "dude": ["Proxmox hit issues", "VMs having problems", "Hypervisor not flowing", "Cluster down"],
        "chick": ["Proxmox needs attention", "VMs struggling", "Hypervisor failed", "Cluster offline"],
        "nerd": ["VM migration failed", "QEMU process crashed", "Cluster quorum lost", "Storage backend timeout"],
        "rager": ["Proxmox is fucked", "VMs broken", "Hypervisor dead", "Cluster shit the bed"],
        "ops": ["Proxmox error", "VM failure", "Hypervisor down", "Cluster offline"],
        "tappit": ["Proxmox kak bru", "VMs broken hey", "Hypervisor failed né", "Cluster down"],
        "comedian": ["Proxmox dramatically failed", "VMs plot twist", "Hypervisor unexpectedly dead", "Cluster ironically offline"],
        "action": ["Proxmox compromised", "VM threat detected", "Hypervisor breach", "Cluster mission critical"],
    },
    
    # Unraid responses
    ("unraid", "completed"): {
        "jarvis": ["Unraid operations complete", "Array management successful", "Parity check finished", "Storage pool operational"],
        "dude": ["Unraid cruising smooth", "Array vibing nice", "Parity flowing good", "Storage all set"],
        "chick": ["Unraid running beautifully", "Array looking perfect", "Parity gorgeous", "Storage fab"],
        "nerd": ["Array state synchronized", "Parity verification successful", "Disk spin-up complete", "Cache pool healthy"],
        "rager": ["Unraid finally done", "Array working", "Parity complete", "Storage operational"],
        "ops": ["Unraid operational", "Array running", "Parity verified", "Storage ready"],
        "tappit": ["Unraid lekker bru", "Array sorted hey", "Parity sharp né", "Storage good"],
        "comedian": ["Unraid surprisingly functional", "Array unexpectedly stable", "Parity shockingly valid", "Storage miraculously working"],
        "action": ["Unraid secured", "Array mission complete", "Parity verified", "Storage tactical green"],
    },
    ("unraid", "warning"): {
        "jarvis": ["Unraid warning detected", "Array status degraded", "Parity concern noted", "Disk health warning"],
        "dude": ["Unraid showing concerns", "Array not perfect", "Parity issues", "Disk warning"],
        "chick": ["Unraid needs attention", "Array warning", "Parity concerns", "Disk health alert"],
        "nerd": ["Array disk SMART warning", "Parity sync errors detected", "Cache pool degraded", "Temperature threshold exceeded"],
        "rager": ["Unraid showing problems", "Array warnings", "Parity issues", "Disk alerts"],
        "ops": ["Unraid warning", "Array degraded", "Parity alert", "Disk warning"],
        "tappit": ["Unraid warning bru", "Array concerning hey", "Parity alert né", "Disk warning"],
        "comedian": ["Unraid dramatically warning", "Array ironically degraded", "Parity surprisingly concerned", "Disk predictably alerting"],
        "action": ["Unraid threat detected", "Array caution advised", "Parity alert issued", "Disk warning active"],
    },
    ("unraid", "failed"): {
        "jarvis": ["Unraid failure detected", "Array offline", "Parity check failed", "Disk failure critical"],
        "dude": ["Unraid hit problems", "Array down", "Parity failed", "Disk issues"],
        "chick": ["Unraid needs immediate attention", "Array failed", "Parity error", "Disk failure"],
        "nerd": ["Array mount failure", "Parity validation error", "Disk hardware failure detected", "Filesystem corruption"],
        "rager": ["Unraid is fucked", "Array dead", "Parity failed hard", "Disk shit the bed"],
        "ops": ["Unraid failed", "Array offline", "Parity error", "Disk failure"],
        "tappit": ["Unraid kak bru", "Array down hey", "Parity failed né", "Disk broken"],
        "comedian": ["Unraid dramatically failed", "Array plot twist", "Parity unexpectedly invalid", "Disk ironically dead"],
        "action": ["Unraid compromised", "Array breach detected", "Parity mission critical", "Disk failure confirmed"],
    },
    
    # LXC responses
    ("lxc", "completed"): {
        "jarvis": ["Container operations complete", "LXC management successful", "Container deployment finished", "System container operational"],
        "dude": ["LXC cruising smooth", "Containers vibing nice", "Deployment flowing easy", "LXC all good"],
        "chick": ["LXC running beautifully", "Containers looking perfect", "Deployment gorgeous", "LXC fab"],
        "nerd": ["Container state nominal", "LXC namespace isolated", "Cgroups configured correctly", "Container networking active"],
        "rager": ["LXC finally done", "Containers working", "Deployment complete", "LXC operational"],
        "ops": ["LXC operational", "Containers running", "Deployment complete", "LXC ready"],
        "tappit": ["LXC lekker bru", "Containers sorted hey", "Deployment sharp né", "LXC good"],
        "comedian": ["LXC surprisingly functional", "Containers unexpectedly stable", "Deployment shockingly successful", "LXC miraculously working"],
        "action": ["LXC secured", "Container mission complete", "Deployment successful", "LXC tactical green"],
    },
    ("lxc", "failed"): {
        "jarvis": ["Container failure detected", "LXC management error", "Container deployment failed", "System container offline"],
        "dude": ["LXC hit issues", "Containers having problems", "Deployment stuck", "LXC down"],
        "chick": ["LXC needs attention", "Containers struggling", "Deployment failed", "LXC offline"],
        "nerd": ["Container start failure", "LXC namespace conflict", "Cgroup resource exhausted", "Container network timeout"],
        "rager": ["LXC is fucked", "Containers broken", "Deployment failed", "LXC dead"],
        "ops": ["LXC error", "Container failure", "Deployment failed", "LXC offline"],
        "tappit": ["LXC kak bru", "Containers broken hey", "Deployment failed né", "LXC down"],
        "comedian": ["LXC dramatically failed", "Containers plot twist", "Deployment unexpectedly broken", "LXC ironically dead"],
        "action": ["LXC compromised", "Container threat detected", "Deployment breach", "LXC mission critical"],
    },
    
    # Bazarr responses
    ("bazarr", "completed"): {
        "jarvis": ["Subtitle acquisition complete", "Caption download successful", "Subtitle sync finished", "Language track added"],
        "dude": ["Subtitles downloaded smooth", "Captions vibing in nice", "Subs flowing good", "Subtitles all set"],
        "chick": ["Subtitles downloaded beautifully", "Captions arrived perfectly", "Subs looking gorgeous", "Subtitles fab"],
        "nerd": ["Subtitle metadata parsed", "Caption timing validated", "SRT format verified", "Subtitle encoding confirmed"],
        "rager": ["Subtitles finally downloaded", "Captions arrived", "Subs done", "Subtitles downloaded"],
        "ops": ["Subtitle download complete", "Captions acquired", "Subs delivered", "Subtitle received"],
        "tappit": ["Subtitles downloaded bru", "Captions sorted hey", "Subs lekker né", "Subtitles sharp"],
        "comedian": ["Subtitles surprisingly downloaded", "Captions unexpectedly arrived", "Subs miraculously synced", "Subtitles shockingly accurate"],
        "action": ["Subtitles secured", "Caption mission complete", "Subs acquired", "Subtitle extracted"],
    },
    
    # Cleanuperr responses
    ("cleanuperr", "completed"): {
        "jarvis": ["Media cleanup complete", "File organization successful", "Library maintenance finished", "Cleanup operation done"],
        "dude": ["Cleanup cruising done", "Files organized smooth", "Library flowing clean", "Cleanup all good"],
        "chick": ["Cleanup completed beautifully", "Files organized perfectly", "Library looking gorgeous", "Cleanup fab"],
        "nerd": ["File system optimization complete", "Duplicate detection nominal", "Cleanup algorithm successful", "Library indexed"],
        "rager": ["Cleanup finally done", "Files organized", "Library cleaned", "Cleanup finished"],
        "ops": ["Cleanup complete", "Files organized", "Library maintained", "Cleanup done"],
        "tappit": ["Cleanup done bru", "Files sorted hey", "Library lekker né", "Cleanup sharp"],
        "comedian": ["Cleanup surprisingly thorough", "Files unexpectedly organized", "Library miraculously clean", "Cleanup shockingly successful"],
        "action": ["Cleanup secured", "File organization complete", "Library mission successful", "Cleanup executed"],
    },
    
    # Huntarr responses
    ("huntarr", "completed"): {
        "jarvis": ["Content search complete", "Media discovery successful", "Search operation finished", "Content located"],
        "dude": ["Search cruising done", "Content found smooth", "Discovery flowing nice", "Search all good"],
        "chick": ["Search completed beautifully", "Content found perfectly", "Discovery gorgeous", "Search fab"],
        "nerd": ["Search algorithm complete", "Content metadata indexed", "Discovery query successful", "Search results validated"],
        "rager": ["Search finally done", "Content found", "Discovery complete", "Search finished"],
        "ops": ["Search complete", "Content discovered", "Search finished", "Content located"],
        "tappit": ["Search done bru", "Content found hey", "Discovery lekker né", "Search sharp"],
        "comedian": ["Search surprisingly successful", "Content unexpectedly found", "Discovery miraculously complete", "Search shockingly effective"],
        "action": ["Search mission complete", "Content located", "Discovery successful", "Search secured"],
    },
    
    # qBittorrent responses
    ("qbittorrent", "completed"): {
        "jarvis": ["Torrent download complete", "P2P transfer successful", "Seeding commenced", "Download finalized"],
        "dude": ["Torrent downloaded smooth", "P2P flowing done", "Seeding vibing nice", "Download all good"],
        "chick": ["Torrent completed beautifully", "P2P transfer perfect", "Seeding gorgeous", "Download fab"],
        "nerd": ["Torrent hash verified", "Peer swarm optimal", "Download ratio maintained", "Seed ratio nominal"],
        "rager": ["Torrent finally done", "P2P finished", "Seeding started", "Download complete"],
        "ops": ["Torrent complete", "P2P transfer done", "Seeding active", "Download finished"],
        "tappit": ["Torrent done bru", "P2P sorted hey", "Seeding lekker né", "Download sharp"],
        "comedian": ["Torrent surprisingly complete", "P2P unexpectedly successful", "Seeding miraculously active", "Download shockingly done"],
        "action": ["Torrent secured", "P2P mission complete", "Seeding operational", "Download extracted"],
    },
    ("qbittorrent", "failed"): {
        "jarvis": ["Torrent download failed", "P2P transfer error", "Seeding interrupted", "Download incomplete"],
        "dude": ["Torrent hit issues", "P2P stuck", "Seeding problems", "Download failed"],
        "chick": ["Torrent needs attention", "P2P struggling", "Seeding failed", "Download incomplete"],
        "nerd": ["Torrent tracker timeout", "Peer connection failed", "Download stalled", "Seed ratio insufficient"],
        "rager": ["Torrent is fucked", "P2P broken", "Seeding dead", "Download failed"],
        "ops": ["Torrent failed", "P2P error", "Seeding stopped", "Download incomplete"],
        "tappit": ["Torrent kak bru", "P2P broken hey", "Seeding failed né", "Download not lekker"],
        "comedian": ["Torrent dramatically failed", "P2P plot twist", "Seeding unexpectedly dead", "Download ironically incomplete"],
        "action": ["Torrent compromised", "P2P breach", "Seeding mission failed", "Download critical"],
    },
    
    # Deluge responses
    ("deluge", "completed"): {
        "jarvis": ["Torrent download complete", "Transfer successful", "Seeding active", "Download finalized"],
        "dude": ["Deluge downloaded smooth", "Transfer flowing done", "Seeding vibing", "Download all good"],
        "chick": ["Deluge completed beautifully", "Transfer perfect", "Seeding gorgeous", "Download fab"],
        "nerd": ["Torrent verification complete", "Peer swarm connected", "Download bandwidth optimal", "Seed queue active"],
        "rager": ["Deluge finally done", "Transfer finished", "Seeding started", "Download complete"],
        "ops": ["Deluge complete", "Transfer done", "Seeding active", "Download finished"],
        "tappit": ["Deluge done bru", "Transfer sorted hey", "Seeding lekker né", "Download sharp"],
        "comedian": ["Deluge surprisingly complete", "Transfer unexpectedly done", "Seeding miraculously active", "Download shockingly successful"],
        "action": ["Deluge secured", "Transfer complete", "Seeding operational", "Download mission done"],
    },
    
    # SABnzbd responses
    ("sabnzbd", "completed"): {
        "jarvis": ["Usenet download complete", "NZB processing successful", "Article extraction finished", "Download verified"],
        "dude": ["SAB downloaded smooth", "NZB flowing done", "Usenet vibing complete", "Download all good"],
        "chick": ["SAB completed beautifully", "NZB processed perfectly", "Usenet gorgeous", "Download fab"],
        "nerd": ["NZB par2 verified", "Article assembly complete", "Usenet connection optimal", "Download CRC validated"],
        "rager": ["SAB finally done", "NZB finished", "Usenet complete", "Download done"],
        "ops": ["SAB complete", "NZB processed", "Usenet finished", "Download done"],
        "tappit": ["SAB done bru", "NZB sorted hey", "Usenet lekker né", "Download sharp"],
        "comedian": ["SAB surprisingly complete", "NZB unexpectedly processed", "Usenet miraculously done", "Download shockingly verified"],
        "action": ["SAB secured", "NZB mission complete", "Usenet extracted", "Download operational"],
    },
    ("sabnzbd", "failed"): {
        "jarvis": ["Usenet download failed", "NZB processing error", "Article extraction incomplete", "Download failed verification"],
        "dude": ["SAB hit issues", "NZB stuck", "Usenet problems", "Download failed"],
        "chick": ["SAB needs attention", "NZB struggling", "Usenet failed", "Download incomplete"],
        "nerd": ["NZB par2 repair failed", "Article incomplete", "Usenet connection timeout", "Download CRC mismatch"],
        "rager": ["SAB is fucked", "NZB broken", "Usenet failed", "Download dead"],
        "ops": ["SAB failed", "NZB error", "Usenet incomplete", "Download failed"],
        "tappit": ["SAB kak bru", "NZB broken hey", "Usenet failed né", "Download not lekker"],
        "comedian": ["SAB dramatically failed", "NZB plot twist", "Usenet unexpectedly incomplete", "Download ironically broken"],
        "action": ["SAB compromised", "NZB breach", "Usenet mission failed", "Download critical"],
    },
    
    # Speedtest responses
    ("speedtest", "completed"): {
        "jarvis": ["Speed test complete", "Bandwidth measurement successful", "Network performance assessed", "Connection speed verified"],
        "dude": ["Speedtest cruising done", "Bandwidth flowing measured", "Speed check smooth", "Connection tested good"],
        "chick": ["Speedtest completed beautifully", "Bandwidth measured perfectly", "Speed check gorgeous", "Connection fab"],
        "nerd": ["Throughput metrics nominal", "Latency within tolerances", "Jitter minimal", "Packet loss zero percent"],
        "rager": ["Speedtest finally done", "Bandwidth measured", "Speed checked", "Connection tested"],
        "ops": ["Speedtest complete", "Bandwidth measured", "Speed verified", "Connection tested"],
        "tappit": ["Speedtest done bru", "Bandwidth sorted hey", "Speed lekker né", "Connection sharp"],
        "comedian": ["Speedtest surprisingly accurate", "Bandwidth unexpectedly measured", "Speed miraculously tested", "Connection shockingly fast"],
        "action": ["Speedtest secured", "Bandwidth mission complete", "Speed verified", "Connection operational"],
    },
    
    # Plex responses
    ("plex", "completed"): {
        "jarvis": ["Plex operation complete", "Media server synchronized", "Library scan finished", "Streaming ready"],
        "dude": ["Plex cruising smooth", "Media server vibing", "Library flowing done", "Streaming all good"],
        "chick": ["Plex running beautifully", "Media server perfect", "Library gorgeous", "Streaming fab"],
        "nerd": ["Plex database indexed", "Metadata agents complete", "Transcoding profiles optimal", "Stream bandwidth allocated"],
        "rager": ["Plex finally done", "Media server working", "Library scanned", "Streaming ready"],
        "ops": ["Plex operational", "Media server ready", "Library updated", "Streaming active"],
        "tappit": ["Plex lekker bru", "Media server sorted hey", "Library sharp né", "Streaming good"],
        "comedian": ["Plex surprisingly functional", "Media server unexpectedly working", "Library miraculously complete", "Streaming shockingly smooth"],
        "action": ["Plex secured", "Media server operational", "Library mission complete", "Streaming deployed"],
    },
    
    # Emby responses
    ("emby", "completed"): {
        "jarvis": ["Emby operation complete", "Media server synchronized", "Library scan finished", "Streaming ready"],
        "dude": ["Emby cruising smooth", "Media server vibing", "Library flowing done", "Streaming all good"],
        "chick": ["Emby running beautifully", "Media server perfect", "Library gorgeous", "Streaming fab"],
        "nerd": ["Emby database indexed", "Metadata providers complete", "Transcoding optimal", "Stream delivery ready"],
        "rager": ["Emby finally done", "Media server working", "Library scanned", "Streaming ready"],
        "ops": ["Emby operational", "Media server ready", "Library updated", "Streaming active"],
        "tappit": ["Emby lekker bru", "Media server sorted hey", "Library sharp né", "Streaming good"],
        "comedian": ["Emby surprisingly functional", "Media server unexpectedly working", "Library miraculously complete", "Streaming shockingly smooth"],
        "action": ["Emby secured", "Media server operational", "Library mission complete", "Streaming deployed"],
    },
    
    # Jellyfin responses
    ("jellyfin", "completed"): {
        "jarvis": ["Jellyfin operation complete", "Media server synchronized", "Library scan finished", "Streaming ready"],
        "dude": ["Jellyfin cruising smooth", "Media server vibing", "Library flowing done", "Streaming all good"],
        "chick": ["Jellyfin running beautifully", "Media server perfect", "Library gorgeous", "Streaming fab"],
        "nerd": ["Jellyfin database indexed", "Metadata scrapers complete", "Transcoding profiles active", "Stream protocols ready"],
        "rager": ["Jellyfin finally done", "Media server working", "Library scanned", "Streaming ready"],
        "ops": ["Jellyfin operational", "Media server ready", "Library updated", "Streaming active"],
        "tappit": ["Jellyfin lekker bru", "Media server sorted hey", "Library sharp né", "Streaming good"],
        "comedian": ["Jellyfin surprisingly functional", "Media server unexpectedly working", "Library miraculously complete", "Streaming shockingly smooth"],
        "action": ["Jellyfin secured", "Media server operational", "Library mission complete", "Streaming deployed"],
    },
    
    # Traefik responses
    ("traefik", "completed"): {
        "jarvis": ["Traefik routing operational", "Reverse proxy configured", "Load balancing active", "SSL termination ready"],
        "dude": ["Traefik routing smooth", "Proxy flowing nice", "Load balancing good", "SSL cruising"],
        "chick": ["Traefik running beautifully", "Proxy configured perfectly", "Load balancing gorgeous", "SSL fab"],
        "nerd": ["Traefik middleware applied", "Dynamic routing active", "Certificate resolver operational", "Backend health optimal"],
        "rager": ["Traefik finally working", "Proxy configured", "Load balancing active", "SSL ready"],
        "ops": ["Traefik operational", "Proxy configured", "Load balancing active", "SSL ready"],
        "tappit": ["Traefik lekker bru", "Proxy sorted hey", "Load balancing sharp né", "SSL good"],
        "comedian": ["Traefik surprisingly routing", "Proxy unexpectedly working", "Load balancing miraculously balanced", "SSL shockingly secure"],
        "action": ["Traefik secured", "Proxy mission complete", "Load balancing deployed", "SSL operational"],
    },
    ("traefik", "failed"): {
        "jarvis": ["Traefik routing failure", "Reverse proxy error", "Load balancing failed", "SSL termination error"],
        "dude": ["Traefik having issues", "Proxy stuck", "Load balancing problems", "SSL failed"],
        "chick": ["Traefik needs attention", "Proxy struggling", "Load balancing failed", "SSL error"],
        "nerd": ["Traefik middleware error", "Dynamic routing failed", "Certificate resolver timeout", "Backend unreachable"],
        "rager": ["Traefik is fucked", "Proxy broken", "Load balancing dead", "SSL failed"],
        "ops": ["Traefik error", "Proxy failed", "Load balancing down", "SSL error"],
        "tappit": ["Traefik kak bru", "Proxy broken hey", "Load balancing failed né", "SSL not lekker"],
        "comedian": ["Traefik dramatically failed", "Proxy plot twist", "Load balancing ironically unbalanced", "SSL unexpectedly insecure"],
        "action": ["Traefik compromised", "Proxy breach", "Load balancing mission failed", "SSL threat"],
    },
    
    # Nginx responses
    ("nginx", "completed"): {
        "jarvis": ["Nginx configuration applied", "Web server operational", "Proxy pass active", "SSL certificates loaded"],
        "dude": ["Nginx cruising smooth", "Web server vibing", "Proxy flowing nice", "SSL all good"],
        "chick": ["Nginx running beautifully", "Web server perfect", "Proxy gorgeous", "SSL fab"],
        "nerd": ["Nginx worker processes spawned", "Configuration syntax valid", "Upstream servers healthy", "SSL session cache optimal"],
        "rager": ["Nginx finally working", "Web server running", "Proxy active", "SSL loaded"],
        "ops": ["Nginx operational", "Web server running", "Proxy active", "SSL configured"],
        "tappit": ["Nginx lekker bru", "Web server sorted hey", "Proxy sharp né", "SSL good"],
        "comedian": ["Nginx surprisingly stable", "Web server unexpectedly fast", "Proxy miraculously working", "SSL shockingly valid"],
        "action": ["Nginx secured", "Web server deployed", "Proxy operational", "SSL mission complete"],
    },
    
    # Portainer responses
    ("portainer", "completed"): {
        "jarvis": ["Container management operational", "Docker orchestration ready", "Stack deployment successful", "Container monitoring active"],
        "dude": ["Portainer cruising smooth", "Containers managed nice", "Stack deployed easy", "Monitoring vibing"],
        "chick": ["Portainer running beautifully", "Containers managed perfectly", "Stack gorgeous", "Monitoring fab"],
        "nerd": ["Portainer API responsive", "Container state synchronized", "Stack compose validated", "Resource metrics collected"],
        "rager": ["Portainer finally working", "Containers managed", "Stack deployed", "Monitoring active"],
        "ops": ["Portainer operational", "Container management ready", "Stack deployed", "Monitoring active"],
        "tappit": ["Portainer lekker bru", "Containers sorted hey", "Stack sharp né", "Monitoring good"],
        "comedian": ["Portainer surprisingly functional", "Containers unexpectedly managed", "Stack miraculously deployed", "Monitoring shockingly useful"],
        "action": ["Portainer secured", "Container management operational", "Stack mission complete", "Monitoring deployed"],
    },
    
    # Uptime Kuma responses
    ("uptime-kuma", "warning"): {
        "jarvis": ["Uptime monitoring alert", "Service availability degraded", "Health check warning", "Monitoring threshold exceeded"],
        "dude": ["Kuma seeing issues", "Service having problems", "Health check concerned", "Monitoring worried"],
        "chick": ["Kuma alerting", "Service needs attention", "Health check warning", "Monitoring concerned"],
        "nerd": ["Uptime SLA breach detected", "Ping response degraded", "HTTP status code anomaly", "Certificate expiration warning"],
        "rager": ["Kuma showing problems", "Service degraded", "Health check warnings", "Monitoring alerts"],
        "ops": ["Uptime alert", "Service degraded", "Health warning", "Monitoring threshold exceeded"],
        "tappit": ["Kuma warning bru", "Service not lekker", "Health check concerned hey", "Monitoring alert né"],
        "comedian": ["Kuma dramatically concerned", "Service ironically down", "Health check surprisingly worried", "Monitoring unexpectedly alarmed"],
        "action": ["Uptime threat detected", "Service degradation confirmed", "Health check warning issued", "Monitoring alert active"],
    },
    
    # Vaultwarden responses
    ("vaultwarden", "completed"): {
        "jarvis": ["Password vault synchronized", "Credential storage secure", "Vault backup complete", "Encryption operational"],
        "dude": ["Vault synced smooth", "Passwords flowing secure", "Backup cruising done", "Encryption vibing"],
        "chick": ["Vault synced beautifully", "Passwords secured perfectly", "Backup gorgeous", "Encryption fab"],
        "nerd": ["Vault database encrypted", "AES-256 encryption active", "PBKDF2 iterations nominal", "Two-factor authentication enabled"],
        "rager": ["Vault finally synced", "Passwords secured", "Backup done", "Encryption active"],
        "ops": ["Vault synchronized", "Passwords secure", "Backup complete", "Encryption active"],
        "tappit": ["Vault synced bru", "Passwords sorted hey", "Backup lekker né", "Encryption sharp"],
        "comedian": ["Vault surprisingly secure", "Passwords unexpectedly encrypted", "Backup miraculously complete", "Encryption shockingly strong"],
        "action": ["Vault secured", "Password mission complete", "Backup operational", "Encryption deployed"],
    },
    
    # Nextcloud responses
    ("nextcloud", "completed"): {
        "jarvis": ["File synchronization complete", "Cloud storage operational", "Sync client connected", "File sharing active"],
        "dude": ["Nextcloud synced smooth", "Files flowing nice", "Storage vibing good", "Sharing all set"],
        "chick": ["Nextcloud synced beautifully", "Files perfect", "Storage gorgeous", "Sharing fab"],
        "nerd": ["File delta sync complete", "WebDAV protocol active", "Chunked upload successful", "Database maintenance done"],
        "rager": ["Nextcloud finally synced", "Files uploaded", "Storage working", "Sharing active"],
        "ops": ["Nextcloud synchronized", "Files synced", "Storage operational", "Sharing ready"],
        "tappit": ["Nextcloud synced bru", "Files sorted hey", "Storage lekker né", "Sharing sharp"],
        "comedian": ["Nextcloud surprisingly synced", "Files unexpectedly uploaded", "Storage miraculously working", "Sharing shockingly functional"],
        "action": ["Nextcloud secured", "File sync complete", "Storage operational", "Sharing deployed"],
    },
    
    # Immich responses
    ("immich", "completed"): {
        "jarvis": ["Photo synchronization complete", "Image library indexed", "ML processing finished", "Backup operational"],
        "dude": ["Immich synced smooth", "Photos flowing nice", "Library vibing indexed", "Backup cruising"],
        "chick": ["Immich synced beautifully", "Photos gorgeous", "Library perfect", "Backup fab"],
        "nerd": ["Photo EXIF parsed", "Machine learning inference complete", "Face recognition indexed", "Timeline generated"],
        "rager": ["Immich finally synced", "Photos uploaded", "Library indexed", "Backup done"],
        "ops": ["Immich synchronized", "Photos indexed", "Library ready", "Backup complete"],
        "tappit": ["Immich synced bru", "Photos sorted hey", "Library lekker né", "Backup sharp"],
        "comedian": ["Immich surprisingly fast", "Photos unexpectedly organized", "Library miraculously indexed", "Backup shockingly complete"],
        "action": ["Immich secured", "Photo sync complete", "Library operational", "Backup deployed"],
    },
    
    # Paperless responses
    ("paperless", "completed"): {
        "jarvis": ["Document ingestion complete", "OCR processing successful", "Document indexed", "Archive operational"],
        "dude": ["Paperless processed smooth", "Docs flowing indexed", "OCR vibing done", "Archive cruising"],
        "chick": ["Paperless processed beautifully", "Docs indexed perfectly", "OCR gorgeous", "Archive fab"],
        "nerd": ["OCR accuracy optimal", "Document metadata extracted", "Full-text search indexed", "Tags auto-assigned"],
        "rager": ["Paperless finally done", "Docs processed", "OCR complete", "Archive ready"],
        "ops": ["Paperless complete", "Documents indexed", "OCR done", "Archive ready"],
        "tappit": ["Paperless done bru", "Docs sorted hey", "OCR lekker né", "Archive sharp"],
        "comedian": ["Paperless surprisingly paperless", "Docs unexpectedly digital", "OCR miraculously accurate", "Archive shockingly organized"],
        "action": ["Paperless secured", "Document processing complete", "OCR operational", "Archive deployed"],
    },
    
    # Pi-hole responses
    ("pihole", "completed"): {
        "jarvis": ["DNS filtering operational", "Ad blocking active", "Blocklist updated", "Query logging enabled"],
        "dude": ["Pi-hole cruising smooth", "Ads blocked nice", "DNS flowing clean", "Blocklist vibing"],
        "chick": ["Pi-hole running beautifully", "Ads blocked perfectly", "DNS gorgeous", "Blocklist fab"],
        "nerd": ["DNS cache hit ratio optimal", "Gravity database updated", "FTLDNS operational", "Blocklist domains parsed"],
        "rager": ["Pi-hole finally working", "Ads blocked", "DNS filtering active", "Blocklist updated"],
        "ops": ["Pi-hole operational", "Ad blocking active", "DNS filtering ready", "Blocklist current"],
        "tappit": ["Pi-hole lekker bru", "Ads blocked hey", "DNS sorted né", "Blocklist sharp"],
        "comedian": ["Pi-hole surprisingly effective", "Ads unexpectedly blocked", "DNS miraculously clean", "Blocklist shockingly comprehensive"],
        "action": ["Pi-hole secured", "Ad blocking deployed", "DNS filtering operational", "Blocklist mission complete"],
    },
    
    # Grafana responses
    ("grafana", "completed"): {
        "jarvis": ["Dashboard rendering complete", "Data visualization operational", "Metrics displayed", "Alerts configured"],
        "dude": ["Grafana cruising smooth", "Dashboards vibing nice", "Metrics flowing good", "Alerts all set"],
        "chick": ["Grafana running beautifully", "Dashboards gorgeous", "Metrics perfect", "Alerts fab"],
        "nerd": ["Time series query executed", "Panel rendering optimal", "Data source connected", "Alert threshold configured"],
        "rager": ["Grafana finally working", "Dashboards rendered", "Metrics displayed", "Alerts set"],
        "ops": ["Grafana operational", "Dashboards ready", "Metrics active", "Alerts configured"],
        "tappit": ["Grafana lekker bru", "Dashboards sorted hey", "Metrics sharp né", "Alerts good"],
        "comedian": ["Grafana surprisingly pretty", "Dashboards unexpectedly useful", "Metrics miraculously accurate", "Alerts shockingly functional"],
        "action": ["Grafana secured", "Dashboard deployment complete", "Metrics operational", "Alerts deployed"],
    },
    
    # Homepage/Dashboard responses
    ("homepage", "completed"): {
        "jarvis": ["Dashboard operational", "Services indexed", "Widgets configured", "Status monitoring active"],
        "dude": ["Dashboard cruising smooth", "Services vibing displayed", "Widgets flowing nice", "Status all good"],
        "chick": ["Dashboard running beautifully", "Services displayed perfectly", "Widgets gorgeous", "Status fab"],
        "nerd": ["Service discovery complete", "API endpoints validated", "Widget refresh rate optimal", "Status checks nominal"],
        "rager": ["Dashboard finally working", "Services displayed", "Widgets configured", "Status active"],
        "ops": ["Dashboard operational", "Services indexed", "Widgets ready", "Status monitoring active"],
        "tappit": ["Dashboard lekker bru", "Services sorted hey", "Widgets sharp né", "Status good"],
        "comedian": ["Dashboard surprisingly organized", "Services unexpectedly accessible", "Widgets miraculously configured", "Status shockingly useful"],
        "action": ["Dashboard secured", "Service indexing complete", "Widgets deployed", "Status operational"],
    },
    
    # Authentik responses  
    ("authentik", "completed"): {
        "jarvis": ["Authentication service operational", "SSO configuration active", "User provisioning complete", "OAuth flows enabled"],
        "dude": ["Authentik cruising smooth", "SSO flowing nice", "Users vibing provisioned", "OAuth all set"],
        "chick": ["Authentik running beautifully", "SSO perfect", "Users provisioned gorgeous", "OAuth fab"],
        "nerd": ["LDAP sync complete", "SAML assertions validated", "OAuth2 tokens issued", "User directory indexed"],
        "rager": ["Authentik finally working", "SSO active", "Users provisioned", "OAuth enabled"],
        "ops": ["Authentik operational", "SSO configured", "Users provisioned", "OAuth ready"],
        "tappit": ["Authentik lekker bru", "SSO sorted hey", "Users sharp né", "OAuth good"],
        "comedian": ["Authentik surprisingly authentic", "SSO unexpectedly single", "Users miraculously provisioned", "OAuth shockingly authorized"],
        "action": ["Authentik secured", "SSO deployed", "User provisioning complete", "OAuth operational"],
    },
}

# MASSIVE GENERIC RESPONSE BANKS - More varied and natural
_GENERIC_RESPONSES = {
    "completed": {
        "jarvis": ["Operation completed successfully", "Task execution finished", "Process concluded nominally", "Activity finalized",
                   "Procedure complete", "Execution successful", "Task accomplished", "Operation finalized", "Process finished",
                   "Activity concluded", "Mission complete", "Task delivered", "Operation successful", "Procedure accomplished"],
        "dude": ["All done smooth", "Wrapped up nice", "Finished flowing easy", "Task vibing complete", "Done cruising",
                 "Completed mellow", "All wrapped smooth", "Finished easy", "Task done flowing", "Complete and chill",
                 "All good man", "Wrapped nicely", "Done smooth sailing", "Task completed easy"],
        "chick": ["Completed beautifully", "Finished perfectly", "Done gorgeously", "Task looking fabulous", "Completed with style",
                  "Finished elegantly", "Done beautifully", "Task perfectly complete", "Accomplished gorgeously", "Completed fab",
                  "Finished with grace", "Done stunningly", "Task elegantly finished", "Completed radiant"],
        "nerd": ["Task execution nominal", "Process termination successful", "Operation metrics optimal", "Completion verified",
                 "Execution parameters met", "Task successfully terminated", "Process completion validated", "Operation finalized successfully",
                 "Metrics within tolerances", "Task completion verified", "Process successfully executed", "Operation nominal"],
        "rager": ["Finally fucking done", "Task completed", "Finished goddammit", "Done at last", "Task fucking finished",
                  "Completed finally", "Done thank god", "Task finished", "Wrapped up", "Done already",
                  "Finished finally", "Task done", "Completed now", "Done at fucking last"],
        "ops": ["Task complete", "Operation finished", "Process done", "Activity completed", "Task finalized",
                "Operation complete", "Process finished", "Activity done", "Task accomplished", "Operation finalized",
                "Process complete", "Activity finished", "Task done", "Operation accomplished"],
        "tappit": ["Task done bru", "Completed lekker", "Finished sharp hey", "Done sorted né", "Task lekker complete",
                   "Completed sharp", "Finished all good", "Done bru", "Task sorted hey", "Completed né",
                   "Finished lekker bru", "Done sharp sharp", "Task all good", "Completed sorted"],
        "comedian": ["Task ironically complete", "Finished unexpectedly", "Done surprisingly well", "Task miraculously accomplished",
                     "Completed against odds", "Finished shockingly", "Done unexpectedly", "Task surprisingly finished",
                     "Completed miraculously", "Finished predictably", "Done with irony", "Task deadpan complete"],
        "action": ["Mission accomplished", "Task secured", "Operation complete", "Objective achieved", "Mission finalized",
                   "Task executed", "Operation successful", "Objective secured", "Mission complete", "Task accomplished",
                   "Operation finalized", "Objective complete", "Mission executed", "Task secured successfully"],
    },
    "started": {
        "jarvis": ["Operation initiated", "Process beginning", "Task commenced", "Activity starting", "Procedure initiated",
                   "Execution beginning", "Operation commencing", "Process starting", "Task initiating", "Activity commencing",
                   "Procedure starting", "Execution commenced", "Operation beginning", "Process initiated"],
        "dude": ["Starting up smooth", "Getting going", "Kicking off easy", "Beginning to flow", "Starting mellow",
                 "Getting rolling", "Kicking in smooth", "Beginning easy", "Starting to vibe", "Getting going smooth",
                 "Kicking off chill", "Beginning to cruise", "Starting smooth", "Getting underway"],
        "chick": ["Starting beautifully", "Beginning elegantly", "Kicking off gorgeously", "Starting with style", "Beginning fab",
                  "Kicking off perfectly", "Starting gracefully", "Beginning stunningly", "Kicking off beautifully", "Starting radiant",
                  "Beginning gorgeously", "Kicking off elegantly", "Starting perfectly", "Beginning with grace"],
        "nerd": ["Process initialization", "Task spawning", "Operation bootstrapping", "Execution commenced", "Process starting",
                 "Task initialization begun", "Operation commenced", "Execution initiated", "Process begun", "Task spawned",
                 "Operation initialized", "Execution starting", "Process initiated", "Task commenced"],
        "rager": ["Starting this shit", "Kicking off", "Beginning already", "Starting goddammit", "Kicking in",
                  "Beginning now", "Starting up", "Kicking off finally", "Beginning this", "Starting it",
                  "Kicking in now", "Beginning already", "Starting again", "Kicking off now"],
        "ops": ["Task initiated", "Operation starting", "Process begun", "Activity commenced", "Task beginning",
                "Operation initiated", "Process starting", "Activity begun", "Task commenced", "Operation commencing",
                "Process initiated", "Activity starting", "Task starting", "Operation beginning"],
        "tappit": ["Starting bru", "Kicking off hey", "Beginning sharp", "Starting lekker", "Kicking in né",
                   "Beginning sorted", "Starting now bru", "Kicking off sharp", "Beginning hey", "Starting sorted",
                   "Kicking in lekker", "Beginning bru", "Starting sharp", "Kicking off né"],
        "comedian": ["Reluctantly starting", "Beginning ironically", "Kicking off surprisingly", "Starting unexpectedly", "Beginning with irony",
                     "Kicking off predictably", "Starting against will", "Beginning shockingly", "Kicking off deadpan", "Starting miraculously",
                     "Beginning satirically", "Kicking off absurdly", "Starting with satire", "Beginning comedically"],
        "action": ["Mission initiated", "Task deployed", "Operation launched", "Objective commenced", "Mission starting",
                   "Task initiated", "Operation commencing", "Objective beginning", "Mission commencing", "Task launched",
                   "Operation initiated", "Objective starting", "Mission beginning", "Task commencing"],
    },
    "failed": {
        "jarvis": ["Operation failure detected", "Task execution error", "Process malfunction", "Activity disrupted", "Procedure failed",
                   "Execution error", "Operation unsuccessful", "Process failed", "Task malfunction", "Activity error",
                   "Procedure disrupted", "Execution failed", "Operation error", "Process unsuccessful"],
        "dude": ["Hit a snag man", "Not flowing right", "Having issues", "Something's off", "Not cruising smooth",
                 "Problems detected", "Not vibing", "Issues happening", "Flow interrupted", "Having troubles",
                 "Snag detected", "Not flowing", "Problems man", "Issues found"],
        "chick": ["Needs attention", "Not looking good", "Having problems", "Struggling here", "Needs help",
                  "Not working well", "Issues detected", "Problems found", "Needs fixing", "Not performing well",
                  "Having difficulties", "Needs support", "Problems happening", "Struggling now"],
        "nerd": ["Fatal exception", "Process terminated abnormally", "Critical error detected", "System fault", "Execution failure",
                 "Runtime error", "Process crash", "System exception", "Fatal error", "Abnormal termination",
                 "Critical fault", "Execution exception", "Process failure", "System error"],
        "rager": ["Totally fucked", "Shit's broken", "Failed hard", "Complete disaster", "Fucking broken",
                  "Utterly failed", "Broken as hell", "Failed goddammit", "Total clusterfuck", "Completely screwed",
                  "Shit the bed", "Failed miserably", "Broken badly", "Fucking failed"],
        "ops": ["Task failed", "Operation error", "Process failure", "Activity error", "Task unsuccessful",
                "Operation failed", "Process error", "Activity failed", "Task error", "Operation unsuccessful",
                "Process unsuccessful", "Activity unsuccessful", "Task failure", "Operation failure"],
        "tappit": ["Is kak bru", "Broken hey", "Failed né", "Not lekker", "Broken badly bru",
                   "Failed hard hey", "Is kak né", "Not working bru", "Broken completely", "Failed badly hey",
                   "Is totally kak", "Broken né", "Failed bru", "Not lekker hey"],
        "comedian": ["Dramatically failed", "Unexpectedly broken", "Ironically crashed", "Predictably dead", "Satirically failed",
                     "Absurdly broken", "Deadpan error", "Comedically crashed", "Ironically dead", "Surprisingly failed",
                     "Predictably broken", "Absurdly crashed", "Satirically dead", "Deadpan failed"],
        "action": ["Mission failed", "Target compromised", "Operation unsuccessful", "Objective failed", "Mission unsuccessful",
                   "Target lost", "Operation failed", "Objective compromised", "Mission compromised", "Target failed",
                   "Operation lost", "Objective unsuccessful", "Mission error", "Target down"],
    },
    "warning": {
        "jarvis": ["Advisory condition", "Caution recommended", "Warning threshold reached", "Alert status", "Advisory issued",
                   "Caution advised", "Warning detected", "Alert condition", "Advisory active", "Caution status",
                   "Warning threshold", "Alert issued", "Advisory condition detected", "Caution recommended"],
        "dude": ["Heads up man", "Might wanna check", "Little concerning", "Watch this", "Keep an eye",
                 "Heads up", "Check this out", "Bit worrying", "Monitor this", "Worth watching",
                 "Pay attention", "Look at this", "Slightly concerning", "Watch out"],
        "chick": ["Needs attention", "Little concern", "Worth checking", "Might need help", "Should look at",
                  "Needs checking", "Some concern", "Worth attention", "Could need help", "Should check",
                  "Needs review", "Bit concerning", "Worth looking at", "Might need attention"],
        "nerd": ["Threshold breach detected", "Parameter deviation", "Anomaly identified", "Metric outlier", "Warning condition",
                 "Threshold exceeded", "Parameter anomaly", "Statistical outlier", "Metric deviation", "Warning threshold",
                 "Threshold violation", "Parameter warning", "Anomaly detected", "Metric warning"],
        "rager": ["Potential problem", "Might be fucked", "Could be bad", "Watching this shit", "Possible clusterfuck",
                  "Might break", "Could fail", "Watching closely", "Potential disaster", "Might fuck up",
                  "Could be trouble", "Warning bullshit", "Possible problem", "Might be bad"],
        "ops": ["Warning detected", "Caution advised", "Alert issued", "Warning condition", "Caution status",
                "Alert detected", "Warning active", "Caution condition", "Alert status", "Warning issued",
                "Caution detected", "Alert active", "Warning status", "Caution active"],
        "tappit": ["Watch this bru", "Bit concerning hey", "Check it né", "Monitor bru", "Keep eye hey",
                   "Watch closely bru", "Concerning né", "Check this hey", "Monitor closely", "Keep watching bru",
                   "Heads up hey", "Bit worrying né", "Watch it bru", "Check closely hey"],
        "comedian": ["Ironically concerning", "Surprisingly worrying", "Predictably alarming", "Absurdly cautious", "Deadpan warning",
                     "Satirically alarming", "Comedically concerning", "Ironically alarming", "Absurdly worrying", "Predictably concerning",
                     "Deadpan caution", "Satirically concerning", "Comedically alarming", "Ironically cautious"],
        "action": ["Threat detected", "Caution advised", "Alert status", "Warning condition", "Threat level raised",
                   "Caution status", "Alert condition", "Warning issued", "Threat active", "Caution condition",
                   "Alert advised", "Warning status", "Threat condition", "Caution advised"],
    },
    "updated": {
        "jarvis": ["System updated", "Configuration modified", "Settings refreshed", "Parameters adjusted", "System modified",
                   "Configuration updated", "Settings adjusted", "Parameters refreshed", "System refreshed", "Configuration adjusted",
                   "Settings modified", "Parameters updated", "System adjusted", "Configuration refreshed"],
        "dude": ["Updated smooth", "Refreshed easy", "Modified nicely", "Adjusted well", "Updated flowing",
                 "Refreshed smooth", "Modified easy", "Adjusted mellow", "Updated easy", "Refreshed nicely",
                 "Modified smooth", "Adjusted easy", "Updated nicely", "Refreshed flowing"],
        "chick": ["Updated beautifully", "Refreshed perfectly", "Modified elegantly", "Adjusted gorgeously", "Updated fab",
                  "Refreshed beautifully", "Modified perfectly", "Adjusted elegantly", "Updated gorgeously", "Refreshed fab",
                  "Modified beautifully", "Adjusted perfectly", "Updated elegantly", "Refreshed gorgeously"],
        "nerd": ["Configuration state changed", "System parameters modified", "Settings updated successfully", "Configuration refreshed", "Parameters adjusted",
                 "System state modified", "Configuration parameters updated", "Settings state changed", "Parameters modified", "System configuration updated",
                 "Configuration successfully modified", "Settings parameters adjusted", "System successfully updated", "Configuration state modified"],
        "rager": ["Updated finally", "Changed goddammit", "Modified at last", "Adjusted now", "Updated already",
                  "Changed finally", "Modified now", "Adjusted finally", "Updated done", "Changed at last",
                  "Modified finally", "Adjusted done", "Updated now", "Changed now"],
        "ops": ["System updated", "Configuration changed", "Settings modified", "Parameters adjusted", "Update complete",
                "Configuration updated", "Settings changed", "Parameters modified", "System modified", "Configuration modified",
                "Settings updated", "Parameters changed", "Update applied", "Configuration applied"],
        "tappit": ["Updated bru", "Refreshed hey", "Modified né", "Adjusted sharp", "Updated lekker",
                   "Refreshed bru", "Modified hey", "Adjusted né", "Updated sharp", "Refreshed lekker",
                   "Modified bru", "Adjusted hey", "Updated né", "Refreshed sharp"],
        "comedian": ["Surprisingly updated", "Unexpectedly refreshed", "Ironically modified", "Predictably adjusted", "Absurdly updated",
                     "Satirically refreshed", "Comedically modified", "Deadpan adjusted", "Ironically updated", "Absurdly refreshed",
                     "Predictably modified", "Satirically adjusted", "Comedically updated", "Deadpan refreshed"],
        "action": ["System secured", "Configuration updated", "Settings deployed", "Parameters adjusted", "Update executed",
                   "Configuration deployed", "Settings secured", "Parameters executed", "System deployed", "Configuration executed",
                   "Settings updated", "Parameters deployed", "Update secured", "Configuration secured"],
    },
    "restarted": {
        "jarvis": ["System reinitialized", "Services cycled", "Operations reset", "Process restarted", "System cycled",
                   "Services reset", "Operations restarted", "Process cycled", "System reset", "Services restarted",
                   "Operations cycled", "Process reset", "System restarted", "Services cycled"],
        "dude": ["Restarted smooth", "Cycled easy", "Reset flowing", "Rebooted mellow", "Restarted easy",
                 "Cycled smooth", "Reset easy", "Rebooted smooth", "Restarted flowing", "Cycled mellow",
                 "Reset smooth", "Rebooted easy", "Restarted mellow", "Cycled flowing"],
        "chick": ["Restarted beautifully", "Cycled perfectly", "Reset elegantly", "Rebooted gorgeously", "Restarted fab",
                  "Cycled beautifully", "Reset perfectly", "Rebooted elegantly", "Restarted gorgeously", "Cycled fab",
                  "Reset beautifully", "Rebooted perfectly", "Restarted elegantly", "Cycled gorgeously"],
        "nerd": ["Process respawned", "Services reinitialized", "System cold boot", "Runtime reset", "Process restarted",
                 "Services cycled", "System reinitialized", "Runtime cycled", "Process cycled", "Services respawned",
                 "System reset", "Runtime restarted", "Process reinitialized", "Services cold boot"],
        "rager": ["Restarted again", "Cycled goddammit", "Reset fucking again", "Rebooted already", "Restarted now",
                  "Cycled again", "Reset again", "Rebooted goddammit", "Restarted finally", "Cycled now",
                  "Reset now", "Rebooted again", "Restarted goddammit", "Cycled finally"],
        "ops": ["System restarted", "Services cycled", "Process reset", "Restart complete", "System cycled",
                "Services reset", "Process restarted", "Restart executed", "System reset", "Services restarted",
                "Process cycled", "Restart applied", "System reboot", "Services reboot"],
        "tappit": ["Restarted bru", "Cycled hey", "Reset né", "Rebooted sharp", "Restarted lekker",
                   "Cycled bru", "Reset hey", "Rebooted né", "Restarted sharp", "Cycled lekker",
                   "Reset bru", "Rebooted hey", "Restarted né", "Cycled sharp"],
        "comedian": ["Reluctantly restarted", "Grudgingly cycled", "Ironically reset", "Predictably rebooted", "Absurdly restarted",
                     "Satirically cycled", "Comedically reset", "Deadpan rebooted", "Ironically cycled", "Absurdly reset",
                     "Predictably restarted", "Satirically rebooted", "Comedically cycled", "Deadpan restarted"],
        "action": ["System tactical reset", "Services redeployed", "Operation cycled", "Restart executed", "System redeployed",
                   "Services cycled", "Operation reset", "Restart secured", "System cycled", "Services reset",
                   "Operation restarted", "Restart deployed", "System reset", "Services executed"],
    },
    "connected": {
        "jarvis": ["Connection established", "Link operational", "Network active", "Service online", "Connection active",
                   "Link established", "Network operational", "Service active", "Connection operational", "Link active",
                   "Network established", "Service operational", "Connection online", "Link online"],
        "dude": ["Connected smooth", "Link flowing", "Network vibing", "Online easy", "Connected easy",
                 "Link smooth", "Network flowing", "Online smooth", "Connected flowing", "Link easy",
                 "Network smooth", "Online flowing", "Connected vibing", "Link vibing"],
        "chick": ["Connected beautifully", "Link perfect", "Network gorgeous", "Online fab", "Connected elegantly",
                  "Link beautifully", "Network perfect", "Online gorgeously", "Connected perfectly", "Link elegantly",
                  "Network beautifully", "Online elegantly", "Connected gorgeously", "Link gorgeously"],
        "nerd": ["Handshake complete", "Protocol established", "Connection authenticated", "Link synchronized", "Network joined",
                 "Handshake successful", "Protocol active", "Connection verified", "Link established", "Network synchronized",
                 "Handshake established", "Protocol operational", "Connection operational", "Link verified"],
        "rager": ["Connected finally", "Link up now", "Network online", "Online goddammit", "Connected now",
                  "Link finally up", "Network finally", "Online now", "Connected at last", "Link goddammit",
                  "Network now", "Online finally", "Connected goddammit", "Link now"],
        "ops": ["Connection active", "Link established", "Network online", "Service connected", "Connection established",
                "Link active", "Network connected", "Service online", "Connection online", "Link operational",
                "Network active", "Service established", "Connection operational", "Link online"],
        "tappit": ["Connected bru", "Link lekker", "Network sharp", "Online né", "Connected sharp",
                   "Link bru", "Network lekker", "Online bru", "Connected lekker", "Link né",
                   "Network bru", "Online sharp", "Connected né", "Link sharp"],
        "comedian": ["Surprisingly connected", "Unexpectedly online", "Ironically linked", "Predictably active", "Absurdly connected",
                     "Satirically online", "Comedically linked", "Deadpan active", "Ironically connected", "Absurdly online",
                     "Predictably linked", "Satirically connected", "Comedically online", "Deadpan linked"],
        "action": ["Connection secured", "Link operational", "Network established", "Service active", "Connection deployed",
                   "Link secured", "Network operational", "Service established", "Connection operational", "Link deployed",
                   "Network secured", "Service operational", "Connection established", "Link established"],
    },
    "disconnected": {
        "jarvis": ["Connection terminated", "Link offline", "Network disconnected", "Service unavailable", "Connection lost",
                   "Link terminated", "Network offline", "Service disconnected", "Connection offline", "Link lost",
                   "Network terminated", "Service offline", "Connection unavailable", "Link unavailable"],
        "dude": ["Disconnected man", "Link dropped", "Network down", "Offline now", "Disconnected now",
                 "Link down man", "Network offline", "Offline man", "Disconnected dropped", "Link offline",
                 "Network down man", "Offline down", "Disconnected offline", "Link lost"],
        "chick": ["Disconnected sadly", "Link down", "Network offline", "Offline unfortunately", "Disconnected down",
                  "Link offline sadly", "Network down", "Offline sadly", "Disconnected unfortunately", "Link unfortunately",
                  "Network offline sadly", "Offline down", "Disconnected offline", "Link down"],
        "nerd": ["Connection timeout", "Link failure", "Network unreachable", "Service terminated", "Connection refused",
                 "Link timeout", "Network failure", "Service unreachable", "Connection terminated", "Link refused",
                 "Network timeout", "Service failure", "Connection unreachable", "Link terminated"],
        "rager": ["Disconnected goddammit", "Link dead", "Network fucked", "Offline shit", "Disconnected fuck",
                  "Link down goddammit", "Network down fuck", "Offline goddammit", "Disconnected dead", "Link fucked",
                  "Network dead", "Offline fuck", "Disconnected down", "Link goddammit"],
        "ops": ["Connection lost", "Link down", "Network offline", "Service disconnected", "Connection offline",
                "Link offline", "Network down", "Service offline", "Connection down", "Link lost",
                "Network lost", "Service down", "Connection unavailable", "Link unavailable"],
        "tappit": ["Disconnected bru", "Link down hey", "Network offline né", "Offline bru", "Disconnected hey",
                   "Link offline bru", "Network down né", "Offline hey", "Disconnected né", "Link down bru",
                   "Network offline hey", "Offline né", "Disconnected down", "Link offline hey"],
        "comedian": ["Predictably disconnected", "Ironically offline", "Absurdly down", "Satirically lost", "Comedically disconnected",
                     "Deadpan offline", "Ironically down", "Absurdly offline", "Predictably down", "Satirically disconnected",
                     "Comedically offline", "Deadpan down", "Ironically lost", "Absurdly disconnected"],
        "action": ["Connection lost", "Link compromised", "Network down", "Service offline", "Connection terminated",
                   "Link down", "Network compromised", "Service lost", "Connection down", "Link terminated",
                   "Network lost", "Service compromised", "Connection compromised", "Link lost"],
    },
    "stopped": {
        "jarvis": ["Service terminated", "Operations halted", "Process stopped", "Activity ceased", "Service stopped",
                   "Operations terminated", "Process halted", "Activity stopped", "Service halted", "Operations stopped",
                   "Process ceased", "Activity terminated", "Service ceased", "Operations ceased"],
        "dude": ["Stopped smooth", "Halted easy", "Shut down mellow", "Ceased flowing", "Stopped easy",
                 "Halted smooth", "Shut down easy", "Ceased smooth", "Stopped flowing", "Halted mellow",
                 "Shut down smooth", "Ceased easy", "Stopped mellow", "Halted flowing"],
        "chick": ["Stopped gracefully", "Halted beautifully", "Shut down elegantly", "Ceased perfectly", "Stopped elegantly",
                  "Halted gracefully", "Shut down beautifully", "Ceased elegantly", "Stopped perfectly", "Halted elegantly",
                  "Shut down gracefully", "Ceased beautifully", "Stopped beautifully", "Halted perfectly"],
        "nerd": ["Process terminated", "Service shutdown complete", "Operation ceased", "Task killed", "Process stopped",
                 "Service terminated", "Operation halted", "Task terminated", "Process halted", "Service stopped",
                 "Operation stopped", "Task stopped", "Process shutdown", "Service halted"],
        "rager": ["Stopped finally", "Halted goddammit", "Shut down now", "Ceased already", "Stopped now",
                  "Halted finally", "Shut down finally", "Ceased now", "Stopped goddammit", "Halted now",
                  "Shut down goddammit", "Ceased finally", "Stopped already", "Halted already"],
        "ops": ["Service stopped", "Operations halted", "Process terminated", "Activity ceased", "Service terminated",
                "Operations stopped", "Process stopped", "Activity halted", "Service halted", "Operations terminated",
                "Process halted", "Activity stopped", "Service ceased", "Operations ceased"],
        "tappit": ["Stopped bru", "Halted hey", "Shut down né", "Ceased sharp", "Stopped lekker",
                   "Halted bru", "Shut down hey", "Ceased né", "Stopped sharp", "Halted lekker",
                   "Shut down bru", "Ceased hey", "Stopped né", "Halted sharp"],
        "comedian": ["Reluctantly stopped", "Grudgingly halted", "Ironically ceased", "Predictably shutdown", "Absurdly stopped",
                     "Satirically halted", "Comedically ceased", "Deadpan shutdown", "Ironically halted", "Absurdly ceased",
                     "Predictably stopped", "Satirically shutdown", "Comedically halted", "Deadpan stopped"],
        "action": ["Mission terminated", "Operations ceased", "Service shutdown", "Task completed", "Mission stopped",
                   "Operations halted", "Service halted", "Task terminated", "Mission halted", "Operations stopped",
                   "Service terminated", "Task stopped", "Mission ceased", "Operations terminated"],
    },
    "status": {
        "jarvis": ["Status nominal", "Systems operational", "Operations normal", "All systems green", "Status optimal",
                   "Systems stable", "Operations steady", "All nominal", "Status stable", "Systems normal",
                   "Operations optimal", "All stable", "Status operational", "Systems steady"],
        "dude": ["All good man", "Cruising smooth", "Vibing well", "Flowing easy", "All chill",
                 "Cruising easy", "Vibing smooth", "Flowing well", "All smooth", "Cruising well",
                 "Vibing easy", "Flowing smooth", "All easy", "Cruising vibes"],
        "chick": ["Looking fabulous", "Running beautifully", "Performing gorgeously", "Operating perfectly", "Looking perfect",
                  "Running fab", "Performing beautifully", "Operating gorgeously", "Looking gorgeous", "Running perfectly",
                  "Performing fab", "Operating beautifully", "Looking beautifully", "Running gorgeously"],
        "nerd": ["All parameters nominal", "Systems within spec", "Metrics optimal", "Performance nominal", "Parameters stable",
                 "Systems optimal", "Metrics stable", "Performance optimal", "Parameters nominal", "Systems stable",
                 "Metrics nominal", "Performance stable", "Parameters optimal", "Systems nominal"],
        "rager": ["Shit's working", "Running fine", "Functioning normally", "Working properly", "Shit's functional",
                  "Running ok", "Functioning fine", "Working ok", "Shit's running", "Running properly",
                  "Functioning ok", "Working fine", "Shit's ok", "Running functional"],
        "ops": ["Status green", "Systems operational", "All normal", "Operations nominal", "Status operational",
                "Systems green", "All operational", "Operations green", "Status normal", "Systems nominal",
                "All green", "Operations operational", "Status stable", "Systems stable"],
        "tappit": ["All lekker bru", "Running sharp", "Good vibes né", "All sorted hey", "All good bru",
                   "Running lekker", "Good sharp né", "All lekker hey", "Running sorted", "Good bru",
                   "All sharp né", "Running good hey", "All sorted bru", "Good lekker"],
        "comedian": ["Remarkably boring", "Uneventfully stable", "Thrillingly normal", "Suspensefully nominal", "Ironically stable",
                     "Predictably boring", "Absurdly normal", "Satirically stable", "Deadpan nominal", "Comedically boring",
                     "Ironically normal", "Absurdly stable", "Predictably nominal", "Satirically boring"],
        "action": ["All sectors secure", "Mission nominal", "Operations green", "Status secured", "All operational",
                   "Mission green", "Operations secure", "Status nominal", "All secure", "Mission operational",
                   "Operations nominal", "Status green", "All nominal", "Mission secure"],
    },
    "scaling": {
        "jarvis": ["Capacity adjustment initiated", "Resource scaling active", "Instance modification underway", "Scaling operation commenced"],
        "dude": ["Scaling smooth", "Adjusting capacity easy", "Resizing flowing", "Scaling vibing well"],
        "chick": ["Scaling beautifully", "Capacity adjusting perfectly", "Resizing elegantly", "Scaling gorgeously"],
        "nerd": ["Horizontal scaling executed", "Resource allocation modified", "Instance count adjusted", "Capacity parameters changed"],
        "rager": ["Scaling this shit", "Adjusting capacity now", "Resizing goddammit", "Scaling finally"],
        "ops": ["Scaling initiated", "Capacity adjusting", "Resources modified", "Instance count changing"],
        "tappit": ["Scaling bru", "Adjusting sharp", "Resizing né", "Scaling lekker"],
        "comedian": ["Ironically scaling", "Surprisingly resizing", "Predictably adjusting", "Absurdly scaling"],
        "action": ["Scaling operation", "Capacity tactical adjustment", "Resource deployment", "Scaling mission active"],
    },
    "migrating": {
        "jarvis": ["Migration process initiated", "Data transfer underway", "System relocation active", "Migration commenced"],
        "dude": ["Migration flowing", "Moving data smooth", "Transferring easy", "Migrating vibes"],
        "chick": ["Migrating beautifully", "Transfer running perfectly", "Moving elegantly", "Migration gorgeous"],
        "nerd": ["Data migration executing", "Transfer protocol active", "System state replication", "Migration sequence running"],
        "rager": ["Migrating this shit", "Moving data now", "Transferring goddammit", "Migration finally"],
        "ops": ["Migration active", "Data transferring", "System relocating", "Migration in progress"],
        "tappit": ["Migrating bru", "Moving data hey", "Transferring né", "Migration lekker"],
        "comedian": ["Reluctantly migrating", "Ironically moving", "Predictably transferring", "Absurdly relocating"],
        "action": ["Migration operation", "Data extraction active", "Transfer mission", "Migration tactical"],
    },
}

def _generate_natural_header(persona: str, ctx: Dict, subject: str) -> str:
    """Generate natural, context-aware header"""
    try:
        daypart = ctx.get("daypart", "afternoon")
        service = ctx.get("primary_service")
        action = ctx.get("action", "status")
        urgency = ctx.get("urgency", 0)
        
        # Get greeting
        greetings = _GREETINGS.get(daypart, {}).get(persona, ["Update"])
        greeting = random.choice(greetings) if greetings else "Update"
        
        # Build status based on context
        if urgency >= 6:
            # Critical/failure - use service-specific or generic failure
            statuses = {
                "jarvis": [f"{service or 'system'} requires immediate attention", f"{service or 'service'} critical failure", f"{service or 'operations'} compromised"],
                "dude": [f"{service or 'system'} needs help man", f"{service or 'service'} having major issues", f"{service or 'system'} seriously stuck"],
                "chick": [f"{service or 'system'} needs urgent attention", f"{service or 'service'} critical issue", f"{service or 'system'} seriously struggling"],
                "nerd": [f"{service or 'service'} catastrophic failure", f"{service or 'system'} critical exception", f"{service or 'service'} fatal error state"],
                "rager": [f"{service or 'system'} is totally fucked", f"{service or 'service'} completely broken", f"{service or 'system'} fucking dead"],
                "ops": [f"{service or 'service'} critical failure", f"{service or 'system'} down", f"{service or 'service'} offline"],
                "tappit": [f"{service or 'system'} properly kak bru", f"{service or 'service'} completely broken hey", f"{service or 'system'} totally kaput né"],
                "comedian": [f"{service or 'system'} catastrophically failed", f"{service or 'service'} dramatically dead", f"{service or 'system'} epic failure mode"],
                "action": [f"{service or 'system'} critical breach", f"{service or 'service'} code red", f"{service or 'system'} emergency status"],
            }
        elif urgency >= 3:
            # Warning
            statuses = {
                "jarvis": [f"{service or 'system'} advisory condition", f"{service or 'service'} caution recommended", f"{service or 'system'} monitoring required"],
                "dude": [f"{service or 'system'} heads up", f"{service or 'service'} watch this", f"{service or 'system'} little concerning"],
                "chick": [f"{service or 'system'} needs checking", f"{service or 'service'} some concern", f"{service or 'system'} worth attention"],
                "nerd": [f"{service or 'service'} threshold breach", f"{service or 'system'} anomaly detected", f"{service or 'service'} parameter deviation"],
                "rager": [f"{service or 'system'} potential problem", f"{service or 'service'} might be fucked", f"{service or 'system'} watch this shit"],
                "ops": [f"{service or 'service'} warning", f"{service or 'system'} caution", f"{service or 'service'} alert"],
                "tappit": [f"{service or 'system'} watch it bru", f"{service or 'service'} bit concerning hey", f"{service or 'system'} check this né"],
                "comedian": [f"{service or 'system'} ironically concerning", f"{service or 'service'} surprisingly worrying", f"{service or 'system'} predictably alarming"],
                "action": [f"{service or 'system'} threat detected", f"{service or 'service'} caution advised", f"{service or 'system'} alert status"],
            }
        elif action in ["failed", "disconnected", "stopped"]:
            # Failure but lower urgency
            statuses = {
                "jarvis": [f"{service or 'system'} operation unsuccessful", f"{service or 'service'} failure detected", f"{service or 'system'} error condition"],
                "dude": [f"{service or 'system'} needs help", f"{service or 'service'} acting up", f"{service or 'system'} got issues"],
                "chick": [f"{service or 'system'} needs attention", f"{service or 'service'} issue detected", f"{service or 'system'} not looking good"],
                "nerd": [f"{service or 'service'} error detected", f"{service or 'system'} failure mode active", f"{service or 'service'} anomaly confirmed"],
                "rager": [f"{service or 'system'} is fucked", f"{service or 'service'} broke", f"{service or 'system'} shit the bed"],
                "ops": [f"{service or 'service'} down", f"{service or 'system'} failed", f"{service or 'service'} offline"],
                "tappit": [f"{service or 'system'} is kak", f"{service or 'service'} broken bru", f"{service or 'system'} not lekker"],
                "comedian": [f"{service or 'system'} dramatically failed", f"{service or 'service'} quit the show", f"{service or 'system'} unexpected plot twist"],
                "action": [f"{service or 'system'} compromised", f"{service or 'service'} mission critical", f"{service or 'system'} threat detected"],
            }
        else:
            # Normal/positive status
            statuses = {
                "jarvis": [f"{service or 'systems'} running smoothly", f"{service or 'operations'} stable", f"{service or 'systems'} operating normally", f"{service or 'services'} nominal"],
                "dude": [f"{service or 'system'} cruising", f"{service or 'setup'} flowing nice", f"{service or 'system'} vibing smooth", f"{service or 'everything'} chill"],
                "chick": [f"{service or 'system'} looking fabulous", f"{service or 'setup'} running beautifully", f"{service or 'system'} performing gorgeously", f"{service or 'everything'} perfect"],
                "nerd": [f"{service or 'system'} operating nominally", f"{service or 'metrics'} within bounds", f"{service or 'system'} performing optimally", f"{service or 'parameters'} stable"],
                "rager": [f"{service or 'shit'} working", f"{service or 'system'} running", f"{service or 'shit'} functioning", f"{service or 'everything'} ok"],
                "ops": [f"{service or 'system'} operational", f"{service or 'status'} green", f"{service or 'system'} stable", f"{service or 'services'} nominal"],
                "tappit": [f"{service or 'system'} lekker bru", f"{service or 'setup'} running smooth", f"{service or 'system'} all good", f"{service or 'everything'} sorted"],
                "comedian": [f"{service or 'system'} remarkably boring", f"{service or 'status'} uneventfully stable", f"{service or 'system'} thrillingly normal", f"{service or 'everything'} ironically fine"],
                "action": [f"{service or 'system'} secure", f"{service or 'operation'} stable", f"{service or 'system'} operational", f"{service or 'all sectors'} green"],
            }
        
        status = random.choice(statuses.get(persona, [f"{service or 'system'} operational"]))
        
        return f"{greeting}, {status}"
    except:
        return f"{subject or 'Update'}"

def _generate_intelligent_riff(persona: str, ctx: Dict, slot: int) -> str:
    """Generate intelligent riff with enhanced context awareness"""
    try:
        service = ctx.get("primary_service")
        action = ctx.get("action")
        
        # Try service-specific first
        key = (service, action)
        if key in _SERVICE_RESPONSES and persona in _SERVICE_RESPONSES[key]:
            return random.choice(_SERVICE_RESPONSES[key][persona])
        
        # Fall back to generic action responses
        if action in _GENERIC_RESPONSES and persona in _GENERIC_RESPONSES[action]:
            return random.choice(_GENERIC_RESPONSES[action][persona])
        
        # Final fallback to status
        return random.choice(_GENERIC_RESPONSES.get("status", {}).get(persona, ["Systems operational"]))
    except:
        return "Systems operational"

def lexi_quip(persona_name: str, *, with_emoji: bool = True, subject: str = "", body: str = "") -> str:
    """Generate natural conversational header with enhanced intelligence"""
    try:
        persona = _canon(persona_name)
        subj = strip_transport_tags((subject or "Update").strip().replace("\n"," "))[:120]
        ctx = _extract_smart_context(subject, body)
        header = _generate_natural_header(persona, ctx, subj)
        return f"{header}{_maybe_emoji(persona, with_emoji)}"
    except:
        return f"{subject or 'Update'}: ok"

def lexi_riffs(persona_name: str, n: int = 3, *, with_emoji: bool = False, subject: str = "", body: str = "") -> List[str]:
    """Generate intelligent riff lines with enhanced context"""
    try:
        persona = _canon(persona_name)
        ctx = _extract_smart_context(subject, body)
        out: List[str] = []
        attempts = 0
        
        while len(out) < n and attempts < n * 10:
            riff = _generate_intelligent_riff(persona, ctx, len(out))
            riff = re.sub(r"[\U0001F300-\U0001FAFF]", "", riff).strip()
            if riff and riff not in out and len(riff) <= 140:
                out.append(riff)
            attempts += 1
        
        while len(out) < n:
            out.append("Systems operational")
        
        return out[:n]
    except:
        return ["Status nominal", "Operations normal", "Systems stable"][:n]

def persona_header(persona_name: str, subject: str = "", body: str = "") -> str:
    """Generate natural persona header"""
    return lexi_quip(persona_name, with_emoji=True, subject=subject, body=body)

# LLM integration
_PROF_RE = re.compile(r"(?i)\b(fuck|shit|damn|asshole|bitch|bastard|dick|pussy|cunt)\b")

def _soft_censor(s: str) -> str:
    return _PROF_RE.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), s)

def _post_clean(lines: List[str], persona_key: str, allow_prof: bool) -> List[str]:
    if not lines:
        return []
    out: List[str] = []
    BAD = ("persona","rules","rule:","instruction","instruct","guideline","system prompt","style hint",
           "lines:","respond with","produce only","you are","jarvis prime","[system]","[input]","[output]")
    seen = set()
    for ln in lines:
        t = strip_transport_tags(ln.strip())
        if not t:
            continue
        low = t.lower()
        if any(b in low for b in BAD):
            continue
        if len(t) > 140:
            t = t[:140].rstrip()
        if persona_key != "rager" and not allow_prof:
            t = _soft_censor(t)
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
        if len(out) >= int(os.getenv("LLM_PERSONA_LINES_MAX", "3") or 3):
            break
    return out

def llm_quips(persona_name: str, *, context: str = "", max_lines: int = 3) -> List[str]:
    """Generate LLM riffs"""
    if os.getenv("BEAUTIFY_LLM_ENABLED", "true").lower() not in ("1","true","yes"):
        return []
    
    try:
        key = _canon(persona_name)
        context = strip_transport_tags((context or "").strip())
        if not context:
            return []
        allow_prof = (key == "rager") or (os.getenv("PERSONALITY_ALLOW_PROFANITY", "false").lower() in ("1","true","yes"))
        
        llm = importlib.import_module("llm_client")
        
        if hasattr(llm, "persona_riff"):
            try:
                lines = llm.persona_riff(
                    persona=key,
                    context=context,
                    max_lines=int(max_lines or 3),
                    timeout=int(os.getenv("LLM_TIMEOUT_SECONDS", "8")),
                    cpu_limit=int(os.getenv("LLM_MAX_CPU_PERCENT", "70")),
                )
                lines = _post_clean(lines, key, allow_prof)
                if lines:
                    return lines
            except Exception:
                pass
        
        return []
    except:
        return []

def quip(persona_name: str, *, with_emoji: bool = True) -> str:
    """Legacy compatibility"""
    return lexi_quip(persona_name, with_emoji=with_emoji, subject="Update", body="")

def build_header_and_riffs(persona_name: str, subject: str = "", body: str = "", max_riff_lines: int = 3) -> Tuple[str, List[str]]:
    """Build header and riffs with enhanced intelligence"""
    try:
        header = persona_header(persona_name, subject=subject, body=body)
        context = strip_transport_tags(" ".join([subject or "", body or ""]).strip())
        lines = llm_quips(persona_name, context=context, max_lines=max_riff_lines)
        if not lines:
            lines = lexi_riffs(persona_name, n=max_riff_lines, with_emoji=False, subject=subject, body=body)
        lines = [re.sub(r"[\U0001F300-\U0001FAFF]", "", ln).strip() for ln in lines]
        return header, lines
    except:
        return f"{subject or 'Update'}: ok", ["Status nominal", "Operations normal"]
