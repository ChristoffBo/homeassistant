#!/usr/bin/env python3
# /app/personality.py  — Enhanced with safe context awareness
# Persona quip + Lexi engine for Jarvis Prime
#
# Public API (unchanged entry points):
#   - quip(persona_name: str, *, with_emoji: bool = True) -> str
#   - llm_quips(persona_name: str, *, context: str = "", max_lines: int = 3) -> list[str]
#   - lexi_quip(persona_name: str, *, with_emoji: bool = True, subject: str = "", body: str = "") -> str
#   - lexi_riffs(persona_name: str, n: int = 3, *, with_emoji: bool = False, subject: str = "", body: str = "") -> list[str]
#   - persona_header(persona_name: str, subject: str = "", body: str = "") -> str

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
# Safe context analysis
# ----------------------------------------------------------------------------
def _get_safe_context(subject: str = "", body: str = "") -> Dict[str, any]:
    """Safe context extraction that won't break"""
    try:
        # Time context
        t = time.localtime()
        h = t.tm_hour
        weekday = t.tm_wday
        
        if 0 <= h < 6:
            daypart = "night"
        elif 6 <= h < 12:
            daypart = "morning"
        elif 12 <= h < 18:
            daypart = "afternoon"
        else:
            daypart = "evening"
        
        # Simple message analysis
        text = f"{subject} {body}".lower()
        
        # Basic pattern detection
        is_urgent = any(word in text for word in ["critical", "down", "failed", "error", "urgent"])
        is_routine = any(word in text for word in ["backup", "scheduled", "daily", "weekly", "routine"])
        is_completion = any(word in text for word in ["completed", "finished", "done", "success"])
        is_weekend = weekday in [5, 6]
        
        # System type hints
        has_docker = any(word in text for word in ["docker", "container", "pod"])
        has_database = any(word in text for word in ["mysql", "postgres", "database", "db"])
        has_backup = any(word in text for word in ["backup", "restore", "snapshot"])
        
        return {
            "daypart": daypart,
            "is_weekend": is_weekend,
            "is_urgent": is_urgent,
            "is_routine": is_routine,
            "is_completion": is_completion,
            "has_docker": has_docker,
            "has_database": has_database,
            "has_backup": has_backup,
            "hour": h
        }
    except:
        # Safe fallback
        return {
            "daypart": "afternoon",
            "is_weekend": False,
            "is_urgent": False,
            "is_routine": False,
            "is_completion": False,
            "has_docker": False,
            "has_database": False,
            "has_backup": False,
            "hour": 12
        }

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

def _apply_contextual_flavor(persona: str, text: str, context: Dict) -> str:
    """Apply context-aware flavor safely"""
    try:
        # Time-based replacements
        if "{time}" in text:
            if context["daypart"] == "night":
                time_flavors = {
                    "jarvis": "night watch",
                    "rager": "graveyard shift",
                    "dude": "midnight session",
                    "action": "night ops",
                    "nerd": "after-hours processing"
                }
            elif context["is_weekend"]:
                time_flavors = {
                    "jarvis": "weekend service",
                    "rager": "weekend duty", 
                    "dude": "weekend cruise",
                    "action": "off-duty watch",
                    "nerd": "batch processing"
                }
            else:
                time_flavors = {
                    "jarvis": f"{context['daypart']} protocols",
                    "rager": f"{context['daypart']} chaos",
                    "dude": f"{context['daypart']} flow",
                    "action": f"{context['daypart']} ops",
                    "nerd": f"{context['daypart']} cycles"
                }
            
            flavor = time_flavors.get(persona, context['daypart'])
            text = text.replace("{time}", flavor)
        
        return text
    except:
        return text.replace("{time}", "")

# ----------------------------------------------------------------------------
# Enhanced Lexicons (expanded but safe)
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

