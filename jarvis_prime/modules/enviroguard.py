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
# Dependency: requests, pyyaml

from __future__ import annotations
import os
import json
import time
import asyncio
import requests
import yaml
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
    "profile_source": "defaults",  # track if profile values came from options.json or defaults
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
    # Profiles:
    # - Any profile with cpu_percent <= 0 implies "OFF": disable LLM/riffs
    # - Keys: cpu_percent, ctx_tokens, timeout_seconds
    "profiles": {
        "manual": { "cpu_percent": 20, "ctx_tokens": 4096, "timeout_seconds": 20 },
        "hot":    { "cpu_percent": 10, "ctx_tokens": 2048, "timeout_seconds": 15 },
        "cold":   { "cpu_percent": 60, "ctx_tokens": 8192, "timeout_seconds": 25 },
        "normal": { "cpu_percent": 30, "ctx_tokens": 4096, "timeout_seconds": 20 },
        "boost":  { "cpu_percent": 60, "ctx_tokens": 8192, "timeout_seconds": 25 },
        # explicit OFF profile
        "off":    { "cpu_percent": 0, "ctx_tokens": 0, "timeout_seconds": 0 },
    },
    # Home Assistant (preferred source)
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

def _try_parse_yaml_or_json(v: Any) -> Optional[dict]:
    """Attempt to parse value as YAML or JSON, tolerant of formats."""
    if isinstance(v, dict):
        return v
    if not isinstance(v, str):
        return None

    # Try JSON direct
    try:
        j = json.loads(v)
        if isinstance(j, dict):
            return j
    except Exception:
        pass

    # Try YAML safe_load
    try:
        y = yaml.safe_load(v)
        if isinstance(y, dict):
            return y
    except Exception:
        pass

    # Try flat JSON (strip newlines)
    try:
        flat = v.replace("\r\n", "\n").replace("\n", "").strip()
        j = json.loads(flat)
        if isinstance(j, dict):
            return j
    except Exception:
        pass

    return None

def _cfg_from(merged: dict) -> Dict[str, Any]:
    """Build runtime config from merged options (supports YAML+JSON)."""
    cfg = dict(_cfg_template)
    try:
        # Enablement & cadence
        cfg["enabled"] = _as_bool(merged.get("llm_enviroguard_enabled", cfg["enabled"]), cfg["enabled"])
        cfg["poll_minutes"] = int(merged.get("llm_enviroguard_poll_minutes", cfg["poll_minutes"]))
        cfg["max_stale_minutes"] = int(merged.get("llm_enviroguard_max_stale_minutes", cfg["max_stale_minutes"]))

        # Thresholds
        cfg["off_c"]    = float(merged.get("llm_enviroguard_off_c", cfg["off_c"]))
        cfg["hot_c"]    = float(merged.get("llm_enviroguard_hot_c", cfg["hot_c"]))
        cfg["normal_c"] = float(merged.get("llm_enviroguard_normal_c", merged.get("llm_enviroguard_warm_c", cfg["normal_c"])))
        cfg["boost_c"]  = float(merged.get("llm_enviroguard_boost_c", cfg["boost_c"]))
        cfg["cold_c"]   = float(merged.get("llm_enviroguard_cold_c", cfg["cold_c"]))
        cfg["hyst_c"]   = float(merged.get("llm_enviroguard_hysteresis_c", cfg["hyst_c"]))

        # Profiles - unified YAML/JSON parse
        prof_raw = merged.get("llm_enviroguard_profiles", None)

        if prof_raw is None:
            _state["profile_source"] = "defaults"
        else:
            parsed = _try_parse_yaml_or_json(prof_raw)
            if isinstance(parsed, dict):
                cfg["profiles"] = parsed
                _state["profile_source"] = "options.json"
            else:
                _state["profile_source"] = "string-unparseable"

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

        # Fallback weather
        cfg["weather_enabled"] = _as_bool(merged.get("weather_enabled", cfg["weather_enabled"]), cfg["weather_enabled"])
        cfg["weather_lat"] = float(merged.get("weather_lat", cfg["weather_lat"]))
        cfg["weather_lon"] = float(merged.get("weather_lon", cfg["weather_lon"]))
    except Exception as e:
        print(f"[EnviroGuard] config merge error: {e}")
    return cfg
