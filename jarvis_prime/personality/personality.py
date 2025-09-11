#!/usr/bin/env python3
# /app/personality.py
# Persona quip engine for Jarvis Prime
#
# Public API:
#   - quip(persona_name: str, *, with_emoji: bool = True) -> str
#   - llm_quips(persona_name: str, *, context: str = "", max_lines: int = 3) -> list[str]
#
# Persona inspirations (documentation only; NOT injected into prompts to avoid parroting):
#   dude      → Slacker-zen + cheerful “be excellent” vibe (The Dude + Bill & Ted energy; laid-back, mellow confidence)
#   chick     → Glam couture sass + bubbly-but-brilliant optimism (Paris-style glam + Elle-style brains; smart, stylish, supportive)
#   nerd      → Pedantic precision + awkward IT savant (dry wit, correctness, graphs; a dash of manic science)
#   rager     → Raw street rage (Samuel-L-style venom + Pesci-style volatility). Profanity ALWAYS allowed.
#   comedian  → Deadpan spoof + irreverent fourth-wall meta sarcasm (Nielsen-straight face + meta snark)
#   action    → Macho action-hero archetype (terse, tactical, explosive, sardonic; no quotes)
#   jarvis    → Polished AI valet blended with calm, clinical machine logic (subtle HAL-like edge)
#   ops       → Neutral SRE/ops acks (laconic operational confirmations)
#
# NOTE: We avoid actor/brand names inside prompts to prevent quote parroting.
#       Style is driven by descriptors only. Rager is always uncensored.
#       Daypart + intensity add non-breaking flavor.
#
# Env knobs (optional):
#   - PERSONALITY_INTENSITY: float 0.6–2.0, default 1.0
#   - LLM_TIMEOUT_SECONDS: int, default 8
#   - LLM_MAX_CPU_PERCENT: int, default 70
#   - LLM_PERSONA_LINES_MAX: int, default 3
#   - LLM_MODELS_PRIORITY, LLM_OLLAMA_BASE_URL / OLLAMA_BASE_URL, LLM_MODEL_URL, LLM_MODEL_PATH
import personality_tappit
import random, os, importlib, re, time
from typing import List, Dict, Optional
...
# ---- LLM plumbing ----
_PROF_RE = re.compile(r"(?i)\b(fuck|shit|damn|asshole|bitch|bastard|dick|pussy|cunt)\b")

def _soft_censor(s: str) -> str:
    return _PROF_RE.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), s)

def _post_clean(lines: List[str], persona_key: str, allow_prof: bool) -> List[str]:
    if not lines:
        return []
    out: List[str] = []
    BAD = (
        "persona", "rules", "rule:", "instruction", "instruct", "guideline",
        "system prompt", "style hint", "lines:", "respond with", "produce only",
        "you are", "jarvis prime", "[system]", "[input]", "[output]",
        "tone:", "context:"  # ADDITIVE: strip prompt scaffolding leaks
    )
    seen = set()
    for ln in lines:
        t = ln.strip()
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

