#!/usr/bin/env python3
# /app/personality.py — ENHANCED with natural language generation
# Makes Lexi sound human and intelligent without LLM calls
#
# Public API:
#   - quip(persona_name: str, *, with_emoji: bool = True) -> str
#   - llm_quips(persona_name: str, *, context: str = "", max_lines: int = 3) -> list[str]
#   - lexi_quip(persona_name: str, *, with_emoji: bool = True, subject: str = "", body: str = "") -> str
#   - lexi_riffs(persona_name: str, n: int = 3, *, with_emoji: bool = False, subject: str = "", body: str = "") -> list[str]
#   - persona_header(persona_name: str, subject: str = "", body: str = "") -> str

import random, os, importlib, re, time
from typing import List, Dict, Optional, Tuple

# Transport tag scrubber
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

# Time awareness
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

# Personas
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

# ============================================================================
# SMART CONTEXT EXTRACTION - Makes Lexi actually intelligent
# ============================================================================

def _extract_smart_context(subject: str = "", body: str = "") -> Dict:
    """Deep context analysis for intelligent response generation"""
    try:
        text = f"{subject} {body}".lower()
        
        # Service detection
        services = {
            "sonarr": "sonarr" in text,
            "radarr": "radarr" in text,
            "plex": "plex" in text or "jellyfin" in text,
            "homeassistant": "home assistant" in text or "homeassistant" in text,
            "docker": "docker" in text or "container" in text,
            "database": any(db in text for db in ["mysql", "postgres", "mariadb", "mongodb", "sql", "database"]),
            "backup": "backup" in text or "snapshot" in text,
            "network": any(net in text for net in ["network", "dns", "proxy", "nginx", "firewall"]),
            "storage": any(stor in text for stor in ["disk", "storage", "mount", "volume", "raid"]),
            "monitoring": any(mon in text for mon in ["uptime", "monitor", "health", "check", "analytics"]),
            "certificate": "certificate" in text or "cert" in text or "ssl" in text or "tls" in text,
            "update": "update" in text or "upgrade" in text or "patch" in text,
        }
        active_services = [k for k, v in services.items() if v]
        
        # Action detection
        actions = {
            "completed": any(w in text for w in ["completed", "finished", "done", "success", "passed", "ok"]),
            "started": any(w in text for w in ["started", "beginning", "initiated", "launching"]),
            "failed": any(w in text for w in ["failed", "error", "failure", "crashed", "down"]),
            "warning": any(w in text for w in ["warning", "caution", "degraded", "slow"]),
            "updated": any(w in text for w in ["updated", "upgraded", "patched", "modified"]),
            "restarted": any(w in text for w in ["restarted", "rebooted", "cycled", "restart"]),
            "connected": any(w in text for w in ["connected", "online", "up", "available"]),
            "disconnected": any(w in text for w in ["disconnected", "offline", "down", "unavailable"]),
            "scheduled": any(w in text for w in ["scheduled", "queued", "planned", "upcoming"]),
        }
        active_action = next((k for k, v in actions.items() if v), "status")
        
        # Urgency scoring
        urgency = 0
        if any(w in text for w in ["critical", "emergency", "urgent"]):
            urgency = 8
        elif any(w in text for w in ["down", "offline", "failed", "error"]):
            urgency = 6
        elif any(w in text for w in ["warning", "degraded", "slow"]):
            urgency = 3
        elif any(w in text for w in ["success", "completed", "healthy"]):
            urgency = 0
        
        # Extract numbers
        numbers = re.findall(r'\b\d+(?:\.\d+)?%?\b', text)
        
        return {
            "services": active_services,
            "primary_service": active_services[0] if active_services else None,
            "action": active_action,
            "urgency": urgency,
            "has_numbers": bool(numbers),
            "numbers": numbers[:3],
            "is_weekend": time.localtime().tm_wday in [5, 6],
            "is_night": time.localtime().tm_hour < 6 or time.localtime().tm_hour > 22,
            "daypart": _daypart(),
        }
    except:
        return {
            "services": [], "primary_service": None, "action": "status",
            "urgency": 0, "has_numbers": False, "numbers": [],
            "is_weekend": False, "is_night": False, "daypart": "afternoon"
        }

# ============================================================================
# NATURAL LANGUAGE GENERATION - Makes Lexi sound human
# ============================================================================

