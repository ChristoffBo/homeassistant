#!/usr/bin/env python3
# /app/personality.py  — rebuilt per Christoff's spec with ENHANCED CONTEXT
# Persona quip + Lexi engine for Jarvis Prime
#
# ENHANCED: Smarter Lexi with deep context awareness and intelligent phrase generation
# Makes Lexi sound more natural and LLM-like without actual LLM calls
#
# Public API (unchanged entry points):
#   - quip(persona_name: str, *, with_emoji: bool = True) -> str
#   - llm_quips(persona_name: str, *, context: str = "", max_lines: int = 3) -> list[str]
#   - lexi_quip(persona_name: str, *, with_emoji: bool = True, subject: str = "", body: str = "") -> str
#   - lexi_riffs(persona_name: str, n: int = 3, *, with_emoji: bool = False, subject: str = "", body: str = "") -> list[str]
#   - persona_header(persona_name: str, subject: str = "", body: str = "") -> str
#
# Behavior per spec:
#   - TOP LINE: always Lexi (NOT LLM), time-aware, emoji allowed, NO "Lexi." suffix
#   - BOTTOM LINES: LLM riffs (no emoji); Lexi-only fallback if LLM is off/unavailable
#   - Strip transport tags like [SMTP]/[Proxy]/[Gotify]/... from inputs and outputs
#   - Expanded lexicons & sharper templates; Rager swears (meaningful), Tappit SA slang (no "rev-rev")

import random, os, importlib, re, time
from typing import List, Dict, Optional, Tuple

# ----------------------------------------------------------------------------
# Transport / source tag scrubber
# ----------------------------------------------------------------------------
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

# ----------------------------------------------------------------------------
# Enhanced time and context awareness
# ----------------------------------------------------------------------------
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

def _get_context_hints(subject: str = "", body: str = "") -> Dict[str, bool]:
    """Extract safe context hints from message content"""
    try:
        text = f"{subject} {body}".lower()
        
        return {
            # Urgency indicators
            "is_urgent": any(word in text for word in ["critical", "down", "failed", "error", "urgent", "emergency"]),
            "is_routine": any(word in text for word in ["backup", "scheduled", "daily", "weekly", "routine", "maintenance"]),
            "is_completion": any(word in text for word in ["completed", "finished", "done", "success", "passed"]),
            
            # System type hints
            "has_docker": any(word in text for word in ["docker", "container", "pod", "k8s", "kubernetes"]),
            "has_database": any(word in text for word in ["mysql", "postgres", "database", "db", "sql", "mongodb"]),
            "has_backup": any(word in text for word in ["backup", "restore", "snapshot", "archive"]),
            "has_network": any(word in text for word in ["network", "dns", "firewall", "proxy", "nginx"]),
            
            # Time context
            "is_weekend": time.localtime().tm_wday in [5, 6],
            "is_night": time.localtime().tm_hour < 6 or time.localtime().tm_hour > 22
        }
    except:
        return {
            "is_urgent": False, "is_routine": False, "is_completion": False,
            "has_docker": False, "has_database": False, "has_backup": False, 
            "has_network": False, "is_weekend": False, "is_night": False
        }

# ============================================================================
# NEW: SMART CONTEXT ANALYSIS FOR INTELLIGENT LEXI
# ============================================================================

