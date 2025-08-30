#!/usr/bin/env python3
# /app/personality_state.py — selector for personas (no moods)
import json, datetime

CONFIG_PATH = "/data/options.json"
STATE_PATH = "/data/personality_state.json"
DEFAULT_PERSONA = "neutral"

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

def _enabled_personas(cfg):
    # 1) explicit override: active_persona: "dude" | "ai" | ...
    ap = str(cfg.get("active_persona", "") or "").strip().lower()
    if ap and ap != "auto":
        return [ap]

    # 2) new map: personas_enabled: {dude:true,...}
    pe = cfg.get("personas_enabled")
    if isinstance(pe, dict) and pe:
        enabled = [p for p, v in pe.items() if v]
        if enabled:
            return enabled

    # 3) legacy flags
    legacy = [k for k in ("dude","chick","nerd","angry","dry","ai","neutral") if cfg.get(f"enable_{k}", False)]
    if legacy:
        return legacy

    return [DEFAULT_PERSONA]

def get_active_persona():
    cfg = _load(CONFIG_PATH)
    enabled = _enabled_personas(cfg)

    if len(enabled) == 1:
        persona = enabled[0]
    else:
        # deterministic rotation by day-of-month
        day = datetime.datetime.now().day
        persona = enabled[day % len(enabled)]

    tod = _tod()
    state = {"persona": persona, "time_of_day": tod}
    _save_state(state)
    return persona, tod

if __name__ == "__main__":
    p, t = get_active_persona()
    print(f"{p} ({t})")
