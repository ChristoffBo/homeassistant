#!/usr/bin/env python3
# /app/rag.py
#
# Home Assistant RAG fetcher (read-only, REST)
# - Reads HA URL + token from /data/options.json (/data/config.json fallback)
#   using keys: llm_enviroguard_ha_base_url, llm_enviroguard_ha_token
# - Includes: sensor, binary_sensor, light, switch, person, device_tracker
# - Ecosystems boosted: SolarAssistant, ZHA (native Zigbee), Zigbee2MQTT (z2m), Sonoff, Tasmota, MQTT
# - Promotes attribute-only values (battery %, solar metrics) to synthetic facts
# - Writes /data/rag_facts.json with both detailed facts and grouped summaries
# - inject_context(user_msg, top_k=5): returns top-k fact lines for the LLM
#
# Privacy: person/device_tracker summarized as zones (no GPS by default)
# Safe: read-only (never calls HA /api/services)

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

# Domains to include
INCLUDE_DOMAINS = {"sensor", "binary_sensor", "light", "switch", "person", "device_tracker"}

# Toggle GPS leakage for people (False = zone-only)
PERSON_INCLUDE_GPS = False

# Keyword families (ranking)
SOLAR_KEYWORDS    = {"solar", "solar_assistant", "solarassistant", "pv", "inverter", "soc", "battery", "grid", "load"}
ZIGBEE_KEYWORDS   = {"zigbee", "zigbee2mqtt", "z2m", "zha", "linkquality", "lqi", "rssi"}
SONOFF_KEYWORDS   = {"sonoff"}
TASMOTA_KEYWORDS  = {"tasmota"}
MQTT_KEYWORDS     = {"mqtt"}
RADARR_KEYWORDS   = {"radarr"}
SONARR_KEYWORDS   = {"sonarr"}

# Device-class boosts
DEVICE_CLASS_PRIORITY = {
    "motion": 6,
    "presence": 6,
    "occupancy": 5,
    "door": 4,
    "opening": 4,
    "window": 3,
    "battery": 4,
    "temperature": 3,
    "humidity": 2,
    "power": 4,
    "energy": 3
}

# Attribute keys commonly holding battery % (ZHA/Z2M/Sonoff/Tasmota/phones)
BATTERY_ATTR_KEYS = [
    "battery", "battery_level", "battery_soc", "batterylevel",
    "battery_percent", "battery_percentage", "Battery", "BatteryPercentage"
]

# Solar metrics frequently found as attributes (some payloads do this)
ATTR_SOLAR_KEYS = {
    "inverter_load":        ("Inverter Load", "W"),
    "inverter_output_power":("Inverter Output Power", "W"),
    "load_power":           ("Load Power", "W"),
    "load_apparent_power":  ("Load Apparent Power", "VA"),
    "pv_power":             ("PV Power", "W"),
    "pv_input_power":       ("PV Input Power", "W"),
    "grid_import_power":    ("Grid Import", "W"),
    "grid_export_power":    ("Grid Export", "W"),
    "grid_power":           ("Grid Power", "W"),
    "battery_power":        ("Battery Power", "W"),
    "battery_soc":          ("Battery SOC", "%"),
}

