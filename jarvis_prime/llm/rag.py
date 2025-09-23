#!/usr/bin/env python3
# /app/rag.py
#
# RAG entity collector for Jarvis Prime (REST version)
# Builds rag_facts.json by calling Home Assistant /api/states
#
# Output (atomic writes):
#   /share/jarvis_prime/memory/rag_facts.json  (primary, human-visible)
#   /data/rag_facts.json                       (fallback)

import os, json, re, urllib.request
from datetime import datetime
from typing import Dict, Any, List

# --- Where to read HA connection from (your options.json has these) ---
OPTIONS_PATHS = ["/data/options.json", "/data/config.json"]

# ---- OUTPUT CONFIG (primary in /share, fallback in /data) ----
OUTPUT_PRIMARY_DIRS = ["/share/jarvis_prime/memory", "/share/jarvis_prime"]
OUTPUT_FALLBACK_PATH = "/data/rag_facts.json"
OUTPUT_BASENAME = "rag_facts.json"

# --- Keyword groups for boosting ---
SOLAR_KEYWORDS   = {"axpert", "inverter", "pv", "grid", "battery", "solar", "soc"}
ZIGBEE_KEYWORDS  = {"zigbee", "zigbee2mqtt", "z2m", "zha", "linkquality", "lqi", "rssi"}
TASMOTA_KEYWORDS = {"tasmota"}
PHONE_KEYWORDS   = {"phone", "mobile"}
PERSON_KEYWORDS  = {"person", "device_tracker"}

# --- Canonical name mapping (customize for household) ---
NAME_MAP = {
    "sam-phone": "Sam",
    "sonoff-temp-study": "Study Temp",
    "sonoff-snzb-02d": "Living Room Temp",
}

def _load_options() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    for p in OPTIONS_PATHS:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    cfg.update(data)
        except Exception:
            pass
    return cfg

def _http_get_json(url: str, headers: Dict[str, str], timeout: int = 25):
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))

def normalize_name(eid: str) -> str:
    e = eid.lower().replace("_", " ")
    for k, v in NAME_MAP.items():
        if k in e:
            return v
    if "." in e:
        e = e.split(".", 1)[1]
    return e.strip()

def extract_value(state: str):
    try:
        if state is None:
            return None
        if re.match(r"^-?\d+(\.\d+)?$", state):
            return float(state) if "." in state else int(state)
        return state
    except Exception:
        return state

def _write_json_atomic(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def _boost_for_entity_id(eid_lower: str):
    score = 1
    source = "ha"
    if any(k in eid_lower for k in SOLAR_KEYWORDS):
        score += 5; source = "solar"
    if any(k in eid_lower for k in ZIGBEE_KEYWORDS):
        score += 3; source = "zigbee"
    if any(k in eid_lower for k in TASMOTA_KEYWORDS):
        score += 2; source = "tasmota"
    if any(k in eid_lower for k in PHONE_KEYWORDS) or "device_tracker" in eid_lower:
        score += 2; source = "phone"
    if any(k in eid_lower for k in PERSON_KEYWORDS):
        score += 2; source = "person"
    return score, source

def collect_facts(limit_per_entity: int = 5):
    opts = _load_options()
    base = (opts.get("llm_enviroguard_ha_base_url") or "").rstrip("/")
    token = (opts.get("llm_enviroguard_ha_token") or "").strip()

    if not base or not token:
        print("[RAG] Missing llm_enviroguard_ha_base_url or llm_enviroguard_ha_token in /data/options.json")
        return

    url = f"{base}/api/states"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        data = _http_get_json(url, headers, timeout=25)
    except Exception as e:
        print(f"[RAG] REST /api/states failed: {e}")
        return

    now = datetime.utcnow().isoformat()
    facts: List[Dict[str, Any]] = []

    for item in data if isinstance(data, list) else []:
        try:
            eid = str(item.get("entity_id") or "")
            state = str(item.get("state") or "")
            attrs = item.get("attributes") or {}
            last_upd = (item.get("last_updated") or item.get("last_changed") or "")

            if not eid or state in ("unknown", "unavailable", ""):
                continue

            eid_l = eid.lower()
            score, source = _boost_for_entity_id(eid_l)

            fact = {
                "entity_id": eid,
                "name": normalize_name(eid),
                "state": extract_value(state),
                "last_updated": last_upd,
                "score": score,
                "source": source,
            }

            # pick useful attributes if present
            for k in ["unit_of_measurement","battery_level","voltage","current","power",
                      "temperature","humidity","linkquality","lqi","rssi","device_class","friendly_name"]:
                if k in attrs:
                    fact[k] = attrs[k]

            # build summary
            parts = [fact["name"]]
            if fact.get("state") not in (None, "", "on", "off"):
                parts.append(str(fact["state"]))
            if "unit_of_measurement" in fact:
                parts.append(str(fact["unit_of_measurement"]))
            if "battery_level" in fact:
                parts.append(f"Battery {fact['battery_level']}%")
            if "temperature" in fact:
                parts.append(f"T={fact['temperature']}°C")
            if "humidity" in fact:
                parts.append(f"H={fact['humidity']}%")
            if "linkquality" in fact:
                parts.append(f"LQ={fact['linkquality']}")
            if "rssi" in fact:
                parts.append(f"RSSI={fact['rssi']}")
            if "lqi" in fact:
                parts.append(f"LQI={fact['lqi']}")
            fact["summary"] = " ".join(map(str, parts))

            facts.append(fact)
        except Exception:
            continue

    # sort + trim
    facts.sort(key=lambda x: (x["score"], x["last_updated"]), reverse=True)
    pruned, seen = [], {}
    for f in facts:
        eid = f["entity_id"]
        seen.setdefault(eid, 0)
        if seen[eid] < limit_per_entity:
            pruned.append(f); seen[eid] += 1

    result = {
        "generated_at": now,
        "facts": pruned,
        "count": len(pruned),
        "note": "Live context facts from Home Assistant via REST.",
        "write_targets": []
    }

    written = []
    for d in OUTPUT_PRIMARY_DIRS:
        try:
            p = os.path.join(d, OUTPUT_BASENAME)
            _write_json_atomic(p, result)
            written.append(p)
        except Exception as e:
            print(f"[RAG] write failed for {d}: {e}")
    try:
        _write_json_atomic(OUTPUT_FALLBACK_PATH, result)
        written.append(OUTPUT_FALLBACK_PATH)
    except Exception as e:
        print(f"[RAG] fallback write failed: {e}")

    result["write_targets"] = written
    if written:
        try:
            _write_json_atomic(written[0], result)  # include write_targets in primary
        except Exception:
            pass

    print(f"[RAG] wrote {len(pruned)} facts to: " + " | ".join(written))

if __name__ == "__main__":
    collect_facts()