#!/usr/bin/env python3
# /app/rag.py  (REST → /api/states)

import os, re, json, time, threading, urllib.request
from typing import Any, Dict, List

OPTIONS_PATHS = ["/data/options.json", "/data/config.json"]

PRIMARY_DIRS   = ["/share/jarvis_prime/memory"]
FALLBACK_PATH  = "/data/rag_facts.json"
BASENAME       = "rag_facts.json"

REFRESH_INTERVAL_SEC = 15*60
DEFAULT_TOP_K = 10   # ⬅️ bumped from 5
_CACHE_LOCK = threading.RLock()
_LAST_REFRESH_TS = 0.0

SAFE_RAG_BUDGET_FRACTION = 0.30

# ----------------- helpers -----------------

def _tok(s: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9_]+", s.lower() if s else "")

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
                with open(p,"r",encoding="utf-8") as f: cfg.update(json.load(f))
        except Exception: pass
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

def _estimate_tokens(text: str) -> int:
    if not text: return 0
    words = len(re.findall(r"\S+", text))
    return max(8, min(int(words*1.3),128))

def _ctx_tokens_from_options() -> int:
    cfg = _load_options()
    try: return int(cfg.get("llm_ctx_tokens",4096))
    except Exception: return 4096

def _rag_budget_tokens(ctx_tokens: int) -> int:
    return max(256,int(ctx_tokens*SAFE_RAG_BUDGET_FRACTION))

# ----------------- fetch + summarize -----------------

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
            eid = str(item.get("entity_id") or "")
            if not eid: continue
            domain = eid.split(".",1)[0] if "." in eid else ""
            attrs = item.get("attributes") or {}
            device_class = str(attrs.get("device_class","")).lower()
            name  = str(attrs.get("friendly_name", eid))
            state = str(item.get("state",""))
            unit  = str(attrs.get("unit_of_measurement","") or "")

            if domain == "device_tracker" and state not in ("unknown","unavailable","none",""):
                state = _safe_zone_from_tracker(state, attrs)

            summary = f"{name}: {state}{(' '+unit) if unit else ''}"
            facts.append({
                "entity_id": eid,
                "domain": domain,
                "device_class": device_class,
                "friendly_name": name,
                "state": state,
                "summary": summary
            })
        except Exception: continue
    return facts

# ----------------- IO + cache -----------------

def refresh_and_cache() -> List[Dict[str,Any]]:
    global _LAST_REFRESH_TS
    facts = _fetch_ha_states(_load_options())
    for d in PRIMARY_DIRS:
        try: _write_json_atomic(os.path.join(d,BASENAME),facts)
        except Exception: pass
    try: _write_json_atomic(FALLBACK_PATH,facts)
    except Exception: pass
    _LAST_REFRESH_TS=time.time()
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
    if force_refresh or (time.time()-_LAST_REFRESH_TS>REFRESH_INTERVAL_SEC):
        return refresh_and_cache()
    facts=load_cached()
    return facts or refresh_and_cache()

# ----------------- query → context -----------------

def inject_context(user_msg: str, top_k: int=DEFAULT_TOP_K) -> str:
    ql=(user_msg or "").lower()
    facts=get_facts()

    # --- domain / keyword overrides ---
    domain_hint=None; device_class_hint=None; keyword_hint=None
    if "light" in ql: domain_hint="light"
    if "switch" in ql: domain_hint="switch"
    if "motion" in ql: domain_hint="binary_sensor"; device_class_hint="motion"
    if "sensor" in ql: domain_hint="sensor"
    if "media" in ql: domain_hint="media_player"
    if "climate" in ql: domain_hint="climate"
    if "cover" in ql: domain_hint="cover"
    if "person" in ql or "where" in ql: domain_hint="person"
    for kw in ["axpert","sonoff","zigbee","mqtt","inverter","solar","ess","ups","bms"]:
        if kw in ql: keyword_hint=kw; break

    candidates=facts
    if domain_hint:
        candidates=[f for f in candidates if f.get("domain")==domain_hint]
    if device_class_hint:
        candidates=[f for f in candidates if f.get("device_class")==device_class_hint]
    if keyword_hint:
        candidates=[f for f in candidates if keyword_hint in f.get("entity_id","").lower() or keyword_hint in f.get("friendly_name","").lower()]

    if (domain_hint or keyword_hint) and candidates:
        on=[f for f in candidates if str(f.get("state","")).lower() in ("on","open","playing")]
        off=[f for f in candidates if str(f.get("state","")).lower() in ("off","closed","idle")]
        other=[f for f in candidates if str(f.get("state","")).lower() not in ("on","off","open","closed","playing","idle")]

        parts=[]
        if on: parts.append(f"{len(on)} active")
        if off: parts.append(f"{len(off)} inactive")
        if other: parts.append(f"{len(other)} other")
        header=f"Found {len(candidates)} {domain_hint or keyword_hint} entities ({', '.join(parts)})."

        lines=[f"- {f.get('friendly_name')}: {f.get('state')}" for f in candidates]
        ctx_tokens=_ctx_tokens_from_options(); budget=_rag_budget_tokens(ctx_tokens)
        selected=[]; remaining=budget
        for line in lines:
            cost=_estimate_tokens(line)
            if cost<=remaining:
                selected.append(line); remaining-=cost
            else: break
        if len(selected)<len(lines):
            return header+f"\nShowing {len(selected)}:\n"+"\n".join(selected)
        return header+"\n"+"\n".join(selected)

    # --- fallback: prefer active states ---
    active_words={"on","open","playing","active"}
    sorted_facts=sorted(
        facts,
        key=lambda f: (str(f.get("state","")).lower() in active_words, f.get("friendly_name","")),
        reverse=True
    )
    selected=[]
    ctx_tokens=_ctx_tokens_from_options(); budget=_rag_budget_tokens(ctx_tokens)
    for f in sorted_facts[:top_k*4]:  # bigger pool, but budget trims it
        line=f.get("summary","")
        if not line: continue
        cost=_estimate_tokens(line)
        if cost<=budget:
            selected.append(line); budget-=cost
        else: break
    return "\n".join(selected)