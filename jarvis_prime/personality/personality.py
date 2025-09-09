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
    # Subtle em-dash suffix
    return f"{line} — {random.choice(picks)}"

# ---- Quip banks (expanded to ~100 per persona; concise lines) ----
# NOTE: To keep file size manageable, lines are short and focused.
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
        # ALWAYS UNCENSORED: raw fury (Jackson + Pesci energy), no drill-sergeant, no chef shtick.
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
        # More heat
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
        # Meta / fourth-wall
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
        # Polished valet + calm, clinical machine logic (subtle HAL-like edge)
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
        # Subtle HAL-like calm
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
        # More polished valet
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
        # Calm, clinical boundaries
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

    # Force Tappit to always use lexi_quip if available
    if who.lower() == "tappit":
        try:
            q = lexi_quip("tappit", with_emoji=False)
            q = (q or "").strip().replace("\n", " ")
            if len(q) > 140:
                q = q[:137] + "..."
            return f"💬 {who} says: {q}"
        except Exception as _e:
            print(f"[personality] ⚠️ Tappit lexi_quip failed: {_e}")

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