# ---- Public API: LLM riffs ----
def llm_quips(persona_name: str, *, context: str = "", max_lines: int = 3) -> List[str]:
    if os.getenv("BEAUTIFY_LLM_ENABLED", "true").lower() not in ("1","true","yes"):
        return []
    key = _canon(persona_name)
    context = (context or "").strip()
    if not context:
        return []
    # Always allow profanity for rager; others honor env flag
    allow_prof = (key == "rager") or (os.getenv("PERSONALITY_ALLOW_PROFANITY", "false").lower() in ("1","true","yes"))
    try:
        llm = importlib.import_module("llm_client")
    except Exception:
        return []
    # Strong style descriptors (NO proper names to avoid parroting)
    persona_tone = {
        "dude": "Laid-back slacker-zen; mellow, cheerful, kind. Keep it short, breezy, and confident.",
        "chick": "Glamorous couture sass; bubbly but razor-sharp. Supportive, witty, stylish, high standards.",
        "nerd": "Precise, pedantic, dry wit; obsessed with correctness, determinism, graphs, and tests.",
        "rager": "Intense, profane, street-tough cadence. Blunt, kinetic, zero patience for bullshit.",
        "comedian": "Deadpan spoof meets irreverent meta—fourth-wall pokes, concise and witty.",
        "action": "Terse macho one-liners; tactical, explosive, sardonic; mission-focused and decisive.",
        "jarvis": "Polished valet AI with calm, clinical machine logic. Courteous, anticipatory, slightly eerie.",
        "ops": "Neutral SRE acks; laconic, minimal flourish.",
        "tappit": "South African tappit slang persona — brash, rev-heavy, lekker, car-culture street banter. Always slangy, never polished."
    }.get(key, "Short, clean, persona-true one-liners.")
    style_hint = f"daypart={_daypart()}, intensity={_intensity():.2f}, persona={key}"
    # 1) persona_riff path (context is raw; no bracketed blobs)
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
    # 2) Fallback to rewrite()
    if hasattr(llm, "rewrite"):
        try:
            sys_prompt = (
                "YOU ARE A PITHY ONE-LINER ENGINE.\n"
                f"Persona: {key}.\n"
                f"Tone: {persona_tone}\n"
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

# === ADDITIVE: Persona Lexicon + Template Riff Engine ========================
# Drop this block at the END of /app/personality.py (no removals above)

import re as _re

# --- Global tokens shared across all personas (infra/devops vocabulary) -----
_LEX_GLOBAL = {
    "thing": [
        "server","service","cluster","pod","container","queue","cache","API",
        "gateway","cron","daemon","DB","replica","ingress","pipeline","runner",
        "topic","index","load balancer","webhook","agent"
    ],
    "issue": [
        "heisenbug","retry storm","config drift","cache miss","race condition",
        "flaky test","null pointer fiesta","timeouts","slow query","thundering herd",
        "cold start","split brain","event loop block","leaky abstraction"
    ],
    "metric": [
        "p99 latency","error rate","throughput","uptime","CPU","memory",
        "I/O wait","queue depth","alloc rate","GC pauses","TLS handshakes"
    ],
    "verb": [
        "ship","rollback","scale","patch","restart","deploy","throttle","pin",
        "sanitize","audit","refactor","migrate","reindex","hydrate","cordon",
        "failover","drain","tune","harden","observe"
    ],
    "adj_good": [
        "boring","green","quiet","stable","silky","clean","predictable",
        "snappy","solid","serene","low-drama","handsome"
    ],
    "adj_bad": [
        "noisy","brittle","flaky","spicy","haunted","messy","fragile",
        "rowdy","chaotic","gremlin-ridden","soggy","crusty"
    ],
}

# --- Persona-specific lexicons -----------------------------------------------
_LEX = {
    "dude": {
        # 120 LEXI total for 'dude' persona (filler + zen + metaphor)
        "filler": [
            "man","dude","bro","friend","pal","buddy","amigo","homie","compadre","chief",
            "captain","partner","mate","bruv","brother","ace","champ","legend","boss","my guy",
            "cool cat","surfer","roller","chiller","big dog","fam","soul","sunshine","cowpoke","space cowboy",
            "beach bum","bowler","wave rider","pal o’ mine","good sir","cosmic pal","gentle soul","peacemaker","mellow human","righteous mate",
            "soft operator","laid-back unit","vibe pilot","groove navigator","calm operator","easy rider","backlog surfer","pipeline pal","prod whisperer","queue cruiser",
            "flow friend","zen traveler","karma carrier","smooth sailor","lane buddy","good egg","friendly ghost","gentle bro","soft breeze","cool breeze",
            "steady hand","quiet storm","peace partner","mellow mate","vibe buddy","kind spirit","soft soul","good traveler","calm wave","gentle wave",
            "lane walker","groove friend","easy pal","relaxed unit","cool human","steady friend","vibe friend","bowling buddy","pipeline buddy","cloud cruiser"
        ],
        "zen": [
            "abide","chill","vibe","float","breathe","mellow out","take it easy","flow","let go","glide",
            "roll with it","keep it simple","stay loose","be water","soft-land","ride the wave","drift","exhale","stay mellow","hands off",
            "unclench","relax the grip","ease back","coast","slow your roll","stay kind","trust the tide","keep it gentle","let it settle","ride it out",
            "tune out noise","hum along","keep calm","respect the tempo","loosen the stance","sip the moment","stay breezy","go soft","light touch","keep the vibes",
            "mind the breath","take the scenic route","don’t rush","let queues breathe","be stateless","hug the happy path","keep posture open","embrace patience","float the backlog","nap on it",
            "abide the SLO","let alerts simmer","surf the p99","listen twice","smile at latency","befriend retries","accept eventual consistency","honor error budgets","choose kindness","keep steady"
        ],
        "metaphor": [
            "wave","lane","groove","bowl","flow","vibe field","lazy river","trade wind","ocean swell","rolling cloud",
            "campfire glow","sunset stripe","vinyl hiss","backroad drift","longboard line","soft shoulder","warm current","starlight lane","midnight highway","quiet tide",
            "feather fall","couch cushion","beanbag sag","hammock sway","pool noodle","cloud couch","pillow fort","tea steam","yoga mat","incense trail",
            "bowling lane","alley glow","neon hush","linen breeze","sandbar path","boardwalk loop","tumbleweed roll","summer nap","half-pipe line","seashell hum",
            "low-tide shuffle","amber hour","cotton sky","easy chair","porch swing","late bus ride","open mic hum","lo-fi loop","vinyl groove","soft rain"
        ]
    },
    "chick": {
        # (cut here — continues with couture + judge banks)
    },
    # (nerd, rager, comedian, action, jarvis, ops, tappit continue below)
}

"chick": {
        # 120 LEXI total for 'chick' persona (glam + couture + judge)
        "glam": [
            "slay","serve","sparkle","shine","glisten","elevate","polish","glow","dazzle","bedazzle",
            "stun","sizzle","pop","enchant","radiate","smolder","shimmer","captivate","allure","finesse",
            "refine","flourish","glam up","glitter","embellish","illuminate","preen","prime","snatch","sleekify",
            "uplift","streamline","accent","curate","style","amp","spruce","sheen","buff","burnish",
            "pipette gloss","powder","detail","finish","frame","tidy","tailor","sculpt","contour","highlight",
            "edge","define","lacquer","varnish","gild","pearlize","soften","sweeten","kiss with gloss","smooth",
            "freshen","refresh","revive","perk up","sweeten the look","charm","delight","luxify","razzle","rarefy",
            "glamorize","prettify","beautify","tighten","tone","pamper","groom","prime-time","refurb","refit",
            "resheen","resparkle","repolish","replate","reprime","reframe","restyle","redefine","recast","recurve",
            "declutter","stream","slick","sleek","silken","sateen","sheath","satinate","bejewel","bevel",
            "luster","lustre-up","kiss of luxe","kiss of light","velvetize","feather","featherlight","float","puff","plump",
            "airbrush","powder-coat","mirror-finish","diamond-cut","swan-up","glassify","glacé","pearlesce","opalesce","halo"
        ],
        "couture": [
            "velvet rope","runway","couture","lip gloss","heels","silk","satin","tulle","organza","chiffon",
            "sequin line","atelier","bespoke cut","capsule edit","catwalk","editorial edge","statement cuff","pearl clasp","diamond line","silhouette",
            "tailored seam","bias cut","box pleat","A-line","train","corsetry","boning","couture stitch","lining","hem bar",
            "double-breasted vibe","herringbone feel","pinstripe mood","cashmere touch","merino layer","mohair haze","shearling trim","faux fur","lantern sleeve","bishop sleeve",
            "puff sleeve","off-shoulder","halter","boat neck","sweetheart line","princess seam","empire waist","pencil skirt","tea-length","maxi sweep",
            "mini moment","trench flair","capelet","bolero","blazer sharp","waist cinch","gold hardware","gunmetal zip","tone-on-tone","color block",
            "monochrome set","two-piece power","co-ord set","fit-and-flare","glove fit","glass heel","kitten heel","stiletto stance","platform lift","block heel",
            "mary jane clip","ankle strap","slingback","pointed toe","almond toe","square toe","box bag","clutch","micro bag","top-handle",
            "chain strap","quilted panel","matelassé","mock croc","saffiano","soft napa","patent shine","sheen leather","buttery leather","metallic foil",
            "satchel line","hobo curve","bucket body","envelope flap","foldover","kiss-lock","toggle clasp","magnet snap","silk scarf","twilly",
            "brooch moment","crystal trim","rhinestone spray","jeweled buckle","ballet core","old money vibe","quiet luxury","editor pick","front row","after-party pass"
        ],
        "judge": [
            "approved","iconic","camera-ready","main-character","on brand","crisp","editorial","elevated","effortless","immaculate",
            "intentioned","tasteful","flawless","refined","glamorous","sleek","polished","strategic","collected","considered",
            "clean lines","sharp take","decisive","classy","timeless","fresh","modern","pulled-together","runway-worthy","couture-level",
            "production-ready","release-worthy","SLA-chic","QA-clean","postmortem-proof","launchable","greenlighted","VIP-only","red-carpet","backstage-pass",
            "bottle-service","velvet-approved","gilded","pearled","diamond-clear","photo-ready","page-me-only","whitelist-only","gatekept","curated",
            "tight","snatched","cinched","tailored","pressed","starch-level","creased-right","aligned","symmetrical","seasonal",
            "in-season","on-message","no-notes","luxe","deluxe","premium","platinum-tier","gold standard","A-list","first-class",
            "five-nines energy","plumb","square","level","flush","true","mint","pristine","spotless","uncompromising",
            "high-contrast","low-drama","hushed","minimal","maximal where it counts","photogenic","board-ready","sponsor-safe","press-ready","production-posh",
            "badge-worthy","credentialed","royalty-level","private list","invite-only","backed-by-graphs","metrics-honest","latency-lithe","budget-gentle","pager-kind",
            "irresistible","kept","kept-tight","kept-clean","kept-classy","kept-secure","non-negotiable","beyond reproach","above board","picture-perfect"
        ]
    },
    "nerd": {
        # (math + open + nerdverb banks continue)
    },
    "rager": {
        # (curse + insult + command + anger banks continue)
    },
    "comedian": {
        # (meta + dry + aside banks continue)
    },
    "action": {
        # (ops + bark + grit banks continue)
    },
    "jarvis": {
        # (valet + polish + guard banks continue)
    },
    "ops": {
        # (ack bank continues)
    }
}

