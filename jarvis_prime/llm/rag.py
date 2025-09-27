#!/usr/bin/env python3
# /app/rag.py  (Enhanced with Weather + General Knowledge)
#
# - Home Assistant: Every 5 minutes + startup (states + areas)
# - Weather: Every hour + startup (OpenWeatherMap free tier)
# - General Knowledge: Weekly + startup (TMDB movies/TV, Wikipedia articles)
# - All read-only, safe APIs
#
# inject_context(user_msg, top_k) returns blended context from all sources

import os, re, json, time, threading, urllib.request, urllib.parse
from typing import Any, Dict, List, Tuple, Set
from datetime import datetime

OPTIONS_PATHS = ["/data/options.json", "/data/config.json"]

# Storage paths
PRIMARY_DIRS = ["/share/jarvis_prime/memory"]
HA_BASENAME = "rag_facts.json"
WEATHER_BASENAME = "weather_facts.json"
GENERAL_BASENAME = "general_knowledge.json"

FALLBACK_HA_PATH = "/data/rag_facts.json"
FALLBACK_WEATHER_PATH = "/data/weather_facts.json"
FALLBACK_GENERAL_PATH = "/data/general_knowledge.json"

# Include ALL domains for HA
INCLUDE_DOMAINS = None

# Refresh intervals
HA_REFRESH_INTERVAL_SEC = 5 * 60  # 5 minutes
WEATHER_REFRESH_INTERVAL_SEC = 60 * 60  # 1 hour
GENERAL_REFRESH_INTERVAL_SEC = 7 * 24 * 60 * 60  # 1 week

# Knowledge cutoff for general data
KNOWLEDGE_CUTOFF_YEAR = 2023

# ----------------- Keywords / Integrations -----------------

# Energy / Solar
SOLAR_KEYWORDS = {"solar","solar_assistant","pv","inverter","ess","battery_soc","soc","battery","grid","load","generation","import","export","axpert"}
SONOFF_KEYWORDS = {"sonoff","tasmota"}
ZIGBEE_KEYWORDS = {"zigbee","zigbee2mqtt","z2m","zha"}
MQTT_KEYWORDS = {"mqtt"}
TUYA_KEYWORDS = {"tuya","localtuya","local_tuya"}
FORECAST_SOLAR = {"forecast.solar","forecastsolar","forecast_solar"}

# Media (separate + combined)
PLEX_KEYWORDS = {"plex"}
EMBY_KEYWORDS = {"emby"}
JELLYFIN_KEYWORDS = {"jellyfin"}
KODI_KEYWORDS = {"kodi","xbmc"}
TV_KEYWORDS = {"tv","androidtv","chromecast","google_tv"}
RADARR_KEYWORDS = {"radarr"}
SONARR_KEYWORDS = {"sonarr"}
LIDARR_KEYWORDS = {"lidarr"}
BAZARR_KEYWORDS = {"bazarr"}
READARR_KEYWORDS = {"readarr"}
SONOS_KEYWORDS = {"sonos"}
AMP_KEYWORDS = {"denon","onkyo","yamaha","marantz"}

MEDIA_KEYWORDS = set().union(
    PLEX_KEYWORDS, EMBY_KEYWORDS, JELLYFIN_KEYWORDS, KODI_KEYWORDS, TV_KEYWORDS,
    RADARR_KEYWORDS, SONARR_KEYWORDS, LIDARR_KEYWORDS, BAZARR_KEYWORDS, READARR_KEYWORDS,
    SONOS_KEYWORDS, AMP_KEYWORDS, {"media","player"}
)

# Infra / system
PROXMOX_KEYWORDS = {"proxmox","pve"}
SPEEDTEST_KEYS = {"speedtest","speed_test"}
CPU_KEYS = {"cpu","processor","loadavg","load_avg"}
WEATHER_KEYS = {"weather","weatherbit","openweathermap","met","yr","temperature","humidity","wind","rain","conditions"}

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
    "weather": ["weather","temperature","temp","humidity","wind","rain","conditions","forecast","outside","outdoor"],
    "movie": ["movie","film","cinema","movies","films"],
    "tv": ["tv","show","series","television","episode","season"],
    "actor": ["actor","actress","star","celebrity","cast"],
}

# Intent → categories we prefer
INTENT_CATEGORY_MAP = {
    "solar": {"energy.storage","energy.pv","energy.inverter"},
    "pv": {"energy.pv","energy.inverter","energy.storage"},
    "soc": {"energy.storage"},
    "battery": {"energy.storage"},
    "grid": {"energy.grid"},
    "load": {"energy.load"},
    "media": {"media"},
    "weather": {"weather"},
    "movie": {"entertainment.movies"},
    "tv": {"entertainment.tv"},
    "actor": {"entertainment.actors"},
}

DEFAULT_TOP_K = 10
SAFE_RAG_BUDGET_FRACTION = 0.30

# Global caches and locks
_CACHE_LOCK = threading.RLock()
_HA_LAST_REFRESH_TS = 0.0
_WEATHER_LAST_REFRESH_TS = 0.0
_GENERAL_LAST_REFRESH_TS = 0.0

