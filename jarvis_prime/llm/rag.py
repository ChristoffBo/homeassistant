#!/usr/bin/env python3
# /app/rag.py  (REST → /api/states + /api/areas + curated knowledge APIs)
#
# - Reads HA URL + token from /data/options.json (/data/config.json fallback)
# - Pulls states via /api/states (read-only) + area metadata via /api/areas
# - Summarizes/boosts entities and auto-categorizes them
# - Fetches curated external facts (Movies, Actors, Series, Cars, Tech/OPNSense/Docker)
# - Writes JSON to /share/jarvis_prime/memory/rag_facts.json
#   and curated JSONL to /share/jarvis_prime/memory/knowledge_2025.jsonl
# - inject_context(user_msg, top_k) merges HA + curated facts
#
# Safe: read-only, never calls HA /api/services. External APIs optional.

import os, re, json, time, threading, urllib.request, urllib.parse
from typing import Any, Dict, List, Tuple, Set

OPTIONS_PATHS = ["/data/options.json", "/data/config.json"]

# Paths
PRIMARY_DIRS   = ["/share/jarvis_prime/memory"]
FALLBACK_PATH  = "/data/rag_facts.json"
BASENAME       = "rag_facts.json"
CURATED_FILE   = "/share/jarvis_prime/memory/knowledge_2025.jsonl"

# Cutoff
MAX_CURATED_SIZE = 500 * 1024 * 1024  # 500 MB
CURATED_REFRESH_DAYS = 30

# ----------------- Helpers -----------------

def _http_get_json(url: str, headers: Dict[str,str]=None, timeout: int=20):
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8","replace"))

