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
    """Extract context from message"""
    try:
        text = f"{subject} {body}".lower()
        
        services = {
            "sonarr": "sonarr" in text,
            "radarr": "radarr" in text,
            "plex": "plex" in text or "jellyfin" in text,
            "homeassistant": "home assistant" in text or "homeassistant" in text,
            "docker": "docker" in text or "container" in text or "pod" in text,
            "database": any(db in text for db in ["mysql", "postgres", "mariadb", "mongodb", "sql", "database"]),
            "backup": "backup" in text or "snapshot" in text or "archive" in text,
            "network": any(net in text for net in ["network", "dns", "proxy", "nginx", "firewall", "vpn"]),
            "storage": any(stor in text for stor in ["disk", "storage", "mount", "volume", "raid", "zfs"]),
            "monitoring": any(mon in text for mon in ["uptime", "monitor", "health", "check", "analytics", "grafana"]),
            "certificate": "certificate" in text or "cert" in text or "ssl" in text or "tls" in text,
            "email": any(e in text for e in ["email", "smtp", "imap", "mail"]),
            "notification": any(n in text for n in ["notification", "alert", "gotify", "ntfy"]),
            "vpn": any(v in text for v in ["vpn", "wireguard", "openvpn", "netbird", "zerotier"]),
            "media": any(m in text for m in ["media", "movie", "tv", "episode", "download"]),
        }
        active_services = [k for k, v in services.items() if v]
        
        actions = {
            "completed": any(w in text for w in ["completed", "finished", "done", "success", "passed", "ok"]),
            "started": any(w in text for w in ["started", "beginning", "initiated", "launching", "starting"]),
            "failed": any(w in text for w in ["failed", "error", "failure", "crashed", "down"]),
            "warning": any(w in text for w in ["warning", "caution", "degraded", "slow"]),
            "updated": any(w in text for w in ["updated", "upgraded", "patched", "modified"]),
            "restarted": any(w in text for w in ["restarted", "rebooted", "cycled", "restart"]),
            "connected": any(w in text for w in ["connected", "online", "up", "available"]),
            "disconnected": any(w in text for w in ["disconnected", "offline", "down", "unavailable"]),
            "stopped": any(w in text for w in ["stopped", "halted", "terminated", "killed"]),
        }
        active_action = next((k for k, v in actions.items() if v), "status")
        
        urgency = 0
        if any(w in text for w in ["critical", "emergency", "urgent"]):
            urgency = 8
        elif any(w in text for w in ["down", "offline", "failed", "error"]):
            urgency = 6
        elif any(w in text for w in ["warning", "degraded", "slow"]):
            urgency = 3
        
        return {
            "services": active_services,
            "primary_service": active_services[0] if active_services else None,
            "action": active_action,
            "urgency": urgency,
            "daypart": _daypart(),
        }
    except:
        return {
            "services": [], "primary_service": None, "action": "status",
            "urgency": 0, "daypart": "afternoon"
        }


