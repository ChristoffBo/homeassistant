#!/usr/bin/env python3
# /app/enviroguard.py
# Minimal EnviroGuard module for Jarvis Prime
# - Primary ambient temperature from Home Assistant (if configured)
# - Fallback to Open-Meteo if HA is unavailable
# - OFF / HOT / NORMAL / COLD profiles with hysteresis
# - Manual lock file override to force LLM OFF
# - Writes /data/enviroguard_state.json with profile + llm_blocked
# - Exposes read_ha_temperature_c() for Weather to show 'Indoor' when available
# - start_background_poll() helper to run a polling loop from bot.py
#
# Configuration is read from /data/options.json (written by HA Supervisor from config.json schema).
#
# Expected option keys (flat):
#   llm_enviroguard_enabled: bool
#   llm_enviroguard_poll_minutes: int
#   llm_enviroguard_hot_c: float
#   llm_enviroguard_cold_c: float
#   llm_enviroguard_hysteresis_c: float   # general hysteresis (optional; kept for future use)
#   llm_enviroguard_off_c: float          # OFF threshold (>= off_c -> off)
#   llm_enviroguard_off_hyst_c: float     # OFF hysteresis (resume below off_c - this)
#   ha_enabled: bool
#   ha_base_url: str
#   ha_token: str
#   ha_temp_entity: str
#   ha_verify_ssl: bool
#   openmeteo_lat / openmeteo_lon (or weather_lat / weather_lon) for fallback (optional)
#
# State file (/data/enviroguard_state.json):
#   { "profile": "off|hot|normal|cold",
#     "ambient_c": 33.2,
#     "llm_blocked": true,
#     "manual_lock": false,
#     "ts": 1690000000 }
#
# Manual override:
#   touch /data/llm_off.lock   -> forces llm_blocked = true until removed.
#
# Usage from bot.py (threaded):
#   from enviroguard import start_background_poll
#   start_background_poll()  # uses llm_enviroguard_poll_minutes, defaults to 30m
#
# Or single-tick:
#   from enviroguard import enviroguard_tick
#   enviroguard_tick()
from __future__ import annotations

import json
import math
import os
import ssl
import time
import urllib.parse
import urllib.request
from typing import Optional

STATE_PATH = "/data/enviroguard_state.json"
OPT_PATH   = "/data/options.json"
LOCK_PATH  = "/data/llm_off.lock"  # manual override: if present, llm_blocked = True


# --------------------- options & utils ---------------------

