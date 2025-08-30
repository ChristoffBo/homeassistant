#!/usr/bin/env python3
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
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[Jarvis] ⚠️ Failed to save persona state: {e}", flush=True)

def _current_time_of_day():
    hour = datetime.datetime.now().hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 22:
        return "evening"
    else:
        return "night"

def get_active_persona():
    cfg = _load_config()
    personas_enabled = cfg.get("personas_enabled", {})
    enabled_personas = [p for p, v in personas_enabled.items() if v]

    if not enabled_personas:
        return DEFAULT_PERSONA, _current_time_of_day()

    # Simple deterministic selection: rotate based on day of month
    day = datetime.datetime.now().day
    persona = enabled_personas[day % len(enabled_personas)]
    tod = _current_time_of_day()

    state = {"persona": persona, "time_of_day": tod}
    _save_state(state)
    return persona, tod

if __name__ == "__main__":
    persona, tod = get_active_persona()
    print(f"[Jarvis] Active persona: {persona} ({tod})")