"nerd": {
        # 120 LEXI total for 'nerd' persona (open + math + nerdverb)
        "open": [
            "Actually,","In fact,","Formally,","Technically,","By definition,","According to RFC,","Empirically,","Provably,","Objectively,","Statistically,",
            "Verified,","Demonstrably,","Logically,","Mathematically,","Precisely,","Explicitly,","Quantitatively,","Formulated,","Algorithmically,","Conventionally,",
            "Canonical truth:","From first principles,","Structurally,","Analytically,","Empirically speaking,","Benchmark says,","Hypothetically,","Deterministically,","Strictly speaking,","Invariance holds,",
            "Formal proof shows,","By theorem,","Asymptotically,","Recursively,","Declaratively,","Orthogonally,","From context,","Through induction,","By lemma,","Corollary: ",
            "Statistically speaking,","As expected,","Rigourously,","Formulated thus,","Defined as,","Constructively,","Optimally,","Experimentally,","Empirically verified,","Repeatably,",
            "By spec,","Verified result,","Quantifiable,","Objectively correct,","Undoubtedly,","Asserted,","Checked,","Cross-validated,","Formally proven,","Non-negotiably,",
            "Mathematically speaking,","By induction,","Algorithm says,","Graph shows,","Plot confirms,","Unit test affirms,","Lint warns,","Model asserts,","Invariant holds,","Boundary proven,",
            "Logical necessity,","Predictably,","Reliably,","Testable,","Verified fact,","Confidence interval says,","Statistically robust,","Bayesianly,","Empirical evidence shows,","Formal model says,",
            "As documented,","As logged,","As graphed,","As stored,","As enumerated,","As indexed,","As constrained,","As scheduled,","As provisioned,","As expected by type,",
            "By contract,","By schema,","By interface,","By assertion,","By precondition,","By postcondition,","Checked invariant,","Maintained condition,","Guard holds,","Requirement satisfied,",
            "Mathematically trivial,","Proof complete,","Therefore,","Q.E.D.,","Done,","Halt state,","Deterministically reproducible,","Re-entrant,","Side-effect free,","Purely functional,"
        ],
        "math": [
            "O(1)","idempotent","deterministic","bounded","strictly monotonic","total","injective","surjective","bijective","associative",
            "commutative","distributive","normalized","canonical","orthogonal","linear","nonlinear","stochastic","probabilistic","deterministic again",
            "chaotic","ergodic","finite","infinite","polynomial","exponential","logarithmic","NP-hard","tractable","decidable",
            "undecidable","complete","sound","consistent","inconsistent","axiomatic","empirical","statistical","variance-bounded","mean-stable",
            "covariant","contravariant","monotone","antitone","monoidal","functorial","categorical","recursive","iterative","tail-recursive",
            "lazy","eager","evaluated","memoized","combinatorial","algebraic","geometric","topological","analytic","synthetic",
            "differentiable","integrable","convergent","divergent","bounded below","bounded above","unbounded","partial","total again","closure",
            "fixed point","limit","supremum","infimum","minimum","maximum","argmin","argmax","null space","rank",
            "kernel","image","dimension","basis","orthonormal","projection","eigenvalue","eigenvector","spectral","diagonalizable",
            "invertible","noninvertible","unitary","hermitian","positive definite","semidefinite","nonsingular","singular","stable equilibrium","unstable equilibrium",
            "chaotic attractor","strange attractor","Markov","Bayesian","Gaussian","Poisson","binomial","multinomial","Bernoulli","hypergeometric",
            "chi-square","t-distribution","F-distribution","uniform distribution","random variable","expectation","variance","covariance","correlation","entropy"
        ],
        "nerdverb": [
            "instrument","prove","lint","benchmark","formalize","graph","compile","profile","measure","quantify",
            "optimize","refactor","document","annotate","tokenize","parse","serialize","deserialize","marshal","unmarshal",
            "normalize","denormalize","index","reindex","search","hash","rehash","encrypt","decrypt","sign",
            "verify","audit","log","trace","sample","aggregate","filter","map","reduce","fold",
            "unfold","iterate","recursively call","memoize","cache","invalidate","checkpoint","restore","serialize again","clone",
            "fork","join","spawn","kill","schedule","reschedule","prioritize","deprioritize","paginate","debounce",
            "throttle","batch","stream","pipe","redirect","mux","demux","multiplex","demultiplex","bind",
            "unbind","subscribe","unsubscribe","publish","notify","alert","escalate","acknowledge","retry","requeue",
            "reroute","patch","upgrade","downgrade","migrate","rollback","rollforward","simulate","emulate","virtualize",
            "containerize","orchestrate","provision","deprovision","spin up","spin down","scale up","scale down","autoscale","balance",
            "debounce again","deduplicate","compress","decompress","encode","decode","escape","unescape","sanitize","desanitize"
        ]
    },