def _extract_smart_context(subject: str = "", body: str = "") -> Dict:
    """
    Advanced context extraction for intelligent Lexi responses
    Analyzes patterns, numbers, services, and actions for natural language generation
    """
    try:
        text = f"{subject} {body}".lower()
        
        # Service/system detection with specificity
        services = {
            "sonarr": "sonarr" in text,
            "radarr": "radarr" in text,
            "plex": "plex" in text or "jellyfin" in text,
            "homeassistant": "home assistant" in text or "homeassistant" in text or "ha " in text,
            "docker": "docker" in text or "container" in text or "pod" in text,
            "database": any(db in text for db in ["mysql", "postgres", "mariadb", "mongodb", "sql", "database"]),
            "backup": "backup" in text or "snapshot" in text or "archive" in text,
            "network": any(net in text for net in ["network", "dns", "proxy", "nginx", "firewall", "vpn"]),
            "storage": any(stor in text for stor in ["disk", "storage", "mount", "volume", "raid", "zfs"]),
            "monitoring": any(mon in text for mon in ["uptime", "monitor", "health", "check", "ping", "analytics"]),
        }
        active_services = [k for k, v in services.items() if v]
        
        # Extract numbers and percentages
        numbers = re.findall(r'\b\d+(?:\.\d+)?%?\b', text)
        has_percentage = any('%' in n for n in numbers)
        has_large_number = any(int(re.sub(r'[^\d]', '', n)) > 1000 for n in numbers if re.sub(r'[^\d]', '', n))
        
        # Action/status detection
        actions = {
            "completed": any(word in text for word in ["completed", "finished", "done", "success", "passed", "ok"]),
            "started": any(word in text for word in ["started", "beginning", "initiated", "launching", "starting"]),
            "failed": any(word in text for word in ["failed", "error", "failure", "unsuccessful", "crashed"]),
            "warning": any(word in text for word in ["warning", "caution", "attention", "degraded", "slow"]),
            "updated": any(word in text for word in ["updated", "upgraded", "patched", "modified", "refreshed"]),
            "restarted": any(word in text for word in ["restarted", "rebooted", "cycled", "bounced", "restart"]),
            "connected": any(word in text for word in ["connected", "online", "up", "available", "restored"]),
            "disconnected": any(word in text for word in ["disconnected", "offline", "down", "unavailable", "lost"]),
        }
        active_action = next((k for k, v in actions.items() if v), "generic")
        
        # Urgency scoring (0-10)
        urgency_score = 0
        if any(word in text for word in ["critical", "emergency", "urgent", "immediate"]):
            urgency_score += 5
        if any(word in text for word in ["down", "offline", "failed", "error"]):
            urgency_score += 3
        if any(word in text for word in ["warning", "degraded", "slow"]):
            urgency_score += 2
        if any(word in text for word in ["success", "completed", "healthy", "ok"]):
            urgency_score -= 2
        urgency_score = max(0, min(10, urgency_score))
        
        # Pattern detection
        is_test = "test" in text
        is_notification = "notification" in text
        is_automated = any(auto in text for auto in ["scheduled", "automatic", "cron", "daily", "weekly"])
        
        return {
            "services": active_services,
            "primary_service": active_services[0] if active_services else None,
            "action": active_action,
            "urgency_score": urgency_score,
            "has_numbers": bool(numbers),
            "has_percentage": has_percentage,
            "has_large_number": has_large_number,
            "is_test": is_test,
            "is_notification": is_notification,
            "is_automated": is_automated,
            "numbers": numbers[:3],  # Keep first 3 numbers
        }
    except:
        return {
            "services": [], "primary_service": None, "action": "generic",
            "urgency_score": 0, "has_numbers": False, "has_percentage": False,
            "has_large_number": False, "is_test": False, "is_notification": False,
            "is_automated": False, "numbers": []
        }

