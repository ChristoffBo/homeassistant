#!/usr/bin/env python3
# /app/rag.py
#
# RAG entity collector for Jarvis Prime
# Builds rag_facts.json from Home Assistant state DB
#
# Sources:
# - SolarAssistant (Axpert, batteries, inverters, PV, grid)
# - HA sensors (Zigbee, Sonoff, Tasmota, MQTT)
# - Phones & persons (Sam’s phone, etc.)
#
# Output:
# /share/jarvis_prime/memory/rag_facts.json  (primary, human-visible)
# /data/rag_facts.json                       (fallback)
#
# Notes:
# - Atomic writes to avoid partial files
# - Creates /share/jarvis_prime/memory if missing
# - Prints all write locations to logs for easy confirmation

import os, json, sqlite3, re
from datetime import datetime

DB_PATHS = [
    "/config/home-assistant_v2.db",
    "/data/home-assistant_v2.db",
]

# ---- OUTPUT CONFIG (primary in /share, fallback in /data) ----
OUTPUT_PRIMARY_DIRS = ["/share/jarvis_prime/memory", "/share/jarvis_prime"]
OUTPUT_FALLBACK_PATH = "/data/rag_facts.json"
OUTPUT_BASENAME = "rag_facts.json"

# --- Keyword groups for boosting ---
SOLAR_KEYWORDS   = {"axpert", "inverter", "pv", "grid", "battery"}
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

# --- Helpers ---------------------------------------------------
def normalize_name(eid: str) -> str:
    eid = eid.lower().replace("_", " ")
    for k, v in NAME_MAP.items():
        if k in eid:
            return v
    if "." in eid:
        eid = eid.split(".", 1)[1]
    return eid.strip()

def extract_value(state: str):
    try:
        if state is None:
            return None
        if re.match(r"^-?\d+(\.\d+)?$", state):
            return float(state) if "." in state else int(state)
        return state
    except Exception:
        return state

def get_connection():
    for path in DB_PATHS:
        if os.path.exists(path):
            return sqlite3.connect(path)
    raise FileNotFoundError("No home-assistant_v2.db found in " + ", ".join(DB_PATHS))

def _write_json_atomic(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

# --- Main collector --------------------------------------------
def collect_facts(limit_per_entity: int = 5):
    conn = get_connection()
    cur = conn.cursor()

    # fetch last states for each entity
    cur.execute("""
        SELECT entity_id, state, attributes, last_updated
        FROM states
        WHERE last_updated = (
            SELECT MAX(last_updated) FROM states s2 WHERE s2.entity_id = states.entity_id
        )
    """)
    rows = cur.fetchall()
    conn.close()

    facts = []
    now = datetime.utcnow().isoformat()

    for eid, state, attrs, last_upd in rows:
        eid_l = eid.lower()

        # skip unknown/unavailable
        if state in ("unknown", "unavailable", None, ""):
            continue

        # parse attributes JSON
        try:
            attr = json.loads(attrs) if attrs else {}
        except Exception:
            attr = {}

        # base fact
        fact = {
            "entity_id": eid,
            "name": normalize_name(eid),
            "state": extract_value(state),
            "last_updated": last_upd,
            "score": 1,
            "source": "ha",
        }

        # include selected attributes
        for k in ["unit_of_measurement", "battery_level", "voltage", "current",
                  "power", "temperature", "humidity", "linkquality", "lqi", "rssi"]:
            if k in attr:
                fact[k] = attr[k]

        # scoring boosts
        if any(k in eid_l for k in SOLAR_KEYWORDS):
            fact["score"] += 5
            fact["source"] = "solar"
        if any(k in eid_l for k in ZIGBEE_KEYWORDS):
            fact["score"] += 3
            fact["source"] = "zigbee"
        if any(k in eid_l for k in TASMOTA_KEYWORDS):
            fact["score"] += 2
            fact["source"] = "tasmota"
        if any(k in eid_l for k in PHONE_KEYWORDS) or "device_tracker" in eid_l:
            fact["score"] += 2
            fact["source"] = "phone"
        if any(k in eid_l for k in PERSON_KEYWORDS):
            fact["score"] += 2
            fact["source"] = "person"

        # build summary for LLM context
        parts = [fact["name"]]
        if "state" in fact and fact["state"] not in (None, "", "on", "off"):
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

    # sort by score and recency
    facts.sort(key=lambda x: (x["score"], x["last_updated"]), reverse=True)

    # optional: trim per entity
    pruned = []
    seen = {}
    for f in facts:
        eid = f["entity_id"]
        seen.setdefault(eid, 0)
        if seen[eid] < limit_per_entity:
            pruned.append(f)
            seen[eid] += 1

    result = {
        "generated_at": now,
        "facts": pruned,
        "count": len(pruned),
        "note": "These are live context facts from your Home Assistant setup. Use them when answering questions about the home environment.",
        "write_targets": []  # will be filled below for debugging
    }

    # ---- write to /share first, then fallback to /data ----
    written_paths = []
    for d in OUTPUT_PRIMARY_DIRS:
        try:
            p = os.path.join(d, OUTPUT_BASENAME)
            _write_json_atomic(p, result)
            written_paths.append(p)
        except Exception as e:
            print(f"[RAG] write failed for {d}: {e}")
    # Always also write fallback
    try:
        _write_json_atomic(OUTPUT_FALLBACK_PATH, result)
        written_paths.append(OUTPUT_FALLBACK_PATH)
    except Exception as e:
        print(f"[RAG] fallback write failed: {e}")

    result["write_targets"] = written_paths

    # Re-write primary (first successful) including write_targets for full trace (non-fatal if fails)
    if written_paths:
        try:
            _write_json_atomic(written_paths[0], result)
        except Exception:
            pass

    print(f"[RAG] wrote {len(pruned)} facts to: " + " | ".join(written_paths))

if __name__ == "__main__":
    collect_facts()