def _apply_profile(name: str, merged: dict, cfg: Dict[str, Any]) -> None:
    """Apply a profile and enforce OFF if cpu<=0 or name=='off'."""
    name = (name or "normal").lower()
    profiles = cfg.get("profiles", {}) or {}
    prof = profiles.get(name) or {}

    cpu = prof.get("cpu_percent")
    ctx = prof.get("ctx_tokens")
    tout = prof.get("timeout_seconds")

    # fallbacks
    if cpu is None:
        cpu = merged.get("llm_max_cpu_percent", cfg.get("profiles", {}).get(name, {}).get("cpu_percent", 80))
    if ctx is None:
        ctx = merged.get("llm_ctx_tokens", cfg.get("profiles", {}).get(name, {}).get("ctx_tokens", 4096))
    if tout is None:
        tout = merged.get("llm_timeout_seconds", cfg.get("profiles", {}).get(name, {}).get("timeout_seconds", 20))

    try: cpu = int(cpu)
    except Exception: cpu = int(merged.get("llm_max_cpu_percent", 80))
    try: ctx = int(ctx)
    except Exception: ctx = int(merged.get("llm_ctx_tokens", 4096))
    try: tout = int(tout)
    except Exception: tout = int(merged.get("llm_timeout_seconds", 20))

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

def _ha_get_temperature(cfg: Dict[str, Any]) -> Optional[float]:
    url, token, entity = cfg.get("ha_url"), cfg.get("ha_token"), cfg.get("ha_temperature_entity")
    if not (url and token and entity): return None
    try:
        r = requests.get(
            f"{url.rstrip('/')}/api/states/{entity}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=6
        )
        if not r.ok: return None
        j = r.json() or {}
        if "state" in j:
            v = j.get("state")
            if v is not None and str(v).lower() not in ("unknown", "unavailable"):
                try: return float(v)
                except Exception: pass
        for k in ("temperature", "current_temperature", "temp", "value"):
            try:
                if k in j.get("attributes", {}):
                    return float(j["attributes"][k])
            except Exception:
                continue
        return None
    except Exception:
        return None

def _meteo_get_temperature(cfg: Dict[str, Any]) -> Optional[float]:
    if not cfg.get("weather_enabled", True): return None
    lat, lon = cfg.get("weather_lat"), cfg.get("weather_lon")
    try:
        r = requests.get(
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&temperature_unit=celsius",
            timeout=8
        )
        if not r.ok: return None
        cw = (r.json() or {}).get("current_weather") or {}
        t = cw.get("temperature")
        if isinstance(t, (int, float)): return float(t)
    except Exception:
        return None
    return None

