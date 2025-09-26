#!/usr/bin/env python3
# /app/rag.py  (REST → /api/states + /api/areas + Free Knowledge APIs)
#
# - Reads HA URL + token from /data/options.json (/data/config.json fallback)
# - Pulls states via /api/states (read-only) + area metadata via /api/areas
# - Fetches entertainment, automotive, tech knowledge from free APIs
# - Summarizes/boosts entities and auto-categorizes them (no per-entity config)
# - Writes primary JSON to /share/jarvis_prime/memory/rag_facts.json
#   and also mirrors to /data/rag_facts.json as a fallback
# - inject_context(user_msg, top_k) returns a small, relevant context block
#
# Safe: read-only, never calls HA /api/services

import os, re, json, time, threading, urllib.request, requests
from typing import Any, Dict, List, Tuple, Set
from datetime import datetime

OPTIONS_PATHS = ["/data/options.json", "/data/config.json"]

# Primary (single target) + fallback
PRIMARY_DIRS   = ["/share/jarvis_prime/memory"]
FALLBACK_PATH  = "/data/rag_facts.json"
BASENAME       = "rag_facts.json"

# Include ALL domains
INCLUDE_DOMAINS = None

# ----------------- Free API Endpoints -----------------

# All free, no API keys needed
FREE_APIS = {
    # Entertainment APIs with actual movie/actor data
    "trending_movies": "https://api.themoviedb.org/3/trending/movie/day?api_key=15d2ea6d0dc1d476efbca3eba2b9bbfb",  # Free public key
    "trending_tv": "https://api.themoviedb.org/3/trending/tv/day?api_key=15d2ea6d0dc1d476efbca3eba2b9bbfb",
    "popular_movies": "https://api.themoviedb.org/3/movie/popular?api_key=15d2ea6d0dc1d476efbca3eba2b9bbfb",
    "popular_actors": "https://api.themoviedb.org/3/person/popular?api_key=15d2ea6d0dc1d476efbca3eba2b9bbfb",
    
    # Other free APIs
    "news": "https://newsapi.org/v2/top-headlines?country=us&pageSize=5&apiKey=demo",
    "cars": "https://vpic.nhtsa.dot.gov/api/vehicles/GetMakesForVehicleType/car?format=json",
    "space": "http://api.open-notify.org/astros.json",
    "programming_jokes": "https://v2.jokeapi.dev/joke/Programming?type=single",
    "tech_news": "https://hn.algolia.com/api/v1/search_by_date?tags=story&hitsPerPage=5",
    "world_time": "http://worldtimeapi.org/api/ip",
}

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

# Entertainment keywords (expanded)
MOVIE_KEYWORDS = {"movie", "film", "cinema", "theatre", "hollywood", "blockbuster"}
TV_KEYWORDS_ENT = {"tv", "television", "series", "show", "netflix", "hbo", "disney", "amazon"}
ACTOR_KEYWORDS = {"actor", "actress", "celebrity", "star", "director", "producer"}
GENRE_KEYWORDS = {"action", "comedy", "drama", "horror", "sci-fi", "romance", "thriller"}

ENTERTAINMENT_KEYWORDS = set().union(MOVIE_KEYWORDS, TV_KEYWORDS_ENT, ACTOR_KEYWORDS, GENRE_KEYWORDS)

# Knowledge domains
AUTOMOTIVE_KEYWORDS = {"car", "vehicle", "ford", "toyota", "honda", "tesla", "bmw", "mercedes", "audi"}
TECH_KEYWORDS = {"tech", "technology", "computer", "software", "hardware", "programming", "ai", "coding"}
NEWS_KEYWORDS = {"news", "headlines", "current", "events", "world", "politics"}
WEATHER_KEYWORDS = {"weather", "temperature", "forecast", "rain", "sunny", "cloudy"}
SPACE_KEYWORDS = {"space", "astronaut", "nasa", "orbit", "iss", "rocket"}
JOKE_KEYWORDS = {"joke", "funny", "humor", "laugh", "comedy"}
QUOTE_KEYWORDS = {"quote", "inspiration", "motivation", "wisdom"}

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
    "movie": ["movie", "film", "cinema", "flick"],
    "tv": ["tv", "television", "series", "show"],
    "actor": ["actor", "actress", "celebrity", "star"],
    "car": ["car", "vehicle", "auto", "automobile", "ride"],
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
    "movie": {"entertainment.movies"},
    "tv": {"entertainment.tv"},
    "actor": {"entertainment.people"},
    "car": {"automotive"},
    "tech": {"technology"},
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

