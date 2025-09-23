#!/usr/bin/env python3
# /app/rag.py  (REST → /api/states)
#
# - Reads HA URL + token from /data/options.json (/data/config.json fallback)
# - Pulls states via /api/states (read-only)
# - Summarizes/boosts entities and auto-categorizes them (no per-entity config)
# - Writes primary JSON to /share/jarvis_prime/memory/rag_facts.json
#   and also mirrors to /data/rag_facts.json as a fallback
# - inject_context(user_msg) returns a context block sized dynamically
#
# Safe: read-only, never calls HA /api/services

import os, re, json, time, threading, urllib.request
from typing import Any, Dict, List, Set

OPTIONS_PATHS = ["/data/options.json", "/data/config.json"]

# Primary (single target) + fallback
PRIMARY_DIRS   = ["/share/jarvis_prime/memory"]
FALLBACK_PATH  = "/data/rag_facts.json"
BASENAME       = "rag_facts.json"

# Include ALL domains
INCLUDE_DOMAINS = None  # None => include all domains

# Keywords/integrations commonly seen
SOLAR_KEYWORDS   = {"solar","solar_assistant","pv","inverter","ess","battery_soc","soc","battery","grid","load","generation","import","export"}
SONOFF_KEYWORDS  = {"sonoff"}
ZIGBEE_KEYWORDS  = {"zigbee","zigbee2mqtt","z2m","zha"}
MQTT_KEYWORDS    = {"mqtt"}
RADARR_KEYWORDS  = {"radarr"}
SONARR_KEYWORDS  = {"sonarr"}

# Device-class priority boosts
DEVICE_CLASS_PRIORITY = {
    "motion":6,"presence":6,"occupancy":5,"door":4,"opening":4,"window":3,
    "battery":3,"temperature":3,"humidity":2,"power":3,"energy":3
}

# Query synonyms (intent signals)
QUERY_SYNONYMS = {
    "soc": ["soc","state_of_charge","battery_state_of_charge","battery_soc","battery","charge","charge_percentage","soc_percentage","soc_percent"],
    "solar": ["solar","pv","generation","inverter","array","ess"],
    "pv": ["pv","solar"],
    "load": ["load","power","w","kw","consumption"],
    "grid": ["grid","import","export"],
    "battery": ["battery","soc","charge","state_of_charge","battery_state_of_charge","charge_percentage","soc_percentage","soc_percent"],
    # location-style queries
    "where": ["where","location","zone","home","work","present","presence","is"],
}

# Intent → categories
INTENT_CATEGORY_MAP = {
    "solar":   {"energy.storage","energy.pv","energy.inverter"},
    "pv":      {"energy.pv","energy.inverter","energy.storage"},
    "soc":     {"energy.storage"},
    "battery": {"energy.storage"},
    "grid":    {"energy.grid"},
    "load":    {"energy.load"},
    # NEW: treat "where" queries as person/location intent
    "where":   {"person"},
}

REFRESH_INTERVAL_SEC = 15*60
_CACHE_LOCK = threading.RLock()
_LAST_REFRESH_TS = 0.0

# ----------------- helpers -----------------

def _tok(s: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9_]+", s.lower() if s else "")

def _expand_query_tokens(tokens: List[str]) -> List[str]:
    out=[]; seen=set()
    for t in tokens:
        for x in QUERY_SYNONYMS.get(t,[t]):
            if x not in seen:
                seen.add(x); out.append(x)
    return out

def _safe_zone_from_tracker(state: str, attrs: Dict[str,Any]) -> str:
    zone = attrs.get("zone")
    if zone: return zone
    ls = (state or "").lower()
    if ls in ("home","not_home"): return "Home" if ls=="home" else "Away"
    return state

def _load_options() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    for p in OPTIONS_PATHS:
        try:
            if os.path.exists(p):
                with open(p,"r",encoding="utf-8") as f:
                    raw=f.read()
                try:
                    data=json.loads(raw)
                except json.JSONDecodeError:
                    try:
                        import yaml
                        data=yaml.safe_load(raw)
                    except Exception:
                        data=None
                if isinstance(data,dict):
                    cfg.update(data)
        except Exception:
            pass
    return cfg

def _http_get_json(url: str, headers: Dict[str,str], timeout: int=20):
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8","replace"))

