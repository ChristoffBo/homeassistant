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
    # off_c: at/above → OFF safety state
    # hot_c: at/above (but below off_c) → HOT profile
    # normal_c: lower bound for NORMAL band (>= normal_c and < hot_c)
    # boost_c: at/under → BOOST profile
    # cold_c: optional extra lower band (<= cold_c) → COLD profile
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
        "normal": { "cpu_percent": 30, "ctx_tokens": 4096, "timeout_seconds": 20 },
        "boost":  { "cpu_percent": 60, "ctx_tokens": 8192, "timeout_seconds": 25 },
        # optional: "cold": { "cpu_percent": 35, "ctx_tokens": 4096, "timeout_seconds": 22 },
        # optional OFF profile; otherwise cpu_percent<=0 will be enforced dynamically
        # "off": { "cpu_percent": 0, "ctx_tokens": 0, "timeout_seconds": 0 },
    },
    # Home Assistant (preferred source)
    # Accept both classic and llm_enviroguard_ha_* keys via _cfg_from()
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
    """Build runtime config from merged options (supports multiple key names)."""
    cfg = dict(_cfg_template)
    try:
        # Enablement & cadence
        cfg["enabled"] = _as_bool(merged.get("llm_enviroguard_enabled", cfg["enabled"]), cfg["enabled"])
        cfg["poll_minutes"] = int(merged.get("llm_enviroguard_poll_minutes", cfg["poll_minutes"]))
        cfg["max_stale_minutes"] = int(merged.get("llm_enviroguard_max_stale_minutes", cfg["max_stale_minutes"]))

        # Thresholds (accept new explicit keys; fall back to old ones)
        cfg["off_c"]    = float(merged.get("llm_enviroguard_off_c", cfg["off_c"]))
        cfg["hot_c"]    = float(merged.get("llm_enviroguard_hot_c", cfg["hot_c"]))
        cfg["normal_c"] = float(merged.get("llm_enviroguard_normal_c", merged.get("llm_enviroguard_warm_c", cfg["normal_c"])))
        cfg["boost_c"]  = float(merged.get("llm_enviroguard_boost_c", cfg["boost_c"]))
        cfg["cold_c"]   = float(merged.get("llm_enviroguard_cold_c", cfg["cold_c"]))
        cfg["hyst_c"]   = float(merged.get("llm_enviroguard_hysteresis_c", cfg["hyst_c"]))

        # Profiles (stringified JSON or dict)
        prof = merged.get("llm_enviroguard_profiles", cfg["profiles"])
        if isinstance(prof, str):
            try:
                prof = json.loads(prof)
            except Exception:
                prof = cfg["profiles"]
        if isinstance(prof, dict):
            cfg["profiles"] = prof

        # Home Assistant (prefer llm_enviroguard_ha_*; fall back to classic)
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
    prof = (cfg.get("profiles") or {}).get(name) or {}
    cpu = int(prof.get("cpu_percent", merged.get("llm_max_cpu_percent", 80)))
    ctx = int(prof.get("ctx_tokens",  merged.get("llm_ctx_tokens", 4096)))
    tout= int(prof.get("timeout_seconds", merged.get("llm_timeout_seconds", 20)))

    # Apply to merged so the rest of the app sees it
    merged["llm_max_cpu_percent"] = cpu
    merged["llm_ctx_tokens"] = ctx
    merged["llm_timeout_seconds"] = tout

    # Reflect in environment for sidecars / modules that read env
    os.environ["LLM_MAX_CPU_PERCENT"] = str(cpu)
    os.environ["LLM_CTX_TOKENS"] = str(ctx)
    os.environ["LLM_TIMEOUT_SECONDS"] = str(tout)

    # Hard disable if OFF
    if cpu <= 0 or name == "off":
        _state["forced_off"] = True
        merged["llm_enabled"] = False
        merged["llm_rewrite_enabled"] = False
        os.environ["BEAUTIFY_LLM_ENABLED"] = "false"
    else:
        if _state.get("forced_off"):
            # Only re-enable if we previously forced it off
            merged["llm_enabled"] = True
            os.environ["BEAUTIFY_LLM_ENABLED"] = "true"
        _state["forced_off"] = False

    _state["profile"] = name
def _ha_get_temperature(cfg: Dict[str, Any]) -> Optional[float]:
    """Read current temperature from HA sensor if configured."""
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
        # Prefer numeric state; else try common attribute names
        if "state" in j:
            v = j.get("state")
            if v is not None and str(v).lower() not in ("unknown", "unavailable"):
                return float(v)
        attrs = j.get("attributes") or {}
        for k in ("temperature", "current_temperature", "temp", "value"):
            if k in attrs:
                try:
                    return float(attrs[k])
                except Exception:
                    continue
        return None
    except Exception:
        return None

def _meteo_get_temperature(cfg: Dict[str, Any]) -> Optional[float]:
    """Get outdoor temperature from Open-Meteo (fallback)."""
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
    """Return (effective_temp_c, source). Prefer HA; fallback to Open-Meteo."""
    t = _ha_get_temperature(cfg)
    if t is not None:
        return round(float(t), 1), "homeassistant"
    t = _meteo_get_temperature(cfg)
    if t is not None:
        return round(float(t), 1), "open-meteo"
    return None, None

