#!/usr/bin/env python3
# /app/enviroguard.py
# EnviroGuard — ambient-aware LLM performance governor for Jarvis Prime

from __future__ import annotations
import os
import json
import time
import asyncio
import requests
from typing import Optional, Dict, Any, Tuple

# ------------------------------
# Internal state
# ------------------------------
_state: Dict[str, Any] = {
    "enabled": False,
    "mode": "auto",
    "profile": "normal",
    "last_temp_c": None,
    "last_ts": 0,
    "source": None,
    "task": None,
    "forced_off": False,
    "profile_source": "defaults",
}

# Default configuration template
_cfg_template: Dict[str, Any] = {
    "enabled": False,
    "poll_minutes": 30,
    "max_stale_minutes": 120,
    "off_c": 42,
    "hot_c": 33,
    "normal_c": 22,
    "boost_c": 16,
    "cold_c": 10,
    "hyst_c": 2,
    "profiles": {
        "manual": { "cpu_percent": 20, "ctx_tokens": 4096, "timeout_seconds": 20 },
        "hot":    { "cpu_percent": 10, "ctx_tokens": 2048, "timeout_seconds": 15 },
        "cold":   { "cpu_percent": 60, "ctx_tokens": 8192, "timeout_seconds": 25 },
        "normal": { "cpu_percent": 30, "ctx_tokens": 4096, "timeout_seconds": 20 },
        "boost":  { "cpu_percent": 60, "ctx_tokens": 8192, "timeout_seconds": 25 },
        "off":    { "cpu_percent": 0, "ctx_tokens": 0, "timeout_seconds": 0 },
    },
    "ha_url": "",
    "ha_token": "",
    "ha_temperature_entity": "",
    "weather_enabled": True,
    "weather_lat": -26.2041,
    "weather_lon": 28.0473,
}

# ------------------------------
# Helpers
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
        cfg["normal_c"] = float(merged.get("llm_enviroguard_normal_c", cfg["normal_c"]))
        cfg["boost_c"]  = float(merged.get("llm_enviroguard_boost_c", cfg["boost_c"]))
        cfg["cold_c"]   = float(merged.get("llm_enviroguard_cold_c", cfg["cold_c"]))
        cfg["hyst_c"]   = float(merged.get("llm_enviroguard_hysteresis_c", cfg["hyst_c"]))

        # ------------------------------
        # Profiles fix — handle dict OR JSON string
        # ------------------------------
        prof_raw = merged.get("llm_enviroguard_profiles")

        if isinstance(prof_raw, dict):
            cfg["profiles"] = prof_raw
            _state["profile_source"] = "options.json"
        elif isinstance(prof_raw, str):
            try:
                parsed = json.loads(prof_raw)
                if isinstance(parsed, dict):
                    cfg["profiles"] = parsed
                    _state["profile_source"] = "options.json"
                else:
                    raise ValueError("profiles JSON was not a dict")
            except Exception as e:
                print(f"[EnviroGuard] Failed to parse profiles string: {e}")
                _state["profile_source"] = "invalid"
        else:
            _state["profile_source"] = "defaults"

        # Home Assistant
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

# ------------------------------
# Apply Profile
# ------------------------------
def _apply_profile(name: str, merged: dict, cfg: Dict[str, Any]) -> None:
    name = (name or "normal").lower()
    profiles = cfg.get("profiles", {}) or {}
    prof = profiles.get(name) or {}

    cpu  = prof.get("cpu_percent", merged.get("llm_max_cpu_percent", 80))
    ctx  = prof.get("ctx_tokens", merged.get("llm_ctx_tokens", 4096))
    tout = prof.get("timeout_seconds", merged.get("llm_timeout_seconds", 20))

    try: cpu = int(cpu)
    except: cpu = 80
    try: ctx = int(ctx)
    except: ctx = 4096
    try: tout = int(tout)
    except: tout = 20

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
        os.environ["BEAUTIFY_LLM_ENABLED"] = "false"
    else:
        if _state.get("forced_off"):
            merged["llm_enabled"] = True
            os.environ["BEAUTIFY_LLM_ENABLED"] = "true"
        _state["forced_off"] = False

    _state["profile"] = name
    src = _state.get("profile_source", "defaults")
    print(f"[EnviroGuard] Applied profile {name.upper()} (CPU={cpu}%, ctx={ctx}, to={tout}s) [source={src}]")

# ------------------------------
# Temp fetch
# ------------------------------
def _ha_get_temperature(cfg: Dict[str, Any]) -> Optional[float]:
    url, token, entity = cfg.get("ha_url"), cfg.get("ha_token"), cfg.get("ha_temperature_entity")
    if not (url and token and entity): return None
    try:
        r = requests.get(f"{url.rstrip('/')}/api/states/{entity}",
                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                         timeout=6)
        if not r.ok: return None
        j = r.json() or {}
        v = j.get("state")
        if v and str(v).lower() not in ("unknown", "unavailable"):
            try: return float(v)
            except: pass
        attrs = j.get("attributes") or {}
        for k in ("temperature","current_temperature","temp","value"):
            if k in attrs:
                try: return float(attrs[k])
                except: continue
    except Exception: pass
    return None

