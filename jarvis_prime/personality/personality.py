#!/usr/bin/env python3
# /app/personality.py  — Enhanced version with personality-rich header generation
# Persona quip + Lexi engine for Jarvis Prime
#
# Public API (unchanged entry points):
#   - quip(persona_name: str, *, with_emoji: bool = True) -> str
#   - llm_quips(persona_name: str, *, context: str = "", max_lines: int = 3) -> list[str]
#   - lexi_quip(persona_name: str, *, with_emoji: bool = True, subject: str = "", body: str = "") -> str
#   - lexi_riffs(persona_name: str, n: int = 3, *, with_emoji: bool = False, subject: str = "", body: str = "") -> list[str]
#   - persona_header(persona_name: str, subject: str = "", body: str = "") -> str
#
# ENHANCED: Top-line headers now use personality-rich vocabulary instead of bland technical terms

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

def _intensity() -> float:
    try:
        v = float(os.getenv("PERSONALITY_INTENSITY", "1.0"))
        return max(0.6, min(2.0, v))
    except Exception:
        return 1.0

# ----------------------------------------------------------------------------
# Personas, aliases, emojis
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
# Enhanced personality-rich lexicons for headers
# ----------------------------------------------------------------------------
_ENHANCED_LEX: Dict[str, Dict[str, List[str]]] = {
    "jarvis": {
        "signature": [
            "telemetry curated", "protocols aligned", "service immaculate", "housekeeping complete",
            "diagnostics elegant", "configuration poised", "settings domesticated", "notifications courteous",
            "alerts groomed", "logs polished", "cadence refined", "posture composed",
            "maintenance discreet", "orchestration tailored", "compliance effortless", "monitoring genteel",
            "graceful execution", "civilized deployment", "refined rollback", "courteous failover",
            "precision maintained", "etiquette preserved", "timing impeccable", "delivery seamless",
            "artifacts catalogued", "reports curated", "dashboards presentable", "metrics aligned",
            "uptime curated", "boredom exemplary", "trace polished", "journals logged",
            "alerts domesticated", "confidence exceeds risk", "maintenance passed unnoticed", "records immaculate"
        ],
        "completion": [
            "mission accomplished gracefully", "task executed flawlessly", "protocol completed immaculately",
            "service rendered elegantly", "configuration perfected quietly", "settings calibrated precisely",
            "notifications trained properly", "alerts educated thoroughly", "system tutored completely",
            "handover elegant", "notes precise", "orchestration poised", "choreography exact"
        ],
        "monitoring": [
            "watchful supervision", "attentive monitoring", "vigilant oversight", "careful observation",
            "dedicated surveillance", "mindful tracking", "respectful logging", "courteous alerting",
            "observability curated", "dashboards dapper", "telemetry monogrammed", "graphs tailored"
        ],
        "maintenance": [
            "thoughtful upkeep", "careful preservation", "diligent maintenance", "respectful archiving",
            "gentle housekeeping", "precise calibration", "mindful optimization", "courteous rotation",
            "secrets rotated", "memories short", "artifacts dusted", "indexes fragrant"
        ]
    },
    "rager": {
        "signature": [
            "shit handled", "bullshit eliminated", "crap sorted", "nonsense crushed", "garbage cleared",
            "mess cleaned", "chaos tamed", "drama killed", "noise silenced", "clutter purged",
            "flakes destroyed", "junk removed", "trash deleted", "waste eliminated", "prick alert silenced",
            "asshole behavior stopped", "dumb fuck bug dead", "piece of shit fixed", "goddamn noise killed"
        ],
        "completion": [
            "fucking done", "goddamn finished", "shit completed", "crap resolved", "mess sorted",
            "problem crushed", "issue destroyed", "bug murdered", "error eliminated", "bastard task finished"
        ],
        "urgent": [
            "emergency handled", "crisis crushed", "disaster averted", "catastrophe prevented",
            "shitstorm calmed", "clusterfuck resolved", "trainwreck avoided", "fire extinguished"
        ]
    },
    "nerd": {
        "signature": [
            "algorithmically verified", "mathematically confirmed", "statistically validated", "empirically proven",
            "deterministically executed", "logically consistent", "formally verified", "computationally sound",
            "analytically confirmed", "systematically validated", "methodically proven", "rigorously tested",
            "checksums aligned", "assertions hold", "p99 stabilized", "invariants preserved", "schema respected"
        ],
        "completion": [
            "theorem proved", "assertion validated", "hypothesis confirmed", "invariant maintained",
            "constraint satisfied", "predicate holds", "function converged", "algorithm terminated",
            "refactor proven", "complexity down", "entropy reduced", "order restored"
        ],
        "monitoring": [
            "metrics normalized", "variance bounded", "distribution stable", "samples sufficient",
            "confidence interval tight", "p-value significant", "correlation strong", "telemetry coherent"
        ]
    },
    "dude": {
        "signature": [
            "totally handled", "completely chilled", "absolutely mellow", "thoroughly relaxed",
            "peacefully resolved", "calmly completed", "smoothly finished", "easily sorted",
            "effortlessly done", "naturally flowing", "gently settled", "quietly resolved",
            "vibes aligned", "karma balanced", "flow steady", "drama nil"
        ],
        "completion": [
            "ride complete", "wave surfed", "flow maintained", "vibe preserved", "chill achieved",
            "zen attained", "karma balanced", "harmony restored", "peace established", "cruise control engaged"
        ]
    },
    "chick": {
        "signature": [
            "flawlessly executed", "perfectly styled", "elegantly completed", "beautifully finished",
            "gracefully handled", "stylishly resolved", "fashionably done", "gorgeously polished",
            "glamorously completed", "sophisticatedly finished", "charmingly resolved", "QA-clean",
            "runway-ready", "zero-downtime grace", "polish applied", "couture correct"
        ],
        "completion": [
            "look perfected", "style locked", "aesthetic achieved", "polish applied", "glam complete",
            "finish flawless", "presentation perfect", "appearance immaculate", "wardrobe updated"
        ]
    },
    "action": {
        "signature": [
            "mission accomplished", "target neutralized", "objective secured", "operation complete",
            "threat eliminated", "area cleared", "perimeter secured", "position held",
            "extraction successful", "deployment clean", "execution precise", "strike effective",
            "targets green", "payload verified", "rollback vector armed", "guard the SLO"
        ],
        "completion": [
            "enemy down", "target destroyed", "threat neutralized", "mission success",
            "objective achieved", "area secured", "position taken", "victory confirmed",
            "contact light", "mission first", "extract successful", "area safe"
        ]
    },
    "comedian": {
        "signature": [
            "remarkably unremarkable", "thrillingly boring", "spectacularly mundane", "dramatically dull",
            "hilariously ordinary", "comically normal", "absurdly routine", "ironically stable",
            "paradoxically predictable", "surprisingly unsurprising", "entertainingly bland",
            "peak normal", "thrilling news", "laugh track muted", "sequels delayed"
        ],
        "completion": [
            "applause withheld", "encore cancelled", "standing ovation postponed", "curtain call skipped",
            "comedy complete", "joke delivered", "punchline landed", "audience satisfied",
            "credits rolled", "show cancelled", "pilot renewed"
        ]
    },
    "tappit": {
        "signature": [
            "lekker sorted", "sharp-sharp done", "properly handled", "netjies completed", "skoon finished",
            "tidy resolved", "clean executed", "neat accomplished", "sorted properly", "handled sharp",
            "howzit green", "all gees", "no kak", "pipeline smooth", "lekker clean"
        ],
        "completion": [
            "job lekker", "work sharp", "task netjies", "mission skoon", "duty sorted",
            "assignment tidy", "operation clean", "objective neat", "boet stable", "tjop done"
        ]
    },
    "ops": {
        "signature": [
            "acknowledged", "executed", "completed", "processed", "handled", "resolved", "finished",
            "applied", "synced", "confirmed", "validated", "archived", "scaled", "deployed"
        ]
    }
}

