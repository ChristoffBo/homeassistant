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
from collections import defaultdict

OPTIONS_PATHS = ["/data/options.json", "/data/config.json"]

# Primary (single target) + fallback
PRIMARY_DIRS   = ["/share/jarvis_prime/memory"]
FALLBACK_PATH  = "/data/rag_facts.json"
BASENAME       = "rag_facts.json"

# Include ALL domains
INCLUDE_DOMAINS = None

# ----------------- Keywords / Integrations -----------------

# Energy / Solar
SOLAR_KEYWORDS   = {"solar","solar_assistant","pv","inverter","ess","battery_soc","soc","battery","grid","load","generation","import","export"}
AXPERT_KEYWORDS  = {"axpert"}
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

# Room/area synonyms for better matching
AREA_SYNONYMS = {
    "living": ["living_room", "lounge", "livingroom", "sitting_room"],
    "bed": ["bedroom", "bed_room", "master_bedroom", "guest_bedroom"],
    "bath": ["bathroom", "bath_room", "toilet", "restroom"],
    "kitchen": ["kitchen", "cook"],
    "garage": ["garage", "car"],
    "outside": ["outdoor", "outside", "exterior", "garden", "yard", "patio", "deck"],
    "office": ["office", "study", "workspace"],
    "dining": ["dining", "dining_room", "diningroom"],
}

# ----------------- Device-class priority -----------------

DEVICE_CLASS_PRIORITY = {
    "motion":6,"presence":6,"occupancy":5,"door":4,"opening":4,"window":3,
    "battery":3,"temperature":3,"humidity":2,"power":3,"energy":3,
    "illuminance":2,"lock":5,"smoke":7,"gas":7,"problem":6
}

# ----------------- Query synonyms -----------------

QUERY_SYNONYMS = {
    "soc": ["soc","state_of_charge","battery_state_of_charge","battery_soc","battery","charge","charge_percentage","soc_percentage","soc_percent"],
    "solar": ["solar","pv","generation","inverter","array","ess"],
    "pv": ["pv","solar"],
    "load": ["load","power","w","kw","consumption","usage"],
    "grid": ["grid","import","export","utility"],
    "battery": ["battery","soc","charge","state_of_charge","battery_state_of_charge","charge_percentage","soc_percentage","soc_percent"],
    "where": ["where","location","zone","home","work","present","at"],
    "lights": ["light","lights","lighting","lamp","lamps","bulb","bulbs"],
    "switches": ["switch","switches","outlet","outlets","plug","plugs"],
    "temperature": ["temp","temperature","hot","cold","warm","cool"],
    "humidity": ["humidity","humid","moisture","dampness"],
    "on": ["on","enabled","active","running"],
    "off": ["off","disabled","inactive","stopped"],
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
    "axpert": {"energy.inverter"},
}

REFRESH_INTERVAL_SEC = 10*60
DEFAULT_TOP_K = 15  # Increased from 10 for better context
_CACHE_LOCK = threading.RLock()
_LAST_REFRESH_TS = 0.0
_MEM_CACHE: List[Dict[str,Any]] = []
_AREA_MAP: Dict[str,str] = {}
_AREA_FETCH_ATTEMPTS = 0
MAX_AREA_FETCH_ATTEMPTS = 3

# New: Track area-to-entities mapping for smarter queries
_AREA_ENTITIES: Dict[str, List[str]] = {}

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

def _match_area_fuzzy(query_token: str, area_name: str) -> bool:
    """Smart area matching with synonyms"""
    area_lower = area_name.lower()
    area_tokens = _tok(area_name)
    
    # Direct match
    if query_token in area_lower or query_token in area_tokens:
        return True
    
    # Check synonyms
    for key, synonyms in AREA_SYNONYMS.items():
        if query_token == key or query_token in synonyms:
            for syn in synonyms:
                if syn in area_lower or syn in area_tokens:
                    return True
    
    # Partial match (e.g., "bed" matches "bedroom")
    for token in area_tokens:
        if query_token in token or token in query_token:
            return True
    
    return False

