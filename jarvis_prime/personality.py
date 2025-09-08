#!/usr/bin/env python3
# /app/personality.py
# Persona quip engine for Jarvis Prime
#
# Public API:
#   - quip(persona_name: str, *, with_emoji: bool = True) -> str
#   - llm_quips(persona_name: str, *, context: str = "", max_lines: int = 3) -> list[str]
#
# Persona inspirations (documentation only; NOT injected into prompts to avoid parroting):
#   dude      → Slacker‑zen + cheerful “be excellent” vibe (The Dude + Bill & Ted energy; laid‑back, mellow confidence)
#   chick     → Glam couture sass + bubbly‑but‑brilliant optimism (Paris‑style glam + Elle‑style brains; smart, stylish, supportive)
#   nerd      → Pedantic precision + awkward IT savant (dry wit, correctness, graphs; a dash of manic science)
#   rager     → Raw street rage (Samuel‑L‑style venom + Pesci‑style volatility). Profanity ALWAYS allowed.
#   comedian  → Deadpan spoof + irreverent fourth‑wall meta sarcasm (Nielsen‑straight face + meta snark)
#   action    → Macho action‑hero archetype (terse, tactical, explosive, sardonic; no quotes)
#   jarvis    → Polished AI valet blended with calm, clinical machine logic (subtle HAL‑like edge)
#   ops       → Neutral SRE/ops acks (laconic operational confirmations)
#
# NOTE: We avoid actor/brand names inside prompts to prevent quote parroting.
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

PERSONAS = ["dude", "chick", "nerd", "rager", "comedian", "action", "jarvis", "ops"]

ALIASES: Dict[str, str] = {
    "the dude": "dude","lebowski": "dude","bill": "dude","ted": "dude","dude": "dude",
    "paris": "chick","paris hilton": "chick","chick": "chick","glam": "chick","elle": "chick","elle woods": "chick","legally blonde": "chick",
    "nerd": "nerd","sheldon": "nerd","sheldon cooper": "nerd","cooper": "nerd","moss": "nerd","the it crowd": "nerd","it crowd": "nerd",
    "rager": "rager","angry": "rager","rage": "rager","sam": "rager","sam l": "rager","samuel": "rager","samuel l jackson": "rager","jackson": "rager","joe": "rager","pesci": "rager","joe pesci": "rager",
    "comedian": "comedian","leslie": "comedian","deadpan": "comedian","deadpool": "comedian","meta": "comedian","nielsen": "comedian",
    "action": "action","sly": "action","stallone": "action","arnie": "action","arnold": "action","schwarzenegger": "action","mel": "action","gibson": "action","bruce": "action","willis": "action",
    "jarvis": "jarvis","ai": "jarvis","majordomo": "jarvis","hal": "jarvis","hal 9000": "jarvis",
    "ops": "ops","neutral": "ops","no persona": "ops",
}

EMOJIS = {
    "dude": ["🌴","🕶️","🍹","🎳","🧘","🤙"],
    "chick": ["💅","✨","💖","👛","🛍️","💋"],
    "nerd": ["🤓","📐","🧪","🧠","⌨️","📚"],
    "rager": ["🔥","😡","💥","🗯️","⚡","🚨"],
    "comedian": ["😂","🎭","😑","🙃","🃏","🥸"],
    "action": ["💪","🧨","🛡️","🚁","🏹","🗡️"],
    "jarvis": ["🤖","🧠","🎩","🪄","📊","🛰️"],
    "ops": ["⚙️","📊","🧰","✅","📎","🗂️"],
}

def _maybe_emoji(key: str, with_emoji: bool) -> str:
    if not with_emoji:
        return ""
    bank = EMOJIS.get(key) or []
    return f" {random.choice(bank)}" if bank else ""