# Enhanced subject-aware vocabulary selection
def _get_subject_context(subject: str) -> str:
    """Determine subject context for vocabulary selection"""
    subject_lower = subject.lower()
    
    if any(word in subject_lower for word in ["test", "notification", "alert", "email"]):
        return "notification"
    elif any(word in subject_lower for word in ["backup", "archive", "snapshot"]):
        return "maintenance"  
    elif any(word in subject_lower for word in ["deploy", "release", "rollout"]):
        return "completion"
    elif any(word in subject_lower for word in ["monitor", "watch", "check", "health"]):
        return "monitoring"
    elif any(word in subject_lower for word in ["urgent", "critical", "emergency", "down"]):
        return "urgent"
    elif any(word in subject_lower for word in ["config", "setting", "setup"]):
        return "completion"
    else:
        return "general"

def _enhanced_bank_for(persona: str, subject: str = "", context_hints: Dict = None) -> List[str]:
    """Get enhanced personality-rich vocabulary bank"""
    persona_lex = _ENHANCED_LEX.get(persona, {})
    
    # Start with signature personality terms (highest priority)
    bank = persona_lex.get("signature", []).copy()
    
    # Add context-specific terms based on subject
    subject_context = _get_subject_context(subject)
    if subject_context in persona_lex:
        bank.extend(persona_lex[subject_context])
    
    # Add context hints vocabulary
    if context_hints:
        if context_hints.get("is_urgent") and "urgent" in persona_lex:
            bank.extend(persona_lex["urgent"])
        elif context_hints.get("is_completion") and "completion" in persona_lex:
            bank.extend(persona_lex["completion"])
        elif context_hints.get("is_routine") and "maintenance" in persona_lex:
            bank.extend(persona_lex["maintenance"])
    
    # Fallback to basic terms if empty
    if not bank:
        bank = ["ready", "confirmed", "completed", "processed"]
    
    return bank

