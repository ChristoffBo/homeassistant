#!/usr/bin/env python3
# /app/rag.py  (REST → /api/states + /api/areas)
#
# - Reads HA URL + token from /data/options.json (/data/config.json fallback)
# - Pulls states via /api/states (read-only) + area metadata via /api/areas
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

# Include ALL domains
INCLUDE_DOMAINS = None

# ----------------- Keywords / Integrations -----------------

# Energy / Solar
SOLAR_KEYWORDS   = {"solar","solar_assistant","pv","inverter","ess","battery_soc","soc","battery","grid","load","generation","import","export","axpert"}
SONOFF_KEYWORDS  = {"sonoff","tasmota"}
ZIGBEE_KEYWORDS  = {"zigbee","zigbee2mqtt","z2m","zha"}
MQTT_KEYWORDS    = {"mqtt"}
TUYA_KEYWORDS    = {"tuya","localtuya","local_tuya"}
FORECAST_SOLAR   = {"forecast.solar","forecastsolar","forecast_solar"}

# Media (separate + combined)
PLEX_KEYWORDS    = {"plex"}
EMBY_KEYWORDS    = {"emby"}
JELLYFIN_KEYWORDS= {"jellyfin"}
KODI_KEYWORDS    = {"kodi","xbmc"}
TV_KEYWORDS      = {"tv","androidtv","chromecast","google_tv"}
RADARR_KEYWORDS  = {"radarr"}
SONARR_KEYWORDS  = {"sonarr"}
LIDARR_KEYWORDS  = {"lidarr"}
BAZARR_KEYWORDS  = {"bazarr"}
READARR_KEYWORDS = {"readarr"}
SONOS_KEYWORDS   = {"sonos"}
AMP_KEYWORDS     = {"denon","onkyo","yamaha","marantz"}

MEDIA_KEYWORDS   = set().union(
    PLEX_KEYWORDS, EMBY_KEYWORDS, JELLYFIN_KEYWORDS, KODI_KEYWORDS, TV_KEYWORDS,
    RADARR_KEYWORDS, SONARR_KEYWORDS, LIDARR_KEYWORDS, BAZARR_KEYWORDS, READARR_KEYWORDS,
    SONOS_KEYWORDS, AMP_KEYWORDS, {"media","player"}
)

# Infra / system
PROXMOX_KEYWORDS = {"proxmox","pve"}
SPEEDTEST_KEYS   = {"speedtest","speed_test"}
CPU_KEYS         = {"cpu","processor","loadavg","load_avg"}
WEATHER_KEYS     = {"weather","weatherbit","openweathermap","met","yr"}

# ----------------- Device-class priority -----------------

DEVICE_CLASS_PRIORITY = {
    "motion":6,"presence":6,"occupancy":5,"door":4,"opening":4,"window":3,
    "battery":3,"temperature":3,"humidity":2,"power":3,"energy":3
}

# ----------------- Query synonyms -----------------

QUERY_SYNONYMS = {
    "soc": ["soc","state_of_charge","battery_state_of_charge","battery_soc","battery","charge","charge_percentage","soc_percentage","soc_percent"],
    "solar": ["solar","pv","generation","inverter","array","ess","axpert"],
    "pv": ["pv","solar"],
    "load": ["load","power","w","kw","consumption"],
    "grid": ["grid","import","export"],
    "battery": ["battery","soc","charge","state_of_charge","battery_state_of_charge","charge_percentage","soc_percentage","soc_percent"],
    "where": ["where","location","zone","home","work","present"],
}

# Intent → categories we prefer
INTENT_CATEGORY_MAP = {
    "solar": {"energy.storage","energy.pv","energy.inverter"},
    "pv":    {"energy.pv","energy.inverter","energy.storage"},
    "soc":   {"energy.storage"},
    "battery": {"energy.storage"},
    "grid":  {"energy.grid"},
    "load":  {"energy.load"},
    "media": {"media"},
}

REFRESH_INTERVAL_SEC = 15*60
DEFAULT_TOP_K = 10
_CACHE_LOCK = threading.RLock()
_LAST_REFRESH_TS = 0.0
_MEM_CACHE: List[Dict[str,Any]] = []
_AREA_MAP: Dict[str,str] = {}

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

SAFE_RAG_BUDGET_FRACTION = 0.30
def _estimate_tokens(text: str) -> int:
    if not text: return 0
    words = len(re.findall(r"\S+", text))
    return max(8, min(int(words * 1.3), 128))

