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
        "filler": ["man","dude","bro","friend","pal"],
        "zen": ["abide","chill","vibe","float","breathe","mellow out"],
        "metaphor": ["wave","lane","groove","bowl","flow","vibe field"],
    },
    "chick": {
        "glam": ["slay","serve","sparkle","shine","glisten","elevate","polish"],
        "couture": ["velvet rope","runway","couture","lip gloss","heels","silk"],
        "judge": ["approved","iconic","camera-ready","main-character","on brand"],
    },
    "nerd": {
        "open": ["Actually,","In fact,","Formally,","Technically,"],
        "math": ["O(1)","idempotent","deterministic","bounded","strictly monotonic","total"],
        "nerdverb": ["instrument","prove","lint","benchmark","formalize","graph"],
    },
    "rager": {
        "curse": ["fuck","shit","damn","hell"],
        "insult": ["clown","jackass","cowboy","tourist","gremlin","rookie"],
        "command": ["fix it","ship it","pin it","kill it","roll it back","own it","do it now"],
        "anger": ["I mean it","no excuses","right now","capisce","today","before I snap"],
    },
    "comedian": {
        "meta": ["don’t clap","insert laugh track","try to look impressed","narrate this in italics","self-aware mode"],
        "dry": ["Adequate.","Fine.","Remarkable—if you like beige.","Thrilling stuff.","Peak normal."],
        "aside": ["allegedly","probably","I’m told","sources say","per my last joke"],
    },
    "action": {
        "ops": ["mission","exfil","fallback","perimeter","vector","payload","blast radius"],
        "bark": ["Move.","Execute.","Hold.","Advance.","Abort.","Stand by.","Engage."],
        "grit": ["no retreat","decisive","clean shot","on target","hardening","silent"],
    },
    "jarvis": {
        "valet": ["I took the liberty","It’s already handled","Might I suggest","With your permission","Discreetly done"],
        "polish": ["immaculate","exemplary","presentable","tasteful","elegant","measured"],
        "guard": ["risk minimized","graceful rollback prepared","secrets secured","entropy subdued"],
    },
    "ops": {
        "ack": ["ack.","done.","noted.","applied.","synced.","green.","healthy.","rolled back.","queued.","executed."]
    }
}

# --- Templates per persona (short, slot-filled, 140c max before daypart) -----
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

# Optional: quick manual test (kept inert unless run directly)
if __name__ == "__main__":
    for p in ["dude","chick","nerd","rager","comedian","action","jarvis","ops"]:
        print(f"[{p}] {lexi_quip(p, with_emoji=False)}")