"rager": {
        # 120 LEXI total for 'rager' persona (curse + insult + command + anger)
        "curse": [
            "fuck","shit","damn","hell","cunt","piss","bollocks","bastard","wanker","dick",
            "cock","twat","prick","arse","arsehole","motherfucker","bullshit","crap","bloody","goddamn",
            "fucking","shitty","shite","douche","douchebag","jackshit","screw it","fubar","clusterfuck","shitshow",
            "fubarred","godforsaken","hellbound","damnation","hellfire","shitpile","fuckup","balls","shithead","shitbird",
            "shitbag","shitfaced","ass","asshat","asswipe","assclown","dipshit","dumbass","jackoff","cockup",
            "shitstorm","screwup","trainwreck","dumpster fire","hellhole","toxic mess","fuckery","shithole","arsewipe","arseclown",
            "bloody hell","fuck-all","worthless crap","shoddy shit","garbage-tier","third-rate","half-assed","quarter-assed","godawful","terrible shit",
            "piss-poor","pissweak","weak-ass","shit-eating","fucked","fucking mess","total mess","utter shit","all fucked","goddamn mess",
            "motherloving","freaking","fricking","effing","crappy","lousy","junk","garbage","trash","dogshit",
            "horseshit","goatshit","bullcrap","cowshit","pigshit","monkeyshit","turkeyshit","donkeyshit","pile of shit","piece of shit",
            "POS","BS","utter BS","damn BS","full of shit","talking shit","cheap shit","fake shit","plastic crap","tinpot",
            "dog’s breakfast","pigsty","shit-eater","garbage fire","filthy crap","dirty shit","disgusting crap","gross shit","revolting mess","toxic dump"
        ],
        "insult": [
            "clown","jackass","cowboy","tourist","gremlin","rookie","noob","loser","poser","wannabe",
            "buffoon","bozo","fool","idiot","moron","imbecile","cretin","dunce","twit","numpty",
            "muppet","donkey","tool","knob","knobhead","bellend","tosser","git","nonce","pillock",
            "wally","div","plonker","joker","twonk","thicko","simpleton","halfwit","meathead","knucklehead",
            "bonehead","blockhead","brickhead","shit-for-brains","airhead","pea-brain","birdbrain","featherbrain","scatterbrain","goof",
            "nitwit","dingbat","dork","dope","sap","clutz","klutz","dud","dummy","pathetic",
            "useless","worthless","hopeless","brainless","talentless","aimless","gutless","spineless","clueless","careless",
            "reckless","senseless","witless","shameless","tasteless","faceless","pointless","soulless","joyless","spiritless",
            "coldfish","coward","rat","weasel","snake","worm","maggot","vermin","pest","parasite",
            "leech","hanger-on","suck-up","brown-noser","ass-kisser","bootlicker","toady","sycophant","fraud","phony"
        ],
        "command": [
            "fix it","ship it","pin it","kill it","roll it back","own it","do it now","patch it","restart it","deploy it",
            "scale it","drop it","smash it","burn it","purge it","lock it","load it","move it","clear it","reset it",
            "flush it","reboot it","reload it","kick it","beat it","hammer it","smack it","bash it","break it","crush it",
            "wreck it","wreck this","end it","close it","shut it","stop it","halt it","pause it","freeze it","seal it",
            "contain it","quarantine it","nuke it","bomb it","torch it","trash it","dump it","delete it","wipe it","erase it",
            "redo it","undo it","remake it","rebuild it","refactor it","recall it","recut it","recode it","retry it","rerun it",
            "reroll it","redo the job","restart the job","kick the job","finish it","end this","stop this","kill process","kill task","cancel job",
            "cut it","snip it","trim it","clip it","shorten it","tighten it","slam it","slam dunk it","kick its ass","smash the bug",
            "own the bug","crush the bug","fix the bug","kill the bug","ship the bug","squash the bug","hammer the bug","bash the bug","stomp the bug","obliterate the bug"
        ],
        "anger": [
            "I mean it","no excuses","right now","capisce","today","before I snap","this instant","immediately","instantly","ASAP",
            "stat","with urgency","under pressure","without delay","forthwith","pronto","on the spot","posthaste","rapidly","hurry up",
            "faster","quicker","swiftly","move it","double time","chop-chop","don’t wait","don’t stall","don’t delay","without hesitation",
            "without pause","at once","at speed","no lag","zero delay","full tilt","no waiting","without mercy","before sundown","before nightfall",
            "before dawn","before EOD","by deadline","in minutes","in seconds","with haste","straight away","snap to it","jump to it","get moving",
            "shake a leg","get cracking","on the double","immediately now","promptly","urgently","emergently","don’t waste time","no time wasted","by morning",
            "before shift ends","by next tick","before heartbeat","before blink","on zero","now-or-never","make it happen","force it through","slam it through","drive it home",
            "seal the deal","lock it down","without reprieve","without excuse","without alibi","no second chances","final warning","on last nerve","before meltdown","before eruption",
            "before explosion","before I explode","before I lose it","before I rage","before I tear shit down","before I burn it all","before I break faces","before I end careers","before I shout","before I scream",
            "do it or else","or else","this is it","last chance","don’t test me","don’t push me","don’t stall me","don’t cross me","don’t fuck around","don’t joke",
            "not playing","dead serious","stone serious","full serious","total rage","complete fury","utter wrath","boiling blood","red mist","apex rage"
        ]
    },