def _next_profile_with_hysteresis(temp_c: float, last_profile: str, cfg: Dict[str, Any]) -> str:
    """
    Decide profile using thresholds and hysteresis.
    Bands (from hottest to coolest):
      OFF:   temp >= off_c
      HOT:   off_c > temp >= hot_c
      NORMAL: hot_c > temp > boost_c (above normal_c if set; otherwise default middle band)
      BOOST: temp <= boost_c
      COLD:  optional extra band if temp <= cold_c and a 'cold' profile exists
    Hysteresis: require crossing thresholds +/- hyst before switching out of current band.
    """
    off_c   = float(cfg.get("off_c"))
    hot_c   = float(cfg.get("hot_c"))
    normal_c= float(cfg.get("normal_c"))
    boost_c = float(cfg.get("boost_c"))
    cold_c  = float(cfg.get("cold_c"))
    hyst    = float(cfg.get("hyst_c", 0))

    lp = (last_profile or "normal").lower()

    # Determine target band without hysteresis
    def band_of(t: float) -> str:
        if t >= off_c:
            return "off"
        if t >= hot_c:
            return "hot"
        if t <= boost_c:
            # prefer explicit 'boost' if defined, else fall back to 'cold' if provided
            return "boost" if "boost" in cfg.get("profiles", {}) else ("cold" if "cold" in cfg.get("profiles", {}) else "normal")
        # optional cold band even lower than boost
        if "cold" in cfg.get("profiles", {}) and t <= cold_c:
            return "cold"
        # middle band
        return "normal"

    target = band_of(temp_c)

    # Hysteresis edges for leaving current band
    if lp == "off":
        if temp_c <= off_c - hyst:
            return band_of(temp_c)
        return "off"
    if lp == "hot":
        if temp_c <= hot_c - hyst:
            return band_of(temp_c)
        return "hot"
    if lp == "boost":
        if temp_c >= boost_c + hyst:
            return band_of(temp_c)
        return "boost"
    if lp == "cold":
        if temp_c >= cold_c + hyst:
            return band_of(temp_c)
        return "cold"

    # lp == normal
    return target
# ------------------------------
# Public API
# ------------------------------
def get_boot_status_line(merged: dict) -> str:
    cfg = _cfg_from(merged)
    mode = _state.get("mode", "auto")
    if not cfg.get("enabled"):
        return f"🌡️ EnviroGuard — OFF (mode={mode})"
    prof = _state.get("profile", "normal")
    t = _state.get("last_temp_c")
    src = _state.get("source") or "?"
    suffix = f" (mode={mode}, profile={prof}, {t} °C, src={src})" if t is not None else f" (mode={mode}, profile={prof}, src={src})"
    return "🌡️ EnviroGuard — ACTIVE" + suffix

def command(want: str, merged: dict, send_message) -> bool:
    """
    Handle 'jarvis env <auto|PROFILE>' routed from bot.
    If no argument, show current state (mode, profile, temp/source).
    Always report state after executing a command.
    """
    cfg = _cfg_from(merged)
    w = (want or "").strip().lower()

    def _report_state():
        mode = _state.get("mode", "auto")
        prof = _state.get("profile", "normal")
        t = _state.get("last_temp_c")
        src = _state.get("source") or "?"
        msg = f"Mode={mode.upper()}, profile={prof.upper()}, src={src}"
        if t is not None:
            msg += f", {t:.1f}°C"
        if callable(send_message):
            try:
                send_message("EnviroGuard", msg, priority=4, decorate=False)
            except Exception:
                pass

    # Report current state when no argument is provided
    if not w:
        _report_state()
        return True

    # Switch to AUTO mode
    if w == "auto":
        changed = (_state.get("mode") != "auto")
        _state["mode"] = "auto"
        if callable(send_message):
            try:
                text = "Switched to AUTO mode — ambient temperature will control the profile."
                if not changed:
                    text = "Already in AUTO mode — ambient temperature controls the profile."
                send_message("EnviroGuard", text, priority=4, decorate=False)
            except Exception:
                pass
        _report_state()
        return True

    # Manual profile selection
    profiles = (cfg.get("profiles") or {}).keys()
    if w in profiles:
        was_mode = _state.get("mode")
        _state["mode"] = "manual"
        _apply_profile(w, merged, cfg)
        if callable(send_message):
            try:
                prefix = "Switched to MANUAL" if was_mode != "manual" else "MANUAL override"
                send_message(
                    "EnviroGuard",
                    (f"{prefix} → profile **{w.upper()}** "
                     f"(CPU={merged.get('llm_max_cpu_percent')}%, "
                     f"ctx={merged.get('llm_ctx_tokens')}, "
                     f"to={merged.get('llm_timeout_seconds')}s)"),
                    priority=4,
                    decorate=False
                )
            except Exception:
                pass
        _report_state()
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
                # OFF safety check first
                if temp_c >= float(cfg.get("off_c")) - 0.0:
                    nextp = "off"
                else:
                    nextp = _next_profile_with_hysteresis(temp_c, last, cfg)

                if nextp != last:
                    _apply_profile(nextp, merged, cfg)
                    if callable(send_message):
                        try:
                            send_message(
                                "EnviroGuard",
                                f"{source or 'temp'} {temp_c:.1f}°C → profile **{nextp.upper()}** (CPU={merged.get('llm_max_cpu_percent')}%, ctx={merged.get('llm_ctx_tokens')}, to={merged.get('llm_timeout_seconds')}s)",
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