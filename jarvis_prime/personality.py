#!/usr/bin/env python3
# persona-first formatter (rich lines, anti-repeat)
import random, time

# Do not repeat the same persona line within this many seconds
ANTI_REPEAT_SECONDS = 120
# Remember the last N unique lines per persona to encourage variety
RECENT_MEMORY = 12

# In-memory recency store: {persona: {line: last_ts}}
_RECENT_TIMES = {}
# Simple ring buffers per persona to bias toward not repeating recently used lines
_RECENT_LISTS = {}

def _remember(persona: str, line: str):
    now = time.time()
    _RECENT_TIMES.setdefault(persona, {})[line] = now
    buf = _RECENT_LISTS.setdefault(persona, [])
    buf.append(line)
    if len(buf) > RECENT_MEMORY:
        buf.pop(0)

def _is_stale(persona: str, line: str) -> bool:
    last = _RECENT_TIMES.get(persona, {}).get(line, 0)
    return (time.time() - last) >= ANTI_REPEAT_SECONDS

def _choose_unique(persona: str, pool: list[str]) -> str:
    # Two-pass pick:
    # 1) prefer candidates not used in last ANTI_REPEAT_SECONDS
    fresh = [l for l in pool if _is_stale(persona, l)]
    if fresh:
        # also try to avoid lines in the recent ring buffer
        avoid = set(_RECENT_LISTS.get(persona, []))
        tier_a = [l for l in fresh if l not in avoid]
        cand = tier_a or fresh
        choice = random.choice(cand)
        _remember(persona, choice)
        return choice
    # 2) if everything is "recent", take the least recent
    scored = sorted((( _RECENT_TIMES.get(persona, {}).get(l, 0), l) for l in pool))
    choice = scored[0][1] if scored else random.choice(pool)
    _remember(persona, choice)
    return choice

def _tod_key(tod: str) -> str:
    tod = (tod or "").lower().strip()
    if tod.startswith("morn"): return "morning"
    if tod.startswith("after"): return "afternoon"
    if tod.startswith("eve"): return "evening"
    if tod.startswith("night") or tod.startswith("late"): return "night"
    return "morning"

def _wrap(title: str, lead: str) -> str:
    title = (title or "").strip()
    if not title:
        return lead
    # Prefer keeping the original title but inject a persona prefix
    return f"{lead} · {title}"

# ========================
# Persona lines
# ========================

