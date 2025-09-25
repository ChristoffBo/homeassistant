#!/usr/bin/env python3
# /app/enviroguard.py
# EnviroGuard — ambient-aware LLM performance governor for Jarvis Prime
#
# Responsibilities:
# - Prefer Home Assistant indoor temperature; fallback to Open-Meteo outdoor
# - Decide a profile (off/ hot/ normal/ boost/ cold/ manual) using hysteresis to avoid flapping
# - Apply profile by updating the shared "merged" config + select env vars
# - OFF profile (or cpu_percent <= 0) hard-disables LLM/riffs to protect the host
#
# Public API expected by /app/bot.py:
#   - get_boot_status_line(merged: dict) -> str
#   - command(want: str, merged: dict, send_message: callable) -> bool
#   - start_background_poll(merged: dict, send_message: callable) -> None
#   - stop_background_poll() -> None
#
# Dependency: requests

from __future__ import annotations
import os, json, time, asyncio, requests
from typing import Optional, Dict, Any, Tuple

# ------------------------------
# Internal state
# ------------------------------
_state: Dict[str, Any] = {
    "enabled": False,
    "mode": "auto",        # auto | manual
    "profile": "normal",
    "last_temp_c": None,   # float | None
    "last_ts": 0,          # epoch seconds of last temp fetch
    "source": None,        # 'homeassistant' | 'open-meteo' | None
    "task": None,          # asyncio.Task or None
    "forced_off": False,   # we turned LLM off due to OFF profile
}

# Default configuration template
_cfg_template: Dict[str, Any] = {
    "enabled": False,
    "poll_minutes": 30,
    "max_stale_minutes": 120,
    # Temperature thresholds (°C)
    "off_c": 42,
    "hot_c": 33,
    "normal_c": 22,
    "boost_c": 16,
    "cold_c": 10,
    "hyst_c": 2,
    # Profiles
    "profiles": {
        "manual": { "cpu_percent": 20, "ctx_tokens": 4096, "timeout_seconds": 20 },
        "hot":    { "cpu_percent": 10, "ctx_tokens": 2048, "timeout_seconds": 15 },
        "normal": { "cpu_percent": 30, "ctx_tokens": 4096, "timeout_seconds": 20 },
        "boost":  { "cpu_percent": 60, "ctx_tokens": 8192, "timeout_seconds": 25 },
    },
    # Home Assistant
    "ha_url": "",
    "ha_token": "",
    "ha_temperature_entity": "",
    # Fallback Open-Meteo
    "weather_enabled": True,
    "weather_lat": -26.2041,
    "weather_lon": 28.0473,
}

# ------------------------------
# Utilities
# ------------------------------
def _as_bool(v, default=False):
    s = str(v).strip().lower()
    if s in ("1","true","yes","on"): return True
    if s in ("0","false","no","off"): return False
    return bool(default)

def _cfg_from(merged: dict) -> Dict[str, Any]:
    cfg = dict(_cfg_template)
    try:
        cfg["enabled"] = _as_bool(merged.get("llm_enviroguard_enabled", cfg["enabled"]), cfg["enabled"])
        cfg["poll_minutes"] = int(merged.get("llm_enviroguard_poll_minutes", cfg["poll_minutes"]))
        cfg["max_stale_minutes"] = int(merged.get("llm_enviroguard_max_stale_minutes", cfg["max_stale_minutes"]))
        cfg["off_c"]    = float(merged.get("llm_enviroguard_off_c", cfg["off_c"]))
        cfg["hot_c"]    = float(merged.get("llm_enviroguard_hot_c", cfg["hot_c"]))
        cfg["normal_c"] = float(merged.get("llm_enviroguard_normal_c", merged.get("llm_enviroguard_warm_c", cfg["normal_c"])))
        cfg["boost_c"]  = float(merged.get("llm_enviroguard_boost_c", cfg["boost_c"]))
        cfg["cold_c"]   = float(merged.get("llm_enviroguard_cold_c", cfg["cold_c"]))
        cfg["hyst_c"]   = float(merged.get("llm_enviroguard_hysteresis_c", cfg["hyst_c"]))

        prof = merged.get("llm_enviroguard_profiles", cfg["profiles"])
        if isinstance(prof, str):
            try: prof = json.loads(prof)
            except Exception: prof = cfg["profiles"]
        if isinstance(prof, dict):
            cfg["profiles"] = prof

        cfg["ha_url"] = str(
            merged.get("llm_enviroguard_ha_base_url")
            or merged.get("ha_base_url")
            or merged.get("ha_url")
            or cfg["ha_url"]
        ).strip()
        cfg["ha_token"] = str(
            merged.get("llm_enviroguard_ha_token")
            or merged.get("ha_token")
            or cfg["ha_token"]
        ).strip()
        cfg["ha_temperature_entity"] = str(
            merged.get("llm_enviroguard_ha_temp_entity")
            or merged.get("ha_indoor_temp_entity")
            or merged.get("ha_temperature_entity")
            or cfg["ha_temperature_entity"]
        ).strip()

        cfg["weather_enabled"] = _as_bool(merged.get("weather_enabled", cfg["weather_enabled"]), cfg["weather_enabled"])
        cfg["weather_lat"] = float(merged.get("weather_lat", cfg["weather_lat"]))
        cfg["weather_lon"] = float(merged.get("weather_lon", cfg["weather_lon"]))
    except Exception as e:
        print(f"[EnviroGuard] config merge error: {e}")
    return cfg

