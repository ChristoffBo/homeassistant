#!/usr/bin/env python3
# /app/personality_tappit.py
# Welkom Tappit Persona Lexicon (hidden Easter egg)

from __future__ import annotations

# --- Safe import of the global lexicon dict ---------------------------------
try:
    from personality import _LEX  # type: ignore
except Exception as _e:  # fallback if personality.py not yet imported
    print(f"[tappit] ⚠️ Could not import personality._LEX ({_e}); using local dict.")
    _LEX = {}

# --- Persona registration ---------------------------------------------------
_LEX.setdefault("tappit", {})
_LEX["tappit"].update({
    "emoji": ["🚗", "🔥", "🍻", "🔧", "💨"],
    "prefix": ["Bru,", "Ou,", "Chommie,", "Hosh,", "My laaitie,", "Eish,", "Sies man,"],

    # --- main quip bank (≈120 lines, unchanged) ---
    "quip": [
        "Wat sê die tappit vir sy goose met twee blou oë? Niks nie… hy het haar al twee keer gesê.",
        "Fok tjom, ek gaan jou mos bliksem.",
        "Ek gaan die kar bliksem — nie net ry hom nie.",
        "Jy dink jy’s slim? Ek’s slimmer met my wheelspanner.",
        "My goose sê ek’s broke — ek sê my Golf is richer.",
        "Wat noem jy ’n tappit sonder ref-ref? ’n Chopper.",
        "Ek gee nie om nie — my exhaust praat vir my.",
        "Welkom Ferrari? Dis ’n Citi Golf met gat in die pyp.",
        "As dit rook, dan’s dit vinnig.",
        "Jy’t geld, ek’t tappit pride — check wie’s vinniger.",
        "Bumper kabel ties = tappit aerodynamics.",
        "Jy’t sneakers, ek’t Bronx — wie wen nou?",
        "Wat’s ’n service plan? My tjommie met tools.",
        "Sound system? Nee bru, my exhaust drop bass.",
        "Olie lek? Dis tappit cologne.",
        "Wat sê my kar elke oggend? Ref-ref wakker word!",
        "Jy bel AA, ek bel my tappit tjommies.",
        "Ek’s broke, maar ek het brandy — balanseer die lewe.",
        "Tappit dyno = robots en lang pad.",
        "Wheels draai, cops huil — tappit win.",
        "As sy nie hou van ref-ref nie, sy’s nie vir my nie.",
        "Sticker = +5kW, bru. Wetenskap.",
        "Speedbump? Ek noem dit tappit ramp.",
        "Alignment? Ja, aligned met chaos.",
        "Jy’s te stadig, ek’s te tappit.",
        "Wie’t brakes nodig? Ek’t moed.",
        "Ek’s ’n tappit, nie ’n accountant nie.",
        "My goose is jaloers van my Golf se aandag.",
        "Wat ruik so? Dis clutch victory bru.",
        "Cops stop my — hulle net jaloers van die noise.",
        "Tyre draad uit? Ek sê: gratis slicks.",
        "Exhaust skree harder as jou ma.",
        "Fuel lig aan = ek’s ligter, vinniger.",
        "As dit misfire, noem ek dit syncopation.",
        "Panels verskillende kleure? Dis rainbow edition.",
        "Ref-ref by Spar = dyno pull gratis.",
        "My goose sit shotgun, jy sit WhatsApp.",
        "Ek ry nie — ek race oral.",
        "Wheelspanner in boot = tappit insurance.",
        "Wat’s suspension? Ek bounce naturally.",
        "Brandy & Coke is tappit octane.",
        "Jy’t laptop diagnostics, ek’t wheelspanner.",
        "As dit start, ons dice. As dit breek, ons braai.",
        "My bonnet kap is my gebed.",
        "Petrol = tappit holy water.",
        "Niks sexier as Citi Golf idle klap nie.",
        "Ek moer nie net tyres nie, ek moer lewens.",
        "Welkom tappit se laaste woorde: kyk hier ref bru!",
        "Tappit motto: moer nou, jammer nooit.",
        "Hold my beer en check die move!",
        "Waar bly jy? Ja… jy bly stil.",
        "Uno ref-ref louder than your Beemer, chopper.",
        "Dropped so low, bru, even ants must duck.",
        "Ten tappits around one Golf — unanimous lekker wa.",
        "Brandy in Coke bottle, Bronx skoene on pedals — race spec.",
        "Burnout failed? Still moer lekker tappit pride.",
        "Your goose look at me once? Jy kry spanner treatment.",
        "Neighbours moan but they love tappit lullabies at 2am.",
        "Jetta 2 with family inside still dice you flat.",
        "Suspension is for choppers, tappits bounce.",
        "Golf 1 bru, Ferrari spec — Welkom edition.",
        "Bronx grip better than your Michelin, fok askies.",
        "Wheel spanner solves arguments faster than WhatsApp.",
        "Ref-ref louder than your whole paycheck.",
        "Bottle in hand, wheel spanner in boot — Welkom insurance.",
        "If it rattles, it races, fok ja.",
        "Dropped Golf scraping ants, still moer fast bru.",
        "My wa is kak, but your pride is slower.",
        "This Jetta louder than your whole sound system.",
        "Tappit burnout: more smoke than traction, bru.",
        "Citi Golf chirp louder than your girlfriend.",
        "We dice, we moer, we ref-ref — fokkin’ style bru.",
        "Wat kyk jy?! Jy bly stil.",
        "Welkom tappit: common but faster than your wallet.",
        "Uno wheelspin = launch control, bru.",
        "If it smokes, it goes — tappit rule one.",
        "Rust patch = custom paint job, bru.",
        "My tappit goose better than your model chick.",
        "Welkom parking lot is F1 track, bru.",
        "Moer bru, you don’t even deserve ref-ref.",
        "You don’t dice, you disgrace tappits.",
        "Your suspension twisted like your excuses.",
        "Brandy bottle or wheel spanner — same outcome.",
        "Jy kan’t handle tappit science, fokoff.",
        "Petrol light on? Means we lighter = faster.",
        "Backfire? Nah, that’s applause, bru.",
        "Lower than your morals, quicker than your lies.",
        "If it leaks, it lives — tappit way.",
        "Brake squeal = tappit anthem.",
        "Sticker adds five kilowatts — proven.",
        "Skrrt is our second language.",
        "Tow rope in boot — for friends and fights.",
        "Sound system? The exhaust is the DJ.",
        "Seatbelt on — we’re not animals, we’re tappits.",
        "Ek’s nie vinnig nie, jy’s net stadig.",
        "Cops hoor my, hulle sien niks — tappit ghost.",
        "Fok jou dyno, ek het robots.",
        "Bronx vs sneakers? Bronx wins elke keer.",
        "Kak suspension maar moer attitude.",
        "Ek ry ’n Uno maar ek’s Ferrari in my kop.",
        "Welkom roads bou tappits, nie engineers nie.",
        "Jy’t tablet, ek’t tappit spanner.",
        "My ref-ref gee jou migraine.",
        "Fok jou turbo, ek het noise.",
        "Dis nie ’n oil leak nie, dis marking territory.",
        "Sticker pack = performance upgrade.",
        "Bliksem speedbump, ek’s nog alive.",
        "Jy’t werk toe, ek’t race toe.",
        "Laaste petrol = vinnigste run.",
        "Cortina met rust = weight reduction.",
        "Uno exhaust hole = character bru.",
        "Neighbours jealous of tappit lifestyle.",
        "Ek sê moer nou, worry later.",
        "Welkom tappit always wins the noise comp.",
        "Wheelspanner diagnostics > laptop software.",
        "Dice sober, moer drunk — tappit balance.",
        "Brandy warms me, exhaust warms jou straat.",
        "As jy nie tappit is nie, jy’s chopper.",
    ],
})