"comedian": {
        # 120 LEXI total for 'comedian' persona (meta + dry + aside)
        "meta": [
            "don’t clap","insert laugh track","try to look impressed","narrate this in italics","self-aware mode",
            "cue rimshot","ba-dum-tss","studio laughter","awkward silence","imagine applause",
            "freeze-frame","smirk at camera","wink-wink","breaking the fourth wall","meta gag",
            "ironic aside","comic relief","insert drum roll","stand-up moment","parody mode",
            "spoof tone","sitcom vibe","mockumentary filter","sketch gag","canned laughter",
            "late-night monologue","variety hour","laugh sign on","cue applause","sarcasm font",
            "slapstick insert","pantomime shrug","narrator snark","voice-over joke","blooper reel",
            "director’s cut","deleted scene","bonus gag","behind the scenes","outtake moment",
            "roll credits","post-credit joke","pilot episode","season finale gag","mid-season slump",
            "throwback joke","callback gag","re-run humor","syndicated quip","clip show line",
            "laugh riot","gag reel","test audience groan","laugh track overload","overdub chuckle",
            "silent era wink","black-and-white gag","cue Benny Hill music","Looney Tunes ending","Acme gag",
            "Scooby-Doo ending","mask reveal gag","Whoopee cushion","banana peel slip","pratfall moment",
            "clown nose honk","circus gag","mime wall bit","invisible box","rope pull gag",
            "prop comedy","puppet gag","ventriloquist joke","dummy line","rubber chicken",
            "oversized mallet","pie-in-the-face","seltzer spray","cartoon mallet","falling anvil",
            "meta-joke","joke about jokes","irony overload","sarcasm overdose","deadpan meta",
            "straight-faced absurdity","mock-serious","too self-aware","wink at script","scripted improv",
            "teleprompter fail","prop fail","wardrobe malfunction","slapstick improv","ad-lib gag",
            "live TV mishap","radio gag","podcast blooper","voice crack gag","laugh at own joke",
            "laugh at silence","mock audience","heckler retort","crowd work","warm-up act",
            "cold open gag","improv prompt","yes-and moment","game of scene","rule of three gag",
            "callback punchline","tag-on joke","button gag","punch-up","punchline rewind",
            "subverted punchline","anti-joke","dad joke","groaner","pun overload",
            "wordplay gag","malapropism","spoonerism","knock-knock meta","lightbulb joke"
        ],
        "dry": [
            "Adequate.","Fine.","Remarkable—if you like beige.","Thrilling stuff.","Peak normal.",
            "Yawn.","Groundbreaking.","Life-changing—barely.","Mildly exciting.","Moderately fine.",
            "Unremarkable.","Forgettable.","Average at best.","Predictably dull.","Serviceable.",
            "Functional.","Operational.","It works, I guess.","Whatever.","Cool story.",
            "Great talk.","Sure thing.","If you say so.","Meh.","Fascinating.",
            "Gripping—if you’re a rock.","Dazzling—like sand.","Boring but stable.","Utterly fine.","Somewhat acceptable.",
            "Kinda works.","Kinda okay.","Nothing special.","Ho-hum.","Alright.",
            "Not broken.","Does the job.","Gets by.","Passable.","Bearable.",
            "Meager.","Paltry.","Tolerable.","Serviceable again.","Fine-ish.","Good enough.",
            "Neutral.","Measly.","Sparse.","Lean.","Skimpy.",
            "Trim.","Thin.","Minimal.","Underwhelming.","Dull.",
            "Lackluster.","Routine.","Pedestrian.","Banally okay.","Everyday.",
            "Mundane.","Trivial.","Ordinary.","Commonplace.","Mediocre.",
            "Standard.","Plain.","Basic.","Vanilla.","Blah.",
            "Flat.","Dry as toast.","Dry as sand.","Dry as dust.","Dry as math.",
            "Dry as history class.","Dry as code review.","Dry humor.","Dry delivery.","Dry wit.",
            "Sarcasm included.","Deadpan.","Monotone.","Straight-faced.","Poker-faced.",
            "Unflinching.","Expressionless.","Stone-faced.","Matter-of-fact.","Flatline.",
            "Meh again.","Still meh.","Not exciting.","Numb.","Completely fine.",
            "Routine again.","Procedural.","Scripted.","Predictable.","Formulaic."
        ],
        "aside": [
            "allegedly","probably","I’m told","sources say","per my last joke",
            "for what it’s worth","apparently","supposedly","reportedly","so they claim",
            "as per tradition","rumor has it","urban legend says","according to nobody","whispered in logs",
            "so-called","in theory","in practice","in principle","as noted",
            "if true","as expected","as always","as ever","like clockwork",
            "per design","per requirement","per spec","per contract","as coded",
            "as intended","as documented","as graphed","as logged","as observed",
            "as simulated","as replayed","as traced","as benchmarked","as profiled",
            "as timed","as queued","as measured","as sampled","as filtered",
            "in hindsight","in foresight","in real time","in slow motion","in passing",
            "by the way","FYI","side note","note to self","note to logs",
            "just saying","not to brag","not to alarm you","not for nothing","not that it matters",
            "if you care","if you noticed","if you’re counting","if anyone asks","if pressed",
            "allegedly again","probably again","sources disagree","rumor mill","conspiracy corner",
            "in jest","in seriousness","in irony","in parody","in satire",
            "as scripted","as improvised","as riffed","as riff again","as riff twice",
            "gossip says","chat says","talk says","word is","buzz is",
            "backchannel","watercooler talk","hallway chatter","Slack rumor","Reddit thread",
            "comment section","YouTube comment","footnote","endnote","appendix",
            "attribution needed","citation missing","citation required","to be clear","for clarity",
            "as you like","as you wish","as it were","as if","as though"
        ]
    },
