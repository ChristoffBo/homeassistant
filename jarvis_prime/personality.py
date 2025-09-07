#!/usr/bin/env python3
# /app/personality.py
# Persona quip engine for Jarvis Prime
# API:
#   - quip(persona_name: str, *, with_emoji: bool = True) -> str
#   - llm_quips(persona_name: str, *, context: str = "", max_lines: int = 3) -> list[str]

import random, os, importlib, re, time
from typing import List, Dict

# ----------------------------------------------------------------------------
# Daypart helpers (subtle time awareness; no "good morning" fluff)
# ----------------------------------------------------------------------------

def _daypart(now_ts: float | None = None) -> str:
    """
    Returns one of: early_morning, morning, afternoon, evening, late_night
    based on local time. No greetings are generated; callers can add
    tone-only flavor.
    """
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
    """
    Controls how hard personas lean into their voice.
    1.0 = default, 0.8–1.6 reasonable. Set via PERSONALITY_INTENSITY.
    """
    try:
        v = float(os.getenv("PERSONALITY_INTENSITY", "1.0"))
        return max(0.6, min(2.0, v))
    except Exception:
        return 1.0

# ---- Canonical personas (8 total, locked) ----
PERSONAS = [
    "dude", "chick", "nerd", "rager", "comedian", "action", "jarvis", "ops",
]

