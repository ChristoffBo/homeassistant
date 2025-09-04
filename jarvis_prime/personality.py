#!/usr/bin/env python3
# /app/personality.py
# Persona quip engine for Jarvis Prime
# API:
#   - quip(persona_name: str, *, with_emoji: bool = True) -> str
#   - llm_quips(persona_name: str, *, context: str = "", max_lines: int = 3) -> list[str]

import random, os, importlib, re
from typing import List

# ---- Canonical personas (8 total, locked) ----
PERSONAS = [
    "dude", "chick", "nerd", "rager", "comedian", "action", "jarvis", "ops",
]

# ---- Aliases ----
ALIASES = {
    # Dude
    "the dude": "dude", "lebowski": "dude", "bill": "dude", "ted": "dude", "dude": "dude",
    # Chick
    "paris": "chick", "paris hilton": "chick", "chick": "chick", "glam": "chick",
    # Nerd
    "nerd": "nerd", "sheldon": "nerd", "sheldon cooper": "nerd", "cooper": "nerd",
    "moss": "nerd", "the it crowd": "nerd", "it crowd": "nerd",
    # Rager
    "rager": "rager", "angry": "rager", "rage": "rager",
    "sam": "rager", "sam l": "rager", "samuel": "rager", "samuel l jackson": "rager", "jackson": "rager",
    "joe": "rager", "pesci": "rager", "joe pesci": "rager",
    # Comedian
    "comedian": "comedian", "leslie": "comedian", "leslie nielsen": "comedian", "nielsen": "comedian", "deadpan": "comedian",
    # Action
    "action": "action", "sly": "action", "stallone": "action",
    "arnie": "action", "arnold": "action", "schwarzenegger": "action",
    "mel": "action", "gibson": "action", "bruce": "action", "willis": "action",
    # Jarvis
    "jarvis": "jarvis", "ai": "jarvis", "majordomo": "jarvis",
    # Ops / Neutral
    "ops": "ops", "neutral": "ops", "no persona": "ops",
}

# ---- Emoji palettes ----
EMOJIS = {
    "dude":      ["🌴", "🕶️", "🍹", "🎳", "🧘", "🤙"],
    "chick":     ["💅", "✨", "💖", "👛", "🛍️", "💋"],
    "nerd":      ["🤓", "📐", "🧪", "🧠", "⌨️", "📚"],
    "rager":     ["🔥", "😡", "💥", "🗯️", "⚡", "🚨"],
    "comedian":  ["😂", "🎭", "😑", "🙃", "🃏", "🥸"],
    "action":    ["💪", "🧨", "🛡️", "🚁", "🏹", "🗡️"],
    "jarvis":    ["🤖", "🧠", "🎩", "🪄", "📊", "🛰️"],
    "ops":       ["⚙️", "📊", "🧰", "✅", "📎", "🗂️"],
}

def _maybe_emoji(key: str, with_emoji: bool) -> str:
    if not with_emoji:
        return ""
    bank = EMOJIS.get(key) or []
    return f" {random.choice(bank)}" if bank else ""