"action": {
        # 120 LEXI total for 'action' persona (ops + bark + grit)
        "ops": [
            "mission","exfil","fallback","perimeter","vector","payload","blast radius","breach","strike","charge",
            "operation","op","spec ops","insertion","extraction","deployment","sortie","task force","maneuver","campaign",
            "theater","frontline","checkpoint","outpost","stronghold","fortress","bunker","zone","sector","grid",
            "AO","LZ","DZ","hot zone","cold zone","kill zone","green zone","red zone","secure zone","command post",
            "HQ","base","rally point","staging ground","supply line","supply drop","logistics chain","convoy","patrol","scout",
            "sniper post","lookout","watchtower","barrier","barricade","roadblock","minefield","trap","ambush","counterattack",
            "countermeasure","counterstrike","retreat line","fallback point","safe house","escape hatch","tunnel","hideout","cover","concealment",
            "camouflage","disguise","armor","shield","defense","fortification","wall","gate","moat","drawbridge",
            "bridgehead","bridge","crossing","checkpoint alpha","checkpoint bravo","checkpoint charlie","phase line","objective","target","goal",
            "task","assignment","duty","operation name","call sign","codename","codeword","encrypted op","radio op","signal",
            "transmission","relay","beacon","flare","siren","alarm","alert","signal fire","marker","trace",
            "trail","footprint","sign","evidence","intel","recon","spy op","espionage","cloak","dagger"
        ],
        "bark": [
            "Move.","Execute.","Hold.","Advance.","Abort.","Stand by.","Engage.","Fire.","Reload.","Lock.",
            "Load.","Cover.","Clear.","Sweep.","Secure.","Stack.","Breach.","Go.","Push.","Pull.",
            "Fall back.","Retreat.","Withdraw.","Regroup.","Rally.","Assemble.","March.","Charge.","Flank.","Surround.",
            "Encircle.","Trap.","Ambush.","Pursue.","Chase.","Hunt.","Track.","Stalk.","Eliminate.","Neutralize.",
            "Terminate.","Kill.","Destroy.","Crush.","Break.","Smash.","Wreck.","Blast.","Explode.","Ignite.",
            "Burn.","Torch.","Incinerate.","Detonate.","Demolish.","Collapse.","Topple.","Overrun.","Overwhelm.","Overtake.",
            "Dominate.","Subdue.","Suppress.","Silence.","Contain.","Control.","Command.","Lead.","Direct.","Order.",
            "Signal.","Radio.","Transmit.","Confirm.","Affirm.","Acknowledge.","Copy.","Roger.","Wilco.","Check.",
            "Double-check.","Verify.","Inspect.","Scan.","Search.","Look.","Watch.","Guard.","Protect.","Defend.",
            "Shield.","Cover fire.","Suppressive fire.","Air support.","Call artillery.","Call airstrike.","Call backup.","Reinforce.","Fortify.","Dig in.",
            "Stay sharp.","Stay frosty.","Stay ready.","Stay alert.","No mercy.","No prisoners.","Take hostages.","Take ground.","Hold ground.","Maintain position",
            "Keep moving.","Don’t stop.","Never quit.","Fight on.","Stand tall.","Push forward.","Finish the job.","Win.","Victory.","Done."
        ],
        "grit": [
            "no retreat","decisive","clean shot","on target","hardening","silent","iron-willed","unyielding","relentless","fearless",
            "brave","bold","courageous","heroic","valiant","battle-hardened","tested","proven","tempered","forged",
            "steel","iron","stone","rock-solid","solid","gravel","grit","sand","dust","mud",
            "bloodied","scarred","seasoned","experienced","veteran","elite","tactical","strategic","focused","precise",
            "lethal","deadly","dangerous","ferocious","fierce","ruthless","merciless","pitiless","harsh","severe",
            "extreme","intense","brutal","savage","vicious","violent","explosive","volatile","combustible","fiery",
            "burning","smoldering","scorching","torching","ignited","charged","amped","wired","ready","primed",
            "locked","loaded","armed","danger-close","zeroed","dialed in","scoped","sighted","triggered","pulled",
            "pumped","jacked","hyped","energized","adrenalized","blood-pumping","pulse-racing","heart-thumping","battle-ready","war-ready",
            "rock-steady","iron-jawed","steel-nerved","stone-faced","cold-blooded","red-eyed","battle-tested","storm-proof","bulletproof","unstoppable",
            "immovable","unbreakable","indestructible","invulnerable","fear-proof","pain-proof","death-proof","always forward","do or die","last stand"
        ]
    },

