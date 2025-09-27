#!/usr/bin/env python3
# /app/rag.py  (REST → /api/states + /api/areas + General Knowledge APIs)
#
# - Reads HA URL + token from /data/options.json (/data/config.json fallback)
# - Pulls states via /api/states (read-only) + area metadata via /api/areas
# - Summarizes/boosts entities and auto-categorizes them (no per-entity config)
# - Writes primary JSON to /share/jarvis_prime/memory/rag_facts.json
#   and also mirrors to /data/rag_facts.json as a fallback
# - Adds General knowledge cache (people/shows/movies via TVMaze; cars via CarQuery)
#   → stored in /share/jarvis_prime/memory/general_facts.json
# - inject_context(user_msg, top_k) returns a small, relevant context block
#   (HA first; if weak/empty, falls back to general facts)
# - Refreshes General knowledge on startup and automatically every 30 days
# - Enforces a hard cap: combined RAG caches never exceed 1 GB
#
# Safe: HA is read-only (no /api/services). External APIs are free/no-key (TVMaze, CarQuery).
#       No CLI required/assumed for add-on operation.

import os, re, json, time, threading, urllib.request, urllib.parse
from typing import Any, Dict, List, Tuple, Set, Optional

OPTIONS_PATHS = ["/data/options.json", "/data/config.json"]

# Primary (single target) + fallback (HA)
PRIMARY_DIRS   = ["/share/jarvis_prime/memory"]
FALLBACK_PATH  = "/data/rag_facts.json"
BASENAME       = "rag_facts.json"                 # HA cache filename (kept for compatibility)

# General knowledge cache filename (separate file)
GENERAL_BASENAME = "general_facts.json"

# Include ALL domains
INCLUDE_DOMAINS = None

# Storage hard cap (across HA + General caches)
MAX_CACHE_BYTES = 1_000_000_000  # 1 GB absolute ceiling

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
    # general knowledge intents
    "actor": ["actor","actress","cast","star","celebrity","celeb","person"],
    "movie": ["movie","film","cinema","motion_picture"],
    "series": ["series","show","tv","tvshow","season","episodes"],
    "car": ["car","auto","vehicle","ev","model","trim","spec"],
}

# Intent → categories we prefer (HA)
INTENT_CATEGORY_MAP = {
    "solar": {"energy.storage","energy.pv","energy.inverter"},
    "pv":    {"energy.pv","energy.inverter","energy.storage"},
    "soc":   {"energy.storage"},
    "battery": {"energy.storage"},
    "grid":  {"energy.grid"},
    "load":  {"energy.load"},
    "media": {"media"},
}

REFRESH_INTERVAL_SEC   = 15*60
GENERAL_REFRESH_DAYS   = 30  # Once per month
DEFAULT_TOP_K          = 10
_CACHE_LOCK            = threading.RLock()
_LAST_REFRESH_TS       = 0.0
_MEM_CACHE: List[Dict[str,Any]]     = []  # HA facts (in-memory)
_GEN_CACHE: List[Dict[str,Any]]     = []  # General facts (in-memory)
_LAST_GENERAL_REFRESH  = 0.0
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

def _http_get_json(url: str, headers: Optional[Dict[str,str]]=None, timeout: int=20):
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8","replace"))

