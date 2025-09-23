#!/usr/bin/env python3
# /app/rag.py
#
# RAG entity collector for Jarvis Prime
# Builds rag_facts.json from Home Assistant (SQLite OR REST fallback)
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
# - Tries SQLite first (supports old/new schemas). Falls back to REST /api/states.
# - Atomic writes, creates /share folders, logs write targets + source used.

import os, json, sqlite3, re, urllib.request
from datetime import datetime

# ====== INPUT SOURCES ======
DB_PATHS = [
    "/config/home-assistant_v2.db",
    "/data/home-assistant_v2.db",
]
# Options file(s) to locate HA base URL and token for REST fallback
OPTIONS_PATHS = ["/data/options.json", "/data/config.json"]

# ====== OUTPUT TARGETS ======
OUTPUT_PRIMARY_DIRS = ["/share/jarvis_prime/memory", "/share/jarvis_prime"]
OUTPUT_FALLBACK_PATH = "/data/rag_facts.json"
OUTPUT_BASENAME = "rag_facts.json"

# ====== SCORING / NAME MAP ======
SOLAR_KEYWORDS   = {"axpert", "inverter", "pv", "grid", "battery", "soc"}
ZIGBEE_KEYWORDS  = {"zigbee", "zigbee2mqtt", "z2m", "zha", "linkquality", "lqi", "rssi"}
TASMOTA_KEYWORDS = {"tasmota"}
PHONE_KEYWORDS   = {"phone", "mobile"}
PERSON_KEYWORDS  = {"person", "device_tracker"}

NAME_MAP = {
    "sam-phone": "Sam",
    "sonoff-temp-study": "Study Temp",
    "sonoff-snzb-02d": "Living Room Temp",
}

# ====== HELPERS ======
def normalize_name(eid: str) -> str:
    eid_l = (eid or "").lower()
    for k, v in NAME_MAP.items():
        if k in eid_l:
            return v
    # strip domain + underscores
    if "." in eid_l:
        eid_l = eid_l.split(".", 1)[1]
    return eid_l.replace("_", " ").strip()

def extract_value(state: str):
    try:
        if state is None:
            return None
        if re.match(r"^-?\d+(\.\d+)?$", str(state)):
            return float(state) if "." in str(state) else int(state)
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

def _save_result(result: dict):
    written_paths = []
    # write to /share targets first
    for d in OUTPUT_PRIMARY_DIRS:
        try:
            p = os.path.join(d, OUTPUT_BASENAME)
            _write_json_atomic(p, result)
            written_paths.append(p)
        except Exception as e:
            print(f"[RAG] write failed for {d}: {e}")
    # always also write fallback
    try:
        _write_json_atomic(OUTPUT_FALLBACK_PATH, result)
        written_paths.append(OUTPUT_FALLBACK_PATH)
    except Exception as e:
        print(f"[RAG] fallback write failed: {e}")

    # store write_targets back into the primary file (best-effort)
    result["write_targets"] = written_paths
    if written_paths:
        try:
            _write_json_atomic(written_paths[0], result)
        except Exception:
            pass

    print(f"[RAG] wrote {result.get('count', 0)} facts to: " + " | ".join(written_paths))

def _load_options() -> dict:
    cfg = {}
    for p in OPTIONS_PATHS:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    raw = f.read()
                try:
                    data = json.loads(raw)
                except Exception:
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