def _generate_intelligent_phrase(persona: str, smart_context: Dict, slot: str = "a") -> str:
    """
    Generate contextually intelligent phrases based on deep analysis
    Makes Lexi sound more natural and LLM-like without actual LLM calls
    """
    try:
        service = smart_context.get("primary_service")
        action = smart_context.get("action", "generic")
        urgency = smart_context.get("urgency_score", 0)
        
        # Service-specific intelligent response patterns
        service_patterns = {
            "sonarr": {
                "completed": ["episode indexed", "series catalogued", "library synced", "metadata current", "queue cleared"],
                "updated": ["metadata refreshed", "episodes scanned", "queue processed", "series updated", "catalog synced"],
                "failed": ["download stalled", "import blocked", "source unavailable", "indexer timeout", "queue stuck"],
                "restarted": ["service cycled", "queue reset", "indexers reconnected", "monitoring resumed"],
                "generic": ["tv automation active", "series monitored", "queue managed", "episodes tracked", "library maintained"]
            },
            "radarr": {
                "completed": ["film archived", "movie indexed", "collection updated", "catalog current", "library complete"],
                "updated": ["catalog refreshed", "library synced", "metadata current", "movies scanned", "posters updated"],
                "failed": ["acquisition blocked", "import failed", "source missing", "indexer down", "download stalled"],
                "restarted": ["service restored", "indexers reconnected", "queue reloaded", "automation resumed"],
                "generic": ["movie automation live", "films tracked", "queue active", "collection managed", "catalog monitored"]
            },
            "plex": {
                "completed": ["media scanned", "library updated", "thumbnails generated", "transcode finished"],
                "updated": ["metadata refreshed", "posters synced", "library indexed", "database optimized"],
                "failed": ["scan failed", "database locked", "transcode error", "server unreachable"],
                "restarted": ["server cycled", "services restored", "streams reconnected", "plex reloaded"],
                "generic": ["streaming ready", "media served", "library accessible", "playback stable"]
            },
            "homeassistant": {
                "completed": ["automation executed", "scene applied", "devices synced", "entities updated"],
                "updated": ["config reloaded", "integrations synced", "entities refreshed", "dashboard current"],
                "failed": ["automation blocked", "device offline", "integration failed", "entity unavailable"],
                "restarted": ["core reloaded", "automations reset", "devices reconnected", "ha cycled"],
                "generic": ["home controlled", "automations active", "devices monitored", "scenes ready"]
            },
            "docker": {
                "completed": ["container stable", "orchestration complete", "stack healthy", "services aligned"],
                "restarted": ["services cycled", "containers refreshed", "runtime reset", "pods rescheduled"],
                "failed": ["container crashed", "pod failed", "orchestration blocked", "healthcheck timeout"],
                "updated": ["images pulled", "stack updated", "containers patched", "compose synced"],
                "generic": ["containers managed", "runtime stable", "orchestration active", "stack monitored"]
            },
            "database": {
                "completed": ["queries optimized", "transactions committed", "integrity verified", "indexes rebuilt"],
                "updated": ["schema synced", "indexes rebuilt", "tables optimized", "stats refreshed"],
                "failed": ["connection lost", "query blocked", "transaction failed", "deadlock detected"],
                "restarted": ["connections reset", "pools refreshed", "service cycled", "replicas synced"],
                "generic": ["data layer stable", "queries responsive", "connections pooled", "transactions flowing"]
            },
            "backup": {
                "completed": ["archives sealed", "snapshots verified", "retention applied", "backup validated"],
                "started": ["backup initiated", "snapshot capturing", "data securing", "archive building"],
                "failed": ["backup blocked", "snapshot failed", "retention missed", "destination unreachable"],
                "generic": ["backup cycle active", "archives managed", "snapshots current", "retention enforced"]
            },
            "network": {
                "completed": ["routes updated", "firewall synced", "dns propagated", "traffic flowing"],
                "connected": ["link established", "gateway reachable", "routes stable", "connectivity restored"],
                "disconnected": ["link down", "gateway lost", "route unreachable", "connectivity failed"],
                "updated": ["rules applied", "config synced", "zones updated", "policies refreshed"],
                "generic": ["network stable", "traffic routed", "connections managed", "firewall active"]
            },
            "storage": {
                "completed": ["volumes mounted", "raid synced", "quotas applied", "pool healthy"],
                "warning": ["space low", "degraded array", "smart warning", "quota approaching"],
                "failed": ["mount failed", "disk error", "raid degraded", "pool unavailable"],
                "generic": ["storage healthy", "volumes accessible", "arrays stable", "capacity managed"]
            },
            "monitoring": {
                "completed": ["checks passed", "metrics collected", "alerts cleared", "health confirmed"],
                "failed": ["check failed", "timeout exceeded", "endpoint down", "probe unsuccessful"],
                "updated": ["metrics refreshed", "alerts synced", "thresholds updated", "dashboards current"],
                "generic": ["monitoring active", "metrics flowing", "health tracked", "alerts configured"]
            },
        }
        
        # Get service-specific patterns or fall back to generic
        patterns = service_patterns.get(service, {})
        phrases = patterns.get(action, patterns.get("generic", ["status nominal", "system stable"]))
        
        # Urgency modifiers
        if urgency >= 7:
            urgency_mods = ["immediate", "critical", "urgent", "priority"]
        elif urgency >= 4:
            urgency_mods = ["attention", "check", "review", "monitor"]
        else:
            urgency_mods = []
        
        # Combine intelligently
        base_phrase = random.choice(phrases)
        if urgency_mods and slot == "a" and urgency >= 5:
            return f"{random.choice(urgency_mods)} {base_phrase}"
        
        return base_phrase
        
    except:
        return "status nominal"

# ============================================================================
# END SMART CONTEXT ADDITIONS
# ============================================================================