_HA_CACHE: List[Dict[str,Any]] = []
_WEATHER_CACHE: List[Dict[str,Any]] = []
_GENERAL_CACHE: List[Dict[str,Any]] = []
_AREA_MAP: Dict[str,str] = {}

# ----------------- Helpers -----------------

def _tok(s: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9_]+", s.lower() if s else "")

def _expand_query_tokens(tokens: List[str]) -> List[str]:
    out = []
    seen = set()
    for t in tokens:
        for x in QUERY_SYNONYMS.get(t, [t]):
            if x not in seen:
                seen.add(x)
                out.append(x)
    return out

def _safe_zone_from_tracker(state: str, attrs: Dict[str,Any]) -> str:
    zone = attrs.get("zone")
    if zone: 
        return zone
    ls = (state or "").lower()
    if ls in ("home","not_home"): 
        return "Home" if ls=="home" else "Away"
    return state

def _load_options() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    for p in OPTIONS_PATHS:
        try:
            if os.path.exists(p):
                with open(p,"r",encoding="utf-8") as f:
                    raw = f.read()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    try:
                        import yaml
                        data = yaml.safe_load(raw)
                    except Exception:
                        data = None
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
        json.dump(obj,f,indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp,path)

def _estimate_tokens(text: str) -> int:
    if not text: 
        return 0
    words = len(re.findall(r"\S+", text))
    return max(8, min(int(words * 1.3), 128))

def _ctx_tokens_from_options() -> int:
    cfg = _load_options()
    try: 
        return int(cfg.get("llm_ctx_tokens", 4096))
    except Exception: 
        return 4096

def _rag_budget_tokens(ctx_tokens: int) -> int:
    return max(256, int(ctx_tokens * SAFE_RAG_BUDGET_FRACTION))

def _is_recent_content(date_str: str, cutoff_year: int = KNOWLEDGE_CUTOFF_YEAR) -> bool:
    """Check if content is from cutoff year onwards"""
    try:
        if not date_str:
            return True  # Include if no date
        year = int(date_str.split('-')[0])
        return year >= cutoff_year
    except:
        return True  # Include if can't parse date

# ----------------- HA Categorization (unchanged) -----------------

def _infer_categories(eid: str, name: str, attrs: Dict[str,Any], domain: str, device_class: str) -> Set[str]:
    cats: set[str] = set()
    toks = set(_tok(eid) + _tok(name) + _tok(device_class))
    manf = str(attrs.get("manufacturer","") or attrs.get("vendor","") or "").lower()
    model = str(attrs.get("model","") or "").lower()

    if domain in ("person","device_tracker"):
        cats.add("person")

    # Energy / solar
    if any(k in toks for k in SOLAR_KEYWORDS) or "inverter" in model:
        cats.add("energy")
        if "pv" in toks or "solar" in toks: 
            cats.add("energy.pv")
        if "inverter" in toks or "ess" in toks: 
            cats.add("energy.inverter")
        if "soc" in toks or "battery" in toks or "bms" in model: 
            cats.add("energy.storage")
    if "grid" in toks or "import" in toks or "export" in toks: 
        cats.update({"energy","energy.grid"})
    if "load" in toks or "consumption" in toks: 
        cats.update({"energy","energy.load"})
    if device_class == "battery" or "battery" in toks: 
        cats.add("device.battery")

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

# ----------------- HA Areas (unchanged) -----------------

def _fetch_area_map(cfg: Dict[str,Any]) -> Dict[str,str]:
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
        amap = {}
        if isinstance(data,list):
            for a in data:
                if "area_id" in a and "name" in a:
                    amap[a["area_id"]] = a["name"]
        print(f"[RAG] Loaded {len(amap)} areas")
        return amap
    except Exception as e:
        print(f"[RAG] Failed to fetch areas: {e}")
        return {}

# ----------------- HA Data Fetching (updated to 5min) -----------------