_LEX: Dict[str, Dict[str, List[str]]] = {
    "ops": {
        "ack": [
            "ack","done","noted","executed","received","stable","running","applied","synced","completed",
            "success","confirmed","ready","scheduled","queued","accepted","active","closed","green","healthy",
            "rolled back","rolled forward","muted","paged","silenced","deferred","escalated","contained","optimized",
            "ratelimited","rotated","restarted","reloaded","validated","archived","reconciled","cleared","holding"
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
            "deployment choreographed; staging flawless","incident contained; recovery elegant","maintenance scheduled; downtime minimal",
            "monitoring calibrated; alerting refined","weekend duty fulfilled; service uninterrupted","night watch commenced; vigilance heightened"
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
            "container orchestration stable; pods healthy","database consistency verified; ACID preserved","backup verified; integrity confirmed",
            "monitoring pipeline functional; data flowing","deployment pipeline green; tests passing","weekend batch completed; processing verified"
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
            "deployment executed; beachhead established","incident contained; damage controlled","maintenance completed; systems hardened",
            "monitoring active; threats tracked","night shift ready; watch posted","weekend guard maintained; perimeter intact"
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
            "deployment surfed; no wipeouts","incident handled; still zen","maintenance cruised; minimal waves",
            "monitoring chilled; alerts rare","weekend mode; systems coast","midnight session; quiet flows"
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
            "deployment styled; launch flawless","incident managed; composure intact","maintenance polished; downtime minimal",
            "monitoring refined; alerts tasteful","weekend refresh; Monday prep","night mode; systems sleek"
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
            "deployment unfucked; ship it","incident crushed; stop panicking","maintenance forced; deal with it",
            "monitoring silenced; quit whining","weekend shit handled; back to life","graveyard garbage cleared; sleep now"
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
            "deployment: the musical; reviews mixed","incident: horror movie; happy ending","maintenance: documentary; critically acclaimed",
            "monitoring: reality TV; surprisingly dull","weekend rerun; still not funny","late night comedy; systems sleep"
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
            "deployment lekker; shipped clean","incident sorted; no more kak","maintenance sharp; downtime brief",
            "monitoring tidy; alerts quiet","weekend lekker; systems rest","late night bakkie; quiet cruise"
        ]
    }
}

# ----------------------------------------------------------------------------
# Context-aware template selection
# ----------------------------------------------------------------------------
def _get_smart_templates(persona: str, context: Dict) -> List[str]:
    """Get templates based on context"""
    base_templates = [
        "{subj}: {a}. {b}.",
        "{subj} — {a}; {b}.",
        "{subj}: {a}; {b}.",
        "{subj}: {a} and {b}."
    ]
    
    try:
        # Add context-specific templates
        if context.get("is_urgent"):
            urgent_templates = [
                "{subj}: urgent {a}; {b} now.",
                "{subj} — critical {a}; {b}.",
                "{subj}: {a} immediately; {b}."
            ]
            base_templates.extend(urgent_templates)
        
        if context.get("is_routine"):
            routine_templates = [
                "{subj}: routine {a}; {b} as scheduled.",
                "{subj}: {a} per plan; {b}.",
                "{subj} — scheduled {a}; {b}."
            ]
            base_templates.extend(routine_templates)
        
        if context.get("is_completion"):
            completion_templates = [
                "{subj}: {a} complete; {b}.",
                "{subj}: mission {a}; result {b}.",
                "{subj} — {a} delivered; {b}."
            ]
            base_templates.extend(completion_templates)
        
        return base_templates
    except:
        return base_templates

def _expand_bank_with_context(persona: str, base_bank: List[str], context: Dict) -> List[str]:
    """Safely expand vocabulary based on context"""
    try:
        expanded = base_bank.copy()
        
        # Add context-specific terms
        if context.get("has_docker"):
            docker_terms = {
                "nerd": ["containerized", "orchestrated", "pods scaled"],
                "jarvis": ["containers aligned", "orchestration complete"],
                "action": ["containers deployed", "pods secured"]
            }
            expanded.extend(docker_terms.get(persona, []))
        
        if context.get("has_database"):
            db_terms = {
                "nerd": ["ACID compliant", "transactions committed"],
                "jarvis": ["data integrity maintained", "queries optimized"],
                "dude": ["data flowing", "queries smooth"]
            }
            expanded.extend(db_terms.get(persona, []))
        
        if context.get("has_backup"):
            backup_terms = {
                "nerd": ["checksummed", "integrity verified"],
                "jarvis": ["archived gracefully", "preservation complete"],
                "action": ["backup secured", "recovery verified"]
            }
            expanded.extend(backup_terms.get(persona, []))
        
        return list(set(expanded))  # Remove duplicates
    except:
        return base_bank

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

def _canon(name: str) -> str:
    try:
        n = (name or "").strip().lower()
        key = ALIASES.get(n, n)
        return key if key in PERSONAS else "ops"
    except:
        return "ops"

def _bank_for(persona: str, context: Dict) -> List[str]:
    """Get vocabulary bank with context expansion"""
    try:
        key = _PERSONA_BANK_KEY.get(persona, "ack")
        base_bank = _LEX.get(persona, {}).get(key, [])
        if not base_bank:
            base_bank = _LEX.get("ops", {}).get("ack", ["ok","noted"])
        
        return _expand_bank_with_context(persona, base_bank, context)
    except:
        return ["ok", "noted"]