# ====== REST FALLBACK ======
def _http_get_json(url: str, headers: dict, timeout: int = 25):
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def _collect_via_rest() -> list:
    opts = _load_options()
    ha_url   = (opts.get("llm_enviroguard_ha_base_url") or "").rstrip("/")
    ha_token = (opts.get("llm_enviroguard_ha_token") or "").strip()
    if not ha_url or not ha_token:
        print("[RAG] REST fallback unavailable: missing base_url or token in options")
        return []

    url = f"{ha_url}/api/states"
    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    try:
        data = _http_get_json(url, headers=headers, timeout=25)
    except Exception as e:
        print(f"[RAG] REST fetch failed: {e}")
        return []
    if not isinstance(data, list):
        return []

    out = []
    for item in data:
        eid = item.get("entity_id", "")
        state = item.get("state", "")
        attrs = item.get("attributes", {}) or {}
        last_changed = item.get("last_changed", "")
        if state in ("unknown", "unavailable", None, ""):
            continue

        rec = {
            "entity_id": eid,
            "name": normalize_name(eid),
            "state": extract_value(state),
            "last_updated": last_changed,
            "score": 1,
            "source": "ha"
        }
        # copy a few attributes
        for k in ["unit_of_measurement","battery_level","voltage","current","power",
                  "temperature","humidity","linkquality","lqi","rssi","device_class"]:
            if k in attrs:
                rec[k] = attrs[k]

        eid_l = (eid or "").lower()
        if any(k in eid_l for k in SOLAR_KEYWORDS):   rec["score"] += 5; rec["source"] = "solar"
        if any(k in eid_l for k in ZIGBEE_KEYWORDS):  rec["score"] += 3; rec["source"] = "zigbee"
        if any(k in eid_l for k in TASMOTA_KEYWORDS): rec["score"] += 2; rec["source"] = "tasmota"
        if any(k in eid_l for k in PHONE_KEYWORDS) or "device_tracker" in eid_l:
            rec["score"] += 2; rec["source"] = "phone"
        if any(k in eid_l for k in PERSON_KEYWORDS):
            rec["score"] += 2; rec["source"] = "person"

        parts = [rec["name"]]
        if rec.get("state") not in (None, "", "on", "off"):
            parts.append(str(rec["state"]))
        if "unit_of_measurement" in rec: parts.append(str(rec["unit_of_measurement"]))
        if "battery_level" in rec:       parts.append(f"Battery {rec['battery_level']}%")
        if "temperature" in rec:         parts.append(f"T={rec['temperature']}°C")
        if "humidity" in rec:            parts.append(f"H={rec['humidity']}%")
        if "linkquality" in rec:         parts.append(f"LQ={rec['linkquality']}")
        if "rssi" in rec:                parts.append(f"RSSI={rec['rssi']}")
        if "lqi" in rec:                 parts.append(f"LQI={rec['lqi']}")
        rec["summary"] = " ".join(map(str, parts))

        out.append(rec)

    print(f"[RAG] collected {len(out)} records via REST /api/states")
    return out

# ====== SQLITE (supports old/new schemas) ======
def _sqlite_paths() -> list:
    return [p for p in DB_PATHS if os.path.exists(p)]

def _table_has_column(cur, table: str, col: str) -> bool:
    try:
        cur.execute(f"PRAGMA table_info({table})")
        cols = [row[1] for row in cur.fetchall()]
        return col in cols
    except Exception:
        return False

