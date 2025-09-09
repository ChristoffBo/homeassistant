#!/usr/bin/env python3
# /app/personality_state.py — selector for personas (no moods)
import json, datetime

CONFIG_PATH = "/data/options.json"
STATE_PATH = "/data/personality_state.json"

# Canonical personas in your new set
NEW_PERSONAS = (
    "dude", "chick", "nerd", "rager", "comedian", "action", "jarvis", "ops",
    "tappit",  # ADDITIVE: hidden Easter egg persona
)

# Choose ops as the safe/default baseline (your “no personality”)
DEFAULT_PERSONA = "ops"

def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_state(state):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def _tod(now=None):
    now = now or datetime.datetime.now()
    h = now.hour
    if 5 <= h < 12: return "morning"
    if 12 <= h < 17: return "afternoon"
    if 17 <= h < 22: return "evening"
    return "night"

def _canonical(name: str) -> str:
    """
    Map any legacy or sloppy values into your new canonical set.
    """
    n = (name or "").strip().lower()
    if not n:
        return DEFAULT_PERSONA

    # direct hits
    if n in NEW_PERSONAS:
        return n

    # legacy → new
    if n in ("angry",):      return "rager"
    if n in ("dry",):        return "comedian"
    if n in ("ai",):         return "jarvis"
    if n in ("neutral",):    return "ops"

    # a few common aliases/typos
    if n in ("boss", "ironman", "stark", "jarvis prime"): return "jarvis"
    if n in ("support", "helpdesk", "opsy", "operator"):  return "ops"
    if n in ("action-hero", "hero", "actionhero"):        return "action"

    # ADDITIVE: tappit aliases
    if n in ("welkom", "tappet"): return "tappit"

    # fall back
    return DEFAULT_PERSONA

def _enabled_personas(cfg):
    """
    Build the enabled persona pool from:
      1) active_persona (explicit override)
      2) personas_enabled dict (new style)
      3) per-flag booleans (both new & legacy for compatibility)
    """
    # 1) explicit override
    ap = str(cfg.get("active_persona", "") or "").strip().lower()
    if ap and ap not in ("auto", "random"):
        return [_canonical(ap)]

    # 2) new map: personas_enabled: {dude:true, ...}
    pe = cfg.get("personas_enabled")
    if isinstance(pe, dict) and pe:
        enabled = []
        for k, v in pe.items():
            if v:
                enabled.append(_canonical(k))
        enabled = [p for p in enabled if p in NEW_PERSONAS]
        if enabled:
            # de-dup while preserving order
            seen = set(); out = []
            for p in enabled:
                if p not in seen:
                    seen.add(p); out.append(p)
            return out

    # 3) new boolean flags (preferred)
    new_flags = []
    for key in NEW_PERSONAS:
        if cfg.get(f"enable_{key}", False):
            new_flags.append(key)
    if new_flags:
        return new_flags

    # 4) legacy boolean flags → map to new
    legacy_map = {
        "angry": "rager",
        "dry": "comedian",
        "ai": "jarvis",
        "neutral": "ops",
        "dude": "dude",
        "chick": "chick",
        "nerd": "nerd",
    }
    legacy_enabled = []
    for legacy_key, mapped in legacy_map.items():
        if cfg.get(f"enable_{legacy_key}", False):
            legacy_enabled.append(mapped)
    if legacy_enabled:
        # de-dup
        seen = set(); out = []
        for p in legacy_enabled:
            if p not in seen:
                seen.add(p); out.append(p)
        return out

    # nothing configured → default
    return [DEFAULT_PERSONA]

def get_active_persona():
    cfg = _load(CONFIG_PATH)
    enabled = _enabled_personas(cfg)

    # Always keep the pool within the canonical set
    enabled = [p for p in enabled if p in NEW_PERSONAS] or [DEFAULT_PERSONA]

    if len(enabled) == 1:
        persona = enabled[0]
    else:
        # deterministic rotation by day-of-month (stable, no RNG)
        day = datetime.datetime.now().day
        persona = enabled[day % len(enabled)]

    tod = _tod()
    state = {"persona": persona, "time_of_day": tod, "pool": enabled}
    _save_state(state)
    return persona, tod

# ADDITIVE: force persona switch at runtime
def set_active_persona(name: str):
    """
    Force a persona at runtime (used for wakeword triggers).
    Persists until changed or reset.
    """
    persona = _canonical(name)
    state = {"persona": persona, "time_of_day": _tod(), "pool": [persona]}
    _save_state(state)
    return persona

if __name__ == "__main__":
    p, t = get_active_persona()
    print(f"{p} ({t})")
