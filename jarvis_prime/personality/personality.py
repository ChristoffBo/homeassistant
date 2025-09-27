#!/usr/bin/env python3
# /app/personality.py  — Complete working version with enhanced personality-rich headers
# Persona quip + Lexi engine for Jarvis Prime

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
            "is_urgent": any(word in text for word in ["critical", "down", "failed", "error", "urgent", "emergency"]),
            "is_routine": any(word in text for word in ["backup", "scheduled", "daily", "weekly", "routine", "maintenance"]),
            "is_completion": any(word in text for word in ["completed", "finished", "done", "success", "passed"]),
            "has_docker": any(word in text for word in ["docker", "container", "pod", "k8s", "kubernetes"]),
            "has_database": any(word in text for word in ["mysql", "postgres", "database", "db", "sql", "mongodb"]),
            "has_backup": any(word in text for word in ["backup", "restore", "snapshot", "archive"]),
            "has_network": any(word in text for word in ["network", "dns", "firewall", "proxy", "nginx"]),
            "is_weekend": time.localtime().tm_wday in [5, 6],
            "is_night": time.localtime().tm_hour < 6 or time.localtime().tm_hour > 22
        }
    except:
        return {"is_urgent": False, "is_routine": False, "is_completion": False, "has_docker": False, "has_database": False, "has_backup": False, "has_network": False, "is_weekend": False, "is_night": False}

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

def _canon(name: str) -> str:
    try:
        n = (name or "").strip().lower()
        key = ALIASES.get(n, n)
        return key if key in PERSONAS else "ops"
    except:
        return "ops"

# ----------------------------------------------------------------------------
# Enhanced personality-rich vocabulary for headers
# ----------------------------------------------------------------------------
ENHANCED_VOCAB = {
    "jarvis": {
        "primary": [
            "telemetry curated", "protocols aligned", "service immaculate", "housekeeping complete",
            "diagnostics elegant", "configuration poised", "settings domesticated", "notifications courteous",
            "alerts groomed", "logs polished", "cadence refined", "posture composed",
            "maintenance discreet", "orchestration tailored", "compliance effortless", "monitoring genteel",
            "graceful execution", "civilized deployment", "refined rollback", "courteous failover",
            "precision maintained", "etiquette preserved", "timing impeccable", "delivery seamless",
            "artifacts catalogued", "reports curated", "dashboards presentable", "metrics aligned",
            "uptime curated", "trace polished", "journals logged", "alerts domesticated"
        ],
        "completion": [
            "mission accomplished gracefully", "task executed flawlessly", "protocol completed immaculately",
            "service rendered elegantly", "configuration perfected quietly", "settings calibrated precisely",
            "handover elegant", "notes precise", "orchestration poised", "choreography exact"
        ]
    },
    "rager": {
        "primary": [
            "shit handled", "bullshit eliminated", "crap sorted", "nonsense crushed", "garbage cleared",
            "mess cleaned", "chaos tamed", "drama killed", "noise silenced", "clutter purged",
            "flakes destroyed", "junk removed", "trash deleted", "waste eliminated", "prick alert silenced"
        ],
        "completion": [
            "fucking done", "goddamn finished", "shit completed", "crap resolved", "mess sorted",
            "problem crushed", "issue destroyed", "bug murdered", "error eliminated"
        ]
    },
    "nerd": {
        "primary": [
            "algorithmically verified", "mathematically confirmed", "statistically validated", "empirically proven",
            "deterministically executed", "logically consistent", "formally verified", "computationally sound",
            "analytically confirmed", "systematically validated", "methodically proven", "rigorously tested",
            "checksums aligned", "assertions hold", "invariants preserved", "schema respected"
        ],
        "completion": [
            "theorem proved", "assertion validated", "hypothesis confirmed", "invariant maintained",
            "constraint satisfied", "predicate holds", "function converged", "algorithm terminated"
        ]
    },
    "dude": {
        "primary": [
            "totally handled", "completely chilled", "absolutely mellow", "thoroughly relaxed",
            "peacefully resolved", "calmly completed", "smoothly finished", "easily sorted",
            "effortlessly done", "naturally flowing", "gently settled", "quietly resolved",
            "vibes aligned", "karma balanced", "flow steady", "drama nil"
        ],
        "completion": [
            "ride complete", "wave surfed", "flow maintained", "vibe preserved", "chill achieved",
            "zen attained", "karma balanced", "harmony restored", "peace established"
        ]
    },
    "chick": {
        "primary": [
            "flawlessly executed", "perfectly styled", "elegantly completed", "beautifully finished",
            "gracefully handled", "stylishly resolved", "fashionably done", "gorgeously polished",
            "glamorously completed", "sophisticatedly finished", "charmingly resolved", "QA-clean",
            "runway-ready", "polish applied", "couture correct"
        ],
        "completion": [
            "look perfected", "style locked", "aesthetic achieved", "polish applied", "glam complete",
            "finish flawless", "presentation perfect", "appearance immaculate"
        ]
    },
    "action": {
        "primary": [
            "mission accomplished", "target neutralized", "objective secured", "operation complete",
            "threat eliminated", "area cleared", "perimeter secured", "position held",
            "extraction successful", "deployment clean", "execution precise", "strike effective",
            "targets green", "payload verified", "rollback vector armed"
        ],
        "completion": [
            "enemy down", "target destroyed", "threat neutralized", "mission success",
            "objective achieved", "area secured", "position taken", "victory confirmed"
        ]
    },
    "comedian": {
        "primary": [
            "remarkably unremarkable", "thrillingly boring", "spectacularly mundane", "dramatically dull",
            "hilariously ordinary", "comically normal", "absurdly routine", "ironically stable",
            "paradoxically predictable", "surprisingly unsurprising", "entertainingly bland",
            "peak normal", "laugh track muted", "sequels delayed"
        ],
        "completion": [
            "applause withheld", "encore cancelled", "standing ovation postponed", "curtain call skipped",
            "comedy complete", "joke delivered", "punchline landed", "audience satisfied"
        ]
    },
    "tappit": {
        "primary": [
            "lekker sorted", "sharp-sharp done", "properly handled", "netjies completed", "skoon finished",
            "tidy resolved", "clean executed", "neat accomplished", "sorted properly", "handled sharp",
            "howzit green", "all gees", "no kak", "pipeline smooth", "lekker clean"
        ],
        "completion": [
            "job lekker", "work sharp", "task netjies", "mission skoon", "duty sorted",
            "assignment tidy", "operation clean", "objective neat"
        ]
    },
    "ops": {
        "primary": ["acknowledged", "executed", "completed", "processed", "handled", "resolved", "finished"]
    }
}