# Synonyms to make retrieval robust
QUERY_SYNONYMS = {
    "soc": ["soc", "state_of_charge", "battery_soc", "battery"],
    "solar": ["solar", "pv", "generation", "inverter", "array"],
    "pv": ["pv", "solar"],
    "load": ["load", "power", "w", "kw", "consumption", "apparent"],
    "grid": ["grid", "import", "export"],
    "battery": ["battery", "soc", "charge", "capacity"],
    "presence": ["presence", "motion", "occupancy"],
    "where": ["where", "location", "zone", "home", "work", "present"],
    "zigbee": ["zigbee", "z2m", "zigbee2mqtt", "zha"],
    "tasmota": ["tasmota"],
    "phone": ["phone", "mobile", "android", "ios"],
    "lights": ["light", "lights", "on", "illumination"],
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
    # dedupe preserving order
    out, seen = [], set()
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
    # Prefer user-friendly zone; avoid raw lat/lon in summaries
    zone = attrs.get("zone") or attrs.get("friendly_zone_name")
    if zone:
        return zone
    if isinstance(state, str) and state.lower() in ("home", "not_home"):
        return "Home" if state.lower() == "home" else "Away"
    return state or "unknown"

def _looks_like_battery_sensor(entity_id: str, device_class: str, unit: str) -> bool:
    eid = (entity_id or "").lower()
    return (
        device_class == "battery"
        or "_battery" in eid
        or eid.endswith(".battery")
        or unit.strip() == "%"
    )

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

            # -------- People / trackers (privacy-friendly) --------
            if domain in {"person", "device_tracker"}:
                where = _safe_zone_from_tracker(state, attrs)
                summary = f"{name} → Location: {where}"
                if PERSON_INCLUDE_GPS and "latitude" in attrs and "longitude" in attrs:
                    try:
                        lat = float(attrs.get("latitude"))
                        lon = float(attrs.get("longitude"))
                        summary += f" (GPS {lat:.4f},{lon:.4f})"
                    except Exception:
                        pass
                recent = _short_iso(last_changed)
                if recent:
                    summary += f" (as of {recent})"
                score = 6  # make presence easy to retrieve
                facts.append({
                    "entity_id": entity_id,
                    "domain": domain,
                    "device_class": device_class,
                    "friendly_name": name,
                    "state": where,
                    "unit": "",
                    "last_changed": last_changed,
                    "summary": summary,
                    "score": score
                })
                # Battery often lives as attribute on trackers
                for k in BATTERY_ATTR_KEYS:
                    if k in attrs:
                        raw = attrs.get(k)
                        if raw is None or str(raw).strip() in ("unknown","unavailable",""):
                            continue
                        show = _fmt_num(str(raw), "%")
                        bsum = f"{name} Battery: {show}"
                        facts.append({
                            "entity_id": f"{entity_id}#{k}",
                            "domain": domain,
                            "device_class": "battery",
                            "friendly_name": f"{name} Battery",
                            "state": str(raw),
                            "unit": "%",
                            "last_changed": last_changed,
                            "summary": bsum,
                            "score": 7
                        })
                continue  # handled

            # ------------------ Generic entity path ------------------
            # Main summary
            show_state = _upper_if_onoff(state) if state else ""
            if unit and state not in ("on", "off", "open", "closed"):
                show_state = _fmt_num(state, unit)

            summary = f"{name}"
            if device_class:
                summary += f" ({device_class})"
            if show_state:
                summary += f": {show_state}"

            recent = _short_iso(last_changed)
            if domain in ("binary_sensor","sensor") and recent:
                summary += f" (as of {recent})"

            # Base score + ecosystem boosts
            score = 1
            toks = _tok(entity_id) + _tok(name) + _tok(device_class)
            tok_join = "_".join(toks)
            if any(k in toks for k in SOLAR_KEYWORDS):   score += 6
            if any(k in toks for k in ZIGBEE_KEYWORDS):  score += 3
            if any(k in toks for k in SONOFF_KEYWORDS):  score += 3
            if any(k in toks for k in TASMOTA_KEYWORDS): score += 3
            if any(k in toks for k in MQTT_KEYWORDS):    score += 2
            if any(k in toks for k in RADARR_KEYWORDS):  score += 2
            if any(k in toks for k in SONARR_KEYWORDS):  score += 2
            score += DEVICE_CLASS_PRIORITY.get(device_class, 0)

            # Extra emphasis for SOC sensors
            if "state of charge" in name.lower() or "soc" in name.lower():
                score += 6

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

            # Promote battery as attribute (when not already a dedicated battery sensor)
            if not _looks_like_battery_sensor(entity_id, device_class, unit):
                for k in BATTERY_ATTR_KEYS:
                    if k in attrs:
                        raw = attrs.get(k)
                        if raw is None or str(raw).strip() in ("unknown","unavailable",""):
                            continue
                        show = _fmt_num(str(raw), "%")
                        attr_summary = f"{name} Battery: {show}"
                        af = {
                            "entity_id": f"{entity_id}#{k}",
                            "domain": domain,
                            "device_class": "battery",
                            "friendly_name": f"{name} Battery",
                            "state": str(raw),
                            "unit": "%",
                            "last_changed": last_changed,
                            "summary": attr_summary,
                            "score": 3
                        }
                        # Small ecosystem nudges
                        if any(x in tok_join for x in ("zigbee","zigbee2mqtt","z2m","sonoff","mqtt","tasmota")):
                            af["score"] += 2
                        facts.append(af)

            # Promote solar metrics from attributes (when present)
            if any(k in tok_join for k in ("solar","solarassistant","inverter","pv","grid","battery")):
                for k, (label, unit_hint) in ATTR_SOLAR_KEYS.items():
                    if k in attrs:
                        val = attrs.get(k)
                        if val is None or str(val).strip() in ("unknown","unavailable",""):
                            continue
                        show = _fmt_num(str(val), unit_hint)
                        ssum = f"{name} {label}: {show}"
                        base = 4
                        facts.append({
                            "entity_id": f"{entity_id}#{k}",
                            "domain": domain,
                            "device_class": device_class or "",
                            "friendly_name": f"{name} {label}",
                            "state": str(val),
                            "unit": unit_hint,
                            "last_changed": last_changed,
                            "summary": ssum,
                            "score": base + DEVICE_CLASS_PRIORITY.get(device_class or "", 0)
                        })

        except Exception:
            continue

    # Cap runaway files (very high deployments)
    if len(facts) > 20000:
        facts.sort(key=lambda f: f.get("score", 0), reverse=True)
        facts = facts[:20000]
    return facts

# -----------------------------
# Grouped summaries (overviews)
# -----------------------------
def _build_overviews(facts: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Helpers
    def _is_on(f):  return str(f.get("state","")).lower() == "on"
    def _is_light(f): return f.get("domain") == "light"
    def _is_battery_summary(s): return " battery:" in s.lower()
    def _pct_val(s):  # parse "74 %" etc.
        try:
            m = re.search(r"(-?\d+(?:\.\d+)?)\s*%?", s)
            return float(m.group(1)) if m else None
        except Exception:
            return None

    presence = []
    for f in facts:
        if f.get("domain") in ("person","device_tracker") and "Location:" in f.get("summary",""):
            presence.append({"name": f.get("friendly_name",""), "where": f.get("state","")})

    lights_on = [f.get("friendly_name","") for f in facts if _is_light(f) and _is_on(f)]

    # Batteries (try dedicated battery facts first, then device_class:battery sensors)
    batteries = []
    for f in facts:
        summ = f.get("summary","")
        if _is_battery_summary(summ) or f.get("device_class") == "battery":
            val = _pct_val(summ) if summ else None
            if val is None:
                try:
                    val = float(f.get("state",""))
                except Exception:
                    val = None
            batteries.append({
                "name": f.get("friendly_name",""),
                "percent": val
            })
    low_batts = sorted([b for b in batteries if isinstance(b.get("percent"), (int,float)) and b["percent"] <= 30],
                       key=lambda x: (x["percent"] if x["percent"] is not None else 999))

    # Solar overview (simple roll-up if present)
    solar = {"pv_power_w": 0.0, "load_power_w": 0.0, "grid_import_w": 0.0, "grid_export_w": 0.0, "battery_soc_pct": []}
    for f in facts:
        s = f.get("summary","").lower()
        try:
            if " pv power:" in s:
                solar["pv_power_w"] += float(re.search(r"(-?\d+(?:\.\d+)?)", s).group(1))
            elif " load power:" in s:
                solar["load_power_w"] += float(re.search(r"(-?\d+(?:\.\d+)?)", s).group(1))
            elif " grid import:" in s:
                solar["grid_import_w"] += float(re.search(r"(-?\d+(?:\.\d+)?)", s).group(1))
            elif " grid export:" in s:
                solar["grid_export_w"] += float(re.search(r"(-?\d+(?:\.\d+)?)", s).group(1))
            elif "state of charge" in s or "battery soc" in s:
                m = re.search(r"(-?\d+(?:\.\d+)?)", s)
                if m:
                    solar["battery_soc_pct"].append(float(m.group(1)))
        except Exception:
            pass

    # Compose overviews
    over = {
        "presence_overview": {
            "people": presence,
            "count_home": sum(1 for p in presence if str(p["where"]).lower() == "home"),
        },
        "lights_overview": {
            "on_count": len(lights_on),
            "on_names": lights_on[:30]  # cap long lists
        },
        "batteries_overview": {
            "low_batteries": low_batts[:30],
            "avg_battery_pct": round(sum(b["percent"] for b in batteries if isinstance(b.get("percent"), (int,float))) / max(1, sum(1 for b in batteries if isinstance(b.get("percent"), (int,float)))), 1) if batteries else None
        },
        "solar_overview": {
            "pv_power_w": round(solar["pv_power_w"], 2),
            "load_power_w": round(solar["load_power_w"], 2),
            "grid_import_w": round(solar["grid_import_w"], 2),
            "grid_export_w": round(solar["grid_export_w"], 2),
            "avg_battery_soc_pct": round(sum(solar["battery_soc_pct"]) / max(1, len(solar["battery_soc_pct"])), 2) if solar["battery_soc_pct"] else None
        }
    }
    return over

# -----------------------------
# Public API
# -----------------------------
def refresh_and_cache() -> List[Dict[str, Any]]:
    """Fetch states and update rag_facts.json"""
    global _LAST_REFRESH_TS
    cfg = _load_options()
    facts = _fetch_ha_states(cfg)
    over = _build_overviews(facts)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "facts": facts,
        "overviews": over,
        "count": len(facts)
    }
    with _CACHE_LOCK:
        try:
            with open(FACTS_PATH, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            pass
        _LAST_REFRESH_TS = time.time()
    return facts

def load_cached() -> Dict[str, Any]:
    try:
        with open(FACTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"facts": [], "overviews": {}}

def get_facts(force_refresh: bool = False) -> List[Dict[str, Any]]:
    global _LAST_REFRESH_TS
    if force_refresh or (time.time() - _LAST_REFRESH_TS > REFRESH_INTERVAL_SEC):
        refresh_and_cache()
    obj = load_cached()
    return obj.get("facts", [])

def inject_context(user_msg: str, top_k: int = DEFAULT_TOP_K) -> str:
    """Return top-k matching fact summaries for user_msg (synonym-aware)"""
    q_raw = _tok(user_msg)
    q_toks = set(_expand_query_tokens(q_raw)) if q_raw else set()
    obj = load_cached()
    facts = obj.get("facts", [])
    scored: List[Tuple[int, str]] = []
    for f in facts:
        score = int(f.get("score", 1))
        summary = f.get("summary", "") or ""
        f_toks = set(_tok(summary)) | set(_tok(f.get("entity_id","")))
        # direct token overlap
        if q_toks and (q_toks & f_toks):
            score += 3
        # nudges for common queries
        if {"inverter","load"} & q_toks and {"inverter","load","power","w","kw"} & f_toks:
            score += 2
        if {"battery","soc","charge"} & q_toks and "battery" in f_toks:
            score += 2
        if {"where","location","home","work"} & q_toks and (f.get("domain") in ("person","device_tracker")):
            score += 3
        if {"lights","light"} & q_toks and f.get("domain") == "light":
            score += 2
        scored.append((score, summary))
    top = sorted(scored, key=lambda x: x[0], reverse=True)[:max(1, int(top_k or DEFAULT_TOP_K))]
    return "\n".join([t[1] for t in top if t[1]])

if __name__ == "__main__":
    print("Refreshing RAG facts from Home Assistant...")
    facts = refresh_and_cache()
    print(f"Wrote {len(facts)} facts to {FACTS_PATH}")