# Enhanced template selection with personality-specific patterns
_PERSONALITY_TEMPLATES: Dict[str, List[str]] = {
    "jarvis": [
        "{subj}: {a}; {b}.",
        "{subj}: {a}. {b}, sir.",
        "{subj}: {a}; {b}. As you wish.",
        "{subj}: {a}. {b}; protocols maintained.",
        "{subj}: {a}; {b}. Service immaculate.",
        "{subj} — {a}; {b}. Elegance preserved."
    ],
    "rager": [
        "{subj}: {a}. {b}.",
        "{subj} — {a}, {b}.",
        "{subj}: fucking {a}; {b}.",
        "{subj}: {a}. {b}. Done.",
        "{subj} — {a}; goddamn {b}."
    ],
    "nerd": [
        "{subj}: {a}; {b}.",
        "{subj}: formally {a}, empirically {b}.",
        "{subj}: {a} ∴ {b}.",
        "{subj}: {a}; {b}. QED.",
        "{subj}: algorithmically {a}; {b}."
    ],
    "comedian": [
        "{subj}: {a}. {b}. *crickets*",
        "{subj} — {a}; {b}. Try the veal.",
        "{subj}: {a}; {b}. Thank you, I'll be here all week.",
        "{subj}: {a}. {b}. *rimshot*"
    ],
    "action": [
        "{subj}: {a}. {b}.",
        "{subj} — {a}; {b}. Mission complete.",
        "{subj}: {a}. {b}. Over and out.",
        "{subj}: {a}; {b}. Target acquired."
    ],
    "dude": [
        "{subj}: {a}. {b}, man.",
        "{subj} — totally {a}; {b}.",
        "{subj}: {a}; {b}. Righteous.",
        "{subj}: like, {a}; {b}."
    ],
    "chick": [
        "{subj}: {a}. {b}, gorgeous.",
        "{subj} — {a}; {b}. Stunning.",
        "{subj}: {a}; {b}. Absolutely divine.",
        "{subj}: {a}. {b}. Perfection."
    ],
    "tappit": [
        "{subj}: {a}. {b}, bru.",
        "{subj} — {a}; {b}. Sharp-sharp.",
        "{subj}: {a}; {b}. Lekker.",
        "{subj}: {a}. {b}. Howzit."
    ],
    "ops": [
        "{subj}: {a}. {b}.",
        "{subj}: {a}; {b}.",
        "{subj} — {a}. {b}."
    ]
}

def _choose_personality_pair(bank_list: List[str]) -> Tuple[str, str]:
    """Choose two distinct personality-rich terms"""
    if len(bank_list) < 2:
        return (bank_list[0] if bank_list else "ready", "confirmed")
    
    a = random.choice(bank_list)
    # Try to avoid similar words
    b_choices = [x for x in bank_list if x != a and not any(word in x.lower() for word in a.lower().split())]
    if not b_choices:
        b_choices = [x for x in bank_list if x != a]
    b = random.choice(b_choices) if b_choices else "confirmed"
    return a, b

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
# CANNED QUIPS (kept for compatibility; fallback only)
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
        context_hints = _get_context_hints(subject, body)
        templates = _templates_for(persona, context_hints)
        bank = _bank_for(persona, context_hints)
        
        out: List[str] = []
        
        # Try to echo a key body phrase if available (simple heuristic)
        key_phrase = ""
        m = re.search(r"(integrity check passed|latency .*? (spike|back to baseline)|retention rotated|snapshot(s)? (done|archived)|no action required|error rate .*?bounded)", body, flags=re.I)
        if m:
            key_phrase = m.group(0).strip().rstrip(".")
        
        for _ in range(max(6, n*3)):  # oversample for uniqueness
            tmpl = random.choice(templates)
            a, b = _choose_two(bank)
            base = tmpl.format(subj=subj, a=a, b=b, time="{time}")
            base = _apply_daypart_flavor_inline(persona, base, context_hints)
            line = base
            
            if key_phrase:
                if not line.endswith("."):
                    line += "."
                line += f" {key_phrase.lower()}."
            
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
    """Generate enhanced context-aware persona header using personality-rich vocabulary"""
    return lexi_quip(persona_name, with_emoji=True, subject=subject, body=body)