def _get_temperature(cfg: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    t = _ha_get_temperature(cfg)
    if t is not None: return round(float(t), 1), "homeassistant"
    t = _meteo_get_temperature(cfg)
    if t is not None: return round(float(t), 1), "open-meteo"
    return None, None
def _next_profile_with_hysteresis(temp_c: float, last_profile: str, cfg: Dict[str, Any]) -> str:
    off_c, hot_c, normal_c, boost_c, cold_c, hyst = (
        float(cfg.get("off_c")), float(cfg.get("hot_c")), float(cfg.get("normal_c")),
        float(cfg.get("boost_c")), float(cfg.get("cold_c")), float(cfg.get("hyst_c", 0))
    )
    lp = (last_profile or "normal").lower()

    def band_of(t: float) -> str:
        if t >= off_c: return "off"
        if t >= hot_c: return "hot"
        if t <= boost_c: return "boost" if "boost" in cfg.get("profiles", {}) else ("cold" if "cold" in cfg.get("profiles", {}) else "normal")
        if "cold" in cfg.get("profiles", {}) and t <= cold_c: return "cold"
        return "normal"

    target = band_of(temp_c)
    if lp == "off" and temp_c > off_c - hyst: return "off"
    if lp == "hot" and temp_c > hot_c - hyst: return "hot"
    if lp == "boost" and temp_c < boost_c + hyst: return "boost"
    if lp == "cold" and temp_c > cold_c + hyst: return "cold"
    return target

def get_boot_status_line(merged: dict) -> str:
    cfg = _cfg_from(merged)
    mode, prof, t, src = _state.get("mode","auto"), _state.get("profile","normal"), _state.get("last_temp_c"), _state.get("source") or "?"
    if not cfg.get("enabled"): return f"🌡️ EnviroGuard — OFF (mode={mode.upper()}, profile={prof.upper()}, src={src})"
    if t is not None: return f"🌡️ EnviroGuard — ACTIVE (mode={mode.upper()}, profile={prof.upper()}, {t:.1f}°C, src={src})"
    return f"🌡️ EnviroGuard — ACTIVE (mode={mode.upper()}, profile={prof.upper()}, src={src})"

def command(want: str, merged: dict, send_message) -> bool:
    cfg, w = _cfg_from(merged), (want or "").strip().lower()
    if w == "auto":
        _state["mode"] = "auto"
        if callable(send_message): send_message("EnviroGuard", "Switched to AUTO mode — ambient temperature will control the profile.", priority=4, decorate=False)
    elif w in (cfg.get("profiles") or {}):
        _state["mode"] = "manual"; _apply_profile(w, merged, cfg)
        if callable(send_message): send_message("EnviroGuard", f"MANUAL override → profile **{w.upper()}** (CPU={merged['llm_max_cpu_percent']}%, ctx={merged['llm_ctx_tokens']}, to={merged['llm_timeout_seconds']}s)", priority=4, decorate=False)
    elif w: return False
    if callable(send_message): send_message("EnviroGuard", get_boot_status_line(merged), priority=4, decorate=False)
    return True

def set_profile(name: str) -> Dict[str, Any]:
    cfg = _cfg_from({}); _apply_profile(name, {}, cfg); return cfg.get("profiles", {}).get(name, {})

async def _poll_loop(merged: dict, send_message) -> None:
    cfg, poll = _cfg_from(merged), max(1, int(_cfg_from(merged).get("poll_minutes", 30)))
    _apply_profile(_state.get("profile","normal"), merged, cfg)
    while True:
        try:
            if not cfg.get("enabled", False): await asyncio.sleep(poll*60); continue
            temp_c, source = _get_temperature(cfg)
            if temp_c is not None:
                _state.update({"last_temp_c": temp_c, "source": source or _state.get("source"), "last_ts": int(time.time())})
            if _state.get("mode","auto") == "auto" and temp_c is not None:
                last, nextp = _state.get("profile","normal"), _next_profile_with_hysteresis(temp_c, _state.get("profile","normal"), cfg) if temp_c < float(cfg.get("off_c")) else "off"
                if nextp != last:
                    _apply_profile(nextp, merged, cfg)
                    if callable(send_message): send_message("EnviroGuard", f"{source or 'temp'} {temp_c:.1f}°C → profile **{nextp.upper()}** (CPU={merged['llm_max_cpu_percent']}%, ctx={merged['llm_ctx_tokens']}, to={merged['llm_timeout_seconds']}s)", priority=4, decorate=False)
        except Exception as e: print(f"[EnviroGuard] poll error: {e}")
        await asyncio.sleep(poll*60)

def start_background_poll(merged: dict, send_message):
    cfg = _cfg_from(merged); _state.update({"enabled": bool(cfg.get("enabled")), "mode": _state.get("mode","auto"), "profile": _state.get("profile","normal")})
    try: loop = asyncio.get_running_loop()
    except RuntimeError: return
    t = _state.get("task"); 
    if t and isinstance(t, asyncio.Task) and not t.done(): t.cancel()
    task = loop.create_task(_poll_loop(merged, send_message)); _state["task"] = task; return task

def stop_background_poll() -> None:
    t = _state.get("task")
    if t and isinstance(t, asyncio.Task) and not t.done(): t.cancel()
    _state["task"] = None