def _generate_natural_header(persona: str, ctx: Dict, subject: str) -> str:
    """Generate natural conversational header based on context"""
    try:
        service = ctx.get("primary_service")
        action = ctx.get("action")
        urgency = ctx.get("urgency", 0)
        daypart = ctx.get("daypart", "afternoon")
        
        # Time-based greetings by persona
        greetings = {
            "early_morning": {
                "jarvis": ["Early morning service", "Pre-dawn operations", "Night watch concluding"],
                "dude": ["Early vibes", "Dawn patrol", "Morning brew time"],
                "chick": ["Rise and shine", "Early bird mode", "Morning glow"],
                "nerd": ["Early processing cycle", "Morning batch complete", "Dawn computation"],
                "rager": ["Too damn early", "Morning bullshit", "Early chaos"],
                "ops": ["Early shift", "Morning ops", "Dawn cycle"],
                "tappit": ["Early start bru", "Morning shift", "Dawn run"],
                "comedian": ["Sunrise nobody asked for", "Morning show", "Early comedy hour"],
                "action": ["Dawn patrol", "Early mission", "Morning brief"],
            },
            "morning": {
                "jarvis": ["Good morning", "Morning status", "Day operations commencing"],
                "dude": ["Morning vibes", "Good morning", "Day's flowing"],
                "chick": ["Morning darling", "Good morning", "Daylight ready"],
                "nerd": ["Morning analysis", "Daily standup", "Morning metrics"],
                "rager": ["Morning shit sorted", "Day starting", "Coffee then chaos"],
                "ops": ["Morning", "Daily ops", "Day shift"],
                "tappit": ["Howzit morning", "Morning bru", "Day starting"],
                "comedian": ["Morning allegedly", "Good morning question mark", "Day begins theoretically"],
                "action": ["Morning brief", "Day mission", "Morning ops"],
            },
            "afternoon": {
                "jarvis": ["Afternoon report", "Midday status", "Day progressing smoothly"],
                "dude": ["Afternoon flow", "Midday check", "All's chill"],
                "chick": ["Afternoon update", "Midday status", "Day's looking good"],
                "nerd": ["Afternoon analysis", "Midday metrics", "Status nominal"],
                "rager": ["Afternoon chaos managed", "Midday sorted", "Still running"],
                "ops": ["Afternoon", "Midday ops", "Status"],
                "tappit": ["Afternoon bru", "Midday check", "All lekker"],
                "comedian": ["Afternoon intermission", "Midday report", "Still here somehow"],
                "action": ["Afternoon brief", "Midday status", "Operations steady"],
            },
            "evening": {
                "jarvis": ["Evening status", "Day concluding well", "Twilight operations"],
                "dude": ["Evening vibes", "Day winding down", "Sunset mode"],
                "chick": ["Evening update", "Day's wrapping up", "Prime time"],
                "nerd": ["Evening validation", "End-of-day check", "Daily summary"],
                "rager": ["Evening wrap", "Day done", "Finally"],
                "ops": ["Evening", "End-of-day", "Night shift prep"],
                "tappit": ["Evening bru", "Day closing", "Sunset run"],
                "comedian": ["Evening performance", "Day finale", "Curtain call"],
                "action": ["Evening brief", "Day secure", "Night watch prep"],
            },
            "late_night": {
                "jarvis": ["Late night service", "After-hours operations", "Night watch"],
                "dude": ["Late night flow", "Midnight run", "Night vibes"],
                "chick": ["Late night update", "After hours", "Night shift"],
                "nerd": ["Overnight processing", "Late cycle", "Night batch"],
                "rager": ["Too damn late", "Night shit", "Late chaos"],
                "ops": ["Night ops", "Late shift", "Overnight"],
                "tappit": ["Late night bru", "Graveyard shift", "Night run"],
                "comedian": ["Late night show", "Nobody watching", "Night performance"],
                "action": ["Night watch", "Late ops", "Midnight brief"],
            },
        }
        
        # Get greeting
        greeting = random.choice(greetings.get(daypart, {}).get(persona, ["Status"]))
        
        # Build status based on action and service
        if urgency >= 6:
            # Urgent situations
            status_parts = {
                "jarvis": [f"{service or 'service'} requires attention", f"{service or 'system'} incident detected", "immediate action required"],
                "dude": [f"{service or 'system'} needs help", f"{service or 'service'} acting up", "situation needs handling"],
                "chick": [f"{service or 'system'} needs attention", f"{service or 'service'} issue", "needs fixing"],
                "nerd": [f"{service or 'service'} error detected", f"{service or 'system'} failure", "diagnostics required"],
                "rager": [f"{service or 'system'} is fucked", f"{service or 'service'} broke", "fix this shit"],
                "ops": [f"{service or 'service'} down", f"{service or 'system'} failed", "action required"],
                "tappit": [f"{service or 'system'} kak", f"{service or 'service'} broken", "needs sorting"],
                "comedian": [f"{service or 'system'} dramatically failed", f"{service or 'service'} quit the show", "unexpected plot twist"],
                "action": [f"{service or 'system'} compromised", f"{service or 'service'} failed", "mission critical"],
            }
        elif action == "completed":
            # Success scenarios
            status_parts = {
                "jarvis": [f"{service or 'task'} completed successfully", f"{service or 'operation'} concluded", "all systems nominal"],
                "dude": [f"{service or 'task'} is done", f"{service or 'job'} finished", "everything's cool"],
                "chick": [f"{service or 'task'} completed perfectly", f"{service or 'job'} done", "looking good"],
                "nerd": [f"{service or 'task'} executed successfully", f"{service or 'operation'} validated", "metrics green"],
                "rager": [f"{service or 'shit'} done", f"{service or 'task'} sorted", "fucking finally"],
                "ops": [f"{service or 'task'} complete", f"{service or 'job'} finished", "confirmed"],
                "tappit": [f"{service or 'task'} sorted", f"{service or 'job'} done", "lekker clean"],
                "comedian": [f"{service or 'task'} somehow succeeded", f"{service or 'job'} finished against odds", "plot resolved"],
                "action": [f"{service or 'mission'} accomplished", f"{service or 'task'} complete", "objective achieved"],
            }
        elif action in ["started", "scheduled"]:
            # Starting scenarios
            status_parts = {
                "jarvis": [f"{service or 'task'} initiated", f"{service or 'operation'} beginning", "proceeding as planned"],
                "dude": [f"{service or 'task'} starting up", f"{service or 'job'} kicking off", "getting rolling"],
                "chick": [f"{service or 'task'} starting", f"{service or 'job'} beginning", "getting started"],
                "nerd": [f"{service or 'process'} initialized", f"{service or 'task'} commenced", "execution started"],
                "rager": [f"{service or 'shit'} starting", f"{service or 'task'} beginning", "here we go"],
                "ops": [f"{service or 'task'} started", f"{service or 'job'} initiated", "commenced"],
                "tappit": [f"{service or 'task'} starting", f"{service or 'job'} kicking off", "getting going"],
                "comedian": [f"{service or 'task'} attempting to start", f"{service or 'show'} beginning", "curtain rising"],
                "action": [f"{service or 'mission'} commencing", f"{service or 'operation'} initiated", "executing"],
            }
        else:
            # General status
            status_parts = {
                "jarvis": [f"{service or 'systems'} running smoothly", f"{service or 'operations'} stable", "everything under control"],
                "dude": [f"{service or 'system'} is cruising", f"{service or 'setup'} flowing", "all good"],
                "chick": [f"{service or 'system'} looking great", f"{service or 'setup'} running smooth", "everything's perfect"],
                "nerd": [f"{service or 'system'} operating nominally", f"{service or 'metrics'} within bounds", "status green"],
                "rager": [f"{service or 'shit'} working", f"{service or 'system'} running", "no problems"],
                "ops": [f"{service or 'system'} stable", f"{service or 'status'} green", "operational"],
                "tappit": [f"{service or 'system'} lekker", f"{service or 'setup'} smooth", "all good bru"],
                "comedian": [f"{service or 'system'} remarkably boring", f"{service or 'status'} uneventfully stable", "thrilling normalcy"],
                "action": [f"{service or 'system'} secure", f"{service or 'operation'} stable", "status green"],
            }
        
        status = random.choice(status_parts.get(persona, ["running"]))
        
        # Combine naturally
        if ":" in subject:
            # Subject has its own structure, just use greeting
            return f"{greeting} — {status}"
        else:
            # Clean subject structure
            return f"{greeting}, {status}"
            
    except:
        return f"{subject or 'Update'}"