def _write_json_atomic(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(obj,f,indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

def _path_for(basename: str) -> str:
    # always prefer first primary dir
    d = PRIMARY_DIRS[0] if PRIMARY_DIRS else "/share"
    return os.path.join(d, basename)

def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return 0

def _combined_cache_size(bytes_including: int = 0) -> int:
    """Return combined size of HA + General caches, optionally including a prospective write size."""
    ha = _file_size(_path_for(BASENAME))
    gen = _file_size(_path_for(GENERAL_BASENAME))
    return ha + gen + bytes_including

def _safe_write_json_capped(path: str, obj: dict, max_total_bytes: int = MAX_CACHE_BYTES) -> bool:
    """Write JSON atomically, refusing if combined caches would exceed max_total_bytes."""
    try:
        data = json.dumps(obj, indent=2).encode("utf-8")
    except Exception as e:
        print(f"[RAG] JSON serialize failed for {path}: {e}")
        return False
    projected = _combined_cache_size(bytes_including=len(data))
    if projected > max_total_bytes:
        print(f"[RAG] REFUSED write: {path} would exceed 1GB cap (proj={projected} bytes)")
        return False
    # write atomically
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)
    return True

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

# ----------------- categorization (HA) -----------------

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

# ----------------- fetch areas (HA) -----------------

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
    try:
        data = _http_get_json(f"{ha_url}/api/areas", headers, timeout=15)
        amap={}
        if isinstance(data,list):
            for a in data:
                if "area_id" in a and "name" in a:
                    amap[a["area_id"]] = a["name"]
        print(f"[RAG] Loaded {len(amap)} areas")
        return amap
    except Exception as e:
        print(f"[RAG] Failed to fetch areas: {e}")
        return {}

# ----------------- fetch + summarize (HA) -----------------

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

    # also fetch areas once
    if not _AREA_MAP:
        _AREA_MAP = _fetch_area_map(cfg)

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

# ----------------- IO + cache (HA) -----------------

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
                    ok = _safe_write_json_capped(p, payload)
                    if ok: result_paths.append(p)
                except Exception as e:
                    print(f"[RAG] write failed for {d}: {e}")
            try:
                ok = _safe_write_json_capped(FALLBACK_PATH, payload)
                if ok: result_paths.append(FALLBACK_PATH)
            except Exception as e:
                print(f"[RAG] fallback write failed: {e}")
        finally:
            _LAST_REFRESH_TS = time.time()

        print(f"[RAG] wrote {len(facts)} HA facts to: " + " | ".join(result_paths))
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
            print(f"[RAG] Error loading cached HA facts: {e}")
            
        return []

def get_facts(force_refresh: bool=False) -> List[Dict[str,Any]]:
    with _CACHE_LOCK:
        if force_refresh or (time.time() - _LAST_REFRESH_TS > REFRESH_INTERVAL_SEC):
            return refresh_and_cache()
        facts = load_cached()
        if not facts:
            return refresh_and_cache()
        return facts

# ----------------- General Knowledge (TVMaze + CarQuery) -----------------

def _tvmaze_get(path: str, params: Optional[Dict[str, Any]]=None, timeout: int=20):
    base = "https://api.tvmaze.com"
    q = ""
    if params:
        q = "?" + urllib.parse.urlencode(params)
    url = base + path + q
    return _http_get_json(url, timeout=timeout)

def _fetch_tvmaze_shows_sample(pages: int = 4) -> List[Dict[str,Any]]:
    """Pull first N pages of shows (each page ~250 shows)."""
    out=[]
    for pg in range(pages):
        try:
            shows = _tvmaze_get(f"/shows", params={"page": pg})
            if isinstance(shows, list):
                out.extend(shows)
        except Exception as e:
            print(f"[RAG] TVMaze shows page {pg} failed: {e}")
    return out

def _fetch_tvmaze_show_cast(show_id: int) -> List[Dict[str,Any]]:
    try:
        data = _tvmaze_get(f"/shows/{show_id}/cast")
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[RAG] TVMaze cast for show {show_id} failed: {e}")
        return []

def _top_n_shows_from_sample(sample: List[Dict[str,Any]], n: int = 100) -> List[Dict[str,Any]]:
    # Score by rating.average (desc), fallback weight (desc), then updated order
    def score_show(s: Dict[str,Any]) -> Tuple:
        rating = (s.get("rating") or {}).get("average") or 0.0
        weight = s.get("weight") or 0
        premiered = s.get("premiered") or ""
        return (float(rating or 0.0), int(weight or 0), premiered)
    ranked = sorted([s for s in sample if isinstance(s, dict)], key=score_show, reverse=True)
    return ranked[:n]

def _extract_show_fact(s: Dict[str,Any]) -> Dict[str,Any]:
    title = s.get("name") or "Unknown"
    premiered = (s.get("premiered") or "")[:4]
    show_type = s.get("type") or ""
    genres = s.get("genres") or []
    status = s.get("status") or ""
    language = s.get("language") or ""
    network = ((s.get("network") or {}).get("name")) or ((s.get("webChannel") or {}).get("name")) or ""
    rating = (s.get("rating") or {}).get("average")
    summary_html = s.get("summary") or ""
    # Strip simple HTML tags
    summary = re.sub(r"<[^>]+>", "", summary_html).strip()
    sid = s.get("id")
    return {
        "type": "show",
        "source": "tvmaze",
        "id": sid,
        "title": title,
        "year": premiered,
        "genres": genres,
        "status": status,
        "language": language,
        "network": network,
        "rating": rating,
        "kind": show_type,
        "summary": f"{title} ({premiered}) — {show_type}; {', '.join(genres)}; {status}; rating={rating}"[:300]
    }

def _fetch_tvmaze_movies_from_sample(sample: List[Dict[str,Any]], n: int = 100) -> List[Dict[str,Any]]:
    # TVMaze doesn't cover theatrical movies broadly; we approximate by shows with type == "TV Movie".
    tv_movies = [s for s in sample if (s.get("type") or "").lower() == "tv movie"]
    def score_mv(s: Dict[str,Any]) -> Tuple:
        rating = (s.get("rating") or {}).get("average") or 0.0
        premiered = s.get("premiered") or ""
        return (float(rating or 0.0), premiered)
    ranked = sorted(tv_movies, key=score_mv, reverse=True)[:n]
    return [_extract_show_fact(s) | {"type": "movie"} for s in ranked]

def _fetch_tvmaze_people_via_cast(shows: List[Dict[str,Any]], n: int = 100) -> List[Dict[str,Any]]:
    # Build people popularity by frequency across top shows' cast
    freq: Dict[int, Dict[str,Any]] = {}
    for s in shows:
        sid = s.get("id")
        if not sid: continue
        cast = _fetch_tvmaze_show_cast(int(sid))
        for c in cast:
            person = (c or {}).get("person") or {}
            pid = person.get("id")
            if not pid: continue
            d = freq.get(pid) or {"count":0, "person":person}
            d["count"] += 1
            freq[pid] = d
    ranked = sorted(freq.values(), key=lambda x: x["count"], reverse=True)
    out=[]
    for x in ranked[:n]:
        p = x["person"]
        name = p.get("name") or "Unknown"
        country = ((p.get("country") or {}).get("name")) or ""
        birthday = p.get("birthday") or ""
        gender = p.get("gender") or ""
        out.append({
            "type":"person",
            "source":"tvmaze",
            "id": p.get("id"),
            "name": name,
            "country": country,
            "birthday": birthday,
            "gender": gender,
            "summary": f"{name} — {gender or 'N/A'}; {country or 'Unknown'}; born {birthday or '?'}; known for top TV casts."[:300]
        })
    return out

# ----------------- CarQuery (cars since 2023) -----------------

def _carquery_get(params: Dict[str, Any], timeout: int=20):
    base = "https://www.carqueryapi.com/api/0.3/"
    url = base + "?" + urllib.parse.urlencode(params)
    data = _http_get_json(url, timeout=timeout)
    # CarQuery JSON sometimes returns a string-wrapped JSON; handle both
    if isinstance(data, str):
        try:
            return json.loads(data)
        except Exception:
            return {}
    return data

def _fetch_carquery_makes_by_year(year: int) -> List[Dict[str,Any]]:
    try:
        data = _carquery_get({"cmd":"getMakes", "year": year})
        makes = data.get("Makes") or []
        return makes if isinstance(makes, list) else []
    except Exception as e:
        print(f"[RAG] CarQuery makes {year} failed: {e}")
        return []

def _fetch_carquery_trims(make: str, year: int) -> List[Dict[str,Any]]:
    try:
        data = _carquery_get({"cmd":"getTrims", "make": make, "year": year})
        trims = data.get("Trims") or []
        return trims if isinstance(trims, list) else []
    except Exception as e:
        print(f"[RAG] CarQuery trims {make} {year} failed: {e}")
        return []

def _fetch_top_cars_since_2023(max_items: int = 100) -> List[Dict[str,Any]]:
    now_year = time.gmtime().tm_year
    cars=[]
    # Strategy: iterate years from 2023..now, sample makes per year to limit calls,
    # collect trims and build compact facts, stop when we hit max_items.
    for yr in range(2023, now_year+1):
        makes = _fetch_carquery_makes_by_year(yr)
        # Sample at most 20 makes per year for compactness/perf
        for m in (makes[:20] if len(makes) > 20 else makes):
            make_name = m.get("make_display") or m.get("make_name") or ""
            trims = _fetch_carquery_trims(make_name or m.get("make_name",""), yr)
            for t in trims:
                if len(cars) >= max_items: break
                model = t.get("model_name") or ""
                year  = t.get("model_year") or yr
                body  = t.get("model_body") or ""
                engine= (t.get("model_engine_fuel") or "") or (t.get("model_engine_type") or "")
                drive = t.get("model_drive") or ""
                doors = t.get("model_doors") or ""
                seats = t.get("model_seats") or ""
                summary = f"{year} {make_name} {model} — {body or 'vehicle'}; engine={engine or 'n/a'}; drive={drive or 'n/a'}; {doors or '?'} doors; {seats or '?'} seats."
                cars.append({
                    "type":"car",
                    "source":"carquery",
                    "year": str(year),
                    "make": make_name,
                    "model": model,
                    "body": body,
                    "engine": engine,
                    "drive": drive,
                    "doors": doors,
                    "seats": seats,
                    "summary": summary[:300]
                })
            if len(cars) >= max_items: break
        if len(cars) >= max_items: break
    return cars

# ----------------- General facts refresh + cache -----------------

def _build_general_payload() -> Dict[str,Any]:
    # Gather TV shows sample
    sample = _fetch_tvmaze_shows_sample(pages=4)  # ~1000 shows
    top_shows_raw = _top_n_shows_from_sample(sample, n=100)
    top_shows = [_extract_show_fact(s) for s in top_shows_raw]

    # Derive "movies" as TV movies
    top_movies = _fetch_tvmaze_movies_from_sample(sample, n=100)

    # Derive top people via cast frequency in top shows
    top_people = _fetch_tvmaze_people_via_cast(top_shows_raw, n=100)

    # Cars since 2023 (top 100 by sampling)
    top_cars = _fetch_top_cars_since_2023(max_items=100)

    facts: List[Dict[str,Any]] = []
    facts.extend(top_people)
    facts.extend(top_shows)
    facts.extend(top_movies)
    facts.extend(top_cars)

    return {
        "facts": facts,
        "timestamp": time.time(),
        "count": len(facts),
        "source": "tvmaze+carquery",
        "refreshed_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    }

def refresh_general_facts(force: bool = False) -> List[Dict[str,Any]]:
    """Refresh general knowledge cache if never run or older than 30 days, or if force=True."""
    global _GEN_CACHE, _LAST_GENERAL_REFRESH
    with _CACHE_LOCK:
        now = time.time()
        age_days = (now - _LAST_GENERAL_REFRESH) / 86400.0 if _LAST_GENERAL_REFRESH else 1e9
        if (not force) and age_days < GENERAL_REFRESH_DAYS:
            # Load existing if available
            cache = load_general_cached()
            if cache:
                _GEN_CACHE = cache
                return cache
        print("[RAG] Refreshing General facts (TVMaze + CarQuery)...")
        payload = _build_general_payload()
        # Save atomically with size cap
        path = _path_for(GENERAL_BASENAME)
        ok = _safe_write_json_capped(path, payload)
        if not ok:
            print("[RAG] General facts write skipped due to 1GB cap")
        else:
            print(f"[RAG] Wrote General facts: {path} ({payload.get('count')} items)")
        # Update memory regardless (still useful in-session)
        _GEN_CACHE = payload.get("facts", [])
        _LAST_GENERAL_REFRESH = now
        return _GEN_CACHE

def load_general_cached() -> List[Dict[str,Any]]:
    global _GEN_CACHE
    with _CACHE_LOCK:
        if _GEN_CACHE: return _GEN_CACHE
        path = _path_for(GENERAL_BASENAME)
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "facts" in data:
                        return data["facts"]
                    elif isinstance(data, list):
                        return data
        except Exception as e:
            print(f"[RAG] Error loading General cache: {e}")
        return []

def get_general_facts(force_refresh: bool=False) -> List[Dict[str,Any]]:
    with _CACHE_LOCK:
        if force_refresh or not _GEN_CACHE:
            facts = load_general_cached()
            if facts:
                _GEN_CACHE = facts
                return facts
            # no cache → refresh now
            return refresh_general_facts(force=True)
        return _GEN_CACHE

def _general_matches_query(f: Dict[str,Any], q_tokens: Set[str]) -> bool:
    # tokens across key fields
    fields = []
    t = (f.get("type") or "").lower()
    if t in ("show","movie"):
        fields += [f.get("title",""), f.get("genres",[]), f.get("summary",""), f.get("kind","")]
    elif t == "person":
        fields += [f.get("name",""), f.get("country",""), f.get("summary",""), f.get("gender","")]
    elif t == "car":
        fields += [f.get("make",""), f.get("model",""), f.get("year",""), f.get("body",""), f.get("engine",""), f.get("summary","")]
    toks=set()
    for fld in fields:
        if isinstance(fld, list):
            for x in fld: toks.update(_tok(str(x)))
        else:
            toks.update(_tok(str(fld)))
    return bool(q_tokens & toks)

def _general_score(f: Dict[str,Any], q_tokens: Set[str]) -> int:
    s=0
    t=(f.get("type") or "").lower()
    if _general_matches_query(f, q_tokens): s+=10
    # lightweight boosting
    if t=="person" and ({"who","actor","actress","celebrity","celeb","person"} & q_tokens): s+=6
    if t in ("show","movie") and ({"movie","film","series","show","tv"} & q_tokens): s+=6
    if t=="car" and ({"car","vehicle","model","ev"} & q_tokens): s+=6
    rating = f.get("rating")
    if rating: 
        try:
            s += int(float(rating) or 0)
        except Exception:
            pass
    return s

def search_general_entities(query: str, limit: int = 10) -> List[Dict[str,Any]]:
    q_tokens = set(_tok(query))
    facts = get_general_facts()
    scored=[]
    for f in facts:
        sc = _general_score(f, q_tokens)
        if sc>0:
            scored.append((sc, f))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for _,f in scored[:limit]]

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

    # ---- Domain/keyword overrides (HA) ----
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

    # If HA produced nothing useful, try General cache
    if not selected:
        g_matches = search_general_entities(user_msg, limit=top_k)
        remaining = budget
        for g in g_matches:
            line = g.get("summary","") or ""
            # fallback summaries if missing
            t=(g.get("type") or "").lower()
            if not line:
                if t in ("show","movie"):
                    line = f"{g.get('title','?')} ({g.get('year','?')}) — {g.get('kind','show')}; {', '.join(g.get('genres',[]))}"
                elif t=="person":
                    line = f"{g.get('name','?')} — {g.get('gender','?')}; {g.get('country','')} born {g.get('birthday','?')}"
                elif t=="car":
                    line = f"{g.get('year','?')} {g.get('make','?')} {g.get('model','?')} — {g.get('body','vehicle')}"
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
    """Search entities based on query string (HA only)"""
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
    """Get statistics about the RAG system (HA only + general counts if loaded)"""
    facts = get_facts()
    domain_counts = {}
    for entity in facts:
        domain = entity.get("domain", "unknown")
        domain_counts[domain] = domain_counts.get(domain, 0) + 1

    gen_count = len(_GEN_CACHE) if _GEN_CACHE else len(load_general_cached())

    return {
        "total_facts": len(facts),
        "domains": domain_counts,
        "areas": len(_AREA_MAP),
        "last_refresh": _LAST_REFRESH_TS,
        "cache_size": len(_MEM_CACHE),
        "general_count": gen_count,
        "general_last_refresh": _LAST_GENERAL_REFRESH
    }

# ----------------- background scheduler (monthly general refresh) -----------------

def _general_refresh_loop():
    """Background loop that refreshes general facts once every 30 days."""
    global _LAST_GENERAL_REFRESH
    while True:
        try:
            now = time.time()
            # If never refreshed or older than threshold, refresh
            if (_LAST_GENERAL_REFRESH == 0.0) or ((now - _LAST_GENERAL_REFRESH) >= GENERAL_REFRESH_DAYS*86400):
                refresh_general_facts(force=True)
            # Sleep a day; we don't need sub-day precision
            time.sleep(86400)  # 24h
        except Exception as e:
            print(f"[RAG] General refresh loop error: {e}")
            # Avoid busy-looping on error
            time.sleep(3600)

def _start_general_scheduler_if_needed():
    t = threading.Thread(target=_general_refresh_loop, name="rag-general-monthly", daemon=True)
    t.start()

# ----------------- main -----------------

if __name__ == "__main__":
    # NOTE: Keep CLI support as-is for compatibility, but add-on does not need to use it.
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "refresh":
            print("Manually refreshing HA RAG facts...")
            facts = refresh_and_cache()
            print(f"Refreshed {len(facts)} HA facts.")
            print("Refreshing General facts...")
            g = refresh_general_facts(force=True)
            print(f"Refreshed {len(g)} General facts.")

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
            # Ensure general cache is available for fallback context
            get_general_facts(force_refresh=False)
            context = inject_context(query)
            print(f"Context for '{query}':")
            print("=" * 50)
            print(context)
            
        elif command == "test":
            print("Testing configuration...")
            cfg = _load_options()
            print(f"Config keys: {list(cfg.keys())}")
            facts = get_facts(force_refresh=True)
            print(f"Successfully loaded {len(facts)} HA facts")
            g = refresh_general_facts(force=True)
            print(f"Successfully loaded {len(g)} General facts")
            print("Starting background monthly scheduler...")
            _start_general_scheduler_if_needed()
            print("OK.")
            
        else:
            print("Usage: python rag.py [refresh|stats|search <query>|context <query>|test]")
    else:
        # Normal add-on run: refresh HA + General on startup, then start monthly scheduler.
        print("Refreshing HA RAG facts from Home Assistant...")
        facts = refresh_and_cache()
        print(f"Wrote {len(facts)} HA facts.")

        print("Refreshing General knowledge facts (startup)...")
        g = refresh_general_facts(force=True)
        print(f"Wrote {len(g)} General facts.")

        print("Starting background monthly general refresh scheduler...")
        _start_general_scheduler_if_needed()
        print("RAG ready.")
