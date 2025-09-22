#!/usr/bin/env python3
# /app/rag.py
#
# RAG fetcher for Home Assistant
# - Reads HA URL + token from /data/options.json (/data/config.json fallback)
#   using existing keys: llm_enviroguard_ha_base_url, llm_enviroguard_ha_token
# - Focuses on lights, switches, sensors, binary_sensors, person, device_tracker
# - Boosts SolarAssistant, Sonoff, Zigbee, MQTT, Radarr, Sonarr entities
# - Summarizes facts into /data/rag_facts.json
# - Provides inject_context(user_msg, top_k=5) for the LLM (synonym-aware)
#
# Safe: read-only, never calls HA /api/services

import os
import re
import json
import time
import threading
from typing import Any, Dict, List, Tuple

import urllib.request

# -----------------------------
# Config / Paths
# -----------------------------
OPTIONS_PATHS = ["/data/options.json", "/data/config.json"]
FACTS_PATH    = "/data/rag_facts.json"

# Include these domains
INCLUDE_DOMAINS = {"light", "switch", "sensor", "binary_sensor", "person", "device_tracker"}

# Keywords to boost (Solar, Sonoff, Zigbee, MQTT, Radarr, Sonarr)
SOLAR_KEYWORDS   = {"solar", "solar_assistant", "pv", "inverter", "soc", "battery_soc", "battery", "grid", "load", "generation", "import", "export"}
SONOFF_KEYWORDS  = {"sonoff"}
ZIGBEE_KEYWORDS  = {"zigbee", "zigbee2mqtt", "z2m", "zha"}
MQTT_KEYWORDS    = {"mqtt"}
RADARR_KEYWORDS  = {"radarr"}
SONARR_KEYWORDS  = {"sonarr"}

# Device-class priority boosts
DEVICE_CLASS_PRIORITY = {
    "motion": 6,
    "presence": 6,
    "occupancy": 5,
    "door": 4,
    "opening": 4,
    "window": 3,
    "battery": 3,
    "temperature": 3,
    "humidity": 2,
    "power": 3,
    "energy": 3
}

# Query synonyms to make matching robust (SOC, PV, load, grid, etc.)
QUERY_SYNONYMS = {
    "soc": ["soc", "state_of_charge", "battery_soc", "battery"],
    "solar": ["solar", "pv", "generation", "inverter", "array"],
    "pv": ["pv", "solar"],
    "load": ["load", "power", "w", "kw", "consumption"],
    "grid": ["grid", "import", "export"],
    "battery": ["battery", "soc", "charge"],
    "where": ["where", "location", "zone", "home", "work", "present"],
    # add more as needed
}

REFRESH_INTERVAL_SEC = 15 * 60  # 15 minutes
DEFAULT_TOP_K = 5

_CACHE_LOCK = threading.RLock()
_LAST_REFRESH_TS = 0.0

# -----------------------------
# Helpers
# -----------------------------
def _load_options() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    for p in OPTIONS_PATHS:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    raw = f.read()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    try:
                        import yaml
                        data = yaml.safe_load(raw)
                    except Exception:
                        data = None
                if isinstance(data, dict):
                    cfg.update(data)
        except Exception:
            continue
    return cfg

def _http_get_json(url: str, headers: Dict[str, str], timeout: int = 20):
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))

def _domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else ""

def _upper_if_onoff(s: str) -> str:
    return s.upper() if s in ("on", "off", "open", "closed") else s

def _tok(s: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9_]+", s.lower() if s else "")

def _expand_query_tokens(tokens: List[str]) -> List[str]:
    expanded = []
    for t in tokens:
        expanded.extend(QUERY_SYNONYMS.get(t, [t]))
    # dedupe in-order
    out = []
    seen = set()
    for x in expanded:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def _short_iso(ts: str) -> str:
    return ts.replace("T"," ").split(".")[0].replace("Z","") if ts else ""

def _fmt_num(state: str, unit: str) -> str:
    try:
        v = float(state)
        if abs(v) < 0.005:
            v = 0.0
        s = f"{v:.2f}".rstrip("0").rstrip(".")
        return f"{s} {unit}".strip()
    except Exception:
        return f"{state} {unit}".strip() if unit else state

def _safe_zone_from_tracker(state: str, attrs: Dict[str, Any]) -> str:
    # Prefer zone name if available; avoid raw lat/lon in summaries.
    zone = attrs.get("zone")
    if zone:
        return zone
    if isinstance(state, str) and state.lower() in ("home", "not_home"):
        return "Home" if state.lower() == "home" else "Away"
    return state