def _apply_profile(name: str, merged: dict, cfg: Dict[str, Any]) -> None:
    name = (name or "normal").lower()
    prof = (cfg.get("profiles") or {}).get(name) or {}
    cpu = int(prof.get("cpu_percent", merged.get("llm_max_cpu_percent", 80)))
    ctx = int(prof.get("ctx_tokens",  merged.get("llm_ctx_tokens", 4096)))
    tout= int(prof.get("timeout_seconds", merged.get("llm_timeout_seconds", 20)))

    merged["llm_max_cpu_percent"] = cpu
    merged["llm_ctx_tokens"] = ctx
    merged["llm_timeout_seconds"] = tout

    os.environ["LLM_MAX_CPU_PERCENT"] = str(cpu)
    os.environ["LLM_CTX_TOKENS"] = str(ctx)
    os.environ["LLM_TIMEOUT_SECONDS"] = str(tout)

    if cpu <= 0 or name == "off":
        _state["forced_off"] = True
        merged["llm_enabled"] = False
        merged["llm_rewrite_enabled"] = False
        os.environ["BEAUTIFY_LLM_ENABLED"] = "0"
    else:
        if _state.get("forced_off"):
            merged["llm_enabled"] = True
            os.environ["BEAUTIFY_LLM_ENABLED"] = "1"
        _state["forced_off"] = False

    _state["profile"] = name
def _ha_get_temperature(cfg: Dict[str, Any]) -> Optional[float]:
    url, token, entity = cfg.get("ha_url"), cfg.get("ha_token"), cfg.get("ha_temperature_entity")
    if not (url and token and entity): return None
    try:
        r = requests.get(f"{url.rstrip('/')}/api/states/{entity}",
                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                         timeout=6)
        if not r.ok: return None
        j = r.json() or {}
        if "state" in j:
            v = j.get("state")
            if v and str(v).lower() not in ("unknown","unavailable"):
                return float(v)
        for k in ("temperature","current_temperature","temp","value"):
            if k in (j.get("attributes") or {}):
                try: return float(j["attributes"][k])
                except Exception: continue
        return None
    except Exception: return None

def _meteo_get_temperature(cfg: Dict[str, Any]) -> Optional[float]:
    if not cfg.get("weather_enabled", True): return None
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={cfg['weather_lat']}&longitude={cfg['weather_lon']}&current_weather=true&temperature_unit=celsius"
        r = requests.get(url, timeout=8)
        if not r.ok: return None
        t = (r.json() or {}).get("current_weather",{}).get("temperature")
        if isinstance(t,(int,float)): return float(t)
    except Exception: return None
    return None

