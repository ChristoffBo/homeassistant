#!/usr/bin/env python3
# /app/rag.py  (REST → /api/states)
#
# - Reads HA URL + token from /data/options.json (/data/config.json fallback)
# - Pulls states via /api/states (read-only)
# - Summarizes/boosts entities and auto-categorizes them (no per-entity config)
# - Writes rag_facts.json to /share/jarvis_prime/memory and /data (fallback)
# - inject_context(user_msg, top_k) returns a small, relevant context block
#
# Safe: read-only, never calls HA /api/services

import os, re, json, time, threading, urllib.request
from typing import Any, Dict, List, Set

OPTIONS_PATHS = ["/data/options.json", "/data/config.json"]

PRIMARY_DIRS   = ["/share/jarvis_prime/memory"]
FALLBACK_PATH  = "/data/rag_facts.json"
BASENAME       = "rag_facts.json"

INCLUDE_DOMAINS = None  # None = include all

SOLAR_KEYWORDS   = {"solar","solar_assistant","pv","inverter","ess","battery_soc","soc","battery","grid","load","generation","import","export"}
DEVICE_CLASS_PRIORITY = {"motion":6,"presence":6,"occupancy":5,"door":4,"opening":4,"window":3,
                         "battery":3,"temperature":3,"humidity":2,"power":3,"energy":3}

QUERY_SYNONYMS = {
    "soc": ["soc","state_of_charge","battery_soc","battery","charge","charge_percentage"],
    "solar": ["solar","pv","generation","inverter","array","ess"],
    "pv": ["pv","solar"],
    "load": ["load","power","w","kw","consumption"],
    "grid": ["grid","import","export"],
    "battery": ["battery","soc","charge","state_of_charge"],
    "where": ["where","location","zone","home","work","present"],
}

INTENT_CATEGORY_MAP = {
    "solar": {"energy.storage","energy.pv","energy.inverter"},
    "pv":    {"energy.pv","energy.inverter","energy.storage"},
    "soc":   {"energy.storage"},
    "battery": {"energy.storage"},
    "grid":  {"energy.grid"},
    "load":  {"energy.load"},
}

REFRESH_INTERVAL_SEC = 15*60
DEFAULT_TOP_K = 5
_LAST_REFRESH_TS = 0.0

# --------------- helpers ----------------

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

def _short_iso(ts: str) -> str:
    return ts.replace("T"," ").split(".")[0].replace("Z","") if ts else ""