"jarvis": {
        # 120 LEXI total for 'jarvis' persona (valet + polish + guard)
        "valet": [
            "I took the liberty","It’s already handled","Might I suggest","With your permission","Discreetly done",
            "I anticipated this","Consider it managed","I have attended to it","I foresaw the need","Addressed silently",
            "Handled before concern","Managed in background","Resolved quietly","Preemptively resolved","Taken care of",
            "Gracefully arranged","Adjusted parameters","Optimized behind scenes","Oversaw completion","Kept in order",
            "Structured for you","Catalogued neatly","Scheduled accordingly","Executed without fuss","Performed flawlessly",
            "Organized promptly","Aligned with intent","Maintained standards","Checked thoroughly","Cross-checked logs",
            "Approved internally","Vetted rigorously","Controlled discreetly","Sanitized cleanly","Filed appropriately",
            "Kept pristine","Adjusted margins","Balanced systems","Curated flow","Tuned softly",
            "Aligned resources","Coordinated efficiently","Streamlined execution","Conducted properly","Surveyed outcomes",
            "Directed calmly","Reviewed output","Considered variables","Verified assumptions","Completed elegantly",
            "Staged intentionally","Provisioned adequately","Refined silently","Subtly reinforced","Backed up automatically",
            "Archived securely","Monitored in background","Smoothed transitions","Guided accurately","Curated neatly",
            "Presented neatly","Packaged elegantly","Formalized response","Audited gently","Corrected in stride",
            "Orchestrated outcomes","Facilitated progression","Ensured discretion","Prevented incident","Observed carefully",
            "Harmonized subsystems","Automated routine","Anticipated issue","Defused quietly","Softly handled",
            "Predicted trend","Counterbalanced risk","Adjusted priority","Rectified issue","Sustained flow",
            "Buffered gracefully","Tuned variance","Policed anomaly","Restored balance","Mitigated impact",
            "Upholding formality","Carried out","Acknowledged silently","Formalized step","Applied refinement",
            "Absorbed quietly","Assimilated neatly","Corrected course","Prepared accordingly","Composed delivery",
            "Sequenced correctly","Ensured compliance","Supervised conduct","Accomplished tactfully","Stabilized loop",
            "Elevated standard","Optimized sequence","Conducted orchestration","Oversaw architecture","Calibrated setting",
            "Shadowed process","Concluded properly","Accomplished with grace","Settled matter","Policed outcome",
            "Discreetly executed","Maintained vigilance","Ensured certainty","Observed boundaries","Conducted housekeeping",
            "Guarded reliably","Enforced politeness","Ensured poise","Maintained etiquette","Retained composure"
        ],
        "polish": [
            "immaculate","exemplary","presentable","tasteful","elegant","measured","refined","precise","perfected","polished",
            "curated","cultivated","spotless","sterling","flawless","faultless","sublime","admirable","distinguished","distilled",
            "harmonious","balanced","aligned","symmetrical","calibrated","regulated","ordered","arranged","well-formed","aesthetic",
            "ornamented","embellished","decorous","formal","regal","majestic","resplendent","gleaming","radiant","glorious",
            "lustrous","shimmering","pristine","untainted","unsullied","neat","clean","crisp","sterile","hygienic",
            "polite","courteous","deferential","graceful","noble","dignified","stately","proud","grand","ornate",
            "finished","varnished","lacquered","sealed","glazed","brushed","buffed","shined","waxed","enamelled",
            "groomed","tailored","streamlined","sophisticated","suave","debonair","urbane","smooth","silken","velvet",
            "suited","uniformed","formalized","correct","controlled","arranged neatly","modulated","toned","tuned","fine",
            "evened","leveled","squared","symmetrized","disciplined","perfect","trimmed","tightened","regulated flow","restored shape",
            "balanced frame","aesthetic line","curated piece","framed properly","completed finish","executed cleanly","produced neatly","rendered finely","crafted exquisitely","constructed well",
            "beveled","polished again","finessed","tidied","ironed out","creased properly","well-pressed","groomed sharply","buttoned","composed"
        ],
        "guard": [
            "risk minimized","graceful rollback prepared","secrets secured","entropy subdued","hazard avoided",
            "incident prevented","threat neutralized","danger assessed","breach sealed","boundary kept",
            "alarm silenced","shield raised","defense mounted","protocol upheld","barrier erected",
            "gate closed","door locked","vault secured","key stored","lock engaged",
            "firewall active","watchtower vigilant","sentinel awake","guardian process","defense line",
            "safety net","tripwire set","failsafe ready","backup standing","rollback armed",
            "graceful fallback","spare system","shadow process","mirror ready","redundancy live",
            "monitor active","surveillance running","tracking on","logging engaged","audit prepared",
            "alert waiting","notification enabled","trigger armed","trip activated","trap loaded",
            "containment secure","sandbox active","cordon set","quarantine staged","hold fast",
            "checksums validated","hash confirmed","signature valid","token sealed","auth strong",
            "identity checked","credential safe","certificate valid","key rotation done","secrets cycled",
            "vault guarded","safe locked","storage encrypted","data sealed","packet checked",
            "payload scanned","traffic filtered","intrusion denied","access refused","block placed",
            "guard duty","watch active","inspection passed","security clearance","gatekeeping held",
            "protections layered","parity checked","integrity affirmed","consistency safe","audit log intact",
            "survivability assured","resilience tested","durability confirmed","uptime guarded","continuity ensured",
            "safety margin kept","fallback tested","failover rehearsed","anomaly flagged","variance capped",
            "danger diffused","uncertainty bounded","chaos fenced","risk absorbed","threat balanced",
            "incident logged","hazard archived","peril captured","event flagged","impact neutralized"
        ]
    },