def _generate_intelligent_riff(persona: str, ctx: Dict, slot: int) -> str:
    """Generate contextually intelligent riff lines"""
    try:
        service = ctx.get("primary_service")
        action = ctx.get("action")
        urgency = ctx.get("urgency", 0)
        
        # Service + Action specific intelligent responses
        # These sound natural, not templated
        responses = {
            ("backup", "completed"): {
                "jarvis": ["Backup archives validated and stored", "Data secured with verification complete", "Snapshot captured and confirmed"],
                "dude": ["Backup's in the bag, totally secure", "Data saved, no worries", "Snapshot done, chill mode"],
                "chick": ["Backup completed flawlessly", "Data preserved perfectly", "Archives looking pristine"],
                "nerd": ["Backup completed with checksum validation", "Data integrity confirmed across snapshots", "Archives verified against baseline"],
                "rager": ["Backup done, finally", "Data saved, stop asking", "Snapshot finished, relax"],
                "ops": ["Backup complete", "Archives stored", "Data secured"],
                "tappit": ["Backup sorted bru", "Data saved lekker", "Snapshot done clean"],
                "comedian": ["Backup somehow didn't fail", "Data preserved against all odds", "Snapshot succeeded surprisingly"],
                "action": ["Data secured and verified", "Backup mission accomplished", "Archives confirmed"],
            },
            ("docker", "restarted"): {
                "jarvis": ["Containers cycled cleanly", "Services refreshed and stable", "Orchestration resumed normally"],
                "dude": ["Containers restarted smooth", "Docker's back flowing", "Services up and rolling"],
                "chick": ["Containers refreshed beautifully", "Services restarted perfectly", "Docker looking great"],
                "nerd": ["Container runtime reinitialized", "Service orchestration restored", "Pods rescheduled successfully"],
                "rager": ["Containers restarted, working now", "Docker cycled, done", "Services back up"],
                "ops": ["Containers restarted", "Services restored", "Docker operational"],
                "tappit": ["Containers cycled bru", "Docker restarted lekker", "Services back up"],
                "comedian": ["Containers reluctantly restarted", "Docker cycled with minimal drama", "Services restored accidentally"],
                "action": ["Container stack secured", "Services restored to operational", "Docker mission complete"],
            },
            ("database", "completed"): {
                "jarvis": ["Database operations concluded successfully", "Queries optimized and executing well", "Transactions processing smoothly"],
                "dude": ["Database doing its thing", "Queries running smooth", "Data flowing nicely"],
                "chick": ["Database performing beautifully", "Queries executing perfectly", "Data processing flawlessly"],
                "nerd": ["Database operations within SLA", "Query performance optimal", "Transaction throughput nominal"],
                "rager": ["Database shit done", "Queries working", "Data processing"],
                "ops": ["Database operational", "Queries executing", "Transactions processing"],
                "tappit": ["Database sorted", "Queries running lekker", "Data flowing smooth"],
                "comedian": ["Database surprisingly functional", "Queries executing despite expectations", "Data processing miraculously"],
                "action": ["Database secure and operational", "Query performance confirmed", "Data integrity maintained"],
            },
            ("monitoring", "completed"): {
                "jarvis": ["Health checks passed across all systems", "Monitoring confirms stable operations", "All metrics within normal parameters"],
                "dude": ["Everything's checking out fine", "Monitoring shows all good", "Health checks passing"],
                "chick": ["All systems looking healthy", "Monitoring shows perfection", "Health checks passed beautifully"],
                "nerd": ["Health checks validated successfully", "Monitoring thresholds satisfied", "Metrics within acceptable variance"],
                "rager": ["Health checks done, all fine", "Monitoring shows no problems", "Everything working"],
                "ops": ["Health checks passed", "Monitoring green", "Systems healthy"],
                "tappit": ["Health checks lekker", "Monitoring all green", "Systems healthy bru"],
                "comedian": ["Health checks somehow passed", "Monitoring shows suspicious normalcy", "Everything functioning unexpectedly"],
                "action": ["All systems report green", "Health confirmed across infrastructure", "Monitoring mission complete"],
            },
            ("network", "connected"): {
                "jarvis": ["Network connectivity restored", "Routes established and stable", "Communications functioning normally"],
                "dude": ["Network's back online", "Connection restored smooth", "Everything's connected again"],
                "chick": ["Network connection restored perfectly", "Routes looking stable", "Communications back beautifully"],
                "nerd": ["Network connectivity reestablished", "Routing tables converged", "Latency within acceptable bounds"],
                "rager": ["Network back up finally", "Connection restored", "Routes working"],
                "ops": ["Network connected", "Routes established", "Connectivity restored"],
                "tappit": ["Network back up bru", "Connection lekker now", "Routes sorted"],
                "comedian": ["Network mysteriously reconnected", "Connectivity restored inexplicably", "Routes found their way back"],
                "action": ["Network secured and operational", "Communications established", "Routes confirmed"],
            },
            ("plex", "completed"): {
                "jarvis": ["Media library scan completed", "Content indexed and ready", "Streaming services prepared"],
                "dude": ["Plex scanned everything smooth", "Media library updated", "Streaming's ready to roll"],
                "chick": ["Media library looking perfect", "Content organized beautifully", "Streaming ready flawlessly"],
                "nerd": ["Library metadata synchronized", "Media index updated successfully", "Transcoding parameters optimized"],
                "rager": ["Plex scan done", "Media indexed", "Streaming working"],
                "ops": ["Media scan complete", "Library updated", "Plex operational"],
                "tappit": ["Plex sorted bru", "Media library updated", "Streaming lekker"],
                "comedian": ["Plex somehow finished scanning", "Media library updated surprisingly", "Streaming ready against odds"],
                "action": ["Media operations complete", "Library secured and indexed", "Streaming mission accomplished"],
            },
        }
        
        # Try to find specific response
        key = (service, action)
        if key in responses and persona in responses[key]:
            return random.choice(responses[key][persona])
        
        # Fallback to generic action responses
        generic_responses = {
            "completed": {
                "jarvis": ["Task completed successfully", "Operations concluded normally", "Execution finished cleanly"],
                "dude": ["Task finished smooth", "All done, no problems", "Wrapped up nicely"],
                "chick": ["Task completed perfectly", "Finished beautifully", "Done flawlessly"],
                "nerd": ["Execution completed successfully", "Task validated and closed", "Operation finished nominally"],
                "rager": ["Task done", "Finished finally", "Completed"],
                "ops": ["Task complete", "Operation finished", "Execution done"],
                "tappit": ["Task sorted", "Finished lekker", "Done clean"],
                "comedian": ["Task somehow completed", "Finished surprisingly", "Done against expectations"],
                "action": ["Mission accomplished", "Task completed", "Objective achieved"],
            },
            "failed": {
                "jarvis": ["Issue detected, reviewing", "Error encountered, investigating", "Problem identified, analyzing"],
                "dude": ["Something went wrong, checking it", "Issue popped up, looking into it", "Problem needs attention"],
                "chick": ["Issue needs fixing", "Error detected, handling it", "Problem needs attention"],
                "nerd": ["Error state detected, debugging", "Failure mode identified", "Exception logged for analysis"],
                "rager": ["Something broke, fix it", "Error happened, deal with it", "Problem needs sorting now"],
                "ops": ["Error detected", "Failure logged", "Issue identified"],
                "tappit": ["Something's kak, checking", "Error needs fixing", "Problem bru"],
                "comedian": ["Predictably failed", "Error as expected", "Problem right on schedule"],
                "action": ["Situation developing", "Issue identified", "Problem under review"],
            },
            "status": {
                "jarvis": ["Systems operating normally", "Status nominal across board", "All operations proceeding"],
                "dude": ["Everything's cruising", "All systems flowing", "Looking good overall"],
                "chick": ["Everything running smoothly", "Status looking perfect", "All systems great"],
                "nerd": ["Metrics within parameters", "Status nominal", "Operations stable"],
                "rager": ["Everything's working", "No problems now", "Status fine"],
                "ops": ["Status nominal", "Systems operational", "Running normal"],
                "tappit": ["All lekker", "Systems smooth", "Everything good bru"],
                "comedian": ["Unremarkably functional", "Boringly stable", "Surprisingly normal"],
                "action": ["All systems green", "Status secure", "Operations steady"],
            },
        }
        
        return random.choice(generic_responses.get(action, generic_responses["status"]).get(persona, ["Status nominal"]))
        
    except:
        return "Systems operational"