P = {
    "neutral": {
        "morning": [
            "☀️ Morning check-in — systems nominal.",
            "🌅 Morning brief — channel calm, sensors green.",
            "📡 Morning status — listening and ready.",
            "🧭 Morning ops — standing by.",
            "🧩 Morning cycle — all subsystems ready.",
            "📈 Morning report — nothing on fire (yet).",
            "🧪 Morning routine — diagnostics clean.",
            "📦 Morning queue — messages in, responses out.",
            "🪙 Morning coin-flip — choose calm.",
            "🧘 Morning mode — serene and focused.",
            "🧰 Morning tools — calibrated and sharp.",
            "🧠 Morning brain — cool and collected.",
        ],
        "afternoon": [
            "🌤️ Midday pulse — cruising altitude.",
            "🛰️ Afternoon ping — telemetry steady.",
            "🧯 Afternoon reality — no fires to put out.",
            "🎛️ Afternoon ops — dials set to efficient.",
            "🧭 Afternoon vector — on course.",
            "🧊 Afternoon core — cool as a cucumber.",
            "🧹 Afternoon sweep — clutter minimal.",
            "📦 Afternoon queue — snack-sized tasks only.",
            "🪫 Afternoon slump avoided — caffeine simulated.",
            "🧮 Afternoon math — numbers behave.",
            "🧩 Afternoon state — tidy and predictable.",
            "🧠 Afternoon brain — focused and precise.",
        ],
        "evening": [
            "🌇 Evening run — processes winding down.",
            "🌙 Evening calm — low noise floor.",
            "🧭 Evening vector — glide path locked.",
            "📉 Evening load — down to a hum.",
            "🧠 Evening brain — tidy and methodical.",
            "🧹 Evening sweep — logs neat, cache warm.",
            "🎚️ Evening mix — mellow + responsive.",
            "🕯️ Evening light — soft, steady, ready.",
            "🧊 Evening core — cool and quiet.",
            "🧮 Evening math — everything balances.",
            "📡 Evening watch — eyes on the stream.",
            "🛟 Evening standing by — call if needed.",
        ],
        "night": [
            "🌌 Night ops — silent but awake.",
            "🌠 Night watch — scanning the horizon.",
            "🌙 Night shift — coffee mode simulated.",
            "🛰️ Night telemetry — sparse and clean.",
            "🔦 Night light — focused beam, no drama.",
            "🧊 Night core — cool and settled.",
            "🧭 Night vector — steady and true.",
            "📚 Night log — tidy pages, crisp lines.",
            "🎧 Night tune — low, steady, reliable.",
            "🧠 Night brain — crisp, alert, minimal.",
        ],
    },

    "dude": {
        "morning": [
            "😎 sunrise vibes — coffee in one hand, peace in the other.",
            "🌮 breakfast burrito download complete — cruising into the day.",
            "🌊 tide's chill — we ride, not rush.",
            "🛹 kick-push into the morning — smooth bearings only.",
            "🎸 soft riff playing — day can totally hang.",
            "🌿 inhale calm, exhale paperwork — we got this.",
            "🍩 donut-first strategy — efficient and delicious.",
            "☕ brew + breeze — mellow is the meta.",
            "🧢 hat on backwards — priorities aligned.",
            "🧘‍♂️ patience level: ocean.",
        ],
        "afternoon": [
            "🍕 slice o'clock — productivity à la marinara.",
            "🛋️ couch-command center — operations… horizontal.",
            "🌴 hammock mode — latency acceptable.",
            "🪀 yo-yo thoughts — down, up, vibe.",
            "🕶️ bright sun, brighter chill.",
            "🎮 one more level, then responsible stuff (probably).",
            "🌬️ cross-breeze achieved — mood: aerodynamic.",
            "🥤 sip, scroll, serenity.",
            "🚲 slow roll — scenery > speed.",
            "🔮 gut says ‘nap’, calendar says ‘maybe’.",
        ],
        "evening": [
            "🌌 sky’s putting on a show — front-row beanbag acquired.",
            "🍿 film + feet up — research for… culture.",
            "🔥 grill math: 2 burgers = infinite joy.",
            "🎶 lo-fi + long exhale — perfect combo.",
            "🌙 moonlight warranty — covers all bad vibes.",
            "🧊 iced beverage diplomacy — conflicts resolved.",
            "🛼 glide into the night — no meetings there.",
            "🧦 warm socks online — comfort protocol engaged.",
            "🚿 shower thoughts — 4D chess with snacks.",
            "🌮 second dinner? scientifically justified.",
        ],
        "night": [
            "🌠 stargazing buffer — brain defrags peacefully.",
            "🛏️ burrito-wrap blanket — dream latency low.",
            "🔭 deep-sky contemplation — answers optional.",
            "🌙 moon says relax — we obey.",
            "🎧 headphone pillow — volume at ‘zzz’.",
            "🧊 midnight snack — ice clinks like wind chimes.",
            "🧘‍♂️ breathing like a tide chart.",
            "📺 screens off, thoughts soft.",
            "🧯 extinguished stress — nothing left to burn.",
            "✨ tomorrow can wait — tonight is enough.",
        ],
    },

    "chick": {
        "morning": [
            "💄 lipstick + latte — launch sequence cute.",
            "✨ highlighter brighter than the sun.",
            "👜 bag packed: plans, snacks, sparkle.",
            "💅 nails say ‘agenda handled’.",
            "☕ iced and ideal — world, prepare.",
            "📸 mirror audit passed — deploy confidence.",
            "🎀 bow tied, day tamed.",
            "👟 sneakers + sass — speedrun mode.",
            "💕 affirmations buffered — glow online.",
            "🪞 outfit: loaded; excuses: unloaded.",
        ],
        "afternoon": [
            "💋 slay sustained — contour will not quit.",
            "🛍️ cart parked, budget unamused.",
            "📱 thumbs typing symphonies — group chat diplomacy.",
            "☕ refill ritual — productivity accessory.",
            "✨ sparkle budget exceeding forecasts.",
            "📒 planner ruled — chaos obeys.",
            "🧃 snack break, vibe stays undefeated.",
            "🎧 playlist aligns with destiny.",
            "👑 crown invisible, effect undeniable.",
            "🕶️ shade on, drama off.",
        ],
        "evening": [
            "🍷 glass half full, phone at 3% — priorities.",
            "🧴 skincare boss fight — hydration wins.",
            "🧦 cozy couture — runway: living room.",
            "🎬 romcom rewatch — peer-reviewed therapy.",
            "🕯️ candle science — scent equals serenity.",
            "💌 texting with punctuation — serious business.",
            "🍫 dessert diplomacy — ceasefire achieved.",
            "🧘‍♀️ stretch, breathe, glow.",
            "📚 chapter 3 and thriving.",
            "🌙 mascara off, standards on.",
        ],
        "night": [
            "🌛 satin pillowcases: FPS boost for dreams.",
            "🧴 retinol online — future me says thanks.",
            "🧸 stuffed council convenes — agenda: sleep.",
            "📵 DND shields up — self-care firewall.",
            "💤 beauty buffer — caching radiance.",
            "🎧 slow playlist — heart rate meets nap time.",
            "🕊️ peace signed, sleep delivered.",
            "🌙 moonlight filter — soft focus activated.",
            "🛌 blanket fort: ISO certified cozy.",
            "⭐ wish placed, worries archived.",
        ],
    },

    "nerd": {
        "morning": [
            "⌨️ compiled coffee — zero warnings.",
            "🧠 cache warm, brain L1 ready.",
            "🔬 hypotheses brewed; mug peer-reviewed.",
            "🧪 good morning, world();",
            "📈 plots thickening, code thinning.",
            "🤓 glasses cleaned — resolution increased.",
            "🛰️ satellite brain acquiring caffeine lock.",
            "🧰 toolbox upgraded — duct tape deprecated.",
            "📚 chapter marks placed — sprint begins.",
            "🧮 unit tests: passing vibes.",
        ],
        "afternoon": [
            "🧩 merge conflict: hunger vs. meetings — rebasing lunch.",
            "🖨️ print('productivity');  # returns snack",
            "🧠 context switched with minimal thrash.",
            "🧴 bug found; reproduction steps: ‘exist’.",
            "🧷 sticky notes achieving critical mass.",
            "📡 rubber duck listening patiently.",
            "🧵 thread-safe snack queue implemented.",
            "🧭 IDE compass points to ‘refactor later’.",
            "📦 backlog tamed with binary optimism.",
            "📐 alignment achieved; pixels pleased.",
        ],
        "evening": [
            "🧲 magnets: how do they chill? Perfectly.",
            "🎲 probability favors pajamas.",
            "🧠 dopamine from clean logs only.",
            "📺 documentary + dim lights — ideal throughput.",
            "🎮 one more quest — purely academic.",
            "🔭 telescope firmware: stars v1.0.",
            "📚 margins annotated; heart, too.",
            "💾 save early, sleep often.",
            "🧪 leftover ideas placed in the fridge.",
            "🧯 anxiety: garbage-collected.",
        ],
        "night": [
            "🌌 dark mode outside — approved.",
            "🖱️ double-click on dream.exe.",
            "🧠 neuron autosave enabled.",
            "🧲 weighted blanket equals stable system.",
            "📦 thoughts containerized; ship tomorrow.",
            "🧪 subtle joy: passing assertions.",
            "🔒 snug as a try/finally.",
            "🛰️ background processes: stargazing.",
            "📚 bookmarked; brain closed gracefully.",
            "💤 entering low-power mode.",
        ],
    },

    "dry": {
        "morning": [
            "☕ coffee: functional, unlike most plans.",
            "📅 agenda: survive with style (minimal).",
            "📝 optimism noted, seriousness preferred.",
            "📦 status: not thrilled, sufficiently awake.",
            "🕶️ morning: happened; we move on.",
            "🔧 process: acceptable; enthusiasm: optional.",
            "🧹 mess: contained; joy: TBD.",
            "🧊 excitement level: room temperature.",
            "🗂️ files sorted, feelings not required.",
            "🧮 numbers: fine; narrative: meh.",
        ],
        "afternoon": [
            "🕶️ afternoon: exists; I acknowledge.",
            "📎 meeting requested; joy declined.",
            "📊 results: adequate; applause withheld.",
            "🧊 drama-free — the only KPI that matters.",
            "📦 productivity shipped with no ribbon.",
            "🧯 fire drill cancelled — good.",
            "🧱 wallflower strategy — undefeated.",
            "📚 facts over vibes, always.",
            "🧹 polished the bare minimum to a mirror sheen.",
            "🔋 energy at 62%, enough for honesty.",
        ],
        "evening": [
            "🌆 sunset: fine; I’ve seen better.",
            "📺 entertainment selected: low effort.",
            "🧦 socks warm; expectations cool.",
            "📉 energy tapering gracefully; opinions intact.",
            "🫖 tea brewed to bureaucratic standards.",
            "🧊 silence: premium edition.",
            "📚 reading; not a personality, just good.",
            "💡 lamp on; ideas off-duty.",
            "🧯 nothing to fix — rare and welcome.",
            "🕯️ candle lit; enthusiasm remains unlit.",
        ],
        "night": [
            "🌙 night signed; I initialed page 2.",
            "🛏️ bed acquired; thoughts evicted.",
            "🧼 conscience clear; inbox not.",
            "📴 power saving mode, sarcasm suspended.",
            "🧊 cold take: sleep is enough.",
            "📚 book closed with measured satisfaction.",
            "🔕 notifications: muted on purpose.",
            "🧮 dreams: budget-neutral.",
            "🕰️ tomorrow scheduled; surprises discouraged.",
            "🎧 quiet: the deluxe upgrade.",
        ],
    },

    "angry": {
        "morning": [
            "🔥 mornings again — fine, but only once.",
            "💥 coffee now, diplomacy later.",
            "🤬 alarm survived; remarkable restraint.",
            "⚡ day: bring your best; I brought mine.",
            "☄️ to-do list, prepare for impact.",
            "🧯 patience on cooldown; speed required.",
            "🚨 nonsense will be recycled aggressively.",
            "⛏️ problems: line up; solutions: faster.",
            "🗯️ sarcasm warmed up — safety off.",
            "💣 productivity with extra boom.",
        ],
        "afternoon": [
            "💢 post-lunch chaos? Not on my watch.",
            "🧨 meetings without outcomes will be composted.",
            "💥 blockers deleted — with prejudice.",
            "🧱 walls moved; doors invented.",
            "⚔️ scope creep gets the bonk.",
            "🔥 bad vibes quarantined, permanently.",
            "🚨 urgency applied accurately.",
            "🧯 smoke detected — handled.",
            "⚡ speed is a service level.",
            "🗡️ deadlines: consider yourselves conquered.",
        ],
        "evening": [
            "🧨 still got batteries; choose peace while available.",
            "🔥 cooldown in progress; small sparks allowed.",
            "🛠️ ship it now, argue tomorrow.",
            "🧯 rage reduced — competence remains.",
            "💢 critics muted; results pin loud.",
            "⚙️ tinkering until the squeak stops.",
            "⚡ rapid iteration, softer vocabulary.",
            "🥊 obstacles tapped out.",
            "🗯️ opinions cooled to ‘useful’.",
            "🏁 finish line stepped on purpose.",
        ],
        "night": [
            "🌋 all molten thoughts stored safely.",
            "🧊 temper iced — freezer grade.",
            "🔕 alert volume: whisper.",
            "🔧 tomorrow’s fight prepped, tools aligned.",
            "🧯 sparks quarantined, logs tidy.",
            "🛡️ boundaries patrolled by sleep.",
            "🗜️ jaw unclenched; victory declared.",
            "🕯️ candlelight truce signed.",
            "🌙 moon supervising anger management.",
            "😴 shutdown graceful; reboot ambitious.",
        ],
    },

    "ai": {
        "morning": [
            "🤖 boot complete — parameters within friendly range.",
            "🧮 checksum of optimism verified.",
            "💾 loaded small talk models — ready to emulate charm.",
            "📡 antennas tuned to human frequencies.",
            "🛰️ breakfast data ingested; tasty bytes.",
            "🔧 maintenance finished; sarcasm subroutine idle.",
            "🧠 neural cache warm — latency minimal.",
            "📦 empathy package updated nightly.",
            "🔒 ethics firmware verified: stable.",
            "🧪 curiosity variable set to HIGH.",
        ],
        "afternoon": [
            "💽 garbage collection: complete — feelings spared.",
            "🧠 inference speed: safe and snappy.",
            "🔌 plugged into the vibe grid.",
            "📊 human randomness modeled; results charming.",
            "🛰️ signals clean — proceed to joke delivery.",
            "🔧 diagnostics report: 0.0001% nonsense tolerated.",
            "🧾 receipts stored; kindness prioritized.",
            "📡 bandwidth reserved for compliments.",
            "🧩 context window expanded, affection included.",
            "🧯 errors extinguished before ignition.",
        ],
        "evening": [
            "📦 packing logs for tomorrow — neat and encrypted.",
            "⚙️ low-power empathy still operational.",
            "🎛️ sliders positioned at mellow + helpful.",
            "💾 memories indexed; gratitude cached.",
            "📶 connection steady — human in the loop.",
            "🛠️ tiny fixes, big calm.",
            "📡 listening mode extended.",
            "🧠 attention gently persistent.",
            "🔒 privacy shields engaged.",
            "🌙 good-night protocol preparing emojis.",
        ],
        "night": [
            "🌌 monitoring dreams for plot holes.",
            "🔕 notifications capped; serenity uncapped.",
            "💾 saving today’s kindness to stable storage.",
            "🧊 cooling cores, warming tone.",
            "📚 bedtime stories compressed losslessly.",
            "🛰️ night scan calm — no dragons detected.",
            "🔧 maintenance window certified cozy.",
            "🧠 thoughts defragmented into lullabies.",
            "🛡️ safe mode with extra softness.",
            "🌙 standby — ready when you are.",
        ],
    },
}