def _intensity() -> float:
    try:
        v = float(os.getenv("PERSONALITY_INTENSITY", "1.0"))
        return max(0.6, min(2.0, v))
    except Exception:
        return 1.0

# ----------------------------------------------------------------------------
# Personas, aliases, emojis (unchanged)
# ----------------------------------------------------------------------------
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
    "chick":["💅","✨","💖","👛","🛍️","💋"],
    "nerd":["🤓","📐","🧪","🧠","⌨️","📚"],
    "rager":["🤬","🔥","💥","🗯️","⚡","🚨"],
    "comedian":["😑","😂","🎭","🙃","🃏","🥸"],
    "action":["💪","🧨","🛡️","🚁","🏹","🗡️"],
    "jarvis":["🤖","🧠","🎩","🪄","📊","🛰️"],
    "ops":["⚙️","📊","🧰","✅","📎","🗂️"],
    "tappit":["🏁","🛠️","🚗","🔧","🛞","🇿🇦"]
}

def _maybe_emoji(key: str, with_emoji: bool) -> str:
    if not with_emoji:
        return ""
    try:
        bank = EMOJIS.get(key) or []
        return f" {random.choice(bank)}" if bank else ""
    except:
        return ""

# ----------------------------------------------------------------------------
# CANNED QUIPS (kept for compatibility)
# ----------------------------------------------------------------------------
QUIPS = {
    "ops": ["ack.","done.","noted.","executed.","received.","stable.","running.","applied.","synced.","completed."],
    "jarvis": [
        "As always, sir, a great pleasure watching you work.",
        "Status synchronized, sir; elegance maintained.",
        "I've taken the liberty of tidying the logs.",
        "Telemetry aligned; do proceed.",
        "Your request has been executed impeccably.",
        "All signals nominal; shall I fetch tea?",
        "Diagnostics complete; no anomalies worth your time.",
        "I archived the artifacts; future-you will approve.",
        "Quiet nights are my love letter to ops.",
    ],
    "dude": ["The Dude abides; the logs can, like, chill.","Party on, pipelines. CI is totally non-bogus."],
    "chick":["That's hot—ship it with sparkle.","Zero-downtime? She's beauty, she's grace."],
    "nerd":["This is the optimal outcome. Bazinga.","Measured twice; compiled once."],
    "rager":["Say downtime again. I fucking dare you.","Push it now or I'll lose my goddamn mind."],
    "comedian":["Remarkably unremarkable—my favorite kind of uptime.","Doing nothing is hard; you never know when you're finished."],
    "action":["Consider it deployed.","System secure. Threat neutralized."],
    "tappit":["Howzit bru—green lights all round.","Lekker clean; keep it sharp-sharp."],
}

def _apply_daypart_flavor_inline(persona: str, text: str, context_hints: Dict = None) -> str:
    """Enhanced context-aware flavor injection"""
    try:
        dp = _daypart()
        
        # Enhanced time-based flavor table
        table = {
            "early_morning": {
                "rager": "too early for this shit",
                "jarvis": "pre-dawn service, discreet",
                "chick": "first-light polish",
                "dude": "quiet boot cycle",
                "tappit": "early start, sharp-sharp",
                "action": "dawn ops, silent",
                "nerd": "early batch processing",
                "comedian": "sunrise comedy, nobody laughing"
            },
            "morning": {
                "rager": "coffee then chaos, not now",
                "jarvis": "morning throughput aligned",
                "chick": "daylight-ready glam",
                "dude": "fresh-cache hours",
                "tappit": "morning run, no kak",
                "action": "morning brief, proceed",
                "nerd": "daily standup validated",
                "comedian": "morning show, still boring"
            },
            "afternoon": {
                "rager": "peak-traffic nonsense trimmed",
                "jarvis": "prime-time cadence",
                "chick": "runway hours",
                "dude": "cruising altitude",
                "tappit": "midday jol, keep it tidy",
                "action": "afternoon ops, steady",
                "nerd": "optimal processing window",
                "comedian": "matinee performance, empty seats"
            },
            "evening": {
                "rager": "golden hour, don't start",
                "jarvis": "twilight shift, composed",
                "chick": "prime-time glam",
                "dude": "dusk patrol vibes",
                "tappit": "evening cruise, no drama",
                "action": "evening watch, alert",
                "nerd": "end-of-day validation",
                "comedian": "evening news, nobody watching"
            },
            "late_night": {
                "rager": "too late for your bullshit",
                "jarvis": "after-hours, immaculate",
                "chick": "after-party polish",
                "dude": "midnight mellow",
                "tappit": "graveyard calm, bru",
                "action": "night watch, silent",
                "nerd": "overnight processing",
                "comedian": "late night, audience asleep"
            }
        }
        
        # Context-based flavor overrides
        if context_hints:
            if context_hints.get("is_urgent"):
                urgent_flavors = {
                    "jarvis": "immediate attention required",
                    "rager": "urgent shit needs fixing",
                    "action": "critical mission status",
                    "dude": "emergency, but chill"
                }
                flavor = urgent_flavors.get(persona, "")
            elif context_hints.get("is_weekend"):
                weekend_flavors = {
                    "jarvis": "weekend service protocols",
                    "rager": "weekend duty bullshit",
                    "dude": "weekend vibes active",
                    "tappit": "weekend jol mode"
                }
                flavor = weekend_flavors.get(persona, "")
            else:
                flavor = table.get(dp, {}).get(persona, "")
        else:
            flavor = table.get(dp, {}).get(persona, "")
        
        if not flavor:
            return text
        
        # Replace {time} token if present
        if "{time}" in text:
            return text.replace("{time}", flavor)
        return text
    except:
        return text.replace("{time}", "") if "{time}" in text else text

