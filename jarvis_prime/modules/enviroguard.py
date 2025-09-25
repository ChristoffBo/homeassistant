#!/usr/bin/env python3
# /app/enviroguard.py
# EnviroGuard — ambient-aware LLM performance governor for Jarvis Prime

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
    "off_c": 42,
    "hot_c": 33,
    "normal_c": 22,
    "boost_c": 16,
    "cold_c": 10,
    "hyst_c": 2,
    "profiles": {
        "manual": { "cpu_percent": 20, "ctx_tokens": 4096, "timeout_seconds": 20 },
        "hot":    { "cpu_percent": 10, "ctx_tokens": 2048, "timeout_seconds": 15 },
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
# Utilities
# ------------------------------
def _as_bool(v, default=False):
    s = str(v).strip().lower()
    if s in ("1","true","yes","on"): return True
    if s in ("0","false","no","off"): return False
    return bool(default)

def _cfg_from(merged: dict) -> Dict[str, Any]:
    """Build runtime config from merged options.json."""
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

        # --- Force load custom profiles from options.json ---
        prof = merged.get("llm_enviroguard_profiles")
        if prof:
            if isinstance(prof, str):
                try:
                    cfg["profiles"] = json.loads(prof)
                    print("[EnviroGuard] Loaded custom profiles from string JSON")
                except Exception as e:
                    print(f"[EnviroGuard] ERROR parsing profiles: {e}")
            elif isinstance(prof, dict):
                cfg["profiles"] = prof
                print("[EnviroGuard] Loaded custom profiles from dict")
        # -----------------------------------------------------

        cfg["ha_url"] = str(
            merged.get("llm_enviroguard_ha_base_url")
            or cfg["ha_url"]
        ).strip()
        cfg["ha_token"] = str(
            merged.get("llm_enviroguard_ha_token")
            or cfg["ha_token"]
        ).strip()
        cfg["ha_temperature_entity"] = str(
            merged.get("llm_enviroguard_ha_temp_entity")
            or cfg["ha_temperature_entity"]
        ).strip()

        cfg["weather_enabled"] = _as_bool(merged.get("weather_enabled", cfg["weather_enabled"]), cfg["weather_enabled"])
        cfg["weather_lat"] = float(merged.get("weather_lat", cfg["weather_lat"]))
        cfg["weather_lon"] = float(merged.get("weather_lon", cfg["weather_lon"]))
    except Exception as e:
        print(f"[EnviroGuard] config merge error: {e}")
    return cfg

def _apply_profile(name: str, merged: dict, cfg: Dict[str, Any], mode: str="AUTO") -> None:
    """Apply a profile and enforce OFF if cpu<=0 or name=='off'."""
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
        os.environ["BEAUTIFY_LLM_ENABLED"] = "false"
    else:
        if _state.get("forced_off"):
            merged["llm_enabled"] = True
            os.environ["BEAUTIFY_LLM_ENABLED"] = "true"
        _state["forced_off"] = False

    _state["profile"] = name

    # Always print when applied
    print(f"[EnviroGuard] {mode} → profile {name.upper()} (CPU={cpu}%, ctx={ctx}, to={tout}s)")

def _ha_get_temperature(cfg: Dict[str, Any]) -> Optional[float]:
    url = cfg.get("ha_url") or ""
    token = cfg.get("ha_token") or ""
    entity = cfg.get("ha_temperature_entity") or ""
    if not (url and token and entity):
        return None
    try:
        s_url = f"{url.rstrip('/')}/api/states/{entity}"
        r = requests.get(
            s_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=6
        )
        if not r.ok:
            return None
        j = r.json() or {}
        if "state" in j:
            v = j.get("state")
            if v not in (None, "unknown", "unavailable"):
                return float(v)
        attrs = j.get("attributes") or {}
        for k in ("temperature", "current_temperature", "temp", "value"):
            if k in attrs:
                return float(attrs[k])
        return None
    except Exception:
        return None

def _meteo_get_temperature(cfg: Dict[str, Any]) -> Optional[float]:
    if not cfg.get("weather_enabled", True):
        return None
    lat = cfg.get("weather_lat", -26.2041)
    lon = cfg.get("weather_lon", 28.0473)
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}&current_weather=true&temperature_unit=celsius"
        )
        r = requests.get(url, timeout=8)
        if not r.ok:
            return None
        j = r.json() or {}
        cw = j.get("current_weather") or {}
        t = cw.get("temperature")
        if isinstance(t, (int, float)):
            return float(t)
    except Exception:
        return None
    return None