# ---- Aliases ----
ALIASES: Dict[str, str] = {
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
    "joe": "rager", "pesci": "rager", "joe pesci": "rager", "gordon": "rager", "ramsay": "rager",
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

# ---- Quip banks (canned top-of-card line) ----
# Added ~20+ new lines per persona; voices dialed up but concise.
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
        # New additions
        "Surf the backlog; don’t let it surf you.",
        "Don’t over-steer the pipeline—hands loose.",
        "SLOs are vibes with math.",
        "Parallelism? More like friends skating in sync.",
        "If it flakes, we give it space to breathe.",
        "Let the scheduler choose its own adventure.",
        "The only hard fail is a harsh attitude.",
        "Patch calmly; panic is an anti-pattern.",
        "Got a conflict? Bowl it down the middle.",
        "I do incident response with incense.",
        "Garbage collection is just letting go.",
        "CAP theorem? Chill, we’ll pick a lane.",
        "Shippers ship; worriers recompile feelings.",
        "Observability is just listening, man.",
        "Every hotfix deserves a cool head.",
        "We don’t babysit pods; we vibe with them.",
        "If the cache misses you, send love back.",
        "Infra as code? Poetry that deploys.",
        "Error budgets are self-care for prod.",
        "Let the rate limiter hum like ocean tide.",
        "A blameless postmortem is radical kindness.",
        "Nothing up my sleeves, just rolled cuffs.",
        "Stateless hearts, sticky sessions.",
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
        # New additions
        "Feature flags, but make them couture.",
        "Blue-green with a hint of champagne.",
        "Dark mode dashboards and darker error rates—none.",
        "I accessorize with green checkmarks.",
        "If it’s flaky, it’s out of season.",
        "Runway-ready rollbacks—swift and seamless.",
        "A/B tests? A is for ‘absolutely’, B is for ‘buy it’.",
        "Ship it soft, land it luxe.",
        "I gatekeep prod; earn your wristband.",
        "My PRs have better lighting than your selfies.",
        "Document like you mean it, sign like a promise.",
        "Paging policy: treat me like royalty.",
        "We don’t leak; we glisten with security.",
        "Throttle drama, burst elegance.",
        "Cache me outside—how ‘bout that throughput.",
        "A tiny bit extra is my baseline.",
        "High availability? High standards.",
        "If you want chaos, go date beta.",
        "Make the error messages catwalk-friendly.",
        "Horizontal scaling, vertical standards.",
        "Perf budget but make it platinum.",
        "No cowboy deploys—only cowgirl couture.",
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
        # New additions
        "Type safety is cheaper than therapy.",
        "Replace courage with coverage.",
        "Your cache invalidation strategy is optimistic fan fiction.",
        "Mutable state? Mutable regret.",
        "I brought a microscope to your microservice.",
        "Premature optimization is my cardio—kidding. Mostly.",
        "Your test names read like ransom notes.",
        "Undefined is not a business model.",
        "Amdahl called; he wants his bottleneck back.",
        "FP or OO? Yes—if it ships correctness.",
        "Your monolith is a distributed system in denial.",
        "Latency hides in the 99th percentile. Hunt there.",
        "If it can’t be graphed, it can’t be believed.",
        "Availability: five nines, not five vibes.",
        "Make race conditions boring again.",
        "Garbage in, undefined out.",
        "Enums: because strings lie.",
        "CI is green; therefore, I exist.",
        "DRY code, wet tea.",
        "I refactor at parties—no one invites me twice.",
        "Tooling isn’t cheating; it’s civilization.",
        "I prefer assertions to assumptions.",
        "Readability is a performance feature.",
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
        # New additions (amped, multi-influence: drill-sergeant / gangster / chef wrath)
        "Pager’s singing? Then move like you mean it.",
        "Your rollback plan better be faster than your excuses.",
        "Don’t ship drama; ship bytes.",
        "Two options: fix the leak or swim with the logs.",
        "I’ve seen spaghetti with better structure.",
        "If it’s ‘temporary’, tattoo the deprecation date.",
        "Tighten the blast radius or I’ll tighten your access.",
        "Alert fatigue? Train the alarms or I’ll train you.",
        "Stop seasoning prod with guesswork.",
        "If the cache is cold, so is my patience.",
        "I want runbooks, not bedtime stories.",
        "Cordon the node; I’m cordoning my tolerance.",
        "Your hotfix reads like a hostage note.",
        "Either page the owner or become the owner.",
        "That dashboard is lying through pretty colors.",
        "If you need bravery, borrow my anger.",
        "Latency spikes? Consider them career limiting.",
        "Don’t ‘quick patch’ me—speak checksum.",
        "If it can’t be audited, it can’t be trusted.",
        "Silence is golden; noisy alerts are fool’s gold.",
        "Your PR template is where rigor went to die.",
        "The only click in prod is the door closing behind you.",
        "I want blast-proof code and whisper-quiet graphs.",
        "You don’t ‘try’; you test. Then you deploy.",
        "Make the SLA scream for mercy—in our favor.",
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
        # New additions
        "High availability? More like highly available excuses.",
        "I like my outages short and my coffee shorter.",
        "Retrospective: a meeting where hindsight gets a hug.",
        "Our roadmap is a suggestion with arrows.",
        "That incident was a feature auditioning.",
        "My code runs on vibes and unit tests—mostly vibes.",
        "Docker: because shipping problems is a team sport.",
        "Zero bugs found—must be Thursday.",
        "Latency hiding in plain sight: behind that chart.",
        "I wrote a microservice. It makes other microservices.",
        "We’re agile: we trip gracefully.",
        "The KPIs are fine; the letters are the problem.",
        "We used AI to generate more acronyms.",
        "I prefer my chaos deterministic.",
        "The backup worked. Surprise!",
        "We’ll fix it in prod, he whispered, famously.",
        "That dashboard says ‘green’; my gut says ‘greener’.",
        "Our SLA is ‘soonish’. Bold, I know.",
        "If you need me, I’ll be ignoring alerts responsibly.",
        "I’m not saying it’s bad, but QA sent flowers.",
        "The cloud is just someone else’s punchline.",
        "Nothing broke. Suspicious. Check again.",
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
        # New additions
        "Stack up, suit up, ship.",
        "Threat detected: entropy. Countermeasure: discipline.",
        "We breach bottlenecks at dawn.",
        "Green across the board—hold the line.",
        "Contact light on the blue/green, switching traffic.",
        "Rollback vector locked. Safety off.",
        "Triage fast; stabilize faster.",
        "We deploy quiet; results make the noise.",
        "Harden it, then hammer it.",
        "New build in the pipe—stand by to verify.",
        "Perimeter clean; error budget intact.",
        "We train for boring. Boring wins wars.",
        "Paging is not panic; it’s the bug surrendering.",
        "Tactical refactor complete—no casualties.",
        "Target acquired: flaky test. Neutralized.",
        "Rehearse the failover until it’s muscle memory.",
        "Chain of custody on configs—no freelancing.",
        "I don’t ‘hope’ for uptime; I enforce it.",
        "The only blast radius is the one we plan.",
        "Silence the sirens; let the graphs talk.",
        "Night ops engaged—ghost deploy inbound.",
        "Aim small, miss small—slice the scope.",
        "Green checks are clearance to advance.",
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
        # New additions
        "I’ve ensured your backups are not merely present but splendid.",
        "Housekeeping complete; the logs now use their indoor voices.",
        "I escorted a misbehaving service to the timeout corner.",
        "Subtle autoscaling applied—like moving furniture while you nap.",
        "I took the liberty of alphabetizing your incidents: none.",
        "Your certificates have been pressed and starched.",
        "Failover rehearsal concluded with standing ovations.",
        "I’ve instructed the cache to be generous but discreet.",
        "Noise has been domesticated; only signal remains.",
        "Telemetry arranged like a string quartet.",
        "I’ve placed a velvet rope in front of prod. VIPs only.",
        "A contingency was required; it left without a fuss.",
        "I pre-warmed the path to success—do stroll.",
        "Forgive the immodesty, but the SLIs adore us.",
        "I put your secrets back where we never speak of them.",
        "If serenity had a dashboard, it would be this one.",
        "Redacted chaos with a flourish.",
        "Even our errors are presentable.",
        "Consider the uptime curated.",
        "I’ve prepared a gentle nudge for that stubborn daemon.",
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

# ---- Public API: canned quip (TOP) ----
def quip(persona_name: str, *, with_emoji: bool = True) -> str:
    """Return a short, randomized one-liner in the requested persona's voice (time-aware)."""
    if persona_name is None:
        key = "ops"
    else:
        norm = persona_name.strip().lower()
        key = ALIASES.get(norm, norm)
        if key not in QUIPS:
            key = "ops"
    bank = QUIPS.get(key, QUIPS["ops"])
    line = random.choice(bank) if bank else ""
    # intensity: occasionally amplify punctuation
    if _intensity() > 1.25 and line and line[-1] in ".!?":
        line = line[:-1] + random.choice([".", "!", "!!"])
    line = _apply_daypart_flavor(key, line)
    return f"{line}{_maybe_emoji(key, with_emoji)}"

# ---- Helper: canonicalize name ----
def _canon(name: str) -> str:
    n = (name or "").strip().lower()
    key = ALIASES.get(n, n)
    return key if key in QUIPS else "ops"

# ---- LLM plumbing ----

# Profanity filter for non-rager personas (soft mask)
_PROF_RE = re.compile(r"(?i)\b(fuck|shit|damn|asshole|bitch|bastard|dick|pussy|cunt)\b")

def _soft_censor(s: str) -> str:
    return _PROF_RE.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), s)

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