def _fetch_ha_states(cfg: Dict[str,Any]) -> List[Dict[str,Any]]:
    global _AREA_MAP
    
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
        print(f"[RAG] Failed to fetch HA states: {e}")
        return []
    
    if not isinstance(data,list): 
        return []

    # Fetch areas once
    if not _AREA_MAP:
        _AREA_MAP = _fetch_area_map(cfg)

    facts = []
    for item in data:
        try:
            eid = str(item.get("entity_id") or "")
            if not eid: 
                continue
            domain = eid.split(".",1)[0] if "." in eid else ""
            if INCLUDE_DOMAINS and (domain not in INCLUDE_DOMAINS):
                continue

            attrs = item.get("attributes") or {}
            device_class = str(attrs.get("device_class","")).lower()
            area_id = attrs.get("area_id","")
            area_name = _AREA_MAP.get(area_id,"") if area_id else ""
            name = str(attrs.get("friendly_name", eid))
            state = str(item.get("state",""))
            unit = str(attrs.get("unit_of_measurement","") or "")
            last_changed = str(item.get("last_changed","") or "")

            is_unknown = str(state).lower() in ("", "unknown", "unavailable", "none")
            
            # Normalize tracker/person zones
            if domain == "device_tracker" and not is_unknown:
                state = _safe_zone_from_tracker(state, attrs)

            # Displayable state
            show_state = state.upper() if state in ("on","off","open","closed") else state
            if unit and state not in ("on","off","open","closed"):
                try:
                    v = float(state)
                    if abs(v) < 0.005: v = 0.0
                    s = f"{v:.2f}".rstrip("0").rstrip(".")
                    show_state = f"{s} {unit}".strip()
                except Exception:
                    show_state = f"{state} {unit}".strip()

            # Build summary
            if domain == "person":
                zone = _safe_zone_from_tracker(state, attrs)
                summary = f"{name} is at {zone}"
            else:
                summary = name
                if area_name: 
                    summary = f"[{area_name}] " + summary
                if device_class: 
                    summary += f" ({device_class})"
                if show_state: 
                    summary += f": {show_state}"

            recent = last_changed.replace("T"," ").split(".")[0].replace("Z","") if last_changed else ""
            if domain in ("person","device_tracker","binary_sensor","sensor") and recent:
                summary += f" (as of {recent})"

            # Score baseline
            score = 1
            toks = _tok(eid) + _tok(name) + _tok(device_class)
            if any(k in toks for k in SOLAR_KEYWORDS): 
                score += 6
            if "solar_assistant" in "_".join(toks): 
                score += 3
            score += DEVICE_CLASS_PRIORITY.get(device_class,0)
            if domain in ("person","device_tracker"): 
                score += 5
            if eid.endswith(("_linkquality","_rssi","_lqi")): 
                score -= 2
            if is_unknown: 
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
                "source": "homeassistant"
            })
        except Exception as e:
            print(f"[RAG] Error processing HA entity {item.get('entity_id', 'unknown')}: {e}")
            continue
    
    return facts

# ----------------- Weather Data Fetching -----------------

def _fetch_weather_data(cfg: Dict[str,Any]) -> List[Dict[str,Any]]:
    """Fetch weather data from OpenWeatherMap free tier"""
    
    # Get API key and location from config
    weather_api_key = cfg.get("openweather_api_key", "")
    weather_location = cfg.get("weather_location", "Johannesburg,ZA")  # Default to user's location
    
    if not weather_api_key:
        print("[RAG] No OpenWeatherMap API key found in config")
        return []
    
    try:
        # Current weather API call
        base_url = "http://api.openweathermap.org/data/2.5/weather"
        params = {
            "q": weather_location,
            "appid": weather_api_key,
            "units": "metric"
        }
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        
        data = _http_get_json(url, {}, timeout=10)
        
        if not data or data.get("cod") != 200:
            print(f"[RAG] Weather API error: {data.get('message', 'Unknown error')}")
            return []
        
        # Extract weather info
        main = data.get("main", {})
        weather = data.get("weather", [{}])[0]
        wind = data.get("wind", {})
        
        temperature = main.get("temp")
        feels_like = main.get("feels_like")
        humidity = main.get("humidity")
        pressure = main.get("pressure")
        description = weather.get("description", "")
        wind_speed = wind.get("speed")
        wind_direction = wind.get("deg")
        
        # Build weather facts
        facts = []
        
        # Temperature fact
        if temperature is not None:
            temp_summary = f"Temperature: {temperature:.1f}°C"
            if feels_like is not None and abs(temperature - feels_like) > 2:
                temp_summary += f" (feels like {feels_like:.1f}°C)"
            
            facts.append({
                "entity_id": "weather.temperature",
                "domain": "weather",
                "device_class": "temperature",
                "friendly_name": "Current Temperature",
                "area": weather_location.split(",")[0],
                "state": f"{temperature:.1f}",
                "unit": "°C",
                "last_changed": datetime.now().isoformat(),
                "summary": temp_summary,
                "score": 5,
                "cats": ["weather", "weather.temperature"],
                "source": "openweather"
            })
        
        # Weather conditions
        if description:
            facts.append({
                "entity_id": "weather.conditions",
                "domain": "weather", 
                "device_class": "weather",
                "friendly_name": "Weather Conditions",
                "area": weather_location.split(",")[0],
                "state": description.title(),
                "unit": "",
                "last_changed": datetime.now().isoformat(),
                "summary": f"Weather: {description.title()}",
                "score": 4,
                "cats": ["weather", "weather.conditions"],
                "source": "openweather"
            })
        
        # Humidity
        if humidity is not None:
            facts.append({
                "entity_id": "weather.humidity",
                "domain": "weather",
                "device_class": "humidity", 
                "friendly_name": "Humidity",
                "area": weather_location.split(",")[0],
                "state": f"{humidity}",
                "unit": "%",
                "last_changed": datetime.now().isoformat(),
                "summary": f"Humidity: {humidity}%",
                "score": 3,
                "cats": ["weather", "weather.humidity"],
                "source": "openweather"
            })
        
        # Wind
        if wind_speed is not None:
            wind_summary = f"Wind: {wind_speed:.1f} m/s"
            if wind_direction is not None:
                # Convert degrees to cardinal direction
                directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
                idx = round(wind_direction / 22.5) % 16
                wind_summary += f" {directions[idx]}"
            
            facts.append({
                "entity_id": "weather.wind",
                "domain": "weather",
                "device_class": "wind_speed",
                "friendly_name": "Wind Speed", 
                "area": weather_location.split(",")[0],
                "state": f"{wind_speed:.1f}",
                "unit": "m/s",
                "last_changed": datetime.now().isoformat(),
                "summary": wind_summary,
                "score": 2,
                "cats": ["weather", "weather.wind"],
                "source": "openweather"
            })
        
        print(f"[RAG] Fetched {len(facts)} weather facts for {weather_location}")
        return facts
        
    except Exception as e:
        print(f"[RAG] Failed to fetch weather data: {e}")
        return []

