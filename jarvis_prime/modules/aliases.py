
# aliases.py — Canonical command normalization for Jarvis Prime
# This module is optional; bot.py will import normalize_cmd() if present.

import json
import re

# ---- Canonical command names (must match bot.py routes) ----
CANON = {
    "dns",
    "kuma",
    "weather",
    "forecast",
    "arr",
    "chat",
    "digest",
}

# ---- Built‑in aliases (left -> canonical right) ----
DEFAULT_ALIASES = {
    # DNS
    "dns": "dns",
    "technitium": "dns",
    "adguard": "dns",

    # Uptime Kuma
    "kuma": "kuma",
    "uptime": "kuma",
    "monitor": "kuma",
    "status": "kuma",

    # Weather
    "weather": "weather",
    "temp": "weather",
    "temps": "weather",
    "temperature": "weather",
    "now": "weather",
    "today": "weather",
    "current": "weather",

    "forecast": "forecast",
    "forcast": "forecast",
    "weekly": "forecast",
    "7day": "forecast",
    "7-day": "forecast",
    "7 day": "forecast",

    # ARR
    "arr": "arr",
    "radarr": "arr",
    "sonarr": "arr",
    "movie_count": "arr",
    "series_count": "arr",

    # Chat / joke
    "chat": "chat",
    "joke": "chat",

    # Digest
    "digest": "digest",
    "daily digest": "digest",
    "summary": "digest",
}

def _load_custom_aliases() -> dict:
    """
    Read user custom aliases from /data/options.json (key: custom_aliases).
    Accepts either a JSON object or a JSON string of an object.
    """
    try:
        with open("/data/options.json", "r") as f:
            raw_text = f.read()
        try:
            opts = json.loads(raw_text)
        except json.JSONDecodeError:
            # Some HA configs write YAML; try a simple key scan
            m = re.search(r"custom_aliases:\s*(\{.*\})", raw_text, re.S)
            if m:
                opts = {"custom_aliases": json.loads(m.group(1))}
            else:
                opts = {}
    except Exception:
        opts = {}

    val = opts.get("custom_aliases", {})
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            val = {}
    if not isinstance(val, dict):
        return {}

    out = {}
    for k, v in val.items():
        lk = str(k).strip().lower()
        lv = str(v).strip().lower()
        out[lk] = lv
    return out

# Build the alias map once
_ALIAS_MAP = DEFAULT_ALIASES.copy()
_ALIAS_MAP.update(_load_custom_aliases())

# ---- Public API -------------------------------------------------------------
def normalize_cmd(cmd: str) -> str:
    """
    Normalize a raw message title/body into a canonical command token.
    - Case-insensitive.
    - Strips wake words like "jarvis - " or "jarvis ".
    - Collapses whitespace.
    - Applies built-in and user-defined aliases.
    Returns either a canonical token (e.g., "weather", "forecast", "kuma", "dns", "arr", "chat", "digest")
    or the cleaned input if no alias matched.
    """
    s = (cmd or "").strip()
    s = re.sub(r"\s+", " ", s)
    s_low = s.lower()

    # Trim wake-word prefixes
    for prefix in ("jarvis - ", "jarvis — ", "jarvis–", "jarvis —", "jarvis—", "jarvis ", "jarvis: "):
        if s_low.startswith(prefix):
            s = s[len(prefix):].strip()
            s_low = s.lower()
            break

    # Fast path exact match
    if s_low in _ALIAS_MAP:
        return _ALIAS_MAP[s_low]

    # Try common single-word intents inside longer strings
    tokens = s_low.split()
    for t in tokens:
        if t in _ALIAS_MAP:
            return _ALIAS_MAP[t]

    # No mapping; return cleaned, lower-cased input for bot.py to handle generically
    return s_low
