import os
import json
import requests
from datetime import datetime, timezone

# -----------------------------
# Load options/env
# -----------------------------
TECHNITIUM_ENABLED = False
TECHNITIUM_URL = ""
TECHNITIUM_API_KEY = ""

def _load_from_env():
    return (
        os.getenv("TECHNITIUM_ENABLED", "false").lower() in ("1","true","yes"),
        os.getenv("TECHNITIUM_URL", ""),
        os.getenv("TECHNITIUM_API_KEY", ""),
    )

def _load_from_options():
    try:
        with open("/data/options.json", "r") as f:
            opts = json.load(f)
    except Exception:
        opts = {}
    return (
        bool(opts.get("technitium_enabled", False)),
        str(opts.get("technitium_url", "")),
        str(opts.get("technitium_api_key", "")),
    )

try:
    TECHNITIUM_ENABLED, TECHNITIUM_URL, TECHNITIUM_API_KEY = _load_from_env()
    e_enabled, e_url, e_key = _load_from_options()
    # options.json overrides env (your standard)
    TECHNITIUM_ENABLED = e_enabled if e_url or e_key or "technitium_enabled" in locals() else TECHNITIUM_ENABLED
    if e_url: TECHNITIUM_URL = e_url
    if e_key: TECHNITIUM_API_KEY = e_key
except Exception:
    pass

# Normalize URL (no trailing slash)
TECHNITIUM_URL = (TECHNITIUM_URL or "").rstrip("/")

# -----------------------------
# HTTP helpers
# -----------------------------
def _get_json(url, timeout=8):
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def _kv(label, value):
    return f"    {label}: {value}"

# -----------------------------
# Stats fetch
# -----------------------------
def _fetch_stats():
    """
    Technitium DNS Server exposes a JSON stats API. Implementations vary slightly by version,
    so we try a small set of well-known candidates and normalize fields if found.
    """
    if not TECHNITIUM_ENABLED:
        return {"error": "Technitium not enabled"}
    if not TECHNITIUM_URL or not TECHNITIUM_API_KEY:
        return {"error": "Technitium URL/API key not configured"}

    # Candidate endpoints to maximize compatibility.
    candidates = [
        f"{TECHNITIUM_URL}/api/dns/stats?token={TECHNITIUM_API_KEY}",
        f"{TECHNITIUM_URL}/api/dns/stats?apiToken={TECHNITIUM_API_KEY}",
        f"{TECHNITIUM_URL}/api/stats?apiToken={TECHNITIUM_API_KEY}",
        f"{TECHNITIUM_URL}/api/statistics?apiToken={TECHNITIUM_API_KEY}",
    ]

    last_err = None
    for url in candidates:
        data = _get_json(url)
        if isinstance(data, dict) and "error" not in data:
            # Try common shapes; normalize
            total = (
                data.get("totalQueries")
                or data.get("queriesTotal")
                or data.get("total")
                or data.get("queryCount")
            )
            blocked = (
                data.get("blockedQueries")
                or data.get("queriesBlocked")
                or data.get("blocked")
            )
            cache = (
                data.get("cacheSize")
                or data.get("cacheEntries")
                or data.get("cache_count")
            )

            # Sometimes counts are nested
            if total is None and isinstance(data.get("totals"), dict):
                t = data["totals"]
                total = t.get("queries") or t.get("total")

            if blocked is None and isinstance(data.get("totals"), dict):
                t = data["totals"]
                blocked = t.get("blocked")

            if cache is None and isinstance(data.get("cache"), dict):
                c = data["cache"]
                cache = c.get("size") or c.get("entries")

            # If still None, leave as None (we'll render "?")
            return {
                "total": total,
                "blocked": blocked,
                "cache": cache,
                "source": url
            }
        else:
            last_err = data.get("error") if isinstance(data, dict) else "Unexpected response"
    return {"error": last_err or "Stats endpoint not found"}

# -----------------------------
# Public command
# -----------------------------
def dns_status():
    st = _fetch_stats()
    if "error" in st:
        return f"⚠️ Technitium error: {st['error']}", None

    total = st.get("total")
    blocked = st.get("blocked")
    cache = st.get("cache")

    # Compute allowed if we can
    allowed = None
    try:
        if total is not None and blocked is not None:
            allowed = int(total) - int(blocked)
    except Exception:
        allowed = None

    # Render compact, aligned, no tables
    lines = []
    lines.append(f"🧬 DNS — Technitium Status")
    lines.append(_kv("Total queries", total if total is not None else "?"))
    lines.append(_kv("Total blocked", blocked if blocked is not None else "?"))
    lines.append(_kv("Total allowed", allowed if allowed is not None else "?"))
    lines.append(_kv("Cache entries", cache if cache is not None else "?"))
    return "\n".join(lines), None

# -----------------------------
# Router (called by bot.py)
# -----------------------------
def handle_dns_command(cmd: str):
    """
    Accepts a lowercase command string that already had the wake word stripped.
    Intended usage with title starting with 'Jarvis'.
    Examples:
      'dns status'
    """
    c = (cmd or "").strip().lower()
    if not c:
        return None
    if c.startswith("dns status") or c == "dns" or c == "dnsstatus":
        return dns_status()
    return None