def _collect_via_sqlite() -> list:
    paths = _sqlite_paths()
    if not paths:
        print("[RAG] SQLite not found at any known path")
        return []

    db = paths[0]
    print(f"[RAG] Using SQLite DB at {db}")
    try:
        conn = sqlite3.connect(db)
        cur = conn.cursor()

        # detect schema
        has_attrs_inline = _table_has_column(cur, "states", "attributes")
        has_attrs_id     = _table_has_column(cur, "states", "attributes_id")
        has_ts           = _table_has_column(cur, "states", "last_updated_ts")
        ts_col = "last_updated_ts" if has_ts else "last_updated"

        # build query for latest row per entity
        # inner: latest ts per entity
        # join back to states; join attributes depending on schema
        if has_attrs_inline:
            cur.execute(f"""
                WITH latest AS (
                  SELECT entity_id, MAX({ts_col}) AS ts
                  FROM states
                  GROUP BY entity_id
                )
                SELECT s.entity_id, s.state, s.attributes, s.{ts_col}
                FROM states s
                JOIN latest t
                  ON t.entity_id = s.entity_id AND t.ts = s.{ts_col}
            """)
            rows = cur.fetchall()
            def _attrs_from_row(rattrs):  # JSON text
                try:
                    return json.loads(rattrs) if rattrs else {}
                except Exception:
                    return {}
        else:
            # join state_attributes by attributes_id (new schema)
            cur.execute(f"""
                WITH latest AS (
                  SELECT entity_id, MAX({ts_col}) AS ts
                  FROM states
                  GROUP BY entity_id
                )
                SELECT s.entity_id, s.state, sa.shared_attrs, s.{ts_col}
                FROM states s
                LEFT JOIN state_attributes sa
                  ON sa.attributes_id = s.attributes_id
                JOIN latest t
                  ON t.entity_id = s.entity_id AND t.ts = s.{ts_col}
            """)
            rows = cur.fetchall()
            def _attrs_from_row(rattrs):  # shared_attrs JSON
                try:
                    return json.loads(rattrs) if rattrs else {}
                except Exception:
                    return {}

        out = []
        for eid, state, rattrs, ts in rows:
            # skip unknown/unavailable
            if state in ("unknown", "unavailable", None, ""):
                continue
            attrs = _attrs_from_row(rattrs)

            # convert ts to ISO if numeric
            try:
                if isinstance(ts, (int, float)):
                    last_upd = datetime.utcfromtimestamp(ts).isoformat()
                else:
                    last_upd = str(ts)
            except Exception:
                last_upd = str(ts)

            rec = {
                "entity_id": eid,
                "name": normalize_name(eid),
                "state": extract_value(state),
                "last_updated": last_upd,
                "score": 1,
                "source": "ha",
            }
            # copy some attrs
            for k in ["unit_of_measurement","battery_level","voltage","current","power",
                      "temperature","humidity","linkquality","lqi","rssi","device_class"]:
                if k in attrs:
                    rec[k] = attrs[k]

            eid_l = (eid or "").lower()
            if any(k in eid_l for k in SOLAR_KEYWORDS):   rec["score"] += 5; rec["source"] = "solar"
            if any(k in eid_l for k in ZIGBEE_KEYWORDS):  rec["score"] += 3; rec["source"] = "zigbee"
            if any(k in eid_l for k in TASMOTA_KEYWORDS): rec["score"] += 2; rec["source"] = "tasmota"
            if any(k in eid_l for k in PHONE_KEYWORDS) or "device_tracker" in eid_l:
                rec["score"] += 2; rec["source"] = "phone"
            if any(k in eid_l for k in PERSON_KEYWORDS):
                rec["score"] += 2; rec["source"] = "person"

            parts = [rec["name"]]
            if rec.get("state") not in (None, "", "on", "off"):
                parts.append(str(rec["state"]))
            if "unit_of_measurement" in rec: parts.append(str(rec["unit_of_measurement"]))
            if "battery_level" in rec:       parts.append(f"Battery {rec['battery_level']}%")
            if "temperature" in rec:         parts.append(f"T={rec['temperature']}°C")
            if "humidity" in rec:            parts.append(f"H={rec['humidity']}%")
            if "linkquality" in rec:         parts.append(f"LQ={rec['linkquality']}")
            if "rssi" in rec:                parts.append(f"RSSI={rec['rssi']}")
            if "lqi" in rec:                 parts.append(f"LQI={rec['lqi']}")
            rec["summary"] = " ".join(map(str, parts))

            out.append(rec)

        print(f"[RAG] collected {len(out)} records via SQLite")
        return out

    except Exception as e:
        print(f"[RAG] SQLite collection failed: {e}")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass

# ====== MAIN ======
def collect_facts(limit_per_entity: int = 5):
    # 1) Try SQLite
    records = _collect_via_sqlite()

    # 2) Fallback to REST if needed
    if not records:
        print("[RAG] falling back to REST /api/states …")
        records = _collect_via_rest()

    # If still nothing, write minimal debug file
    now = datetime.utcnow().isoformat()
    if not records:
        result = {
            "generated_at": now,
            "facts": [],
            "count": 0,
            "note": "No facts collected (check DB path or HA REST token/base_url).",
            "write_targets": [],
            "source": "none"
        }
        _save_result(result)
        return

    # sort by score/recency (best effort on recency using last_updated text/ts)
    def _ts_key(r):
        v = r.get("last_updated")
        try:
            if isinstance(v, (int, float)): return float(v)
            return datetime.fromisoformat(str(v).replace("Z","")).timestamp()
        except Exception:
            return 0.0

    records.sort(key=lambda x: (x.get("score", 1), _ts_key(x)), reverse=True)

    # trim per entity
    pruned, seen = [], {}
    for rec in records:
        eid = rec.get("entity_id")
        seen.setdefault(eid, 0)
        if seen[eid] < limit_per_entity:
            pruned.append(rec); seen[eid] += 1

    result = {
        "generated_at": now,
        "facts": pruned,
        "count": len(pruned),
        "note": "Live context facts from Home Assistant (SQLite or REST). Use when answering home questions.",
        "write_targets": [],
        "source": "sqlite" if _sqlite_paths() else "rest"
    }
    _save_result(result)

if __name__ == "__main__":
    collect_facts()