# ============================================================================
# ENHANCED PUBLIC API WITH NATURAL LANGUAGE
# ============================================================================

def lexi_quip(persona_name: str, *, with_emoji: bool = True, subject: str = "", body: str = "") -> str:
    """Generate natural conversational header"""
    try:
        persona = _canon(persona_name)
        subj = strip_transport_tags((subject or "Update").strip().replace("\n"," "))[:120]
        
        # Extract context
        ctx = _extract_smart_context(subject, body)
        
        # Generate natural header
        header = _generate_natural_header(persona, ctx, subj)
        
        # Add emoji
        return f"{header}{_maybe_emoji(persona, with_emoji)}"
    except:
        return f"{subject or 'Update'}: ok"

def lexi_riffs(persona_name: str, n: int = 3, *, with_emoji: bool = False, subject: str = "", body: str = "") -> List[str]:
    """Generate intelligent context-aware riff lines"""
    try:
        persona = _canon(persona_name)
        ctx = _extract_smart_context(subject, body)
        
        out: List[str] = []
        attempts = 0
        max_attempts = n * 5
        
        while len(out) < n and attempts < max_attempts:
            riff = _generate_intelligent_riff(persona, ctx, len(out))
            # Remove emojis and ensure uniqueness
            riff = re.sub(r"[\U0001F300-\U0001FAFF]", "", riff).strip()
            if riff and riff not in out and len(riff) <= 140:
                out.append(riff)
            attempts += 1
        
        # Fill with generic if needed
        while len(out) < n:
            out.append("Systems operational")
        
        return out[:n]
    except:
        return ["Status nominal", "Operations normal", "Systems stable"][:n]

