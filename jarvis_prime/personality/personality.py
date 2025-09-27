#!/usr/bin/env python3
# /app/personality.py  — Enhanced with time awareness and rich context
# Persona quip + Lexi engine for Jarvis Prime
#
# Enhanced features:
#   - Deep time awareness (hour, day, week, season, holidays)
#   - Rich contextual pattern detection
#   - Smart vocabulary expansion based on message content
#   - Intelligent template selection
#   - Technical domain awareness
#   - Operational context recognition

import random, os, importlib, re, time, calendar
from typing import List, Dict, Optional, Tuple
from datetime import datetime, date

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
    t = _TRANSPORT_TAG_RE.sub("", text)
    t = re.sub(r'\s*\[(?:smtp|proxy|gotify|apprise|email|poster|webhook|imap|ntfy|pushover|telegram)\]\s*', ' ', t, flags=re.I)
    return re.sub(r'\s{2,}', ' ', t).strip()

# ----------------------------------------------------------------------------
# Enhanced time awareness
# ----------------------------------------------------------------------------
def _get_time_context(now_ts: Optional[float] = None) -> Dict[str, any]:
    """Extract rich temporal context"""
    t = time.localtime(now_ts or time.time())
    dt = datetime.fromtimestamp(now_ts or time.time())
    
    # Basic daypart
    h = t.tm_hour
    if 0 <= h < 5:
        daypart = "deep_night"
    elif 5 <= h < 8:
        daypart = "early_morning"  
    elif 8 <= h < 12:
        daypart = "morning"
    elif 12 <= h < 14:
        daypart = "midday"
    elif 14 <= h < 17:
        daypart = "afternoon"
    elif 17 <= h < 20:
        daypart = "evening"
    elif 20 <= h < 23:
        daypart = "night"
    else:
        daypart = "late_night"
    
    # Day of week context
    weekday = t.tm_wday  # 0=Monday, 6=Sunday
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    
    # Week phase
    if weekday in [0, 1]:  # Mon, Tue
        week_phase = "week_start"
    elif weekday in [2, 3]:  # Wed, Thu
        week_phase = "mid_week"
    elif weekday == 4:  # Friday
        week_phase = "week_end"
    else:  # Weekend
        week_phase = "weekend"
    
    # Month context
    month = t.tm_mon
    day_of_month = t.tm_mday
    
    # Season (Northern hemisphere)
    if month in [12, 1, 2]:
        season = "winter"
    elif month in [3, 4, 5]:
        season = "spring"
    elif month in [6, 7, 8]:
        season = "summer"
    else:
        season = "autumn"
    
    # Special days detection
    is_month_start = day_of_month <= 3
    is_month_end = day_of_month >= 28
    is_weekend = weekday in [5, 6]
    
    return {
        "hour": h,
        "daypart": daypart,
        "weekday": weekday,
        "day_name": day_names[weekday],
        "week_phase": week_phase,
        "month": month,
        "day_of_month": day_of_month,
        "season": season,
        "is_month_start": is_month_start,
        "is_month_end": is_month_end,
        "is_weekend": is_weekend,
        "is_business_hours": 9 <= h <= 17 and not is_weekend
    }

def _intensity() -> float:
    try:
        v = float(os.getenv("PERSONALITY_INTENSITY", "1.0"))
        return max(0.6, min(2.0, v))
    except Exception:
        return 1.0