def _ctx_tokens_from_options() -> int:
    cfg = _load_options()
    try: return int(cfg.get("llm_ctx_tokens", 4096))
    except Exception: return 4096

def _rag_budget_tokens(ctx_tokens: int) -> int:
    return max(256, int(ctx_tokens * SAFE_RAG_BUDGET_FRACTION))

# ----------------- categorization -----------------

def _infer_categories(eid: str, name: str, attrs: Dict[str,Any], domain: str, device_class: str) -> Set[str]:
    cats:set[str] = set()
    toks = set(_tok(eid) + _tok(name) + _tok(device_class))
    manf = str(attrs.get("manufacturer","") or attrs.get("vendor","") or "").lower()
    model= str(attrs.get("model","") or "").lower()

    if domain in ("person","device_tracker"):
        cats.add("person")

    # Energy / solar
    if any(k in toks for k in SOLAR_KEYWORDS) or "inverter" in model:
        cats.add("energy")
        if "pv" in toks or "solar" in toks: cats.add("energy.pv")
        if "inverter" in toks or "ess" in toks: cats.add("energy.inverter")
        if "soc" in toks or "battery" in toks or "bms" in model: cats.add("energy.storage")
    if "grid" in toks or "import" in toks or "export" in toks: cats.update({"energy","energy.grid"})
    if "load" in toks or "consumption" in toks: cats.update({"energy","energy.load"})
    if device_class == "battery" or "battery" in toks: cats.add("device.battery")

    # Media
    if any(k in toks for k in MEDIA_KEYWORDS):
        cats.add("media")
        if toks & PLEX_KEYWORDS: cats.add("media.plex")
        if toks & EMBY_KEYWORDS: cats.add("media.emby")
        if toks & JELLYFIN_KEYWORDS: cats.add("media.jellyfin")
        if toks & KODI_KEYWORDS: cats.add("media.kodi")
        if toks & TV_KEYWORDS: cats.add("media.tv")
        if toks & RADARR_KEYWORDS: cats.add("media.radarr")
        if toks & SONARR_KEYWORDS: cats.add("media.sonarr")
        if toks & LIDARR_KEYWORDS: cats.add("media.lidarr")
        if toks & BAZARR_KEYWORDS: cats.add("media.bazarr")
        if toks & READARR_KEYWORDS: cats.add("media.readarr")
        if toks & SONOS_KEYWORDS: cats.add("media.sonos")
        if toks & AMP_KEYWORDS: cats.add("media.amplifier")

    # Infra / system
    if toks & PROXMOX_KEYWORDS: cats.add("infra.proxmox")
    if toks & SPEEDTEST_KEYS: cats.add("infra.speedtest")
    if toks & CPU_KEYS: cats.add("infra.cpu")
    if toks & WEATHER_KEYS: cats.add("weather")

    return cats

# ----------------- fetch areas -----------------

def _fetch_area_map(cfg: Dict[str,Any]) -> Dict[str,str]:
    # Try multiple possible config key names for flexibility
    ha_url = (cfg.get("ha_url") or 
              cfg.get("homeassistant_url") or 
              cfg.get("llm_enviroguard_ha_base_url") or "").rstrip("/")
    
    ha_token = (cfg.get("ha_token") or 
                cfg.get("homeassistant_token") or 
                cfg.get("llm_enviroguard_ha_token") or "")
    
    if not ha_url or not ha_token: 
        print("[RAG] No HA URL/token found in config")
        return {}
        
    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    
    # Try multiple possible endpoints
    endpoints = [
        "/api/config/area_registry/list",  # Correct endpoint for area registry
        "/api/areas",                       # Fallback attempt
    ]
    
    for endpoint in endpoints:
        try:
            data = _http_get_json(f"{ha_url}{endpoint}", headers, timeout=15)
            amap = {}
            
            # Handle different response formats
            if isinstance(data, list):
                for a in data:
                    # area_registry format
                    if "area_id" in a and "name" in a:
                        amap[a["area_id"]] = a["name"]
                    # Alternative format
                    elif "id" in a and "name" in a:
                        amap[a["id"]] = a["name"]
                        
            elif isinstance(data, dict):
                # Handle dict response format
                for area_id, area_info in data.items():
                    if isinstance(area_info, dict) and "name" in area_info:
                        amap[area_id] = area_info["name"]
                    elif isinstance(area_info, str):
                        amap[area_id] = area_info
            
            if amap:
                print(f"[RAG] Loaded {len(amap)} areas from {endpoint}")
                return amap
            else:
                print(f"[RAG] No areas found in response from {endpoint}")
                
        except urllib.error.HTTPError as e:
            print(f"[RAG] HTTP {e.code} fetching {endpoint}: {e.reason}")
            continue
        except Exception as e:
            print(f"[RAG] Failed to fetch from {endpoint}: {e}")
            continue
    
    # If all endpoints failed, try to build area map from entity attributes
    print("[RAG] Could not fetch areas from any endpoint, will try extracting from entity attributes")
    return {}