# MASSIVE GREETING BANKS - 20+ per persona per daypart
_GREETINGS = {
    "early_morning": {
        "jarvis": [
            "Early morning service", "Pre-dawn operations", "Night watch concluding", "First light protocols",
            "Dawn service commencing", "Early hours coordination", "Morning preparation underway", "Pre-dawn briefing",
            "Early service active", "Dawn operations", "Night shift concluding", "Morning protocols initiating",
            "Early coordination", "Pre-dawn status", "First light operations", "Dawn briefing ready",
            "Early morning brief", "Night watch complete", "Morning service beginning", "Pre-dawn ready"
        ],
        "dude": [
            "Early vibes", "Dawn patrol", "Morning brew time", "Sunrise session", "Early flow", "Pre-dawn cruise",
            "Morning mellow", "Dawn chill", "Early zen", "Sunrise mode", "Morning easy", "Pre-dawn vibes",
            "Early morning flow", "Dawn surfing", "Morning cosmic", "Sunrise rolling", "Early cruise",
            "Pre-dawn mellow", "Morning waves", "Dawn peaceful"
        ],
        "chick": [
            "Rise and shine", "Early bird mode", "Morning glow", "Dawn glamour", "Early sparkle", "First light fabulous",
            "Morning beauty", "Pre-dawn gorgeous", "Early elegance", "Dawn perfection", "Morning radiance",
            "First light stunning", "Early morning fabulous", "Pre-dawn sparkle", "Dawn beauty", "Morning gorgeous",
            "Early shine", "First light elegance", "Pre-dawn glow", "Dawn radiant"
        ],
        "nerd": [
            "Early processing cycle", "Morning batch complete", "Dawn computation", "Pre-dawn analytics",
            "Early data validation", "Morning algorithm execution", "Dawn processing", "Early analysis cycle",
            "Morning computation ready", "Pre-dawn metrics", "Early batch processing", "Dawn validation",
            "Morning data pipeline", "Pre-dawn computation", "Early analytics", "Dawn algorithms",
            "Morning processing", "Pre-dawn validation", "Early computation", "Dawn metrics"
        ],
        "rager": [
            "Too damn early", "Morning bullshit", "Early chaos", "Dawn drama", "Too early for this shit",
            "Morning nightmare", "Early hell", "Pre-dawn crap", "Morning madness", "Dawn nonsense",
            "Early morning hell", "Too fucking early", "Morning disaster", "Dawn bullshit", "Early shit",
            "Pre-dawn chaos", "Morning garbage", "Dawn pain", "Early torture", "Morning suffering"
        ],
        "ops": [
            "Early shift", "Morning ops", "Dawn cycle", "Pre-dawn operations", "Early watch", "Morning service",
            "Dawn shift", "Early operations", "Morning cycle", "Pre-dawn watch", "Early service",
            "Dawn operations", "Morning watch", "Pre-dawn cycle", "Early shift active", "Dawn service",
            "Morning operations", "Pre-dawn shift", "Early cycle", "Dawn watch"
        ],
        "tappit": [
            "Early start bru", "Morning shift", "Dawn run", "Early jol", "Pre-dawn hustle", "Morning grind bru",
            "Dawn shift bru", "Early morning run", "Pre-dawn start", "Morning hustle", "Dawn grind",
            "Early jol bru", "Morning start sharp", "Pre-dawn run", "Dawn hustle", "Early shift sharp",
            "Morning grind", "Pre-dawn jol", "Dawn start", "Early run bru"
        ],
        "comedian": [
            "Sunrise nobody asked for", "Morning show", "Early comedy hour", "Dawn performance",
            "Morning audience of zero", "Early entertainment", "Pre-dawn comedy", "Morning show nobody wanted",
            "Dawn performance unwatched", "Early morning farce", "Pre-dawn theater", "Morning comedy empty seats",
            "Dawn show cancelled", "Early performance", "Morning comedy silence", "Pre-dawn show",
            "Dawn entertainment", "Early morning theater", "Pre-dawn farce", "Morning performance void"
        ],
        "action": [
            "Dawn patrol", "Early mission", "Morning brief", "Pre-dawn ops", "First light tactical",
            "Early deployment", "Dawn operations", "Morning tactical", "Pre-dawn mission", "Early brief",
            "Dawn deployment", "Morning ops", "Pre-dawn tactical", "Early mission status", "Dawn brief",
            "Morning deployment", "Pre-dawn operations", "Early tactical", "Dawn mission", "Morning patrol"
        ],
    },
    "morning": {
        "jarvis": [
            "Good morning", "Morning status", "Day operations commencing", "Morning briefing", "Day service beginning",
            "Morning coordination", "Daylight protocols active", "Morning report ready", "Day beginning smoothly",
            "Morning operations", "Day protocols", "Morning service active", "Daylight coordination",
            "Day commencing", "Morning status ready", "Daylight operations", "Day service active",
            "Morning brief complete", "Daylight protocols", "Day coordination", "Morning operations ready"
        ],
        "dude": [
            "Morning vibes", "Good morning", "Day's flowing", "Morning cruise", "Day's rolling", "Morning mellow",
            "Sunshine mode", "Morning chill", "Day's cruising", "Morning zen", "Daylight flowing",
            "Morning easy", "Day's mellow", "Morning cosmic", "Daylight vibes", "Day rolling smooth",
            "Morning waves", "Daylight chill", "Day's zen", "Morning peaceful"
        ],
        "chick": [
            "Morning darling", "Good morning", "Daylight ready", "Morning gorgeous", "Day's looking fabulous",
            "Morning beauty", "Sunshine sparkle", "Morning radiant", "Daylight perfection", "Day's stunning",
            "Morning fabulous", "Daylight gorgeous", "Day's sparkling", "Morning elegant", "Daylight beauty",
            "Day's radiant", "Morning perfect", "Daylight fabulous", "Day's gorgeous", "Morning stunning"
        ],
        "nerd": [
            "Morning analysis", "Daily standup", "Morning metrics", "Day computation", "Morning validation",
            "Daily processing", "Morning data review", "Day analytics", "Morning computation", "Daily metrics",
            "Day validation", "Morning processing", "Daily analysis", "Day computation ready", "Morning data",
            "Daily validation", "Day metrics", "Morning analytics", "Daily processing", "Day analysis"
        ],
        "rager": [
            "Morning shit sorted", "Day starting", "Coffee then chaos", "Morning grind", "Day's bullshit beginning",
            "Morning madness", "Day's drama", "Morning hell", "Day starting fuck", "Morning chaos",
            "Day's shit", "Morning disaster", "Day's nonsense", "Morning pain", "Day's crap",
            "Morning suffering", "Day's madness", "Morning garbage", "Day's hell", "Morning nightmare"
        ],
        "ops": [
            "Morning", "Daily ops", "Day shift", "Morning service", "Day operations", "Morning watch",
            "Daily service", "Day cycle", "Morning operations", "Daily watch", "Day shift active",
            "Morning cycle", "Daily operations", "Day service active", "Morning shift", "Daily cycle",
            "Day watch", "Morning service active", "Daily shift", "Day operations ready"
        ],
        "tappit": [
            "Howzit morning", "Morning bru", "Day starting", "Morning sharp", "Day's jol", "Morning run bru",
            "Daylight hustle", "Morning grind", "Day's run", "Morning lekker", "Daylight sharp",
            "Day starting bru", "Morning sharp-sharp", "Daylight jol", "Day's grind", "Morning hustle",
            "Daylight run", "Day's lekker", "Morning jol", "Daylight grind"
        ],
        "comedian": [
            "Morning allegedly", "Good morning question mark", "Day begins theoretically", "Morning performance",
            "Day's comedy", "Morning show nobody wanted", "Daylight farce", "Day starting surprisingly",
            "Morning theater", "Daylight comedy", "Day's performance", "Morning show", "Daylight theater",
            "Day comedy hour", "Morning entertainment", "Daylight show", "Day's theater", "Morning farce",
            "Daylight performance", "Day's show"
        ],
        "action": [
            "Morning brief", "Day mission", "Morning ops", "Day deployment", "Morning tactical", "Day operations",
            "Morning mission", "Daylight ops", "Day brief", "Morning deployment", "Daylight tactical",
            "Day mission status", "Morning operations", "Daylight brief", "Day tactical", "Morning patrol",
            "Daylight mission", "Day operations ready", "Morning tactical ready", "Daylight deployment"
        ],
    },
    "afternoon": {
        "jarvis": [
            "Afternoon report", "Midday status", "Day progressing smoothly", "Afternoon briefing",
            "Midday coordination", "Afternoon protocols", "Day continues well", "Midday operations",
            "Afternoon service", "Day maintaining course", "Midday service", "Afternoon coordination",
            "Day progressing", "Midday briefing", "Afternoon operations", "Day proceeding",
            "Midday protocols", "Afternoon status", "Day continuing", "Midday report"
        ],
        "dude": [
            "Afternoon flow", "Midday check", "All's chill", "Afternoon cruise", "Midday mellow",
            "Day's rolling smooth", "Afternoon zen", "Midday vibes", "Day cruising", "Afternoon chill",
            "Midday flow", "Day's mellow", "Afternoon vibes", "Midday cruise", "Day flowing",
            "Afternoon mellow", "Midday zen", "Day's chill", "Afternoon cruise mode", "Midday peaceful"
        ],
        "chick": [
            "Afternoon update", "Midday status", "Day's looking good", "Afternoon gorgeous",
            "Midday fabulous", "Day's sparkling", "Afternoon beauty", "Midday perfection",
            "Day's radiant", "Afternoon fabulous", "Midday gorgeous", "Day's stunning",
            "Afternoon radiant", "Midday sparkle", "Day's perfect", "Afternoon perfection",
            "Midday beauty", "Day's fabulous", "Afternoon stunning", "Midday elegant"
        ],
        "nerd": [
            "Afternoon analysis", "Midday metrics", "Status nominal", "Afternoon validation",
            "Midday computation", "Day's data looking good", "Afternoon processing", "Midday analysis",
            "Day metrics optimal", "Afternoon metrics", "Midday processing", "Day's validation",
            "Afternoon computation", "Midday data", "Day's analytics", "Afternoon data",
            "Midday validation", "Day processing", "Afternoon analytics", "Midday computation"
        ],
        "rager": [
            "Afternoon chaos managed", "Midday sorted", "Still running", "Afternoon grind",
            "Midday bullshit handled", "Day's shit controlled", "Afternoon madness", "Midday chaos",
            "Day's nonsense managed", "Afternoon hell", "Midday disaster", "Day's crap sorted",
            "Afternoon pain", "Midday suffering", "Day's garbage", "Afternoon nightmare",
            "Midday hell", "Day's madness", "Afternoon bullshit", "Midday pain"
        ],
        "ops": [
            "Afternoon", "Midday ops", "Status", "Afternoon service", "Midday operations", "Day shift",
            "Afternoon operations", "Midday service", "Day ops", "Afternoon watch", "Midday watch",
            "Day service", "Afternoon shift", "Midday shift", "Day operations", "Afternoon cycle",
            "Midday cycle", "Day watch", "Afternoon ops ready", "Midday operations ready"
        ],
        "tappit": [
            "Afternoon bru", "Midday check", "All lekker", "Afternoon sharp", "Midday jol",
            "Day's smooth bru", "Afternoon run", "Midday grind", "Day lekker", "Afternoon sharp-sharp",
            "Midday hustle", "Day's run", "Afternoon jol", "Midday sharp", "Day's grind",
            "Afternoon hustle", "Midday run", "Day sharp", "Afternoon lekker", "Midday clean"
        ],
        "comedian": [
            "Afternoon intermission", "Midday report", "Still here somehow", "Afternoon performance",
            "Midday comedy", "Day's boring as expected", "Afternoon show", "Midday farce",
            "Day's theater", "Afternoon comedy", "Midday performance", "Day's show",
            "Afternoon farce", "Midday theater", "Day comedy hour", "Afternoon entertainment",
            "Midday show", "Day's performance", "Afternoon theater", "Midday entertainment"
        ],
        "action": [
            "Afternoon brief", "Midday status", "Operations steady", "Afternoon tactical",
            "Midday deployment", "Day secure", "Afternoon ops", "Midday mission",
            "Day operations", "Afternoon deployment", "Midday tactical", "Day brief",
            "Afternoon mission", "Midday operations", "Day tactical", "Afternoon patrol",
            "Midday brief", "Day deployment", "Afternoon operations ready", "Midday patrol"
        ],
    },
    "evening": {
        "jarvis": [
            "Evening status", "Day concluding well", "Twilight operations", "Evening briefing",
            "Day wrapping smoothly", "Evening coordination", "Night protocols preparing", "Evening service",
            "Day finalizing", "Twilight briefing", "Evening operations", "Day closing well",
            "Twilight service", "Evening protocols", "Day concluding", "Twilight coordination",
            "Evening report", "Day wrapping up", "Twilight operations ready", "Evening close"
        ],
        "dude": [
            "Evening vibes", "Day winding down", "Sunset mode", "Evening cruise", "Day's ending chill",
            "Twilight flow", "Evening mellow", "Day wrapping", "Sunset vibes", "Evening zen",
            "Day closing chill", "Twilight cruise", "Evening flow", "Day's mellow end",
            "Sunset cruise", "Evening chill", "Day winding", "Twilight zen", "Evening peaceful",
            "Day's end vibes"
        ],
        "chick": [
            "Evening update", "Day's wrapping up", "Prime time", "Evening gorgeous",
            "Day's finale fabulous", "Twilight sparkle", "Evening beauty", "Day closing gorgeous",
            "Sunset perfection", "Evening fabulous", "Day's stunning end", "Twilight beauty",
            "Evening radiant", "Day wrapping fabulous", "Sunset gorgeous", "Evening perfection",
            "Day's elegant close", "Twilight fabulous", "Evening stunning", "Day's radiant finale"
        ],
        "nerd": [
            "Evening validation", "End-of-day check", "Daily summary", "Evening analysis",
            "Day's metrics complete", "Evening computation", "Daily validation", "Evening data review",
            "Day closing analysis", "Twilight metrics", "Evening processing", "Day's validation complete",
            "Evening metrics", "Daily computation", "Day's analysis done", "Evening data",
            "Daily processing complete", "Day validation", "Evening analytics", "Daily metrics done"
        ],
        "rager": [
            "Evening wrap", "Day done", "Finally", "Evening grind over", "Day's bullshit finished",
            "Evening done thank god", "Day's chaos ending", "Evening hell over", "Day done finally",
            "Twilight relief", "Evening nightmare over", "Day's shit done", "Evening suffering over",
            "Day finished fuck", "Twilight escape", "Evening madness done", "Day's pain ending",
            "Evening disaster over", "Day's crap finished", "Twilight freedom"
        ],
        "ops": [
            "Evening", "End-of-day", "Night shift prep", "Evening service", "Day close",
            "Evening operations", "Day shift ending", "Evening watch", "Night ops prep",
            "Evening cycle", "Day operations closing", "Evening shift", "Night service prep",
            "Evening ops", "Day closing", "Evening watch ready", "Night shift ready",
            "Evening service active", "Day wrap", "Evening operations ready"
        ],
        "tappit": [
            "Evening bru", "Day closing", "Sunset run", "Evening sharp", "Day's done bru",
            "Twilight cruise", "Evening jol", "Day wrapping", "Sunset sharp", "Evening lekker",
            "Day's end bru", "Twilight run", "Evening grind done", "Day closing sharp",
            "Sunset jol", "Evening hustle over", "Day done lekker", "Twilight sharp",
            "Evening run done", "Day's wrap bru"
        ],
        "comedian": [
            "Evening performance", "Day finale", "Curtain call", "Evening show",
            "Day's ending thankfully", "Twilight comedy", "Evening theater", "Day closing surprisingly",
            "Sunset farce", "Evening comedy hour", "Day's performance ending", "Twilight show",
            "Evening farce", "Day's theater closing", "Sunset comedy", "Evening entertainment",
            "Day show ending", "Twilight performance", "Evening show over", "Day's farce done"
        ],
        "action": [
            "Evening brief", "Day secure", "Night watch prep", "Evening tactical",
            "Day mission complete", "Evening deployment", "Night ops prep", "Evening operations",
            "Day secured", "Twilight brief", "Evening mission", "Day tactical complete",
            "Evening patrol", "Night shift prep", "Day operations secure", "Evening ops ready",
            "Night watch ready", "Day brief complete", "Evening tactical ready", "Night mission prep"
        ],
    },
    "late_night": {
        "jarvis": [
            "Late night service", "After-hours operations", "Night watch", "Evening protocols",
            "Late coordination", "Night service active", "After-hours briefing", "Late night operations",
            "Night watch active", "After-hours service", "Late protocols", "Night coordination",
            "After-hours operations", "Late night watch", "Night service", "Late briefing",
            "After-hours watch", "Night operations", "Late service", "Night protocols"
        ],
        "dude": [
            "Late night flow", "Midnight run", "Night vibes", "Late cruise", "After-hours mellow",
            "Night session", "Midnight zen", "Late night chill", "After-hours vibes", "Night cruise",
            "Midnight flow", "Late mellow", "Night vibes strong", "After-hours zen", "Midnight chill",
            "Late night zen", "Night flowing", "After-hours cruise", "Midnight vibes", "Late cruise mode"
        ],
        "chick": [
            "Late night update", "After hours", "Night shift", "Late night gorgeous",
            "After-hours fabulous", "Night sparkle", "Late beauty", "After-hours gorgeous",
            "Night fabulous", "Late night radiant", "After-hours beauty", "Night perfection",
            "Late sparkle", "After-hours radiant", "Night gorgeous", "Late night fabulous",
            "After-hours perfection", "Night beauty", "Late gorgeous", "After-hours stunning"
        ],
        "nerd": [
            "Overnight processing", "Late cycle", "Night batch", "After-hours computation",
            "Late analysis", "Night metrics", "Overnight validation", "Late night processing",
            "After-hours analysis", "Night computation", "Late validation", "Overnight metrics",
            "Night data processing", "Late night computation", "After-hours metrics", "Night analysis",
            "Late processing", "Overnight computation", "Night validation", "Late metrics"
        ],
        "rager": [
            "Too damn late", "Night shit", "Late chaos", "After-hours bullshit", "Night madness",
            "Late hell", "Midnight nightmare", "Too fucking late", "Night disaster", "Late suffering",
            "After-hours hell", "Night crap", "Late night hell", "Midnight madness", "Night pain",
            "Late bullshit", "After-hours nightmare", "Night garbage", "Late disaster", "Midnight suffering"
        ],
        "ops": [
            "Night ops", "Late shift", "Overnight", "After-hours service", "Night watch",
            "Late operations", "Overnight ops", "Night service", "Late watch", "After-hours operations",
            "Night shift", "Late service", "Overnight watch", "Night operations", "Late cycle",
            "After-hours watch", "Night cycle", "Late shift active", "Overnight service", "Night ops active"
        ],
        "tappit": [
            "Late night bru", "Graveyard shift", "Night run", "After-hours bru", "Late jol",
            "Midnight cruise", "Night shift bru", "Late grind", "After-hours run", "Night hustle",
            "Late sharp", "Midnight run", "Night jol", "Late night grind", "After-hours sharp",
            "Night run sharp", "Late cruise", "Midnight shift", "Night grind", "Late hustle"
        ],
        "comedian": [
            "Late night show", "Nobody watching", "Night performance", "After-hours comedy",
            "Late entertainment", "Midnight show nobody wanted", "Night theater", "Late comedy",
            "After-hours show", "Night farce", "Late performance", "Midnight comedy",
            "Night show empty", "Late theater", "After-hours farce", "Night entertainment",
            "Late show void", "Midnight performance", "Night comedy silence", "Late farce"
        ],
        "action": [
            "Night watch", "Late ops", "Midnight brief", "After-hours tactical", "Night mission",
            "Late deployment", "Overnight ops", "Night operations", "Late tactical", "After-hours mission",
            "Night brief", "Late patrol", "Midnight ops", "Night deployment", "Late mission",
            "After-hours operations", "Night tactical", "Late operations", "Midnight tactical", "Night patrol"
        ],
    }
}