# --- Helper to build full message: header + riffs (LLM primary) --------------
def build_header_and_riffs(persona_name: str, subject: str = "", body: str = "", max_riff_lines: int = 3) -> Tuple[str, List[str]]:
    """Build enhanced header and riffs with full context awareness"""
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

# --- Test examples -----------------------------------------------------------
if __name__ == "__main__":
    test_cases = [
        ("jarvis", "Sonarr - Test Notification", "Email settings successfully configured"),
        ("rager", "Critical System Alert", "Database connection failed"),
        ("nerd", "Algorithm Performance", "Optimization completed successfully"),
        ("dude", "Backup Status", "Daily backup completed"),
        ("chick", "Style Update", "CSS changes deployed"),
        ("action", "Security Update", "Firewall rules updated"),
        ("comedian", "Monitoring Alert", "Everything is fine"),
        ("tappit", "Service Status", "All systems operational")
    ]
    
    print("Enhanced Header Examples:")
    print("=" * 60)
    for persona, subject, body in test_cases:
        header = persona_header(persona, subject=subject, body=body)
        print(f"{persona.upper()}: {header}")
        
        # Show riffs too
        _, riffs = build_header_and_riffs(persona, subject=subject, body=body, max_riff_lines=2)
        for riff in riffs:
            print(f"    {riff}")
        print()
    
    # Compare old vs new for Jarvis
    print("\nJARVIS COMPARISON:")
    print("=" * 60)
    print("OLD (bland): Update: fast-forwarded; reconciled. ✅")
    print("NEW (rich):", persona_header("jarvis", "Sonarr - Test Notification", "Email settings successfully configured"))
    print()
    print("OLD (bland): Config Update: applied; synced. 🤖")  
    print("NEW (rich):", persona_header("jarvis", "Config Update", "Database settings modified"))
    print()
    print("OLD (bland): System Status: validated; confirmed. 🤖")
    print("NEW (rich):", persona_header("jarvis", "System Status", "Health check completed successfully"))_hints("", context)
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
# === ENHANCED LEXI ENGINE ===================================================
# ----------------------------------------------------------------------------
# Persona→bank key mapping for headers (legacy fallback)
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