# ----------------- Free API Knowledge Fetching -----------------

def _fetch_entertainment_facts() -> List[Dict[str, Any]]:
    """Fetch current movies, TV shows, and actors from TMDB"""
    facts = []
    
    # Trending Movies
    try:
        response = requests.get(FREE_APIS["trending_movies"], timeout=10)
        if response.status_code == 200:
            data = response.json()
            for movie in data.get("results", [])[:5]:
                release_year = movie.get("release_date", "")[:4] if movie.get("release_date") else "TBA"
                facts.append({
                    "type": "knowledge",
                    "category": "entertainment",
                    "entity_id": f"movie.{movie['id']}",
                    "domain": "knowledge",
                    "friendly_name": movie.get("title", ""),
                    "title": movie.get("title", ""),
                    "summary": f"Trending Movie: {movie.get('title', '')} ({release_year}) - Rating: {movie.get('vote_average', 0)}/10 - {movie.get('overview', '')[:100]}...",
                    "popularity": movie.get("popularity", 0),
                    "release_date": movie.get("release_date", ""),
                    "score": 9,
                    "cats": ["entertainment", "entertainment.movies", "trending"],
                    "last_updated": datetime.now().isoformat()
                })
    except Exception as e:
        print(f"Trending movies API error: {e}")
    
    # Popular TV Shows
    try:
        response = requests.get(FREE_APIS["trending_tv"], timeout=10)
        if response.status_code == 200:
            data = response.json()
            for show in data.get("results", [])[:5]:
                first_air_year = show.get("first_air_date", "")[:4] if show.get("first_air_date") else "TBA"
                facts.append({
                    "type": "knowledge",
                    "category": "entertainment",
                    "entity_id": f"tv.{show['id']}",
                    "domain": "knowledge",
                    "friendly_name": show.get("name", ""),
                    "title": show.get("name", ""),
                    "summary": f"Trending TV Show: {show.get('name', '')} ({first_air_year}) - Rating: {show.get('vote_average', 0)}/10 - {show.get('overview', '')[:100]}...",
                    "popularity": show.get("popularity", 0),
                    "first_air_date": show.get("first_air_date", ""),
                    "score": 8,
                    "cats": ["entertainment", "entertainment.tv", "trending"],
                    "last_updated": datetime.now().isoformat()
                })
    except Exception as e:
        print(f"Trending TV API error: {e}")
    
    # Popular Actors
    try:
        response = requests.get(FREE_APIS["popular_actors"], timeout=10)
        if response.status_code == 200:
            data = response.json()
            for person in data.get("results", [])[:8]:
                known_for = [item.get("title") or item.get("name") for item in person.get("known_for", [])[:2]]
                known_for_str = ", ".join([k for k in known_for if k])
                facts.append({
                    "type": "knowledge",
                    "category": "entertainment",
                    "entity_id": f"person.{person['id']}",
                    "domain": "knowledge",
                    "friendly_name": person.get("name", ""),
                    "title": person.get("name", ""),
                    "summary": f"Popular Actor: {person.get('name', '')} - Known for: {known_for_str}",
                    "popularity": person.get("popularity", 0),
                    "known_for": known_for,
                    "score": 7,
                    "cats": ["entertainment", "entertainment.people", "actors"],
                    "last_updated": datetime.now().isoformat()
                })
    except Exception as e:
        print(f"Popular actors API error: {e}")
    
    return facts

