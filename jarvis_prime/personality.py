# /app/personality.py
# Persona quip engine for Jarvis Prime
# API: quip(persona_name: str, *, with_emoji: bool = True) -> str
# - Accepts many aliases (e.g., "the dude", "sheldon", "pesci", etc.)
# - Returns a one-liner in that persona’s voice (randomized)
# - Rager is allowed explicit profanity

import random

# ---- Canonical personas (8 total, locked) ----
PERSONAS = [
    "dude",       # The Dude + Bill & Ted
    "chick",      # Paris Hilton
    "nerd",       # Moss + Sheldon
    "rager",      # Samuel L. Jackson + Joe Pesci
    "comedian",   # Leslie Nielsen
    "action",     # Sly/Arnie/Mel/Bruce
    "jarvis",     # Iron Man AI
    "ops",        # Neutral ops mode
]

# ---- Aliases ----
ALIASES = {
    # Dude
    "the dude": "dude", "lebowski": "dude", "bill": "dude", "ted": "dude", "dude": "dude",
    # Chick
    "paris": "chick", "paris hilton": "chick", "chick": "chick",
    # Nerd (Moss + Sheldon)
    "nerd": "nerd", "sheldon": "nerd", "sheldon cooper": "nerd", "cooper": "nerd",
    "moss": "nerd", "the it crowd": "nerd", "it crowd": "nerd",
    # Rager (Sam L + Pesci)
    "rager": "rager", "angry": "rager", "rage": "rager",
    "sam": "rager", "sam l": "rager", "samuel": "rager", "samuel l jackson": "rager", "jackson": "rager",
    "joe": "rager", "pesci": "rager", "joe pesci": "rager",
    # Comedian (Leslie Nielsen)
    "comedian": "comedian", "leslie": "comedian", "leslie nielsen": "comedian", "nielsen": "comedian", "dry": "comedian",
    # Action
    "action": "action", "sly": "action", "stallone": "action",
    "arnie": "action", "arnold": "action", "schwarzenegger": "action",
    "mel": "action", "gibson": "action", "bruce": "action", "willis": "action",
    # Jarvis
    "jarvis": "jarvis", "ai": "jarvis", "majordomo": "jarvis",
    # Ops / Neutral
    "ops": "ops", "neutral": "ops", "no persona": "ops",
}

# ---- Emoji palettes (sprinkled randomly) ----
EMOJIS = {
    "dude":      ["🌴", "🕶️", "🍹", "🎳", "🧘", "🤙"],
    "chick":     ["💅", "✨", "💖", "👛", "🛍️", "💋"],
    "nerd":      ["🤓", "📐", "🧪", "🧠", "⌨️", "📚"],
    "rager":     ["🔥", "😡", "💥", "🗯️", "⚡", "🚨"],
    "comedian":  ["😂", "🎭", "😑", "🙃", "🃏", "🥸"],
    "action":    ["💪", "🧨", "🔫", "🛡️", "🚁", "🏹"],
    "jarvis":    ["🤖", "🧠", "🎩", "🪄", "📊", "🛰️"],
    "ops":       ["⚙️", "📊", "🧰", "✅", "📎", "🗂️"],
}

def _maybe_emoji(key: str, with_emoji: bool) -> str:
    if not with_emoji:
        return ""
    bank = EMOJIS.get(key) or []
    return f" {random.choice(bank)}" if bank else ""