# ----------------------------------------------------------------------------
# Message context analysis
# ----------------------------------------------------------------------------
def _analyze_message_context(subject: str, body: str) -> Dict[str, any]:
    """Extract semantic context from message content"""
    text = f"{subject} {body}".lower()
    
    # System types
    system_types = {
        "docker": any(word in text for word in ["docker", "container", "pod", "k8s", "kubernetes"]),
        "database": any(word in text for word in ["mysql", "postgres", "mongodb", "redis", "db", "database"]),
        "backup": any(word in text for word in ["backup", "restore", "snapshot", "archive"]),
        "network": any(word in text for word in ["network", "dns", "firewall", "proxy", "nginx"]),
        "storage": any(word in text for word in ["disk", "storage", "filesystem", "mount"]),
        "monitoring": any(word in text for word in ["monitor", "alert", "metric", "grafana", "prometheus"])
    }
    
    # Operation types
    operations = {
        "deployment": any(word in text for word in ["deploy", "release", "rollout", "ship"]),
        "maintenance": any(word in text for word in ["maintenance", "update", "patch", "restart"]),
        "incident": any(word in text for word in ["down", "failed", "error", "critical", "outage"]),
        "completion": any(word in text for word in ["completed", "finished", "done", "success"]),
        "scheduled": any(word in text for word in ["scheduled", "cron", "daily", "weekly", "routine"])
    }
    
    # Severity indicators
    urgency_level = "normal"
    if any(word in text for word in ["critical", "emergency", "down", "failed"]):
        urgency_level = "high"
    elif any(word in text for word in ["warning", "degraded", "slow"]):
        urgency_level = "medium"
    elif any(word in text for word in ["info", "completed", "success"]):
        urgency_level = "low"
    
    # Scale indicators
    scale = "single"
    if any(word in text for word in ["cluster", "fleet", "multiple", "all"]):
        scale = "multiple"
    
    return {
        "systems": [k for k, v in system_types.items() if v],
        "operations": [k for k, v in operations.items() if v],
        "urgency": urgency_level,
        "scale": scale,
        "length": len(text),
        "has_numbers": bool(re.search(r'\d+', text)),
        "has_ips": bool(re.search(r'\b\d+\.\d+\.\d+\.\d+\b', text))
    }

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
    bank = EMOJIS.get(key) or []
    return f" {random.choice(bank)}" if bank else ""

# ----------------------------------------------------------------------------
# Enhanced persona bank mappings
# ----------------------------------------------------------------------------
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

