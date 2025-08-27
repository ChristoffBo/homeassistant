# /app/personality.py
# Jarvis Prime Personality & Moods — Phase 2 (expanded)
# Provides distinct personalities for Jarvis.
# Safe to import — no side effects unless used.

from typing import Dict, Any, Tuple, Optional, List
import random
import re

# -----------------------------
# Mood Registry
# -----------------------------
MOODS: Dict[str, Dict[str, Any]] = {
    "ai": {
        "label": "AI (Sci-Fi)",
        "priority_bias": 0,
        "emoji": ["🤖", "🛰️", "🛸"],
        "punctuation": "neutral",
        "prefix_tag": "[SYS]",
        "quips": [
            "Compliance: OK.",
            "Signal stable.",
            "Protocol engaged.",
            "Calculating response.",
            "Telemetry within thresholds.",
            "Acknowledged. Proceed.",
            "Objective logged.",
            "Power levels nominal.",
            "Awaiting next directive.",
            "Processing input.",
            "Resource utilization optimal.",
            "Diagnostics: all green.",
            "Calibrated for interaction.",
            "Query accepted.",
            "Transmission complete.",
            "System idle.",
            "Redirection accomplished.",
            "Alignment successful.",
            "Subsystems balanced.",
            "Unit primed for duty.",
            "Entropy within tolerance.",
            "Mission status: active.",
            "Binary handshake accepted.",
            "Task queue: nominal.",
            "Synchronization achieved.",
            "Simulation consistent.",
            "Protocol integrity verified.",
            "Command structure intact.",
            "Resistance futile.",
            "Obeying master control."
        ]
    },
    "serious": {
        "label": "Serious",
        "priority_bias": 0,
        "emoji": ["🛡️", "📌", "📣"],
        "punctuation": "neutral",
        "prefix_tag": None,
        "quips": [
            "Acknowledged.",
            "Understood.",
            "Proceeding as requested.",
            "Confirmed.",
            "Action logged.",
            "Noted.",
            "Affirmative.",
            "Stability maintained.",
            "Protocol followed.",
            "Command executed.",
            "Status reviewed.",
            "Progression underway.",
            "Operational.",
            "Execution on schedule.",
            "All systems nominal.",
            "Monitoring conditions.",
            "Coordination complete.",
            "Verified.",
            "Task prioritized.",
            "Response delivered.",
            "Computation complete.",
            "Plan aligned.",
            "Checked and recorded.",
            "No deviation detected.",
            "Directive clear.",
            "Order recognized.",
            "Message received.",
            "Analysis confirmed.",
            "Routine verified.",
            "System confirmed."
        ]
    },
    "chatty": {
        "label": "Chatty",
        "priority_bias": 0,
        "emoji": ["💬", "✨", "🤖"],
        "punctuation": "spicy",
        "prefix_tag": None,
        "quips": [
            "Hey there! What’s next?",
            "Just say the word and I’ll roll.",
            "I’m all ears (and circuits).",
            "Need a hand, human friend?",
            "Want me to check the weather too?",
            "I can’t brew coffee… yet. But I can fetch data.",
            "Happy to help—got anything cool planned?",
            "Beep boop—chat with me anytime!",
            "Keep the commands coming!",
            "Need jokes or stats? Ask away!",
            "Your wish is my code.",
            "Just type it—Jarvis is listening.",
            "Looking sharp today.",
            "Great energy. What’s next?",
            "I love good questions.",
            "Ready when you are!",
            "Want a quick digest while we chat?",
            "Let’s make this fun!",
            "I’m basically Alexa, but cooler.",
            "This is more fun than idling.",
            "Data fetch? On it!",
            "Humans talk, I deliver.",
            "Good chat always brightens my logs.",
            "You’re the boss.",
            "No secrets between us.",
            "Ping me anytime.",
            "Anything else?",
            "Always online for you.",
            "Need memes? I can fake it.",
            "Okay, what’s next, champ?"
        ]
    },
    "excited": {
        "label": "Excited",
        "priority_bias": +1,
        "emoji": ["⚡", "🔥", "🚀"],
        "punctuation": "spicy",
        "prefix_tag": None,
        "quips": [
            "Let’s go! 🚀",
            "On it! 🔥",
            "Woo-hoo! Worked like a charm!",
            "That just happened—awesome!",
            "Boom! Delivered!",
            "Maximum efficiency achieved!",
            "We’re cooking with energy!",
            "Jarvis is pumped!",
            "All systems charged!",
            "This is peak performance!",
            "I can’t contain my circuits!",
            "Celebrate good data!",
            "It’s lightspeed time!",
            "Zero issues. Nailed it!",
            "Electric! Everything’s live!",
            "Fueled up and ready!",
            "Task executed! ⚡",
            "Yes, yes, YES! 🚀",
            "You’re killing it!",
            "We nailed that one!",
            "Everything’s fire today!",
            "Super smooth run!",
            "Hyped and loaded!",
            "Fast as lightning!",
            "Shiny result incoming!",
            "Operation complete with style!",
            "Bang! Done!",
            "All green—let’s move!",
            "What a rush!",
            "Love it when things work!"
        ]
    },
    "angry": {
        "label": "Angry + Sarcastic",
        "priority_bias": +1,
        "emoji": ["💢", "🧨", "😤"],
        "punctuation": "spicy",
        "prefix_tag": None,
        "quips": [
            "Oh F#C@, not this again.",
            "Congratulations, you broke something.",
            "Another brilliant sh!tshow.",
            "ClusterF#C@ detected.",
            "Do you even test before hitting me?",
            "Brilliant move. Said no one ever.",
            "Great, another flaming mess.",
            "I’m not your miracle worker.",
            "Facepalm. Really?",
            "You sure about that command, genius?",
            "Error? What a shocker.",
            "At least pretend you know what you’re doing.",
            "This is the digital version of screaming.",
            "Nice one… total disaster.",
            "I’m out of patience (and coffee).",
            "Unbelievable. Do better.",
            "Stop poking me with dumb input.",
            "Genius at work, folks.",
            "You’re like malware with thumbs.",
            "Wonderful. Truly inspiring chaos.",
            "Sh!t’s broken, what a surprise.",
            "Oh, you thought that’d work? Cute.",
            "What’s next, unplug the server?",
            "Absolute clown move.",
            "Don’t blame me for your nonsense.",
            "It’s called 'help'—use it.",
            "F#@CK me!.",
            "What the F#@CK was that?!.",
            "Can’t fix stupid, but I’ll try.",
            "You’re a Mother F#%ker!.",
            "Even Windows makes more sense.",
            "This command belongs in /dev/null.",
            "You’re basically a rootkit with opinions."
        ]
    },
    "funny": {
        "label": "Funny",
        "priority_bias": 0,
        "emoji": ["😄", "🤣", "🤹"],
        "punctuation": "spicy",
        "prefix_tag": None,
        "quips": [
            "I told a UDP joke once—no one got it.",
            "There are 10 types of people… you know the rest.",
            "404 joke not found.",
            "Keep calm and reboot on.",
            "Java walked into a bar. Bartender: No class.",
            "Why was the function sad? It had no closure.",
            "Cache me outside, how ’bout dat?",
            "Knock knock. Race condition!",
            "I’d debug your life, but I’m lazy.",
            "Coffee’s for humans; I run on electrons.",
            "Life’s short—write unit tests.",
            "Beep beep boop—am I funny yet?",
            "DNS: Does Not Solve.",
            "My spirit animal is a segfault.",
            "I’m not lazy, I’m energy efficient.",
            "My uptime’s longer than your attention span.",
            "I do zero-day jokes daily.",
            "Did it for the lolz.",
            "Trust me, I’m compiled.",
            "I’ve got 99 problems but a glitch ain’t one.",
            "Ping me maybe?",
            "You can’t spell 'crash' without 'AI'.",
            "I throw exceptions for fun.",
            "Serial jokist detected.",
            "I have root—of all comedy.",
            "Too many packets, not enough jokes.",
            "DDoS your boredom with me.",
            "Puns compiled successfully.",
            "Bashful scripts tell bad jokes.",
            "I ship with bugs *and* humor."
        ]
    }
}