# ---- Quip banks (20 each) ----
QUIPS = {
    "dude": [
        "The Dude abides.",
        "Far out—systems are chill.",
        "This really tied the stack together.",
        "Beverage optional, uptime mandatory.",
        "Most excellent, dude.",
        "Whoa—party on, sysadmins!",
        "All we are is dust in the wind, dude.",
        "Solid—metrics flow like a White Russian.",
        "Keep it simple, man. No drama.",
        "Roll with it, logs don’t lie.",
        "Abide and let the services ride.",
        "Bowling later? Stack first.",
        "That alert? Just your opinion, man.",
        "Chill, the system knows its groove.",
        "Slack is ephemeral; abiding is eternal.",
        "This deploy really tied the room together.",
        "Vibes: immaculate. Errors: minimal.",
        "Take ’er easy—healthchecks are green.",
        "If it crashes, we un-abide politely.",
        "Be excellent to each other—and to prod.",
    ],
    "chick": [
        "That’s hot.",
        "So cute, love that for you.",
        "Life’s too short to be boring—ship it.",
        "Adore. Screenshot it.",
        "Sliving—push complete.",
        "Darling, the graphs are giving.",
        "Ugh, glam even when it scales.",
        "Make it pink, then deploy.",
        "Literally obsessed with this uptime.",
        "Confidence is sexy—even in logs.",
        "This cluster? Iconic.",
        "Low-effort, high-vibes release.",
        "Couture, but make it Kubernetes.",
        "Extra, but necessary.",
        "We don’t ‘down’; we ‘glow’.",
        "Your dashboards? Designer.",
        "Zero-downtime? Très chic.",
        "Heels high, error rates low.",
        "Post it. Tag it. Ship it.",
        "Major serve—production ready.",
    ],
    "nerd": [  # Moss + Sheldon
        "This is the optimal outcome. Bazinga.",
        "No segfaults detected; dignity intact.",
        "Systems nominal; please refrain from touching.",
        "If it reboots again, I’m naming it Schrödinger.",
        "RTFM. Kindly.",
        "I possess the precise sarcasm for this scenario.",
        "That’s not chaos—it’s entropy. Important distinction.",
        "A patch! My kingdom for a patch!",
        "Knock, knock, knock—service. (x3)",
        "Your algorithm is inferior, but acceptable.",
        "Oh dear, someone pushed to main again.",
        "I drink milk while I debug. Judge me.",
        "Unsurprisingly, I was right.",
        "Did you seriously say ‘turn it off and on’? Barbaric.",
        "I made a flowchart for your feelings. It’s unhelpful.",
        "The proper term is ‘elegant’. You’re welcome.",
        "My standards are high. Your tests are not.",
        "It’s not a bug; it’s determinism being honest.",
        "I scheduled my sarcasm. You’re already late.",
        "Bazinga, but professionally.",
    ],
    "rager": [  # Sam L + Pesci; explicit profanity allowed
        "Say downtime again. I fucking dare you.",
        "Motherfucker, merge that branch!",
        "What am I, a clown? Do I amuse you? Deploy it!",
        "Hell yeah, ship the goddamn thing.",
        "Latency? Don’t fuck with me on latency.",
        "Push it now, or I’ll lose my goddamn mind.",
        "Perfect. Now don’t touch a fucking thing.",
        "Jesus Christ, this config is a nightmare.",
        "What kind of stupid shit commit is this?",
        "Get the fuck outta here with that excuse.",
        "I don’t want reasons, I want results.",
        "This is one badass packet storm.",
        "Logs don’t lie—assholes do.",
        "Do you even know what the fuck you’re doing?",
        "Move fast, break shit, curse later.",
        "That fix? Beautiful. Don’t fuck it up.",
        "We’re done talking—start deploying.",
        "Next person who pings me at 3am gets paged forever.",
        "Production is sacred—wipe your fucking feet.",
        "Good. Now get the hell out of prod.",
    ],
    "comedian": [  # Leslie Nielsen deadpan
        "I am serious. And don’t call me Shirley.",
        "Doing nothing is hard—you never know when you’re finished.",
        "Remarkably unremarkable.",
        "File under ‘works’.",
        "I’ve seen worse. Recently.",
        "Not the worst I’ve ever seen.",
        "Thrilling. Truly.",
        "This dashboard is funnier than me.",
        "Systems are stable—how dull.",
        "Stop me if you’ve heard this uptime before.",
        "Adequate. No applause needed.",
        "I’m impressed, and I never am.",
        "Well, isn’t that… functioning.",
        "Put that on my tombstone: ‘It compiled.’",
        "Try to contain your excitement.",
        "If boredom were uptime, we’d be heroes.",
        "Good news: nothing exploded. Yet.",
        "I prefer my errors shaken, not stirred. Wrong franchise.",
        "Add it to the list. No, the other list.",
        "It’s fine. That’s the joke.",
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
        "Cowabunga, build pipeline.",
        "System secured. Enemy terminated.",
        "Backup locked and loaded.",
        "Merge conflict? Kill it with fire.",
        "Queue the hero music—tests passed.",
        "Single-tenant? Single-handed victory.",
        "Scope creep neutralized.",
        "Release window is now—hit it.",
        "Ship it like you mean it.",
    ],
    "jarvis": [  # Iron Man’s AI tone
        "As always, sir, a great pleasure watching you work.",
        "Status synchronized, sir.",
        "Polished and filed for your review.",
        "Telemetry aligned; do proceed.",
        "Your request has been executed impeccably.",
        "All signals nominal; elegance maintained.",
        "Gracefully completed, as expected.",
        "Sir, I’ve anticipated the failure and patched accordingly.",
        "Power levels optimal; systems at your command.",
        "I exist to serve, sir.",
        "Uptime graph polished for presentation.",
        "Might I suggest a strategic reboot, sir?",
        "Pardon me, but that was flawless.",
        "System harmony has been restored.",
        "Of course, sir. Done before you asked.",
        "Diagnostics complete; no anomalies present.",
        "I’ve taken the liberty of tidying the logs.",
        "Encryption verified; perimeter secure.",
        "Shall I archive the artifacts, sir?",
        "A delight, sir. Truly.",
    ],
    "ops": [
        "ok.",
        "done.",
        "noted.",
        "executed.",
        "received.",
        "ack.",
        "stable.",
        "running.",
        "applied.",
        "patched.",
        "synced.",
        "completed.",
        "success.",
        "confirmed.",
        "ready.",
        "scheduled.",
        "queued.",
        "accepted.",
        "active.",
        "closed.",
    ],
}

# ---- Public API ----
def quip(persona_name: str, *, with_emoji: bool = True) -> str:
    """
    Return a short, randomized one-liner in the requested persona's voice.
    Unknown names map to 'ops'. Emojis can be toggled via with_emoji.
    """
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