def _fetch_other_knowledge_facts() -> List[Dict[str, Any]]:
    """Fetch other types of knowledge facts"""
    facts = []
    
    # Car facts
    try:
        response = requests.get(FREE_APIS["cars"], timeout=10)
        if response.status_code == 200:
            car_data = response.json()
            for make in car_data.get("Results", [])[:8]:
                facts.append({
                    "type": "knowledge",
                    "category": "automotive",
                    "entity_id": f"car.{make.get('MakeId', '')}",
                    "domain": "knowledge",
                    "friendly_name": make.get("MakeName", ""),
                    "title": make.get("MakeName", ""),
                    "summary": f"Car brand: {make.get('MakeName', '')}",
                    "score": 5,
                    "cats": ["automotive", "cars"],
                    "last_updated": datetime.now().isoformat()
                })
    except Exception as e:
        print(f"Car API error: {e}")
    
    # Space facts
    try:
        response = requests.get(FREE_APIS["space"], timeout=10)
        if response.status_code == 200:
            space_data = response.json()
            facts.append({
                "type": "knowledge",
                "category": "space",
                "entity_id": "space.astronauts",
                "domain": "knowledge",
                "friendly_name": "People in Space",
                "title": "People in Space",
                "summary": f"There are {space_data.get('number', 0)} people in space right now: {', '.join([p['name'] for p in space_data.get('people', [])])}",
                "score": 5,
                "cats": ["space", "science"],
                "last_updated": datetime.now().isoformat()
            })
    except Exception as e:
        print(f"Space API error: {e}")
    
    # Tech news
    try:
        response = requests.get(FREE_APIS["tech_news"], timeout=10)
        if response.status_code == 200:
            tech_data = response.json()
            for hit in tech_data.get("hits", [])[:3]:
                facts.append({
                    "type": "knowledge",
                    "category": "technology",
                    "entity_id": f"tech.{hit.get('created_at_i', '')}",
                    "domain": "knowledge",
                    "friendly_name": hit.get("title", ""),
                    "title": hit.get("title", ""),
                    "summary": f"Tech News: {hit.get('title', '')} - Points: {hit.get('points', 0)}",
                    "score": 6,
                    "cats": ["technology", "news"],
                    "last_updated": datetime.now().isoformat()
                })
    except Exception as e:
        print(f"Tech news API error: {e}")
    
    return facts

def _fetch_knowledge_facts() -> List[Dict[str, Any]]:
    """Combine all knowledge facts"""
    facts = []
    
    # Entertainment facts (movies, TV, actors)
    entertainment_facts = _fetch_entertainment_facts()
    facts.extend(entertainment_facts)
    
    # Other knowledge facts
    other_facts = _fetch_other_knowledge_facts()
    facts.extend(other_facts)
    
    return facts

# ----------------- Home Assistant Integration -----------------

def _fetch_ha_areas() -> Dict[str, str]:
    """Fetch area information from Home Assistant"""
    cfg = _load_options()
    ha_url = cfg.get("ha_url", "").strip()
    ha_token = cfg.get("ha_token", "").strip()
    
    if not ha_url or not ha_token:
        print("Warning: No HA URL/token configured")
        return {}
    
    try:
        url = f"{ha_url}/api/areas"
        headers = {
            "Authorization": f"Bearer {ha_token}",
            "Content-Type": "application/json"
        }
        data = _http_get_json(url, headers)
        return {area["area_id"]: area["name"] for area in data}
    except Exception as e:
        print(f"Error fetching areas: {e}")
        return {}

def _fetch_ha_states() -> List[Dict[str, Any]]:
    """Fetch entity states from Home Assistant"""
    cfg = _load_options()
    ha_url = cfg.get("ha_url", "").strip()
    ha_token = cfg.get("ha_token", "").strip()
    
    if not ha_url or not ha_token:
        print("Warning: No HA URL/token configured")
        return []
    
    try:
        url = f"{ha_url}/api/states"
        headers = {
            "Authorization": f"Bearer {ha_token}",
            "Content-Type": "application/json"
        }
        return _http_get_json(url, headers)
    except Exception as e:
        print(f"Error fetching states: {e}")
        return []

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

    # Knowledge domains
    if any(k in toks for k in ENTERTAINMENT_KEYWORDS): 
        cats.add("entertainment")
        if toks & MOVIE_KEYWORDS: cats.add("entertainment.movies")
        if toks & TV_KEYWORDS_ENT: cats.add("entertainment.tv")
        if toks & ACTOR_KEYWORDS: cats.add("entertainment.people")
    if any(k in toks for k in AUTOMOTIVE_KEYWORDS): cats.add("automotive")
    if any(k in toks for k in TECH_KEYWORDS): cats.add("technology")
    if any(k in toks for k in NEWS_KEYWORDS): cats.add("news")
    if any(k in toks for k in WEATHER_KEYWORDS): cats.add("weather")
    if any(k in toks for k in SPACE_KEYWORDS): cats.add("space")
    if any(k in toks for k in JOKE_KEYWORDS): cats.add("humor")

    # Infra / system
    if toks & PROXMOX_KEYWORDS: cats.add("infra.proxmox")
    if toks & SPEEDTEST_KEYS: cats.add("infra.speedtest")
    if toks & CPU_KEYS: cats.add("infra.cpu")
    if toks & WEATHER_KEYS: cats.add("weather")

    return cats