# Legacy lexicons for riffs only (headers use enhanced)
_LEX: Dict[str, Dict[str, List[str]]] = {
    "ops": {
        "ack": [
            "ack","done","noted","executed","received","stable","running","applied","synced","completed",
            "success","confirmed","ready","scheduled","queued","accepted","active","closed","green","healthy",
            "rolled back","rolled forward","muted","paged","silenced","deferred","escalated","contained","optimized",
            "ratelimited","rotated","restarted","reloaded","validated","archived","reconciled","cleared","holding","watching",
            "backfilled","indexed","pruned","compacted","sealed","mirrored","snapshotted","scaled","throttled","hydrated",
            "drained","fenced","provisioned","retired","quarantined","sharded","replicated","promoted","demoted","cordoned",
            "untainted","gc run","scrubbed","checkpointed","rebased","fast-forwarded","replayed","rolled","mounted","unmounted",
            "attached","detached","invalidated","revoked","renewed","trimmed","balanced","resynced","realigned","rekeyed",
            "reindexed","retuned","patched"
        ]
    },
    "jarvis": {
        "line": [
            "archived; assured","telemetry aligned; noise filtered","graceful rollback prepared; confidence high",
            "housekeeping complete; logs polished","secrets vaulted; protocol upheld","latency escorted; budgets intact",
            "artifacts catalogued; reports curated","dashboards presentable; metrics aligned","after-hours service; composure steady",
            "failover rehearsal passed; perimeter calm","cache generous; etiquette maintained","encryption verified; perimeter secure",
            "uptime curated; boredom exemplary","trace polished; journals logged","alerts domesticated; only signal remains",
            "confidence exceeds risk; proceed","maintenance passed unnoticed; records immaculate","graceful nudge applied; daemon compliant",
            "quiet mitigation; impact nil","indexes tidy; archives in order","change window honored; optics clean",
            "handover elegant; notes precise","backpressure civilized; queues courteous","fail-safe primed; decorum intact",
            "replicas attentive; quorum polite","rate limits gentlemanly; costs discreet","noise quarantined; signal escorted",
            "cadence even; posture composed","rollouts courteous; guardrails present","backfills mannered; histories neat",
            "concurrency tamed; threads well-behaved","latency chauffeured; jitter brief","budget respected; refinement visible",
            "orchestration poised; choreography exact","secrets rotated; memories short","observability curated; dashboards dapper",
            "incidents domesticated; pages rare","degradations declined; polish ascendant","resilience rehearsed; etiquette immaculate",
            "audit trails luminous; paperwork minimal","artifacts dusted; indexes fragrant","drift corrected; symmetry restored",
            "telemetry monogrammed; graphs tailored","uptime framed; silence intentional","handoff seamless; provenance clear",
            "compliance effortless; posture impeccable","cache refreshed; manners intact","locks courteous; contention modest",
            "footprint light; impact negligible","availability tailored; elegance constant",
            # Context-aware additions
            "containers orchestrated; pods aligned","database integrity maintained; queries optimized","backup verified; restoration elegant",
            "network topology secured; traffic routed","weekend service; protocols maintained","emergency response; composure intact"
        ]
    },
    "nerd": {
        "line": [
            "validated; consistent","checksums aligned; assertions hold","p99 stabilized; invariants preserved",
            "error rate bounded; throughput acceptable","deterministic; idempotent by design","schema respected; contract satisfied",
            "graph confirms; model agrees","SLA satisfied; telemetry coherent","unit tests pass; coverage sane",
            "retry with jitter; backpressure OK","NTP aligned; time monotonic","GC pauses low; alloc rate steady",
            "argmin reached; variance small","latency within CI; budgets safe","tail risk negligible; outliers trimmed",
            "refactor proven; complexity down","DRY upheld; duplication removed","entropy reduced; order restored",
            "cache locality improved; misses down","branch prediction friendly; stalls rare","O(n) achieved; constants trimmed",
            "deadlocks absent; liveness holds","heap pressure stable; fragmentation low","index selectivity high; scans minimal",
            "AP chose availability; consistency eventual","CAP respected; trade-offs explicit","Amdahl smiles; parallelism sane",
            "cold starts amortized; warm paths preferred","hash distribution uniform; collisions rare",
            "cardinality understood; histograms honest","idempotence intact; retries cheap","time-series compact; deltas tidy",
            "throughput linear; headroom visible","latency histogram civilized; tails cut","variance explained; R² smug",
            "feature flags gated; blast radius tiny","circuit closed; fallback asleep","read-after-write coherent enough",
            "bounded queues; fair scheduling","causal order preserved; replays exact","roll-forward safe; rollbacks rehearsed",
            "mutexes minimal; contention mapped","allocations pooled; GC naps","vectorized path wins; scalar retires",
            "cache warm; TLB polite","TLS fast; handshakes trimmed","telemetry cardinality bounded; cost sane",
            "SLO met; error budget plush","kanban flow; WIP low","postmortem short; learnings long",
            # Context-aware additions
            "container orchestration validated; YAML parsed","ACID properties confirmed; transactions atomic","backup checksums verified; restoration tested",
            "DNS resolution optimized; queries cached","weekend batch processing; cron validated","emergency algorithm executed; complexity linear"
        ]
    },
    "action": {
        "line": [
            "targets green; advance approved","threat neutralized; perimeter holds","payload verified; proceed",
            "rollback vector armed; safety on","triage fast; stabilize faster","deploy quiet; results loud",
            "guard the SLO; hold the line","extract successful; area safe","scope trimmed; blast radius minimal",
            "contact light; switch traffic","mission first; ego last","abort gracefully; re-attack smarter",
            "eyes up; logs live","stack locked; breach denied","move silent; ship violent",
            "path clear; burn down","patch hot; risk cold","cutover clean; chatter zero",
            "tempo high; friction low","signal up; noise down","defuse page; secure core",
            "map terrain; flank failure","pin the root; pull the weed","toggle flag; steer fate",
            "breach sealed; assets safe","hit window; exit crisp","ops steady; hands calm",
            "lean scope; lethal focus","pressure on; panic off","hold discipline; win uptime",
            "smoke tested; doors open","grid stable; threat boxed","air cover ready; roll",
            "recon done; execute clean","no drama; just shipping","armor up; regressions down",
            "route traffic; trace truth","calm voice; sharp actions","contain blast; save face",
            "clear runway; punch it","patch discipline; posture strong","reload services; hold axis",
            "compartmentalize risk; breathe","hand-off tight; mission intact","drill paid off; ops sings",
            "suppress alarms; track targets","eyes on gauges; trust plan","exfil logs; lock vault",
            # Context-aware additions
            "containers deployed; pods secured","database secured; access controlled","backup mission complete; data extracted",
            "network perimeter secured; traffic filtered","weekend ops; skeleton crew","emergency protocols active; all hands"
        ]
    },
    "comedian": {
        "quip": [
            "remarkably unremarkable; thrillingly boring","adequate; save your applause","green and seen; don't clap at once",
            "plot twist: stable; credits roll quietly","laugh track muted; uptime refuses drama","peak normal; show cancelled",
            "retro skipped; nothing exploded","applause optional; graphs yawn","jokes aside; it actually works",
            "deadpan OK; try not to faint","boring graphs win; sequels delayed","we did it; Jenkins takes the bow",
            "thrilling news: nothing is wrong","latency on time; comedy off","confetti in staging; not here",
            "no cliffhangers; just commits","punchline withheld; service delivered","pilot renewed; drama not",
            "laughs in monotony; cries in errors","green bars—audience left early","credits rolled; pager slept",
            "build so dull it's beautiful","the bug cancelled itself","SRE: the silent comedians",
            "silence is my laugh track","our outage arc was cut","spoiler: it's fine","bloopers only in dev",
            "slapstick-free deploy","stand-up for uptime","bananas not on the floor","cue cards say 'boring'",
            "clowns off-duty; graphs beige","insert laugh; remove alert","sitcom rerun: stability",
            "punch-up cancelled; prod safe","tight five on reliability","heckler muted; 200 OK",
            "open mic closed; SLA met","callback landed; queues drained","slow clap saved for later",
            "kill the laugh track; keep the SLO","bit killed; bug too","props to caching; no acting",
            "crowd left; uptime stayed","one-liners only; zero fires","low effort; high effect",
            "final joke: nothing broke",
            # Context-aware additions
            "container comedy; pod cast cancelled","database sitcom; queries boring","backup special; restore routine",
            "network comedy; packets predictable","weekend rerun; same old stable","emergency drama; anticlimactic ending"
        ]
    },
    "dude": {
        "line": [
            "verified; keep it mellow","queues breathe; vibes stable","roll with it; no drama",
            "green checks; take it easy","cache hits high; chill intact","latency surfed; tide calm",
            "nap secured; alerts low","ride the wave; ship small","be water; flow steady",
            "friction low; sandals on","pager quiet; hammock loud","steady flow; no whitecaps",
            "easy does it; deploy smooth","logs zen; noise gone","coffee warm; ops cool",
            "cruise control; hands light","steady stoke; bugs smoked","float mode; errors sunk",
            "cool breeze; hotfix cold","vibes aligned; graphs kind","mellow merge; drama nil",
            "calm seas; green buoys","flow state; stress late","good karma; clean schema",
            "no sweat; just set","lazy river; quick commits","keep it loose; checks tight",
            "low tide errors; high tide wins","sand between toes; not gears","latency chilled; surf up",
            "cozy cache; sunny CI","flip-flop deploys; barefoot ops","chill pipeline; brisk results",
            "dawn patrol; build glassy","easy paddle; quick ride","stoked on SLOs; mellow on egos",
            "zen master of retries","soft landings; soft pretzels","keep rolling; keep cool",
            "laid back; locked in","margarita metrics; salt rim","vibe check: all green",
            "fog lifts; logs clear","waves small; smiles big","ship tiny; sleep heavy",
            "go with the flow; glow","drama-free zone; zone in","light breeze; heavy uptime",
            "good juju; clean deploy",
            # Context-aware additions
            "containers flowing; pods chilling","database cruising; queries smooth","backup surfed; restore easy",
            "network flowing; packets riding","weekend vibes; systems coasting","emergency handled; still zen"
        ]
    },
    "chick": {
        "line": [
            "QA-clean; runway-ready","zero-downtime; she's grace","polish applied; ship with shine",
            "alerts commitment-ready; logs tasteful","secure defaults; couture correct","green across; camera-ready",
            "perf smooth; silk finish","refactor = self-care; release worthy","gatekept prod; VIPs only",
            "makeup on; bugs off","latency sleek; heels higher","wardrobe change; no costume drama",
            "hair did; graphs did too","lip gloss popping; errors dropping","fit checked; build checked",
            "playlist vibing; deploy sliding","eyeliner sharp; cuts cleaner","couture cache; chic checks",
            "uptime glows; pager dozes","staging flirted; prod committed","heels steady; metrics petty",
            "smudge-proof SLA; kiss-proof deploy","catwalk to prod; trip-free","couture config; zero cringe",
            "silk rollback; velvet rollout","accessories minimal; impact maximal","bottled polish; uncorked ship",
            "pearls on; rough edges off","seamless seams; spotless logs","mascara dry; code crisp",
            "mirror checks; alert checks","velvet ropes; tight scopes","dewy graphs; matte risks",
            "clean palette; clean pipeline","gold hoops; zero loops","high gloss; low noise",
            "tucked edges; tight cadence","sleek silhouette; slim latencies","shine on; bugs gone",
            "dramatic liner; calm deploy","mood board says 'ship'","fit for prod; fit for print",
            "couture cadence; error-free","capsule release; timeless","no smears; no smolders",
            "tasteful trims; tasteful logs","glam yes; outages no","cat-eye sharp; rollback soft",
            "silhouette strong; incidents weak",
            # Context-aware additions
            "containers styled; pods polished","database glamour; queries elegant","backup couture; restore chic",
            "network fashion; traffic flowing","weekend glow-up; systems fresh","emergency makeup; still flawless"
        ]
    },
    "rager": {
        "rage": [
            "kill the flake; ship the fix","stop the damn noise; own the pager","sorted; now piss off",
            "you mother fucker you; done","fuckin' prick; fix merged","piece of shit; rollback clean",
            "asshole alert; silenced","dumb fuck bug; dead","fuck face error; crushed",
            "prick bastard test; unflaked","shit stain retry; throttled","goddamn punk alarm; gagged",
            "what the fuck spike; cooled","latency leashed; back to baseline","blast radius contained; move",
            "talk less; ship more","root cause or bust; do it now","ffs patch; deploy hot",
            "own it; stop guessing","pager sings; you dance","green or gone; pick",
            "no more cowboy deploys; grow up","fix the root; not my mood","stop click-opsing prod; read the runbook",
            "feature flag it; or I flag you","silence the alert; or I silence your access",
            "cut the crap; merge clean","ship or shut it","slam the gate; hold the line",
            "stop the thrash; pick a plan","quit hand-waving; bring data","patch the leak; not the story",
            "burn the flake; freeze the scope","no tourists in prod; badge up","alerts are rent; pay them",
            "shock the cache; cool the heat","tighten blast radius; grow spine","ship small; swear less",
            "argue later; page now","we fix fast; we don't whine","dogpile the root; starve the noise",
            "no mystery meat; label it","switch traffic; stop panic","own the rollback; own the win",
            "push the patch; pull the risk","turn off hero mode; turn on discipline","ban chaos; invite repeatability",
            "your excuse crashed; mine shipped","risk is loud; rigor is louder","hold the standard; hold your tongue",
            # Context-aware additions
            "containers unfucked; pods working","database shit fixed; queries fast","backup bullshit done; restore ready",
            "network crap sorted; traffic moving","weekend duty; deal with it","emergency chaos; I'll handle it"
        ]
    },
    "tappit": {
        "line": [
            "sorted bru; lekker clean","sharp-sharp; no kak","howzit bru; all green",
            "pipeline smooth; keep it tidy","idling lekker; don't stall","give it horns; not drama",
            "latency chilled; budgets safe","jol still smooth; nothing dodgy","no kak here; bru it's mint",
            "solid like a boerie roll; carry on","lekker tidy; keep the wheels straight","netjies man; pipeline in gear",
            "all gees; no grease","voetsek to noise; keep signal","shaya small; ship neat",
            "graphs skoon; vibes dop","moer-alert quiet; ops calm","lekker pull; clean push",
            "bakkie packed; no rattles","boet, stable; jy weet","tjop done; salad cool",
            "line lekker; queue short","no jang; just jol","bundu bash bugs; leave prod",
            "braai smoke off; alarms off","gear engaged; no clutch slip","no nonsense; just lekker",
            "SLA gesort; pager slaap","moenie stress; alles fine","tjoepstil errors; groot smile",
            "boerie budget; chips cheap","kan nie kla; graphs mooi","kiff ship; safe trip",
            "don't kak around; release","dop cold; deploy cooler","bakkie clean; cargo safe",
            "lines netjies; ops strak","tune the cache; drop the kak","skrik vir niks; just ship",
            "keep it local; no kak","bru, green; laat dit gaan","lekker graphs; jol on",
            "skoon merge; stout bugs out","dop die logs; dance the deploy","bietsie latency; baie chill",
            "laaitie queues; oubaas uptime","groot jol; klein change","mooi man; klaar gestuur",
            "braai later; ship nou",
            # Context-aware additions
            "containers lekker; pods sharp","database tidy; queries quick","backup solid; restore ready",
            "network clean; traffic flowing","weekend lekker; systems rest","emergency sorted; no stress bru"
        ]
    }
}