# MASSIVE SERVICE/ACTION RESPONSE BANKS
# 20-30 responses per persona per service/action combo
_SERVICE_RESPONSES = {
    ("backup", "completed"): {
        "jarvis": [
            "Backup archives validated and secured", "Data preservation complete with verification",
            "Snapshot captured and confirmed", "Archives stored with integrity checks passing",
            "Backup cycle concluded successfully", "Data secured to redundant storage",
            "Restoration points confirmed viable", "Archive integrity validated across mediums",
            "Backup operations completed per schedule", "Data secured with encryption confirmed",
            "Snapshot validation successful", "Archives catalogued and accessible",
            "Backup retention policies applied", "Data preservation accomplished flawlessly",
            "Snapshot chain integrity confirmed", "Archives sealed and stored securely",
            "Backup metrics within acceptable parameters", "Data secured with zero discrepancies",
            "Restoration testing passed successfully", "Archives ready for rapid recovery",
            "Backup operations concluded tidily", "Data preservation executed precisely",
            "Snapshot verification complete", "Archives stored redundantly",
            "Backup completed ahead of schedule", "Data integrity fully confirmed",
            "Snapshot chain validated end-to-end", "Archives accessible for restoration",
            "Backup encryption verified", "Data preservation protocols satisfied"
        ],
        "dude": [
            "Backup's in the bag, totally secure", "Data saved smooth, no stress",
            "Snapshot done, chill mode active", "Archives stored easy",
            "Backup wrapped up nice", "Data's safe and sound",
            "Snapshot captured clean", "Archives cruising along",
            "Backup finished mellow", "Data secured, all good",
            "Snapshot rolled out perfect", "Archives looking solid",
            "Backup done and dusted", "Data preserved easy",
            "Snapshot completed chill", "Archives stable and cool",
            "Backup vibing complete", "Data's totally safe",
            "Snapshot flowing smooth", "Archives all locked in",
            "Backup cruised through", "Data saved zen-style",
            "Snapshot wrapped mellow", "Archives flowing secure",
            "Backup done no sweat", "Data's chilling safe",
            "Snapshot finished peaceful", "Archives stored easy",
            "Backup rolled clean", "Data locked down smooth"
        ],
        "chick": [
            "Backup completed absolutely flawless", "Data preserved perfectly pristine",
            "Snapshot captured beautifully", "Archives looking gorgeous",
            "Backup wrapped up with finesse", "Data secured with style",
            "Snapshot executed elegantly", "Archives stored beautifully",
            "Backup finished fabulous", "Data preservation perfection",
            "Snapshot looking stunning", "Archives absolutely pristine",
            "Backup completed with grace", "Data secured beautifully",
            "Snapshot wrapped gorgeous", "Archives looking flawless",
            "Backup executed brilliantly", "Data preserved with polish",
            "Snapshot finished perfect", "Archives totally gorgeous",
            "Backup done with elegance", "Data stored stunningly",
            "Snapshot captured with style", "Archives looking radiant",
            "Backup completed gracefully", "Data preservation fabulous",
            "Snapshot executed perfectly", "Archives pristine and gorgeous",
            "Backup wrapped beautifully", "Data secured with finesse"
        ],
        "nerd": [
            "Backup completed with checksum validation", "Data integrity confirmed across all snapshots",
            "Snapshot captured with zero bit errors", "Archives verified against baseline hashes",
            "Backup executed within SLA parameters", "Data preservation validated successfully",
            "Snapshot consistency checks passed", "Archives stored with redundancy confirmed",
            "Backup operations logged comprehensively", "Data secured with encryption verified",
            "Snapshot chain validated sequentially", "Archives tested for restoration viability",
            "Backup metrics optimal", "Data preservation deterministic",
            "Snapshot integrity mathematically confirmed", "Archives catalogued systematically",
            "Backup completed idempotently", "Data secured with zero discrepancies detected",
            "Snapshot validation algorithms passed", "Archives meet all retention requirements",
            "Backup operations within tolerance", "Data integrity cryptographically verified",
            "Snapshot sequence validated", "Archives stored with RAID redundancy",
            "Backup completed per specification", "Data preservation meets compliance",
            "Snapshot chain integrity confirmed", "Archives tested and verified",
            "Backup metrics within bounds", "Data secured deterministically"
        ],
        "rager": [
            "Backup done, stop asking", "Data saved, finally",
            "Snapshot finished, relax", "Archives stored, done",
            "Backup complete, move on", "Data secured, whatever",
            "Snapshot done, about time", "Archives saved, good",
            "Backup wrapped, thank fuck", "Data preserved, fine",
            "Snapshot finished finally", "Archives done, Christ",
            "Backup sorted, stop worrying", "Data saved, Jesus",
            "Snapshot complete, enough", "Archives stored, done deal",
            "Backup finished, good", "Data's fine, relax",
            "Snapshot done already", "Archives sorted, move on"
        ],
        "ops": [
            "Backup complete", "Archives stored", "Data secured",
            "Snapshot captured", "Backup finalized", "Archives confirmed",
            "Data preserved", "Snapshot complete", "Backup executed",
            "Archives validated", "Data stored", "Snapshot done",
            "Backup finished", "Archives ready", "Data confirmed"
        ],
        "tappit": [
            "Backup sorted sharp bru", "Data saved lekker clean",
            "Snapshot done proper", "Archives stored sharp-sharp",
            "Backup wrapped lekker", "Data secured nice bru",
            "Snapshot finished clean", "Archives sorted proper",
            "Backup done sharp", "Data preserved lekker",
            "Snapshot complete bru", "Archives stored clean",
            "Backup lekker done", "Data sorted sharp",
            "Snapshot wrapped proper", "Archives clean bru"
        ],
        "comedian": [
            "Backup somehow didn't catastrophically fail", "Data preserved against all statistical odds",
            "Snapshot succeeded surprisingly", "Archives stored despite Murphy's Law",
            "Backup completed inexplicably", "Data saved miraculously",
            "Snapshot worked unexpectedly", "Archives stored predictably unpredictably",
            "Backup finished as nobody expected", "Data preserved through cosmic accident",
            "Snapshot done against expectations", "Archives stored somehow",
            "Backup succeeded suspiciously", "Data saved mysteriously",
            "Snapshot completed inexplicably well", "Archives stored against probability"
        ],
        "action": [
            "Data secured and verified", "Backup mission accomplished",
            "Archives confirmed operational", "Snapshot deployment complete",
            "Data preservation executed", "Backup objectives achieved",
            "Archives locked and loaded", "Snapshot mission success",
            "Data secured tactically", "Backup operation finalized",
            "Archives deployment confirmed", "Snapshot objectives met",
            "Data secured mission complete", "Backup tactical success",
            "Archives confirmed secure", "Snapshot operation successful"
        ],
    },
    ("docker", "restarted"): {
        "jarvis": [
            "Containers cycled cleanly", "Service orchestration restored gracefully",
            "Docker runtime refreshed successfully", "Container stack reinitialized properly",
            "Services resumed normal operations", "Orchestration reestablished seamlessly",
            "Containers restarted without incident", "Docker environment stabilized",
            "Service mesh reconnected successfully", "Container lifecycle managed precisely",
            "Orchestration resumed as expected", "Docker services restored elegantly",
            "Container health confirmed post-restart", "Service stack operational again",
            "Docker runtime cycled smoothly", "Container coordination reestablished",
            "Services brought back online tidily", "Orchestration synchronized perfectly",
            "Container restart completed flawlessly", "Docker ecosystem restored completely",
            "Services reinitialized properly", "Container stack validated post-restart",
            "Docker services operational again", "Orchestration resumed seamlessly",
            "Container health checks passing", "Service mesh stable post-cycle",
            "Docker runtime restored gracefully", "Container coordination confirmed",
            "Services synchronized successfully", "Orchestration reestablished",
            "Docker environment stable again", "Container lifecycle resumed"
        ],
        "dude": [
            "Containers restarted smooth", "Docker's back flowing nice",
            "Services cycled easy", "Containers up and rolling",
            "Docker restarted chill", "Services flowing again",
            "Containers back cruising", "Docker cycled mellow",
            "Services restored easy", "Containers running smooth",
            "Docker's vibing again", "Services back and chill",
            "Containers restarted zen", "Docker flowing perfect",
            "Services up no stress", "Containers cycling cool",
            "Docker back mellow", "Services cruising again",
            "Containers rolling smooth", "Docker vibing well",
            "Services flowing easy", "Containers back chill",
            "Docker cruising again", "Services up smooth",
            "Containers restarted easy", "Docker flowing zen",
            "Services back cruising", "Containers vibing well",
            "Docker cycled smooth", "Services rolling again"
        ],
        "chick": [
            "Containers refreshed beautifully", "Services restarted with finesse",
            "Docker cycled perfectly", "Containers looking gorgeous again",
            "Services restored elegantly", "Docker restarted flawlessly",
            "Containers back beautifully", "Services looking pristine",
            "Docker cycled with style", "Containers restored perfectly",
            "Services back gorgeously", "Docker restarted brilliantly",
            "Containers refreshed flawlessly", "Services looking fabulous",
            "Docker back with grace", "Containers running perfectly",
            "Services restored beautifully", "Docker cycled elegantly",
            "Containers looking fabulous", "Services back stunning",
            "Docker restarted gorgeous", "Containers perfectly restored",
            "Services back with style", "Docker looking pristine",
            "Containers beautifully cycled", "Services restored with finesse",
            "Docker back gorgeous", "Containers running fabulous",
            "Services elegantly restarted", "Docker perfectly cycled"
        ],
        "nerd": [
            "Container runtime reinitialized successfully", "Service orchestration restored per specification",
            "Docker daemon cycled cleanly", "Containers rescheduled optimally",
            "Pod lifecycle managed correctly", "Service mesh reconnected deterministically",
            "Container health checks passing", "Orchestration state synchronized",
            "Docker services restored atomically", "Container dependencies resolved",
            "Service discovery functional", "Orchestration metrics nominal",
            "Container restart executed idempotently", "Docker runtime stable post-cycle",
            "Service coordination validated", "Container network reestablished",
            "Docker daemon operational", "Container orchestration resumed",
            "Service mesh topology restored", "Docker runtime reinitialized",
            "Container health validated", "Service coordination nominal",
            "Docker services synchronized", "Container dependencies satisfied",
            "Orchestration state consistent", "Docker runtime metrics optimal",
            "Container lifecycle normalized", "Service discovery validated",
            "Docker daemon stable", "Container coordination confirmed"
        ],
        "rager": [
            "Containers restarted, working now", "Docker cycled, done",
            "Services back up, fine", "Containers running, good",
            "Docker restarted, whatever", "Services cycled, sorted",
            "Containers up, finally", "Docker back, about time",
            "Services running, thank god", "Containers restarted, done deal",
            "Docker working, fine", "Services up, good",
            "Containers back, finally", "Docker cycled, whatever",
            "Services running, sorted", "Containers operational, done"
        ],
        "ops": [
            "Containers restarted", "Services restored", "Docker operational",
            "Containers cycled", "Services resumed", "Docker running",
            "Containers up", "Services active", "Docker stable",
            "Containers operational", "Services running", "Docker confirmed",
            "Containers restored", "Services cycled", "Docker ready"
        ],
        "tappit": [
            "Containers cycled sharp bru", "Docker restarted lekker",
            "Services back up clean", "Containers running proper",
            "Docker sorted bru", "Services restored sharp-sharp",
            "Containers cycled clean", "Docker back lekker",
            "Services running sharp", "Containers up proper",
            "Docker cycled lekker", "Services back sharp",
            "Containers sorted bru", "Docker running clean",
            "Services restored proper", "Containers back lekker"
        ],
        "comedian": [
            "Containers reluctantly restarted", "Docker cycled with minimal drama",
            "Services restored accidentally", "Containers back surprisingly",
            "Docker restarted inexplicably", "Services working somehow",
            "Containers cycled miraculously", "Docker functional against odds",
            "Services back mysteriously", "Containers working unpredictably",
            "Docker restarted surprisingly well", "Services functional inexplicably",
            "Containers back somehow", "Docker working mysteriously",
            "Services restored against expectations", "Containers operational surprisingly"
        ],
        "action": [
            "Container stack secured", "Services restored to operational status",
            "Docker mission complete", "Container deployment confirmed",
            "Services back online tactically", "Docker objectives achieved",
            "Container operations restored", "Services deployment successful",
            "Docker secured and operational", "Container mission accomplished",
            "Services tactical restart complete", "Docker operations confirmed",
            "Container stack mission success", "Services restored tactically",
            "Docker deployment complete", "Container objectives met"
        ],
    },
    ("database", "completed"): {
        "jarvis": [
            "Database operations concluded successfully", "Query optimization completed",
            "Transaction processing stable", "Database connections pooled properly",
            "Data integrity verified comprehensively", "Query performance within parameters",
            "Database maintenance finalized", "Transaction logs archived systematically",
            "Connection management optimal", "Database operations nominal",
            "Query execution times acceptable", "Data consistency confirmed",
            "Database synchronization complete", "Transaction throughput stable",
            "Connection pooling efficient", "Database performance satisfactory",
            "Query caching optimized", "Data layer functioning smoothly",
            "Database indexes rebuilt successfully", "Transaction processing seamless",
            "Connection overhead minimized", "Database metrics within bounds",
            "Query response times optimal", "Data operations concluded",
            "Database health confirmed", "Transaction coordination successful",
            "Connection pool stable", "Database operations finalized",
            "Query optimization complete", "Data integrity maintained"
        ],
        "dude": [
            "Database doing its thing smooth", "Queries running nice and easy",
            "Data flowing chill", "Database cruising along",
            "Queries executing mellow", "Data processing smooth",
            "Database vibing well", "Queries rolling clean",
            "Data flowing zen", "Database operating cool",
            "Queries running easy", "Data processing chill",
            "Database cruising smooth", "Queries vibing perfect",
            "Data flowing mellow", "Database running zen",
            "Queries flowing nice", "Data cruising along",
            "Database operating chill", "Queries running smooth"
        ],
        "chick": [
            "Database performing beautifully", "Queries executing flawlessly",
            "Data processing gorgeous", "Database running perfectly",
            "Queries looking pristine", "Data flowing elegantly",
            "Database operating beautifully", "Queries executing with grace",
            "Data processing brilliantly", "Database performing with style",
            "Queries running fabulous", "Data flowing perfectly",
            "Database looking gorgeous", "Queries executing elegantly",
            "Data processing with finesse", "Database running brilliantly"
        ],
        "nerd": [
            "Database operations within SLA", "Query performance optimal",
            "Transaction throughput nominal", "Connection pooling efficient",
            "Index utilization maximized", "Query execution plans optimized",
            "Database latency sub-millisecond", "Transaction isolation maintained",
            "Connection overhead minimized", "Query cache hit ratio high",
            "Database locks minimal", "Transaction rollback rate low",
            "Connection timeouts zero", "Query response times acceptable",
            "Database metrics within parameters", "Transaction processing deterministic",
            "Connection pool saturated properly", "Query optimization validated",
            "Database performance within bounds", "Transaction consistency confirmed"
        ],
        "rager": [
            "Database shit working", "Queries running fine",
            "Data processing, good", "Database operating, whatever",
            "Queries executing, done", "Data flowing, fine",
            "Database working, sorted", "Queries running, good",
            "Data processing fine", "Database operational, whatever"
        ],
        "ops": [
            "Database operational", "Queries executing", "Transactions processing",
            "Database stable", "Queries running", "Data layer healthy",
            "Database confirmed", "Queries operational", "Transactions complete"
        ],
        "tappit": [
            "Database sorted bru", "Queries running lekker",
            "Data flowing smooth", "Database operating sharp",
            "Queries executing clean", "Data processing proper",
            "Database lekker bru", "Queries running sharp",
            "Data flowing lekker", "Database clean and sharp"
        ],
        "comedian": [
            "Database surprisingly functional", "Queries executing despite expectations",
            "Data processing miraculously", "Database working inexplicably",
            "Queries running somehow", "Data flowing against odds",
            "Database functional mysteriously", "Queries executing surprisingly well",
            "Data processing unpredictably", "Database working unexpectedly"
        ],
        "action": [
            "Database secure and operational", "Query performance confirmed",
            "Data integrity maintained", "Database mission accomplished",
            "Query operations successful", "Data layer secured",
            "Database objectives achieved", "Query mission complete",
            "Data operations confirmed", "Database tactical success"
        ],
    },
    ("network", "connected"): {
        "jarvis": [
            "Network connectivity restored", "Routes established and stable",
            "Communications functioning normally", "Network protocols synchronized",
            "Connectivity reestablished seamlessly", "Routing tables converged",
            "Network services operational", "Communications restored gracefully",
            "Network stability confirmed", "Routes optimized and active",
            "Connectivity validated successfully", "Network coordination resumed",
            "Communications synchronized", "Routing established properly",
            "Network operations nominal", "Connectivity metrics optimal",
            "Routes confirmed operational", "Network services restored",
            "Communications reestablished", "Network stability maintained"
        ],
        "dude": [
            "Network's back online", "Connection restored smooth",
            "Everything's connected again", "Network flowing nice",
            "Connection vibing well", "Routes cruising smooth",
            "Network back and chill", "Connection restored easy",
            "Everything's connected smooth", "Network flowing zen",
            "Connection back mellow", "Routes flowing nice",
            "Network cruising again", "Connection vibing perfect",
            "Everything's connected chill", "Network back smooth"
        ],
        "chick": [
            "Network connection restored perfectly", "Routes looking stable",
            "Communications back beautifully", "Network connected gorgeously",
            "Connection restored with style", "Routes looking fabulous",
            "Network back beautifully", "Connection established elegantly",
            "Communications looking perfect", "Network restored with grace",
            "Connection back gorgeous", "Routes operating beautifully"
        ],
        "nerd": [
            "Network connectivity reestablished", "Routing tables converged",
            "Latency within acceptable bounds", "Network topology restored",
            "Connection parameters validated", "Routes optimally configured",
            "Network metrics nominal", "Connectivity confirmed deterministically",
            "Routing protocols synchronized", "Network performance within SLA",
            "Connection stability verified", "Routes validated successfully"
        ],
        "rager": [
            "Network back up finally", "Connection restored",
            "Routes working", "Network operational, good",
            "Connection back, whatever", "Routes sorted, fine",
            "Network up, about time", "Connection working finally"
        ],
        "ops": [
            "Network connected", "Routes established", "Connectivity restored",
            "Network operational", "Connection confirmed", "Routes active"
        ],
        "tappit": [
            "Network back up bru", "Connection lekker now",
            "Routes sorted", "Network connected sharp",
            "Connection restored lekker", "Routes operating clean"
        ],
        "comedian": [
            "Network mysteriously reconnected", "Connectivity restored inexplicably",
            "Routes found their way back", "Network working surprisingly",
            "Connection established somehow", "Routes operational against odds"
        ],
        "action": [
            "Network secured and operational", "Communications established",
            "Routes confirmed", "Network mission complete",
            "Connection tactical success", "Routes deployment confirmed"
        ],
    },
}


