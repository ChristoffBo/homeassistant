
#!/usr/bin/env python3
# /app/enviroguard.py
# EnviroGuard — ambient-aware LLM performance governor for Jarvis Prime
#
# Responsibilities:
# - Periodically read ambient temperature (Home Assistant sensor if configured; otherwise Open‑Meteo)
# - Decide a profile (hot/normal/cold/boost/off/manual) using hysteresis to avoid flapping
# - Apply profile by updating the shared "merged" config + select env vars so other modules immediately see it
# - Optionally hard-disable LLM/riffs in the "off" profile (cpu_percent <= 0 implies OFF)
#
# Public API expected by /app/bot.py:
#   - get_boot_status_line(merged: dict) -> str
#   - command(want: str, merged: dict, send_message: callable) -> bool
#   - start_background_poll(merged: dict, send_message: callable) -> None
#   - stop_background_poll() -> None
#
# The module is intentionally dependency-light (requests only).

from __future__ import annotations
import os, json, time, asyncio, requests
from typing import Optional, Dict, Any

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

_cfg_template: Dict[str, Any] = {
    "enabled": False,
    "poll_minutes": 30,
    "max_stale_minutes": 120,
    "hot_c": 30,
    "cold_c": 10,
    "hyst_c": 2,
    # Profiles note:
    # - Any profile with cpu_percent <= 0 implies "OFF": disable LLM/riffs
    # - Keys: cpu_percent, ctx_tokens, timeout_seconds
    "profiles": {
        "manual": { "cpu_percent": 80, "ctx_tokens": 4096, "timeout_seconds": 20 },
        "hot":    { "cpu_percent": 50, "ctx_tokens": 2048, "timeout_seconds": 15 },
        "normal": { "cpu_percent": 80, "ctx_tokens": 4096, "timeout_seconds": 20 },
        "boost":  { "cpu_percent": 95, "ctx_tokens": 8192, "timeout_seconds": 25 },
        "cold":   { "cpu_percent": 85, "ctx_tokens": 6144, "timeout_seconds": 25 },
        # Optional OFF profile (hard disable)
        # "off": { "cpu_percent": 0, "ctx_tokens": 0, "timeout_seconds": 0 },
    },
    # Optional Home Assistant hook (used if fully configured)
    "ha_url": "",                # e.g., http://homeassistant.local:8123
    "ha_token": "",              # long-lived token
    "ha_temperature_entity": "", # e.g., sensor.living_room_temperature
    # Fallback Open‑Meteo
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
        cfg["hot_c"] = int(merged.get("llm_enviroguard_hot_c", cfg["hot_c"]))
        cfg["cold_c"] = int(merged.get("llm_enviroguard_cold_c", cfg["cold_c"]))
        cfg["hyst_c"] = int(merged.get("llm_enviroguard_hysteresis_c", cfg["hyst_c"]))
        prof = merged.get("llm_enviroguard_profiles", cfg["profiles"])
        if isinstance(prof, str):
            try:
                prof = json.loads(prof)
            except Exception:
                prof = cfg["profiles"]
        if isinstance(prof, dict):
            cfg["profiles"] = prof
        # HA
        cfg["ha_url"] = str(merged.get("ha_url", cfg["ha_url"])).strip()
        cfg["ha_token"] = str(merged.get("ha_token", cfg["ha_token"])).strip()
        cfg["ha_temperature_entity"] = str(merged.get("ha_temperature_entity", cfg["ha_temperature_entity"])).strip()
        # Fallback weather
        cfg["weather_enabled"] = _as_bool(merged.get("weather_enabled", cfg["weather_enabled"]), cfg["weather_enabled"])
        cfg["weather_lat"] = float(merged.get("weather_lat", cfg["weather_lat"]))
        cfg["weather_lon"] = float(merged.get("weather_lon", cfg["weather_lon"]))
    except Exception:
        pass
    return cfg

def _hysteresis_profile_for(temp_c: float, last_profile: str, cfg: Dict[str, Any]) -> str:
    hot = int(cfg["hot_c"]); cold = int(cfg["cold_c"]); hyst = int(cfg["hyst_c"])
    lp = (last_profile or "normal").lower()
    if lp == "hot":
        if temp_c <= hot - hyst: return "normal"
        return "hot"
    if lp == "cold":
        if temp_c >= cold + hyst: return "normal"
        return "cold"
    # normal baseline
    if temp_c >= hot: return "hot"
    if temp_c <= cold: return "cold"
    return "normal"

def _apply_profile(name: str, merged: dict, cfg: Dict[str, Any]) -> None:
    name = (name or "normal").lower()
    prof = (cfg.get("profiles") or {}).get(name) or {}
    cpu = int(prof.get("cpu_percent", merged.get("llm_max_cpu_percent", 80)))
    ctx = int(prof.get("ctx_tokens",  merged.get("llm_ctx_tokens", 4096)))
    tout= int(prof.get("timeout_seconds", merged.get("llm_timeout_seconds", 20)))

    # Apply to merged so rest of app sees it immediately
    merged["llm_max_cpu_percent"] = cpu
    merged["llm_ctx_tokens"] = ctx
    merged["llm_timeout_seconds"] = tout

    # Reflect in environment for sidecars / modules that read env
    os.environ["LLM_MAX_CPU_PERCENT"] = str(cpu)
    os.environ["LLM_CTX_TOKENS"] = str(ctx)
    os.environ["LLM_TIMEOUT_SECONDS"] = str(tout)

    # LLM hard disable if cpu <= 0
    if cpu <= 0 or name == "off":
        _state["forced_off"] = True
        os.environ["BEAUTIFY_LLM_ENABLED"] = "false"
        merged["llm_enabled"] = False
        merged["llm_rewrite_enabled"] = False
    else:
        # Only re-enable if we previously forced it off
        if _state.get("forced_off"):
            os.environ["BEAUTIFY_LLM_ENABLED"] = "true"
            merged["llm_enabled"] = True
            # do not force rewrite back on; respect existing value
        _state["forced_off"] = False

    _state["profile"] = name

def _ha_get_temperature(cfg: Dict[str, Any]) -> Optional[float]:
    url = cfg.get("ha_url") or ""
    token = cfg.get("ha_token") or ""
    entity = cfg.get("ha_temperature_entity") or ""
    if not (url and token and entity):
        return None
    try:
        # Try the state endpoint first
        s_url = f"{url.rstrip('/')}/api/states/{entity}"
        r = requests.get(s_url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, timeout=6)
        if not r.ok:
            return None
        j = r.json() or {}
        v = j.get("state")
        if v is None or str(v).lower() in ("unknown","unavailable"):
            return None
        return float(v)
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

def _get_temperature(cfg: Dict[str, Any]) -> (Optional[float], Optional[str]):
    # Prefer HA if configured; else Open‑Meteo
    t = _ha_get_temperature(cfg)
    if t is not None:
        return round(float(t), 1), "homeassistant"
    t = _meteo_get_temperature(cfg)
    if t is not None:
        return round(float(t), 1), "open-meteo"
    return None, None

# ------------------------------
# Public API
# ------------------------------
def get_boot_status_line(merged: dict) -> str:
    cfg = _cfg_from(merged)
    if not cfg.get("enabled"):
        return "🌡️ EnviroGuard — OFF"
    prof = _state.get("profile", "normal")
    t = _state.get("last_temp_c")
    suffix = f" (profile={prof}" + (f", {t} °C" if t is not None else "") + ")"
    return "🌡️ EnviroGuard — ACTIVE" + suffix

def command(want: str, merged: dict, send_message) -> bool:
    """
    Handle 'jarvis env <auto|PROFILE>' routed from bot.
    """
    cfg = _cfg_from(merged)
    w = (want or "").strip().lower()
    if w == "auto":
        _state["mode"] = "auto"
        if callable(send_message):
            try:
                send_message("EnviroGuard", "Auto mode resumed — ambient temperature will control the profile.", priority=4, decorate=False)
            except Exception:
                pass
        return True
    profiles = (cfg.get("profiles") or {}).keys()
    if w in profiles:
        _state["mode"] = "manual"
        _apply_profile(w, merged, cfg)
        if callable(send_message):
            try:
                send_message("EnviroGuard", f"Manual override → profile **{w.upper()}** (CPU={merged.get('llm_max_cpu_percent')}%, ctx={merged.get('llm_ctx_tokens')}, to={merged.get('llm_timeout_seconds')}s)", priority=4, decorate=False)
            except Exception:
                pass
        return True
    return False

async def _poll_loop(merged: dict, send_message) -> None:
    cfg = _cfg_from(merged)
    poll = max(1, int(cfg.get("poll_minutes", 30)))
    # Initial apply from current profile to ensure knobs are set
    _apply_profile(_state.get("profile","normal"), merged, cfg)
    while True:
        try:
            if not cfg.get("enabled", False):
                await asyncio.sleep(poll * 60)
                continue

            temp_c, source = _get_temperature(cfg)
            if temp_c is not None:
                _state["last_temp_c"] = temp_c
                _state["source"] = source or _state.get("source")
                _state["last_ts"] = int(time.time())

            if _state.get("mode","auto") == "auto" and temp_c is not None:
                last = _state.get("profile","normal")
                nextp = _hysteresis_profile_for(temp_c, last, cfg)
                if nextp != last:
                    _apply_profile(nextp, merged, cfg)
                    if callable(send_message):
                        try:
                            send_message(
                                "EnviroGuard",
                                f"Ambient {temp_c:.1f}°C → profile **{nextp.upper()}** (CPU={merged.get('llm_max_cpu_percent')}%, ctx={merged.get('llm_ctx_tokens')}, to={merged.get('llm_timeout_seconds')}s)",
                                priority=4,
                                decorate=False
                            )
                        except Exception:
                            pass
        except Exception as e:
            # keep the loop alive
            print(f"[EnviroGuard] poll error: {e}")
        await asyncio.sleep(poll * 60)

def start_background_poll(merged: dict, send_message) -> None:
    """
    Create/replace the background polling task. Safe to call multiple times.
    """
    # Initialize enabled flag & profile from merged (support hot reload)
    cfg = _cfg_from(merged)
    _state["enabled"] = bool(cfg.get("enabled"))
    _state["mode"] = _state.get("mode","auto")
    _state["profile"] = _state.get("profile","normal")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Not in async context; caller should schedule us
        return

    # Cancel existing
    t = _state.get("task")
    if t and isinstance(t, asyncio.Task) and not t.done():
        try:
            t.cancel()
        except Exception:
            pass

    # Start new
    _state["task"] = loop.create_task(_poll_loop(merged, send_message))

def stop_background_poll() -> None:
    t = _state.get("task")
    if t and isinstance(t, asyncio.Task) and not t.done():
        try:
            t.cancel()
        except Exception:
            pass
    _state["task"] = None