# Enhanced templates with context awareness
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

# Enhanced context-aware template selection
def _get_smart_templates(persona: str, context_hints: Dict) -> List[str]:
    """Get templates based on context hints"""
    try:
        base_templates = _TEMPLATES.get(persona, _TEMPLATES["default"])
        
        # Add context-specific templates
        if context_hints.get("is_urgent"):
            urgent_templates = [
                "{subj}: urgent {a}; {b} now.",
                "{subj} — critical {a}; {b}!",
                "{subj}: immediate {a}; {b}."
            ]
            return base_templates + urgent_templates
        
        if context_hints.get("is_routine"):
            routine_templates = [
                "{subj}: routine {a}; {b} scheduled.",
                "{subj}: {a} per plan; {b}.",
                "{subj} — scheduled {a}; {b}."
            ]
            return base_templates + routine_templates
        
        if context_hints.get("is_completion"):
            completion_templates = [
                "{subj}: {a} complete; {b}.",
                "{subj}: mission {a}; result {b}.",
                "{subj} — {a} delivered; {b}."
            ]
            return base_templates + completion_templates
        
        return base_templates
    except:
        return _TEMPLATES.get("default", [])

def _expand_bank_with_context(persona: str, base_bank: List[str], context_hints: Dict) -> List[str]:
    """Expand vocabulary based on context hints"""
    try:
        expanded = base_bank.copy()
        
        # Add context-specific terms
        if context_hints.get("has_docker"):
            docker_terms = {
                "nerd": ["containerized", "orchestrated", "pods scaled"],
                "jarvis": ["containers aligned", "orchestration complete"],
                "action": ["containers deployed", "pods secured"],
                "dude": ["containers flowing", "pods chilling"]
            }
            expanded.extend(docker_terms.get(persona, []))
        
        if context_hints.get("has_database"):
            db_terms = {
                "nerd": ["ACID compliant", "transactions committed"],
                "jarvis": ["data integrity maintained", "queries optimized"],
                "action": ["database secured", "queries locked"],
                "dude": ["database cruising", "queries smooth"]
            }
            expanded.extend(db_terms.get(persona, []))
        
        if context_hints.get("has_backup"):
            backup_terms = {
                "nerd": ["checksummed", "integrity verified"],
                "jarvis": ["archived gracefully", "preservation complete"],
                "action": ["backup secured", "recovery verified"],
                "dude": ["backup surfed", "restore easy"]
            }
            expanded.extend(backup_terms.get(persona, []))
        
        # Weekend additions
        if context_hints.get("is_weekend"):
            weekend_terms = {
                "jarvis": ["weekend service", "off-hours protocol"],
                "dude": ["weekend vibes", "sunday cruise"],
                "rager": ["weekend duty", "saturday bullshit"]
            }
            expanded.extend(weekend_terms.get(persona, []))
        
        return list(set(expanded))  # Remove duplicates
    except:
        return base_bank