# ----------------------------------------------------------------------------
# Public API: canned quip (kept; not used for header post-rebuild)
# ----------------------------------------------------------------------------
def quip(persona_name: str, *, with_emoji: bool = True) -> str:
    try:
        key = ALIASES.get((persona_name or "").strip().lower(), (persona_name or "").strip().lower()) or "ops"
        if key not in QUIPS:
            key = "ops"
        bank = QUIPS.get(key, QUIPS["ops"])
        line = random.choice(bank) if bank else ""
        if _intensity() > 1.25 and line and line[-1] in ".!?":
            line = line[:-1] + random.choice([".", "!", "!!"])
        line = _apply_daypart_flavor_inline(key, line + " {time}").replace(" {time}", "")
        return f"{line}{_maybe_emoji(key, with_emoji)}"
    except:
        return "ack."

# ----------------------------------------------------------------------------
# Helper: canonicalize persona key
# ----------------------------------------------------------------------------
def _canon(name: str) -> str:
    try:
        n = (name or "").strip().lower()
        key = ALIASES.get(n, n)
        return key if key in PERSONAS else "ops"
    except:
        return "ops"

# ----------------------------------------------------------------------------
# LLM plumbing (enhanced with context awareness)
# ----------------------------------------------------------------------------
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
    if os.getenv("BEAUTIFY_LLM_ENABLED", "true").lower() not in ("1","true","yes"):
        return []
    
    try:
        key = _canon(persona_name)
        context = strip_transport_tags((context or "").strip())
        if not context:
            return []
        allow_prof = (key == "rager") or (os.getenv("PERSONALITY_ALLOW_PROFANITY", "false").lower() in ("1","true","yes"))
        
        llm = importlib.import_module("llm_client")
        
        # Enhanced context-aware persona descriptions
        context_hints = _get_context_hints("", context)
        daypart = _daypart()
        
        # Build enhanced persona tone with context
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
        
        # Add context enhancements
        context_additions = []
        if context_hints["is_urgent"]:
            context_additions.append(f"{daypart} emergency response mode")
        elif context_hints["is_weekend"]:
            context_additions.append(f"{daypart} weekend operations")
        else:
            context_additions.append(f"{daypart} operations")
        
        if context_hints["has_docker"]:
            context_additions.append("container environment")
        if context_hints["has_database"]:
            context_additions.append("database operations")
        if context_hints["has_backup"]:
            context_additions.append("backup/restore context")
        
        enhanced_tone = persona_tone
        if context_additions:
            enhanced_tone += f" Context: {', '.join(context_additions)}."
        
        style_hint = f"daypart={daypart}, intensity={_intensity():.2f}, persona={key}"
        
        # Primary persona_riff
        if hasattr(llm, "persona_riff"):
            try:
                lines = llm.persona_riff(
                    persona=key,
                    context=context,
                    max_lines=int(max_lines or int(os.getenv("LLM_PERSONA_LINES_MAX", "3") or 3)),
                    timeout=int(os.getenv("LLM_TIMEOUT_SECONDS", "8")),
                    cpu_limit=int(os.getenv("LLM_MAX_CPU_PERCENT", "70")),
                    models_priority=os.getenv("LLM_MODELS_PRIORITY", "").split(",") if os.getenv("LLM_MODELS_PRIORITY") else None,
                    base_url=os.getenv("LLM_OLLAMA_BASE_URL", "") or os.getenv("OLLAMA_BASE_URL", ""),
                    model_url=os.getenv("LLM_MODEL_URL", ""),
                    model_path=os.getenv("LLM_MODEL_PATH", "")
                )
                lines = _post_clean(lines, key, allow_prof)
                if lines:
                    return lines
            except Exception:
                pass
        
        # Fallback rewrite
        if hasattr(llm, "rewrite"):
            try:
                sys_prompt = (
                    "YOU ARE A PITHY ONE-LINER ENGINE.\n"
                    f"Persona: {key}.\n"
                    f"Tone: {enhanced_tone}\n"
                    f"Context flavor: {style_hint}.\n"
                    f"Rules: Produce ONLY {min(3, max(1, int(max_lines or 3)))} lines; each under 140 chars.\n"
                    "No lists, no numbers, no JSON, no labels."
                )
                user_prompt = "Context (for vibes only):\n" + context + "\n\nWrite the lines now:"
                raw = llm.rewrite(
                    text=f"""[SYSTEM]
{sys_prompt}
[INPUT]
{user_prompt}
[OUTPUT]
""",
                    mood=key,
                    timeout=int(os.getenv("LLM_TIMEOUT_SECONDS", "8")),
                    cpu_limit=int(os.getenv("LLM_MAX_CPU_PERCENT", "70")),
                    models_priority=os.getenv("LLM_MODELS_PRIORITY", "").split(",") if os.getenv("LLM_MODELS_PRIORITY") else None,
                    base_url=os.getenv("LLM_OLLAMA_BASE_URL", "") or os.getenv("OLLAMA_BASE_URL", ""),
                    model_url=os.getenv("LLM_MODEL_URL", ""),
                    model_path=os.getenv("LLM_MODEL_PATH", ""),
                    allow_profanity=True if key == "rager" else bool(os.getenv("PERSONALITY_ALLOW_PROFANITY", "false").lower() in ("1","true","yes")),
                )
                lines = [ln.strip(" -*\t") for ln in (raw or "").splitlines() if ln.strip()]
                lines = _post_clean(lines, key, allow_prof)
                return lines
            except Exception:
                pass
        
        return []
    except:
        return []