# -----------------------------
# Fetch + summarize
# -----------------------------
def _fetch_ha_states(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    ha_url   = cfg.get("llm_enviroguard_ha_base_url", "").rstrip("/")
    ha_token = cfg.get("llm_enviroguard_ha_token", "")
    if not ha_url or not ha_token:
        return []

    url = f"{ha_url}/api/states"
    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    try:
        data = _http_get_json(url, headers=headers, timeout=25)
    except Exception:
        return []
    if not isinstance(data, list):
        return []

    facts: List[Dict[str, Any]] = []
    for item in data:
        try:
            entity_id = str(item.get("entity_id", ""))
            if not entity_id:
                continue
            domain = _domain_of(entity_id)
            if domain not in INCLUDE_DOMAINS:
                continue

            attrs = item.get("attributes", {}) or {}
            device_class = str(attrs.get("device_class", "")).lower()
            name = str(attrs.get("friendly_name", entity_id))
            state = str(item.get("state", ""))
            unit  = str(attrs.get("unit_of_measurement", "") or "")
            last_changed = str(item.get("last_changed", "") or "")

            # Domain-specific normalization
            if domain == "device_tracker":
                state = _safe_zone_from_tracker(state, attrs)

            # Build summary
            show_state = _upper_if_onoff(state) if state else ""
            if unit and state not in ("on", "off", "open", "closed"):
                show_state = _fmt_num(state, unit)

            summary = f"{name}"
            if device_class:
                summary += f" ({device_class})"
            if show_state:
                summary += f": {show_state}"

            recent = _short_iso(last_changed)
            if domain in ("person","device_tracker","binary_sensor","sensor") and recent:
                summary += f" (as of {recent})"

            # --- Scoring ---
            score = 1
            toks = _tok(entity_id) + _tok(name) + _tok(device_class)

            # Strong solar prioritization
            if any(k in toks for k in SOLAR_KEYWORDS):
                score += 6
            if "solar_assistant" in "_".join(toks) or "solarassistant" in "_".join(toks):
                score += 3

            # Existing boosts
            if any(k in toks for k in SONOFF_KEYWORDS):  score += 3
            if any(k in toks for k in ZIGBEE_KEYWORDS):  score += 2
            if any(k in toks for k in MQTT_KEYWORDS):    score += 2
            if any(k in toks for k in RADARR_KEYWORDS):  score += 3
            if any(k in toks for k in SONARR_KEYWORDS):  score += 3
            score += DEVICE_CLASS_PRIORITY.get(device_class, 0)
            if domain in ("person","device_tracker"):
                score += 5  # phones/people are highly relevant

            # de-boost spammy radio stats
            if entity_id.endswith(("_linkquality","_rssi","_lqi")):
                score -= 2

            facts.append({
                "entity_id": entity_id,
                "domain": domain,
                "device_class": device_class,
                "friendly_name": name,
                "state": state,
                "unit": unit,
                "last_changed": last_changed,
                "summary": summary,
                "score": score
            })
        except Exception:
            continue
    return facts

# -----------------------------
# Public API
# -----------------------------
def refresh_and_cache() -> List[Dict[str, Any]]:
    """Fetch states and update rag_facts.json"""
    global _LAST_REFRESH_TS
    cfg = _load_options()
    facts = _fetch_ha_states(cfg)
    with _CACHE_LOCK:
        try:
            with open(FACTS_PATH, "w", encoding="utf-8") as f:
                json.dump(facts, f, indent=2)
        except Exception:
            pass
        _LAST_REFRESH_TS = time.time()
    return facts

def load_cached() -> List[Dict[str, Any]]:
    try:
        with open(FACTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def get_facts(force_refresh: bool = False) -> List[Dict[str, Any]]:
    global _LAST_REFRESH_TS
    if force_refresh or (time.time() - _LAST_REFRESH_TS > REFRESH_INTERVAL_SEC):
        return refresh_and_cache()
    return load_cached()

def inject_context(user_msg: str, top_k: int = DEFAULT_TOP_K) -> str:
    """Return top-k matching facts for user_msg (synonym aware)"""
    q_toks_raw = _tok(user_msg)
    q_toks = set(_expand_query_tokens(q_toks_raw))
    facts = get_facts()
    scored: List[Tuple[int, str]] = []
    for f in facts:
        score = f.get("score", 1)
        if q_toks:
            f_toks = set(_tok(f.get("summary", "")) + _tok(f.get("entity_id", "")))
            if q_toks & f_toks:
                score += 3
            if ({"solar","pv","inverter","soc","battery"}.intersection(q_toks)
                and any(k in f_toks for k in SOLAR_KEYWORDS)):
                score += 2
        scored.append((score, f.get("summary", "")))
    top = sorted(scored, key=lambda x: x[0], reverse=True)[:top_k]
    return "\n".join([t[1] for t in top if t[1]])

if __name__ == "__main__":
    print("Refreshing RAG facts from Home Assistant...")
    facts = refresh_and_cache()
    print(f"Wrote {len(facts)} facts to {FACTS_PATH}")