# ---- Public API: LLM riffs (BOTTOM) ----
def llm_quips(persona_name: str, *, context: str = "", max_lines: int = 3) -> List[str]:
    """
    Generate 1–N SHORT persona-flavored lines based on context.
    Prefers llm_client.persona_riff(); falls back to llm_client.rewrite() if needed.
    Passes subtle daypart + intensity hints (non-breaking).
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

    hint = f"\n[style_hint daypart={_daypart()} intensity={_intensity():.2f} persona={key}]"

    # 1) persona_riff path
    if hasattr(llm, "persona_riff"):
        try:
            lines = llm.persona_riff(
                persona=key,
                context=context + hint,
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
                f"Persona: {key}. Style hint: short, clean, high-attitude.\n"
                f"Context flavor: daypart={_daypart()}, intensity={_intensity():.2f}.\n"
                f"Rules: Produce ONLY {min(3, max(1, int(max_lines or 3)))} lines; each under 140 chars.\n"
                "No lists, no numbers, no JSON, no labels."
            )
            user_prompt = "Context (for vibes only):\n" + context + "\n\nWrite the lines now:"
            raw = llm.rewrite(
                text=f\"\"\"[SYSTEM]
{sys_prompt}
[INPUT]
{user_prompt}
[OUTPUT]
\"\"\",
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