def _write_json_atomic(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(obj,f,indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

# --------- categorization ---------

def _infer_categories(eid: str, name: str, attrs: Dict[str,Any], domain: str, device_class: str) -> Set[str]:
    cats:set[str] = set()
    toks = set(_tok(eid) + _tok(name) + _tok(device_class))
    manf = str(attrs.get("manufacturer","") or attrs.get("vendor","") or "").lower()
    model= str(attrs.get("model","") or "").lower()

    # People/locations
    if domain in ("person","device_tracker"):
        cats.add("person")

    # Energy related
    if any(k in toks for k in ("pv","inverter","ess","solar","solar_assistant","solarassistant")) \
       or any(k in manf for k in ("solar","solarassistant")) \
       or any(k in model for k in ("inverter","bms","battery")) \
       or "solar assistant" in (" ".join(_tok(name))):
        cats.add("energy")
        if any(k in toks for k in ("pv","solar")):
            cats.add("energy.pv")
        if any(k in toks for k in ("inverter","ess")) or "inverter" in model:
            cats.add("energy.inverter")
        if any(k in toks for k in ("soc","battery_soc","battery","state_of_charge","battery_state_of_charge")) or "bms" in model:
            cats.add("energy.storage")

    # Grid/load
    if any(k in toks for k in ("grid","import","export")):
        cats.update({"energy","energy.grid"})
    if any(k in toks for k in ("load","consumption")):
        cats.update({"energy","energy.load"})

    # Generic device batteries (sensors/phones/etc.)
    if device_class == "battery" or "battery" in toks:
        if "energy.storage" not in cats:
            cats.add("device.battery")

    return cats

# ----------------- fetch + summarize -----------------

def _fetch_ha_states(cfg: Dict[str,Any]) -> List[Dict[str,Any]]:
    ha_url   = (cfg.get("llm_enviroguard_ha_base_url","").rstrip("/"))
    ha_token = (cfg.get("llm_enviroguard_ha_token",""))
    if not ha_url or not ha_token: return []
    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    try:
        data = _http_get_json(f"{ha_url}/api/states", headers, timeout=25)
    except Exception:
        return []
    if not isinstance(data,list): return []

    facts=[]
    for item in data:
        try:
            eid = str(item.get("entity_id") or "")
            if not eid: continue
            domain = eid.split(".",1)[0] if "." in eid else ""

            attrs = item.get("attributes") or {}
            device_class = str(attrs.get("device_class","")).lower()
            name  = str(attrs.get("friendly_name", eid))
            state = str(item.get("state",""))
            unit  = str(attrs.get("unit_of_measurement","") or "")
            last_changed = str(item.get("last_changed","") or "")

            is_unknown = str(state).lower() in ("", "unknown", "unavailable", "none")
            if domain == "device_tracker" and not is_unknown:
                state = _safe_zone_from_tracker(state, attrs)

            show_state = state.upper() if state in ("on","off","open","closed") else state
            if unit and state not in ("on","off","open","closed"):
                try:
                    v = float(state)
                    if abs(v) < 0.005: v = 0.0
                    s = f"{v:.2f}".rstrip("0").rstrip(".")
                    show_state = f"{s} {unit}".strip()
                except Exception:
                    show_state = f"{state} {unit}".strip()

            summary = name
            if device_class:
                summary += f" ({device_class})"
            if show_state:
                summary += f": {show_state}"
            recent = last_changed.replace("T"," ").split(".")[0].replace("Z","") if last_changed else ""
            if domain in ("person","device_tracker","binary_sensor","sensor") and recent:
                summary += f" (as of {recent})"

            score=1
            toks=_tok(eid)+_tok(name)+_tok(device_class)
            if any(k in toks for k in SOLAR_KEYWORDS): score+=6
            score += DEVICE_CLASS_PRIORITY.get(device_class,0)
            if domain in ("person","device_tracker"): score+=5
            if is_unknown: score -= 3

            cats = _infer_categories(eid, name, attrs, domain, device_class)

            facts.append({
                "entity_id": eid,
                "domain": domain,
                "device_class": device_class,
                "friendly_name": name,
                "state": state,
                "unit": unit,
                "last_changed": last_changed,
                "summary": summary,
                "score": score,
                "cats": sorted(list(cats))
            })
        except Exception:
            continue
    return facts

# ----------------- IO + cache -----------------

def refresh_and_cache() -> List[Dict[str,Any]]:
    global _LAST_REFRESH_TS
    cfg = _load_options()
    facts = _fetch_ha_states(cfg)
    result_paths=[]
    try:
        payload = facts
        for d in PRIMARY_DIRS:
            try:
                p=os.path.join(d,BASENAME)
                _write_json_atomic(p, payload); result_paths.append(p)
            except Exception as e:
                print(f"[RAG] write failed for {d}: {e}")
        try:
            _write_json_atomic(FALLBACK_PATH, payload); result_paths.append(FALLBACK_PATH)
        except Exception as e:
            print(f"[RAG] fallback write failed: {e}")
    finally:
        _LAST_REFRESH_TS = time.time()
    print(f"[RAG] wrote {len(facts)} facts to: " + " | ".join(result_paths))
    return facts

def load_cached() -> List[Dict:str]:
    try:
        for d in PRIMARY_DIRS:
            p=os.path.join(d,BASENAME)
            if os.path.exists(p):
                with open(p,"r",encoding="utf-8") as f: return json.load(f)
        with open(FALLBACK_PATH,"r",encoding="utf-8") as f: return json.load(f)
    except Exception:
        return []

def get_facts(force_refresh: bool=False) -> List[Dict[str,Any]]:
    if force_refresh or (time.time() - _LAST_REFRESH_TS > REFRESH_INTERVAL_SEC):
        return refresh_and_cache()
    facts = load_cached()
    if not facts:
        return refresh_and_cache()
    return facts

# ----------------- query → context -----------------

def _intent_categories(q_tokens: Set[str]) -> Set[str]:
    out:set[str] = set()
    for key, cats in INTENT_CATEGORY_MAP.items():
        if key in q_tokens:
            out.update(cats)
    if q_tokens & {"solar","pv","inverter","ess","soc","battery"}:
        out.update({"energy","energy.storage","energy.pv","energy.inverter"})
    if "grid" in q_tokens:
        out.update({"energy.grid"})
    if "load" in q_tokens:
        out.update({"energy.load"})
    return out

def _dynamic_top_k(cfg: Dict[str,Any]) -> int:
    ctx = int(cfg.get("llm_ctx_tokens", 4096))
    est_tokens = int(ctx * 0.25)        # 25% for RAG
    facts = est_tokens // 20            # ~20 tokens per fact
    return max(100, min(facts, 250))    # clamp 100–250

def inject_context(user_msg: str) -> str:
    q_raw = _tok(user_msg)
    q = set(_expand_query_tokens(q_raw))
    cfg = _load_options()
    top_k = _dynamic_top_k(cfg)
    facts = get_facts()

    want_cats = _intent_categories(q)

    # detect location-style ask (helps even if user didn't use exact word 'where')
    is_where_like = bool(q & {"where","location","zone","home","work","present","presence","is"})

    scored=[]
    for f in facts:
        s = int(f.get("score",1))
        ft=set(_tok(f.get("summary","")) + _tok(f.get("entity_id","")))
        cats=set(f.get("cats",[]))

        # token match
        if q and (q & ft): s += 3

        # energy-ish bump
        if q & SOLAR_KEYWORDS: s += 2

        # SOC bump (ESS % sensors bubble up)
        if {"state_of_charge","battery_state_of_charge","battery_soc","soc"} & ft:
            s += 12

        # category routing
        if want_cats and (cats & want_cats):
            s += 15

        # extra preference for storage if asking soc/battery/solar
        if (want_cats & {"energy.storage"}) and ("energy.storage" in cats):
            s += 20

        # push down device batteries vs ESS
        if (want_cats & {"energy.storage"}) and ("device.battery" in cats) and ("energy.storage" not in cats):
            s -= 12

        # push down forecasts for SOC asks
        if (want_cats & {"energy.storage"}) and ("forecast" in ft or "estimated" in ft):
            s -= 10

        # NEW: location-style queries → prefer person/device_tracker
        if is_where_like and ("person" in cats):
            s += 25

        scored.append((s, f.get("summary","")))

    top=sorted(scored,key=lambda x:x[0],reverse=True)[:top_k]

    try:
        print(f"[RAG] inject_context: top_k={top_k} | q={sorted(q)} | want_cats={sorted(list(want_cats))} | where_like={is_where_like} | facts={len(facts)} | matched={len([t for t in top if t[1]])}")
        for i, (_, line) in enumerate(top[:3], 1):
            if line:
                print(f"[RAG] ctx[{i}]: {line}")
    except Exception:
        pass

    return "\n".join([t[1] for t in top if t[1]])

# ----------------- main -----------------

if __name__ == "__main__":
    print("Refreshing RAG facts from Home Assistant...")
    facts = refresh_and_cache()
    print(f"Wrote {len(facts)} facts.")