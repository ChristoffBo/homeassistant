#!/usr/bin/env python3
# /app/rag.py  (REST → /api/states + /api/areas + Wikipedia)
#
# - Reads HA URL + token from /data/options.json (/data/config.json fallback)
# - Pulls states via /api/states (read-only) + area metadata via /api/areas
# - Summarizes/boosts entities and auto-categorizes them (no per-entity config)
# - Writes primary JSON to /share/jarvis_prime/memory/rag_facts.json
#   and also mirrors to /data/rag_facts.json as a fallback
# - inject_context(user_msg, top_k) returns a small, relevant context block
# - Adds Wikipedia REST API as fallback for general queries
#
# Safe: read-only, never calls HA /api/services

import os, re, json, time, threading, urllib.request, urllib.parse
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

def _http_get_json(url: str, headers: Dict[str,str]=None, timeout: int=20):
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
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

# ----------------- Wikipedia fetch -----------------

def _fetch_wiki_summary(query: str) -> str:
    try:
        title = urllib.parse.quote(query.strip())
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
        data = _http_get_json(url, timeout=10)
        if isinstance(data, dict):
            summary = data.get("extract") or ""
            if summary:
                return f"Wikipedia: {summary}"
        return ""
    except Exception:
        return ""

# ----------------- categorization -----------------

# (unchanged _infer_categories function here)

# ----------------- fetch areas, states, cache -----------------

# (unchanged functions for HA fetch and cache here)

# ----------------- query → context -----------------

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

    # scoring (unchanged scoring logic here)

    if facts:
        # build HA-based context (same as before)
        # (unchanged scoring and budget logic here)
        pass
    else:
        # fallback to Wikipedia if no HA facts match
        return _fetch_wiki_summary(user_msg)

# ----------------- main -----------------

if __name__ == "__main__":
    print("Refreshing RAG facts from Home Assistant...")
    facts = refresh_and_cache()
    print(f"Wrote {len(facts)} facts.")