def _write_text_atomic(path: str, text: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        f.write(text); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

def _write_json_atomic(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(obj,f,indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

def _file_too_old(path: str, days: int) -> bool:
    if not os.path.exists(path): return True
    age = time.time() - os.path.getmtime(path)
    return age > days * 86400
# ----------------- Curated Knowledge Fetchers -----------------

def fetch_movies_series() -> List[Dict[str,Any]]:
    """Fetch some popular movies/series/actors from OMDb API"""
    api_key = os.environ.get("OMDB_API_KEY","")  # must set manually
    if not api_key:
        return []
    titles = ["Dune: Part Two", "Oppenheimer", "John Wick", "Breaking Bad", "Stranger Things"]
    out=[]
    for t in titles:
        try:
            url = f"http://www.omdbapi.com/?t={urllib.parse.quote(t)}&apikey={api_key}"
            data = _http_get_json(url, timeout=15)
            if data.get("Title"):
                out.append({
                    "category":"movie/series",
                    "title": data.get("Title"),
                    "year": data.get("Year"),
                    "actors": data.get("Actors"),
                    "plot": data.get("Plot"),
                    "score": 5
                })
        except Exception as e:
            print(f"[RAG] OMDb fetch failed for {t}: {e}")
    return out

def fetch_cars() -> List[Dict[str,Any]]:
    """Fetch some cars from CarQuery API"""
    out=[]
    try:
        url = "https://www.carqueryapi.com/api/0.3/?cmd=getTrims&year=2025&make=tesla"
        data = _http_get_json(url, timeout=20)
        trims = data.get("Trims") or []
        for car in trims[:10]:
            out.append({
                "category":"car",
                "make":car.get("model_make_id"),
                "model":car.get("model_name"),
                "year":car.get("model_year"),
                "engine":car.get("model_engine_fuel"),
                "score":4
            })
    except Exception as e:
        print(f"[RAG] CarQuery fetch failed: {e}")
    return out

def fetch_tech() -> List[Dict[str,Any]]:
    """Fetch tech/self-hosted releases from GitHub"""
    repos = ["opnsense/core","moby/moby","docker/compose"]
    out=[]
    for repo in repos:
        try:
            url = f"https://api.github.com/repos/{repo}/releases/latest"
            data = _http_get_json(url, headers={"User-Agent":"Jarvis-RAG"}, timeout=15)
            if data.get("tag_name"):
                out.append({
                    "category":"tech",
                    "repo":repo,
                    "version":data.get("tag_name"),
                    "published":data.get("published_at"),
                    "name":data.get("name"),
                    "score":3
                })
        except Exception as e:
            print(f"[RAG] GitHub fetch failed for {repo}: {e}")
    return out

def refresh_curated():
    """Refresh curated knowledge file"""
    try:
        if (not os.path.exists(CURATED_FILE)) or _file_too_old(CURATED_FILE, CURATED_REFRESH_DAYS) or os.path.getsize(CURATED_FILE) > MAX_CURATED_SIZE:
            print("[RAG] Refreshing curated knowledge...")
            facts=[]
            facts.extend(fetch_movies_series())
            facts.extend(fetch_cars())
            facts.extend(fetch_tech())
            # Save as JSONL
            lines = [json.dumps(f,ensure_ascii=False) for f in facts]
            _write_text_atomic(CURATED_FILE, "\n".join(lines))
            print(f"[RAG] Wrote curated knowledge: {len(facts)} facts")
    except Exception as e:
        print(f"[RAG] Curated refresh failed: {e}")

def load_curated() -> List[Dict[str,Any]]:
    try:
        if not os.path.exists(CURATED_FILE): 
            return []
        facts=[]
        with open(CURATED_FILE,"r",encoding="utf-8") as f:
            for line in f:
                try:
                    facts.append(json.loads(line))
                except: 
                    continue
        return facts
    except Exception:
        return []
# ----------------- IO + cache (HA + Curated) -----------------

def refresh_and_cache() -> List[Dict[str,Any]]:
    global _LAST_REFRESH_TS, _MEM_CACHE
    cfg = _load_options()
    facts = _fetch_ha_states(cfg)
    curated = load_curated()
    if curated:
        facts.extend(curated)
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
        # refresh curated too
        refresh_curated()
        return refresh_and_cache()
    facts = load_cached()
    if not facts:
        refresh_curated()
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
        filtered += [f for f in facts if "axpert" in str(f.get("entity_id","")).lower() or "axpert" in str(f.get("friendly_name","")).lower()]
    if "sonoff" in q:
        filtered += [f for f in facts if "sonoff" in str(f.get("entity_id","")).lower() or "sonoff" in str(f.get("friendly_name","")).lower()]
    if "zigbee" in q or "z2m" in q:
        filtered += [f for f in facts if "zigbee" in str(f.get("entity_id","")).lower() or "zigbee" in str(f.get("friendly_name","")).lower()]
    if "where" in q:
        filtered += [f for f in facts if f.get("domain") in ("person","device_tracker")]
    if q & MEDIA_KEYWORDS:
        filtered += [f for f in facts if any(
            m in str(f.get("entity_id","")).lower() or m in str(f.get("friendly_name","")).lower()
            for m in MEDIA_KEYWORDS
        )]
    # area queries
    for f in facts:
        if f.get("area") and str(f.get("area","")).lower() in q:
            filtered.append(f)

    if filtered:
        facts = filtered

    want_cats = _intent_categories(q)

    scored: List[Tuple[int, Dict[str, Any]]] = []
    for f in facts:
        s = int(f.get("score", 1))
        ft = set(_tok(f.get("summary", f.get("title",""))) + _tok(f.get("entity_id", "")))
        cats = set(f.get("cats", []))

        if q and (q & ft): s += 3
        if q & SOLAR_KEYWORDS: s += 2
        if {"state_of_charge","battery_state_of_charge","battery_soc","soc"} & ft:
            s += 12
        if want_cats and (cats & want_cats):
            s += 15
        if want_cats & {"energy.storage"} and "energy.storage" in cats:
            s += 20

        scored.append((s, f))

    scored.sort(key=lambda x: x[0], reverse=True)

    ctx_tokens = _ctx_tokens_from_options()
    budget = _rag_budget_tokens(ctx_tokens)

    candidate_facts = [f for _, f in (scored[:top_k] if top_k else scored)]

    selected: List[str] = []
    remaining = budget

    for f in candidate_facts:
        line = f.get("summary") or f.get("plot") or f.get("title") or f.get("repo")
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
    print("Refreshing RAG facts (HA + curated)...")
    try:
        refresh_curated()
    except Exception as e:
        print("[RAG] curated refresh failed:", e)

    facts = refresh_and_cache()
    print(f"[RAG] Wrote {len(facts)} combined facts.")