# ----------------- General Knowledge Fetching -----------------

def _fetch_tmdb_data(api_key: str) -> List[Dict[str,Any]]:
    """Fetch recent movies and TV shows from TMDB"""
    facts = []
    
    try:
        # Recent popular movies (2023+)
        movies_url = f"https://api.themoviedb.org/3/discover/movie?api_key={api_key}&sort_by=popularity.desc&primary_release_date.gte={KNOWLEDGE_CUTOFF_YEAR}-01-01&page=1"
        movies_data = _http_get_json(movies_url, {}, timeout=15)
        
        for movie in movies_data.get("results", [])[:50]:  # Top 50 recent movies
            title = movie.get("title", "")
            release_date = movie.get("release_date", "")
            rating = movie.get("vote_average", 0)
            
            if not _is_recent_content(release_date):
                continue
                
            summary = f"Movie: {title}"
            if release_date:
                year = release_date.split("-")[0]
                summary += f" ({year})"
            if rating > 0:
                summary += f" - Rating: {rating:.1f}/10"
            
            facts.append({
                "entity_id": f"movie.{title.lower().replace(' ', '_')}",
                "domain": "entertainment",
                "device_class": "movie",
                "friendly_name": title,
                "area": "",
                "state": "released" if release_date <= datetime.now().strftime("%Y-%m-%d") else "upcoming",
                "unit": "",
                "last_changed": release_date,
                "summary": summary,
                "score": 3 + int(rating),
                "cats": ["entertainment", "entertainment.movies"],
                "source": "tmdb"
            })
        
        # Recent popular TV shows (2023+)
        tv_url = f"https://api.themoviedb.org/3/discover/tv?api_key={api_key}&sort_by=popularity.desc&first_air_date.gte={KNOWLEDGE_CUTOFF_YEAR}-01-01&page=1"
        tv_data = _http_get_json(tv_url, {}, timeout=15)
        
        for show in tv_data.get("results", [])[:50]:  # Top 50 recent shows
            name = show.get("name", "")
            first_air_date = show.get("first_air_date", "")
            rating = show.get("vote_average", 0)
            
            if not _is_recent_content(first_air_date):
                continue
                
            summary = f"TV Show: {name}"
            if first_air_date:
                year = first_air_date.split("-")[0]
                summary += f" ({year})"
            if rating > 0:
                summary += f" - Rating: {rating:.1f}/10"
            
            facts.append({
                "entity_id": f"tv.{name.lower().replace(' ', '_')}",
                "domain": "entertainment",
                "device_class": "tv_show",
                "friendly_name": name,
                "area": "", 
                "state": "airing",
                "unit": "",
                "last_changed": first_air_date,
                "summary": summary,
                "score": 3 + int(rating),
                "cats": ["entertainment", "entertainment.tv"],
                "source": "tmdb"
            })
        
        print(f"[RAG] Fetched {len(facts)} TMDB facts")
        return facts
        
    except Exception as e:
        print(f"[RAG] Failed to fetch TMDB data: {e}")
        return []

def _fetch_wikipedia_data() -> List[Dict[str,Any]]:
    """Fetch recent featured articles from Wikipedia"""
    facts = []
    
    try:
        # Get featured articles from recent dates
        current_date = datetime.now()
        
        for days_back in range(0, 30):  # Last 30 days
            check_date = datetime.fromtimestamp(current_date.timestamp() - (days_back * 24 * 60 * 60))
            date_str = check_date.strftime("%Y/%m/%d")
            
            try:
                url = f"https://en.wikipedia.org/api/rest_v1/feed/featured/{date_str}"
                data = _http_get_json(url, {"User-Agent": "RAG-Bot/1.0"}, timeout=10)
                
                if data and "tfa" in data:
                    article = data["tfa"]
                    title = article.get("title", "")
                    extract = article.get("extract", "")
                    
                    if title and extract:
                        summary = f"Wikipedia: {title} - {extract[:100]}..."
                        
                        facts.append({
                            "entity_id": f"wikipedia.{title.lower().replace(' ', '_')}",
                            "domain": "knowledge",
                            "device_class": "article",
                            "friendly_name": f"Wikipedia: {title}",
                            "area": "",
                            "state": "published",
                            "unit": "",
                            "last_changed": check_date.isoformat(),
                            "summary": summary,
                            "score": 2,
                            "cats": ["knowledge", "knowledge.wikipedia"],
                            "source": "wikipedia"
                        })
                        
                if len(facts) >= 20:  # Limit to 20 articles
                    break
                    
            except Exception:
                continue  # Skip failed dates
        
        print(f"[RAG] Fetched {len(facts)} Wikipedia facts")
        return facts
        
    except Exception as e:
        print(f"[RAG] Failed to fetch Wikipedia data: {e}")
        return []