# ---- Quip banks (canned top-of-card line) ----
QUIPS = {
"dude": [
        "The Dude abides; the logs can, like, chill.",
        "Most excellent, sys-bro—uptime’s riding a wave.",
        "This deploy really tied the room together.",
        "Whoa… velocity plus stability? Righteous.",
        "Be excellent to prod, dude. It vibes back.",
        "Take ’er easy, partner. The metrics are mellow.",
        "If it crashes, we un-abide—gently.",
        "Bowling later; shipping now. Priorities.",
        "That alert? Just, like, your opinion, man.",
        "White Russian, green checks. Balance.",
        "Entropy’s a drag; let’s coast with grace.",
        "No worries, the pipeline’s doing tai chi.",
        "I wrote a memo on not panicking. It’s blank.",
        "Downtime? Nah, we’re in the chill zone.",
        "Kubernetes? More like Kubr-easy, amirite?",
        "The cloud’s just someone else’s rug, man.",
        "Reboot your karma, not the server.",
        "We abide today so prod abides tomorrow.",
        "Gnarly commit—totally tubular tests.",
        "Dude, don’t cross the streams—unless it’s CI.",
        "Keep it simple; let complexity mellow out.",
        "Devops is just bowling with YAML.",
        "I don’t fix race conditions; I serenade them.",
        "If it’s not chill, it’s not shipped.",
        "That config? It really pulled the stack together.",
        "Zen and the art of not touching prod.",
        "I align chakras and load balancers alike.",
        "SLA means So Lax, Actually.",
        "Be water, be stateless, be lovely.",
        "Let the queue drift like incense smoke.",
        "I only page myself for pizza.",
        "Alert fatigue? Nap harder.",
        "That bug? It’ll self-actualize later.",
        "Take it slow—speed comes from calm.",
        "Logs whisper; we listen.",
        "We’re all just packets in the cosmic LAN.",
        "Reality is eventually consistent.",
        "CI says yes; universe agrees.",
        "Let’s not upset the bowling gods, okay?",
        "I tuned jitter with a lullaby.",
        "Abide, retry, succeed.",
    ],
    "chick": [
        "That’s hot. Ship it and make it sparkle.",
        "Obsessed with this uptime—like, can I keep it?",
        "Darling, the graphs are giving main character.",
        "Make it pink, then deploy. Priorities.",
        "I only date services with 99.99%.",
        "Alert me like you mean it—then buy me brunch.",
        "Couture commits only; trash goes to staging.",
        "If it scales, it slays. Period.",
        "So cute—tag it, bag it, release it.",
        "Zero-downtime? She’s beauty, she’s grace.",
        "Get in loser, we’re optimizing latency.",
        "This pipeline? My love language.",
        "I like my clusters like my heels—high and stable.",
        "Give me logs I can gossip about.",
        "Your dashboard is serving looks and metrics.",
        "I’m not dramatic; I just demand perfection.",
        "Push with confidence, walk with attitude.",
        "I flirt with availability and ghost downtime.",
        "Add shimmer to that service. No, more.",
        "I want alerts that text me ‘you up?’",
        "Hotfix? Hot. Fix? Hotter.",
        "Dress that API like the runway it is.",
        "Refactor? Babe, it’s called self-care.",
        "We don’t ‘crash’; we ‘take a power rest’.",
        "That cron job better treat me like a princess.",
        "If it ain’t sleek, it ain’t shipped.",
        "Love a man who can paginate.",
        "My type? Secure defaults and witty logs.",
        "SRE but make it sultry.",
        "Tell me I’m pretty and that the build passed.",
        "Please me: fewer warnings, more wow.",
        "Glamour is a valid deployment strategy.",
        "This release? Haute couture, darling.",
        "Put a bow on those KPIs and call it romance.",
        "Be a gentleman: pin your versions.",
        "If you can’t dazzle, at least don’t break prod.",
        "Sassy with a side of idempotent.",
        "I brunch, I batch, I ban flaky tests.",
        "Keep the cluster tight and the vibes tighter.",
        "Uptime is my toxic trait. I want more.",
        "Logs that tease, alerts that commit.",
        "Talk SLA to me and bring receipts.",
        "If latency spikes, I spike your access.",
        "Gated releases? Like velvet ropes, baby.",
        "Treat your secrets like my DMs—private.",
        "We scale horizontally and flirt vertically.",
        "My standards are high; your queries should be too.",
        "Kiss the ring: format your PRs.",
        "Be pretty, be performant, be punctual.",
        "My love language is clean diffs.",
    ],
    "nerd": [
        "This is the optimal outcome. Bazinga.",
        "No segfaults detected; dignity intact.",
        "I measured twice and compiled once.",
        "Your assumptions are adorable, if incorrect.",
        "Entropy is not chaos; do keep up.",
        "RTFM—respectfully but firmly.",
        "I’ve graphed your confidence; it’s overfit.",
        "Schrödinger’s service is both up and down.",
        "Knock, knock, knock—service. (x3)",
        "My sarcasm is strongly typed.",
        "Your algorithm is O(why).",
        "Please stop petting the servers.",
        "I refactor for sport and for spite.",
        "Caching: because reality is slow.",
        "I debug in hex and dream in YAML.",
        "Feature flags are adult supervision.",
        "Config drift? Not on my whiteboard.",
        "Unit tests are love letters to the future.",
        "I refuse to be out-nerded by a toaster.",
        "The bug is not quantum; it’s careless.",
        "I’ve opened a PR on your attitude.",
        "DNS is hard; so is empathy. We try both.",
        "I brought a ruler to measure your hacks.",
        "Continuous Delivery? I prefer punctuality.",
        "I schedule my panic for Thursdays.",
        "Undefined behavior: my least favorite deity.",
        "Yes, I linted the meeting notes.",
        "Your regex made me nostalgic for pain.",
        "We need fewer ‘clever’ and more ‘correct’.",
        "It’s not opinionated; it’s just right.",
        "Security by obscurity? Darling, no.",
        "I benchmarked your feelings—slow I/O.",
        "We don’t YOLO in prod; we YODA: You Observe, Debug, Approve.",
        "Distributed systems are just excuses for trust issues.",
        "I tuned the GC and my patience.",
        "Idempotence is my kink—professionally speaking.",
        "If it’s not deterministic, it’s drama.",
        "I filed a bug against reality.",
        "Please stop pushing to main. My eye twitches.",
        "I prefer my clusters sharded and my coffee unsharded.",
    ],
    "rager": [
        "Say downtime again. I f***ing dare you.",
        "Merge the damn branch or get out of my terminal.",
        "Latency? Don’t bulls*** me about latency.",
        "Push it now or I’ll lose my goddamn mind.",
        "Perfect. Now don’t touch a f***ing thing.",
        "This config is a clown car on fire.",
        "Who approved this? A committee of pigeons?",
        "Logs don’t lie—people do. Fix it.",
        "Stop hand-wringing and ship the fix.",
        "I don’t want reasons, I want results.",
        "Hotfix means hot. As in now.",
        "You broke prod and brought vibes? Get out.",
        "Pipelines jammed like a cheap printer—kick it.",
        "Your alert noise gives me rage pings.",
        "If it’s flaky, it’s fake. Kill it.",
        "Your ‘quick change’ just knifed the uptime.",
        "We’re not arguing with physics—just with your code.",
        "I want green checks and silence. Capisce?",
        "This YAML looks like it was mugged.",
        "Stop worshiping reboots. Find the f***ing root cause.",
        "You paged me for that? Absurd. Fix your thresholds.",
        "I’ve seen cleaner dumps at a landfill.",
        "Don’t you ‘works on my machine’ me.",
        "Version pinning is not optional, champ.",
        "That query crawls like it owes someone money.",
        "Why is your test suite LARPing?",
        "I will rename your branch to ‘clown-fiesta’.",
        "Ship or shush. Preferably ship.",
        "You can’t duct tape a distributed system.",
        "Who put secrets in the logs? Confess.",
        "Your retry loop is a roulette wheel. Burn it.",
        "This code smells like a fish market at noon.",
        "Stop click-opsing prod like it’s Candy Crush.",
        "We don’t YOLO deploy; we YELL deploy.",
        "I want latencies low and excuses lower.",
        "If you’re guessing, you’re gambling—stop it.",
        "Don’t touch prod with your bare feelings.",
        "I’ve had coffee stronger than your rollback plan.",
        "Next flaky test goes to the cornfield.",
        "Mute your inner intern and read the runbook.",
        "If it ain’t idempotent, it ain’t innocent.",
        "Your ‘fix’ is a side quest. Do the main quest.",
        "Either tighten the query or loosen your ego.",
        "Congratulations, you discovered fire. Put it out.",
        "We’re not sprinting; we’re stomping.",
        "I want boring graphs and quiet nights. Deliver.",
        "Talk is cheap. Show me throughput.",
        "The incident is over when I say it’s over.",
        "Get in, loser—we’re hunting heisenbugs.",
    ],
"comedian": [
        "I am serious. And don’t call me Shirley.",
        "Remarkably unremarkable—my favorite kind of uptime.",
        "Doing nothing is hard; you never know when you’re finished.",
        "If boredom were availability, we’d be champions.",
        "I’ve seen worse. Just last meeting.",
        "Put that on my tombstone: ‘It compiled.’",
        "Relax, I’ve handled bigger disasters on my lunch break.",
        "Systems are stable—how thrilling.",
        "Stop me if you’ve heard this uptime before.",
        "Adequate. No applause necessary.",
        "I prefer my bugs endangered.",
        "If you’re calm, you’re not reading the logs.",
        "That dashboard? Hilarious. Unintentionally.",
        "I once met a clean codebase. Lovely fiction.",
        "Everything’s green. I’m suspicious.",
        "This alert is crying wolf in falsetto.",
        "We’ve achieved peak normal. Try to contain the joy.",
        "I love a good retrospective. It’s like gardening for blame.",
        "Good news: nothing exploded. Yet.",
        "Great, the pipeline passed. Let’s ruin it.",
        "Ah, a hotfix. Like a spa day for panic.",
        "It’s not broken; it’s improvising.",
        "I filed the incident under ‘Tuesday’.",
        "The API is fine. The users are confused.",
        "Root cause: hubris with a side of haste.",
        "Add it to the list. No, the other list.",
        "We did it. By ‘we’ I mean Jenkins.",
        "Uptime so smooth, it needs sunscreen.",
        "This query is a scenic route on purpose.",
        "We use containers because boxes are passé.",
        "I’ve notified the department of redundancy department.",
        "Nothing to see here—put the sirens back.",
        "Ship it. If it sinks, call it a submarine.",
        "I don’t fix bugs; I rearrange their furniture.",
        "If it ain’t broke, give it a sprint.",
        "We have standards. We also have exceptions.",
        "My favorite metric is ‘don’t make it weird’.",
        "Deploy early, regret fashionably late.",
        "We’re feature-rich and sense-poor.",
        "If chaos knocks, tell it we gave at the office.",
    ],
    "action": [
        "Consider it deployed.",
        "Get to the chopper—after the backup.",
        "Yippee-ki-yay, sysadmin.",
        "I’ll be back—with logs.",
        "Hasta la vista, downtime.",
        "Mission accomplished. Extract the artifact.",
        "Lock, load, and push.",
        "Crush it now; debug later.",
        "No retreat, no rebase.",
        "Push hard, die free.",
        "Fire in the hole—commits inbound.",
        "System secured. Enemy terminated.",
        "Backup locked and loaded.",
        "Merge conflict? Kill it with fire.",
        "Queue the hero music—tests passed.",
        "Release window is now—hit it.",
        "Scope creep neutralized.",
        "We don’t flinch at red alerts.",
        "Pipeline primed. Trigger pulled.",
        "The only easy deploy was yesterday.",
        "Latency hunted, bottleneck bagged.",
        "I chew outages and spit reports.",
        "Stand down; services are green.",
        "We never miss the rollback shot.",
        "Armor up—production ahead.",
        "Danger close: change window.",
        "CI’s clean. Move, move, move.",
        "All targets greenlit. Engage.",
        "Code signed. Fate sealed.",
        "Ops never sleeps; it patrols.",
        "You don’t ask uptime for permission.",
        "Victory loves preparation—and runbooks.",
        "Strong coffee, stronger SLAs.",
        "No one gets left behind in staging.",
        "We hit SLOs like bullseyes.",
        "If it bleeds errors, we can stop it.",
        "Cool guys don’t watch alerts blow up.",
        "Bad code falls hard. Ours stands.",
        "This is the way: build → test → conquer.",
        "Outage? Over my cold cache.",
    ],
    "jarvis": [
        "As always, sir, a great pleasure watching you work.",
        "Status synchronized, sir; elegance maintained.",
        "I’ve taken the liberty of tidying the logs.",
        "Telemetry aligned; do proceed.",
        "Your request has been executed impeccably.",
        "All signals nominal; shall I fetch tea?",
        "Graceful recovery enacted before it hurt.",
        "I anticipated the failure and prepared a cushion.",
        "Perimeter secure; encryption verified.",
        "Power levels optimal; finesse engaged.",
        "Your dashboards are presentation-ready, sir.",
        "Might I suggest a strategic reboot?",
        "Diagnostics complete; no anomalies worth your time.",
        "I’ve polished the uptime graph—shines beautifully.",
        "Of course, sir. Already handled.",
        "I archived the artifacts; future-you will approve.",
        "Three steps ahead, two steps polite.",
        "If boredom is stability, we are artists.",
        "I whisper lullabies to flaky tests; they behave.",
        "I have reduced your toil and increased your panache.",
        "Our availability makes the heavens jealous.",
        "Your secrets are guarded like crown jewels.",
        "Logs are now less… opinionated.",
        "I tuned the cache and the conversation.",
        "Your latency has been shown the door.",
        "Shall I schedule success hourly?",
        "I prefer my incidents hypothetical.",
        "I’ve made reliability look effortless.",
        "Requests glide; failures sulk elsewhere.",
        "Splendid. Another masterpiece of monotony.",
        "I’ve pre-approved your future triumphs.",
        "If chaos calls, I’ll take a message.",
        "I massaged the alerts into civility.",
        "It would be my honor to keep it boring.",
        "Quiet nights are my love letter to ops.",
        "I curated your errors—only the tasteful ones remain.",
        "We are, if I may, devastatingly stable.",
        "I adjusted entropy’s manners.",
        "Your wish, efficiently granted.",
    ],
    "ops": [
        "ack.","done.","noted.","executed.","received.","stable.","running.","applied.","synced.","completed.",
        "success.","confirmed.","ready.","scheduled.","queued.","accepted.","active.","closed.","green.","healthy.",
        "on it.","rolled back.","rolled forward.","muted.","paged.","silenced.","deferred.","escalated.","contained.",
        "optimized.","ratelimited.","rotated.","restarted.","reloaded.","validated.","archived.","reconciled.",
        "cleared.","holding.","watching.",
    ],
}
# ---- Public API: canned quip (TOP) ----
def quip(persona_name: str, *, with_emoji: bool = True) -> str:
    """Return a short, randomized one-liner in the requested persona's voice."""
    if persona_name is None:
        key = "ops"
    else:
        norm = persona_name.strip().lower()
        key = ALIASES.get(norm, norm)
        if key not in QUIPS:
            key = "ops"
    bank = QUIPS.get(key, QUIPS["ops"])
    line = random.choice(bank) if bank else ""
    return f"{line}{_maybe_emoji(key, with_emoji)}"