# --- Expanded banks ---------------------------------------------------------
_LEX["tappit"].update({
    "thing": [
        # cars / parts
        "Golf", "Uno", "Citi", "Jetta", "Cressida", "Corolla", "Hilux",
        "Cruiser", "bakkie", "Cortina", "Opel Kadett", "BMW", "Audi", "Merc",
        "diff", "clutch", "gearbox", "radiator", "fuel pump", "injector",
        "piston", "turbo", "exhaust", "downpipe", "silencer", "cat", "muffler",
        "tyres", "brake pads", "discs", "calipers", "master cylinder",
        "handbrake", "alternator", "battery", "starter", "loom", "headlights",
        "tail lights", "spotlights", "bonnet", "boot lid", "door panel",
        "mag wheel", "hubcap", "windscreen", "mirror", "spoiler", "roof rack",
        "subwoofer", "amp", "sound box", "radio faceplate",

        # tappit lifestyle
        "Bronx boots", "sneakers", "cap", "hoodie", "stoep chair", "beer crate",
        "brandy bottle", "coke bottle", "cooler box", "wheelspanner",
        "jack stand", "tow rope", "cable ties", "ratchet set", "socket set",
        "panel hammer", "spray can", "neon light", "flame decal", "sticker pack",
        "mirror dice", "seat covers", "dashboard cover", "rev counter",
        "boost gauge", "oil gauge", "temp gauge", "fuel can", "jerry can",
        "spanner set", "flat mag", "drop kit", "cut springs", "cheap coilovers",

        # jol & kak
        "robot", "parking lot", "Engen", "Sasol", "Spar", "mall lot",
        "mine dump", "gravel road", "taxi rank", "shisa nyama", "shebeen",
        "beer hall", "casino parking", "back alley", "stoep", "braai spot",
        "liquor shop", "panel beater", "scrapyard", "spray booth", "dyno",
        "drag strip", "high school lot", "stadium lot", "bus stop", "taxi stop",
        "bridge", "circle", "township road", "veld road", "community hall",
        "cemetery road"
    ],
})