def _fetch_general_knowledge(cfg: Dict[str,Any]) -> List[Dict[str,Any]]:
    """Fetch all general knowledge from various APIs"""
    facts = []
    
    # TMDB data (requires API key)
    tmdb_api_key = cfg.get("tmdb_api_key", "")
    if tmdb_api_key:
        facts.extend(_fetch_tmdb_data(tmdb_api_key))
    else:
        print("[RAG] No TMDB API key found in config")
    
    # Wikipedia data (no API key needed)
    facts.extend(_fetch_wikipedia_data())
    
    return facts

# ----------------- Cache Management Functions -----------------

def refresh_ha_cache() -> List[Dict[str,Any]]:
    """Refresh Home Assistant cache"""
    global _HA_LAST_REFRESH_TS, _HA_CACHE
    
    with _CACHE_LOCK:
        cfg = _load_options()
        facts = _fetch_ha_states(cfg)
        _HA_CACHE = facts

        result_paths = []
        try:
            payload = {
                "facts": facts,
                "timestamp": time.time(),
                "count": len(facts),
                "source": "homeassistant"
            }
            
            for d in PRIMARY_DIRS:
                try:
                    p = os.path.join(d, HA_BASENAME)
                    _write_json_atomic(p, payload)
                    result_paths.append(p)
                except Exception as e:
                    print(f"[RAG] HA write failed for {d}: {e}")
            
            try:
                _write_json_atomic(FALLBACK_HA_PATH, payload)
                result_paths.append(FALLBACK_HA_PATH)
            except Exception as e:
                print(f"[RAG] HA fallback write failed: {e}")
                
        finally:
            _HA_LAST_REFRESH_TS = time.time()

        print(f"[RAG] Wrote {len(facts)} HA facts to: " + " | ".join(result_paths))
        return facts

def refresh_weather_cache() -> List[Dict[str,Any]]:
    """Refresh weather cache"""
    global _WEATHER_LAST_REFRESH_TS, _WEATHER_CACHE
    
    with _CACHE_LOCK:
        cfg = _load_options()
        facts = _fetch_weather_data(cfg)
        _WEATHER_CACHE = facts

        result_paths = []
        try:
            payload = {
                "facts": facts,
                "timestamp": time.time(),
                "count": len(facts),
                "source": "weather"
            }
            
            for d in PRIMARY_DIRS:
                try:
                    p = os.path.join(d, WEATHER_BASENAME)
                    _write_json_atomic(p, payload)
                    result_paths.append(p)
                except Exception as e:
                    print(f"[RAG] Weather write failed for {d}: {e}")
            
            try:
                _write_json_atomic(FALLBACK_WEATHER_PATH, payload)
                result_paths.append(FALLBACK_WEATHER_PATH)
            except Exception as e:
                print(f"[RAG] Weather fallback write failed: {e}")
                
        finally:
            _WEATHER_LAST_REFRESH_TS = time.time()

        print(f"[RAG] Wrote {len(facts)} weather facts to: " + " | ".join(result_paths))
        return facts

def refresh_general_cache() -> List[Dict[str,Any]]:
    """Refresh general knowledge cache"""
    global _GENERAL_LAST_REFRESH_TS, _GENERAL_CACHE
    
    with _CACHE_LOCK:
        cfg = _load_options()
        facts = _fetch_general_knowledge(cfg)
        _GENERAL_CACHE = facts

        result_paths = []
        try:
            payload = {
                "facts": facts,
                "timestamp": time.time(),
                "count": len(facts),
                "source": "general_knowledge"
            }
            
            for d in PRIMARY_DIRS:
                try:
                    p = os.path.join(d, GENERAL_BASENAME)
                    _write_json_atomic(p, payload)
                    result_paths.append(p)
                except Exception as e:
                    print(f"[RAG] General knowledge write failed for {d}: {e}")
            
            try:
                _write_json_atomic(FALLBACK_GENERAL_PATH, payload)
                result_paths.append(FALLBACK_GENERAL_PATH)
            except Exception as e:
                print(f"[RAG] General knowledge fallback write failed: {e}")
                
        finally:
            _GENERAL_LAST_REFRESH_TS = time.time()

        print(f"[RAG] Wrote {len(facts)} general knowledge facts to: " + " | ".join(result_paths))
        return facts

def load_ha_cached() -> List[Dict[str,Any]]:
    """Load cached Home Assistant data"""
    global _HA_CACHE
    with _CACHE_LOCK:
        if _HA_CACHE: 
            return _HA_CACHE
        
        try:
            # Try primary locations first
            for d in PRIMARY_DIRS:
                p = os.path.join(d, HA_BASENAME)
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            return data
                        elif isinstance(data, dict) and "facts" in data:
                            return data["facts"]
            
            # Try fallback
            if os.path.exists(FALLBACK_HA_PATH):
                with open(FALLBACK_HA_PATH, "r", encoding="utf-8") as f: 
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "facts" in data:
                        return data["facts"]
        except Exception as e:
            print(f"[RAG] Error loading cached HA facts: {e}")
            
        return []