def _meteo_get_temperature(cfg: Dict[str, Any]) -> Optional[float]:
    if not cfg.get("weather_enabled", True): return None
    try:
        r = requests.get(
            f"https://api.open-meteo.com/v1/forecast?latitude={cfg['weather_lat']}&longitude={cfg['weather_lon']}&current_weather=true&temperature_unit=celsius",
            timeout=8
        )
        if not r.ok: return None
        cw = (r.json() or {}).get("current_weather") or {}
        t = cw.get("temperature")
        if isinstance(t,(int,float)): return float(t)
    except Exception: pass
    return None

def _get_temperature(cfg: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    t = _ha_get_temperature(cfg)
    if t is not None: return round(float(t),1), "homeassistant"
    t = _meteo_get_temperature(cfg)
    if t is not None: return round(float(t),1), "open-meteo"
    return None, None

# ------------------------------
# Public API
# ------------------------------
def get_boot_status_line(merged: dict) -> str:
    cfg = _cfg_from(merged)
    mode, prof, t, src = _state.get("mode","auto"), _state.get("profile","normal"), _state.get("last_temp_c"), _state.get("source") or "?"
    if not cfg.get("enabled"):
        return f"🌡️ EnviroGuard — OFF (mode={mode.upper()}, profile={prof.upper()}, src={src})"
    if t is not None:
        return f"🌡️ EnviroGuard — ACTIVE (mode={mode.upper()}, profile={prof.upper()}, {t:.1f}°C, src={src})"
    return f"🌡️ EnviroGuard — ACTIVE (mode={mode.upper()}, profile={prof.upper()}, src={src})"

def command(want: str, merged: dict, send_message) -> bool:
    cfg = _cfg_from(merged)
    w = (want or "").strip().lower()
    if w == "auto":
        _state["mode"] = "auto"
        if callable(send_message):
            send_message("EnviroGuard","Switched to AUTO mode — ambient temperature will control the profile.",priority=4,decorate=False)
    elif w in (cfg.get("profiles") or {}):
        _state["mode"] = "manual"
        _apply_profile(w, merged, cfg)
        if callable(send_message):
            send_message("EnviroGuard",f"MANUAL override → profile **{w.upper()}** (CPU={merged['llm_max_cpu_percent']}%, ctx={merged['llm_ctx_tokens']}, to={merged['llm_timeout_seconds']}s)",priority=4,decorate=False)
    else:
        return False
    return True

def start_background_poll(merged: dict, send_message):
    cfg = _cfg_from(merged)
    _state["enabled"], _state["mode"], _state["profile"] = bool(cfg.get("enabled")), _state.get("mode","auto"), _state.get("profile","normal")
    try: loop = asyncio.get_running_loop()
    except RuntimeError: return
    t = _state.get("task")
    if t and isinstance(t,asyncio.Task) and not t.done():
        try: t.cancel()
        except: pass
    task = loop.create_task(_poll_loop(merged, send_message))
    _state["task"] = task
    return task

def stop_background_poll():
    t = _state.get("task")
    if t and isinstance(t,asyncio.Task) and not t.done():
        try: t.cancel()
        except: pass
    _state["task"] = None

async def _poll_loop(merged: dict, send_message):
    cfg = _cfg_from(merged)
    poll = max(1,int(cfg.get("poll_minutes",30)))
    _apply_profile(_state.get("profile","normal"), merged, cfg)
    while True:
        try:
            if not cfg.get("enabled",False):
                await asyncio.sleep(poll*60); continue
            temp_c, source = _get_temperature(cfg)
            if temp_c is not None:
                _state.update({"last_temp_c":temp_c,"source":source,"last_ts":int(time.time())})
                if _state.get("mode","auto") == "auto":
                    last = _state.get("profile","normal")
                    nextp = "off" if temp_c >= float(cfg.get("off_c")) else "normal"
                    if nextp != last:
                        _apply_profile(nextp, merged, cfg)
                        if callable(send_message):
                            send_message("EnviroGuard",f"{source or 'temp'} {temp_c:.1f}°C → profile **{nextp.upper()}** (CPU={merged['llm_max_cpu_percent']}%, ctx={merged['llm_ctx_tokens']}, to={merged['llm_timeout_seconds']}s)",priority=4,decorate=False)
        except Exception as e:
            print(f"[EnviroGuard] poll error: {e}")
        await asyncio.sleep(poll*60)