# ----------------------------------------------------------------------------
# Enhanced lexicons with time and context awareness
# ----------------------------------------------------------------------------
_LEX: Dict[str, Dict[str, List[str]]] = {
    "ops": {
        "ack": [
            "ack","done","noted","executed","received","stable","running","applied","synced","completed",
            "success","confirmed","ready","scheduled","queued","accepted","active","closed","green","healthy",
            "rolled back","rolled forward","muted","paged","silenced","deferred","escalated","contained","optimized",
            "ratelimited","rotated","restarted","reloaded","validated","archived","reconciled","cleared","holding","watching",
            "backfilled","indexed","pruned","compacted","sealed","mirrored","snapshotted","scaled","throttled","hydrated"
        ]
    },
    
    "jarvis": {
        "line": [
            # Standard operations
            "archived; assured","telemetry aligned; noise filtered","graceful rollback prepared; confidence high",
            "housekeeping complete; logs polished","secrets vaulted; protocol upheld","latency escorted; budgets intact",
            "artifacts catalogued; reports curated","dashboards presentable; metrics aligned","after-hours service; composure steady",
            
            # Time-aware variants
            "dawn patrol complete; systems immaculate","morning briefing prepared; status pristine",
            "midday checkpoint passed; standards maintained","afternoon protocols observed; quality assured",
            "evening audit complete; records exemplary","night watch commenced; vigilance heightened",
            "weekend duty fulfilled; service uninterrupted","business hours concluded; operations seamless",
            
            # Context-aware variants  
            "deployment choreographed; staging flawless","incident contained; recovery elegant",
            "maintenance scheduled; downtime minimal","backup verified; restoration rehearsed",
            "monitoring calibrated; alerting refined","performance tuned; efficiency optimized"
        ]
    },
    
    "nerd": {
        "line": [
            # Standard technical
            "validated; consistent","checksums aligned; assertions hold","p99 stabilized; invariants preserved",
            "error rate bounded; throughput acceptable","deterministic; idempotent by design","schema respected; contract satisfied",
            
            # Time-contextual  
            "morning batch completed; overnight processing verified","midday metrics within bounds; performance nominal",
            "weekend job successful; Monday ready","end-of-week backup verified; integrity confirmed",
            "quarterly report generated; statistics normalized","monthly cleanup executed; space reclaimed",
            
            # System-specific
            "container orchestration stable; pods healthy","database consistency verified; ACID preserved",
            "network topology mapped; latency measured","storage allocation optimized; I/O balanced",
            "monitoring pipeline functional; data flowing","deployment pipeline green; tests passing"
        ]
    },
    
    "action": {
        "line": [
            # Standard tactical
            "targets green; advance approved","threat neutralized; perimeter holds","payload verified; proceed",
            "rollback vector armed; safety on","triage fast; stabilize faster","deploy quiet; results loud",
            
            # Time-tactical
            "dawn raid successful; objectives secured","morning brief complete; mission clear",
            "midday status; all sectors secure","evening debrief; ops nominal",
            "night shift ready; watch posted","weekend guard maintained; perimeter intact",
            
            # Operations-specific
            "deployment executed; beachhead established","incident contained; damage controlled",
            "maintenance completed; systems hardened","backup secured; recovery verified",
            "monitoring active; threats tracked","performance optimized; efficiency gained"
        ]
    },
    
    "dude": {
        "line": [
            # Standard chill
            "verified; keep it mellow","queues breathe; vibes stable","roll with it; no drama",
            "green checks; take it easy","cache hits high; chill intact","latency surfed; tide calm",
            
            # Time-chill
            "morning coffee deployed; day flows","lunch break systems; all smooth",
            "afternoon cruise; systems glide","evening wind-down; ops mellow",
            "weekend mode; systems coast","late night; quiet flows",
            
            # Context-chill
            "deployment surfed; no wipeouts","incident handled; still zen",
            "maintenance cruised; minimal waves","backup flowed; restoration ready",
            "monitoring chilled; alerts rare","performance smooth; no turbulence"
        ]
    },
    
    "chick": {
        "line": [
            # Standard glam
            "QA-clean; runway-ready","zero-downtime; she's grace","polish applied; ship with shine",
            "alerts commitment-ready; logs tasteful","secure defaults; couture correct","green across; camera-ready",
            
            # Time-glam
            "morning glow-up; systems fresh","lunch hour polish; midday shine",
            "afternoon touch-up; evening ready","night mode; systems sleek",
            "weekend refresh; Monday prep","late night glamour; systems stunning",
            
            # Context-glam
            "deployment styled; launch flawless","incident managed; composure intact",
            "maintenance polished; downtime minimal","backup curated; restoration elegant",
            "monitoring refined; alerts tasteful","performance optimized; efficiency chic"
        ]
    },
    
    "rager": {
        "rage": [
            # Standard rage
            "kill the flake; ship the fix","stop the damn noise; own the pager","sorted; now piss off",
            "you mother fucker you; done","fuckin' prick; fix merged","piece of shit; rollback clean",
            
            # Time-rage  
            "morning bullshit handled; coffee time","lunch interrupted; fixed anyway",
            "afternoon chaos contained; move on","evening clusterfuck resolved; go home",
            "weekend shit handled; back to life","late night garbage cleared; sleep now",
            
            # Context-rage
            "deployment unfucked; ship it","incident crushed; stop panicking", 
            "maintenance forced; deal with it","backup fixed; stop crying",
            "monitoring silenced; quit whining","performance improved; stop bitching"
        ]
    },
    
    "comedian": {
        "quip": [
            # Standard deadpan
            "remarkably unremarkable; thrillingly boring","adequate; save your applause","green and seen; don't clap at once",
            "plot twist: stable; credits roll quietly","laugh track muted; uptime refuses drama","peak normal; show cancelled",
            
            # Time-comedy
            "morning sitcom; episode boring","lunch break drama; cancelled",
            "afternoon comedy; audience left","evening special; featuring uptime",
            "weekend rerun; still not funny","late night comedy; systems sleep",
            
            # Context-comedy
            "deployment: the musical; reviews mixed","incident: horror movie; happy ending",
            "maintenance: documentary; critically acclaimed","backup: thriller; plot twist works",
            "monitoring: reality TV; surprisingly dull","performance: action movie; explosions minimal"
        ]
    },
    
    "tappit": {
        "line": [
            # Standard SA
            "sorted bru; lekker clean","sharp-sharp; no kak","howzit bru; all green",
            "pipeline smooth; keep it tidy","idling lekker; don't stall","give it horns; not drama",
            
            # Time SA
            "morning bakkie; systems loaded","lunch jol; midday cruise",
            "afternoon skiet; everything lekker","evening braai; ops chilled",
            "weekend lekker; systems rest","late night bakkie; quiet cruise",
            
            # Context SA  
            "deployment lekker; shipped clean","incident sorted; no more kak",
            "maintenance sharp; downtime brief","backup solid; restoration ready",
            "monitoring tidy; alerts quiet","performance lekker; efficiency up"
        ]
    }
}