def load_weather_cached() -> List[Dict[str,Any]]:
    """Load cached weather data"""
    global _WEATHER_CACHE
    with _CACHE_LOCK:
        if _WEATHER_CACHE: 
            return _WEATHER_CACHE
        
        try:
            # Try primary locations first
            for d in PRIMARY_DIRS:
                p = os.path.join(d, WEATHER_BASENAME)
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            return data
                        elif isinstance(data, dict) and "facts" in data:
                            return data["facts"]
            
            # Try fallback
            if os.path.exists(FALLBACK_WEATHER_PATH):
                with open(FALLBACK_WEATHER_PATH, "r", encoding="utf-8") as f: 
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "facts" in data:
                        return data["facts"]
        except Exception as e:
            print(f"[RAG] Error loading cached weather facts: {e}")
            
        return []

def load_general_cached() -> List[Dict[str,Any]]:
    """Load cached general knowledge data"""
    global _GENERAL_CACHE
    with _CACHE_LOCK:
        if _GENERAL_CACHE: 
            return _GENERAL_CACHE
        
        try:
            # Try primary locations first
            for d in PRIMARY_DIRS:
                p = os.path.join(d, GENERAL_BASENAME)
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            return data
                        elif isinstance(data, dict) and "facts" in data:
                            return data["facts"]
            
            # Try fallback
            if os.path.exists(FALLBACK_GENERAL_PATH):
                with open(FALLBACK_GENERAL_PATH, "r", encoding="utf-8") as f: 
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "facts" in data:
                        return data["facts"]
        except Exception as e:
            print(f"[RAG] Error loading cached general knowledge facts: {e}")
            
        return []

def get_ha_facts(force_refresh: bool = False) -> List[Dict[str,Any]]:
    """Get Home Assistant facts with 5-minute refresh cycle"""
    with _CACHE_LOCK:
        if force_refresh or (time.time() - _HA_LAST_REFRESH_TS > HA_REFRESH_INTERVAL_SEC):
            return refresh_ha_cache()
        facts = load_ha_cached()
        if not facts:
            return refresh_ha_cache()
        return facts

def get_weather_facts(force_refresh: bool = False) -> List[Dict[str,Any]]:
    """Get weather facts with hourly refresh cycle"""
    with _CACHE_LOCK:
        if force_refresh or (time.time() - _WEATHER_LAST_REFRESH_TS > WEATHER_REFRESH_INTERVAL_SEC):
            return refresh_weather_cache()
        facts = load_weather_cached()
        if not facts:
            return refresh_weather_cache()
        return facts

def get_general_facts(force_refresh: bool = False) -> List[Dict[str,Any]]:
    """Get general knowledge facts with weekly refresh cycle"""
    with _CACHE_LOCK:
        if force_refresh or (time.time() - _GENERAL_LAST_REFRESH_TS > GENERAL_REFRESH_INTERVAL_SEC):
            return refresh_general_cache()
        facts = load_general_cached()
        if not facts:
            return refresh_general_cache()
        return facts

def get_all_facts(force_refresh: bool = False) -> List[Dict[str,Any]]:
    """Get all facts from all sources"""
    all_facts = []
    
    # Home Assistant facts (highest priority)
    all_facts.extend(get_ha_facts(force_refresh))
    
    # Weather facts (medium priority)
    all_facts.extend(get_weather_facts(force_refresh))
    
    # General knowledge facts (lowest priority)
    all_facts.extend(get_general_facts(force_refresh))
    
    return all_facts

# ----------------- Legacy compatibility function -----------------

def get_facts(force_refresh: bool = False) -> List[Dict[str,Any]]:
    """Legacy function - returns HA facts only for backward compatibility"""
    return get_ha_facts(force_refresh)

def refresh_and_cache() -> List[Dict[str,Any]]:
    """Legacy function - refreshes HA cache only for backward compatibility"""
    return refresh_ha_cache()

def load_cached() -> List[Dict[str,Any]]:
    """Legacy function - loads HA cache only for backward compatibility"""
    return load_ha_cached()

# ----------------- Enhanced Context Injection -----------------

def _intent_categories(q_tokens: Set[str]) -> Set[str]:
    """Determine intent categories from query tokens"""
    out: set[str] = set()
    for key, cats in INTENT_CATEGORY_MAP.items():
        if key in q_tokens:
            out.update(cats)
    
    # Energy related queries
    if q_tokens & {"solar","pv","inverter","ess","soc","battery"}:
        out.update({"energy","energy.storage","energy.pv","energy.inverter"})
    if "grid" in q_tokens:
        out.update({"energy.grid"})
    if "load" in q_tokens:
        out.update({"energy.load"})
    
    # Media queries
    if q_tokens & MEDIA_KEYWORDS:
        out.update({"media"})
    
    # Weather queries
    if q_tokens & WEATHER_KEYS:
        out.update({"weather"})
    
    # Entertainment queries
    if q_tokens & {"movie", "film", "cinema"}:
        out.update({"entertainment.movies"})
    if q_tokens & {"tv", "show", "series", "television"}:
        out.update({"entertainment.tv"})
    if q_tokens & {"actor", "actress", "star", "celebrity"}:
        out.update({"entertainment.actors"})
    
    return out