# ----------------------------------------------------------------------------
# === ENHANCED LEXI ENGINE WITH INTELLIGENT CONTEXT ===========================
# ----------------------------------------------------------------------------
# Persona→bank key mapping for headers
_PERSONA_BANK_KEY = {
    "ops": "ack",
    "rager": "rage",
    "comedian": "quip",
    "action": "line",
    "jarvis": "line",
    "tappit": "line",
    "dude": "line",
    "chick": "line",
    "nerd": "line",
}

# Base lexicons (kept for fallback)
_LEX: Dict[str, Dict[str, List[str]]] = {
    "ops": {
        "ack": [
            "ack","done","noted","executed","received","stable","running","applied","synced","completed",
            "success","confirmed","ready","scheduled","queued","accepted","active","closed","green","healthy",
        ]
    },
    "jarvis": {
        "line": [
            "archived; assured","telemetry aligned; noise filtered","graceful rollback prepared; confidence high",
            "housekeeping complete; logs polished","secrets vaulted; protocol upheld","latency escorted; budgets intact",
        ]
    },
    "nerd": {
        "line": [
            "validated; consistent","checksums aligned; assertions hold","p99 stabilized; invariants preserved",
            "error rate bounded; throughput acceptable","deterministic; idempotent by design","schema respected; contract satisfied",
        ]
    },
    "action": {
        "line": [
            "targets green; advance approved","threat neutralized; perimeter holds","payload verified; proceed",
            "rollback vector armed; safety on","triage fast; stabilize faster","deploy quiet; results loud",
        ]
    },
    "comedian": {
        "quip": [
            "remarkably unremarkable; thrillingly boring","adequate; save your applause","green and seen; don't clap at once",
            "plot twist: stable; credits roll quietly","laugh track muted; uptime refuses drama","peak normal; show cancelled",
        ]
    },
    "dude": {
        "line": [
            "verified; keep it mellow","queues breathe; vibes stable","roll with it; no drama",
            "green checks; take it easy","cache hits high; chill intact","latency surfed; tide calm",
        ]
    },
    "chick": {
        "line": [
            "QA-clean; runway-ready","zero-downtime; she's grace","polish applied; ship with shine",
            "alerts commitment-ready; logs tasteful","secure defaults; couture correct","green across; camera-ready",
        ]
    },
    "rager": {
        "rage": [
            "kill the flake; ship the fix","stop the damn noise; own the pager","sorted; now piss off",
            "you mother fucker you; done","fuckin' prick; fix merged","piece of shit; rollback clean",
        ]
    },
    "tappit": {
        "line": [
            "sorted bru; lekker clean","sharp-sharp; no kak","howzit bru; all green",
            "pipeline smooth; keep it tidy","idling lekker; don't stall","give it horns; not drama",
        ]
    }
}