# ----------------------------------------------------------------------------
# Public API functions (enhanced but safe)
# ----------------------------------------------------------------------------
def lexi_quip(persona_name: str, *, with_emoji: bool = True, subject: str = "", body: str = "") -> str:
    """Enhanced lexi quip with safe context awareness"""
    try:
        persona = _canon(persona_name)
        subj = strip_transport_tags((subject or "Update").strip().replace("\n"," "))[:120]
        
        # Get context safely
        context = _get_safe_context(subject, body)
        
        # Get contextual vocabulary and templates
        bank = _bank_for(persona, context)
        templates = _get_smart_templates(persona, context)
        
        # Choose template and phrases
        tmpl = random.choice(templates)
        a, b = _choose_two(bank)
        
        # Format and apply context
        line = tmpl.format(subj=subj, a=a, b=b)
        line = _apply_contextual_flavor(persona, line, context)
        
        # Add emoji
        line = f"{line}{_maybe_emoji(persona, with_emoji)}"
        return line
    except Exception as e:
        # Safe fallback
        return f"{subject or 'Update'}: ok. noted."

def lexi_riffs(persona_name: str, n: int = 3, *, with_emoji: bool = False, subject: str = "", body: str = "") -> List[str]:
    """Enhanced lexi riffs with safe context awareness"""
    try:
        persona = _canon(persona_name)
        subj = strip_transport_tags((subject or "Update").strip().replace("\n"," "))[:120]
        
        context = _get_safe_context(subject, body)
        templates = _get_smart_templates(persona, context)
        bank = _bank_for(persona, context)
        
        out: List[str] = []
        
        for _ in range(max(6, n*3)):  # oversample for uniqueness
            tmpl = random.choice(templates)
            a, b = _choose_two(bank)
            
            base = tmpl.format(subj=subj, a=a, b=b)
            line = _apply_contextual_flavor(persona, base, context)
            
            # Remove emojis for riffs
            line = re.sub(r"[\U0001F300-\U0001FAFF]", "", line).strip()
            
            if len(line) > 140:
                line = line[:140].rstrip()
            
            if line not in out:
                out.append(line)
            
            if len(out) >= n:
                break
        
        return out
    except:
        # Safe fallback
        return [f"{subject or 'Update'}: ok.", "noted.", "done."][:n]

def persona_header(persona_name: str, subject: str = "", body: str = "") -> str:
    """Generate safe context-aware persona header"""
    return lexi_quip(persona_name, with_emoji=True, subject=subject, body=body)

def quip(persona_name: str, *, with_emoji: bool = True) -> str:
    """Legacy canned quip function with time awareness"""
    try:
        key = ALIASES.get((persona_name or "").strip().lower(), (persona_name or "").strip().lower()) or "ops"
        if key not in QUIPS:
            key = "ops"
        bank = QUIPS.get(key, QUIPS["ops"])
        line = random.choice(bank) if bank else ""
        if _intensity() > 1.25 and line and line[-1] in ".!?":
            line = line[:-1] + random.choice([".", "!", "!!"])
        
        # Add simple time awareness
        context = _get_safe_context()
        line = _apply_contextual_flavor(key, line + " {time}", context).replace(" {time}", "")
        
        return f"{line}{_maybe_emoji(key, with_emoji)}"
    except:
        return "ack."

# ----------------------------------------------------------------------------
# LLM integration (unchanged but with enhanced context)
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
    """LLM-generated quips with enhanced context"""
    if os.getenv("BEAUTIFY_LLM_ENABLED", "true").lower() not in ("1","true","yes"):
        return []
    
    try:
        key = _canon(persona_name)
        context = strip_transport_tags((context or "").strip())
        if not context:
            return []
        
        allow_prof = (key == "rager") or (os.getenv("PERSONALITY_ALLOW_PROFANITY", "false").lower() in ("1","true","yes"))
        
        llm = importlib.import_module("llm_client")
        
        # Enhanced persona descriptions with context
        ctx = _get_safe_context("", context)
        
        persona_tone = {
            "dude": f"Laid-back slacker-zen; mellow, cheerful, kind. {ctx['daypart']} vibes. Keep it short, breezy, and confident.",
            "chick": f"Glamorous couture sass; bubbly but razor-sharp. {ctx['daypart']} energy. Supportive, witty, stylish, high standards.",
            "nerd": f"Precise, pedantic, dry wit; obsessed with correctness. {ctx['daypart']} processing mode. Determinism, graphs, and tests.",
            "rager": f"Intense, profane, street-tough cadence. {ctx['daypart']} intensity. Blunt, kinetic, zero patience for nonsense.",
            "comedian": f"Deadpan spoof meets irreverent meta. {ctx['daypart']} deadpan. Fourth-wall pokes, concise and witty.",
            "action": f"Terse macho one-liners; tactical, sardonic. {ctx['daypart']} ops tempo. Mission-focused and decisive.",
            "jarvis": f"Polished valet AI with calm, clinical machine logic. {ctx