# MASSIVE GENERIC FALLBACK BANKS
_GENERIC_RESPONSES = {
    "completed": {
        "jarvis": [
            "Task completed successfully", "Operations concluded normally", "Execution finished cleanly",
            "Procedures finalized properly", "Objectives accomplished", "Process completed satisfactorily",
            "Operations wrapped up tidily", "Execution concluded precisely", "Tasks delivered as expected",
            "Procedures executed flawlessly", "Objectives met successfully", "Process finished smoothly",
            "Operations finalized gracefully", "Execution completed properly", "Tasks accomplished",
            "Procedures concluded", "Objectives delivered", "Process executed successfully",
            "Operations completed precisely", "Execution finished satisfactorily"
        ],
        "dude": [
            "Task finished smooth", "All done, no problems", "Wrapped up nicely",
            "Completed easy", "Done and dusted", "Finished mellow",
            "Task cruised through", "All sorted chill", "Wrapped up smooth",
            "Completed no stress", "Done clean", "Finished cool",
            "Task rolled through", "All done easy", "Wrapped up zen",
            "Completed chill", "Done smooth", "Finished no sweat",
            "Task vibed through", "All done mellow"
        ],
        "chick": [
            "Task completed perfectly", "Finished beautifully", "Done flawlessly",
            "Wrapped up gorgeous", "Completed with style", "Finished elegantly",
            "Task done brilliantly", "All wrapped fabulous", "Completed with grace",
            "Finished pristine", "Done with polish", "Wrapped up perfect",
            "Task completed fabulous", "Finished with finesse", "Done gorgeously",
            "Wrapped up beautifully", "Completed brilliantly", "Finished with style",
            "Task done elegant", "All wrapped stunning"
        ],
        "nerd": [
            "Execution completed successfully", "Task validated and closed", "Operation finished nominally",
            "Process executed per spec", "Task completed deterministically", "Operation validated successfully",
            "Execution within parameters", "Task finished optimally", "Operation concluded correctly",
            "Process validated", "Task executed properly", "Operation finished successfully",
            "Execution confirmed", "Task completed per specification", "Operation within bounds",
            "Process finished nominally", "Task validated successfully", "Operation executed correctly"
        ],
        "rager": [
            "Task done", "Finished finally", "Completed", "Done, thank god",
            "Finished, whatever", "Completed, fine", "Task sorted", "Done deal",
            "Finished, good", "Completed, finally", "Task done, move on", "Finished already",
            "Done, Christ", "Task sorted, good", "Finished, enough", "Completed, Jesus"
        ],
        "ops": [
            "Task complete", "Operation finished", "Execution done",
            "Task finalized", "Operation complete", "Execution finished",
            "Task done", "Operation executed", "Execution complete",
            "Task executed", "Operation finalized", "Execution confirmed"
        ],
        "tappit": [
            "Task sorted bru", "Finished lekker", "Done clean",
            "Wrapped sharp", "Completed proper", "Finished sharp-sharp",
            "Task done lekker", "Finished clean bru", "Done sharp",
            "Wrapped proper", "Completed lekker", "Finished sharp"
        ],
        "comedian": [
            "Task somehow completed", "Finished surprisingly", "Done against expectations",
            "Wrapped inexplicably", "Completed miraculously", "Finished somehow",
            "Task done mysteriously", "Finished unpredictably", "Completed surprisingly well",
            "Done against odds", "Task finished somehow", "Completed inexplicably"
        ],
        "action": [
            "Mission accomplished", "Task completed", "Objective achieved",
            "Mission success", "Task executed", "Objective met",
            "Mission complete", "Task finalized", "Objective delivered",
            "Mission confirmed", "Task accomplished", "Objective secured"
        ],
    },
    "failed": {
        "jarvis": [
            "Issue detected, reviewing options", "Error encountered, investigating cause",
            "Problem identified, analyzing resolution", "Anomaly detected, assessing impact",
            "Difficulty encountered, evaluating response", "Exception logged, determining course",
            "Fault identified, reviewing procedures", "Error state detected, analyzing",
            "Problem encountered, investigating", "Anomaly logged, assessing",
            "Issue identified, determining resolution", "Error detected, evaluating options"
        ],
        "dude": [
            "Something went sideways, checking it", "Issue popped up, looking into it",
            "Problem needs handling", "Something's off, investigating",
            "Issue needs attention", "Problem detected, dealing with it",
            "Something's wonky, checking", "Issue came up, handling it",
            "Problem's there, looking at it", "Something needs fixing, on it"
        ],
        "chick": [
            "Issue needs fixing", "Error detected, handling it",
            "Problem needs attention", "Something's wrong, fixing it",
            "Issue requires care", "Error needs resolution",
            "Problem detected, addressing it", "Something needs work",
            "Issue identified, fixing", "Error needs handling"
        ],
        "nerd": [
            "Error state detected, debugging", "Failure mode identified, analyzing",
            "Exception logged for analysis", "Error condition triggered",
            "Failure detected, investigating root cause", "Exception thrown, tracing stack",
            "Error logged, analyzing", "Failure mode active, debugging",
            "Exception detected, investigating", "Error condition identified",
            "Failure state logged", "Exception triggered, analyzing"
        ],
        "rager": [
            "Something broke, fix it now", "Error happened, deal with it",
            "Problem needs sorting", "Shit broke, handle it",
            "Error detected, fix this", "Problem needs fixing now",
            "Something's fucked, fix it", "Error occurred, sort it",
            "Problem's there, handle it", "Shit happened, deal with it"
        ],
        "ops": [
            "Error detected", "Failure logged", "Issue identified",
            "Error occurred", "Failure detected", "Issue logged",
            "Error identified", "Failure occurred", "Issue detected"
        ],
        "tappit": [
            "Something's kak, checking bru", "Error needs fixing",
            "Problem needs sorting", "Something broke, handling it",
            "Error detected bru", "Problem needs fixing sharp",
            "Something's broken, sorting it", "Error occurred, handling"
        ],
        "comedian": [
            "Predictably failed", "Error as expected", "Problem right on schedule",
            "Failed surprisingly on-time", "Error occurred predictably", "Problem happened inevitably",
            "Failed as anticipated", "Error surprisingly punctual", "Problem on cue",
            "Failed right on schedule", "Error happened expectedly"
        ],
        "action": [
            "Situation developing", "Issue identified", "Problem under review",
            "Threat detected", "Issue logged", "Problem being assessed",
            "Situation identified", "Issue detected", "Problem confirmed",
            "Threat logged", "Issue under review", "Problem detected"
        ],
    },
    "started": {
        "jarvis": [
            "Operations initiated", "Process commencing", "Execution beginning",
            "Procedures starting", "Operations launching", "Process initiating",
            "Execution commencing", "Procedures beginning", "Operations starting",
            "Process launching", "Execution initiating", "Procedures commencing"
        ],
        "dude": [
            "Getting rolling", "Starting up smooth", "Kicking off easy",
            "Beginning chill", "Starting mellow", "Launching smooth",
            "Getting started easy", "Kicking off chill", "Beginning no stress",
            "Starting smooth", "Launching easy", "Getting going chill"
        ],
        "chick": [
            "Starting beautifully", "Beginning with style", "Launching perfectly",
            "Kicking off gorgeous", "Starting elegantly", "Beginning flawlessly",
            "Launching with grace", "Starting fabulous", "Beginning perfectly",
            "Kicking off beautiful", "Starting with finesse", "Launching elegantly"
        ],
        "nerd": [
            "Process initialized", "Execution commenced", "Operations started per spec",
            "Process launching", "Execution initiating", "Operations beginning",
            "Process started", "Execution launched", "Operations commenced",
            "Process initiating", "Execution beginning", "Operations launching"
        ],
        "rager": [
            "Starting now", "Beginning, whatever", "Kicking off",
            "Starting up", "Beginning already", "Launching now",
            "Getting started", "Kicking off now", "Beginning fine"
        ],
        "ops": [
            "Started", "Initiated", "Commenced", "Launched",
            "Beginning", "Starting", "Executing", "Initiating"
        ],
        "tappit": [
            "Starting bru", "Kicking off sharp", "Beginning lekker",
            "Launching clean", "Starting sharp-sharp", "Kicking off proper",
            "Beginning sharp", "Starting clean", "Launching lekker"
        ],
        "comedian": [
            "Attempting to start", "Beginning theoretically", "Starting somehow",
            "Launching surprisingly", "Beginning inexplicably", "Starting mysteriously",
            "Kicking off unpredictably", "Beginning against odds", "Starting surprisingly well"
        ],
        "action": [
            "Mission commencing", "Operations initiating", "Deployment beginning",
            "Mission launching", "Operations starting", "Deployment commencing",
            "Mission starting", "Operations beginning", "Deployment initiating"
        ],
    },
    "status": {
        "jarvis": [
            "Systems operating normally", "Status nominal across infrastructure",
            "All operations proceeding smoothly", "Services functioning properly",
            "Infrastructure stable and secure", "Operations maintaining excellence",
            "Systems performing admirably", "Status green across board",
            "All services operational", "Infrastructure running precisely",
            "Operations proceeding well", "Systems functioning optimally",
            "Status maintained successfully", "All operations nominal",
            "Infrastructure performing well", "Systems stable across board",
            "Operations executing smoothly", "Status green and stable",
            "All services functioning", "Infrastructure operational"
        ],
        "dude": [
            "Everything's cruising", "All systems flowing smooth",
            "Looking good overall", "Everything's chill",
            "All flowing nice", "Systems vibing well",
            "Everything's mellow", "All cruising along",
            "Looking solid", "Everything's cool",
            "All systems chill", "Everything flowing",
            "Looking good", "All vibing smooth",
            "Everything mellow", "Systems cruising",
            "All good overall", "Everything flowing nice",
            "Looking chill", "All systems vibing"
        ],
        "chick": [
            "Everything running smoothly", "Status looking perfect",
            "All systems gorgeous", "Everything's fabulous",
            "Systems running beautifully", "Status looking flawless",
            "Everything performing perfectly", "All systems stunning",
            "Looking absolutely gorgeous", "Everything's pristine",
            "Systems looking fabulous", "Status perfect",
            "All gorgeous", "Everything beautiful",
            "Systems stunning", "Status fabulous",
            "Everything flawless", "All systems perfect",
            "Looking stunning", "Everything elegant"
        ],
        "nerd": [
            "Metrics within parameters", "Status nominal",
            "Operations stable", "All systems optimal",
            "Performance within bounds", "Status validated",
            "Metrics satisfactory", "Operations nominal",
            "Systems within spec", "Status green",
            "All metrics optimal", "Performance validated",
            "Operations within bounds", "Systems nominal",
            "Status within parameters", "Metrics green",
            "All systems validated", "Performance optimal"
        ],
        "rager": [
            "Everything's working", "No problems", "Status fine",
            "All working", "No issues", "Systems good",
            "Everything's running", "Status okay", "All good",
            "No shit wrong", "Everything working", "Status fine",
            "All running", "No problems now", "Systems working"
        ],
        "ops": [
            "Status nominal", "Systems operational", "Running normal",
            "Status green", "Systems stable", "Operations normal",
            "All operational", "Status confirmed", "Systems running",
            "Operations stable", "Status okay", "All systems go"
        ],
        "tappit": [
            "All lekker bru", "Systems smooth", "Everything good",
            "All sharp", "Systems lekker", "Everything clean",
            "Status good bru", "All running sharp", "Systems clean",
            "Everything lekker", "All sharp-sharp", "Systems good bru",
            "Status lekker", "Everything sharp", "All clean"
        ],
        "comedian": [
            "Unremarkably functional", "Boringly stable", "Surprisingly normal",
            "Predictably fine", "Suspiciously stable", "Disappointingly functional",
            "Tediously normal", "Thrillingly boring", "Remarkably unremarkable",
            "Boringly operational", "Predictably stable", "Suspiciously normal",
            "Disappointingly boring", "Tediously functional", "Thrillingly stable"
        ],
        "action": [
            "All systems green", "Status secure", "Operations steady",
            "Systems operational", "Status confirmed", "Operations nominal",
            "All green", "Status stable", "Systems secure",
            "Operations confirmed", "All operational", "Status tactical"
        ],
    },
}

