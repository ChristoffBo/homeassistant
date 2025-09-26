#!/usr/bin/env python3
# /app/rag.py  (REST → /api/states + /api/areas + curated knowledge)
#
# - Reads HA URL + token from /data/options.json (/data/config.json fallback)
# - Pulls states via /api/states (read-only) + area metadata via /api/areas
# - Summarizes/boosts entities and auto-categorizes them (no per-entity config)
# - Also fetches curated external knowledge (movies, actors, series, cars, tech, OPNSense, Docker)
# - Writes combined JSON to /share/jarvis_prime/memory/rag_facts.json
#   and also mirrors to /data/rag_facts.json as a fallback
# - inject_context(user_msg, top_k) returns a small, relevant context block
#
# Safe: read-only, never calls HA /api/services

import os, re, json, time, threading, urllib.request
from typing import Any, Dict, List, Tuple, Set
import datetime

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

# ----------------- Curated external sources -----------------

CURATED_URLS = {
    "movies": "https://raw.githubusercontent.com/prust/wikipedia-movie-data/master/movies.json",
    "actors": "https://raw.githubusercontent.com/prust/wikipedia-movie-data/master/movies.json",
    "series": "https://raw.githubusercontent.com/awesomedata/awesome-tv-series/master/tvseries.json",
    "cars":   "https://raw.githubusercontent.com/vega/vega-datasets/master/data/cars.json",
    "tech":   "https://raw.githubusercontent.com/EbookFoundation/free-programming-books/main/books/free-programming-books-subjects.md",
    "opnsense": "https://raw.githubusercontent.com/opnsense/docs/master/source/releases.rst",
    "docker":   "https://raw.githubusercontent.com/docker-library/docs/master/README.md"
}

CURATED_PATH = "/share/jarvis_prime/memory/curated_facts.json"
CURATED_REFRESH_INTERVAL_DAYS = 30
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

# ----------------- curated fetcher -----------------

def _http_get_text(url: str, timeout: int=20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-RAG"}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8","replace")