def inject_context(user_msg: str, top_k: int = DEFAULT_TOP_K) -> str:
    """Enhanced context injection from all sources"""
    q_raw = _tok(user_msg)
    q = set(_expand_query_tokens(q_raw))
    
    # Get facts from all sources
    all_facts = get_all_facts()
    
    # ---- Domain/keyword overrides ----
    filtered = []
    
    # Home Assistant specific filters
    if "light" in q or "lights" in q:
        filtered += [f for f in all_facts if f.get("domain") == "light"]
    if "switch" in q or "switches" in q:
        filtered += [f for f in all_facts if f.get("domain") == "switch" and not f.get("entity_id","").startswith("automation.")]
    if "motion" in q or "occupancy" in q:
        filtered += [f for f in all_facts if f.get("domain") == "binary_sensor" and f.get("device_class") == "motion"]
    if "axpert" in q:
        filtered += [f for f in all_facts if "axpert" in f.get("entity_id","").lower() or "axpert" in f.get("friendly_name","").lower()]
    if "sonoff" in q:
        filtered += [f for f in all_facts if "sonoff" in f.get("entity_id","").lower() or "sonoff" in f.get("friendly_name","").lower()]
    if "zigbee" in q or "z2m" in q:
        filtered += [f for f in all_facts if "zigbee" in f.get("entity_id","").lower() or "zigbee" in f.get("friendly_name","").lower()]
    if "where" in q:
        filtered += [f for f in all_facts if f.get("domain") in ("person","device_tracker")]
    
    # Weather specific filters
    if q & WEATHER_KEYS:
        filtered += [f for f in all_facts if f.get("source") == "openweather" or "weather" in f.get("cats", [])]
    
    # Entertainment specific filters
    if q & MEDIA_KEYWORDS:
        filtered += [f for f in all_facts if any(
            m in f.get("entity_id","").lower() or m in f.get("friendly_name","").lower()
            for m in MEDIA_KEYWORDS
        )]
    if q & {"movie", "film", "cinema"}:
        filtered += [f for f in all_facts if f.get("source") == "tmdb" and f.get("device_class") == "movie"]
    if q & {"tv", "show", "series", "television"}:
        filtered += [f for f in all_facts if f.get("source") == "tmdb" and f.get("device_class") == "tv_show"]
    if q & {"actor", "actress", "star", "celebrity"}:
        filtered += [f for f in all_facts if "entertainment.actors" in f.get("cats", [])]
    
    # Area queries
    for f in all_facts:
        if f.get("area") and f.get("area","").lower() in q:
            filtered.append(f)

    if filtered:
        facts = filtered
    else:
        facts = all_facts

    want_cats = _intent_categories(q)

    scored: List[Tuple[int, Dict[str, Any]]] = []
    for f in facts:
        s = int(f.get("score", 1))
        ft = set(_tok(f.get("summary", "")) + _tok(f.get("entity_id", "")))
        cats = set(f.get("cats", []))
        source = f.get("source", "")

        # Source priority scoring
        if source == "homeassistant":
            s += 10  # Highest priority for personal HA data
        elif source == "openweather":
            s += 5   # Medium priority for weather
        elif source in ("tmdb", "wikipedia"):
            s += 2   # Lower priority for general knowledge

        # Query matching
        if q and (q & ft): 
            s += 3
        if q & SOLAR_KEYWORDS: 
            s += 2
        if {"state_of_charge","battery_state_of_charge","battery_soc","soc"} & ft:
            s += 12
        
        # Category matching
        if want_cats and (cats & want_cats):
            s += 15
        if want_cats & {"energy.storage"} and "energy.storage" in cats:
            s += 20
        
        # Weather query boost
        if (q & WEATHER_KEYS) and source == "openweather":
            s += 10
        
        # Entertainment query boost
        if (q & {"movie", "film", "cinema"}) and "entertainment.movies" in cats:
            s += 8
        if (q & {"tv", "show", "series"}) and "entertainment.tv" in cats:
            s += 8

        # Penalties
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

    # Prioritize energy storage facts for SOC queries
    if ("soc" in q) or (want_cats & {"energy.storage"}):
        ess_first = [f for f in candidate_facts if "energy.storage" in set(f.get("cats", []))]
        others = [f for f in candidate_facts if "energy.storage" not in set(f.get("cats", []))]
        ordered = ess_first + others
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