# ----------------- fetch + summarize -----------------

def _fetch_ha_states(cfg: Dict[str,Any]) -> List[Dict[str,Any]]:
    global _AREA_MAP
    
    # Try multiple possible config key names for flexibility
    ha_url = (cfg.get("ha_url") or 
              cfg.get("homeassistant_url") or 
              cfg.get("llm_enviroguard_ha_base_url") or "").rstrip("/")
    
    ha_token = (cfg.get("ha_token") or 
                cfg.get("homeassistant_token") or 
                cfg.get("llm_enviroguard_ha_token") or "")
    
    if not ha_url or not ha_token: 
        print("[RAG] No HA URL/token found in config")
        return []
        
    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    try:
        data = _http_get_json(f"{ha_url}/api/states", headers, timeout=25)
    except Exception as e:
        print(f"[RAG] Failed to fetch states: {e}")
        return []
    if not isinstance(data,list): return []

    # Fetch areas if not already populated
    if not _AREA_MAP:
        _AREA_MAP = _fetch_area_map(cfg)
        
        # If still empty after trying endpoints, build from entity attributes
        if not _AREA_MAP:
            print("[RAG] Building area map from entity attributes...")
            temp_area_map = {}
            for item in data:
                attrs = item.get("attributes") or {}
                area_id = attrs.get("area_id")
                # Try to get area name from entity attributes
                area_name = attrs.get("area_name") or attrs.get("area")
                if area_id and area_name and isinstance(area_name, str):
                    temp_area_map[area_id] = area_name
            if temp_area_map:
                _AREA_MAP = temp_area_map
                print(f"[RAG] Built area map with {len(_AREA_MAP)} areas from entity attributes")

    facts=[]
    for item in data:
        try:
            eid = str(item.get("entity_id") or "")
            if not eid: continue
            domain = eid.split(".",1)[0] if "." in eid else ""
            if INCLUDE_DOMAINS and (domain not in INCLUDE_DOMAINS):
                continue

            attrs = item.get("attributes") or {}
            device_class = str(attrs.get("device_class","")).lower()
            area_id = attrs.get("area_id","")
            area_name = _AREA_MAP.get(area_id,"") if area_id else ""
            name  = str(attrs.get("friendly_name", eid))
            state = str(item.get("state",""))
            unit  = str(attrs.get("unit_of_measurement","") or "")
            last_changed = str(item.get("last_changed","") or "")

            is_unknown = str(state).lower() in ("", "unknown", "unavailable", "none")
            
            # normalize tracker/person zones
            if domain == "device_tracker" and not is_unknown:
                state = _safe_zone_from_tracker(state, attrs)

            # displayable state
            show_state = state.upper() if state in ("on","off","open","closed") else state
            if unit and state not in ("on","off","open","closed"):
                try:
                    v = float(state)
                    if abs(v) < 0.005: v = 0.0
                    s = f"{v:.2f}".rstrip("0").rstrip(".")
                    show_state = f"{s} {unit}".strip()
                except Exception:
                    show_state = f"{state} {unit}".strip()

            # build summary
            if domain == "person":
                zone = _safe_zone_from_tracker(state, attrs)
                summary = f"{name} is at {zone}"
            else:
                summary = name
                if area_name: summary = f"[{area_name}] " + summary
                if device_class: summary += f" ({device_class})"
                if show_state: summary += f": {show_state}"

            recent = last_changed.replace("T"," ").split(".")[0].replace("Z","") if last_changed else ""
            if domain in ("person","device_tracker","binary_sensor","sensor") and recent:
                summary += f" (as of {recent})"

            # score baseline
            score=1
            toks=_tok(eid)+_tok(name)+_tok(device_class)
            if any(k in toks for k in SOLAR_KEYWORDS): score+=6
            if "solar_assistant" in "_".join(toks): score+=3
            score += DEVICE_CLASS_PRIORITY.get(device_class,0)
            if domain in ("person","device_tracker"): score+=5
            if eid.endswith(("_linkquality","_rssi","_lqi")): score-=2
            if is_unknown: score -= 3

            cats = _infer_categories(eid, name, attrs, domain, device_class)

            facts.append({
                "entity_id": eid,
                "domain": domain,
                "device_class": device_class,
                "friendly_name": name,
                "area": area_name,
                "state": state,
                "unit": unit,
                "last_changed": last_changed,
                "summary": summary,
                "score": score,
                "cats": sorted(list(cats))
            })
        except Exception as e:
            print(f"[RAG] Error processing entity {item.get('entity_id', 'unknown')}: {e}")
            continue
    return facts