def _calculate_recency_score(last_changed: str) -> int:
    """Calculate score boost based on how recent the state change was"""
    if not last_changed:
        return 0
    
    try:
        # Parse timestamp
        ts = last_changed.replace("T", " ").split(".")[0].replace("Z", "")
        changed_time = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
        age_seconds = time.time() - changed_time
        
        # Recent changes get boost
        if age_seconds < 300:  # 5 minutes
            return 8
        elif age_seconds < 900:  # 15 minutes
            return 5
        elif age_seconds < 3600:  # 1 hour
            return 3
        elif age_seconds < 86400:  # 1 day
            return 1
        return 0
    except:
        return 0

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

SAFE_RAG_BUDGET_FRACTION = 0.35  # Increased from 0.30 for more context
def _estimate_tokens(text: str) -> int:
    if not text: return 0
    # More accurate token estimation
    words = len(re.findall(r"\S+", text))
    special_chars = len(re.findall(r"[^\w\s]", text))
    return max(8, min(int(words * 1.3 + special_chars * 0.5), 150))

def _ctx_tokens_from_options() -> int:
    cfg = _load_options()
    try: return int(cfg.get("llm_ctx_tokens", 4096))
    except Exception: return 4096

def _rag_budget_tokens(ctx_tokens: int) -> int:
    return max(256, int(ctx_tokens * SAFE_RAG_BUDGET_FRACTION))

def _is_stale_entity(last_changed: str, domain: str) -> bool:
    """Check if entity hasn't updated in a long time (likely offline/unused)"""
    if not last_changed or domain in ("person", "device_tracker"):
        return False
    
    try:
        ts = last_changed.replace("T", " ").split(".")[0].replace("Z", "")
        changed_time = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
        age_days = (time.time() - changed_time) / 86400
        
        # Entity hasn't changed in 7+ days - probably stale
        return age_days > 7
    except:
        return False

# ----------------- categorization -----------------

def _infer_categories(eid: str, name: str, attrs: Dict[str,Any], domain: str, device_class: str) -> Set[str]:
    cats:set[str] = set()
    toks = set(_tok(eid) + _tok(name) + _tok(device_class))
    manf = str(attrs.get("manufacturer","") or attrs.get("vendor","") or "").lower()
    model= str(attrs.get("model","") or "").lower()

    if domain in ("person","device_tracker"):
        cats.add("person")

    # Energy / solar
    is_axpert = any(k in toks for k in AXPERT_KEYWORDS)
    is_solar = any(k in toks for k in SOLAR_KEYWORDS) or "inverter" in model
    
    if is_solar or is_axpert:
        cats.add("energy")
        if "pv" in toks or "solar" in toks: cats.add("energy.pv")
        if "inverter" in toks or "ess" in toks or is_axpert: cats.add("energy.inverter")
        if "soc" in toks or "battery" in toks or "bms" in model: cats.add("energy.storage")
    if "grid" in toks or "import" in toks or "export" in toks: cats.update({"energy","energy.grid"})
    if "load" in toks or "consumption" in toks: cats.update({"energy","energy.load"})
    if device_class == "battery" or "battery" in toks: cats.add("device.battery")

    # Lighting
    if domain == "light" or "light" in toks:
        cats.add("lighting")
    
    # Climate
    if domain == "climate" or device_class in ("temperature", "humidity"):
        cats.add("climate")
    
    # Security
    if device_class in ("door", "window", "lock", "motion", "occupancy", "smoke", "gas"):
        cats.add("security")

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
    """Fetch area map with retry logic"""
    global _AREA_FETCH_ATTEMPTS
    
    ha_url = (cfg.get("ha_url") or 
              cfg.get("homeassistant_url") or 
              cfg.get("llm_enviroguard_ha_base_url") or "").rstrip("/")
    
    ha_token = (cfg.get("ha_token") or 
                cfg.get("homeassistant_token") or 
                cfg.get("llm_enviroguard_ha_token") or "")
    
    if not ha_url or not ha_token: 
        print("[RAG] No HA URL/token found in config")
        return {}
    
    if _AREA_FETCH_ATTEMPTS >= MAX_AREA_FETCH_ATTEMPTS:
        print(f"[RAG] Max area fetch attempts ({MAX_AREA_FETCH_ATTEMPTS}) reached")
        return {}
        
    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    try:
        data = _http_get_json(f"{ha_url}/api/areas", headers, timeout=15)
        amap={}
        if isinstance(data,list):
            for a in data:
                if "area_id" in a and "name" in a:
                    amap[a["area_id"]] = a["name"]
        print(f"[RAG] Loaded {len(amap)} areas")
        _AREA_FETCH_ATTEMPTS = 0
        return amap
    except Exception as e:
        _AREA_FETCH_ATTEMPTS += 1
        print(f"[RAG] Failed to fetch areas (attempt {_AREA_FETCH_ATTEMPTS}/{MAX_AREA_FETCH_ATTEMPTS}): {e}")
        return {}

