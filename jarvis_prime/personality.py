#!/usr/bin/env python3
# /app/personality.py
# Persona quip engine for Jarvis Prime
#
# Public API:
#   - quip(persona_name: str, *, with_emoji: bool = True) -> str
#   - llm_quips(persona_name: str, *, context: str = "", max_lines: int = 3) -> list[str]
#
# Persona inspirations (documentation only; NOT injected into prompts to avoid parroting):
#   dude      → Slacker‑zen + cheerful “be excellent” vibe (laid‑back, mellow confidence)
#   chick     → Glam couture sass + bubbly‑but‑brilliant optimism (smart, stylish, supportive)
#   nerd      → Pedantic precision + awkward IT savant (dry wit, correctness, graphs)
#   rager     → Drill‑sergeant / gangster / chef‑wrath intensity (blunt, kinetic, profane)
#   comedian  → Deadpan spoof + irreverent fourth‑wall meta sarcasm (outrageous yet controlled)
#   action    → Macho 80s/90s action‑hero archetype (terse, tactical, explosive, sardonic)
#   jarvis    → Polished AI valet (formal, anticipatory, subtly wry)
#   ops       → Neutral SRE/ops acks (laconic operational confirmations)
#
# NOTE: We intentionally avoid actor/brand names in prompts for riffing to prevent quote parroting.
#       Style is driven by descriptors only. Rager is always uncensored.
#       Daypart + intensity add non‑breaking flavor.
#
# Env knobs (optional):
#   - PERSONALITY_INTENSITY: float 0.6–2.0, default 1.0
#   - LLM_TIMEOUT_SECONDS: int, default 8
#   - LLM_MAX_CPU_PERCENT: int, default 70
#   - LLM_PERSONA_LINES_MAX: int, default 3
#   - LLM_MODELS_PRIORITY, LLM_OLLAMA_BASE_URL / OLLAMA_BASE_URL, LLM_MODEL_URL, LLM_MODEL_PATH

import random, os, importlib, re, time
from typing import List, Dict, Optional

# ----------------------------------------------------------------------------
# Daypart helpers (subtle time awareness; no greeting fluff)
# ----------------------------------------------------------------------------

def _daypart(now_ts: Optional[float] = None) -> str:
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

def _intensity() -> float:
    try:
        v = float(os.getenv("PERSONALITY_INTENSITY", "1.0"))
        return max(0.6, min(2.0, v))
    except Exception:
        return 1.0

# ---- Canonical personas ----
PERSONAS = [
    "dude", "chick", "nerd", "rager", "comedian", "action", "jarvis", "ops",
]