def _build_summary(eid: str, name: str, state: str, attrs: Dict[str,Any], domain: str, device_class: str, area: str) -> str:
    """Build a summary for an entity"""
    parts = [name or eid]
    
    if area:
        parts.append(f"(in {area})")
    
    if state and state not in ("unavailable", "unknown"):
        if domain == "person" or domain == "device_tracker":
            zone = _safe_zone_from_tracker(state, attrs)
            parts.append(f"is at {zone}")
        elif device_class == "battery":
            parts.append(f"battery at {state}%")
        elif domain in ("light", "switch", "fan"):
            parts.append(f"is {state}")
        elif domain == "sensor":
            unit = attrs.get("unit_of_measurement", "")
            if unit:
                parts.append(f"reads {state} {unit}")
            else:
                parts.append(f"is {state}")
        else:
            parts.append(f"is {state}")
    
    return " ".join(parts)

def _calculate_score(eid: str, name: str, attrs: Dict[str,Any], domain: str, device_class: str, cats: Set[str]) -> int:
    """Calculate relevance score for an entity"""
    score = 1
    
    # Domain-based scoring
    domain_scores = {
        "person": 8, "device_tracker": 8, "light": 6, "switch": 6, "sensor": 5,
        "binary_sensor": 4, "climate": 7, "media_player": 6, "automation": 3
    }
    score += domain_scores.get(domain, 1)
    
    # Device class priority
    if device_class:
        score += DEVICE_CLASS_PRIORITY.get(device_class, 0)
    
    # Category-based boosts
    if "energy" in cats: score += 3
    if "energy.storage" in cats: score += 5
    if "media" in cats: score += 2
    if "person" in cats: score += 4
    
    # Name-based adjustments
    name_lower = (name or "").lower()
    if "main" in name_lower or "primary" in name_lower: score += 2
    if "hidden" in name_lower or "helper" in name_lower: score -= 2
    
    return max(1, score)

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
    if q_tokens & ENTERTAINMENT_KEYWORDS:
        out.update({"entertainment"})
        if q_tokens & MOVIE_KEYWORDS: out.update({"entertainment.movies"})
        if q_tokens & TV_KEYWORDS_ENT: out.update({"entertainment.tv"})
        if q_tokens & ACTOR_KEYWORDS: out.update({"entertainment.people"})
    if q_tokens & AUTOMOTIVE_KEYWORDS:
        out.update({"automotive"})
    if q_tokens & TECH_KEYWORDS:
        out.update({"technology"})
    if q_tokens & NEWS_KEYWORDS:
        out.update({"news"})
    if q_tokens & SPACE_KEYWORDS:
        out.update({"space"})
    return out

# ----------------- Core RAG Functions -----------------

def refresh_and_cache() -> List[Dict[str, Any]]:
    """Refresh facts from HA and external APIs, cache them"""
    global _MEM_CACHE, _AREA_MAP, _LAST_REFRESH_TS
    
    with _CACHE_LOCK:
        now = time.time()
        
        # Fetch area mapping
        _AREA_MAP = _fetch_ha_areas()
        
        # Fetch HA states
        ha_states = _fetch_ha_states()
        facts = []
        
        # Process HA entities
        for state_obj in ha_states:
            try:
                eid = state_obj["entity_id"]
                domain = eid.split(".")[0]
                
                # Skip if domain filtering is active
                if INCLUDE_DOMAINS and domain not in INCLUDE_DOMAINS:
                    continue
                
                attrs = state_obj.get("attributes", {})
                state = state_obj.get("state", "")
                name = attrs.get("friendly_name", eid)
                device_class = attrs.get("device_class", "")
                area_id = attrs.get("area_id")
                area = _AREA_MAP.get(area_id, "") if area_id else ""
                
                # Infer categories
                cats = _infer_categories(eid, name, attrs, domain, device_class)
                
                # Build summary
                summary = _build_summary(eid, name, state, attrs, domain, device_class, area)
                
                # Calculate score
                score = _calculate_score(eid, name, attrs, domain, device_class, cats)
                
                fact = {
                    "type": "ha_entity",
                    "entity_id": eid,
                    "domain": domain,
                    "friendly_name": name,
                    "state": state,
                    "device_class": device_class,
                    "area": area,
                    "summary": summary,
                    "score": score,
                    "cats": list(cats),
                    "last_updated": state_obj.get("last_updated", "")
                }
                facts.append(fact)
                
            except Exception as e: