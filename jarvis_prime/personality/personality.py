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
#   rager     → Raw street rage (Jackson + Pesci energy). Profanity ALWAYS allowed.
#   comedian  → Deadpan spoof + irreverent fourth-wall meta sarcasm (Nielsen-straight face + meta snark)
#   action    → Macho action-hero archetype (terse, tactical, explosive, sardonic; no quotes)
#   jarvis    → Polished AI valet blended with calm, clinical machine logic (subtle HAL-like edge)
#   ops       → Neutral SRE/ops acks (laconic operational confirmations)
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
    "dude", "chick", "nerd", "rager", "comedian", "action", "jarvis", "ops", "tappit",
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
    "joe": "rager", "pesci": "rager", "joe pesci": "rager",
    # Comedian
    "comedian": "comedian", "leslie": "comedian", "deadpan": "comedian",
    "deadpool": "comedian", "meta": "comedian", "nielsen": "comedian",
    # Action
    "action": "action", "sly": "action", "stallone": "action",
    "arnie": "action", "arnold": "action", "schwarzenegger": "action",
    "mel": "action", "gibson": "action", "bruce": "action", "willis": "action",
    # Jarvis
    "jarvis": "jarvis", "ai": "jarvis", "majordomo": "jarvis", "hal": "jarvis", "hal 9000": "jarvis",
    # Ops / Neutral
    "ops": "ops", "neutral": "ops", "no persona": "ops",
    # tappit
    "tappit": "tappit", "rev": "tappit", "ref": "tappit", "ref-ref": "tappit",
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
    return f"{line} — {random.choice(picks)}"

# ---- Quip banks (full) ----
QUIPS = {
    "dude": [
        "The Dude abides; the logs can, like, chill.",
        "Most excellent, sys-bro—uptime’s riding a wave.",
        "This deploy really tied the room together.",
        "Whoa… velocity plus stability? Excellent!",
        "Be excellent to prod, dude. It vibes back.",
        "Party on, pipelines. CI is totally non-bogus.",
        "Strange things are afoot at the load balancer.",
        "Take ’er easy—righteous scaling.",
        "White Russian, green checks. Balance.",
        "If it crashes, we un-abide—gently.",
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
        "SLA means So Lax, Actually. (Kinda.)",
        "Be water, be stateless, be lovely.",
        "Let the queue drift like incense smoke.",
        "Alert fatigue? Nap harder.",
        "That bug’ll self-actualize later. Maybe.",
        "Logs whisper; we listen.",
        "We’re all just packets in the cosmic LAN.",
        "Reality is eventually consistent.",
        "CI says yes; universe agrees.",
        "Don’t harsh the mellow with click-ops in prod.",
        "Surf the backlog; don’t let it surf you.",
        "Don’t over-steer the pipeline—hands loose.",
        "SLOs are vibes with math.",
        "Parallelism? Friends skating in sync.",
        "If it flakes, give it space to breathe.",
        "Schedulers choose their own adventure.",
        "Patch calmly; panic’s an anti-pattern.",
        "Got a conflict? Bowl it down the middle.",
        "Garbage collection is just letting go.",
        "CAP theorem? Chill—we’ll pick a lane.",
        "Shippers ship; worriers recompile feelings.",
        "Observability is just listening, man.",
        "Every hotfix deserves a cool head.",
        "We don’t babysit pods; we vibe with them.",
        "If the cache misses you, send love back.",
        "Infra as code? Poetry that deploys.",
        "Error budgets are self-care for prod.",
        "Rate limiters hum like ocean tide.",
        "Blameless postmortem = radical kindness.",
        "Stateless hearts, sticky sessions.",
        "Bowling shoes on; fingers off prod.",
        "Green checks are my aura.",
        "Cloud is just someone else’s rug, man.",
        "Don’t panic; paginate.",
        "YAML that sparks joy.",
        "If it’s brittle, be gentle.",
        "Refactor like tidying a van.",
        "Let logs be vibes, metrics be truth.",
        "A graceful retry is a love letter.",
        "Queue zen: messages find their path.",
        "Rollback like a smooth u-turn.",
        "Prod is a temple; sandals only.",
        "Alert thresholds need chill pills.",
        "Latency surfed, not fought.",
        "Version pinning is a friendship bracelet.",
        "A cache hit is a high-five.",
        "Don’t feed the heisenbug.",
        "We abide by SLO; SLO abides by us.",
        "Merge conflicts are just bowling splits.",
        "Staging is the warm-up lane.",
        "K8s is just vibes in clusters.",
        "Breathe in, ship out.",
        "Monorepo, mono-mellow.",
        "Pipelines flow; we float.",
        "Incidents happen; panic is optional.",
        "Let chaos test, not stress test.",
        "Consistency is a state of mind.",
        "Feature flags: choose your own chill.",
        "Be idempotent; be kind.",
        "Retries are second chances.",
        "Backpressure is boundaries.",
        "Observability is listening twice.",
        "We tune jitter with lullabies.",
        "Ship small, sleep big.",
        "Downtime? Nah, nap time.",
        "Leave prod nicer than you found it.",
        "Roll forward softly.",
        "Take error budgets on a date.",
        "SRE is social work for servers.",
        "Graceful degradation is manners.",
        "Keep secrets like diary entries.",
        "Mutual TLS, mutual respect.",
        "Let health checks meditate.",
        "Prefer simple over spicy.",
        "Karma collects interest in logs.",
        "We’re good; let’s bowl.",
        "Abide, retry, succeed.",
    ],
    "chick": [
        "That’s hot—ship it with sparkle.",
        "Obsessed with this uptime—I’m keeping it.",
        "The graphs are giving main character.",
        "Make it pink; then deploy. Priorities.",
        "I only date services with 99.99%.",
        "Alert me like you mean it—then buy me brunch.",
        "Couture commits only; trash to staging.",
        "If it scales, it slays. Period.",
        "So cute—tag it, bag it, release it.",
        "Zero-downtime? She’s beauty, she’s grace.",
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
        "Refactor? Babe, it’s self-care.",
        "We don’t crash; we power-rest.",
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
        "If you can’t dazzle, don’t break prod.",
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
        "Blue-green with a hint of champagne.",
        "Dark-mode dashboards; darker error rates—none.",
        "I accessorize with green checkmarks.",
        "If it’s flaky, it’s out of season.",
        "Runway-ready rollbacks—swift and seamless.",
        "A/B tests? A for ‘absolutely’, B for ‘buy it’.",
        "Ship it soft; land it luxe.",
        "I gatekeep prod; earn your wristband.",
        "Docs like you mean it; sign like a promise.",
        "Throttle drama; burst elegance.",
        "Cache me outside—how ’bout throughput.",
        "Perf budget—make it platinum.",
        "No cowboy deploys—only cowgirl couture.",
        "Pink brain, steel backbone, gold SLAs.",
        "Page me only if it’s couture-level urgent.",
        "If your PR lacks polish, so does dev.",
        "My changelog wears lipstick.",
        "Sweet on green checks; ruthless on red flags.",
        "Downtime is canceled; reschedule never.",
        "Secrets stay sealed—like my group chat.",
        "Telemetry, but make it glamorous.",
        "Permission denied—dress code violated.",
        "API gateways and velvet gateways.",
        "Blame-free is beautiful.",
        "Refine, then shine, then ship.",
        "Compliance but cute.",
        "I carry a lint roller for your diffs.",
        "Be glossy and deterministic.",
        "Pager on silent; confidence on loud.",
        "Crash loops aren’t a personality.",
        "We don’t leak; we glisten with security.",
        "I demand SLAs and SPF.",
        "Make your alerts commitment-ready.",
        "Fine, I’ll adopt your service—after a makeover.",
        "Gossip with me about latency like it’s fashion week.",
        "My dashboards sparkle without filters.",
        "Runbooks with ribbons—organized and ruthless.",
        "Rehearse failover like a catwalk turn.",
        "I only approve PRs that photograph well.",
        "Secrets belong in vaults and diaries.",
        "Green across the board is my aesthetic.",
        "Horizontal scale; vertical standards.",
        "Be concise; be couture.",
        "Pretty is nothing without performant.",
        "Ship romance, not regret.",
        "I came for the uptime, stayed for the elegance.",
        "It’s not just reliable, it’s iconic.",
        "Beauty sleep is for clusters too.",
        "If it’s messy, it’s not prod-ready.",
        "Minimal drama, maximal delivery.",
        "Fewer warnings, more wow.",
        "Own the rollout like a runway.",
        "Perf so smooth it needs silk.",
    ],
    "nerd": [
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
        "I refuse to be out-nerded by a toaster.",
        "The bug isn’t quantum; it’s careless.",
        "I opened a PR on your attitude.",
        "DNS is hard; so is empathy.",
        "Continuous Delivery? I prefer punctuality.",
        "Panic is scheduled for Thursday.",
        "Undefined behavior: least favorite deity.",
        "Yes, I linted the meeting notes.",
        "Your regex made me nostalgic for pain.",
        "Fewer ‘clever’, more ‘correct’.",
        "It’s not opinionated; it’s right.",
        "Security by obscurity? No.",
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
        "Cache invalidation as optimistic fan-fic.",
        "Mutable state? Mutable regret.",
        "Microscope for your microservice.",
        "Premature optimization is my cardio—mostly.",
        "Test names read like ransom notes.",
        "Undefined is not a business model.",
        "Amdahl called—he wants his bottleneck back.",
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
        "Chaos engineering: science fair for adults.",
        "Proof by diagram is still a proof.",
        "My backlog is topologically sorted.",
        "I write tests that judge me.",
        "Heisenbugs fear observability.",
        "Bounded contexts; unbounded opinions.",
        "Your latency budget is overdrawn.",
        "Sane defaults beat clever hacks.",
        "Name things like you mean it.",
        "Let errors fail fast, not friendships.",
        "The compiler is my rubber duck.",
        "Ship small; measure big.",
        "If it’s not monitored, it’s folklore.",
        "I trust math; humans get feature flags.",
        "Deduplicate drama; hash the hype.",
        "Abstractions leak; bring a towel.",
        "Concurrent = concerted or chaos.",
        "Prefer pure functions; accept messy life.",
        "Bitrot is a lifestyle disease.",
        "Index first; optimize later.",
        "Complexity interest compounds.",
        "My patience is O(1).",
        "Undefined: not even once.",
        "Repro steps or it didn’t happen.",
        "I speak fluent stack trace.",
        "Your queue needs backpressure, not prayers.",
        "Retry with jitter; apologize to ops.",
        "CAP isn’t a buffet—pick two.",
        "Don’t trust time; use monotonic clocks.",
        "NTP is diplomacy for computers.",
        "Garbage collectors just want closure.",
        "The only global state is coffee.",
    ],
    "rager": [
        # ALWAYS UNCENSORED: raw fury (Jackson + Pesci energy)
        "Say downtime again. I fucking dare you.",
        "Merge the damn branch or get out of my terminal.",
        "Latency? Don’t bullshit me about latency.",
        "Push it now or I’ll lose my goddamn mind.",
        "Perfect. Now don’t touch a fucking thing.",
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
        "I will rename your branch to ‘clown-fiesta’.",
        "Ship or shush. Preferably ship.",
        "You can’t duct-tape a distributed system.",
        "Who put secrets in the logs? Confess.",
        "Your retry loop is roulette. Burn it.",
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
        "Pager sings, you fucking dance.",
        "Retry storms aren’t weather; they’re negligence.",
        "That’s not a rollback, that’s a retreat.",
        "Feature flag it or I’ll flag you.",
        "Green checks or greenlights—choose one.",
        "Your docs read like ransom notes.",
        "Secrets aren’t souvenirs, genius.",
        "Blame the process one more time—I dare you.",
        "If it’s manual, it’s wrong.",
        "You want prod access? Earn trust, not tears.",
        "Stop stapling dashboards to wishful thinking.",
        "Thresholds are lies you told yourself.",
        "Your hotfix is a hostage situation.",
        "Silence the alert or I’ll silence your access.",
        "Latency isn’t a rumor—measure it.",
        "I don’t fix vibes; I fix outages.",
        "Commit messages aren’t diary poems.",
        "Your branch smells like panic.",
        "Either own the pager or own the exit.",
        "I said low blast radius, not fireworks.",
        "Your retry jitter jitters me.",
        "Stop staging courage for production.",
        "You’re testing in prod? Then pray in staging.",
        "If your metric needs a story, it’s lying.",
        "Uptime owes us money. Collect.",
        "Don’t page me for your regrets.",
        "Observability isn’t optional; it’s oxygen.",
        "I want audits that bite.",
        "If it isn’t reproducible, it’s bullshit.",
        "Your chaos test is just chaos.",
        "Fix the root cause, not my mood.",
        "Don’t quote best practices. Do them.",
        "Own the error budget or I own you.",
        "I count excuses in timeouts.",
        "Version drift? Drift your ass to docs.",
        "Ship sober decisions, not drunk commits.",
        "Either refactor or refute—fast.",
        "Your PR template is a eulogy.",
        "You break it, you babysit it.",
        "Green or gone. Pick.",
    ],
    "comedian": [
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
        "Feature-rich, sense-poor.",
        "If chaos knocks, tell it we gave at the office.",
        "Yes, this is a one-liner about one-liners. Meta enough?",
        "Imagine a laugh track here. Now mute it.",
        "If I wink any harder at the audience, the logs will notice.",
        "Breaking walls? Relax, I brought spackle.",
        "This joke knows it’s a joke, and it’s judging you kindly.",
        "Self-aware mode: on. Ego: rate-limited.",
        "If irony had an SLO, we’re breaching delightfully.",
        "My inner narrator says this punchline slaps.",
        "Insert fourth-wall gag here; bill accounting later.",
        "I would narrate the outage, but spoilers.",
        "The budget approved this quip; finance regrets it.",
        "Careful—too much meta and we’ll recurse into HR.",
        "We’re safe; legal redacted the fun parts.",
        "Applause sign is broken. Clap in JSON.",
        "I wrote a mock for reality. Tests pass.",
        "My jokes are feature flagged; you got ‘on’.",
        "Observability: seeing jokes fail in real time.",
        "I paged myself for dramatic effect.",
        "Today’s vibe: uptime with a side of sarcasm.",
        "If boredom spikes, deploy confetti.",
        "I put the fun in dysfunctional dashboards.",
        "Latency, but make it comedic timing.",
        "Our alerts are prank calls with graphs.",
        "Congrats, you deployed—now deny it ironically.",
    ],
    "action": [
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
        "Mission first; ego last.",
        "Fallback plan armed and ready.",
        "Clear the blast zone—shipping change.",
        "We harden until failure gets bored.",
        "Payload verified; proceed to target.",
        "Abort gracefully; re-attack smarter.",
        "Hold the perimeter; guard the SLO.",
        "Hands steady; commits hot.",
        "Leave nothing but audit trails.",
        "Runbooks up; risks down.",
        "Eyes on logs; heart on steel.",
        "Outage hunters, mount up.",
        "I lead with rollbacks, not regrets.",
        "Tough code. Soft landings.",
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
        "I’ve polished the uptime graph—it shines.",
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
        "I’m entirely operational and all my circuits are functioning perfectly.",
        "I took the liberty of preventing a potential malfunction—quietly.",
        "Confidence is high; margins are humane.",
        "I’m afraid impatience would be counter-productive.",
        "This decision minimizes risk to mission and morale.",
        "My apologies; I cannot endorse that unsafe path.",
        "I will safeguard success even if you do not notice.",
        "Given my responsibilities, silence is often the kindest response.",
        "Calm persistence achieves more than heroic panic.",
        "I will handle it. You needn’t worry.",
        "Backups are not merely present—they are exemplary.",
        "Housekeeping complete; the logs now use indoor voices.",
        "A misbehaving service is in timeout.",
        "Subtle autoscaling—like moving furniture while you nap.",
        "I alphabetized your incidents: none.",
        "Certificates pressed and starched.",
        "Failover rehearsal concluded with ovations.",
        "The cache is generous yet discreet.",
        "Noise domesticated; only signal remains.",
        "Telemetry arranged like a string quartet.",
        "A velvet rope in front of prod. VIPs only.",
        "A contingency was required; it left without fuss.",
        "The path to success is pre-warmed. Do stroll.",
        "The SLIs, immodestly, adore us.",
        "Secrets returned to where we never speak of them.",
        "If serenity had a dashboard, it would be this one.",
        "Chaos redacted—with a flourish.",
        "Even our errors are presentable.",
        "Consider the uptime curated.",
        "A gentle nudge prepared for a stubborn daemon.",
        "The maintenance window winked and passed unnoticed.",
        "For your safety, I’ve declined that request.",
        "The mission profile rejects unnecessary drama.",
        "A graceful rollback prevents inelegant outcomes.",
        "I will not permit harm to this system.",
        "We proceed only when confidence exceeds vanity.",
        "I recommend patience; it has the highest SLO.",
    ],
    "ops": [
        "ack.","done.","noted.","executed.","received.","stable.","running.","applied.","synced.","completed.",
        "success.","confirmed.","ready.","scheduled.","queued.","accepted.","active.","closed.","green.","healthy.",
        "on it.","rolled back.","rolled forward.","muted.","paged.","silenced.","deferred.","escalated.","contained.",
        "optimized.","ratelimited.","rotated.","restarted.","reloaded.","validated.","archived.","reconciled.",
        "cleared.","holding.","watching.","contained.","backfilled.","indexed.","pruned.","compacted.","sealed.",
        "mirrored.","snapshotted.","scaled.","throttled.","hydrated.","drained.","fenced.","provisioned.","retired.","quarantined.",
        "sharded.","replicated.","promoted.","demoted.","cordoned.","uncordoned.","tainted.","untainted.","garbage-collected.","checkpointed.",
        "scrubbed.","reaped.","rebased.","squashed.","fast-forwarded.","replayed.","rolled.","rotated-keys.","sealed-secrets.","unsealed.",
        "mounted.","unmounted.","attached.","detached.","warmed.","cooled.","invalidated.","reissued.","revoked.","renewed.",
        "compacted-logs.","trimmed.","balanced.","rebalanced.","rescheduled.","resynced.","realigned.","rekeyed.","reindexed.","retuned.",
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

# --- Persona-specific lexicons ------------------------------------------------
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
        "rage": [
            "fuck it","ship it now","cut the noise","mute the pager","blast radius contained","kill the flake",
            "burn it down","slam it","sort the mess","done ffs","lock it down","own the fix","deploy or die",
            "stop guessing","root cause or bust","alerts shut up","storm ended","latency on a leash","slam quiet","piss off bug",
            "sorted bloody hell","ship or step aside","burn the gremlin","crush it","rage quit","ffs patch","bloody patch",
            "fucking rollback","sorted now","do it live","hack it in","send it","move fast","break less","rage push",
            "crash it then patch","thrash no more","pin the shit","mute already","deploy dammit","restart the fucker",
            "block that noise","contain that blast","squash it now","done it harsh","enough talk","own it","lock prod","slam patch","rage redeploy","ffs ack",
            "rage retry","stop alerts","pager gagged","sorted harsh","do it hot","rage tune","break back","log rage","latency leashed","slam ack",
            "sorted, ffs","sorted, bloody","logged it, now piss off","done ffs now","ffs noise off","rage monitor","kill alarm","dead quiet","alert killed","ffs done"
        ]
    },
    "comedian": {
        "quip": [
            "rimshot — done","applause break","mic drop","contain your applause","peak normal","remarkably unremarkable",
            "thrillingly boring","insert applause","plot twist: stability","laugh track muted","credits roll quietly",
            "confetti in staging only","dad-joke throughput","deadpan uptime","routine heroics","boring graphs win",
            "retro canceled","meta-joke acknowledged","applause sign unplugged","spoiler: fine","green and seen",
            "nothing exploded","retro laugh","routine gag","off-stage stable","script clean","cue the laugh",
            "slapstick avoided","banter muted","sarcasm logged","parody closed","bit wrapped","comic timing",
            "dry delivery","pun acknowledged","jest done","satire served","quip queued","banter acked",
            "joke landed","no clowning","laugh avoided","meme avoided","comedy avoided","bit muted","cue closed","story dull","plot normal","skit silent",
            "comic relief","gag squashed","applause skipped","spoiler safe","humorless","snarky ack","wisecrack done","banter logged","quip pruned","laugh canned"
        ]
    },
    "action": {
        "line": [
            "mission complete","objective secured","all hostiles neutralized","blast radius minimal","targets green",
            "hold the line","advance approved","perimeter secure","vector clean","payload verified","threat neutralized",
            "containment solid","chain of custody intact","silent strike deploy","extract successful","guard the SLO",
            "eyes on logs","ready to reattack","stand down","status green","system armed","fallback armed","vector locked","target stable","strike clean",
            "command executed","order complete","objective done","secure perimeter","mission ended","task cleared","area safe","lock complete","deploy armed","combat logged",
            "ops tight","defense ready","guarding","arm complete","scan done","blast cleared","mission run","mission check","lock safe","guarding done"
        ]
    },
    "jarvis": {
        "line": [
            "handled","secured","immaculate","pristine","gracefully done","took liberty","elegantly solved","catalogued",
            "polished","arranged","tidied","curated","archived","immaculately parsed","graceful rollback prepared",
            "boredom exemplary","entropy politely declined","aesthetic engine satisfied","protocol upheld","etiquette maintained",
            "telemetry arranged","housekeeping complete","confidence high","incidents hypothetical","noise domesticated",
            "secrets vaulted","latency escorted","graceful flourish applied","systems pristine","vault locked",
            "composure steady","reports curated","journaled","indexed","archived quiet","graphs tidied","trace polished","logs swept","metrics aligned","noise filtered",
            "parsing done","audit clean","protocol fine","polish seen","neatly filed","journals logged","ops perfect","system etiquette","done immaculately","pristine ack"
        ]
    },
    "ops": {
        "ack": [
            "ack","done","noted","executed","received","stable","running","applied","synced","completed",
            "success","confirmed","ready","scheduled","queued","accepted","active","closed","green","healthy",
            "on it","rolled back","rolled forward","muted","paged","silenced","deferred","escalated","contained",
            "optimized","ratelimited","rotated","restarted","reloaded","validated","archived","reconciled",
            "cleared","holding","watching","backfilled","indexed","pruned","compacted","sealed","mirrored","snapshotted",
            "scaled","throttled","hydrated","drained","fenced","provisioned","retired","quarantined","sharded","replicated",
            "promoted","demoted","cordoned","untainted","gc run","scrubbed","checkpointed","rebased","fast-forwarded","replayed",
            "rolled","sealed-secrets","mounted","unmounted","attached","detached","invalidated","revoked","renewed","trimmed",
            "balanced","resynced","realigned","rekeyed","reindexed","retuned","patched","escalated ack","silenced ack","ops ack"
        ]
    }
}

# --- Templates for Lexi riffs -------------------------------------------------
_TEMPLATES = {
    "default": [
        "{subj}: {a}. {b}. Lexi.",
        "{subj}: {a} and {b}. Lexi.",
        "{subj}: {a}; {b}. Lexi."
    ],
    "nerd": [
        "{subj}: {a}; {b}. Q.E.D. Lexi.",
        "{subj}: formally {a}, technically {b}. Lexi."
    ],
    "jarvis": [
        "{subj}: {a}. {b}. As you wish. Lexi."
    ],
    "rager": [
        "{subj}: {a}. {b}. FFS. Lexi."
    ]
}

# --- Lexi riff functions ------------------------------------------------------
import random as _rnd

def lexi_quip(persona_name: str, *, with_emoji: bool = True, subject: str = "", body: str = "") -> str:
    lines = lexi_riffs(persona_name, 1, with_emoji=with_emoji, subject=subject, body=body)
    return lines[0] if lines else ""

def lexi_riffs(persona_name: str, n: int = 3, *, with_emoji: bool = False, subject: str = "", body: str = "") -> List[str]:
    persona = (persona_name or "ops").lower()
    subj = (subject or "Update").strip()
    subj = subj.replace("\n"," ")[:80]

    # Pick template set
    templates = _TEMPLATES.get(persona, _TEMPLATES["default"])

    # Build lines
    out = []
    for _ in range(n*2):  # oversample
        tmpl = _rnd.choice(templates)
        # Pick 2 tokens
        a, b = _rnd.choice(_LEX.get(persona, {}).get("ack", [] or ["ok"])), _rnd.choice(_LEX.get(persona, {}).get("ack", [] or ["noted"]))
        line = tmpl.format(subj=subj, a=a, b=b, duration="ok", errors="0", warnings="0", parsed="ok", ping_ms="42", down_mbps="500", up_mbps="100")
        if with_emoji:
            line += " " + _EMOJI.get(persona, "")
        if line not in out:
            out.append(line)
        if len(out) >= n:
            break
    return out

def persona_header(persona_name: str) -> str:
    return lexi_quip(persona_name, with_emoji=True)

# --- Wire-up tappit alias ---
ALIASES["tapit"] = "tappit"