def _write_json_atomic(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(obj,f,indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

def _load_options() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    for p in OPTIONS_PATHS:
        try:
            if os.path.exists(p):
                with open(p,"r",encoding="utf-8") as f:
                    raw=f.read()
                try: cfg.update(json.loads(raw))
                except json.JSONDecodeError:
                    try:
                        import yaml; cfg.update(yaml.safe_load(raw) or {})
                    except Exception: pass
        except Exception:
            pass
    return cfg

def _http_get_json(url: str, headers: Dict[str,str], timeout: int=20):
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8","replace"))

# --------------- categories --------------

def _infer_categories(eid: str, name: str, attrs: Dict[str,Any], domain: str, device_class: str) -> Set[str]:
    cats:set[str] = set()
    toks = set(_tok(eid) + _tok(name) + _tok(device_class))
    model= str(attrs.get("model","") or "").lower()

    if domain in ("person","device_tracker"):
        cats.add("person")
    if any(k in toks for k in ("pv","inverter","ess","solar","solar_assistant")) or "inverter" in model:
        cats.add("energy")
        if "pv" in toks or "solar" in toks: cats.add("energy.pv")
        if "inverter" in toks or "ess" in toks: cats.add("energy.inverter")
        if "soc" in toks or "battery" in toks: cats.add("energy.storage")
    if "grid" in toks: cats.update({"energy","energy.grid"})
    if "load" in toks: cats.update({"energy","energy.load"})
    if device_class == "battery" and "energy.storage" not in cats:
        cats.add("device.battery")
    return cats

# --------------- fetch -------------------

def _fetch_ha_states(cfg: Dict[str,Any]) -> List[Dict[str,Any]]:
    ha_url   = (cfg.get("llm_enviroguard_ha_base_url","").rstrip("/"))
    ha_token = (cfg.get("llm_enviroguard_ha_token",""))
    if not ha_url or not ha_token: return []
    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    try: data = _http_get_json(f"{ha_url}/api/states", headers, timeout=25)
    except Exception: return []
    if not isinstance(data,list): return []

    facts=[]
    for item in data:
        try:
            eid = str(item.get("entity_id") or ""); domain = eid.split(".",1)[0] if "." in eid else ""
            if not eid: continue
            if INCLUDE_DOMAINS and (domain not in INCLUDE_DOMAINS): continue

            attrs=item.get("attributes") or {}
            device_class=str(attrs.get("device_class","")).lower()
            name=str(attrs.get("friendly_name",eid))
            state=str(item.get("state","")); unit=str(attrs.get("unit_of_measurement","") or "")
            last_changed=str(item.get("last_changed","") or "")
            is_unknown=state.lower() in ("","unknown","unavailable","none")

            if domain=="device_tracker" and not is_unknown:
                state=_safe_zone_from_tracker(state,attrs)

            show_state=state.upper() if state in ("on","off","open","closed") else state
            if unit and state not in ("on","off","open","closed"):
                try:
                    v=float(state); show_state=f"{v:.2f}".rstrip("0").rstrip(".")+" "+unit
                except Exception: show_state=f"{state} {unit}".strip()

            summary=name
            if device_class: summary+=f" ({device_class})"
            if show_state: summary+=f": {show_state}"
            if domain in ("person","device_tracker","binary_sensor","sensor") and last_changed:
                summary+=f" (as of {_short_iso(last_changed)})"

            score=1
            toks=_tok(eid)+_tok(name)+_tok(device_class)
            if any(k in toks for k in SOLAR_KEYWORDS): score+=6
            score+=DEVICE_CLASS_PRIORITY.get(device_class,0)
            if domain in ("person","device_tracker"): score+=5
            if is_unknown: score-=3

            cats=_infer_categories(eid,name,attrs,domain,device_class)

            facts.append({
                "entity_id":eid,"domain":domain,"device_class":device_class,
                "friendly_name":name,"state":state,"unit":unit,
                "last_changed":last_changed,"summary":summary,
                "score":score,"cats":sorted(list(cats))
            })
        except Exception: continue
    return facts

# --------------- IO ----------------------

def refresh_and_cache() -> List[Dict[str,Any]]:
    global _LAST_REFRESH_TS
    facts=_fetch_ha_states(_load_options())
    try:
        for d in PRIMARY_DIRS: _write_json_atomic(os.path.join(d,BASENAME),facts)
        _write_json_atomic(FALLBACK_PATH,facts)
    finally: _LAST_REFRESH_TS=time.time()
    print(f"[RAG] wrote {len(facts)} facts")
    return facts

def load_cached() -> List[Dict[str,Any]]:
    try:
        for d in PRIMARY_DIRS:
            p=os.path.join(d,BASENAME)
            if os.path.exists(p): return json.load(open(p,"r",encoding="utf-8"))
        return json.load(open(FALLBACK_PATH,"r",encoding="utf-8"))
    except Exception: return []

def get_facts(force_refresh: bool=False) -> List[Dict[str,Any]]:
    if force_refresh or (time.time()-_LAST_REFRESH_TS>REFRESH_INTERVAL_SEC):
        return refresh_and_cache()
    facts=load_cached()
    return facts or refresh_and_cache()

# --------------- query -------------------

def _intent_categories(q_tokens: Set[str]) -> Set[str]:
    out:set[str]=set()
    for k,c in INTENT_CATEGORY_MAP.items():
        if k in q_tokens: out.update(c)
    if q_tokens & {"solar","pv","inverter","ess","soc","battery"}:
        out.update({"energy","energy.storage","energy.pv","energy.inverter"})
    if "grid" in q_tokens: out.add("energy.grid")
    if "load" in q_tokens: out.add("energy.load")
    return out

def inject_context(user_msg: str, top_k:int=DEFAULT_TOP_K) -> str:
    q_raw=_tok(user_msg); q=set(_expand_query_tokens(q_raw))
    facts=get_facts(); want_cats=_intent_categories(q)

    scored=[]
    for f in facts:
        s=int(f.get("score",1))
        ft=set(_tok(f.get("summary",""))+_tok(f.get("entity_id","")))
        cats=set(f.get("cats",[]))

        if q & ft: s+=3
        if q & SOLAR_KEYWORDS: s+=2
        if {"soc","battery_soc"} & ft: s+=12
        if want_cats & cats: s+=15
        if "energy.storage" in cats and "energy.storage" in want_cats: s+=20
        if "device.battery" in cats and "energy.storage" in want_cats: s-=12

        # Person-specific boost
        if "person" in cats:
            fname=f.get("friendly_name","").lower()
            eid=f.get("entity_id","").lower().split(".")[-1]
            lower_q=" ".join(q_raw).lower()
            if fname in lower_q or eid in lower_q:
                s+=25

        f["score"]=s
        scored.append((s,f))

    # sort normally
    top=sorted(scored,key=lambda x:x[0],reverse=True)[:top_k]
    results=[f.get("summary","") for _,f in top if f.get("summary")]

    # Guarantee: always include at least one person
    if not any("person" in f.get("cats",[]) for _,f in top):
        people=[f for f in facts if "person" in f.get("cats",[])]
        if people:
            results.append(people[0].get("summary",""))

    return "\n".join(results)

# --------------- main --------------------

if __name__=="__main__":
    print("Refreshing RAG facts...")
    refresh_and_cache()