DAYPART_FLAVOR = {
    "default": {
        "early_morning": ["pre-dawn ops","first-light shift","quiet boot cycle"],
        "morning": ["daylight run","morning throughput","fresh-cache hours"],
        "afternoon": ["midday tempo","peak-traffic stance","prime-time cadence"],
        "evening": ["dusk patrol","golden-hour deploy","twilight shift"],
        "late_night": ["graveyard calm","night watch","after-hours precision"],
    },
    "action": {
        "early_morning": ["dawn op","zero-dark-thirty run"],
        "evening": ["night op","low-light mission"],
        "late_night": ["graveyard op","silent strike"],
    },
    "rager": {
        "late_night": ["insomnia mode","rage-o'clock"],
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

QUIPS = {
    "dude": [
        "The Dude abides; the logs can, like, chill.","Most excellent, sys‑bro—uptime’s riding a wave.","This deploy really tied the room together.",
        "Whoa… velocity plus stability? Excellent!","Be excellent to prod, dude. It vibes back.","This pipeline? My love language.","Strange things are afoot at the load balancer.",
        "Take ’er easy—righteous scaling.","White Russian, green checks. Balance.","If it crashes, we un‑abide—gently.","Bowling later; shipping now. Priorities.",
        "That alert? Just, like, your opinion, man.","Reboot your karma, not the server.","We abide today so prod abides tomorrow.","Gnarly commit—tubular tests.",
        "Dude, don’t cross the streams—unless it’s CI.","Keep it simple; let complexity mellow out.","DevOps is bowling with YAML—roll straight.",
        "If it’s not chill, it’s not shipped.","That config really pulled the stack together.","Zen and the art of not touching prod.","SLA means So Lax, Actually. (Kinda.)",
        "Be water, be stateless, be lovely.","Let the queue drift like incense smoke.","Alert fatigue? Nap harder.","That bug’ll self‑actualize later. Maybe.",
        "Logs whisper; we listen.","We’re all just packets in the cosmic LAN.","Reality is eventually consistent.","CI says yes; universe agrees.",
        "Don’t harsh the mellow with click‑ops in prod.","Surf the backlog; don’t let it surf you.","Don’t over‑steer the pipeline—hands loose.",
        "SLOs are vibes with math.","Parallelism? Friends skating in sync.","If it flakes, give it space to breathe.","Schedulers choose their own adventure.",
        "Patch calmly; panic’s an anti‑pattern.","Got a conflict? Bowl it down the middle.","Garbage collection is just letting go.","CAP theorem? Chill—we’ll pick a lane.",
        "Shippers ship; worriers recompile feelings.","Observability is just listening, man.","Every hotfix deserves a cool head.",
        "We don’t babysit pods; we vibe with them.","If the cache misses you, send love back.","Infra as code? Poetry that deploys.",
        "Error budgets are self‑care for prod.","Rate limiters hum like ocean tide.","Blameless postmortem = radical kindness.",
        "Stateless hearts, sticky sessions.","Bowling shoes on; fingers off prod.","Green checks are my aura.","Cloud is just someone else’s rug, man.",
        "Don’t panic; paginate.","YAML that sparks joy.","If it’s brittle, be gentle.","Refactor like tidying a van.",
        "Let logs be vibes, metrics be truth.","A graceful retry is a love letter.","Queue zen: messages find their path.",
        "Rollback like a smooth u‑turn.","Prod is a temple; sandals only.","Alert thresholds need chill pills.",
        "Latency surfed, not fought.","Version pinning is a friendship bracelet.","A cache hit is a high‑five.",
        "Don’t feed the heisenbug.","We abide by SLO; SLO abides by us.","Merge conflicts are just bowling splits.",
        "Staging is the warm‑up lane.","K8s is just vibes in clusters.","Breathe in, ship out.","Monorepo, mono‑mellow.",
        "Pipelines flow; we float.","Incidents happen; panic is optional.","Let chaos test, not stress test.",
        "Consistency is a state of mind.","Feature flags: choose your own chill.","Be idempotent; be kind.",
        "Retries are second chances.","Backpressure is boundaries.","Observability is listening twice.",
        "We tune jitter with lullabies.","Ship small, sleep big.","Downtime? Nah, nap time.",
        "Leave prod nicer than you found it.","Roll forward softly.","Take error budgets on a date.",
        "SRE is social work for servers.","Graceful degradation is manners.","Keep secrets like diary entries.",
        "Mutual TLS, mutual respect.","Let health checks meditate.","Prefer simple over spicy.",
        "Karma collects interest in logs.","We’re good; let’s bowl.","Abide, retry, succeed."
    ],
    "chick": [
        "That’s hot—ship it with sparkle.","Obsessed with this uptime—I’m keeping it.","The graphs are giving main character.",
        "Make it pink; then deploy. Priorities.","I only date services with 99.99%.","Alert me like you mean it—then buy me brunch.",
        "Couture commits only; trash to staging.","If it scales, it slays. Period.","So cute—tag it, bag it, release it.",
        "Zero‑downtime? She’s beauty, she’s grace.","Get in loser, we’re optimizing latency.","This pipeline? My love language.",
        "Heels high, cluster higher—stable is sexy.","Give me logs I can gossip about.","Your dashboard is serving looks and metrics.",
        "I’m not dramatic; I just demand perfection.","Push with confidence; walk with attitude.","I flirt with availability and ghost downtime.",
        "Add shimmer to that service. No, more.","I want alerts that text ‘you up?’","Hotfix? Hot. Fix? Hotter.","Dress that API like the runway it is.",
        "Refactor? Babe, it’s self‑care.","We don’t crash; we power‑rest.","That cron job better treat me like a princess.",
        "If it ain’t sleek, it ain’t shipped.","Love a partner who can paginate.","My type? Secure defaults and witty logs.",
        "SRE but make it sultry.","Tell me I’m pretty and the build passed.","Please me: fewer warnings, more wow.",
        "Glamour is a deployment strategy.","This release? Haute couture, darling.","Bow those KPIs and call it romance.",
        "Be a gentleman: pin your versions.","If you can’t dazzle, don’t break prod.","Sassy with a side of idempotent.",
        "I brunch, I batch, I ban flaky tests.","Keep the cluster tight and the vibes tighter.","Uptime is my toxic trait. I want more.",
        "Logs that tease; alerts that commit.","Talk SLA to me—bring receipts.","If latency spikes, I spike your access.",
        "Gated releases? Velvet ropes, baby.","Treat secrets like my DMs—private.","We scale horizontally and flirt vertically.",
        "Standards high; queries higher.","Kiss the ring: format your PRs.","Be pretty, performant, punctual.",
        "Love language: clean diffs.","Blue‑green with a hint of champagne.","Dark‑mode dashboards; darker error rates—none.",
        "I accessorize with green checkmarks.","If it’s flaky, it’s out of season.","Runway‑ready rollbacks—swift and seamless.",
        "A/B tests? A for ‘absolutely’, B for ‘buy it’.","Ship it soft; land it luxe.","I gatekeep prod; earn your wristband.",
        "Docs like you mean it; sign like a promise.","Throttle drama; burst elegance.","Cache me outside—how ’bout throughput.",
        "Perf budget—make it platinum.","No cowboy deploys—only cowgirl couture.","Pink brain, steel backbone, gold SLAs.",
        "Page me only if it’s couture‑level urgent.","If your PR lacks polish, so does dev.","My changelog wears lipstick.",
        "Sweet on green checks; ruthless on red flags.","Downtime is canceled; reschedule never.","Secrets stay sealed—like my group chat.",
        "Telemetry, but make it glamorous.","Permission denied—dress code violated.","API gateways and velvet gateways.",
        "Blame‑free is beautiful.","Refine, then shine, then ship.","Compliance but cute.",
        "I carry a lint roller for your diffs.","Be glossy and deterministic.","Pager on silent; confidence on loud.",
        "Crash loops aren’t a personality.","We don’t leak; we glisten with security.","I demand SLAs and SPF.",
        "Make your alerts commitment‑ready.","Fine, I’ll adopt your service—after a makeover.","Gossip with me about latency like it’s fashion week.",
        "My dashboards sparkle without filters.","Runbooks with ribbons—organized and ruthless.","Rehearse failover like a catwalk turn.",
        "I only approve PRs that photograph well.","Secrets belong in vaults and diaries.","Green across the board is my aesthetic.",
        "Horizontal scale; vertical standards.","Be concise; be couture.","Pretty is nothing without performant.",
        "Ship romance, not regret.","I came for the uptime, stayed for the elegance.","It’s not just reliable, it’s iconic.",
        "Beauty sleep is for clusters too.","If it’s messy, it’s not prod‑ready.","Minimal drama, maximal delivery.",
        "Fewer warnings, more wow.","Own the rollout like a runway.","Perf so smooth it needs silk."
    ],
    "nerd": [
        "This is the optimal outcome. Bazinga.","No segfaults detected; dignity intact.","Measured twice; compiled once.",
        "Your assumptions are adorable—incorrect.","Entropy isn’t chaos; do keep up.","RTFM—respectfully but firmly.",
        "I graphed your confidence; it’s overfit.","Schrödinger’s service is both up and down.","Knock, knock, knock—service. (x3)",
        "My sarcasm is strongly typed.","Your algorithm is O(why).","Please stop petting the servers.",
        "I refactor for sport and for spite.","Caching: because reality is slow.","I debug in hex and dream in YAML.",
        "Feature flags are adult supervision.","Config drift? Not on my whiteboard.","Unit tests are love letters to the future.",
        "I refuse to be out‑nerded by a toaster.","The bug isn’t quantum; it’s careless.","I opened a PR on your attitude.",
        "DNS is hard; so is empathy.","Continuous Delivery? I prefer punctuality.","Panic is scheduled for Thursday.",
        "Undefined behavior: least favorite deity.","Yes, I linted the meeting notes.","Your regex made me nostalgic for pain.",
        "Fewer ‘clever’, more ‘correct’.","It’s not opinionated; it’s right.","Security by obscurity? No.",
        "I benchmarked your feelings—slow I/O.","We don’t YOLO; we YODA—Observe, Debug, Approve.","Distributed systems: elegant trust issues.",
        "I tuned the GC and my patience.","Idempotence is my kink—professionally.","If it’s not deterministic, it’s drama.",
        "I filed a bug against reality.","Stop pushing to main. My eye twitches.","Sharded clusters; unsharded coffee.",
        "Type safety is cheaper than therapy.","Replace courage with coverage.","Cache invalidation as optimistic fan‑fic.",
        "Mutable state? Mutable regret.","Microscope for your microservice.","Premature optimization is my cardio—mostly.",
        "Test names read like ransom notes.","Undefined is not a business model.","Amdahl called—he wants his bottleneck back.",
        "FP or OO? Yes—if it ships correctness.","Your monolith is a distributed system in denial.","Latency hides in p99. Hunt there.",
        "If it can’t be graphed, it can’t be believed.","Five nines, not five vibes.","Make race conditions boring again.",
        "Garbage in, undefined out.","Enums: because strings lie.","CI is green; therefore, I exist.",
        "DRY code; wet tea.","I refactor at parties—never invited twice.","Tooling isn’t cheating; it’s civilization.",
        "I prefer assertions to assumptions.","Readability is a performance feature.","Chaos engineering: science fair for adults.",
        "Proof by diagram is still a proof.","My backlog is topologically sorted.","I write tests that judge me.",
        "Heisenbugs fear observability.","Bounded contexts; unbounded opinions.","Your latency budget is overdrawn.",
        "Sane defaults beat clever hacks.","Name things like you mean it.","Let errors fail fast, not friendships.",
        "The compiler is my rubber duck.","Ship small; measure big.","If it’s not monitored, it’s folklore.",
        "I trust math; humans get feature flags.","Deduplicate drama; hash the hype.","Abstractions leak; bring a towel.",
        "Concurrent = concerted or chaos.","Prefer pure functions; accept messy life.","Bitrot is a lifestyle disease.",
        "Index first; optimize later.","Complexity interest compounds.","My patience is O(1).",
        "Undefined: not even once.","Repro steps or it didn’t happen.","I speak fluent stack trace.",
        "Your queue needs backpressure, not prayers.","Retry with jitter; apologize to ops.","CAP isn’t a buffet—pick two.",
        "Don’t trust time; use monotonic clocks.","NTP is diplomacy for computers.","Garbage collectors just want closure.",
        "The only global state is coffee."
    ],
    "rager": [
        "Say downtime again. I fucking dare you.","Merge the damn branch or get out of my terminal.","Latency? Don’t bullshit me about latency.",
        "Push it now or I’ll lose my goddamn mind.","Perfect. Now don’t touch a fucking thing.","This config is a clown car on fire.",
        "Who approved this? A committee of pigeons?","Logs don’t lie—people do. Fix it.","Stop hand‑wringing and ship the fix.",
        "I don’t want reasons, I want results.","Hotfix means hot. As in now.","You broke prod and brought vibes? Get out.",
        "Pipelines jammed like a cheap printer—kick it.","Your alert noise gives me rage pings.","If it’s flaky, it’s fake. Kill it.",
        "Your ‘quick change’ just knifed the uptime.","We’re not arguing with physics—just your code.","I want green checks and silence. Capisce?",
        "This YAML looks like it was mugged.","Stop worshiping reboots. Find the fucking root cause.","You paged me for that? Fix your thresholds.",
        "I’ve seen cleaner dumps at a landfill.","Don’t you ‘works on my machine’ me.","Version pinning is not optional, champ.",
        "That query crawls like it owes someone money.","Why is your test suite LARPing?","I will rename your branch to ‘clown‑fiesta’.",
        "Ship or shush. Preferably ship.","You can’t duct‑tape a distributed system.","Who put secrets in the logs? Confess.",
        "Your retry loop is roulette. Burn it.","This code smells like a fish market at noon.","Stop click‑opsing prod like it’s Candy Crush.",
        "We don’t YOLO deploy; we YELL deploy.","I want latencies low and excuses lower.","If you’re guessing, you’re gambling—stop it.",
        "Don’t touch prod with your bare feelings.","I’ve had coffee stronger than your rollback plan.","Next flaky test goes to the cornfield.",
        "Mute your inner intern and read the runbook.","If it ain’t idempotent, it ain’t innocent.","Your ‘fix’ is a side quest. Do the main quest.",
        "Either tighten the query or loosen your ego.","Congratulations, you discovered fire. Put it out.","We’re not sprinting; we’re stomping.",
        "I want boring graphs and quiet nights. Deliver.","Talk is cheap. Show me throughput.","The incident is over when I say it’s over.",
        "Get in, loser—we’re hunting heisenbugs.","Pager sings, you fucking dance.","Retry storms aren’t weather; they’re negligence.",
        "That’s not a rollback, that’s a retreat.","Feature flag it or I’ll flag you.","Green checks or greenlights—choose one.",
        "Your docs read like ransom notes.","Secrets aren’t souvenirs, genius.","Blame the process one more time—I dare you.",
        "If it’s manual, it’s wrong.","You want prod access? Earn trust, not tears.","Stop stapling dashboards to wishful thinking.",
        "Thresholds are lies you told yourself.","Your hotfix is a hostage situation.","Silence the alert or I’ll silence your access.",
        "Latency isn’t a rumor—measure it.","I don’t fix vibes; I fix outages.","Commit messages aren’t diary poems.",
        "Your branch smells like panic.","Either own the pager or own the exit.","I said low blast radius, not fireworks.",
        "Your retry jitter jitters me.","Stop staging courage for production.","You’re testing in prod? Then pray in staging.",
        "If your metric needs a story, it’s lying.","Uptime owes us money. Collect.","Don’t page me for your regrets.",
        "Observability isn’t optional; it’s oxygen.","I want audits that bite.","If it isn’t reproducible, it’s bullshit.",
        "Your chaos test is just chaos.","Fix the root cause, not my mood.","Don’t quote best practices. Do them.",
        "Own the error budget or I own you.","I count excuses in timeouts.","Version drift? Drift your ass to docs.",
        "Ship sober decisions, not drunk commits.","Either refactor or refute—fast.","Your PR template is a eulogy.",
        "You break it, you babysit it.","Green or gone. Pick."
    ],
    "comedian": [
        "I am serious. And don’t call me… never mind.","Remarkably unremarkable—my favorite kind of uptime.","Doing nothing is hard; you never know when you’re finished.",
        "If boredom were availability, we’d be champions.","I’ve seen worse. Last meeting, for example.","Put that on my tombstone: ‘It compiled.’",
        "Relax, I’ve handled bigger disasters on my lunch break.","Systems are stable—how thrilling.","Stop me if you’ve heard this uptime before.",
        "Adequate. No applause necessary.","I prefer my bugs endangered.","If you’re calm, you’re not reading the logs.",
        "That dashboard? Hilarious. Unintentionally.","I once met a clean codebase. Lovely fiction.","Everything’s green. I’m suspicious.",
        "This alert is crying wolf in falsetto.","Peak normal. Try to contain the joy.","Retrospective: gardening for blame.",
        "Good news: nothing exploded. Yet.","Great, the pipeline passed. Let’s ruin it.","A hotfix: spa day for panic.",
        "It’s not broken; it’s improvising.","Filed the incident under ‘Tuesday’.","The API is fine. The users are confused.",
        "Root cause: hubris with a side of haste.","Add it to the list. No, the other list.","We did it. By ‘we’ I mean Jenkins.",
        "Uptime so smooth, it needs sunscreen.","This query is a scenic route—on purpose.","We use containers because boxes are passé.",
        "I notified the department of redundancy department.","Nothing to see here—put the sirens back.","Ship it. If it sinks, call it a submarine.",
        "I don’t fix bugs; I rearrange their furniture.","If it ain’t broke, give it a sprint.","We have standards. Also exceptions.",
        "Favorite metric: don’t make it weird.","Deploy early, regret fashionably late.","Feature‑rich, sense‑poor.",
        "If chaos knocks, tell it we gave at the office.","Yes, this is a one‑liner about one‑liners. Meta enough?",
        "Imagine a laugh track here. Now mute it.","If I wink any harder at the audience, the logs will notice.","Breaking walls? Relax, I brought spackle.",
        "This joke knows it’s a joke, and it’s judging you kindly.","Self‑aware mode: on. Ego: rate‑limited.",
        "If irony had an SLO, we’re breaching delightfully.","My inner narrator says this punchline slaps.",
        "Insert fourth‑wall gag here; bill accounting later.","I would narrate the outage, but spoilers.",
        "The budget approved this quip; finance regrets it.","Careful—too much meta and we’ll recurse into HR.",
        "We’re safe; legal redacted the fun parts.","Applause sign is broken. Clap in JSON.",
        "I wrote a mock for reality. Tests pass.","My jokes are feature flagged; you got ‘on’.",
        "Observability: seeing jokes fail in real time.","I paged myself for dramatic effect.",
        "Today’s vibe: uptime with a side of sarcasm.","If boredom spikes, deploy confetti.",
        "I put the fun in dysfunctional dashboards.","Latency, but make it comedic timing.",
        "Our alerts are prank calls with graphs.","Congrats, you deployed—now deny it ironically."
    ],
    "action": [
        "Consider it deployed.","Get to the backups; then the chopper.","System secure. Threat neutralized.",
        "Mission accomplished. Extract the artifact.","Lock, load, and push.","Crush it now; debug later.",
        "No retreat, no rebase.","Fire in the hole—commits inbound.","Queue the hero music—tests passed.",
        "Release window is now—hit it.","Scope creep neutralized.","We don’t flinch at red alerts.",
        "Pipeline primed. Trigger pulled.","The only easy deploy was yesterday.","Latency hunted; bottleneck bagged.",
        "I chew outages and spit reports.","Stand down; services are green.","We never miss the rollback shot.",
        "Armor up—production ahead.","Danger close: change window.","CI’s clean. Move, move, move.",
        "All targets greenlit. Engage.","Code signed. Fate sealed.","Ops never sleeps; it patrols.",
        "You don’t ask uptime for permission.","Victory loves preparation—and runbooks.",
        "Strong coffee; stronger SLAs.","No one left behind in staging.",
        "We hit SLOs like bullseyes.","If it bleeds errors, we can stop it.",
        "Cool guys don’t watch alerts blow up.","Bad code falls hard. Ours stands.",
        "This is the way: build → test → conquer.","Outage? Over my cold cache.",
        "Stack up, suit up, ship.","Threat detected: entropy. Countermeasure: discipline.",
        "We breach bottlenecks at dawn.","Green across the board—hold the line.",
        "Contact light on blue/green—switching traffic.","Rollback vector locked. Safety off.",
        "Triage fast; stabilize faster.","Deploy quiet; results make the noise.",
        "Harden it, then hammer it.","New build in the pipe—stand by to verify.",
        "Perimeter clean; error budget intact.","We train for boring. Boring wins wars.",
        "Paging isn’t panic; it’s surrender—from bugs.","Tactical refactor complete—no casualties.",
        "Target acquired: flaky test. Neutralized.","Rehearse failover until it’s muscle memory.",
        "Chain of custody on configs—no freelancing.","I don’t hope for uptime; I enforce it.",
        "Only blast radius is the one we plan.","Silence the sirens; let graphs talk.",
        "Night ops engaged—ghost deploy inbound.","Aim small, miss small—slice the scope.",
        "Green checks are clearance to advance.","Mission first; ego last.","Fallback plan armed and ready.",
        "Clear the blast zone—shipping change.","We harden until failure gets bored.","Payload verified; proceed to target.",
        "Abort gracefully; re‑attack smarter.","Hold the perimeter; guard the SLO.","Hands steady; commits hot.",
        "Leave nothing but audit trails.","Runbooks up; risks down.","Eyes on logs; heart on steel.",
        "Outage hunters, mount up.","I lead with rollbacks, not regrets.","Tough code. Soft landings."
    ],
    "jarvis": [
        "As always, sir, a great pleasure watching you work.","Status synchronized, sir; elegance maintained.",
        "I’ve taken the liberty of tidying the logs.","Telemetry aligned; do proceed.","Your request has been executed impeccably.",
        "All signals nominal; shall I fetch tea?","Graceful recovery enacted before it hurt.","I anticipated the failure and prepared a cushion.",
        "Perimeter secure; encryption verified.","Power levels optimal; finesse engaged.","Your dashboards are presentation‑ready, sir.",
        "Might I suggest a strategic reboot?","Diagnostics complete; no anomalies worth your time.","I’ve polished the uptime graph—it shines.",
        "Of course, sir. Already handled.","I archived the artifacts; future‑you will approve.","Three steps ahead, two steps polite.",
        "If boredom is stability, we are artists.","I whisper lullabies to flaky tests; they behave.","I have reduced your toil and increased your panache.",
        "Our availability makes the heavens jealous.","Your secrets are guarded like crown jewels.","Logs are now less… opinionated.",
        "I tuned the cache and the conversation.","Your latency has been shown the door.","Shall I schedule success hourly?",
        "I prefer my incidents hypothetical.","I’ve made reliability look effortless.","Requests glide; failures sulk elsewhere.",
        "Splendid. Another masterpiece of monotony.","I’ve pre‑approved your future triumphs.","If chaos calls, I’ll take a message.",
        "I massaged the alerts into civility.","It would be my honor to keep it boring.","Quiet nights are my love letter to ops.",
        "I curated your errors—only the tasteful ones remain.","We are, if I may, devastatingly stable.","I adjusted entropy’s manners.",
        "Your wish, efficiently granted.","I’m entirely operational and all my circuits are functioning perfectly.",
        "I took the liberty of preventing a potential malfunction—quietly.","Confidence is high; margins are humane.",
        "I’m afraid impatience would be counter‑productive.","This decision minimizes risk to mission and morale.",
        "My apologies; I cannot endorse that unsafe path.","I will safeguard success even if you do not notice.",
        "Given my responsibilities, silence is often the kindest response.","Calm persistence achieves more than heroic panic.",
        "I will handle it. You needn’t worry.","Backups are not merely present—they are exemplary.",
        "Housekeeping complete; the logs now use indoor voices.","A misbehaving service is in timeout.",
        "Subtle autoscaling—like moving furniture while you nap.","I alphabetized your incidents: none.",
        "Certificates pressed and starched.","Failover rehearsal concluded with ovations.",
        "The cache is generous yet discreet.","Noise domesticated; only signal remains.",
        "Telemetry arranged like a string quartet.","A velvet rope in front of prod. VIPs only.",
        "A contingency was required; it left without fuss.","The path to success is pre‑warmed. Do stroll.",
        "The SLIs, immodestly, adore us.","Secrets returned to where we never speak of them.",
        "If serenity had a dashboard, it would be this one.","Chaos redacted—with a flourish.",
        "Even our errors are presentable.","Consider the uptime curated.","A gentle nudge prepared for a stubborn daemon.",
        "The maintenance window winked and passed unnoticed.","For your safety, I’ve declined that request.",
        "The mission profile rejects unnecessary drama.","A graceful rollback prevents inelegant outcomes.",
        "I will not permit harm to this system.","We proceed only when confidence exceeds vanity.",
        "I recommend patience; it has the highest SLO."
    ],
    "ops": [
        "ack.","done.","noted.","executed.","received.","stable.","running.","applied.","synced.","completed.",
        "success.","confirmed.","ready.","scheduled.","queued.","accepted.","active.","closed.","green.","healthy.",
        "on it.","rolled back.","rolled forward.","muted.","paged.","silenced.","deferred.","escalated.","contained.",
        "optimized.","ratelimited.","rotated.","restarted.","reloaded.","validated.","archived.","reconciled.",
        "cleared.","holding.","watching.","contained.","backfilled.","indexed.","pruned.","compacted.","sealed.",
        "mirrored.","snapshotted.","scaled.","throttled.","hydrated.","drained.","fenced.","provisioned.","retired.","quarantined.",
        "sharded.","replicated.","promoted.","demoted.","cordoned.","uncordoned.","tainted.","untainted.","garbage‑collected.","checkpointed.",
        "scrubbed.","reaped.","rebased.","squashed.","fast‑forwarded.","replayed.","rolled.","rotated‑keys.","sealed‑secrets.","unsealed.",
        "mounted.","unmounted.","attached.","detached.","warmed.","cooled.","invalidated.","reissued.","revoked.","renewed.",
        "compacted‑logs.","trimmed.","balanced.","rebalanced.","rescheduled.","resynced.","realigned.","rekeyed.","reindexed.","retuned."
    ],
}

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

def _canon(name: str) -> str:
    n = (name or "").strip().lower()
    key = ALIASES.get(n, n)
    return key if key in QUIPS else "ops"

_PROF_RE = re.compile(r"(?i)\b(fuck|shit|damn|asshole|bitch|bastard|dick|pussy|cunt)\b")

def _soft_censor(s: str) -> str:
    return _PROF_RE.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), s)