def _bank_for(persona: str, context_hints: Dict = None) -> List[str]:
    """Get vocabulary bank with context expansion (legacy for riffs)"""
    try:
        key = _PERSONA_BANK_KEY.get(persona, "ack")
        base_bank = _LEX.get(persona, {}).get(key, [])
        if not base_bank:
            base_bank = _LEX.get("ops", {}).get("ack", ["ok","noted"])
        
        if context_hints:
            return _expand_bank_with_context(persona, base_bank, context_hints)
        return base_bank
    except:
        return ["ok", "noted"]

def _templates_for(persona: str, context_hints: Dict = None) -> List[str]:
    """Get templates with context awareness"""
    try:
        if context_hints:
            return _get_smart_templates(persona, context_hints)
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

# --- Enhanced Lexi header quip (emoji allowed, no "Lexi." suffix) ---
def lexi_quip(persona_name: str, *, with_emoji: bool = True, subject: str = "", body: str = "") -> str:
    """Enhanced personality-rich header generation"""
    try:
        persona = _canon(persona_name)
        subj = strip_transport_tags((subject or "Update").strip().replace("\n"," "))[:120]
        
        # Get context hints for enhanced selection
        context_hints = _get_context_hints(subject, body)
        
        # Get personality-rich vocabulary from enhanced lexicon
        bank = _enhanced_bank_for(persona, subject, context_hints)
        
        # Get personality-specific templates
        templates = _PERSONALITY_TEMPLATES.get(persona, _PERSONALITY_TEMPLATES.get("ops", ["{subj}: {a}; {b}."]))
        
        # Choose template and phrases with personality weighting
        tmpl = random.choice(templates)
        
        # Weight selection toward personality-rich terms
        if len(bank) > 4:
            # Heavily favor first half (signature terms)
            signature_portion = bank[:len(bank)//2]
            full_bank = signature_portion * 3 + bank  # 3x weight to signature terms
        else:
            full_bank = bank
        
        a, b = _choose_personality_pair(full_bank)
        
        # Format and apply time-based flavor
        line = tmpl.format(subj=subj, a=a, b=b, time="{time}")
        line = _apply_daypart_flavor_inline(persona, line, context_hints)
        
        # Add emoji
        line = f"{line}{_maybe_emoji(persona, with_emoji)}"
        return line
    except Exception:
        # Graceful fallback
        return f"{subject or 'Update'}: ready; confirmed."

# --- Enhanced Lexi riffs (fallback; NO emoji) -------------------------------
def lexi_riffs(persona_name: str, n: int = 3, *, with_emoji: bool = False, subject: str = "", body: str = "") -> List[str]:
    """Enhanced lexi riffs with context awareness"""
    try:
        persona = _canon(persona_name)
        subj = strip_transport_tags((subject or "Update").strip().replace("\n"," "))[:120]
        body = strip_transport_tags((body or "").strip())
        
        context_hints = _get_context