# ----------------- IO + cache -----------------

def refresh_and_cache() -> List[Dict[str,Any]]:
    global _LAST_REFRESH_TS, _MEM_CACHE
    
    with _CACHE_LOCK:
        cfg = _load_options()
        facts = _fetch_ha_states(cfg)
        _MEM_CACHE = facts

        result_paths=[]
        try:
            # Create payload with metadata
            payload = {
                "facts": facts,
                "timestamp": time.time(),
                "count": len(facts)
            }
            
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

def load_cached() -> List[Dict[str,Any]]:
    global _MEM_CACHE
    with _CACHE_LOCK:
        if _MEM_CACHE: return _MEM_CACHE
        
        try:
            # Try primary locations first
            for d in PRIMARY_DIRS:
                p=os.path.join(d,BASENAME)
                if os.path.exists(p):
                    with open(p,"r",encoding="utf-8") as f:
                        data = json.load(f)
                        # Handle both old format (list) and new format (dict with facts key)
                        if isinstance(data, list):
                            return data
                        elif isinstance(data, dict) and "facts" in data:
                            return data["facts"]
            
            # Try fallback
            if os.path.exists(FALLBACK_PATH):
                with open(FALLBACK_PATH,"r",encoding="utf-8") as f: 
                    data = json.load(f)
                    # Handle both old format (list) and new format (dict with facts key)
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "facts" in data:
                        return data["facts"]
        except Exception as e:
            print(f"[RAG] Error loading cached facts: {e}")
            
        return []

def get_facts(force_refresh: bool=False) -> List[Dict[str,Any]]:
    with _CACHE_LOCK:
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
    if q_tokens & MEDIA_KEYWORDS:
        out.update({"media"})
    return out

def inject_context(user_msg: str, top_k: int=DEFAULT_TOP_K) -> str:
    q_raw = _tok(user_msg)
    q = set(_expand_query_tokens(q_raw))
    facts = get_facts()

    # ---- Domain/keyword overrides ----
    filtered = []
    if "light" in q or "lights" in q:
        filtered += [f for f in facts if f.get("domain") == "light"]
    if "switch" in q or "switches" in q:
        filtered += [f for f in facts if f.get("domain") == "switch" and not f.get("entity_id","").startswith("automation.")]
    if "motion" in q or "occupancy" in q:
        filtered += [f for f in facts if f.get("domain") == "binary_sensor" and f.get("device_class") == "motion"]
    if "axpert" in q:
        filtered += [f for f in facts if "axpert" in f.get("entity_id","").lower() or "axpert" in f.get("friendly_name","").lower()]
    if "sonoff" in q:
        filtered += [f for f in facts if "sonoff" in f.get("entity_id","").lower() or "sonoff" in f.get("friendly_name","").lower()]
    if "zigbee" in q or "z2m" in q:
        filtered += [f for f in facts if "zigbee" in f.get("entity_id","").lower() or "zigbee" in f.get("friendly_name","").lower()]
    if "where" in q:
        filtered += [f for f in facts if f.get("domain") in ("person","device_tracker")]
    if q & MEDIA_KEYWORDS:
        filtered += [f for f in facts if any(
            m in f.get("entity_id","").lower() or m in f.get("friendly_name","").lower()
            for m in MEDIA_KEYWORDS
        )]
    # area queries
    for f in facts:
        if f.get("area") and f.get("area","").lower() in q:
            filtered.append(f)

    if filtered:
        facts = filtered

    want_cats = _intent_categories(q)

    scored: List[Tuple[int, Dict[str, Any]]] = []
    for f in facts:
        s = int(f.get("score", 1))
        ft = set(_tok(f.get("summary", "")) + _tok(f.get("entity_id", "")))
        cats = set(f.get("cats", []))

        if q and (q & ft): s += 3
        if q & SOLAR_KEYWORDS: s += 2
        if {"state_of_charge","battery_state_of_charge","battery_soc","soc"} & ft:
            s += 12
        if want_cats and (cats & want_cats):
            s += 15
        if want_cats & {"energy.storage"} and "energy.storage" in cats:
            s += 20
        if (("soc" in q) or (want_cats & {"energy.storage"})) and \
           ("device.battery" in cats) and ("energy.storage" not in cats):
            s -= 18
        if (("soc" in q) or (want_cats & {"energy.storage"})) and \
           (("forecast" in ft) or ("estimated" in ft)):
            s -= 12

        scored.append((s, f))

    scored.sort(key=lambda x: x[0], reverse=True)

    ctx_tokens = _ctx_tokens_from_options()
    budget = _rag_budget_tokens(ctx_tokens)

    candidate_facts = [f for _, f in (scored[:top_k] if top_k else scored)]

    if ("soc" in q) or (want_cats & {"energy.storage"}):
        ess_first = [f for f in candidate_facts if "energy.storage" in set(f.get("cats", []))]
        others    = [f for f in candidate_facts if "energy.storage" not in set(f.get("cats", []))]
        ordered   = ess_first + others
    else:
        ordered = candidate_facts

    selected: List[str] = []
    remaining = budget
    seen_entities: Set[str] = set()

    for f in ordered:
        line = f.get("summary", "")
        eid = f.get("entity_id", "")
        if not line:
            continue
        
        # Skip duplicate/similar SOC entities when querying for battery SOC
        if ("soc" in q) or (want_cats & {"energy.storage"}):
            # Extract the base entity name without the specific attribute
            base_name = re.sub(r'_(soc|state_of_charge|battery).*$', '', eid.lower())
            
            # If we've already added an SOC entity from this device, skip additional ones
            if base_name in seen_entities and "soc" in eid.lower():
                continue
            
            # Track this entity
            if "soc" in eid.lower() or "state_of_charge" in eid.lower():
                seen_entities.add(base_name)
        
        cost = _estimate_tokens(line)
        if cost <= remaining:
            selected.append(line)
            remaining -= cost
        if not selected and cost > remaining and remaining > 0:
            selected.append(line)
            remaining = 0
        if remaining <= 0:
            break

    return "\n".join(selected)