# Enhanced templates
_TEMPLATES: Dict[str, List[str]] = {
    "default": [
        "{subj}: {a}. {b}.",
        "{subj} — {a}; {b}.",
        "{subj}: {a} and {b}.",
        "{subj}: {a}; {b}."
    ],
    "nerd": [
        "{subj}: {a}; {b}.",
        "{subj}: formally {a}, technically {b}.",
        "{subj}: {a} — {time}; {b}.",
        "{subj}: {a}; invariants hold; {b}."
    ],
    "jarvis": [
        "{subj}: {a}. {b}.",
        "{subj}: {a}; {b}.",
        "{subj}: {a} — {time}; {b}.",
        "{subj}: {a}; {b}. As you wish."
    ],
    "rager": [
        "{subj}: {a}. {b}.",
        "{subj} — {a}, {b}.",
        "{subj}? {a}. {b}.",
        "{subj}: {a}. {b}."
    ],
    "tappit": [
        "{subj}: {a}. {b}.",
        "{subj} — {a}; {b}.",
        "{subj}: {a}; {b}.",
        "{subj}: {a}. {b}."
    ],
    "ops": [
        "{subj}: {a}. {b}.",
        "{subj}: {a}; {b}.",
        "{subj} — {a}. {b}.",
        "{subj}: {a}. {b}."
    ],
    "dude": [
        "{subj}: {a}. {b}.",
        "{subj} — {a}; {b}.",
        "{subj}: {a}; {b}.",
        "{subj}: {a}. {b}."
    ],
    "chick": [
        "{subj}: {a}. {b}.",
        "{subj} — {a}; {b}.",
        "{subj}: {a}; {b}.",
        "{subj}: {a}. {b}."
    ],
    "comedian": [
        "{subj}: {a}. {b}.",
        "{subj} — {a}; {b}.",
        "{subj}: {a}; {b}.",
        "{subj}: {a}. {b}."
    ],
    "action": [
        "{subj}: {a}. {b}.",
        "{subj} — {a}; {b}.",
        "{subj}: {a}; {b}.",
        "{subj}: {a}. {b}."
    ],
}

def _bank_for(persona: str, smart_context: Dict = None) -> List[str]:
    """Get vocabulary bank with intelligent context expansion"""
    try:
        key = _PERSONA_BANK_KEY.get(persona, "ack")
        base_bank = _LEX.get(persona, {}).get(key, [])
        if not base_bank:
            base_bank = _LEX.get("ops", {}).get("ack", ["ok","noted"])
        
        # If smart context available, use intelligent phrase generation
        if smart_context and smart_context.get("primary_service"):
            # Generate 2 intelligent phrases
            intelligent_phrases = [
                _generate_intelligent_phrase(persona, smart_context, "a"),
                _generate_intelligent_phrase(persona, smart_context, "b")
            ]
            # Mix with base bank (70% intelligent, 30% base)
            combined = intelligent_phrases + intelligent_phrases + intelligent_phrases + base_bank
            return combined
        
        return base_bank
    except:
        return ["ok", "noted"]

def _templates_for(persona: str) -> List[str]:
    """Get templates"""
    try:
        return _TEMPLATES.get(persona, _TEMPLATES.get("default", []))
    except:
        return _TEMPLATES.get("default", [])

