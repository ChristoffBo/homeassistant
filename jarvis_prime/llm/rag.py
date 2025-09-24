#!/usr/bin/env python3
# /app/rag.py  (REST → /api/states)
#
# - Reads HA URL + token from /data/options.json (/data/config.json fallback)
# - Pulls states via /api/states (read-only)
# - Summarizes/boosts entities and auto-categorizes them (no per-entity config)
# - Writes primary JSON to /share/jarvis_prime/memory/rag_facts.json
#   and also mirrors to /data/rag_facts.json as a fallback
# - inject_context(user_msg, top_k) returns a small, relevant context block
#
# Safe: read-only, never calls HA /api/services

import os, re, json, time, threading, urllib.request
from typing import Any, Dict, List, Tuple, Set

OPTIONS_PATHS = ["/data/options.json", "/data/config.json"]

# Primary (single target) + fallback
PRIMARY_DIRS   = ["/share/jarvis_prime/memory"]
FALLBACK_PATH  = "/data/rag_facts.json"
BASENAME       = "rag_facts.json"

INCLUDE_DOMAINS = None  # None => include all

REFRESH_INTERVAL_SEC = 15*60
DEFAULT_TOP_K = 10
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

def _domain_of(eid: str) -> str:
    return eid.split(".",1)[0] if "." in eid else ""

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

# synonyms + intent map (same as before)
QUERY_SYNONYMS = {
    "soc":["soc","state_of_charge","battery_state_of_charge","battery","charge"],
    "solar":["solar","pv","generation","inverter"],
    "load":["load","power","consumption"],
    "grid":["grid","import","export"],
    "battery":["battery","soc","charge","state_of_charge"],
    "where":["where","location","zone","home","work","present"],
}
INTENT_CATEGORY_MAP = {
    "solar":{"energy.pv","energy.inverter"},
    "pv":{"energy.pv"},
    "soc":{"energy.storage"},
    "battery":{"energy.storage"},
    "grid":{"energy.grid"},
    "load":{"energy.load"},
}

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

            # Build summary
            if domain == "person":
                zone = _safe_zone_from_tracker(state, attrs)
                summary = f"{name} is at {zone}"
            else:
                summary = f"{name}: {state}"
                if unit and state not in ("on","off"):
                    summary = f"{name}: {state} {unit}"
            if last_changed:
                recent = last_changed.replace("T"," ").split(".")[0].replace("Z","")
                summary += f" (as of {recent})"

            facts.append({
                "entity_id": eid,
                "domain": domain,
                "device_class": device_class,
                "friendly_name": name,
                "state": state,
                "unit": unit,
                "last_changed": last_changed,
                "summary": summary,
                "tokens": _tok(eid) + _tok(name) + _tok(device_class)  # include friendly_name tokens
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
        for d in PRIMARY_DIRS:
            try:
                p=os.path.join(d,BASENAME)
                _write_json_atomic(p, facts); result_paths.append(p)
            except Exception: pass
        try:
            _write_json_atomic(FALLBACK_PATH, facts); result_paths.append(FALLBACK_PATH)
        except Exception: pass
    finally:
        _LAST_REFRESH_TS = time.time()
    print(f"[RAG] wrote {len(facts)} facts")
    return facts

def load_cached() -> List[Dict[str,Any]]:
    try:
        for d in PRIMARY_DIRS:
            p=os.path.join(d,BASENAME)
            if os.path.exists(p):
                with open(p,"r",encoding="utf-8") as f: return json.load(f)
        with open(FALLBACK_PATH,"r",encoding="utf-8") as f: return json.load(f)
    except Exception: return []

def get_facts(force_refresh: bool=False) -> List[Dict[str,Any]]:
    if force_refresh or (time.time() - _LAST_REFRESH_TS > REFRESH_INTERVAL_SEC):
        return refresh_and_cache()
    facts = load_cached()
    if not facts:
        return refresh_and_cache()
    return facts

# ----------------- query → context -----------------

def inject_context(user_msg: str, top_k: int=DEFAULT_TOP_K) -> str:
    q_raw = _tok(user_msg)
    q = set(_expand_query_tokens(q_raw))
    facts = get_facts()

    # --- Overrides ---
    if ("who" in q and "home" in q) or ("who" in q and "away" in q):
        facts = [f for f in facts if f["domain"]=="person"]
    elif "light" in q or "lights" in q:
        facts = [f for f in facts if f["domain"] in ("light","switch") and ("light" in " ".join(f["tokens"]))]
    elif "switch" in q or "switches" in q:
        facts = [f for f in facts if f["domain"] in ("switch","light")]
    elif "pool" in q:
        facts = [f for f in facts if "pool" in " ".join(f["tokens"])]

    # Score + rank
    scored=[]
    for f in facts:
        score=1
        if q & set(f.get("tokens",[])): score+=5
        scored.append((score,f))
    scored.sort(key=lambda x:x[0], reverse=True)
    selected=[f.get("summary","") for _,f in scored[:top_k] if f.get("summary")]

    return "\n".join(selected)

# ----------------- main -----------------

if __name__ == "__main__":
    print("Refreshing RAG facts...")
    facts = refresh_and_cache()
    print(f"Wrote {len(facts)} facts.")