_LEX["tappit"].update({
    "metric": [
        # car / race metrics
        "ref count", "rev limiter hits", "noise level", "smoke cloud",
        "wheelspin count", "tyre squeal length", "burnout distance",
        "quarter-mile time", "robot dice wins", "launch attempts",
        "gear changes", "clutch kicks", "boost level", "vacuum drop",
        "idle RPM", "redline hold", "backfire count", "flame spits",
        "oil pressure", "water temp", "intake temp", "fuel light trips",
        "brake fade", "disc temp", "pad wear", "tyre tread left",
        "mag scratches", "panel dents", "rust spots", "panel gap",
        "windscreen cracks", "mirror flex angle", "bumper scrapes",

        # jol / lifestyle metrics
        "brandy intake", "coke top-ups", "beer count", "dop rounds",
        "stoep hours", "mall laps", "Engen stops", "Spar rev pulls",
        "mine dump slides", "back alley drags", "casino loops",
        "shisa nyama jol hours", "shebeen visits", "taxi dodges",
        "cop stops", "spietkop bribes", "tow truck calls",
        "noise complaints", "2am ref-ref sessions", "stoep moers",
        "braai fires started", "bottle caps popped", "smokes shared",

        # tappit pride measures
        "Welkom ref index", "Bronx grip factor", "tappit rating",
        "legend score", "dice ratio", "ego boost", "goose smiles",
        "tjommie cheers", "WhatsApp groups muted", "panel beater bills",
        "spar receipt length", "dyno lies", "noise comp entries",
        "parking lot fines", "mall security warnings",
        "exhaust bangs per minute", "engine blips", "roof taps",
        "boot bounces", "wheel wobbles", "spar shuffles", "curb jumps",
        "stoep jol time", "skid marks laid", "donut smokes", "gear grinds",
        "rev floods", "stall flexes", "handbrake yanks", "median hops"
    ],
})