def _choose_two(bank: List[str]) -> Tuple[str, str]:
    try:
        if len(bank) < 2:
            return (bank[0] if bank else "ok", "noted")
        a = random.choice(bank)
        b_choices = [x for x in bank if x != a]
        b = random.choice(b_choices) if b_choices else a
        return a, b
    except:
        return ("ok", "noted")

# --- Public: Enhanced Lexi header quip with intelligent context ---
def lexi_quip(persona_name: str, *, with_emoji: bool = True, subject: str = "", body: str = "") -> str:
    """Enhanced lexi quip with intelligent context awareness"""
    try:
        persona = _canon(persona_name)
        subj = strip_transport_tags((subject or "Update").strip().replace("\n"," "))[:120]
        
        # Get smart context for intelligent phrase generation
        smart_context = _extract_smart_context(subject, body)
        context_hints = _get_context_hints(subject, body)
        
        # Get contextual vocabulary and templates
        bank = _bank_for(persona, smart_context)
        templates = _templates_for(persona)
        
        # Choose template and phrases
        tmpl = random.choice(templates)
        a, b = _choose_two(bank)
        
        # Format and apply context
        line = tmpl.format(subj=subj, a=a, b=b, time="{time}")
        line = _apply_daypart_flavor_inline(persona, line, context_hints)
        
        # Add emoji
        line = f"{line}{_maybe_emoji(persona, with_emoji)}"
        return line
    except:
        return f"{subject or 'Update'}: ok. noted."

# --- Public: Enhanced Lexi riffs with intelligent context ---
def lexi_riffs(persona_name: str, n: int = 3, *, with_emoji: bool = False, subject: str = "", body: str = "") -> List[str]:
    """Enhanced lexi riffs with intelligent context awareness"""
    try:
        persona = _canon(persona_name)
        subj = strip_transport_tags((subject or "Update").strip().replace("\n"," "))[:120]
        body_clean = strip_transport_tags((body or "").strip())
        
        # Get smart context for intelligent phrase generation
        smart_context = _extract_smart_context(subject, body)
        context_hints = _get_context_hints(subject, body)
        
        templates = _templates_for(persona)
        bank = _bank_for(persona, smart_context)
        
        out: List[str] = []
        
        for _ in range(max(6, n*3)):  # oversample for uniqueness
            tmpl = random.choice(templates)
            a, b = _choose_two(bank)
            base = tmpl.format(subj=subj, a=a, b=b, time="{time}")
            base = _apply_daypart_flavor_inline(persona, base, context_hints)
            line = base
            
            # Hard cap length and strip emoji (no emoji for riffs)
            line = re.sub(r"[\U0001F300-\U0001FAFF]", "", line)  # remove emojis
            line = line.strip()
            if len(line) > 140:
                line = line[:140].rstrip()
            if line not in out:
                out.append(line)
            if len(out) >= n:
                break
        
        return out
    except:
        return [f"{subject or 'Update'}: ok.", "noted.", "done."][:n]

# --- Convenience header generator used by caller for the TOP line ------------
def persona_header(persona_name: str, subject: str = "", body: str = "") -> str:
    """Generate enhanced intelligent context-aware persona header"""
    return lexi_quip(persona_name, with_emoji=True, subject=subject, body=body)

# --- Helper to build full message: header + riffs (LLM primary) --------------
def build_header_and_riffs(persona_name: str, subject: str = "", body: str = "", max_riff_lines: int = 3) -> Tuple[str, List[str]]:
    """Build enhanced header and riffs with full intelligent context awareness"""
    try:
        header = persona_header(persona_name, subject=subject, body=body)
        # Bottom lines: LLM first (no emoji), Lexi fallback
        context = strip_transport_tags(" ".join([subject or "", body or ""]).strip())
        lines = llm_quips(persona_name, context=context, max_lines=max_riff_lines)
        if not lines:
            lines = lexi_riffs(persona_name, n=max_riff_lines, with_emoji=False, subject=subject, body=body)
        # Ensure riffs contain no emoji
        lines = [re.sub(r"[\U0001F300-\U0001FAFF]", "", ln).strip() for ln in lines]
        return header, lines
    except:
        return f"{subject or 'Update'}: ok.", ["noted.", "done."]
