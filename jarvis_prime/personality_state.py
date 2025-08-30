#!/usr/bin/env python3
# /app/personality_state.py
import os
import json
import datetime

CONFIG_PATH = "/data/options.json"
STATE_PATH = "/data/personality_state.json"

DEFAULT_PERSONA = "neutral"

def _load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_state(state):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Jarvis] ⚠️ Failed to save persona state: {e}", flush=True)

def _current_time_of_day(now=None):
    now = now or datetime.datetime.now()
    h = now.hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "evening"
    return "night"

def _enabled_personas(cfg: dict):
    # 1) explicit override string: active_persona: "dude"|"chick"|...
    ap = str(cfg.get("active_persona", "") or "").strip().lower()
    if ap and ap != "auto":
        return [ap]

    # 2) new-style map: personas_enabled: {dude:true,...}
    pe = cfg.get("personas_enabled")
    if isinstance(pe, dict) and pe:
        enabled = [p for p, v in pe.items() if v]
        if enabled:
            return enabled

    # 3) legacy flags: enable_dude, enable_chick, ...
    legacy = []
    for key in ("dude", "chick", "nerd", "angry", "dry", "ai", "neutral"):
        if cfg.get(f"enable_{key}", False):
            legacy.append(key)
    if legacy:
        return legacy

    # 4) fallback
    return [DEFAULT_PERSONA]

def get_active_persona():
    cfg = _load_config()
    enabled = _enabled_personas(cfg)

    # Single persona enabled → pick it
    if len(enabled) == 1:
        persona = enabled[0]
    else:
        # deterministic rotation by day-of-month so it feels stable
        day = datetime.datetime.now().day
        persona = enabled[day % len(enabled)]

    tod = _current_time_of_day()

    state = {"persona": persona, "time_of_day": tod}
    _save_state(state)
    return persona, tod

if __name__ == "__main__":
    p, tod = get_active_persona()
    print(f"[Jarvis] Active persona: {p} ({tod})")