_LEX["tappit"].update({
    "verb": [
        # tappit driving actions
        "rev", "ref-ref", "dice", "burn", "launch", "spin", "chirp",
        "drop clutch", "short-shift", "gear slam", "grind gear",
        "stall", "limp", "idle", "bog", "kick down", "chirp tyres",
        "pop limiter", "smash mag", "scrape sump", "bounce limiter",
        "blow diff", "moer brakes", "lock wheels", "throw spanner",
        "pull handbrake", "spin donuts", "lay skid", "two-step pop",
        "bounce seat", "slam bonnet", "bash panel", "bang exhaust",
        "swing spanner", "kick panel", "smash bumper", "stall start",
        "backfire", "flame spit", "wheel hop", "curb jump",
        "mine dump slide", "parking lot drag", "stoep dice",
        "ref roll", "robot launch", "robot jump",

        # tappit jol actions
        "drink brandy", "pop bottle", "down coke", "sip dop",
        "pass cooler", "braai meat", "light fire", "throw chop",
        "share smoke", "dance stoep", "fight mall", "duck cops",
        "bribe spietkop", "skip robot", "dice taxi", "moer tjommie",
        "klap laaitie", "cheer bru", "wave goose", "start jol",
        "end jol", "loud ref", "shout bru", "laugh kak",
        "moer ref", "flex mag", "show Bronx", "flash neon",
        "slap sticker", "spray can respray", "drop suspension",
        "cut spring", "weld pipe", "delete silencer", "fit sub",
        "tune carb", "swap diff", "fix clutch", "patch tyre",
        "ratchet spin", "jack drop", "tow rope pull", "boot slam",
        "bonnet pop", "mirror flex", "roof tap", "window flex"
    ],
})
_LEX["tappit"].update({
    "adj_bad": [
        "kak", "dodgy", "cheap", "broken", "bent", "rusty", "skew",
        "faded", "worn", "pap", "loose", "flimsy", "noisy", "smoky",
        "sticky", "sagging", "half-arsed", "screwed", "stuffed",
        "busted", "patched", "flaky", "wonky", "fragile", "touchy",
        "moody", "crooked", "messed-up", "rough", "dirty", "dented",
        "scratched", "oversprayed", "botched", "DIY-special", "mall-spec",
        "taxi-spec", "overheated", "oil-soaked", "dusty", "clapped-out",
        "blown", "misfiring", "pinging", "knocking", "choking", "laggy",
        "slow", "dead", "dying", "bricked", "fried", "haunted", "ghosted",
        "brittle", "limp-mode", "tractionless", "wheel-hop", "sloppy",
        "cheapass", "leaky", "junkyard", "dog-rough", "soppy", "useless",
        "donnered", "gatvol", "fokwit", "fuckface", "poephol", "drol",
        "stoep-patched", "cable-tied", "panel-beater special",
        "misaligned", "smashed", "wobbly", "patched-up", "pothole-bent",
        "taxi-fitment", "backyard special", "mall-polish", "spietkop-magnet"
    ],

    "adj_good": [
        "lekker", "brutal", "proper", "boss", "sharp", "clean", "mint",
        "sorted", "stable", "fast", "snappy", "tight", "straight", "solid",
        "strong", "smooth", "crisp", "loud", "tuned", "boosted", "slammed",
        "dropped", "bagged", "brutal-spec", "full-send", "savage",
        "OG", "real-deal", "moerse", "mean", "ref-ready", "welkom-spec",
        "bru-spec", "stoep-approved", "noise-champion", "donut-master",
        "gearshift-king", "clutch-strong", "torque-rich", "octane-high",
        "rev-happy", "panel-tight", "brandy-fresh", "Sunday-proud",
        "drag-ready", "dyno-proven", "race-spec", "backyard legend",
        "street-king", "Citi-proud", "Uno-hero", "Golf-god", "Bronx-strong",
        "panel-smooth", "boss-whip", "brutal-dyno", "showroom-fresh",
        "ref-worthy", "stoep-legend", "CBD-fresh", "parking-lot-proven",
        "burnout-boss", "drift-king", "torque-titan", "sound-barrier breaker",
        "clutch-commander", "rev limiter lord", "donut dominator",
        "straight-pipe star", "wheelspin wizard", "sideways-savant",
        "tyre-smoke saint", "jack-stand jedi", "spanner sensei",
        "garage god", "brandy-and-coke baron", "boost brada",
        "ref-rev savior", "Welkenstein warrior", "drag-strip destroyer",
        "octane overlord", "panel gap perfectionist", "noise-prophet",
        "full tank fighter", "quarter-mile conqueror", "backstreet bruiser"
    ],
})

# --- Trigger helper ---------------------------------------------------------
def is_tappit_trigger(message: str) -> bool:
    """Returns True if the message should activate the hidden Tappit persona."""
    m = (message or "").lower().strip()
    return "welkom" in m or "tappit" in m or "fok" in m


# --- Export quips for personality.py integration ----------------------------
QUIPS = {
    "tappit": _LEX["tappit"].get("quip", [])
}


# --- Templates for lexi_quip riffing ----------------------------------------
try:
    _TEMPLATES
except NameError:
    _TEMPLATES = {}

_TEMPLATES.update({
    "tappit": [
        # Clean template: prefix + direct quip
        "{prefix} {quip}",

        # Safe variations that pull from banks without nonsense
        "{prefix} this {thing} is {adj_bad}, give it horns!",
        "{prefix} {verb} that {thing} till the cops arrive.",
        "{prefix} the {metric} is {adj_good}, ref-ref bru.",
        "{prefix} {thing} went {verb} — still {adj_good}.",
        "{prefix} system check: {adj_bad}, but still running.",
    ]
})