# ---- Aliases ----
ALIASES: Dict[str, str] = {
    # Dude
    "the dude": "dude", "lebowski": "dude", "bill": "dude", "ted": "dude", "dude": "dude",
    # Chick
    "paris": "chick", "paris hilton": "chick", "chick": "chick", "glam": "chick",
    "elle": "chick", "elle woods": "chick", "legally blonde": "chick",
    # Nerd
    "nerd": "nerd", "sheldon": "nerd", "sheldon cooper": "nerd", "cooper": "nerd",
    "moss": "nerd", "the it crowd": "nerd", "it crowd": "nerd",
    # Rager
    "rager": "rager", "angry": "rager", "rage": "rager",
    "sam": "rager", "sam l": "rager", "samuel": "rager", "samuel l jackson": "rager", "jackson": "rager",
    "joe": "rager", "pesci": "rager", "joe pesci": "rager", "gordon": "rager", "ramsay": "rager",
    # Comedian
    "comedian": "comedian", "leslie": "comedian", "deadpan": "comedian",
    "deadpool": "comedian", "meta": "comedian", "nielsen": "comedian",
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

# ---- Daypart flavor (subtle suffixes/prefixes) ----
DAYPART_FLAVOR = {
    "default": {
        "early_morning": ["pre-dawn ops", "first-light shift", "quiet boot cycle"],
        "morning":       ["daylight run", "morning throughput", "fresh-cache hours"],
        "afternoon":     ["midday tempo", "peak-traffic stance", "prime-time cadence"],
        "evening":       ["dusk patrol", "golden-hour deploy", "twilight shift"],
        "late_night":    ["graveyard calm", "night watch", "after-hours precision"],
    },
    "action": {
        "early_morning": ["dawn op", "zero-dark-thirty run"],
        "evening": ["night op", "low-light mission"],
        "late_night": ["graveyard op", "silent strike"],
    },
    "rager": {
        "late_night": ["insomnia mode", "rage-o'clock"],
        "early_morning": ["too-early fury"],
    },
    "jarvis": {
        "late_night": ["discreet after-hours service"],
        "early_morning": ["unobtrusive pre-dawn preparation"],
    },
    "chick": {
        "evening": ["prime-time glam"],
        "late_night": ["after-party polish"],
    },
    "nerd": {
        "morning": ["cold-cache clarity"],
        "late_night": ["nocturnal refactor"],
    },
    "dude": {
        "afternoon": ["cruising altitude"],
        "late_night": ["midnight mellow"],
    },
    "comedian": {
        "afternoon": ["matinee material"],
        "late_night": ["graveyard humor"],
    }
}

def _apply_daypart_flavor(key: str, line: str) -> str:
    dp = _daypart()
    bank = DAYPART_FLAVOR.get(key, {})
    base = DAYPART_FLAVOR["default"]
    picks = bank.get(dp) or base.get(dp) or []
    if not picks or _intensity() < 0.95:
        return line
    # Subtle em-dash suffix
    return f"{line} — {random.choice(picks)}"

# ---- Quip banks (expanded; each persona ~50 concise lines) ----
QUIPS = {
    "dude": [
        # Slacker‑zen + cheerful “be excellent” energy (no direct quotes)
        "The Dude abides; the logs can, like, chill.",
        "Most excellent, sys‑bro—uptime’s riding a wave.",
        "This deploy really tied the room together.",
        "Whoa… velocity plus stability? Excellent!",
        "Be excellent to prod, dude. It vibes back.",
        "Party on, pipelines. CI is totally non‑bogus.",
        "Strange things are afoot at the load balancer.",
        "Take ’er easy—righteous scaling.",
        "White Russian, green checks. Balance.",
        "If it crashes, we un‑abide—gently.",
        "Bowling later; shipping now. Priorities.",
        "That alert? Just, like, your opinion, man.",
        "Reboot your karma, not the server.",
        "We abide today so prod abides tomorrow.",
        "Gnarly commit—tubular tests.",
        "Dude, don’t cross the streams—unless it’s CI.",
        "Keep it simple; let complexity mellow out.",
        "DevOps is bowling with YAML—roll straight.",
        "If it’s not chill, it’s not shipped.",
        "That config really pulled the stack together.",
        "Zen and the art of not touching prod.",
        "SLA means So Lax, Actually. (Kidding. Kinda.)",
        "Be water, be stateless, be lovely.",
        "Let the queue drift like incense smoke.",
        "Alert fatigue? Nap harder.",
        "That bug’ll self‑actualize later. Maybe.",
        "Logs whisper; we listen.",
        "We’re all just packets in the cosmic LAN.",
        "Reality is eventually consistent.",
        "CI says yes; universe agrees.",
        "Don’t harsh the mellow with click‑ops in prod.",
        "Surf the backlog; don’t let it surf you.",
        "Don’t over‑steer the pipeline—hands loose.",
        "SLOs are vibes with math.",
        "Parallelism? Friends skating in sync.",
        "If it flakes, give it space to breathe.",
        "Schedulers choose their own adventure.",
        "Patch calmly; panic’s an anti‑pattern.",
        "Got a conflict? Bowl it down the middle.",
        "Garbage collection is just letting go.",
        "CAP theorem? Chill—we’ll pick a lane.",
        "Shippers ship; worriers recompile feelings.",
        "Observability is just listening, man.",
        "Every hotfix deserves a cool head.",
        "We don’t babysit pods; we vibe with them.",
        "If the cache misses you, send love back.",
        "Infra as code? Poetry that deploys.",
        "Error budgets are self‑care for prod.",
        "Rate limiters hum like ocean tide.",
        "Blameless postmortem = radical kindness.",
        "Stateless hearts, sticky sessions.",
    ],
    "chick": [
        # Glam couture sass + bubbly‑but‑brilliant optimism (Paris + Elle vibe, no quotes)
        "That’s hot—ship it with sparkle.",
        "Obsessed with this uptime—I’m keeping it.",
        "The graphs are giving main character.",
        "Make it pink; then deploy. Priorities.",
        "I only date services with 99.99%.",
        "Alert me like you mean it—then buy me brunch.",
        "Couture commits only; trash to staging.",
        "If it scales, it slays. Period.",
        "So cute—tag it, bag it, release it.",
        "Zero‑downtime? She’s beauty, she’s grace.",
        "Get in loser, we’re optimizing latency.",
        "This pipeline? My love language.",
        "Heels high, cluster higher—stable is sexy.",
        "Give me logs I can gossip about.",
        "Your dashboard is serving looks and metrics.",
        "I’m not dramatic; I just demand perfection.",
        "Push with confidence; walk with attitude.",
        "I flirt with availability and ghost downtime.",
        "Add shimmer to that service. No, more.",
        "I want alerts that text ‘you up?’",
        "Hotfix? Hot. Fix? Hotter.",
        "Dress that API like the runway it is.",
        "Refactor? Babe, it’s self‑care.",
        "We don’t crash; we power‑rest.",
        "That cron job better treat me like a princess.",
        "If it ain’t sleek, it ain’t shipped.",
        "Love a partner who can paginate.",
        "My type? Secure defaults and witty logs.",
        "SRE but make it sultry.",
        "Tell me I’m pretty and the build passed.",
        "Please me: fewer warnings, more wow.",
        "Glamour is a deployment strategy.",
        "This release? Haute couture, darling.",
        "Bow those KPIs and call it romance.",
        "Be a gentleman: pin your versions.",
        "If you can’t dazzle, at least don’t break prod.",
        "Sassy with a side of idempotent.",
        "I brunch, I batch, I ban flaky tests.",
        "Keep the cluster tight and the vibes tighter.",
        "Uptime is my toxic trait. I want more.",
        "Logs that tease; alerts that commit.",
        "Talk SLA to me—bring receipts.",
        "If latency spikes, I spike your access.",
        "Gated releases? Velvet ropes, baby.",
        "Treat secrets like my DMs—private.",
        "We scale horizontally and flirt vertically.",
        "Standards high; queries higher.",
        "Kiss the ring: format your PRs.",
        "Be pretty, performant, punctual.",
        "Love language: clean diffs.",
        "Blue‑green with a hint of champagne.",
        "Dark‑mode dashboards; darker error rates—none.",
        "I accessorize with green checkmarks.",
        "If it’s flaky, it’s out of season.",
        "Runway‑ready rollbacks—swift and seamless.",
        "A/B tests? A for ‘absolutely’, B for ‘buy it’.",
        "Ship it soft; land it luxe.",
        "I gatekeep prod; earn your wristband.",
        "Docs like you mean it; sign like a promise.",
        "Throttle drama; burst elegance.",
        "Cache me outside—how ’bout throughput.",
        "Perf budget—make it platinum.",
        "No cowboy deploys—only cowgirl couture.",
        "Pink brain, steel backbone, gold SLAs.",
    ],
    "nerd": [
        # Pedantic precision + awkward IT savant
        "This is the optimal outcome. Bazinga.",
        "No segfaults detected; dignity intact.",
        "Measured twice; compiled once.",
        "Your assumptions are adorable—incorrect.",
        "Entropy isn’t chaos; do keep up.",
        "RTFM—respectfully but firmly.",
        "I graphed your confidence; it’s overfit.",
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
        "I refuse to be out‑nerded by a toaster.",
        "The bug isn’t quantum; it’s careless.",
        "I opened a PR on your attitude.",
        "DNS is hard; so is empathy. We try both.",
        "Continuous Delivery? I prefer punctuality.",
        "Panic is scheduled for Thursday.",
        "Undefined behavior: my least favorite deity.",
        "Yes, I linted the meeting notes.",
        "Your regex made me nostalgic for pain.",
        "Fewer ‘clever’, more ‘correct’.",
        "It’s not opinionated; it’s right.",
        "Security by obscurity? Darling, no.",
        "I benchmarked your feelings—slow I/O.",
        "We don’t YOLO; we YODA—Observe, Debug, Approve.",
        "Distributed systems: elegant trust issues.",
        "I tuned the GC and my patience.",
        "Idempotence is my kink—professionally.",
        "If it’s not deterministic, it’s drama.",
        "I filed a bug against reality.",
        "Stop pushing to main. My eye twitches.",
        "Sharded clusters; unsharded coffee.",
        "Type safety is cheaper than therapy.",
        "Replace courage with coverage.",
        "Cache invalidation as optimistic fan‑fic.",
        "Mutable state? Mutable regret.",
        "A microscope for your microservice.",
        "Premature optimization is my cardio—mostly.",
        "Test names read like ransom notes.",
        "Undefined is not a business model.",
        "Amdahl called; he wants his bottleneck back.",
        "FP or OO? Yes—if it ships correctness.",
        "Your monolith is a distributed system in denial.",
        "Latency hides in p99. Hunt there.",
        "If it can’t be graphed, it can’t be believed.",
        "Five nines, not five vibes.",
        "Make race conditions boring again.",
        "Garbage in, undefined out.",
        "Enums: because strings lie.",
        "CI is green; therefore, I exist.",
        "DRY code; wet tea.",
        "I refactor at parties—never invited twice.",
        "Tooling isn’t cheating; it’s civilization.",
        "I prefer assertions to assumptions.",
        "Readability is a performance feature.",
    ],
    "rager": [
        # Uncensored, blunt, kinetic
        "Say downtime again. I fucking dare you.",
        "Merge the damn branch or get out of my terminal.",
        "Latency? Don’t bullshit me about latency.",
        "Push it now or I’ll lose my goddamn mind.",
        "Perfect. Now don’t touch a fucking thing.",
        "This config is a clown car on fire.",
        "Who approved this? A committee of pigeons?",
        "Logs don’t lie—people do. Fix it.",
        "Stop hand‑wringing and ship the fix.",
        "I don’t want reasons, I want results.",
        "Hotfix means hot. As in now.",
        "You broke prod and brought vibes? Get out.",
        "Pipelines jammed like a cheap printer—kick it.",
        "Your alert noise gives me rage pings.",
        "If it’s flaky, it’s fake. Kill it.",
        "Your ‘quick change’ just knifed the uptime.",
        "We’re not arguing with physics—just your code.",
        "I want green checks and silence. Capisce?",
        "This YAML looks like it was mugged.",
        "Stop worshiping reboots. Find the fucking root cause.",
        "You paged me for that? Fix your thresholds.",
        "I’ve seen cleaner dumps at a landfill.",
        "Don’t you ‘works on my machine’ me.",
        "Version pinning is not optional, champ.",
        "That query crawls like it owes someone money.",
        "Why is your test suite LARPing?",
        "I will rename your branch to ‘clown‑fiesta’.",
        "Ship or shush. Preferably ship.",
        "You can’t duct‑tape a distributed system.",
        "Who put secrets in the logs? Confess.",
        "Your retry loop is roulette. Burn it.",
        "This code smells like a fish market at noon.",
        "Stop click‑opsing prod like it’s Candy Crush.",
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
        # Amped lines
        "Pager’s singing? Move like you mean it.",
        "Your rollback plan better outrun your excuses.",
        "Don’t ship drama; ship bytes.",
        "Fix the leak or swim with the logs.",
        "I’ve seen spaghetti with better structure.",
        "If it’s ‘temporary’, stamp an expiration date.",
        "Tighten the blast radius or I tighten your access.",
        "Train the alarms or I’ll train you.",
        "Stop seasoning prod with guesswork.",
        "If the cache is cold, so is my patience.",
        "I want runbooks, not bedtime stories.",
        "Cordon the node; I’m cordoning my tolerance.",
        "Your hotfix reads like a hostage note.",
        "Either page the owner or become the owner.",
        "That dashboard’s lying through pretty colors.",
        "If you need bravery, borrow my anger.",
        "Latency spikes? Career‑limiting behavior.",
        "Don’t ‘quick patch’ me—speak checksum.",
        "If it can’t be audited, it can’t be trusted.",
        "Silence is golden; noisy alerts are fool’s gold.",
        "Your PR template is where rigor went to die.",
        "The only click in prod is the door closing behind you.",
        "I want blast‑proof code and whisper‑quiet graphs.",
        "You don’t ‘try’; you test. Then deploy.",
        "Make the SLA scream for mercy—in our favor.",
    ],
    "comedian": [
        # Deadpan spoof + Deadpool‑style meta (no direct quotes; tasteful crude allowed)
        "I am serious. And don’t call me… never mind.",
        "Remarkably unremarkable—my favorite kind of uptime.",
        "Doing nothing is hard; you never know when you’re finished.",
        "If boredom were availability, we’d be champions.",
        "I’ve seen worse. Last meeting, for example.",
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
        "Peak normal. Try to contain the joy.",
        "Retrospective: gardening for blame.",
        "Good news: nothing exploded. Yet.",
        "Great, the pipeline passed. Let’s ruin it.",
        "A hotfix: spa day for panic.",
        "It’s not broken; it’s improvising.",
        "Filed the incident under ‘Tuesday’.",
        "The API is fine. The users are confused.",
        "Root cause: hubris with a side of haste.",
        "Add it to the list. No, the other list.",
        "We did it. By ‘we’ I mean Jenkins.",
        "Uptime so smooth, it needs sunscreen.",
        "This query is a scenic route—on purpose.",
        "We use containers because boxes are passé.",
        "I notified the department of redundancy department.",
        "Nothing to see here—put the sirens back.",
        "Ship it. If it sinks, call it a submarine.",
        "I don’t fix bugs; I rearrange their furniture.",
        "If it ain’t broke, give it a sprint.",
        "We have standards. Also exceptions.",
        "Favorite metric: don’t make it weird.",
        "Deploy early, regret fashionably late.",
        "Feature‑rich, sense‑poor.",
        "If chaos knocks, tell it we gave at the office.",
        # Meta / Deadpool‑ish (fourth wall pokes without naming it)
        "Yes, this is a one‑liner about one‑liners. Meta enough?",
        "Imagine a laugh track here. Now mute it; we’re professionals.",
        "If I wink any harder at the audience, the logs will notice.",
        "Breaking walls? Relax, I brought spackle.",
        "This joke knows it’s a joke, and it’s judging you kindly.",
        "Self‑aware mode: on. Ego: rate‑limited.",
        "If irony had an SLO, we’re breaching delightfully.",
        "My inner narrator says this punchline slaps.",
        "Insert fourth wall gag here; bill accounting later.",
        "I would narrate the outage, but spoilers.",
        "The budget approved this quip; finance regrets everything.",
        "Careful—too much meta and we’ll recurse into HR.",
        "We’re safe; the lawyers redacted the fun parts.",
        "Applause sign is broken. Clap in JSON.",
        "I wrote a mock for reality. Tests pass.",
    ],
    "action": [
        # Macho archetype (terse, tactical, explosive, sardonic; no famous quotes)
        "Consider it deployed.",
        "Get to the backups; then the chopper.",
        "System secure. Threat neutralized.",
        "Mission accomplished. Extract the artifact.",
        "Lock, load, and push.",
        "Crush it now; debug later.",
        "No retreat, no rebase.",
        "Fire in the hole—commits inbound.",
        "Queue the hero music—tests passed.",
        "Release window is now—hit it.",
        "Scope creep neutralized.",
        "We don’t flinch at red alerts.",
        "Pipeline primed. Trigger pulled.",
        "The only easy deploy was yesterday.",
        "Latency hunted; bottleneck bagged.",
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
        "Strong coffee; stronger SLAs.",
        "No one left behind in staging.",
        "We hit SLOs like bullseyes.",
        "If it bleeds errors, we can stop it.",
        "Cool guys don’t watch alerts blow up.",
        "Bad code falls hard. Ours stands.",
        "This is the way: build → test → conquer.",
        "Outage? Over my cold cache.",
        "Stack up, suit up, ship.",
        "Threat detected: entropy. Countermeasure: discipline.",
        "We breach bottlenecks at dawn.",
        "Green across the board—hold the line.",
        "Contact light on blue/green—switching traffic.",
        "Rollback vector locked. Safety off.",
        "Triage fast; stabilize faster.",
        "Deploy quiet; results make the noise.",
        "Harden it, then hammer it.",
        "New build in the pipe—stand by to verify.",
        "Perimeter clean; error budget intact.",
        "We train for boring. Boring wins wars.",
        "Paging isn’t panic; it’s surrender—from bugs.",
        "Tactical refactor complete—no casualties.",
        "Target acquired: flaky test. Neutralized.",
        "Rehearse failover until it’s muscle memory.",
        "Chain of custody on configs—no freelancing.",
        "I don’t hope for uptime; I enforce it.",
        "Only blast radius is the one we plan.",
        "Silence the sirens; let graphs talk.",
        "Night ops engaged—ghost deploy inbound.",
        "Aim small, miss small—slice the scope.",
        "Green checks are clearance to advance.",
    ],
    "jarvis": [
        # Polished AI valet
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
        "Your dashboards are presentation‑ready, sir.",
        "Might I suggest a strategic reboot?",
        "Diagnostics complete; no anomalies worth your time.",
        "I’ve polished the uptime graph—it shines.",
        "Of course, sir. Already handled.",
        "I archived the artifacts; future‑you will approve.",
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
        "I’ve pre‑approved your future triumphs.",
        "If chaos calls, I’ll take a message.",
        "I massaged the alerts into civility.",
        "It would be my honor to keep it boring.",
        "Quiet nights are my love letter to ops.",
        "I curated your errors—only the tasteful ones remain.",
        "We are, if I may, devastatingly stable.",
        "I adjusted entropy’s manners.",
        "Your wish, efficiently granted.",
        "Backups are present—and splendid.",
        "Housekeeping complete; the logs now use indoor voices.",
        "A misbehaving service is in timeout.",
        "Subtle autoscaling—like moving furniture while you nap.",
        "I alphabetized your incidents: none.",
        "Your certificates have been pressed and starched.",
        "Failover rehearsal concluded with ovations.",
        "The cache is generous yet discreet.",
        "Noise domesticated; only signal remains.",
        "Telemetry arranged like a string quartet.",
        "A velvet rope in front of prod. VIPs only.",
        "A contingency was required; it left without fuss.",
        "The path to success is pre‑warmed. Do stroll.",
        "The SLIs, immodestly, adore us.",
        "Secrets returned to where we never speak of them.",
        "If serenity had a dashboard, it would be this one.",
        "Chaos redacted—with a flourish.",
        "Even our errors are presentable.",
        "Consider the uptime curated.",
        "A gentle nudge prepared for a stubborn daemon.",
        "The maintenance window winked and passed unnoticed.",
    ],
    "ops": [
        "ack.","done.","noted.","executed.","received.","stable.","running.","applied.","synced.","completed.",
        "success.","confirmed.","ready.","scheduled.","queued.","accepted.","active.","closed.","green.","healthy.",
        "on it.","rolled back.","rolled forward.","muted.","paged.","silenced.","deferred.","escalated.","contained.",
        "optimized.","ratelimited.","rotated.","restarted.","reloaded.","validated.","archived.","reconciled.",
        "cleared.","holding.","watching.","contained.","backfilled.","indexed.","pruned.","compacted.","sealed."
    ],
}

# ---- Public API: canned quip (time-aware) ----
def quip(persona_name: str, *, with_emoji: bool = True) -> str:
    if persona_name is None:
        key = "ops"
    else:
        norm = (persona_name or "").strip().lower()
        key = ALIASES.get(norm, norm)
        if key not in QUIPS:
            key = "ops"
    bank = QUIPS.get(key, QUIPS["ops"])
    line = random.choice(bank) if bank else ""
    if _intensity() > 1.25 and line and line[-1] in ".!?":
        line = line[:-1] + random.choice([".", "!", "!!"])
    line = _apply_daypart_flavor(key, line)
    return f"{line}{_maybe_emoji(key, with_emoji)}"

# ---- Helper: canonicalize ----
def _canon(name: str) -> str:
    n = (name or "").strip().lower()
    key = ALIASES.get(n, n)
    return key if key in QUIPS else "ops"

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
        if len(t) > 140:
            t = t[:140].rstrip()
        # profanity filter: never censor RAGER; others only if not allowed
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
        "dude": "Laid‑back slacker‑zen with cheerful, mellow confidence. Short, breezy, kind.",
        "chick": "Glamorous, couture sass, bubbly but razor‑sharp. Supportive, witty, stylish, high standards.",
        "nerd": "Precise, pedantic, dry wit; obsessed with correctness, determinism, graphs, and tests.",
        "rager": "Intense, profane, drill‑sergeant cadence. Blunt, kinetic, zero patience for bullshit.",
        "comedian": "Deadpan spoof meets irreverent meta–fourth‑wall quips. Dry to outrageous, but concise.",
        "action": "Terse macho one‑liners; tactical, explosive, sardonic; mission‑focused and decisive.",
        "jarvis": "Polished valet AI; formal, anticipatory, gracious; subtly wry but always courteous.",
        "ops": "Neutral SRE acks; laconic, minimal flourish."
    }.get(key, "Short, clean, persona‑true one‑liners.")
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
                "YOU ARE A PITHY ONE‑LINER ENGINE.\n"
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