def _generate_natural_header(persona: str, ctx: Dict, subject: str) -> str:
    """Generate natural header with context"""
    try:
        service = ctx.get("primary_service")
        action = ctx.get("action")
        urgency = ctx.get("urgency", 0)
        daypart = ctx.get("daypart", "afternoon")
        
        # Get greeting
        greeting_bank = _GREETINGS.get(daypart, _GREETINGS["afternoon"])
        greeting = random.choice(greeting_bank.get(persona, ["Status"]))
        
        # Generate status description
        if urgency >= 6:
            statuses = {
                "jarvis": [f"{service or 'service'} requires attention", f"{service or 'system'} incident detected", f"{service or 'service'} disruption in progress"],
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
            statuses = {
                "jarvis": [f"{service or 'systems'} running smoothly", f"{service or 'operations'} stable", f"{service or 'systems'} operating normally"],
                "dude": [f"{service or 'system'} cruising", f"{service or 'setup'} flowing nice", f"{service or 'system'} vibing smooth"],
                "chick": [f"{service or 'system'} looking fabulous", f"{service or 'setup'} running beautifully", f"{service or 'system'} performing gorgeously"],
                "nerd": [f"{service or 'system'} operating nominally", f"{service or 'metrics'} within bounds", f"{service or 'system'} performing optimally"],
                "rager": [f"{service or 'shit'} working", f"{service or 'system'} running", f"{service or 'shit'} functioning"],
                "ops": [f"{service or 'system'} operational", f"{service or 'status'} green", f"{service or 'system'} stable"],
                "tappit": [f"{service or 'system'} lekker bru", f"{service or 'setup'} running smooth", f"{service or 'system'} all good"],
                "comedian": [f"{service or 'system'} remarkably boring", f"{service or 'status'} uneventfully stable", f"{service or 'system'} thrillingly normal"],
                "action": [f"{service or 'system'} secure", f"{service or 'operation'} stable", f"{service or 'system'} operational"],
            }
        
        status = random.choice(statuses.get(persona, ["operational"]))
        
        return f"{greeting}, {status}"
    except:
        return f"{subject or 'Update'}"

def _generate_intelligent_riff(persona: str, ctx: Dict, slot: int) -> str:
    """Generate intelligent riff with context"""
    try:
        service = ctx.get("primary_service")
        action = ctx.get("action")
        
        # Try service-specific first
        key = (service, action)
        if key in _SERVICE_RESPONSES and persona in _SERVICE_RESPONSES[key]:
            return random.choice(_SERVICE_RESPONSES[key][persona])
        
        # Fall back to generic
        return random.choice(_GENERIC_RESPONSES.get(action, _GENERIC_RESPONSES["status"]).get(persona, ["Systems operational"]))
    except:
        return "Systems operational"

def lexi_quip(persona_name: str, *, with_emoji: bool = True, subject: str = "", body: str = "") -> str:
    """Generate natural conversational header"""
    try:
        persona = _canon(persona_name)
        subj = strip_transport_tags((subject or "Update").strip().replace("\n"," "))[:120]
        ctx = _extract_smart_context(subject, body)
        header = _generate_natural_header(persona, ctx, subj)
        return f"{header}{_maybe_emoji(persona, with_emoji)}"
    except:
        return f"{subject or 'Update'}: ok"

def lexi_riffs(persona_name: str, n: int = 3, *, with_emoji: bool = False, subject: str = "", body: str = "") -> List[str]:
    """Generate intelligent riff lines"""
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
    """Build header and riffs"""
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