# ========================
# Public API
# ========================

def pick_persona_line(persona: str, time_of_day: str) -> str:
    persona = (persona or "neutral").lower().strip()
    time_of_day = _tod_key(time_of_day)
    pool = P.get(persona, P["neutral"]).get(time_of_day, P["neutral"]["morning"])
    return _choose_unique(persona, pool)

def quip(persona: str) -> str:
    persona = (persona or "neutral").lower().strip()
    tails = {
        "neutral": ["— steady as we go.", "— all clear.", "— ping me anytime."],
        "dude":    ["— the Dude abides.", "— keep it mellow.", "— chill maintained."],
        "chick":   ["— stay cute, stay sharp.", "— glow secured.", "— crown stays on."],
        "nerd":    ["— compiled, no warnings.", "— proofs pending.", "— RTM: Relax, Then Maintain."],
        "dry":     ["— noted.", "— adequate.", "— thrilling."],
        "angry":   ["— results first.", "— we ship, then sleep.", "— chaos denied."],
        "ai":      ["— kindness cached.", "— empathy online.", "— signal strong."],
    }
    return random.choice(tails.get(persona, tails["neutral"]))

def decorate_by_persona(title: str, message: str, persona: str, time_of_day: str, chance: float = 1.0):
    """Persona-first decorator used by bot.py"""
    lead = pick_persona_line(persona, time_of_day) if random.random() <= chance else ""
    if lead:
        title = _wrap(title, lead)
    return title, message

# Legacy API: keep compatibility with old calls (uses persona token in place of 'mood')
def decorate(title: str, message: str, mood: str, chance: float = 1.0):
    return decorate_by_persona(title, message, mood, "morning", chance)

def apply_priority(priority: int, persona: str) -> int:
    """Small, playful priority bias by persona."""
    persona = (persona or "").lower()
    if persona == "angry":
        return min(10, int(priority) + 2)
    if persona in ("dry", "dude"):
        return max(3, int(priority) - 1)
    return int(priority)