# ----------------- Additional utility functions -----------------

def search_entities(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search entities based on query string"""
    facts = get_facts()
    
    if not query:
        return facts[:limit]
    
    q_tokens = set(_tok(query))
    
    # Score and filter entities
    scored = []
    for entity in facts:
        score = 0
        entity_tokens = set(_tok(entity.get("entity_id", "")) + _tok(entity.get("friendly_name", "")))
        
        # Exact matches
        if q_tokens & entity_tokens:
            score += 10
        
        # Partial matches
        for token in q_tokens:
            if any(token in et for et in entity_tokens):
                score += 3
        
        if score > 0:
            scored.append((score, entity))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return [entity for _, entity in scored[:limit]]

def get_stats() -> Dict[str, Any]:
    """Get statistics about the RAG system"""
    facts = get_facts()
    
    # Count by domain
    domain_counts = {}
    for entity in facts:
        domain = entity.get("domain", "unknown")
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
    
    return {
        "total_facts": len(facts),
        "domains": domain_counts,
        "areas": len(_AREA_MAP),
        "last_refresh": _LAST_REFRESH_TS,
        "cache_size": len(_MEM_CACHE)
    }

# ----------------- main -----------------

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "refresh":
            print("Manually refreshing RAG facts...")
            facts = refresh_and_cache()
            print(f"Refreshed {len(facts)} facts.")
            
        elif command == "stats":
            stats = get_stats()
            print(json.dumps(stats, indent=2))
            
        elif command == "search" and len(sys.argv) > 2:
            query = " ".join(sys.argv[2:])
            results = search_entities(query, 10)
            print(f"Found {len(results)} entities for '{query}':")
            for r in results:
                print(f"  - {r.get('summary', r.get('entity_id', 'unknown'))}")
                
        elif command == "context" and len(sys.argv) > 2:
            query = " ".join(sys.argv[2:])
            context = inject_context(query)
            print(f"Context for '{query}':")
            print("=" * 50)
            print(context)
            
        elif command == "test":
            print("Testing configuration...")
            cfg = _load_options()
            print(f"Config keys: {list(cfg.keys())}")
            facts = get_facts(force_refresh=True)
            print(f"Successfully loaded {len(facts)} facts")
            
        else:
            print("Usage: python rag.
[refresh|stats|search <query>|context <query>|test]")
    else:
        print("Refreshing RAG facts from Home Assistant...")
        facts = refresh_and_cache()
        print(f"Wrote {len(facts)} facts.")