PERSONALITY_TEMPLATES = {
    "jarvis": [
        "{subj}: {a}; {b}.",
        "{subj}: {a}. {b}, sir.",
        "{subj}: {a}; {b}. As you wish.",
        "{subj}: {a}; {b}. Service immaculate."
    ],
    "rager": [
        "{subj}: {a}. {b}.",
        "{subj}: fucking {a}; {b}.",
        "{subj}: {a}. {b}. Done."
    ],
    "nerd": [
        "{subj}: {a}; {b}.",
        "{subj}: formally {a}, empirically {b}.",
        "{subj}: {a}; {b}. QED."
    ],
    "comedian": [
        "{subj}: {a}. {b}. *crickets*",
        "{subj}: {a}; {b}. Try the veal."
    ],
    "action": [
        "{subj}: {a}. {b}.",
        "{subj}: {a}; {b}. Mission complete."
    ],
    "dude": [
        "{subj}: {a}. {b}, man.",
        "{subj}: totally {a}; {b}."
    ],
    "chick": [
        "{subj}: {a}. {b}, gorgeous.",
        "{subj}: {a}; {b}. Stunning."
    ],
    "tappit": [
        "{subj}: {a}. {b}, bru.",
        "{subj}: {a}; {b}. Lekker."
    ],
    "ops": [
        "{subj}: {a}; {b}."
    ]
}

def _get_enhanced_vocab(persona: str, context_hints: Dict) -> List[str]:
    """Get personality-rich vocabulary with context awareness"""
    vocab = ENHANCED_VOCAB.get(persona, {})
    
    # Start with primary personality terms
    terms = vocab.get("primary", []).copy()
    
    # Add completion terms if appropriate
    if context_hints.get("is_completion") and "completion" in vocab:
        terms.extend(vocab["completion"])
    
    # Fallback for missing personas
    if not terms:
        terms = ["ready", "confirmed", "completed", "processed"]
    
    return terms

def _choose_distinct_pair(vocab_list: List[str]) -> Tuple[str, str]:
    """Choose two distinct vocabulary terms"""
    if len(vocab_list) < 2:
        return (vocab_list[0] if vocab_list else "ready", "confirmed")
    
    a = random.choice(vocab_list)
    # Try to avoid similar words
    b_choices = [x for x in vocab_list if x != a and not any(word in x.lower() for word in a.lower().split())]
    if not b_choices:
        b_choices = [x for x in vocab_list if x != a]
    b = random.choice(b_choices) if b_choices else "confirmed"
    return a, b