# ----------------------------------------------------------------------------
# Time and context-aware template selection
# ----------------------------------------------------------------------------
def _get_contextual_templates(persona: str, time_ctx: Dict, msg_ctx: Dict) -> List[str]:
    """Select templates based on time and message context"""
    
    base_templates = [
        "{subj}: {a}. {b}.",
        "{subj} — {a}; {b}.", 
        "{subj}: {a}; {b}.",
        "{subj}: {a} and {b}."
    ]
    
    # Time-specific templates
    if time_ctx["daypart"] == "deep_night":
        night_templates = {
            "jarvis": ["{subj}: {a} — night watch; {b}."],
            "rager": ["{subj}: {a}. {b}. (3am bullshit)"],
            "dude": ["{subj}: {a}; {b} — midnight mellow."]
        }
        if persona in night_templates:
            base_templates.extend(night_templates[persona])
    
    if time_ctx["week_phase"] == "weekend":
        weekend_templates = {
            "jarvis": ["{subj}: {a} — weekend service; {b}."],
            "nerd": ["{subj}: {a}; {b} — off-hours processing."],
            "dude": ["{subj}: {a}; {b} — weekend vibes."]
        }
        if persona in weekend_templates:
            base_templates.extend(weekend_templates[persona])
    
    # Context-specific templates
    if "incident" in msg_ctx["operations"]:
        incident_templates = {
            "action": ["{subj}: threat {a}; response {b}."],
            "rager": ["{subj}: {a}. {b}. Fix it."],
            "jarvis": ["{subj}: incident {a}; recovery {b}."]
        }
        if persona in incident_templates:
            base_templates.extend(incident_templates[persona])
    
    if "scheduled" in msg_ctx["operations"]:
        routine_templates = [
            "{subj}: routine {a}; {b} as planned.",
            "{subj}: scheduled {a}; {b} on cadence.",
            "{subj}: {a} per schedule; {b}."
        ]
        base_templates.extend(routine_templates)
    
    return base_templates

# ----------------------------------------------------------------------------
# Enhanced vocabulary expansion
# ----------------------------------------------------------------------------
def _expand_vocabulary(persona: str, base_bank: List[str], time_ctx: Dict, msg_ctx: Dict) -> List[str]:
    """Expand vocabulary based on time and context"""
    
    expanded = base_bank.copy()
    
    # Time-based additions
    if time_ctx["is_weekend"]:
        weekend_terms = {
            "jarvis": ["weekend service", "off-hours precision", "leisure protocols"],
            "dude": ["weekend flow", "saturday chill", "sunday cruise"],
            "nerd": ["batch processing", "offline optimization", "scheduled maintenance"]
        }
        expanded.extend(weekend_terms.get(persona, []))
    
    if time_ctx["daypart"] in ["deep_night", "late_night"]:
        night_terms = {
            "jarvis": ["nocturnal efficiency", "after-hours service", "midnight precision"],
            "rager": ["graveyard shift", "night duty", "dark hours"],
            "dude": ["night session", "midnight flow", "late cruise"]
        }
        expanded.extend(night_terms.get(persona, []))
    
    # System-based additions
    if "docker" in msg_ctx["systems"]:
        container_terms = {
            "nerd": ["containerized", "orchestrated", "scaled pods"],
            "jarvis": ["orchestration complete", "pods aligned", "cluster managed"],
            "action": ["containers deployed", "pods secured", "cluster locked"]
        }
        expanded.extend(container_terms.get(persona, []))
    
    if "database" in msg_ctx["systems"]:
        db_terms = {
            "nerd": ["ACID compliant", "transactions committed", "indexes optimized"],
            "jarvis": ["data integrity maintained", "queries optimized", "schemas aligned"],
            "dude": ["data flowing", "queries smooth", "connections stable"]
        }
        expanded.extend(db_terms.get(persona, []))
    
    # Operation-based additions
    if "deployment" in msg_ctx["operations"]:
        deploy_terms = {
            "action": ["deployment executed", "payload delivered", "mission complete"],
            "nerd": ["rollout verified", "deployment validated", "release confirmed"],
            "jarvis": ["deployment orchestrated", "release managed", "rollout supervised"]
        }
        expanded.extend(deploy_terms.get(persona, []))
    
    return list(set(expanded))  # Remove duplicates