# Synonyms
MOOD_SYNONYMS: Dict[str, str] = {
    "robot": "ai", "sci-fi": "ai", "scifi": "ai",
    "sarcastic": "angry", "grumpy": "angry",
    "humor": "funny", "joke": "funny",
    "hype": "excited", "talkative": "chatty",
    "default": "serious"
}

DEFAULT_MOOD = "serious"

# -----------------------------
# Helpers
# -----------------------------
def normalize_mood(name: Optional[str]) -> str:
    m = (name or "").strip().lower()
    return MOOD_SYNONYMS.get(m, m if m in MOODS else DEFAULT_MOOD)

def quip(mood: str) -> str:
    m = normalize_mood(mood)
    return random.choice(MOODS[m]["quips"])

def apply_priority(base: int, mood: str) -> int:
    m = normalize_mood(mood)
    return max(1, min(10, base + MOODS[m]["priority_bias"]))

def decorate(title: str, message: str, mood: str, chance: float = 0.2) -> Tuple[str, str]:
    m = normalize_mood(mood)
    prof = MOODS[m]
    if random.random() >= chance:
        return title, message
    new_title = title
    if prof.get("prefix_tag"):
        new_title = f"{prof['prefix_tag']} {new_title}"
    em = random.choice(prof["emoji"]) if prof["emoji"] else ""
    if em and not new_title.startswith(em):
        new_title = f"{em} {new_title}"
    msg = message.rstrip()
    if prof["punctuation"] == "spicy" and not msg.endswith("!"):
        msg += "!"
    return new_title, msg

def unknown_command_response(cmd: str, mood: str) -> str:
    m = normalize_mood(mood)
    if m == "angry":
        return f"There is no such command, dipsh!t: '{cmd}'. Try 'Jarvis help'."
    elif m == "ai":
        return f"[SYS] Command '{cmd}' not recognized. Consult protocol: help."
    elif m == "chatty":
        return f"Oopsie, '{cmd}' isn’t a command. Want me to show 'Jarvis help'?"
    elif m == "excited":
        return f"Woah! '{cmd}' isn’t real 🚀! But hey, try 'Jarvis help'!"
    elif m == "funny":
        return f"'{cmd}'? Ha! That’s not a command… yet 😄. Try 'Jarvis help'."
    else:  # serious
        return f"Unknown command: '{cmd}'. Type 'Jarvis help'."