# ----------------- fetch + summarize -----------------

def _fetch_ha_states(cfg: Dict[str,Any]) -> List[Dict[str,Any]]:
    global _AREA_MAP, _AREA_ENTITIES
    
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

    # Fetch areas first if not loaded
    if not _AREA_MAP or len(_AREA_MAP) == 0:
        _AREA_MAP = _fetch_area_map(cfg)
    
    # Reset area entities mapping
    _AREA_ENTITIES = defaultdict(list)

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
            is_stale = _is_stale_entity(last_changed, domain)
            
            # Track area entities
            if area_name:
                _AREA_ENTITIES[area_name.lower()].append(eid)
            
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

            # Smarter baseline scoring
            score=1
            toks=_tok(eid)+_tok(name)+_tok(device_class)
            
            # Solar scoring - conservative
            if any(k in toks for k in SOLAR_KEYWORDS) and not any(k in toks for k in AXPERT_KEYWORDS):
                score+=3
            if any(k in toks for k in AXPERT_KEYWORDS):
                score+=3
            if "solar_assistant" in "_".join(toks): 
                score+=2
            
            # Device class priority
            score += DEVICE_CLASS_PRIORITY.get(device_class,0)
            
            # Important domains
            if domain in ("person","device_tracker"): 
                score+=5
            if domain == "light": 
                score+=2
            if domain == "switch": 
                score+=2
            if domain == "climate":
                score+=3
            
            # Recency boost
            score += _calculate_recency_score(last_changed)
            
            # Penalties
            if eid.endswith(("_linkquality","_rssi","_lqi")): 
                score-=5
            if is_unknown: 
                score -= 4
            if is_stale:
                score -= 3

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
                "cats": sorted(list(cats)),
                "is_stale": is_stale
            })
        except Exception as e:
            print(f"[RAG] Error processing entity {item.get('entity_id', 'unknown')}: {e}")
            continue
    
    print(f"[RAG] Processed {len(facts)} facts across {len(_AREA_ENTITIES)} areas")
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
            payload = {
                "facts": facts,
                "timestamp": time.time(),
                "count": len(facts),
                "areas": len(_AREA_MAP),
                "area_entities": dict(_AREA_ENTITIES)
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
    global _MEM_CACHE, _AREA_ENTITIES
    with _CACHE_LOCK:
        if _MEM_CACHE: return _MEM_CACHE
        
        try:
            for d in PRIMARY_DIRS:
                p=os.path.join(d,BASENAME)
                if os.path.exists(p):
                    with open(p,"r",encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            return data
                        elif isinstance(data, dict) and "facts" in data:
                            # Load area entities mapping if available
                            if "area_entities" in data:
                                _AREA_ENTITIES = defaultdict(list, data["area_entities"])
                            return data["facts"]
            
            if os.path.exists(FALLBACK_PATH):
                with open(FALLBACK_PATH,"r",encoding="utf-8") as f: 
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "facts" in data:
                        if "area_entities" in data:
                            _AREA_ENTITIES = defaultdict(list, data["area_entities"])
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

def _detect_question_type(user_msg: str) -> str:
    """Detect the type of question being asked"""
    msg_lower = user_msg.lower()
    
    if any(w in msg_lower for w in ["where", "location", "zone"]):
        return "location"
    if any(w in msg_lower for w in ["how many", "count", "list"]):
        return "count"
    if any(w in msg_lower for w in ["what", "status", "state"]):
        return "status"
    if any(w in msg_lower for w in ["temperature", "temp", "hot", "cold"]):
        return "temperature"
    if any(w in msg_lower for w in ["all", "every", "everything"]):
        return "comprehensive"
    
    return "general"

def _intent_categories(q_tokens: Set[str]) -> Set[str]:
    out:set[str] = set()
    for key, cats in INTENT_CATEGORY_MAP.items():
        if key in q_tokens:
            out.update(cats)
    
    if q_tokens & (SOLAR_KEYWORDS - AXPERT_KEYWORDS):
        out.update({"energy","energy.storage","energy.pv","energy.inverter"})
    if q_tokens & AXPERT_KEYWORDS:
        out.update({"energy.inverter"})
    if "grid" in q_tokens:
        out.update({"energy.grid"})
    if "load" in q_tokens:
        out.update({"energy.load"})
    if q_tokens & MEDIA_KEYWORDS:
        out.update({"media"})
    if q_tokens & {"light", "lights", "lighting"}:
        out.add("lighting")
    if q_tokens & {"temperature", "temp", "climate"}:
        out.add("climate")
    if q_tokens & {"motion", "door", "window", "lock", "security"}:
        out.add("security")
    
    return out

def inject_context(user_msg: str, top_k: int=DEFAULT_TOP_K) -> str:
    q_raw = _tok(user_msg)
    q = set(_expand_query_tokens(q_raw))
    facts = get_facts()
    
    question_type = _detect_question_type(user_msg)
    
    # Increase top_k for comprehensive questions
    if question_type == "comprehensive":
        top_k = min(top_k * 2, 30)

    # ---- Smarter domain/keyword filtering ----
    filtered = []
    has_specific_filter = False
    
    # Area-based filtering with fuzzy matching
    matched_areas = []
    for token in q:
        for area_name in _AREA_MAP.values():
            if _match_area_fuzzy(token, area_name):
                matched_areas.append(area_name.lower())
                has_specific_filter = True
    
    if matched_areas:
        for f in facts:
            if f.get("area","").lower() in matched_areas:
                filtered.append(f)
    
    # Domain-specific filters
    if "light" in q or "lights" in q:
        filtered += [f for f in facts if f.get("domain") == "light"]
        has_specific_filter = True
    if "switch" in q or "switches" in q:
        filtered += [f for f in facts if f.get("domain") == "switch" and not f.get("entity_id","").startswith("automation.")]
        has_specific_filter = True
    if "motion" in q or "occupancy" in q:
        filtered += [f for f in facts if f.get("domain") == "binary_sensor" and f.get("device_class") == "motion"]
        has_specific_filter = True
    if q & AXPERT_KEYWORDS:
        filtered += [f for f in facts if "axpert" in f.get("entity_id","").lower() or "axpert" in f.get("friendly_name","").lower()]
        has_specific_filter = True
    if "sonoff" in q:
        filtered += [f for f in facts if "sonoff" in f.get("entity_id","").lower() or "sonoff" in f.get("friendly_name","").lower()]
        has_specific_filter = True
    if "zigbee" in q or "z2m" in q:
        filtered += [f for f in facts if "zigbee" in f.get("entity_id","").lower() or "zigbee" in f.get("friendly_name","").lower()]
        has_specific_filter = True
    if "where" in q:
        filtered += [f for f in facts if f.get("domain") in ("person","device_tracker")]
        has_specific_filter = True
    if q & MEDIA_KEYWORDS:
        filtered += [f for f in facts if any(
            m in f.get("entity_id","").lower() or m in f.get("friendly_name","").lower()
            for m in MEDIA_KEYWORDS
        )]
        has_specific_filter = True

    if filtered:
        facts = filtered

    want_cats = _intent_categories(q)

    scored: List[Tuple[int, Dict[str, Any]]] = []
    for f in facts:
        s = int(f.get("score", 1))
        ft = set(_tok(f.get("summary", "")) + _tok(f.get("entity_id", "")))
        cats = set(f.get("cats", []))
        area = f.get("area", "").lower()

        # Enhanced token matching - exact matches get high boost
        overlap = q & ft
        if overlap:
            s += len(overlap) * 6
        
        # Area matching boost
        if matched_areas and area in matched_areas:
            s += 20
        
        # State matching (on/off queries)
        state_lower = str(f.get("state", "")).lower()
        if "on" in q and state_lower == "on":
            s += 10
        if "off" in q and state_lower == "off":
            s += 10
        
        # Reduced blanket solar boost
        if (q & SOLAR_KEYWORDS) and not has_specific_filter:
            s += 1
        
        # Storage/SOC specific boosts
        if {"state_of_charge","battery_state_of_charge","battery_soc","soc"} & ft:
            s += 12
        
        # Category matching
        if want_cats and (cats & want_cats):
            s += 15
        if want_cats & {"energy.storage"} and "energy.storage" in cats:
            s += 20
        
        # Penalties for irrelevant batteries
        if (("soc" in q) or (want_cats & {"energy.storage"})) and \
           ("device.battery" in cats) and ("energy.storage" not in cats):
            s -= 20
        if (("soc" in q) or (want_cats & {"energy.storage"})) and \
           (("forecast" in ft) or ("estimated" in ft)):
            s -= 15
        
        # Stale entity penalty
        if f.get("is_stale", False):
            s -= 5

        scored.append((s, f))

    scored.sort(key=lambda x: x[0], reverse=True)

    ctx_tokens = _ctx_tokens_from_options()
    budget = _rag_budget_tokens(ctx_tokens)

    candidate_facts = [f for _, f in (scored[:top_k] if top_k else scored)]

    # Smart ordering based on query
    if ("soc" in q) or (want_cats & {"energy.storage"}):
        ess_first = [f for f in candidate_facts if "energy.storage" in set(f.get("cats", []))]
        others    = [f for f in candidate_facts if "energy.storage" not in set(f.get("cats", []))]
        ordered   = ess_first + others
    elif matched_areas:
        # Group by area for area-based queries
        area_grouped = defaultdict(list)
        for f in candidate_facts:
            area_grouped[f.get("area", "")].append(f)
        ordered = []
        for area in matched_areas:
            area_name = next((a for a in _AREA_MAP.values() if a.lower() == area), "")
            ordered.extend(area_grouped.get(area_name, []))
        # Add non-area entities at the end
        ordered.extend(area_grouped.get("", []))
    else:
        ordered = candidate_facts

    selected: List[str] = []
    remaining = budget

    for f in ordered:
        line = f.get("summary", "")
        if not line:
            continue
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
    
    scored = []
    for entity in facts:
        score = 0
        entity_tokens = set(_tok(entity.get("entity_id", "")) + _tok(entity.get("friendly_name", "")))
        
        if q_tokens & entity_tokens:
            score += 10
        
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
    
    domain_counts = {}
    category_counts = {}
    stale_count = 0
    
    for entity in facts:
        domain = entity.get("domain", "unknown")
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        
        for cat in entity.get("cats", []):
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        if entity.get("is_stale", False):
            stale_count += 1
    
    return {
        "total_facts": len(facts),
        "domains": domain_counts,
        "categories": category_counts,
        "areas": len(_AREA_MAP),
        "area_entities": {k: len(v) for k, v in _AREA_ENTITIES.items()},
        "stale_entities": stale_count,
        "last_refresh": _LAST_REFRESH_TS,
        "cache_size": len(_MEM_CACHE),
        "refresh_interval_minutes": REFRESH_INTERVAL_SEC / 60
    }

def get_entities_by_area(area_name: str) -> List[Dict[str, Any]]:
    """Get all entities in a specific area with fuzzy matching"""
    facts = get_facts()
    area_lower = area_name.lower()
    
    matched = []
    for f in facts:
        f_area = f.get("area", "").lower()
        if f_area and (area_lower in f_area or f_area in area_lower or _match_area_fuzzy(area_lower, f.get("area", ""))):
            matched.append(f)
    
    return matched

def get_entities_by_domain(domain: str) -> List[Dict[str, Any]]:
    """Get all entities of a specific domain"""
    facts = get_facts()
    return [f for f in facts if f.get("domain") == domain]

def get_entities_by_category(category: str) -> List[Dict[str, Any]]:
    """Get all entities matching a specific category"""
    facts = get_facts()
    return [f for f in facts if category in f.get("cats", [])]

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
            
        elif command == "area" and len(sys.argv) > 2:
            area = " ".join(sys.argv[2:])
            results = get_entities_by_area(area)
            print(f"Found {len(results)} entities in area '{area}':")
            for r in results:
                print(f"  - {r.get('summary', r.get('entity_id', 'unknown'))}")
                
        elif command == "domain" and len(sys.argv) > 2:
            domain = sys.argv[2]
            results = get_entities_by_domain(domain)
            print(f"Found {len(results)} entities in domain '{domain}':")
            for r in results[:20]:
                print(f"  - {r.get('summary', r.get('entity_id', 'unknown'))}")
                
        elif command == "category" and len(sys.argv) > 2:
            category = sys.argv[2]
            results = get_entities_by_category(category)
            print(f"Found {len(results)} entities in category '{category}':")
            for r in results:
                print(f"  - {r.get('summary', r.get('entity_id', 'unknown'))}")
                
        elif command == "test":
            print("Testing configuration...")
            cfg = _load_options()
            print(f"Config keys: {list(cfg.keys())}")
            
            print("\nFetching areas...")
            global _AREA_MAP
            _AREA_MAP = _fetch_area_map(cfg)
            print(f"Found {len(_AREA_MAP)} areas: {list(_AREA_MAP.values())}")
            
            print("\nFetching entities...")
            facts = get_facts(force_refresh=True)
            print(f"Successfully loaded {len(facts)} facts")
            
            print("\nArea distribution:")
            for area, entities in _AREA_ENTITIES.items():
                print(f"  {area}: {len(entities)} entities")
            
            print("\nSample entities:")
            for f in facts[:5]:
                print(f"  - {f.get('summary', 'unknown')}")
            
        else:
            print("Usage: python rag.py [command] [args]")
            print("\nCommands:")
            print("  refresh              - Manually refresh RAG facts")
            print("  stats                - Show statistics")
            print("  search <query>       - Search for entities")
            print("  context <query>      - Get context for a query")
            print("  area <area_name>     - Get entities by area")
            print("  domain <domain>      - Get entities by domain")
            print("  category <category>  - Get entities by category")
            print("  test                 - Test configuration and connectivity")
    else:
        print("Refreshing RAG facts from Home Assistant...")
        facts = refresh_and_cache()
        print(f"Wrote {len(facts)} facts.")