def refresh_curated() -> List[Dict[str,Any]]:
    now = datetime.datetime.utcnow()
    if os.path.exists(CURATED_PATH):
        try:
            ts = os.path.getmtime(CURATED_PATH)
            age_days = (time.time() - ts) / 86400
            if age_days < CURATED_REFRESH_INTERVAL_DAYS:
                with open(CURATED_PATH,"r",encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass

    curated: List[Dict[str,Any]] = []
    for key, url in CURATED_URLS.items():
        try:
            txt = _http_get_text(url, timeout=15)
            if txt:
                if url.endswith(".json"):
                    try:
                        data = json.loads(txt)
                        if isinstance(data, list):
                            for item in data[:200]:
                                curated.append({
                                    "summary": f"{key.title()} :: {str(item)[:200]}",
                                    "cats": [key],
                                    "score": 1
                                })
                        elif isinstance(data, dict):
                            curated.append({
                                "summary": f"{key.title()} :: {list(data.keys())[:20]}",
                                "cats": [key],
                                "score": 1
                            })
                    except Exception:
                        pass
                else:
                    # treat as plain text
                    curated.append({
                        "summary": f"{key.title()} :: {txt[:200]}",
                        "cats": [key],
                        "score": 1
                    })
        except Exception as e:
            print(f"[RAG] curated fetch failed for {key}: {e}")

    try:
        _write_json_atomic(CURATED_PATH, curated)
    except Exception as e:
        print("[RAG] curated write failed:", e)

    print(f"[RAG] refreshed curated: {len(curated)} items")
    return curated

def load_curated() -> List[Dict[str,Any]]:
    try:
        if os.path.exists(CURATED_PATH):
            with open(CURATED_PATH,"r",encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return []
    return []
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

# ----------------- curated fetcher -----------------

def _http_get_text(url: str, timeout: int=20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-RAG"}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8","replace")

def refresh_curated() -> List[Dict[str,Any]]:
    now = datetime.datetime.utcnow()
    if os.path.exists(CURATED_PATH):
        try:
            ts = os.path.getmtime(CURATED_PATH)
            age_days = (time.time() - ts) / 86400
            if age_days < CURATED_REFRESH_INTERVAL_DAYS:
                with open(CURATED_PATH,"r",encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass

    curated: List[Dict[str,Any]] = []
    for key, url in CURATED_URLS.items():
        try:
            txt = _http_get_text(url, timeout=15)
            if txt:
                if url.endswith(".json"):
                    try:
                        data = json.loads(txt)
                        if isinstance(data, list):
                            for item in data[:200]:
                                curated.append({
                                    "summary": f"{key.title()} :: {str(item)[:200]}",
                                    "cats": [key],
                                    "score": 1
                                })
                        elif isinstance(data, dict):
                            curated.append({
                                "summary": f"{key.title()} :: {list(data.keys())[:20]}",
                                "cats": [key],
                                "score": 1
                            })
                    except Exception:
                        pass
                else:
                    # treat as plain text
                    curated.append({
                        "summary": f"{key.title()} :: {txt[:200]}",
                        "cats": [key],
                        "score": 1
                    })
        except Exception as e:
            print(f"[RAG] curated fetch failed for {key}: {e}")

    try:
        _write_json_atomic(CURATED_PATH, curated)
    except Exception as e:
        print("[RAG] curated write failed:", e)

    print(f"[RAG] refreshed curated: {len(curated)} items")
    return curated

def load_curated() -> List[Dict[str,Any]]:
    try:
        if os.path.exists(CURATED_PATH):
            with open(CURATED_PATH,"r",encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return []
    return []
# ----------------- IO + cache -----------------

def refresh_and_cache() -> List[Dict[str,Any]]:
    global _LAST_REFRESH_TS, _MEM_CACHE
    cfg = _load_options()
    facts = _fetch_ha_states(cfg)
    _MEM_CACHE = facts

    result_paths=[]
    try:
        payload = facts
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
    if _MEM_CACHE: return _MEM_CACHE
    try:
        for d in PRIMARY_DIRS:
            p=os.path.join(d,BASENAME)
            if os.path.exists(p):
                with open(p,"r",encoding="utf-8") as f:
                    return json.load(f)
        with open(FALLBACK_PATH,"r",encoding="utf-8") as f: 
            return json.load(f)
    except Exception:
        return []
    return []

def get_facts(force_refresh: bool=False) -> List[Dict[str,Any]]:
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
        filtered += [f for f in facts if f["domain"] == "light"]
    if "switch" in q or "switches" in q:
        filtered += [f for f in facts if f["domain"] == "switch" and not f["entity_id"].startswith("automation.")]
    if "motion" in q or "occupancy" in q:
        filtered += [f for f in facts if f["domain"] == "binary_sensor" and f["device_class"] == "motion"]
    if "axpert" in q:
        filtered += [f for f in facts if "axpert" in f["entity_id"].lower() or "axpert" in f["friendly_name"].lower()]
    if "sonoff" in q:
        filtered += [f for f in facts if "sonoff" in f["entity_id"].lower() or "sonoff" in f["friendly_name"].lower()]
    if "zigbee" in q or "z2m" in q:
        filtered += [f for f in facts if "zigbee" in f["entity_id"].lower() or "zigbee" in f["friendly_name"].lower()]
    if "where" in q:
        filtered += [f for f in facts if f["domain"] in ("person","device_tracker")]
    if q & MEDIA_KEYWORDS:
        filtered += [f for f in facts if any(
            m in f["entity_id"].lower() or m in f["friendly_name"].lower()
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

    return "\n".join(selected)
# ----------------- main -----------------

if __name__ == "__main__":
    print("Refreshing RAG facts from Home Assistant...")
    try:
        facts = refresh_and_cache()
        print(f"Wrote {len(facts)} HA facts.")
    except Exception as e:
        print(f"[RAG] HA refresh failed: {e}")

    # Refresh curated knowledge monthly
    try:
        curated = load_curated_facts(force_refresh=False)
        print(f"[RAG] Curated knowledge available: {len(curated)} entries")
    except Exception as e:
        print(f"[RAG] Curated knowledge refresh failed: {e}")