def _get_temperature(cfg: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    t = _ha_get_temperature(cfg)
    if t is not None:
        return round(float(t), 1), "homeassistant"
    t = _meteo_get_temperature(cfg)
    if t is not None:
        return round(float(t), 1), "open-meteo"
    return None, None

def _next_profile_with_hysteresis(temp_c: float, last_profile: str, cfg: Dict[str, Any]) -> str:
    off_c   = float(cfg.get("off_c"))
    hot_c   = float(cfg.get("hot_c"))
    normal_c= float(cfg.get("normal_c"))
    boost_c = float(cfg.get("boost_c"))
    cold_c  = float(cfg.get("cold_c"))
    hyst    = float(cfg.get("hyst_c", 0))

    lp = (last_profile or "normal").lower()

    def band_of(t: float) -> str:
        if t >= off_c: return "off"
        if t >= hot_c: return "hot"
        if t <= boost_c: return "boost"
        if t <= cold_c: return "cold"
        return "normal"

    target = band_of(temp_c)

    if lp == "off"   and temp_c > off_c - hyst: return "off"
    if lp == "hot"   and temp_c > hot_c - hyst: return "hot"
    if lp == "boost" and temp_c < boost_c + hyst: return "boost"
    if lp == "cold"  and temp_c > cold_c + hyst: return "cold"

    return target

# ------------------------------
# Public API
# ------------------------------
def get_boot_status_line(merged: dict) -> str:
    cfg = _cfg_from(merged)
    mode = _state.get("mode", "auto")
    prof = _state.get("profile", "normal")
    t = _state.get("last_temp_c")
    src = _state.get("source") or "?"
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
            send_message("EnviroGuard","Switched to AUTO mode",priority=4,decorate=False)
    elif w in (cfg.get("profiles") or {}):
        _state["mode"] = "manual"
        _apply_profile(w, merged, cfg, mode="MANUAL")
        if callable(send_message):
            send_message("EnviroGuard",f"MANUAL → profile {w.upper()}",priority=4,decorate=False)
    else:
        return False
    return True

def set_profile(name: str) -> Dict[str, Any]:
    cfg = _cfg_from({})
    _apply_profile(name, {}, cfg)
    return cfg.get("profiles", {}).get(name, {})

async def _poll_loop(merged: dict, send_message) -> None:
    cfg = _cfg_from(merged)
    poll = max(1, int(cfg.get("poll_minutes", 30)))
    while True:
        try:
            if not cfg.get("enabled", False):
                await asyncio.sleep(poll * 60)
                continue
            temp_c, source = _get_temperature(cfg)
            if temp_c is not None:
                _state["last_temp_c"] = temp_c
                _state["source"] = source
                _state["last_ts"] = int(time.time())
            if _state.get("mode","auto") == "auto" and temp_c is not None:
                last = _state.get("profile","normal")
                nextp = _next_profile_with_hysteresis(temp_c, last, cfg)
                if temp_c >= float(cfg.get("off_c")): nextp = "off"
                if nextp != last:
                    _apply_profile(nextp, merged, cfg, mode="AUTO")
                    if callable(send_message):
                        send_message("EnviroGuard",
                            f"AUTO: {source} {temp_c:.1f}°C → {nextp.upper()}",
                            priority=4,decorate=False)
        except Exception as e:
            print(f"[EnviroGuard] poll error: {e}")
        await asyncio.sleep(poll * 60)

def start_background_poll(merged: dict, send_message):
    cfg = _cfg_from(merged)
    _state["enabled"] = bool(cfg.get("enabled"))
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _state.get("task"):
        try: _state["task"].cancel()
        except: pass
    task = loop.create_task(_poll_loop(merged, send_message))
    _state["task"] = task
    return task

def stop_background_poll() -> None:
    t = _state.get("task")
    if t: 
        try: t.cancel()
        except: pass
    _state["task"] = None