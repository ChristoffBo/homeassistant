#!/usr/bin/env python3
# /app/rag.py  (REST → /api/states + /api/areas + Free Knowledge APIs)
#
# - Reads HA URL + token from /data/options.json (/data/config.json fallback)
#   (keys supported: ha_url/ha_token OR llm_enviroguard_ha_base_url/llm_enviroguard_ha_token)
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

FREE_APIS = {
    # TVMaze is free & public — shows and episodes
    "shows": "https://api.tvmaze.com/shows?page=1",
    "schedule": "https://api.tvmaze.com/schedule",
    # Jokes
    "joke": "https://v2.jokeapi.dev/joke/Programming?type=single",
    # Cars
    "cars": "https://vpic.nhtsa.dot.gov/api/vehicles/GetMakesForVehicleType/car?format=json",
    # Space
    "space": "http://api.open-notify.org/astros.json",
    # Tech news
    "tech_news": "https://hn.algolia.com/api/v1/search_by_date?tags=story&hitsPerPage=5",
    # World time
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
TV_KEYWORDS_MEDIA= {"tv","androidtv","chromecast","google_tv"}
RADARR_KEYWORDS  = {"radarr"}
SONARR_KEYWORDS  = {"sonarr"}
LIDARR_KEYWORDS  = {"lidarr"}
BAZARR_KEYWORDS  = {"bazarr"}
READARR_KEYWORDS = {"readarr"}
SONOS_KEYWORDS   = {"sonos"}
AMP_KEYWORDS     = {"denon","onkyo","yamaha","marantz"}

MEDIA_KEYWORDS   = set().union(
    PLEX_KEYWORDS, EMBY_KEYWORDS, JELLYFIN_KEYWORDS, KODI_KEYWORDS, TV_KEYWORDS_MEDIA,
    RADARR_KEYWORDS, SONARR_KEYWORDS, LIDARR_KEYWORDS, BAZARR_KEYWORDS, READARR_KEYWORDS,
    SONOS_KEYWORDS, AMP_KEYWORDS, {"media","player"}
)

# Entertainment keywords
MOVIE_KEYWORDS   = {"movie","film","cinema","blockbuster"}
TV_KEYWORDS_ENT  = {"tv","series","show","netflix","hbo","disney","amazon"}
ACTOR_KEYWORDS   = {"actor","actress","celebrity","star","director","producer"}
GENRE_KEYWORDS   = {"action","comedy","drama","horror","sci-fi","romance","thriller"}
ENTERTAINMENT_KEYWORDS = set().union(MOVIE_KEYWORDS,TV_KEYWORDS_ENT,ACTOR_KEYWORDS,GENRE_KEYWORDS)

# Knowledge domains
AUTOMOTIVE_KEYWORDS = {"car","vehicle","ford","toyota","honda","tesla","bmw","mercedes","audi"}
TECH_KEYWORDS       = {"tech","technology","computer","software","hardware","programming","ai","coding"}
NEWS_KEYWORDS       = {"news","headlines","current","events","world","politics"}
WEATHER_KEYWORDS    = {"weather","temperature","forecast","rain","sunny","cloudy"}
SPACE_KEYWORDS      = {"space","astronaut","nasa","orbit","iss","rocket"}
JOKE_KEYWORDS       = {"joke","funny","humor","laugh","comedy"}

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
    "movie": ["movie","film","cinema","flick"],
    "tv": ["tv","television","series","show"],
    "actor": ["actor","actress","celebrity","star"],
    "car": ["car","vehicle","auto","automobile","ride"],
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

def _get_ha_creds(cfg: Dict[str, Any]) -> Tuple[str,str]:
    """Supports both ha_url/ha_token and llm_enviroguard_ha_base_url/llm_enviroguard_ha_token"""
    ha_url   = (cfg.get("llm_enviroguard_ha_base_url") or cfg.get("ha_url") or "").rstrip("/")
    ha_token = (cfg.get("llm_enviroguard_ha_token") or cfg.get("ha_token") or "")
    return ha_url, ha_token

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
    """Fetch shows and episodes from TVMaze"""
    facts = []
    try:
        resp = requests.get(FREE_APIS["shows"], timeout=15)
        if resp.status_code == 200:
            shows = resp.json()
            for show in shows[:5]:
                facts.append({
                    "type": "knowledge",
                    "category": "entertainment",
                    "entity_id": f"tvmaze.show.{show.get('id')}",
                    "domain": "knowledge",
                    "friendly_name": show.get("name",""),
                    "title": show.get("name",""),
                    "summary": f"TV Show: {show.get('name','')} ({show.get('premiered','')[:4]}) - {show.get('genres')}",
                    "score": 8,
                    "cats": ["entertainment","entertainment.tv"],
                    "last_updated": datetime.now().isoformat()
                })
    except Exception as e:
        print(f"TVMaze shows error: {e}")

    try:
        resp = requests.get(FREE_APIS["schedule"], timeout=15)
        if resp.status_code == 200:
            eps = resp.json()
            for ep in eps[:5]:
                show = ep.get("show",{}).get("name","")
                facts.append({
                    "type": "knowledge",
                    "category": "entertainment",
                    "entity_id": f"tvmaze.episode.{ep.get('id')}",
                    "domain": "knowledge",
                    "friendly_name": ep.get("name",""),
                    "title": ep.get("name",""),
                    "summary": f"Episode: {ep.get('name','')} from {show} (Season {ep.get('season')} Ep {ep.get('number')})",
                    "score": 7,
                    "cats": ["entertainment","entertainment.tv"],
                    "last_updated": datetime.now().isoformat()
                })
    except Exception as e:
        print(f"TVMaze schedule error: {e}")
    return facts

def _fetch_other_knowledge_facts() -> List[Dict[str, Any]]:
    facts = []
    # Cars
    try:
        resp = requests.get(FREE_APIS["cars"], timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for make in data.get("Results",[])[:8]:
                facts.append({
                    "type":"knowledge",
                    "category":"automotive",
                    "entity_id":f"car.{make.get('MakeId')}",
                    "domain":"knowledge",
                    "friendly_name":make.get("MakeName",""),
                    "title":make.get("MakeName",""),
                    "summary":f"Car brand: {make.get('MakeName','')}",
                    "score":5,
                    "cats":["automotive","cars"],
                    "last_updated":datetime.now().isoformat()
                })
    except Exception as e:
        print(f"Car API error: {e}")

    # Space
    try:
        resp = requests.get(FREE_APIS["space"], timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            people = ", ".join([p["name"] for p in data.get("people",[])])
            facts.append({
                "type":"knowledge",
                "category":"space",
                "entity_id":"space.astronauts",
                "domain":"knowledge",
                "friendly_name":"People in Space",
                "title":"People in Space",
                "summary":f"There are {data.get('number',0)} people in space: {people}",
                "score":6,
                "cats":["space","science"],
                "last_updated":datetime.now().isoformat()
            })
    except Exception as e:
        print(f"Space API error: {e}")

    # Tech news
    try:
        resp = requests.get(FREE_APIS["tech_news"], timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for hit in data.get("hits",[])[:3]:
                facts.append({
                    "type":"knowledge",
                    "category":"technology",
                    "entity_id":f"tech.{hit.get('objectID')}",
                    "domain":"knowledge",
                    "friendly_name":hit.get("title",""),
                    "title":hit.get("title",""),
                    "summary":f"Tech News: {hit.get('title','')} - Points: {hit.get('points',0)}",
                    "score":6,
                    "cats":["technology","news"],
                    "last_updated":datetime.now().isoformat()
                })
    except Exception as e:
        print(f"Tech news API error: {e}")

    # Joke
    try:
        resp = requests.get(FREE_APIS["joke"], timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            joke = data.get("joke","")
            if joke:
                facts.append({
                    "type":"knowledge",
                    "category":"humor",
                    "entity_id":"joke.1",
                    "domain":"knowledge",
                    "friendly_name":"Programming Joke",
                    "title":"Programming Joke",
                    "summary":joke,
                    "score":4,
                    "cats":["humor"],
                    "last_updated":datetime.now().isoformat()
                })
    except Exception as e:
        print(f"Joke API error: {e}")

    return facts

def _fetch_external_facts() -> List[Dict[str, Any]]:
    facts = []
    facts.extend(_fetch_entertainment_facts())
    facts.extend(_fetch_other_knowledge_facts())
    return facts
# ----------------- Home Assistant Integration -----------------

def _fetch_ha_areas() -> Dict[str, str]:
    cfg = _load_options()
    ha_url, ha_token = _get_ha_creds(cfg)
    if not ha_url or not ha_token:
        print("Warning: No HA URL/token configured")
        return {}
    try:
        url = f"{ha_url}/api/areas"
        headers = {"Authorization": f"Bearer {ha_token}"}
        data = _http_get_json(url, headers)
        return {area["area_id"]: area["name"] for area in data}
    except Exception as e:
        print(f"Error fetching areas: {e}")
        return {}

def _fetch_ha_states() -> List[Dict[str, Any]]:
    cfg = _load_options()
    ha_url, ha_token = _get_ha_creds(cfg)
    if not ha_url or not ha_token:
        print("Warning: No HA URL/token configured")
        return []
    try:
        url = f"{ha_url}/api/states"
        headers = {"Authorization": f"Bearer {ha_token}"}
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
        if toks & TV_KEYWORDS_MEDIA: cats.add("media.tv")
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
    parts = [name or eid]
    if area:
        parts.append(f"(in {area})")
    if state and state not in ("unavailable", "unknown"):
        if domain in ("person","device_tracker"):
            zone = _safe_zone_from_tracker(state, attrs)
            parts.append(f"is at {zone}")
        elif device_class == "battery":
            parts.append(f"battery at {state}%")
        elif domain in ("light","switch","fan"):
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
    score = 1
    domain_scores = {
        "person": 8, "device_tracker": 8, "light": 6, "switch": 6, "sensor": 5,
        "binary_sensor": 4, "climate": 7, "media_player": 6, "automation": 3
    }
    score += domain_scores.get(domain, 1)
    if device_class:
        score += DEVICE_CLASS_PRIORITY.get(device_class, 0)
    if "energy" in cats: score += 3
    if "energy.storage" in cats: score += 5
    if "media" in cats: score += 2
    if "person" in cats: score += 4
    name_lower = (name or "").lower()
    if "main" in name_lower or "primary" in name_lower: score += 2
    if "hidden" in name_lower or "helper" in name_lower: score -= 2
    return max(1, score)
# ----------------- Refresh + Cache -----------------

def _collect_facts() -> List[Dict[str, Any]]:
    raw_states = _fetch_ha_states()
    if not raw_states:
        return []

    areas = _fetch_ha_areas()
    facts: List[Dict[str, Any]] = []
    for st in raw_states:
        try:
            eid = st.get("entity_id", "")
            domain = eid.split(".")[0] if "." in eid else ""
            attrs = st.get("attributes", {})
            name = attrs.get("friendly_name", eid)
            state = st.get("state", "")
            device_class = attrs.get("device_class", "")
            area = areas.get(attrs.get("area_id", ""), "")

            cats = _infer_categories(eid, name, attrs, domain, device_class)
            summary = _build_summary(eid, name, state, attrs, domain, device_class, area)
            score = _calculate_score(eid, name, attrs, domain, device_class, cats)

            facts.append({
                "entity_id": eid,
                "domain": domain,
                "device_class": device_class,
                "friendly_name": name,
                "state": state,
                "area": area,
                "summary": summary,
                "cats": sorted(cats),
                "score": score
            })
        except Exception:
            continue
    return facts

def refresh_and_cache() -> List[Dict[str, Any]]:
    global _MEM_CACHE, _LAST_REFRESH_TS
    facts = _collect_facts()
    _MEM_CACHE = facts
    _LAST_REFRESH_TS = time.time()

    result_paths = []
    try:
        for d in PRIMARY_DIRS:
            path = os.path.join(d, BASENAME)
            _write_json_atomic(path, facts)
            result_paths.append(path)
        _write_json_atomic(FALLBACK_PATH, facts)
        result_paths.append(FALLBACK_PATH)
    except Exception as e:
        print(f"[RAG] cache write failed: {e}")

    print(f"[RAG] wrote {len(facts)} facts → {', '.join(result_paths)}")
    return facts

def load_cached() -> List[Dict[str, Any]]:
    if _MEM_CACHE:
        return _MEM_CACHE
    try:
        for d in PRIMARY_DIRS:
            path = os.path.join(d, BASENAME)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        if os.path.exists(FALLBACK_PATH):
            with open(FALLBACK_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return []
    return []

def get_facts(force_refresh: bool=False) -> List[Dict[str, Any]]:
    if force_refresh or (time.time() - _LAST_REFRESH_TS > REFRESH_INTERVAL_SEC):
        return refresh_and_cache()
    facts = load_cached()
    if not facts:
        return refresh_and_cache()
    return facts

# ----------------- Query Handling -----------------

def inject_context(user_msg: str, top_k: int=DEFAULT_TOP_K) -> str:
    q_raw = _tok(user_msg)
    q = set(_expand_query_tokens(q_raw))
    facts = get_facts()

    # Direct keyword filters
    filtered = []
    if "light" in q: filtered += [f for f in facts if f["domain"] == "light"]
    if "switch" in q: filtered += [f for f in facts if f["domain"] == "switch"]
    if "motion" in q: filtered += [f for f in facts if f["device_class"] == "motion"]
    if "where" in q: filtered += [f for f in facts if f["domain"] in ("person", "device_tracker")]
    if q & MEDIA_KEYWORDS:
        filtered += [f for f in facts if "media" in f["cats"]]

    if filtered:
        facts = filtered

    scored: List[Tuple[int, Dict[str, Any]]] = []
    for f in facts:
        s = int(f.get("score", 1))
        toks = set(_tok(f.get("summary", "")))
        if q & toks: s += 3
        if q & SOLAR_KEYWORDS: s += 2
        if {"soc", "battery"} & toks: s += 5
        scored.append((s, f))

    scored.sort(key=lambda x: x[0], reverse=True)
    candidate_facts = [f for _, f in (scored[:top_k] if top_k else scored)]

    ctx_tokens = _ctx_tokens_from_options()
    budget = _rag_budget_tokens(ctx_tokens)

    selected: List[str] = []
    remaining = budget
    for f in candidate_facts:
        line = f.get("summary", "")
        if not line: continue
        cost = _estimate_tokens(line)
        if cost <= remaining:
            selected.append(line)
            remaining -= cost
        if remaining <= 0:
            break

    return "\n".join(selected)

# ----------------- Background Refresh -----------------

def _background_refresher():
    while True:
        try:
            refresh_and_cache()
        except Exception as e:
            print(f"[RAG] background refresh failed: {e}")
        time.sleep(300)  # refresh every 5 minutes

# ----------------- Entrypoint -----------------

if __name__ == "__main__":
    print("Refreshing RAG facts from Home Assistant (initial)...")
    refresh_and_cache()
    print("Starting background refresher thread (every 5m)...")
    t = threading.Thread(target=_background_refresher, daemon=True)
    t.start()
    while True:
        time.sleep(3600)  # keep alive