# ----------------------------------------------------------------------------
# Enhanced header generation
# ----------------------------------------------------------------------------
def lexi_quip(persona_name: str, *, with_emoji: bool = True, subject: str = "", body: str = "") -> str:
    """Enhanced personality-rich header generation"""
    try:
        persona = _canon(persona_name)
        subj = strip_transport_tags((subject or "Update").strip().replace("\n"," "))[:120]
        
        # Get context hints
        context_hints = _get_context_hints(subject, body)
        
        # Get personality-rich vocabulary
        vocab = _get_enhanced_vocab(persona, context_hints)
        
        # Get templates
        templates = PERSONALITY_TEMPLATES.get(persona, ["{subj}: {a}; {b}."])
        tmpl = random.choice(templates)
        
        # Choose vocabulary pair
        a, b = _choose_distinct_pair(vocab)
        
        # Format line
        line = tmpl.format(subj=subj, a=a, b=b)
        
        # Add emoji
        return f"{line}{_maybe_emoji(persona, with_emoji)}"
        
    except Exception:
        # Safe fallback
        return f"{subject or 'Update'}: ready; confirmed{_maybe_emoji(_canon(persona_name), with_emoji)}"

# ----------------------------------------------------------------------------
# Legacy support and LLM integration
# ----------------------------------------------------------------------------
QUIPS = {
    "ops": ["ack.","done.","noted.","executed.","received.","stable.","running.","applied.","synced.","completed."],
    "jarvis": ["As always, sir, a great pleasure watching you work.", "Status synchronized, sir; elegance maintained."],
    "dude": ["The Dude abides; the logs can, like, chill.","Party on, pipelines. CI is totally non-bogus."],
    "chick":["That's hot—ship it with sparkle.","Zero-downtime? She's beauty, she's grace."],
    "nerd":["This is the optimal outcome. Bazinga.","Measured twice; compiled once."],
    "rager":["Say downtime again. I fucking dare you.","Push it now or I'll lose my goddamn mind."],
    "comedian":["Remarkably unremarkable—my favorite kind of uptime.","Doing nothing is hard; you never know when you're finished."],
    "action":["Consider it deployed.","System secure. Threat neutralized."],
    "tappit":["Howzit bru—green lights all round.","Lekker clean; keep it sharp-sharp."],
}

def quip(persona_name: str, *, with_emoji: bool = True) -> str:
    """Legacy canned quip function"""
    try:
        key = ALIASES.get((persona_name or "").strip().lower(), (persona_name or "").strip().lower()) or "ops"
        if key not in QUIPS:
            key = "ops"
        bank = QUIPS.get(key, QUIPS["ops"])
        line = random.choice(bank) if bank else ""
        return f"{line}{_maybe_emoji(key, with_emoji)}"
    except:
        return "ack."

# LLM integration functions
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
    """Generate LLM-powered personality riffs"""
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

def lexi_riffs(persona_name: str, n: int = 3, *, with_emoji: bool = False, subject: str = "", body: str = "") -> List[str]:
    """Generate Lexi-style riffs as fallback"""
    try:
        persona = _canon(persona_name)
        vocab = _get_enhanced_vocab(persona, _get_context_hints(subject, body))
        
        out = []
        for _ in range(n * 2):  # Oversample for variety
            a, b = _choose_distinct_pair(vocab)
            line = f"{a}; {b}"
            if line not in out:
                out.append(line)
            if len(out) >= n:
                break
        
        return out[:n]
    except:
        return ["ready", "confirmed", "done"][:n]

# ----------------------------------------------------------------------------
# Public API functions
# ----------------------------------------------------------------------------
def persona_header(persona_name: str, subject: str = "", body: str = "") -> str:
    """Generate enhanced personality-rich header (main function for top line)"""
    return lexi_quip(persona_name, with_emoji=True, subject=subject, body=body)

def build_header_and_riffs(persona_name: str, subject: str = "", body: str = "", max_riff_lines: int = 3) -> Tuple[str, List[str]]:
    """Build complete message: enhanced header + riffs"""
    try:
        header = persona_header(persona_name, subject=subject, body=body)
        
        # Try LLM for riffs first, fallback to Lexi
        context = strip_transport_tags(" ".join([subject or "", body or ""]).strip())
        lines = llm_quips(persona_name, context=context, max_lines=max_riff_lines)
        if not lines:
            lines = lexi_riffs(persona_name, n=max_riff_lines, with_emoji=False, subject=subject, body=body)
        
        # Strip emojis from riffs
        lines = [re.sub(r"[\U0001F300-\U0001FAFF]", "", line).strip() for line in lines]
        
        return header, lines
    except:
        return f"{subject or 'Update'}: ready; confirmed.", ["noted.", "done."]

# ----------------------------------------------------------------------------
# Test/example usage
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    print("Enhanced Personality Headers Test:")
    print("=" * 50)
    
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
    
    for persona, subject, body in test_cases:
        header = persona_header(persona, subject=subject, body=body)
        print(f"{persona.upper()}: {header}")
    
    print("\nComparison:")
    print("OLD: Update: fast-forwarded; reconciled. ✅")
    print("NEW:", persona_header("jarvis", "Sonarr - Test Notification", "Email settings configured"))