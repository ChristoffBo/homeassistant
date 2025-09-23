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
# /share/jarvis_prime/memory/rag_facts.json → facts used by chatbot & notify

import os, json, sqlite3, re
from datetime import datetime

DB_PATHS = [
    "/config/home-assistant_v2.db",
    "/data/home-assistant_v2.db",
]

# --- new persistent path in /share ---
OUTPUT_PATH = "/share/jarvis_prime/memory/rag_facts.json"
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

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
    raise FileNotFoundError("No home-assistant_v2.db found")

def collect_facts(limit_per_entity: int = 5):
    conn = get_connection()
    cur = conn.cursor()
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
        if state in ("unknown", "unavailable", None, ""):
            continue
        try:
            attr = json.loads(attrs) if attrs else {}
        except Exception:
            attr = {}

        fact = {
            "entity_id": eid,
            "name": normalize_name(eid),
            "state": extract_value(state),
            "last_updated": last_upd,
            "score": 1,
            "source": "ha",
        }

        for k in ["unit_of_measurement", "battery_level", "voltage", "current",
                  "power", "temperature", "humidity", "linkquality", "lqi", "rssi"]:
            if k in attr:
                fact[k] = attr[k]

        if any(k in eid_l for k in SOLAR_KEYWORDS):
            fact["score"] += 5; fact["source"] = "solar"
        if any(k in eid_l for k in ZIGBEE_KEYWORDS):
            fact["score"] += 3; fact["source"] = "zigbee"
        if any(k in eid_l for k in TASMOTA_KEYWORDS):
            fact["score"] += 2; fact["source"] = "tasmota"
        if any(k in eid_l for k in PHONE_KEYWORDS) or "device_tracker" in eid_l:
            fact["score"] += 2; fact["source"] = "phone"
        if any(k in eid_l for k in PERSON_KEYWORDS):
            fact["score"] += 2; fact["source"] = "person"

        parts = [fact["name"]]
        if "state" in fact and fact["state"] not in (None, "", "on", "off"):
            parts.append(str(fact["state"]))
        if "unit_of_measurement" in fact:
            parts.append(fact["unit_of_measurement"])
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
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)

    print(f"[RAG] wrote {len(pruned)} facts to {OUTPUT_PATH}")

if __name__ == "__main__":
    collect_facts()