def persona_header(persona_name: str, subject: str = "", body: str = "") -> str:
    """Generate natural persona header (top line)"""
    return lexi_quip(persona_name, with_emoji=True, subject=subject, body=body)

# ============================================================================
# LLM INTEGRATION (unchanged)
# ============================================================================

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
    """Generate LLM-powered riffs (when LLM enabled)"""
    if os.getenv("BEAUTIFY_LLM_ENABLED", "true").lower() not in ("1","true","yes"):
        return []
    
    try:
        key = _canon(persona_name)
        context = strip_transport_tags((context or "").strip())
        if not context:
            return []
        allow_prof = (key == "rager") or (os.getenv("PERSONALITY_ALLOW_PROFANITY", "false").lower() in ("1","true","yes"))
        
        llm = importlib.import_module("llm_client")
        
        base_tones = {
            "dude": "Laid-back slacker-zen; mellow, cheerful, kind. Keep it short, breezy, and confident.",
            "chick":"Glamorous couture sass; bubbly but razor-sharp. Supportive, witty, stylish, high standards.",
            "nerd":"Precise, pedantic, dry wit; obsessed with correctness, determinism, graphs, and tests.",
            "rager":"Intense, profane, street-tough cadence. Blunt, kinetic, zero patience for nonsense.",
            "comedian":"Deadpan spoof meets irreverent meta—fourth-wall pokes, concise and witty.",
            "action":"Terse macho one-liners; tactical, sardonic; mission-focused and decisive.",
            "jarvis":"Polished valet AI with calm, clinical machine logic. Courteous, anticipatory.",
            "ops":"Neutral SRE acks; laconic, minimal flourish.",
            "tappit": "South African bru/lekker slang; cheeky but clear; no filler.",
        }
        
        persona_tone = base_tones.get(key, "Short, clean, persona-true one-liners.")
        style_hint = f"daypart={_daypart()}, intensity={_intensity():.2f}, persona={key}"
        
        # Try persona_riff first
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

# Legacy compatibility
def quip(persona_name: str, *, with_emoji: bool = True) -> str:
    """Legacy canned quip (not used in production)"""
    return lexi_quip(persona_name, with_emoji=with_emoji, subject="Update", body="")

def build_header_and_riffs(persona_name: str, subject: str = "", body: str = "", max_riff_lines: int = 3) -> Tuple[str, List[str]]:
    """Build header and riffs (LLM primary, Lexi fallback)"""
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