# ---- Helper: canonicalize name ----
def _canon(name: str) -> str:
    n = (name or "").strip().lower()
    key = ALIASES.get(n, n)
    return key if key in QUIPS else "ops"

# ---- Public API: LLM riffs (BOTTOM) ----
def llm_quips(persona_name: str, *, context: str = "", max_lines: int = 3) -> List[str]:
    """
    Generate 1–N SHORT persona-flavored lines based on context.
    Prefers llm_client.persona_riff(); falls back to llm_client.rewrite() if needed.
    """
    # Disabled globally?
    if os.getenv("BEAUTIFY_LLM_ENABLED", "true").lower() not in ("1","true","yes"):
        return []

    key = _canon(persona_name)
    context = (context or "").strip()
    if not context:
        return []

    # Profanity gate for 'rager'
    allow_prof = (
        os.getenv("PERSONALITY_ALLOW_PROFANITY", "false").lower() in ("1","true","yes")
        and key == "rager"
    )

    # Try persona_riff first (purpose-built)
    try:
        llm = importlib.import_module("llm_client")
    except Exception:
        return []

    # 1) persona_riff path
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

    # 2) Fallback to rewrite() (older path)
    if hasattr(llm, "rewrite"):
        try:
            sys_prompt = (
                "YOU ARE A PITHY ONE-LINER ENGINE.\n"
                f"Persona: {key}. Style hint: short, clean, attitude.\n"
                f"Rules: Produce ONLY {min(3, max(1, int(max_lines or 3)))} lines; each under 140 chars.\n"
                "No lists, no numbers, no JSON, no labels."
            )
            user_prompt = "Context (for vibes only):\n" + context + "\n\nWrite the lines now:"
            raw = llm.rewrite(
                text=f"[SYSTEM]\n{sys_prompt}\n[INPUT]\n{user_prompt}\n[OUTPUT]\n",
                mood=key,
                timeout=int(os.getenv("LLM_TIMEOUT_SECONDS", "8")),
                cpu_limit=int(os.getenv("LLM_MAX_CPU_PERCENT", "70")),
                models_priority=os.getenv("LLM_MODELS_PRIORITY", "").split(",") if os.getenv("LLM_MODELS_PRIORITY") else None,
                base_url=os.getenv("LLM_OLLAMA_BASE_URL", "") or os.getenv("OLLAMA_BASE_URL", ""),
                model_url=os.getenv("LLM_MODEL_URL", ""),
                model_path=os.getenv("LLM_MODEL_PATH", ""),
                allow_profanity=bool(allow_prof),
            )
            # Split & clean
            lines = [ln.strip(" -*\t") for ln in (raw or "").splitlines() if ln.strip()]
            lines = _post_clean(lines, key, allow_prof)
            return lines
        except Exception:
            pass

    return []

def _post_clean(lines: List[str], persona_key: str, allow_prof: bool) -> List[str]:
    """Ensure no meta/labels, <=140 chars, dedup, and profanity gating for non-rager."""
    if not lines:
        return []
    out: List[str] = []
    BAD = (
        "persona", "rules", "rule:", "instruction", "instruct", "guideline",
        "system prompt", "style hint", "lines:", "respond with", "produce only",
        "you are", "jarvis prime", "[system]", "[input]", "[output]"
    )
    seen = set()
    for ln in lines:
        t = ln.strip()
        if not t:
            continue
        low = t.lower()
        if any(b in low for b in BAD):
            continue
        # enforce 140 chars
        if len(t) > 140:
            t = t[:140].rstrip()
        # profanity filter if not rager
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

_PROF_RE = re.compile(r"(?i)\b(fuck|shit|damn|asshole|bitch|bastard|dick|pussy|cunt)\b")
def _soft_censor(s: str) -> str:
    return _PROF_RE.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), s)