def search_entities(query: str, limit: int = 10, include_all_sources: bool = True) -> List[Dict[str, Any]]:
    """Search entities across all sources or just HA"""
    if include_all_sources:
        facts = get_all_facts()
    else:
        facts = get_ha_facts()
    
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
        
        # Source priority
        source = entity.get("source", "")
        if source == "homeassistant":
            score += 5
        elif source == "openweather":
            score += 3
        elif source in ("tmdb", "wikipedia"):
            score += 1
        
        if score > 0:
            scored.append((score, entity))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return [entity for _, entity in scored[:limit]]

def get_stats() -> Dict[str, Any]:
    """Get statistics about all RAG systems"""
    ha_facts = get_ha_facts()
    weather_facts = get_weather_facts()
    general_facts = get_general_facts()
    
    # Count by domain for HA
    ha_domain_counts = {}
    for entity in ha_facts:
        domain = entity.get("domain", "unknown")
        ha_domain_counts[domain] = ha_domain_counts.get(domain, 0) + 1
    
    # Count by source for general knowledge
    general_source_counts = {}
    for entity in general_facts:
        source = entity.get("source", "unknown")
        general_source_counts[source] = general_source_counts.get(source, 0) + 1
    
    return {
        "homeassistant": {
            "total_facts": len(ha_facts),
            "domains": ha_domain_counts,
            "areas": len(_AREA_MAP),
            "last_refresh": _HA_LAST_REFRESH_TS,
            "cache_size": len(_HA_CACHE),
            "refresh_interval": HA_REFRESH_INTERVAL_SEC
        },
        "weather": {
            "total_facts": len(weather_facts),
            "last_refresh": _WEATHER_LAST_REFRESH_TS,
            "cache_size": len(_WEATHER_CACHE),
            "refresh_interval": WEATHER_REFRESH_INTERVAL_SEC
        },
        "general_knowledge": {
            "total_facts": len(general_facts),
            "sources": general_source_counts,
            "last_refresh": _GENERAL_LAST_REFRESH_TS,
            "cache_size": len(_GENERAL_CACHE),
            "refresh_interval": GENERAL_REFRESH_INTERVAL_SEC
        },
        "total_facts": len(ha_facts) + len(weather_facts) + len(general_facts)
    }

# ----------------- Main CLI -----------------

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "refresh":
            source = sys.argv[2].lower() if len(sys.argv) > 2 else "all"
            
            if source == "ha" or source == "homeassistant":
                print("Refreshing Home Assistant facts...")
                facts = refresh_ha_cache()
                print(f"Refreshed {len(facts)} HA facts.")
                
            elif source == "weather":
                print("Refreshing weather facts...")
                facts = refresh_weather_cache()
                print(f"Refreshed {len(facts)} weather facts.")
                
            elif source == "general":
                print("Refreshing general knowledge facts...")
                facts = refresh_general_cache()
                print(f"Refreshed {len(facts)} general knowledge facts.")
                
            else:  # "all" or default
                print("Refreshing all RAG facts...")
                ha_facts = refresh_ha_cache()
                weather_facts = refresh_weather_cache()
                general_facts = refresh_general_cache()
                total = len(ha_facts) + len(weather_facts) + len(general_facts)
                print(f"Refreshed {total} total facts ({len(ha_facts)} HA, {len(weather_facts)} weather, {len(general_facts)} general).")
            
        elif command == "stats":
            stats = get_stats()
            print(json.dumps(stats, indent=2))
            
        elif command == "search" and len(sys.argv) > 2:
            query = " ".join(sys.argv[2:])
            include_all = "--all" in sys.argv or "-a" in sys.argv
            results = search_entities(query, 10, include_all)
            source_filter = " (all sources)" if include_all else " (HA only)"
            print(f"Found {len(results)} entities for '{query}'{source_filter}:")
            for r in results:
                source = r.get('source', 'unknown')
                print(f"  [{source}] {r.get('summary', r.get('entity_id', 'unknown'))}")
                
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
            
            print("\nTesting Home Assistant connection...")
            ha_facts = get_ha_facts(force_refresh=True)
            print(f"HA: {len(ha_facts)} facts")
            
            print("\nTesting weather connection...")
            weather_facts = get_weather_facts(force_refresh=True)
            print(f"Weather: {len(weather_facts)} facts")
            
            print("\nTesting general knowledge...")
            general_facts = get_general_facts(force_refresh=True)
            print(f"General: {len(general_facts)} facts")
            
            total = len(ha_facts) + len(weather_facts) + len(general_facts)
            print(f"\nTotal: {total} facts across all sources")
            
        else:
            print("Usage: python rag.py [command] [options]")
            print("Commands:")
            print("  refresh [ha|weather|general|all] - Refresh specific or all caches")
            print("  stats                            - Show system statistics")
            print("  search <query> [--all]           - Search entities (--all includes all sources)")
            print("  context <query>                  - Show context for query")
            print("  test                             - Test all connections")
    else:
        print("Enhanced RAG system - refreshing all sources...")
        ha_facts = refresh_ha_cache()
        weather_facts = refresh_weather_cache()
        general_facts = refresh_general_cache()
        total = len(ha_facts) + len(weather_facts) + len(general_facts)
        print(f"Wrote {total} total facts ({len(ha_facts)} HA, {len(weather_facts)} weather, {len(general_facts)} general).")