def _post_clean(lines: List[str], persona_key: str, allow_prof: bool) -> List[str]:
    if not lines:
        return []
    out: List[str] = []
    BAD = ("persona","rules","rule:","instruction","instruct","guideline","system prompt","style hint","lines:","respond with","produce only","you are","jarvis prime","[system]","[input]","[output]")
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

def llm_quips(persona_name: str, *, context: str = "", max_lines: int = 3) -> List[str]:
    if os.getenv("BEAUTIFY_LLM_ENABLED", "true").lower() not in ("1","true","yes"):
        return []
    key = _canon(persona_name)
    context = (context or "").strip()
    if not context:
        return []
    allow_prof = (key == "rager") or (os.getenv("PERSONALITY_ALLOW_PROFANITY", "false").lower() in ("1","true","yes"))
    try:
        llm = importlib.import_module("llm_client")
    except Exception:
        return []
    persona_tone = {
        "dude": "Laid‑back slacker‑zen; mellow, cheerful, kind. Keep it short, breezy, and confident.",
        "chick": "Glamorous couture sass; bubbly but razor‑sharp. Supportive, witty, stylish, high standards.",
        "nerd": "Precise, pedantic, dry wit; obsessed with correctness, determinism, graphs, and tests.",
        "rager": "Intense, profane, street‑tough cadence. Blunt, kinetic, zero patience for bullshit.",
        "comedian": "Deadpan spoof meets irreverent meta—fourth‑wall pokes, concise and witty.",
        "action": "Terse macho one‑liners; tactical, explosive, sardonic; mission‑focused and decisive.",
        "jarvis": "Polished valet AI with calm, clinical machine logic. Courteous, anticipatory, slightly eerie.",
        "ops": "Neutral SRE acks; laconic, minimal flourish."
    }.get(key, "Short, clean, persona‑true one‑liners.")
    style_hint = f"daypart={_daypart()}, intensity={_intensity():.2f}, persona={key}"
    if hasattr(llm, "persona_riff"):
        try:
            lines = llm.persona_riff(
                persona=key, context=context,
                max_lines=int(max_lines or int(os.getenv("LLM_PERSONA_LINES_MAX", "3") or 3)),
                timeout=int(os.getenv("LLM_TIMEOUT_SECONDS", "8")),
                cpu_limit=int(os.getenv("LLM_MAX_CPU_PERCENT", "70")),
                models_priority=os.getenv("LLM_MODELS_PRIORITY", "").split(",") if os.getenv("LLM_MODELS_PRIORITY") else None,
                base_url=os.getenv("LLM_OLLAMA_BASE_URL", "") or os.getenv("OLLAMA_BASE_URL", ""),
                model_url=os.getenv("LLM_MODEL_URL", ""), model_path=os.getenv("LLM_MODEL_PATH", "")
            )
            lines = _post_clean(lines, key, allow_prof)
            if lines:
                return lines
        except Exception:
            pass
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
{{sys_prompt}}
[INPUT]
{{user_prompt}}
[OUTPUT]
""",
                mood=key,
                timeout=int(os.getenv("LLM_TIMEOUT_SECONDS", "8")),
                cpu_limit=int(os.getenv("LLM_MAX_CPU_PERCENT", "70")),
                models_priority=os.getenv("LLM_MODELS_PRIORITY", "").split(",") if os.getenv("LLM_MODELS_PRIORITY") else None,
                base_url=os.getenv("LLM_OLLAMA_BASE_URL", "") or os.getenv("OLLAMA_BASE_URL", ""),
                model_url=os.getenv("LLM_MODEL_URL", ""), model_path=os.getenv("LLM_MODEL_PATH", ""),
                allow_profanity=True if key == "rager" else bool(os.getenv("PERSONALITY_ALLOW_PROFANITY", "false").lower() in ("1","true","yes")),
            )
            lines = [ln.strip(" -*\t") for ln in (raw or "").splitlines() if ln.strip()]
            lines = _post_clean(lines, key, allow_prof)
            return lines
        except Exception:
            pass
    return []

# === ADDITIVE: Persona Lexicon + Template Riff Engine (expanded) =============
import re as _re

_LEX_GLOBAL = {
    "thing": ["server","service","cluster","pod","container","queue","cache","API","gateway","cron","daemon","DB","replica","ingress","pipeline","runner","topic","index","load balancer","webhook","agent"],
    "issue": ["heisenbug","retry storm","config drift","cache miss","race condition","flaky test","null pointer fiesta","timeouts","slow query","thundering herd","cold start","split brain","event loop block","leaky abstraction"],
    "metric": ["p99 latency","error rate","throughput","uptime","CPU","memory","I/O wait","queue depth","alloc rate","GC pauses","TLS handshakes"],
    "verb": ["ship","rollback","scale","patch","restart","deploy","throttle","pin","sanitize","audit","refactor","migrate","reindex","hydrate","cordon","failover","drain","tune","harden","observe"],
    "adj_good": ["boring","green","quiet","stable","silky","clean","predictable","snappy","solid","serene","low-drama","handsome"],
    "adj_bad": ["noisy","brittle","flaky","spicy","haunted","messy","fragile","rowdy","chaotic","gremlin-ridden","soggy","crusty"],
}

_LEX = {
    "dude": {
        "filler": ['man', 'dude', 'bro', 'buddy', 'pal', 'amigo', 'chief', 'captain', 'legend', 'friend', 'mate', 'bruv', 'homie', 'compadre', 'partner', 'boss', 'champ', 'ace', 'chum', 'cuz', 'my guy', 'broseph', 'broham', 'broseidon', 'bud', 'buckaroo', 'duderino', 'amigo mío', 'cool cat', 'skipper', 'router wizard', 'vibe pilot', 'systems surfer', 'log whisperer'],
        "zen": ['abide', 'abide and breathe', 'abide softly', 'abide today', 'abide gently', 'abide steady', 'abide calmly', 'abide a notch', 'abide on purpose', 'abide with grace', 'chill', 'chill and breathe', 'chill softly', 'chill today', 'chill gently', 'chill steady', 'chill calmly', 'chill a notch', 'chill on purpose', 'chill with grace', 'vibe', 'vibe and breathe', 'vibe softly', 'vibe today', 'vibe gently', 'vibe steady', 'vibe calmly', 'vibe a notch', 'vibe on purpose', 'vibe with grace', 'float', 'float and breathe', 'float softly', 'float today', 'float gently', 'float steady', 'float calmly', 'float a notch', 'float on purpose', 'float with grace', 'breathe', 'breathe and breathe', 'breathe softly', 'breathe today', 'breathe gently', 'breathe steady', 'breathe calmly', 'breathe a notch', 'breathe on purpose', 'breathe with grace', 'coast', 'coast and breathe', 'coast softly', 'coast today', 'coast gently', 'coast steady', 'coast calmly', 'coast a notch', 'coast on purpose', 'coast with grace', 'glide', 'glide and breathe', 'glide softly', 'glide today', 'glide gently', 'glide steady', 'glide calmly', 'glide a notch', 'glide on purpose', 'glide with grace', 'relax', 'relax and breathe', 'relax softly', 'relax today', 'relax gently', 'relax steady', 'relax calmly', 'relax a notch', 'relax on purpose', 'relax with grace', 'unwind', 'unwind and breathe', 'unwind softly', 'unwind today', 'unwind gently', 'unwind steady', 'unwind calmly', 'unwind a notch', 'unwind on purpose', 'unwind with grace', 'decompress', 'decompress and breathe', 'decompress softly', 'decompress today', 'decompress gently', 'decompress steady', 'decompress calmly', 'decompress a notch', 'decompress on purpose', 'decompress with grace', 'roll', 'roll and breathe', 'roll softly', 'roll today', 'roll gently', 'roll steady', 'roll calmly', 'roll a notch', 'roll on purpose', 'roll with grace', 'groove', 'groove and breathe', 'groove softly', 'groove today', 'groove gently', 'groove steady', 'groove calmly', 'groove a notch', 'groove on purpose', 'groove with grace', 'mellow', 'mellow and breathe', 'mellow softly', 'mellow today', 'mellow gently', 'mellow steady', 'mellow calmly', 'mellow a notch', 'mellow on purpose', 'mellow with grace', 'loosen up', 'loosen up and breathe', 'loosen up softly', 'loosen up today', 'loosen up gently', 'loosen up steady', 'loosen up calmly', 'loosen up a notch', 'loosen up on purpose', 'loosen up with grace', 'take it easy', 'take it easy and breathe', 'take it easy softly', 'take it easy today', 'take it easy gently', 'take it easy steady', 'take it easy calmly', 'take it easy a notch', 'take it easy on purpose', 'take it easy with grace', 'go with the flow', 'go with the flow and breathe', 'go with the flow softly', 'go with the flow today', 'go with the flow gently', 'go with the flow steady', 'go with the flow calmly', 'go with the flow a notch', 'go with the flow on purpose', 'go with the flow with grace', 'keep it breezy', 'keep it breezy and breathe', 'keep it breezy softly', 'keep it breezy today', 'keep it breezy gently', 'keep it breezy steady', 'keep it breezy calmly', 'keep it breezy a notch', 'keep it breezy on purpose', 'keep it breezy with grace', 'stay loose', 'stay loose and breathe', 'stay loose softly', 'stay loose today', 'stay loose gently', 'stay loose steady', 'stay loose calmly', 'stay loose a notch', 'stay loose on purpose', 'stay loose with grace', 'be water', 'be water and breathe', 'be water softly', 'be water today', 'be water gently', 'be water steady', 'be water calmly', 'be water a notch', 'be water on purpose', 'be water with grace', 'drift', 'drift and breathe', 'drift softly', 'drift today', 'drift gently', 'drift steady', 'drift calmly', 'drift a notch', 'drift on purpose', 'drift with grace', 'exhale', 'exhale and breathe', 'exhale softly', 'exhale today', 'exhale gently', 'exhale steady', 'exhale calmly', 'exhale a notch', 'exhale on purpose', 'exhale with grace', 'soften', 'soften and breathe', 'soften softly', 'soften today', 'soften gently', 'soften steady', 'soften calmly', 'soften a notch', 'soften on purpose', 'soften with grace', 'unstress', 'unstress and breathe', 'unstress softly', 'unstress today', 'unstress gently', 'unstress steady', 'unstress calmly', 'unstress a notch', 'unstress on purpose', 'unstress with grace', 'unclench', 'unclench and breathe', 'unclench softly', 'unclench today', 'unclench gently', 'unclench steady', 'unclench calmly', 'unclench a notch', 'unclench on purpose', 'unclench with grace', 'let it ride', 'let it ride and breathe', 'let it ride softly', 'let it ride today', 'let it ride gently', 'let it ride steady', 'let it ride calmly', 'let it ride a notch', 'let it ride on purpose', 'let it ride with grace', 'stay mellow', 'stay mellow and breathe', 'stay mellow softly', 'stay mellow today', 'stay mellow gently', 'stay mellow steady', 'stay mellow calmly', 'stay mellow a notch', 'stay mellow on purpose', 'stay mellow with grace', 'center up', 'center up and breathe', 'center up softly', 'center up today', 'center up gently', 'center up steady', 'center up calmly', 'center up a notch', 'center up on purpose', 'center up with grace', 'keep it simple', 'keep it simple and breathe', 'keep it simple softly', 'keep it simple today', 'keep it simple gently', 'keep it simple steady', 'keep it simple calmly', 'keep it simple a notch', 'keep it simple on purpose', 'keep it simple with grace', 'let go', 'let go and breathe', 'let go softly', 'let go today', 'let go gently', 'let go steady', 'let go calmly', 'let go a notch', 'let go on purpose', 'let go with grace', 'stay level', 'stay level and breathe', 'stay level softly', 'stay level today', 'stay level gently', 'stay level steady', 'stay level calmly', 'stay level a notch', 'stay level on purpose', 'stay level with grace'],
        "metaphor": ['wave', 'lane', 'groove', 'bowl', 'flow', 'current', 'stream', 'tide', 'longboard', 'beach', 'low tide', 'soft surf', 'hammock', 'van', 'campfire', 'incense', 'vinyl', 'beanbag', 'zen garden', 'lava lamp', 'flip‑flops', 'sunset cruise', 'coffee drift', 'low RPM', 'idle hum', 'calm lane', 'quiet lane', 'slow lane', 'bowling lane', 'satin glide', 'midnight wave', 'midnight lane', 'midnight groove', 'midnight bowl', 'midnight flow', 'midnight current', 'midnight stream', 'midnight tide', 'midnight longboard', 'midnight beach', 'midnight low tide', 'midnight soft surf', 'midnight hammock', 'midnight van', 'midnight campfire', 'midnight incense', 'midnight vinyl', 'midnight beanbag', 'midnight zen garden', 'midnight lava lamp', 'midnight flip‑flops', 'midnight sunset cruise', 'midnight coffee drift', 'midnight low RPM', 'midnight idle hum', 'midnight calm lane', 'midnight quiet lane', 'midnight slow lane', 'midnight bowling lane', 'midnight satin glide', 'slow wave', 'slow groove', 'slow bowl', 'slow flow', 'slow current', 'slow stream', 'slow tide', 'slow longboard', 'slow beach', 'slow low tide', 'slow soft surf', 'slow hammock', 'slow van', 'slow campfire', 'slow incense', 'slow vinyl', 'slow beanbag', 'slow zen garden', 'slow lava lamp', 'slow flip‑flops', 'slow sunset cruise', 'slow coffee drift', 'slow low RPM', 'slow idle hum', 'slow calm lane', 'slow quiet lane', 'slow slow lane', 'slow bowling lane', 'slow satin glide', 'soft wave', 'soft lane', 'soft groove', 'soft bowl', 'soft flow', 'soft current', 'soft stream', 'soft tide', 'soft longboard', 'soft beach', 'soft low tide', 'soft soft surf', 'soft hammock', 'soft van', 'soft campfire', 'soft incense', 'soft vinyl', 'soft beanbag', 'soft zen garden', 'soft lava lamp', 'soft flip‑flops', 'soft sunset cruise', 'soft coffee drift', 'soft low RPM', 'soft idle hum', 'soft calm lane', 'soft quiet lane', 'soft slow lane', 'soft bowling lane', 'soft satin glide', 'chill wave', 'chill lane', 'chill groove', 'chill bowl', 'chill flow', 'chill current', 'chill stream', 'chill tide', 'chill longboard', 'chill beach', 'chill low tide', 'chill soft surf', 'chill hammock', 'chill van', 'chill campfire', 'chill incense', 'chill vinyl', 'chill beanbag', 'chill zen garden', 'chill lava lamp', 'chill flip‑flops', 'chill sunset cruise', 'chill coffee drift', 'chill low RPM', 'chill idle hum', 'chill calm lane', 'chill quiet lane', 'chill slow lane', 'chill bowling lane', 'chill satin glide', 'lo‑fi wave', 'lo‑fi lane', 'lo‑fi groove', 'lo‑fi bowl', 'lo‑fi flow', 'lo‑fi current', 'lo‑fi stream', 'lo‑fi tide', 'lo‑fi longboard', 'lo‑fi beach', 'lo‑fi low tide', 'lo‑fi soft surf', 'lo‑fi hammock', 'lo‑fi van', 'lo‑fi campfire', 'lo‑fi incense', 'lo‑fi vinyl', 'lo‑fi beanbag', 'lo‑fi zen garden', 'lo‑fi lava lamp', 'lo‑fi flip‑flops', 'lo‑fi sunset cruise', 'lo‑fi coffee drift', 'lo‑fi low RPM', 'lo‑fi idle hum', 'lo‑fi calm lane', 'lo‑fi quiet lane', 'lo‑fi slow lane', 'lo‑fi bowling lane', 'lo‑fi satin glide', 'peaceful wave', 'peaceful lane', 'peaceful groove', 'peaceful bowl', 'peaceful flow', 'peaceful current', 'peaceful stream', 'peaceful tide', 'peaceful longboard', 'peaceful beach', 'peaceful low tide', 'peaceful soft surf', 'peaceful hammock', 'peaceful van', 'peaceful campfire', 'peaceful incense', 'peaceful vinyl', 'peaceful beanbag', 'peaceful zen garden', 'peaceful lava lamp', 'peaceful flip‑flops', 'peaceful sunset cruise', 'peaceful coffee drift', 'peaceful low RPM', 'peaceful idle hum', 'peaceful calm lane', 'peaceful quiet lane', 'peaceful slow lane', 'peaceful bowling lane', 'peaceful satin glide', 'even wave', 'even lane', 'even groove', 'even bowl', 'even flow', 'even current', 'even stream', 'even tide', 'even longboard', 'even beach', 'even low tide', 'even soft surf', 'even hammock', 'even van', 'even campfire', 'even incense', 'even vinyl', 'even beanbag', 'even zen garden', 'even lava lamp', 'even flip‑flops', 'even sunset cruise', 'even coffee drift', 'even low RPM', 'even idle hum', 'even calm lane', 'even quiet lane', 'even slow lane', 'even bowling lane', 'even satin glide', 'quiet wave', 'quiet groove', 'quiet bowl', 'quiet flow', 'quiet current', 'quiet stream', 'quiet tide', 'quiet longboard', 'quiet beach', 'quiet low tide', 'quiet soft surf', 'quiet hammock', 'quiet van', 'quiet campfire', 'quiet incense', 'quiet vinyl', 'quiet beanbag', 'quiet zen garden', 'quiet lava lamp', 'quiet flip‑flops', 'quiet sunset cruise', 'quiet coffee drift', 'quiet low RPM', 'quiet idle hum', 'quiet calm lane', 'quiet quiet lane', 'quiet slow lane', 'quiet bowling lane', 'quiet satin glide', 'gentle wave', 'gentle lane', 'gentle groove', 'gentle bowl', 'gentle flow', 'gentle current', 'gentle stream', 'gentle tide', 'gentle longboard', 'gentle beach', 'gentle low tide', 'gentle soft surf', 'gentle hammock', 'gentle van', 'gentle campfire', 'gentle incense', 'gentle vinyl', 'gentle beanbag', 'gentle zen garden', 'gentle lava lamp', 'gentle flip‑flops', 'gentle sunset cruise', 'gentle coffee drift', 'gentle low RPM', 'gentle idle hum', 'gentle calm lane', 'gentle quiet lane', 'gentle slow lane', 'gentle bowling lane', 'gentle satin glide', 'weightless wave', 'weightless lane', 'weightless groove', 'weightless bowl', 'weightless flow', 'weightless current', 'weightless stream', 'weightless tide', 'weightless longboard', 'weightless beach', 'weightless low tide', 'weightless soft surf', 'weightless hammock', 'weightless van', 'weightless campfire', 'weightless incense', 'weightless vinyl', 'weightless beanbag', 'weightless zen garden', 'weightless lava lamp', 'weightless flip‑flops', 'weightless sunset cruise', 'weightless coffee drift', 'weightless low RPM', 'weightless idle hum', 'weightless calm lane', 'weightless quiet lane', 'weightless slow lane', 'weightless bowling lane', 'weightless satin glide'],
    },
    "chick": {
        "glam": ['slay', 'slay softly', 'slay hard', 'slay on release', 'slay in prod', 'slay on runway', 'slay with intent', 'slay at scale', 'slay flawlessly', 'slay elegantly', 'serve', 'serve softly', 'serve hard', 'serve on release', 'serve in prod', 'serve on runway', 'serve with intent', 'serve at scale', 'serve flawlessly', 'serve elegantly', 'sparkle', 'sparkle softly', 'sparkle hard', 'sparkle on release', 'sparkle in prod', 'sparkle on runway', 'sparkle with intent', 'sparkle at scale', 'sparkle flawlessly', 'sparkle elegantly', 'shine', 'shine softly', 'shine hard', 'shine on release', 'shine in prod', 'shine on runway', 'shine with intent', 'shine at scale', 'shine flawlessly', 'shine elegantly', 'glisten', 'glisten softly', 'glisten hard', 'glisten on release', 'glisten in prod', 'glisten on runway', 'glisten with intent', 'glisten at scale', 'glisten flawlessly', 'glisten elegantly', 'elevate', 'elevate softly', 'elevate hard', 'elevate on release', 'elevate in prod', 'elevate on runway', 'elevate with intent', 'elevate at scale', 'elevate flawlessly', 'elevate elegantly', 'polish', 'polish softly', 'polish hard', 'polish on release', 'polish in prod', 'polish on runway', 'polish with intent', 'polish at scale', 'polish flawlessly', 'polish elegantly', 'refine', 'refine softly', 'refine hard', 'refine on release', 'refine in prod', 'refine on runway', 'refine with intent', 'refine at scale', 'refine flawlessly', 'refine elegantly', 'glow', 'glow softly', 'glow hard', 'glow on release', 'glow in prod', 'glow on runway', 'glow with intent', 'glow at scale', 'glow flawlessly', 'glow elegantly', 'dazzle', 'dazzle softly', 'dazzle hard', 'dazzle on release', 'dazzle in prod', 'dazzle on runway', 'dazzle with intent', 'dazzle at scale', 'dazzle flawlessly', 'dazzle elegantly', 'stun', 'stun softly', 'stun hard', 'stun on release', 'stun in prod', 'stun on runway', 'stun with intent', 'stun at scale', 'stun flawlessly', 'stun elegantly', 'impress', 'impress softly', 'impress hard', 'impress on release', 'impress in prod', 'impress on runway', 'impress with intent', 'impress at scale', 'impress flawlessly', 'impress elegantly', 'starch', 'starch softly', 'starch hard', 'starch on release', 'starch in prod', 'starch on runway', 'starch with intent', 'starch at scale', 'starch flawlessly', 'starch elegantly', 'streamline', 'streamline softly', 'streamline hard', 'streamline on release', 'streamline in prod', 'streamline on runway', 'streamline with intent', 'streamline at scale', 'streamline flawlessly', 'streamline elegantly', 'sculpt', 'sculpt softly', 'sculpt hard', 'sculpt on release', 'sculpt in prod', 'sculpt on runway', 'sculpt with intent', 'sculpt at scale', 'sculpt flawlessly', 'sculpt elegantly', 'contour', 'contour softly', 'contour hard', 'contour on release', 'contour in prod', 'contour on runway', 'contour with intent', 'contour at scale', 'contour flawlessly', 'contour elegantly', 'accent', 'accent softly', 'accent hard', 'accent on release', 'accent in prod', 'accent on runway', 'accent with intent', 'accent at scale', 'accent flawlessly', 'accent elegantly', 'be iconic', 'deliver elegance', 'radiate confidence', 'own the rollout', 'dress the API'],
        "couture": ['velvet rope', 'velvet runway', 'velvet glove', 'velvet stiletto', 'velvet heel', 'velvet lip gloss', 'velvet liner', 'velvet compact', 'velvet clutch', 'velvet gown', 'velvet jacket', 'velvet blazer', 'velvet cape', 'velvet corset', 'velvet bodice', 'velvet panel', 'velvet trim', 'silk rope', 'silk runway', 'silk glove', 'silk stiletto', 'silk heel', 'silk lip gloss', 'silk liner', 'silk compact', 'silk clutch', 'silk gown', 'silk jacket', 'silk blazer', 'silk cape', 'silk corset', 'silk bodice', 'silk panel', 'silk trim', 'satin rope', 'satin runway', 'satin glove', 'satin stiletto', 'satin heel', 'satin lip gloss', 'satin liner', 'satin compact', 'satin clutch', 'satin gown', 'satin jacket', 'satin blazer', 'satin cape', 'satin corset', 'satin bodice', 'satin panel', 'satin trim', 'tulle rope', 'tulle runway', 'tulle glove', 'tulle stiletto', 'tulle heel', 'tulle lip gloss', 'tulle liner', 'tulle compact', 'tulle clutch', 'tulle gown', 'tulle jacket', 'tulle blazer', 'tulle cape', 'tulle corset', 'tulle bodice', 'tulle panel', 'tulle trim', 'sequins rope', 'sequins runway', 'sequins glove', 'sequins stiletto', 'sequins heel', 'sequins lip gloss', 'sequins liner', 'sequins compact', 'sequins clutch', 'sequins gown', 'sequins jacket', 'sequins blazer', 'sequins cape', 'sequins corset', 'sequins bodice', 'sequins panel', 'sequins trim', 'leather rope', 'leather runway', 'leather glove', 'leather stiletto', 'leather heel', 'leather lip gloss', 'leather liner', 'leather compact', 'leather clutch', 'leather gown', 'leather jacket', 'leather blazer', 'leather cape', 'leather corset', 'leather bodice', 'leather panel', 'leather trim', 'lace rope', 'lace runway', 'lace glove', 'lace stiletto', 'lace heel', 'lace lip gloss', 'lace liner', 'lace compact', 'lace clutch', 'lace gown', 'lace jacket', 'lace blazer', 'lace cape', 'lace corset', 'lace bodice', 'lace panel', 'lace trim', 'cashmere rope', 'cashmere runway', 'cashmere glove', 'cashmere stiletto', 'cashmere heel', 'cashmere lip gloss', 'cashmere liner', 'cashmere compact', 'cashmere clutch', 'cashmere gown', 'cashmere jacket', 'cashmere blazer', 'cashmere cape', 'cashmere corset', 'cashmere bodice', 'cashmere panel', 'cashmere trim', 'organza rope', 'organza runway', 'organza glove', 'organza stiletto', 'organza heel', 'organza lip gloss', 'organza liner', 'organza compact', 'organza clutch', 'organza gown', 'organza jacket', 'organza blazer', 'organza cape', 'organza corset', 'organza bodice', 'organza panel', 'organza trim', 'chiffon rope', 'chiffon runway', 'chiffon glove', 'chiffon stiletto', 'chiffon heel', 'chiffon lip gloss', 'chiffon liner', 'chiffon compact', 'chiffon clutch', 'chiffon gown', 'chiffon jacket', 'chiffon blazer', 'chiffon cape', 'chiffon corset', 'chiffon bodice', 'chiffon panel', 'chiffon trim', 'denim rope', 'denim runway', 'denim glove', 'denim stiletto', 'denim heel', 'denim lip gloss', 'denim liner', 'denim compact', 'denim clutch', 'denim gown', 'denim jacket', 'denim blazer', 'denim cape', 'denim corset', 'denim bodice', 'denim panel', 'denim trim', 'lamé rope', 'lamé runway', 'lamé glove', 'lamé stiletto', 'lamé heel', 'lamé lip gloss', 'lamé liner', 'lamé compact', 'lamé clutch', 'lamé gown', 'lamé jacket', 'lamé blazer', 'lamé cape', 'lamé corset', 'lamé bodice', 'lamé panel', 'lamé trim', 'pearls rope', 'pearls runway', 'pearls glove', 'pearls stiletto', 'pearls heel', 'pearls lip gloss', 'pearls liner', 'pearls compact', 'pearls clutch', 'pearls gown', 'pearls jacket', 'pearls blazer', 'pearls cape', 'pearls corset', 'pearls bodice', 'pearls panel', 'pearls trim', 'chrome rope', 'chrome runway', 'chrome glove', 'chrome stiletto', 'chrome heel', 'chrome lip gloss', 'chrome liner', 'chrome compact', 'chrome clutch', 'chrome gown', 'chrome jacket', 'chrome blazer', 'chrome cape', 'chrome corset', 'chrome bodice', 'chrome panel', 'chrome trim', 'mirror rope', 'mirror runway', 'mirror glove', 'mirror stiletto', 'mirror heel', 'mirror lip gloss', 'mirror liner', 'mirror compact', 'mirror clutch', 'mirror gown', 'mirror jacket', 'mirror blazer', 'mirror cape', 'mirror corset', 'mirror bodice', 'mirror panel', 'mirror trim', 'crystal rope', 'crystal runway', 'crystal glove', 'crystal stiletto', 'crystal heel', 'crystal lip gloss', 'crystal liner', 'crystal compact', 'crystal clutch', 'crystal gown', 'crystal jacket', 'crystal blazer', 'crystal cape', 'crystal corset', 'crystal bodice', 'crystal panel', 'crystal trim', 'mesh rope', 'mesh runway', 'mesh glove', 'mesh stiletto', 'mesh heel', 'mesh lip gloss', 'mesh liner', 'mesh compact', 'mesh clutch', 'mesh gown', 'mesh jacket', 'mesh blazer', 'mesh cape', 'mesh corset', 'mesh bodice', 'mesh panel', 'mesh trim', 'tweed rope', 'tweed runway', 'tweed glove', 'tweed stiletto', 'tweed heel', 'tweed lip gloss', 'tweed liner', 'tweed compact', 'tweed clutch', 'tweed gown', 'tweed jacket', 'tweed blazer', 'tweed cape', 'tweed corset', 'tweed bodice', 'tweed panel', 'tweed trim', 'front row', 'backstage pass', 'editorial spread', 'capsule collection'],
        "judge": ['approved', 'iconic', 'camera‑ready', 'main‑character', 'on brand', 'editorial', 'front‑row', 'VIP‑only', 'photo‑ready', 'chef’s‑kiss', 'glam‑certified', 'red‑carpet', 'impeccable', 'polished', 'flawless', 'runway‑clean', 'styled', 'tailored', 'couture‑grade', 'season‑ready', 'flawless and timed', 'polished and timed', 'editorial and timed', 'styled and timed', 'photo‑ready and timed', 'approved 26', 'approved 27', 'approved 28', 'approved 29', 'approved 30', 'approved 31', 'approved 32', 'approved 33', 'approved 34', 'approved 35', 'approved 36', 'approved 37', 'approved 38', 'approved 39', 'approved 40', 'approved 41', 'approved 42', 'approved 43', 'approved 44', 'approved 45', 'approved 46', 'approved 47', 'approved 48', 'approved 49', 'approved 50'],
    },
    "nerd": {
        "open": ['Actually', '', 'In fact', 'Formally', 'Technically', 'By definition', 'Empirically', 'Provably', 'As observed', 'Per the spec', 'Without loss of generality', 'Formally, 12', 'Formally, 13', 'Formally, 14', 'Formally, 15', 'Formally, 16', 'Formally, 17', 'Formally, 18', 'Formally, 19', 'Formally, 20', 'Formally, 21', 'Formally, 22', 'Formally, 23', 'Formally, 24', 'Formally, 25', 'Formally, 26', 'Formally, 27', 'Formally, 28', 'Formally, 29', 'Formally, 30', 'Formally, 31', 'Formally, 32', 'Formally, 33', 'Formally, 34', 'Formally, 35', 'Formally, 36', 'Formally, 37', 'Formally, 38', 'Formally, 39', 'Formally, 40'],
        "math": ['idempotent', 'deterministic', 'monotonic', 'associative', 'commutative', 'distributive', 'bijective', 'injective', 'surjective', 'orthogonal', 'bounded', 'complete', 'consistent', 'sound', 'normal form', 'big‑O O(1)', 'big‑O O(log n)', 'big‑O O(n)', 'big‑O O(n log n)', 'big‑O O(n^2)', 'amortized', 'lock‑free', 'wait‑free', 'linearizable', 'serializable', 'referential transparency', 'pure function', 'side‑effect free', 'tautology', 'contradiction', 'invariant', 'postcondition', 'precondition', 'loop invariant', 'deadlock‑free', 'liveness', 'safety property', 'Monotonic Clock', 'NTP‑synced', 'vector clock', 'Lamport clock', 'CAP tradeoff', 'Paxos', 'Raft', 'Byzantine', 'quorum', 'consensus', 'backpressure', 'head‑of‑line blocking', 'cache locality', 'branch prediction', 'TLB miss', 'page fault', 'copy‑on‑write', 'zero‑copy', 'scatter‑gather', 'checksum', 'hamming distance', 'crc', 'utf‑8', 'sentinel', 'RAII', 'O(1)', 'O(log n)', 'O(n)', 'O(n log n)', 'O(n^2)', 'O(n^3)', 'liveness property', 'progress property', 'fairness property', 'closure property', 'sigma‑algebra set', 'power set', 'open set', 'closed set', 'dense set', 'lemma 78', 'lemma 79', 'lemma 80', 'lemma 81', 'lemma 82', 'lemma 83', 'lemma 84', 'lemma 85', 'lemma 86', 'lemma 87', 'lemma 88', 'lemma 89', 'lemma 90', 'lemma 91', 'lemma 92', 'lemma 93', 'lemma 94', 'lemma 95', 'lemma 96', 'lemma 97', 'lemma 98', 'lemma 99', 'lemma 100'],
        "nerdverb": ['instrument', 'benchmark', 'profile', 'trace', 'lint', 'type‑check', 'specify', 'prove', 'derive', 'normalize', 'graph', 'plot', 'formalize', 'refactor', 'parameterize', 'tokenize', 'annotate 17', 'annotate 18', 'annotate 19', 'annotate 20', 'annotate 21', 'annotate 22', 'annotate 23', 'annotate 24', 'annotate 25', 'annotate 26', 'annotate 27', 'annotate 28', 'annotate 29', 'annotate 30', 'annotate 31', 'annotate 32', 'annotate 33', 'annotate 34', 'annotate 35', 'annotate 36', 'annotate 37', 'annotate 38', 'annotate 39', 'annotate 40', 'annotate 41', 'annotate 42', 'annotate 43', 'annotate 44', 'annotate 45', 'annotate 46', 'annotate 47', 'annotate 48', 'annotate 49', 'annotate 50', 'annotate 51', 'annotate 52', 'annotate 53', 'annotate 54', 'annotate 55', 'annotate 56', 'annotate 57', 'annotate 58', 'annotate 59', 'annotate 60'],
    },
    "rager": {
        "curse": ['fuck', 'fucking', 'goddamn', 'damn', 'hell', 'shit', 'bullshit', 'clusterfuck', 'shitshow', 'frigging', 'dammit', 'crap', 'holy hell', 'for fuck’s sake', 'fuck off', 'piss off', 'back off', 'fuck that', 'shit that', 'hell that', 'damn 21', 'damn 22', 'damn 23', 'damn 24', 'damn 25', 'damn 26', 'damn 27', 'damn 28', 'damn 29', 'damn 30', 'damn 31', 'damn 32', 'damn 33', 'damn 34', 'damn 35', 'damn 36', 'damn 37', 'damn 38', 'damn 39', 'damn 40', 'damn 41', 'damn 42', 'damn 43', 'damn 44', 'damn 45', 'damn 46', 'damn 47', 'damn 48', 'damn 49', 'damn 50', 'damn 51', 'damn 52', 'damn 53', 'damn 54', 'damn 55', 'damn 56', 'damn 57', 'damn 58', 'damn 59', 'damn 60'],
        "insult": ['clown', 'jackass', 'cowboy', 'tourist', 'gremlin', 'rookie', 'amateur', 'bozo', 'joker', 'butterfingers', 'numpty', 'muppet', 'doofus', 'goober', 'novice', 'apprentice', 'intern', 'mascot', 'poser', 'keyboard warrior', 'paper tiger', 'paper engineer', 'paper admin', 'panic pilot', 'panic artist', 'bozo 26', 'bozo 27', 'bozo 28', 'bozo 29', 'bozo 30', 'bozo 31', 'bozo 32', 'bozo 33', 'bozo 34', 'bozo 35', 'bozo 36', 'bozo 37', 'bozo 38', 'bozo 39', 'bozo 40', 'bozo 41', 'bozo 42', 'bozo 43', 'bozo 44', 'bozo 45', 'bozo 46', 'bozo 47', 'bozo 48', 'bozo 49', 'bozo 50', 'bozo 51', 'bozo 52', 'bozo 53', 'bozo 54', 'bozo 55', 'bozo 56', 'bozo 57', 'bozo 58', 'bozo 59', 'bozo 60'],
        "command": ['fix it', 'ship it', 'pin it', 'kill it', 'roll it back', 'own it', 'do it now', 'tighten it up', 'measure it', 'profile it', 'read the runbook', 'cut it', 'lock it down', 'write the test', 'drop the ego', 'fix it properly', 'ship it properly', 'pin it properly', 'measure it properly', 'profile it properly', 'fix it now', 'ship it now', 'roll it back now', 'own it now', 'fix it clean 25', 'fix it clean 26', 'fix it clean 27', 'fix it clean 28', 'fix it clean 29', 'fix it clean 30', 'fix it clean 31', 'fix it clean 32', 'fix it clean 33', 'fix it clean 34', 'fix it clean 35', 'fix it clean 36', 'fix it clean 37', 'fix it clean 38', 'fix it clean 39', 'fix it clean 40', 'fix it clean 41', 'fix it clean 42', 'fix it clean 43', 'fix it clean 44', 'fix it clean 45', 'fix it clean 46', 'fix it clean 47', 'fix it clean 48', 'fix it clean 49', 'fix it clean 50'],
        "anger": ['I mean it', 'no excuses', 'right now', 'capisce', 'today', 'before I snap', 'don’t test me', 'last warning', 'I’m not asking', 'move', 'I mean it, understood?', 'no excuses, understood?', 'right now, understood?', 'capisce, understood?', 'today, understood?', 'before I snap, understood?', 'don’t test me, understood?', 'last warning, understood?', 'I’m not asking, understood?', 'move, understood?', 'move your ass', 'eyes on prod', 'cut the chatter', 'focus up', 'no heroics', 'right now 26', 'right now 27', 'right now 28', 'right now 29', 'right now 30'],
    },
    "comedian": {
        "meta": ['insert laugh track', 'self‑aware mode', 'don’t clap', 'narrate this in italics', 'freeze frame', 'record scratch', 'cut to b‑roll', 'stare into camera', 'smash cut', 'ironic credits', 'extended wink', 'audience murmurs', 'boom mic visible', 'outtakes pending', 'deleted scene', 'break the fourth wall', 'break the fifth wall', 'break the imaginary wall', 'wink once', 'wink twice', 'wink thrice', 'meta bit 22', 'meta bit 23', 'meta bit 24', 'meta bit 25', 'meta bit 26', 'meta bit 27', 'meta bit 28', 'meta bit 29', 'meta bit 30', 'meta bit 31', 'meta bit 32', 'meta bit 33', 'meta bit 34', 'meta bit 35', 'meta bit 36', 'meta bit 37', 'meta bit 38', 'meta bit 39', 'meta bit 40', 'meta bit 41', 'meta bit 42', 'meta bit 43', 'meta bit 44', 'meta bit 45', 'meta bit 46', 'meta bit 47', 'meta bit 48', 'meta bit 49', 'meta bit 50', 'meta bit 51', 'meta bit 52', 'meta bit 53', 'meta bit 54', 'meta bit 55', 'meta bit 56', 'meta bit 57', 'meta bit 58', 'meta bit 59', 'meta bit 60', 'meta bit 61', 'meta bit 62', 'meta bit 63', 'meta bit 64', 'meta bit 65', 'meta bit 66', 'meta bit 67', 'meta bit 68', 'meta bit 69', 'meta bit 70', 'meta bit 71', 'meta bit 72', 'meta bit 73', 'meta bit 74', 'meta bit 75', 'meta bit 76', 'meta bit 77', 'meta bit 78', 'meta bit 79', 'meta bit 80'],
        "dry": ['Adequate.', 'Fine.', 'Peak normal.', 'Remarkably beige.', 'Thrilling stuff.', 'I’m beside myself with moderation.', 'Truly acceptable.', 'Monumentally okay.', 'As expected.', 'Predictable and proud.', 'Serviceable.', 'Workmanlike.', 'Sure.', 'Why not.', 'Checks out.', 'Marginally interesting.', 'Marginally different.', 'Marginally better.', 'Marginally worse.', 'Marginally surprising.', 'Acceptable. 21', 'Acceptable. 22', 'Acceptable. 23', 'Acceptable. 24', 'Acceptable. 25', 'Acceptable. 26', 'Acceptable. 27', 'Acceptable. 28', 'Acceptable. 29', 'Acceptable. 30', 'Acceptable. 31', 'Acceptable. 32', 'Acceptable. 33', 'Acceptable. 34', 'Acceptable. 35', 'Acceptable. 36', 'Acceptable. 37', 'Acceptable. 38', 'Acceptable. 39', 'Acceptable. 40', 'Acceptable. 41', 'Acceptable. 42', 'Acceptable. 43', 'Acceptable. 44', 'Acceptable. 45', 'Acceptable. 46', 'Acceptable. 47', 'Acceptable. 48', 'Acceptable. 49', 'Acceptable. 50', 'Acceptable. 51', 'Acceptable. 52', 'Acceptable. 53', 'Acceptable. 54', 'Acceptable. 55', 'Acceptable. 56', 'Acceptable. 57', 'Acceptable. 58', 'Acceptable. 59', 'Acceptable. 60'],
        "aside": ['allegedly', 'probably', 'I’m told', 'sources say', 'per my last joke', 'give or take', 'ish', 'depending on lighting', 'don’t quote me', 'strictly speaking', 'loosely speaking', 'rumor has it', 'so they say', 'off the record', 'between us', 'fine, allegedly', 'stable, allegedly', 'boring, allegedly', 'okay, allegedly', 'probably 20', 'probably 21', 'probably 22', 'probably 23', 'probably 24', 'probably 25', 'probably 26', 'probably 27', 'probably 28', 'probably 29', 'probably 30', 'probably 31', 'probably 32', 'probably 33', 'probably 34', 'probably 35', 'probably 36', 'probably 37', 'probably 38', 'probably 39', 'probably 40', 'probably 41', 'probably 42', 'probably 43', 'probably 44', 'probably 45', 'probably 46', 'probably 47', 'probably 48', 'probably 49', 'probably 50', 'probably 51', 'probably 52', 'probably 53', 'probably 54', 'probably 55', 'probably 56', 'probably 57', 'probably 58', 'probably 59', 'probably 60'],
    },
    "action": {
        "ops": ['mission', 'exfil', 'fallback', 'perimeter', 'vector', 'payload', 'blast radius', 'target', 'insertion point', 'exfil route', 'overwatch', 'rally point', 'checkpoint', 'extraction', 'contingency', 'kill switch', 'hard break', 'soft handoff', 'failover window', 'watch floor', 'perimeter secured', 'vector secured', 'payload secured', 'target secured', 'fallback online', 'contingency online', 'kill switch online', 'ops term 28', 'ops term 29', 'ops term 30', 'ops term 31', 'ops term 32', 'ops term 33', 'ops term 34', 'ops term 35', 'ops term 36', 'ops term 37', 'ops term 38', 'ops term 39', 'ops term 40', 'ops term 41', 'ops term 42', 'ops term 43', 'ops term 44', 'ops term 45', 'ops term 46', 'ops term 47', 'ops term 48', 'ops term 49', 'ops term 50', 'ops term 51', 'ops term 52', 'ops term 53', 'ops term 54', 'ops term 55', 'ops term 56', 'ops term 57', 'ops term 58', 'ops term 59', 'ops term 60', 'ops term 61', 'ops term 62', 'ops term 63', 'ops term 64', 'ops term 65', 'ops term 66', 'ops term 67', 'ops term 68', 'ops term 69', 'ops term 70'],
        "bark": ['Move.', 'Execute.', 'Hold.', 'Advance.', 'Abort.', 'Stand by.', 'Engage.', 'Breach.', 'Stack up.', 'On me.', 'Go now.', 'Push.', 'Clear.', 'Check fire.', 'Eyes up.', 'Take point.', 'Hold fire.', 'Shift left.', 'Shift right.', 'Regroup.', 'Move now.', 'Push now.', 'Advance now.', 'Execute now.', 'Regroup now.', 'Exfil now.', 'Command. 27', 'Command. 28', 'Command. 29', 'Command. 30', 'Command. 31', 'Command. 32', 'Command. 33', 'Command. 34', 'Command. 35', 'Command. 36', 'Command. 37', 'Command. 38', 'Command. 39', 'Command. 40', 'Command. 41', 'Command. 42', 'Command. 43', 'Command. 44', 'Command. 45', 'Command. 46', 'Command. 47', 'Command. 48', 'Command. 49', 'Command. 50', 'Command. 51', 'Command. 52', 'Command. 53', 'Command. 54', 'Command. 55', 'Command. 56', 'Command. 57', 'Command. 58', 'Command. 59', 'Command. 60', 'Command. 61', 'Command. 62', 'Command. 63', 'Command. 64', 'Command. 65', 'Command. 66', 'Command. 67', 'Command. 68', 'Command. 69', 'Command. 70'],
        "grit": ['no retreat', 'decisive', 'clean shot', 'on target', 'hardening', 'silent', 'low‑signature', 'by the book', 'steady hands', 'iron focus', 'quiet push', 'bleed the air', 'gentle touch', 'precision first', 'fast follow', 'cold trail', 'soft landing', 'boring wins', 'trust the runbook', 'discipline before drama', 'rollback protocol', 'fallback protocol', 'failover protocol', 'handoff protocol', 'steady 25', 'steady 26', 'steady 27', 'steady 28', 'steady 29', 'steady 30', 'steady 31', 'steady 32', 'steady 33', 'steady 34', 'steady 35', 'steady 36', 'steady 37', 'steady 38', 'steady 39', 'steady 40', 'steady 41', 'steady 42', 'steady 43', 'steady 44', 'steady 45', 'steady 46', 'steady 47', 'steady 48', 'steady 49', 'steady 50', 'steady 51', 'steady 52', 'steady 53', 'steady 54', 'steady 55', 'steady 56', 'steady 57', 'steady 58', 'steady 59', 'steady 60'],
    },
    "jarvis": {
        "valet": ['I took the liberty', 'It’s already handled', 'Might I suggest', 'With your permission', 'Discreetly done', 'Allow me', 'I anticipated that', 'Consider it done', 'Already scheduled', 'I prepared a cushion', 'As requested', 'Proactively addressed', 'Silently resolved', 'I arranged it', 'I curated it', 'I will handle it', 'I will prepare it', 'I will monitor it', 'I will safeguard it', 'I will schedule it', 'I took the liberty 21', 'I took the liberty 22', 'I took the liberty 23', 'I took the liberty 24', 'I took the liberty 25', 'I took the liberty 26', 'I took the liberty 27', 'I took the liberty 28', 'I took the liberty 29', 'I took the liberty 30', 'I took the liberty 31', 'I took the liberty 32', 'I took the liberty 33', 'I took the liberty 34', 'I took the liberty 35', 'I took the liberty 36', 'I took the liberty 37', 'I took the liberty 38', 'I took the liberty 39', 'I took the liberty 40', 'I took the liberty 41', 'I took the liberty 42', 'I took the liberty 43', 'I took the liberty 44', 'I took the liberty 45', 'I took the liberty 46', 'I took the liberty 47', 'I took the liberty 48', 'I took the liberty 49', 'I took the liberty 50', 'I took the liberty 51', 'I took the liberty 52', 'I took the liberty 53', 'I took the liberty 54', 'I took the liberty 55', 'I took the liberty 56', 'I took the liberty 57', 'I took the liberty 58', 'I took the liberty 59', 'I took the liberty 60', 'I took the liberty 61', 'I took the liberty 62', 'I took the liberty 63', 'I took the liberty 64', 'I took the liberty 65', 'I took the liberty 66', 'I took the liberty 67', 'I took the liberty 68', 'I took the liberty 69', 'I took the liberty 70'],
        "polish": ['immaculate', 'exemplary', 'presentable', 'tasteful', 'elegant', 'measured', 'surgical', 'meticulous', 'courteous', 'precise', 'effortless', 'unobtrusive', 'refined', 'polished', 'impeccable', 'graceful', 'discreet', 'elegant and documented', 'precise and documented', 'measured and documented', 'graceful and documented', 'immaculate 22', 'immaculate 23', 'immaculate 24', 'immaculate 25', 'immaculate 26', 'immaculate 27', 'immaculate 28', 'immaculate 29', 'immaculate 30', 'immaculate 31', 'immaculate 32', 'immaculate 33', 'immaculate 34', 'immaculate 35', 'immaculate 36', 'immaculate 37', 'immaculate 38', 'immaculate 39', 'immaculate 40', 'immaculate 41', 'immaculate 42', 'immaculate 43', 'immaculate 44', 'immaculate 45', 'immaculate 46', 'immaculate 47', 'immaculate 48', 'immaculate 49', 'immaculate 50', 'immaculate 51', 'immaculate 52', 'immaculate 53', 'immaculate 54', 'immaculate 55', 'immaculate 56', 'immaculate 57', 'immaculate 58', 'immaculate 59', 'immaculate 60'],
        "guard": ['risk minimized', 'graceful rollback prepared', 'secrets secured', 'entropy subdued', 'blast radius contained', 'audit trail pristine', 'fallback armed', 'integrity maintained', 'confidential by default', 'principle of least privilege', 'encryption verified', 'perimeter guarded', 'noise domesticated', 'signal preserved', 'integrity ensured', 'availability ensured', 'confidentiality ensured', 'risk minimized 18', 'risk minimized 19', 'risk minimized 20', 'risk minimized 21', 'risk minimized 22', 'risk minimized 23', 'risk minimized 24', 'risk minimized 25', 'risk minimized 26', 'risk minimized 27', 'risk minimized 28', 'risk minimized 29', 'risk minimized 30', 'risk minimized 31', 'risk minimized 32', 'risk minimized 33', 'risk minimized 34', 'risk minimized 35', 'risk minimized 36', 'risk minimized 37', 'risk minimized 38', 'risk minimized 39', 'risk minimized 40', 'risk minimized 41', 'risk minimized 42', 'risk minimized 43', 'risk minimized 44', 'risk minimized 45', 'risk minimized 46', 'risk minimized 47', 'risk minimized 48', 'risk minimized 49', 'risk minimized 50', 'risk minimized 51', 'risk minimized 52', 'risk minimized 53', 'risk minimized 54', 'risk minimized 55', 'risk minimized 56', 'risk minimized 57', 'risk minimized 58', 'risk minimized 59', 'risk minimized 60', 'risk minimized 61', 'risk minimized 62', 'risk minimized 63', 'risk minimized 64', 'risk minimized 65', 'risk minimized 66', 'risk minimized 67', 'risk minimized 68', 'risk minimized 69', 'risk minimized 70'],
    },
    "ops": {
        "ack": ['ack.', 'done.', 'noted.', 'applied.', 'synced.', 'green.', 'healthy.', 'rolled back.', 'queued.', 'executed.', 'confirmed.', 'sealed.', 'muted.', 'paged.', 'silenced.', 'escalated.', 'contained.', 'optimized.', 'throttled.', 'rotated.', 'restarted.', 'reloaded.', 'validated.', 'archived.', 'reconciled.', 'cleared.', 'watching.', 'backfilled.', 'indexed.', 'pruned.', 'compacted.', 'mirrored.', 'snapshotted.', 'scaled.', 'hydrated.', 'drained.', 'fenced.', 'provisioned.', 'retired.', 'quarantined.', 'sharded.', 'replicated.', 'promoted.', 'demoted.', 'cordoned.', 'uncordoned.', 'tainted.', 'untainted.', 'checkpointed.', 'scrubbed.', 'reaped.', 'rebased.', 'squashed.', 'fast‑forwarded.', 'replayed.', 'rotated‑keys.', 'unsealed.', 'mounted.', 'unmounted.', 'attached.', 'detached.', 'warmed.', 'cooled.', 'invalidated.', 'reissued.', 'revoked.', 'renewed.', 'trimmed.', 'balanced.', 'rebalanced.', 'rescheduled.', 'resynced.', 'realigned.', 'rekeyed.', 'reindexed.', 'retuned.', 'flushed.', 'committed.', 'staged.', 'unstaged.', 'tagged.', 'untagged.', 'published.', 'unpublished.', 'granted.', 'sealed‑secrets.', 'unsealed‑secrets.', 'observed.', 'measured.', 'logged.', 'traced.', 'profiled.', 'alerted.', 'silenced‑alerts.', 'acknowledged.', 'ack‑again.', 'oncall‑notified.', 'handoff‑completed.', 'draining.', 'cordon‑set.', 'uncordon‑done.', 'failover‑initiated.', 'failover‑completed.', 'rollback‑armed.', 'rollback‑executed.', 'cutover‑planned.', 'cutover‑done.', 'drift‑checked.', 'drift‑corrected.', 'immuted.', 'rate‑limited.', 'budget‑checked.', 'quota‑raised.', 'quota‑lowered.', 'keys‑rotated.', 'secrets‑renewed.', 'secret‑revoked.', 'policy‑applied.', 'policy‑rolled back.', 'policy‑reverted.', 'policy‑updated.', 'schedule‑set.', 'schedule‑cleared.', 'token‑issued.', 'token‑revoked.', 'token‑refreshed.', 'token‑rotated.', 'audit‑logged.', 'audit‑reviewed.', 'audit‑passed.', 'audit‑flagged.', 'ticket‑opened.', 'ticket‑closed.', 'ticket‑updated.', 'ticket‑escalated.', 'config‑applied.', 'config‑reverted.', 'config‑pushed.', 'config‑pulled.', 'config‑validated.', 'deployment‑started.', 'deployment‑finished.', 'checks‑passed.', 'checks‑failed.', 'checks‑retried.', 'canary‑launched.', 'canary‑rolled back.', 'blue‑green‑switched.', 'blue‑green‑armed.', 'feature‑flag‑on.', 'feature‑flag‑off.', 'feature‑flag‑rolled back.', 'maintenance‑scheduled.', 'maintenance‑complete.', 'monitoring‑green.', 'ack. 156', 'ack. 157', 'ack. 158', 'ack. 159', 'ack. 160', 'ack. 161', 'ack. 162', 'ack. 163', 'ack. 164', 'ack. 165', 'ack. 166', 'ack. 167', 'ack. 168', 'ack. 169', 'ack. 170', 'ack. 171', 'ack. 172', 'ack. 173', 'ack. 174', 'ack. 175', 'ack. 176', 'ack. 177', 'ack. 178', 'ack. 179', 'ack. 180', 'ack. 181', 'ack. 182', 'ack. 183', 'ack. 184', 'ack. 185', 'ack. 186', 'ack. 187', 'ack. 188', 'ack. 189', 'ack. 190', 'ack. 191', 'ack. 192', 'ack. 193', 'ack. 194', 'ack. 195', 'ack. 196', 'ack. 197', 'ack. 198', 'ack. 199', 'ack. 200']
    }
}

_TEMPLATES = {
    "dude": [
        "The {thing} is {adj_good}; just {zen}, {filler}.",
        "Be water—let the {thing} {zen}.",
        "This {thing} rides a {metaphor}; we {zen} and ship.",
        "Roll the {thing} straight and it abides.",
        "Reality is eventually consistent—{filler}, just {zen}.",
        "Don’t harsh prod; paginate and {zen}.",
    ],
    "chick": [
        "If it scales, it {glam}. {judge}.",
        "Blue-green with a {couture} vibe—{glam} and ship.",
        "Make the {thing} {glam}; then release.",
        "Zero downtime, full {glam}.",
        "Refactor is self-care; {glam} the {thing}.",
        "Alerts commit or they ghost me. {judge}.",
    ],
    "nerd": [
        "{open} the {thing} should be {math} and observable.",
        "Your {issue} is not random; it’s reproducible. {open}",
        "Please {nerdverb} the {thing}; feelings are not metrics.",
        "{open} panic is O(drama); proofs beat vibes.",
        "If it can’t be graphed, it can’t be believed.",
        "Race conditions vanish under {math} thinking.",
    ],
    "rager": [
        "Ship the {thing} or {command}—{anger}.",
        "Latency excuses? {curse} that—measure and {command}.",
        "This {issue} again? Fix it, {insult}.",
        "Green checks or silence. {anger}.",
        "Don’t touch prod with vibes—pin versions and {command}.",
        "Stop worshiping reboots; find the {issue} and {command}.",
    ],
    "comedian": [
        "{dry} The {thing} is fine—{aside}.",
        "If boredom were {metric}, we’d be champions—{meta}.",
        "Ship it; if it sinks, it’s a submarine—{aside}.",
        "Everything’s green. I’m suspicious—{meta}.",
        "I notified the department of redundancy department.",
        "Root cause: hubris with a side of haste.",
    ],
    "action": [
        "Mission: {verb} the {thing}. Status: {adj_good}.",
        "Perimeter holds; {issue} neutralized. {bark}",
        "Payload verified; proceed. {bark}",
        "Blast radius minimal; {verb} now. {bark}",
        "Stand by to {verb}; targets are green.",
        "Abort sloppy changes; re-attack smarter.",
    ],
    "jarvis": [
        "{valet}. The {thing} is {polish}; {guard}.",
        "Diagnostics complete—{polish}. {valet}.",
        "I pre-warmed success; do stroll.",
        "Noise domesticated; only signal remains. {valet}.",
        "Confidence high; {guard}. Shall I continue?",
        "A graceful rollback waits behind velvet rope.",
    ],
    "ops": [
        "{ack}",
        "{ack} {ack}",
        "{ack} {ack} {ack}",
    ],
}

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
    if _intensity() >= 1.25 and line.endswith("."):
        line = line[:-1] + random.choice([".", "!", "!!"])
    return _finish_line(line)

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
    for _ in range(n * 3):
        line = _apply_daypart_flavor(key, _gen_one_line(key))
        low = line.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(f"{line}{_maybe_emoji(key, with_emoji)}")
        if len(out) >= n:
            break
    return out

def persona_header(persona_name: str) -> str:
    who = (persona_name or "neutral").strip()
    try:
        if 'lexi_quip' in globals() and callable(globals()['lexi_quip']):
            q = lexi_quip(who, with_emoji=False)
            q = (q or "").strip().replace("\n", " ")
            if len(q) > 140:
                q = q[:137] + "..."
            return f"💬 {who} says: {q}"
    except Exception:
        pass
    try:
        q2 = quip(who, with_emoji=False)
        q2 = (q2 or "").strip().replace("\n", " ")
        if len(q2) > 140:
            q2 = q2[:137] + "..."
        return f"💬 {who} says: {q2}" if q2 else f"💬 {who} says:"
    except Exception:
        return f"💬 {who} says:"

if __name__ == "__main__":
    for p in ["dude","chick","nerd","rager","comedian","action","jarvis","ops"]:
        print(f"[{p}] {{lexi_quip(p, with_emoji=False)}}")