# ----------------------------------------------------------------------------
# Smart phrase selection with context awareness
# ----------------------------------------------------------------------------
def _choose_contextual_phrases(bank: List[str], msg_ctx: Dict, time_ctx: Dict) -> Tuple[str, str]:
    """Choose phrases that match the context"""
    
    # Filter for urgent contexts
    if msg_ctx["urgency"] == "high":
        urgent_phrases = [p for p in bank if any(word in p.lower() for word in 
                         ["immediate", "critical", "urgent", "fast", "quick", "now"])]
        if urgent_phrases and len(urgent_phrases) >= 2:
            return _choose_two(urgent_phrases)
    
    # Filter for routine contexts  
    if "scheduled" in msg_ctx["operations"]:
        routine_phrases = [p for p in bank if any(word in p.lower() for word in
                          ["scheduled", "routine", "planned", "regular", "cadence"])]
        if routine_phrases:
            a = random.choice(routine_phrases)
            b = random.choice([p for p in bank if p != a])
            return a, b
    
    # Default selection
    return _choose_two(bank)

def _choose_two(bank: List[str]) -> Tuple[str, str]:
    if len(bank) < 2:
        return (bank[0] if bank else "ok", "noted")
    a = random.choice(bank)
    b_choices = [x for x in bank if x != a]
    b = random.choice(b_choices) if b_choices else a
    return a, b

# ----------------------------------------------------------------------------
# Time and context token replacement
# ----------------------------------------------------------------------------
def _apply_contextual_replacements(persona: str, text: str, time_ctx: Dict, msg_ctx: Dict) -> str:
    """Apply time and context-aware token replacements"""
    
    # Time-based replacements
    time_flavors = {
        "deep_night": {
            "jarvis": "nocturnal precision",
            "rager": "graveyard bullshit", 
            "dude": "midnight mellow",
            "nerd": "after-hours processing"
        },
        "morning": {
            "jarvis": "morning protocols",
            "rager": "morning chaos",
            "dude": "morning flow", 
            "nerd": "daily startup"
        },
        "weekend": {
            "jarvis": "weekend service",
            "rager": "weekend duty",
            "dude": "weekend cruise",
            "nerd": "offline processing"
        }
    }
    
    # Context-based replacements
    context_flavors = {
        "incident": {
            "jarvis": "incident management",
            "action": "threat response",
            "rager": "firefighting mode",
            "nerd": "error handling"
        },
        "deployment": {
            "jarvis": "deployment supervision", 
            "action": "mission execution",
            "nerd": "release validation",
            "dude": "shipping smooth"
        }
    }
    
    # Apply time replacements
    if "{time}" in text:
        if time_ctx["is_weekend"]:
            flavor = time_flavors.get("weekend", {}).get(persona, "")
        else:
            flavor = time_flavors.get(time_ctx["daypart"], {}).get(persona, "")
        
        if flavor:
            text = text.replace("{time}", flavor)
        else:
            text = text.replace("{time}", "")
    
    # Apply context replacements
    for op in msg_ctx["operations"]:
        if f"{{{op}}}" in text:
            flavor = context_flavors.get(op, {}).get(persona, op)
            text = text.replace(f"{{{op}}}", flavor)
    
    return text

# ----------------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------------
def _canon(name: str) -> str:
    n = (name or "").strip().lower()
    key = ALIASES.get(n, n)
    return key if key in PERSONAS else "ops"