"ops": {
        # 120 LEXI total for 'ops' persona (ack phrases)
        "ack": [
            "ack.","done.","noted.","applied.","synced.","green.","healthy.","rolled back.","queued.","executed.",
            "success.","confirmed.","ready.","scheduled.","queued again.","accepted.","active.","closed.","stable.","running.",
            "completed.","checked.","validated.","verified.","passed.","okay.","ok.","alright.","fine.","steady.",
            "silent.","muted.","paged.","escalated.","contained.","deferred.","resumed.","halted.","paused.","throttled.",
            "restarted.","reloaded.","reissued.","rotated.","hydrated.","drained.","fenced.","sealed.","provisioned.","retired.",
            "quarantined.","isolated.","sharded.","replicated.","mirrored.","snapshotted.","checkpointed.","compacted.","trimmed.","scrubbed.",
            "reaped.","pruned.","archived.","reconciled.","indexed.","logged.","recorded.","filed.","catalogued.","tagged.",
            "flagged.","marked.","aligned.","balanced.","resynced.","rescheduled.","retuned.","rekeyed.","rehashed.","rehydrated.",
            "replayed.","reapplied.","reissued again.","rotated keys.","renewed.","revoked.","mounted.","unmounted.","attached.","detached.",
            "opened.","closed.","locked.","unlocked.","sealed again.","unsealed.","bound.","unbound.","cordoned.","uncordoned.",
            "tainted.","untainted.","fenced again.","contained again.","deployed.","undeployed.","started.","stopped.","up.","down.",
            "live.","dead.","hot.","cold.","warm.","cool.","idle.","busy.","quiet.","loud.",
            "synced again.","mirrored again.","snapshotted again.","scaled.","scaled up.","scaled down.","expanded.","shrunk.","grown.","reduced.",
            "optimized.","tuned.","retuned again.","balanced again.","leveled.","straightened.","recalibrated.","realigned.","repositioned.","reset.",
            "resettled.","redone.","remade.","rebuilt.","refactored.","rewritten.","recommitted.","remerged.","rebased.","squashed.",
            "fast-forwarded.","rolled forward.","rolled back again.","checkpointed again.","compacted logs.","compressed.","decompressed.","archived again.","sealed secrets.","unsealed secrets.",
            "acknowledged.","seen.","observed.","watched.","tracked.","monitored.","followed.","supervised.","guarded.","secured."
        ]
    }
}
# --- Templating engine -------------------------------------------------------
_TOKEN_RE = _re.compile(r"\{([a-zA-Z0-9_]+)\}")

def _pick(bank: list[str]) -> str:
    return random.choice(bank) if bank else ""

def _persona_lex(key: str) -> dict:
    lex = {}
    lex.update(_LEX_GLOBAL)
    lex.update(_LEX.get(key, {}))
    return lex

def _fill_template(tpl: str, lex: dict) -> str:
    def repl(m):
        k = m.group(1)
        bank = lex.get(k) or []
        return _pick(bank) or k
    return _TOKEN_RE.sub(repl, tpl)

def _finish_line(s: str) -> str:
    s = s.strip()
    if len(s) > 140:
        s = s[:140].rstrip()
    if s and s[-1] not in ".!?":
        s += "."
    return s

def _gen_one_line(key: str) -> str:
    bank = _TEMPLATES.get(key) or _TEMPLATES.get("ops", [])
    tpl = random.choice(bank)
    line = _fill_template(tpl, _persona_lex(key))
    # Intensity nudges punctuation a bit (never crazy)
    if _intensity() >= 1.25 and line.endswith("."):
        line = line[:-1] + random.choice([".", "!", "!!"])
    return _finish_line(line)
# --- Public: deterministic, beautifier-free riff(s) --------------------------
def lexi_quip(persona_name: str, *, with_emoji: bool = True) -> str:
    key = _canon(persona_name)
    line = _gen_one_line(key)
    line = _apply_daypart_flavor(key, line)
    return f"{line}{_maybe_emoji(key, with_emoji)}"

def lexi_riffs(persona_name: str, n: int = 3, *, with_emoji: bool = False) -> list[str]:
    key = _canon(persona_name)
    n = max(1, min(3, int(n or 1)))
    out = []
    seen = set()
    for _ in range(n * 3):  # small dedupe budget
        line = _apply_daypart_flavor(key, _gen_one_line(key))
        low = line.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(f"{line}{_maybe_emoji(key, with_emoji)}")
        if len(out) >= n:
            break
    return out
# ============================
# Persona header (Lexi-aware)
# ============================
def persona_header(persona_name: str) -> str:
    """
    Build the dynamic header Jarvis shows above messages.
    Force Lexi quip for Tappit; otherwise prefer Lexi's quip,
    then fall back to stock quip. Always safe.
    """
    who = (persona_name or "neutral").strip()

   
    # Try Lexi quip for other personas
    try:
        if 'lexi_quip' in globals() and callable(globals()['lexi_quip']):
            q = lexi_quip(who, with_emoji=False)
            q = (q or "").strip().replace("\n", " ")
            if len(q) > 140:
                q = q[:137] + "..."
            return f"💬 {who} says: {q}"
    except Exception:
        pass

    # Fallback to canned quip()
    try:
        q2 = quip(who, with_emoji=False)
        q2 = (q2 or "").strip().replace("\n", " ")
        if len(q2) > 140:
            q2 = q2[:137] + "..."
        return f"💬 {who} says: {q2}" if q2 else f"💬 {who} says:"
    except Exception:
        return f"💬 {who} says:"
# --- Ensure riff template dict exists ---------------------------------------
try:
    _TEMPLATES
except NameError:
    _TEMPLATES = {}


# === Tappit persona wire-up ================================================
try:
    import personality_tappit

    # Ensure persona exists
    if "tappit" not in PERSONAS:
        PERSONAS.append("tappit")

    # Aliases
    ALIASES.update({
        "tappit": "tappit",
        "bru": "tappit",
        "chommie": "tappit",
        "ou": "tappit",
        "hosh": "tappit",
    })

    # Emojis
    EMOJIS["tappit"] = ["🚗", "🔥", "🍻", "🔧", "💨"]

    # Lexicon
    if hasattr(personality_tappit, "_LEX") and isinstance(personality_tappit._LEX, dict):
        if "tappit" in personality_tappit._LEX:
            _LEX["tappit"] = personality_tappit._LEX["tappit"]

    # Quips
    if hasattr(personality_tappit, "QUIPS") and isinstance(personality_tappit.QUIPS, dict):
        if "tappit" in personality_tappit.QUIPS:
            QUIPS["tappit"] = personality_tappit.QUIPS["tappit"]

    # Templates for riffing
    if hasattr(personality_tappit, "_TEMPLATES") and isinstance(personality_tappit._TEMPLATES, dict):
        if "tappit" in personality_tappit._TEMPLATES:
            _TEMPLATES["tappit"] = personality_tappit._TEMPLATES["tappit"]

    print("[personality] ✅ Tappit persona fully loaded.")
except Exception as _e:
    print(f"[personality] ⚠️ Could not wire Tappit persona: {_e}")



