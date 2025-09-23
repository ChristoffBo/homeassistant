#!/usr/bin/env python3
# /app/rag.py  (REST → /api/states)

import os, re, json, time, threading, urllib.request
from typing import Any, Dict, List, Tuple

OPTIONS_PATHS = ["/data/options.json", "/data/config.json"]

# Primary + fallback output
PRIMARY_DIRS   = ["/share/jarvis_prime/memory", "/share/jarvis_prime"]
FALLBACK_PATH  = "/data/rag_facts.json"
BASENAME       = "rag_facts.json"

INCLUDE_DOMAINS = {"light","switch","sensor","binary_sensor","person","device_tracker"}

SOLAR_KEYWORDS   = {"solar","solar_assistant","pv","inverter","soc","battery_soc","battery","grid","load","generation","import","export"}
SONOFF_KEYWORDS  = {"sonoff"}
ZIGBEE_KEYWORDS  = {"zigbee","zigbee2mqtt","z2m","zha"}
MQTT_KEYWORDS    = {"mqtt"}
RADARR_KEYWORDS  = {"radarr"}
SONARR_KEYWORDS  = {"sonarr"}

DEVICE_CLASS_PRIORITY = {"motion":6,"presence":6,"occupancy":5,"door":4,"opening":4,"window":3,"battery":3,"temperature":3,"humidity":2,"power":3,"energy":3}

QUERY_SYNONYMS = {
    "soc":["soc","state_of_charge","battery_soc","battery"],
    "solar":["solar","pv","generation","inverter","array"],
    "pv":["pv","solar"],
    "load":["load","power","w","kw","consumption"],
    "grid":["grid","import","export"],
    "battery":["battery","soc","charge"],
    "where":["where","location","zone","home","work","present"],
}

REFRESH_INTERVAL_SEC = 15*60
DEFAULT_TOP_K = 5
_CACHE_LOCK = threading.RLock()
_LAST_REFRESH_TS = 0.0

def _load_options() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    for p in OPTIONS_PATHS:
        try:
            if os.path.exists(p):
                with open(p,"r",encoding="utf-8") as f:
                    raw=f.read()
                try: data=json.loads(raw)
                except json.JSONDecodeError:
                    try:
                        import yaml; data=yaml.safe_load(raw)
                    except Exception: data=None
                if isinstance(data,dict): cfg.update(data)
        except Exception: pass
    return cfg

def _http_get_json(url: str, headers: Dict[str,str], timeout: int=20):
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8","replace"))

def _domain_of(eid: str) -> str:
    return eid.split(".",1)[0] if "." in eid else ""

def _upper_if_onoff(s: str) -> str:
    return s.upper() if s in ("on","off","open","closed") else s

def _tok(s: str) -> List[str]:
    import re
    return re.findall(r"[A-Za-z0-9_]+", s.lower() if s else "")

def _expand_query_tokens(tokens: List[str]) -> List[str]:
    out=[]; seen=set()
    for t in tokens:
        for x in QUERY_SYNONYMS.get(t,[t]):
            if x not in seen:
                seen.add(x); out.append(x)
    return out

def _short_iso(ts: str) -> str:
    return ts.replace("T"," ").split(".")[0].replace("Z","") if ts else ""

def _fmt_num(state: str, unit: str) -> str:
    try:
        v=float(state); 
        if abs(v)<0.005: v=0.0
        s=f"{v:.2f}".rstrip("0").rstrip(".")
        return f"{s} {unit}".strip()
    except Exception:
        return f"{state} {unit}".strip() if unit else state

def _safe_zone_from_tracker(state: str, attrs: Dict[str,Any]) -> str:
    zone = attrs.get("zone")
    if zone: return zone
    ls = (state or "").lower()
    if ls in ("home","not_home"): return "Home" if ls=="home" else "Away"
    return state