def _bank_for(persona: str, time_ctx: Dict, msg_ctx: Dict) -> List[str]:
    key = _PERSONA_BANK_KEY.get(persona, "ack")
    base_bank = _LEX.get(persona, {}).get(key, [])
    if not base_bank:
        base_bank = _LEX.get("ops", {}).get("ack", ["ok","noted"])
    
    return _expand_vocabulary(persona, base_bank, time_ctx, msg_ctx)

# ----------------------------------------------------------------------------
# Enhanced public API functions
# ----------------------------------------------------------------------------
def lexi_quip(persona_name: str, *, with_emoji: bool = True, subject: str = "", body: str = "") -> str:
    """Enhanced lexi quip with time and context awareness"""
    persona = _canon(persona_name)
    subj = strip_transport_tags((subject or "Update").strip().replace("\n"," "))[:120]
    
    # Get time and message context
    time_ctx = _get_time_context()
    msg_ctx = _analyze_message_context(subject, body)
    
    # Get contextual vocabulary and templates
    bank = _bank_for(persona, time_ctx, msg_ctx)
    templates = _get_contextual_templates(persona, time_ctx, msg_ctx)
    
    # Choose template and phrases
    tmpl = random.choice(templates)
    a, b = _choose_contextual_phrases(bank, msg_ctx, time_ctx)
    
    # Apply contextual replacements
    line = tmpl.format(subj=subj, a=a, b=b)
    line = _apply_contextual_replacements(persona, line, time_ctx, msg_ctx)
    
    # Add emoji
    line = f"{line}{_maybe_emoji(persona, with_emoji)}"
    return line

def lexi_riffs(persona_name: str, n: int = 3, *, with_emoji: bool = False, subject: str = "", body: str = "") -> List[str]:
    """Enhanced lexi riffs with context awareness"""
    persona = _canon(persona_name)
    subj = strip_transport_tags((subject or "Update").strip().replace("\n"," "))[:120]
    
    time_ctx = _get_time_context()
    msg_ctx = _analyze_message_context(subject, body)
    
    templates = _get_contextual_templates(persona, time_ctx, msg_ctx)
    bank = _bank_for(persona, time_ctx, msg_ctx)
    
    out: List[str] = []
    
    for _ in range(max(6, n*3)):  # oversample for uniqueness
        tmpl = random.choice(templates)
        a, b = _choose_contextual_phrases(bank, msg_ctx, time_ctx)
        
        base = tmpl.format(subj=subj, a=a, b=b)
        line = _apply_contextual_replacements(persona, base, time_ctx, msg_ctx)
        
        # Remove emojis for riffs
        line = re.sub(r"[\U0001F300-\U0001FAFF]", "", line).strip()
        
        if len(line) > 140:
            line = line[:140].rstrip()
        
        if line not in out:
            out.append(line)
        
        if len(out) >= n:
            break
    
    return out

def persona_header(persona_name: str, subject: str = "", body: str = "") -> str:
    """Generate context-aware persona header"""
    return lexi_quip(persona_name, with_emoji=True, subject=subject, body=body)

def build_header_and_riffs(persona_name: str, subject: str = "", body: str = "", max_riff_lines: int = 3) -> Tuple[str, List[str]]:
    """Build enhanced header and riffs with full context awareness"""
    header = persona_header(persona_name, subject=subject, body=body)
    
    # Try LLM riffs first, fallback to enhanced lexi riffs
    context = strip_transport_tags(" ".join([subject or "", body or ""]).strip())
    lines = []
    
    # Try LLM (existing function)
    try:
        lines = llm_quips(persona_name, context=context, max_lines=max_riff_lines)
    except:
        pass
    
    if not lines:
        lines = lexi_riffs(persona_name, n=max_riff_lines, with_emoji=False, subject=subject, body=body)
    
    # Ensure riffs contain no emoji
    lines = [re.sub(r"[\U0001F300-\U0001FAFF]", "", ln).strip() for ln in lines]
    return header, lines

# ----------------------------------------------------------------------------
# Legacy compatibility functions (unchanged)
# ----------------------------------------------------------------------------
def quip(persona_name: str, *, with_emoji: bool = True) -> str:
    """Legacy canned quip function"""
    key = ALIASES.get((persona