def _read_json(path: str) -> dict:
    """Read JSON file; return {} on any error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _read_options() -> dict:
    """Load /data/options.json (HA add-on runtime config)."""
    return _read_json(OPT_PATH)


def _write_state(d: dict) -> None:
    """Write the enviroguard state JSON to STATE_PATH."""
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        # non-fatal
        pass


def _read_state() -> dict:
    """Return last state (or {})."""
    return _read_json(STATE_PATH)


def _http_get(url: str, headers: dict, timeout: float = 6.0, verify_ssl: bool = True) -> str:
    """Simple HTTP GET with optional TLS verify disable (for self-signed HA)."""
    req = urllib.request.Request(url, headers=headers)
    ctx = None
    if not verify_ssl:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode("utf-8", "replace")


# --------------------- Home Assistant sensor ---------------------

def read_ha_temperature_c() -> Optional[float]:
    """Return indoor temperature (°C) from a Home Assistant sensor, or None if unavailable."""
    opt = _read_options()
    ha_enabled = str(opt.get("ha_enabled", False)).lower() in ("1","true","yes","on")
    if not ha_enabled:
        return None
    base   = (opt.get("ha_base_url") or "").rstrip("/")
    token  = opt.get("ha_token") or ""
    entity = opt.get("ha_temp_entity") or ""
    verify = str(opt.get("ha_verify_ssl", True)).lower() in ("1","true","yes","on")
    if not (base and token and entity):
        return None
    try:
        raw = _http_get(f"{base}/api/states/{entity}",
                        {"Authorization": f"Bearer {token}", "Accept": "application/json"},
                        verify_ssl=verify)
        data = json.loads(raw)
        state = str(data.get("state", "")).strip()
        if state in ("unknown","unavailable","None",""):
            return None
        val = float(state)
        unit = (data.get("attributes", {}).get("unit_of_measurement") or "").strip().lower()
        if unit in ("°f","f","fahrenheit"):
            return (val - 32.0) * (5.0/9.0)
        return val
    except Exception:
        return None


# --------------------- Open-Meteo fallback ---------------------

def _open_meteo_c() -> Optional[float]:
    """Fetch outdoor temperature (°C) from Open-Meteo. Returns None on failure.
    Coordinates are taken from options if present; otherwise from env; otherwise None.
    Keys tried (in order):
      options.json: openmeteo_lat/openmeteo_lon OR weather_lat/weather_lon
      env: OM_LAT/OM_LON OR LAT/LON
    """
    opt = _read_options()
    lat = opt.get("openmeteo_lat") or opt.get("weather_lat") or os.getenv("OM_LAT") or os.getenv("LAT")
    lon = opt.get("openmeteo_lon") or opt.get("weather_lon") or os.getenv("OM_LON") or os.getenv("LON")
    try:
        if not (lat and lon):
            return None
        q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "current": "temperature_2m"})
        url = f"https://api.open-meteo.com/v1/forecast?{q}"
        raw = _http_get(url, {"Accept": "application/json"}, timeout=6.0, verify_ssl=True)
        data = json.loads(raw)
        cur = data.get("current", {}) or {}
        t = cur.get("temperature_2m")
        if t is None:
            return None
        return float(t)
    except Exception:
        return None


def get_ambient_c() -> Optional[float]:
    """Preferred order: HA indoor temp → Open-Meteo outdoor temp."""
    t = read_ha_temperature_c()
    if t is not None and math.isfinite(t):
        return t
    return _open_meteo_c()


# --------------------- Profiles & state ---------------------

def _manual_lock_active() -> bool:
    """Return True if manual lock file exists (forces LLM OFF)."""
    try:
        return os.path.exists(LOCK_PATH)
    except Exception:
        return False


def _pick_profile(ambient_c: float, prev_profile: Optional[str]) -> str:
    """Decide off/hot/normal/cold with OFF hysteresis."""
    opt = _read_options()
    off_c    = float(opt.get("llm_enviroguard_off_c", 33.0))
    off_hyst = float(opt.get("llm_enviroguard_off_hyst_c", 1.0))
    hot_c    = float(opt.get("llm_enviroguard_hot_c", 30.0))
    cold_c   = float(opt.get("llm_enviroguard_cold_c", 15.0))

    # OFF with hysteresis
    if (prev_profile or "") == "off" and ambient_c >= (off_c - off_hyst):
        return "off"
    if ambient_c >= off_c:
        return "off"

    if ambient_c >= hot_c:
        return "hot"
    if ambient_c <= cold_c:
        return "cold"
    return "normal"


def enviroguard_tick() -> None:
    """Single evaluation tick. Call on a timer from bot.py."""
    prev = (_read_state() or {}).get("profile", "normal")
    ambient = get_ambient_c()
    if ambient is None or not math.isfinite(ambient):
        return  # nothing to do
    prof = _pick_profile(ambient, prev)
    manual = _manual_lock_active()
    llm_blocked = manual or (prof == "off")

    st = _read_state() or {}
    changed = (
        st.get("profile") != prof or
        st.get("llm_blocked") != llm_blocked or
        st.get("ambient_c") != round(ambient, 2) or
        st.get("manual_lock") != manual
    )
    if changed:
        _write_state({
            "profile": prof,
            "ambient_c": round(ambient, 2),
            "llm_blocked": llm_blocked,
            "manual_lock": manual,
            "ts": int(time.time())
        })
        # Optionally: emit a Jarvis notification card here if your app supports it.


# --------------------- Convenience: background starter ---------------------

def start_background_poll(loop_seconds: Optional[int] = None) -> None:
    """Fire-and-forget background polling using threading. Use if bot.py isn't async.
    Reads llm_enviroguard_poll_minutes from options.json when loop_seconds is None.
    """
    try:
        import threading
        if loop_seconds is None:
            opt = _read_options()
            mins = int(opt.get("llm_enviroguard_poll_minutes", 30))
            loop_seconds = max(60, mins * 60)
    except Exception:
        loop_seconds = 1800  # default 30 minutes

    def _runner():
        while True:
            try:
                enviroguard_tick()
            except Exception as e:
                try:
                    print(f"[enviroguard] tick error: {e}")
                except Exception:
                    pass
            time.sleep(loop_seconds)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()


if __name__ == "__main__":
    # Manual one-shot for testing
    enviroguard_tick()
    try:
        print(json.dumps(_read_state(), indent=2))
    except Exception:
        pass