def _write_json_atomic(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(obj,f,indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

def _fetch_ha_states(cfg: Dict[str,Any]) -> List[Dict[str,Any]]:
    ha_url = (cfg.get("llm_enviroguard_ha_base_url","").rstrip("/"))
    ha_token = (cfg.get("llm_enviroguard_ha_token",""))
    if not ha_url or not ha_token: return []
    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    try: data = _http_get_json(f"{ha_url}/api/states", headers, timeout=25)
    except Exception: return []
    if not isinstance(data,list): return []

    facts=[]
    for item in data:
        try:
            eid = str(item.get("entity_id") or "")
            if not eid: continue
            domain = _domain_of(eid)
            if domain not in INCLUDE_DOMAINS: continue

            attrs = item.get("attributes") or {}
            device_class = str(attrs.get("device_class","")).lower()
            name  = str(attrs.get("friendly_name", eid))
            state = str(item.get("state",""))
            unit  = str(attrs.get("unit_of_measurement","") or "")
            last_changed = str(item.get("last_changed","") or "")

            if state in ("","unknown","unavailable"): continue
            if domain == "device_tracker":
                state = _safe_zone_from_tracker(state, attrs)

            show_state = _upper_if_onoff(state) if state else ""
            if unit and state not in ("on","off","open","closed"):
                show_state = _fmt_num(state, unit)

            summary = name
            if device_class: summary += f" ({device_class})"
            if show_state:   summary += f": {show_state}"
            recent = _short_iso(last_changed)
            if domain in ("person","device_tracker","binary_sensor","sensor") and recent:
                summary += f" (as of {recent})"

            score=1
            toks=_tok(eid)+_tok(name)+_tok(device_class)
            if any(k in toks for k in SOLAR_KEYWORDS): score+=6
            if "solar_assistant" in "_".join(toks) or "solarassistant" in "_".join(toks): score+=3
            if any(k in toks for k in SONOFF_KEYWORDS): score+=3
            if any(k in toks for k in ZIGBEE_KEYWORDS): score+=2
            if any(k in toks for k in MQTT_KEYWORDS):   score+=2
            if any(k in toks for k in RADARR_KEYWORDS): score+=3
            if any(k in toks for k in SONARR_KEYWORDS): score+=3
            score += DEVICE_CLASS_PRIORITY.get(device_class,0)
            if domain in ("person","device_tracker"): score+=5
            if eid.endswith(("_linkquality","_rssi","_lqi")): score-=2

            facts.append({
                "entity_id": eid,
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

def refresh_and_cache() -> List[Dict[str,Any]]:
    global _LAST_REFRESH_TS
    cfg = _load_options()
    facts = _fetch_ha_states(cfg)

    result_paths=[]
    try:
        result=facts
        # write primary(s)
        payload = facts
        for d in PRIMARY_DIRS:
            try:
                p=os.path.join(d,BASENAME)
                _write_json_atomic(p, payload); result_paths.append(p)
            except Exception as e:
                print(f"[RAG] write failed for {d}: {e}")
        # fallback
        try:
            _write_json_atomic(FALLBACK_PATH, payload); result_paths.append(FALLBACK_PATH)
        except Exception as e:
            print(f"[RAG] fallback write failed: {e}")
    finally:
        _LAST_REFRESH_TS = time.time()

    print(f"[RAG] wrote {len(facts)} facts to: " + " | ".join(result_paths))
    return facts

def load_cached() -> List[Dict[str,Any]]:
    try:
        # prefer primary if present
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
    return load_cached()

def inject_context(user_msg: str, top_k: int=5) -> str:
    q=set(_expand_query_tokens(_tok(user_msg)))
    facts=get_facts()
    scored=[]
    for f in facts:
        s=f.get("score",1)
        if q:
            ft=set(_tok(f.get("summary","")) + _tok(f.get("entity_id","")))
            if q & ft: s+=3
            if ({"solar","pv","inverter","soc","battery"} & q) and any(k in ft for k in SOLAR_KEYWORDS):
                s+=2
        scored.append((s,f.get("summary","")))
    top=sorted(scored,key=lambda x:x[0],reverse=True)[:top_k]
    return "\n".join([t[1] for t in top if t[1]])

if __name__ == "__main__":
    print("Refreshing RAG facts from Home Assistant...")
    facts = refresh_and_cache()
    print(f"Wrote {len(facts)} facts.")