def _get_temperature(cfg: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    t = _ha_get_temperature(cfg)
    if t is not None: return round(float(t),1),"homeassistant"
    t = _meteo_get_temperature(cfg)
    if t is not None: return round(float(t),1),"open-meteo"
    return None,None

def _next_profile_with_hysteresis(temp_c: float, last_profile: str, cfg: Dict[str, Any]) -> str:
    off_c, hot_c, normal_c, boost_c, cold_c, hyst = float(cfg["off_c"]), float(cfg["hot_c"]), float(cfg["normal_c"]), float(cfg["boost_c"]), float(cfg["cold_c"]), float(cfg["hyst_c"])
    lp = (last_profile or "normal").lower()
    def band_of(t: float) -> str:
        if t >= off_c: return "off"
        if t >= hot_c: return "hot"
        if t <= boost_c: return "boost" if "boost" in cfg["profiles"] else ("cold" if "cold" in cfg["profiles"] else "normal")
        if "cold" in cfg["profiles"] and t <= cold_c: return "cold"
        return "normal"
    target = band_of(temp_c)
    if lp=="off" and temp_c<=off_c-hyst: return target
    if lp=="hot" and temp_c<=hot_c-hyst: return target
    if lp=="boost" and temp_c>=boost_c+hyst: return target
    if lp=="cold" and temp_c>=cold_c+hyst: return target
    return target if lp=="normal" else lp

# ------------------------------
# Public API
# ------------------------------
def get_boot_status_line(merged: dict) -> str:
    cfg = _cfg_from(merged)
    mode = _state.get("mode", "auto")
    if not cfg.get("enabled"): return f"🌡️ EnviroGuard — OFF (mode={mode})"
    prof = _state.get("profile","normal")
    t,src = _state.get("last_temp_c"),_state.get("source") or "?"
    suffix = f" (mode={mode}, profile={prof}, {t} °C, src={src})" if t is not None else f" (mode={mode}, profile={prof}, src={src})"
    return "🌡️ EnviroGuard — ACTIVE"+suffix

def command(want: str, merged: dict, send_message) -> bool:
    cfg = _cfg_from(merged)
    w = (want or "").strip().lower()
    if not w:
        mode = _state.get("mode","auto")
        prof = _state.get("profile","normal")
        t,src = _state.get("last_temp_c"),_state.get("source") or "?"
        msg = f"ENV MODE={mode.upper()}, PROFILE={prof.upper()}, SRC={src}"
        if t is not None: msg += f", {t:.1f}°C"
        if callable(send_message):
            try: send_message("EnviroGuard", msg, priority=4, decorate=False)
            except Exception: pass
        return True
    if w=="auto":
        changed = (_state.get("mode")!="auto")
        _state["mode"]="auto"
        if callable(send_message):
            try: send_message("EnviroGuard",
                              "Switched to AUTO mode — ambient temperature will control the profile." if changed else "Already in AUTO mode — ambient temperature controls the profile.",
                              priority=4,decorate=False)
            except Exception: pass
        return True
    profiles=(cfg.get("profiles") or {}).keys()
    if w in profiles:
        was_mode=_state.get("mode")
        _state["mode"]="manual"
        _apply_profile(w, merged, cfg)
        if callable(send_message):
            try: send_message("EnviroGuard",
                              (f"{'Switched to MANUAL' if was_mode!='manual' else 'MANUAL override'} → profile **{w.upper()}** "
                               f"(CPU={merged.get('llm_max_cpu_percent')}%, ctx={merged.get('llm_ctx_tokens')}, to={merged.get('llm_timeout_seconds')}s)"),
                              priority=4,decorate=False)
            except Exception: pass
        return True
    return False

async def _poll_loop(merged: dict, send_message) -> None:
    cfg=_cfg_from(merged)
    poll=max(1,int(cfg.get("poll_minutes",30)))
    _apply_profile(_state.get("profile","normal"), merged, cfg)
    while True:
        try:
            if not cfg.get("enabled",False):
                await asyncio.sleep(poll*60); continue
            temp_c,source=_get_temperature(cfg)
            if temp_c is not None:
                _state.update({"last_temp_c":temp_c,"source":source or _state.get("source"),"last_ts":int(time.time())})
            if _state.get("mode","auto")=="auto" and temp_c is not None:
                last=_state.get("profile","normal")
                nextp="off" if temp_c>=float(cfg.get("off_c")) else _next_profile_with_hysteresis(temp_c,last,cfg)
                if nextp!=last:
                    _apply_profile(nextp,merged,cfg)
                    if callable(send_message):
                        try: send_message("EnviroGuard",
                                          f"{source or 'temp'} {temp_c:.1f}°C → profile **{nextp.upper()}** (CPU={merged.get('llm_max_cpu_percent')}%, ctx={merged.get('llm_ctx_tokens')}, to={merged.get('llm_timeout_seconds')}s)",
                                          priority=4,decorate=False)
                        except Exception: pass
        except Exception as e: print(f"[EnviroGuard] poll error: {e}")
        await asyncio.sleep(poll*60)

def start_background_poll(merged: dict, send_message) -> None:
    cfg=_cfg_from(merged)
    _state.update({"enabled":bool(cfg.get("enabled")), "mode":_state.get("mode","auto"), "profile":_state.get("profile","normal")})
    try: loop=asyncio.get_running_loop()
    except RuntimeError: return
    t=_state.get("task")
    if t and isinstance(t,asyncio.Task) and not t.done():
        try: t.cancel()
        except Exception: pass
    _state["task"]=loop.create_task(_poll_loop(merged,send_message))

def stop_background_poll() -> None:
    t=_state.get("task")
    if t and isinstance(t,asyncio.Task) and not t.done():
        try: t.cancel()
        except Exception: pass
    _state["task"]=None